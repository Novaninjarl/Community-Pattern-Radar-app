import csv
import secrets
import string

from django.conf import settings
from django.db import models
from django.http import HttpResponse
from django.shortcuts import get_object_or_404

from rest_framework import status
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response

from .models import (
    MainSpace,
    MainSpaceMembership,
    UploadBatch,
    IssueCluster,
    PatternTree,
    TreeVersion,
    UserSession,
)
from .serializers import (
    UploadBatchSerializer,
    ClusterSerializer,
    WeeklyReportSerializer,
    MainSpaceSerializer,
    PatternTreeSerializer,
    TreeVersionSerializer,
)
from .auth_utils import (
    bearer_token,
    create_user_session,
    ensure_workspace,
    get_request_user,
    login_user_session,
    require_user,
    user_payload,
)
from .services import (
    process_csv,
    process_pasted_text,
    process_sample_data,
    semantic_search,
    markdown_report,
    action_backlog_rows,
    issue_tree_payload,
    rebuild_issue_tree,
    update_cluster_status,
    create_pattern_tree,
    create_branch_version,
    create_workspace_copy_from_main,
    save_tree_version,
    push_version_to_main,
    tree_version_payload,
)


def parse_bool(value, default=False):
    if value is None:
        return default
    return str(value).lower() in {'true', '1', 'yes', 'y'}


@api_view(['POST'])
def register(request):
    try:
        user, token = create_user_session(
            username=request.data.get('username', ''),
            email=request.data.get('email', ''),
            password=request.data.get('password', ''),
            workspace_name=request.data.get('workspace_name', ''),
            account_type=request.data.get('account_type', 'normal'),
        )
    except ValueError as exc:
        return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    return Response(user_payload(user, token), status=status.HTTP_201_CREATED)


@api_view(['POST'])
def login(request):
    try:
        user, token = login_user_session(
            username=request.data.get('username', ''),
            password=request.data.get('password', ''),
        )
    except ValueError as exc:
        return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    return Response(user_payload(user, token))


@api_view(['GET'])
def me(request):
    user = get_request_user(request)
    if not user:
        return Response({'user': None})
    return Response({'user': user_payload(user)})


@api_view(['POST'])
def logout(request):
    token = bearer_token(request)
    if token:
        UserSession.objects.filter(token=token).delete()
    return Response({'ok': True})



def generate_join_code(prefix='MAIN'):
    alphabet = string.ascii_uppercase + string.digits
    while True:
        code = f'{prefix}-' + ''.join(secrets.choice(alphabet) for _ in range(8))
        if not MainSpace.objects.filter(join_code=code).exists():
            return code


def normalise_join_code(value):
    return (value or '').strip().upper()


def get_main_space_by_code(join_code):
    code = normalise_join_code(join_code)
    if not code:
        return None
    return get_object_or_404(MainSpace.objects.select_related('owner'), join_code=code)


def main_space_membership(user, main_space):
    if not user or not main_space:
        return None
    return MainSpaceMembership.objects.filter(user=user, main_space=main_space).first()


def user_is_main_admin(user, main_space):
    if not user or not main_space:
        return False
    if getattr(user, 'is_staff', False) or main_space.owner_id == user.id:
        return True
    membership = main_space_membership(user, main_space)
    return bool(membership and membership.role in {MainSpaceMembership.ROLE_OWNER, MainSpaceMembership.ROLE_ADMIN})


def user_is_main_member(user, main_space):
    if not user or not main_space:
        return False
    if user_is_main_admin(user, main_space):
        return True
    return MainSpaceMembership.objects.filter(user=user, main_space=main_space).exists()


def user_can_access_tree(user, tree):
    # Main/public trees are visible to anyone who has the join URL/code and can load the tree list for that main.
    if tree.is_public and tree.main_version_id:
        return True
    if not user:
        return False
    if tree.workspace_id and tree.workspace.user_id == user.id:
        return True
    return bool(tree.main_space_id and user_is_main_member(user, tree.main_space))


def user_can_edit_tree(user, tree):
    return bool(user and tree.workspace_id and tree.workspace.user_id == user.id)


def user_can_delete_tree(user, tree):
    if not user:
        return False

    # Normal users can delete their own private workspace trees.
    if tree.workspace_id and tree.workspace.user_id == user.id and not tree.is_public:
        return True

    # Main owners/admins can delete public main trees inside their main space.
    if tree.is_public and tree.main_space_id:
        return user_is_main_admin(user, tree.main_space)

    # Global admin fallback for legacy public trees without a main space.
    return bool(tree.is_public and getattr(user, 'is_staff', False))


def user_can_delete_version(user, version):
    return user_can_delete_tree(user, version.tree)


def require_editable_version(user, version_id):
    if not version_id:
        return None, None

    version = get_object_or_404(
        TreeVersion.objects.select_related('tree', 'tree__workspace', 'tree__main_space'),
        id=int(version_id),
    )

    if not user_can_edit_tree(user, version.tree):
        return None, Response(
            {'error': 'Only the workspace owner can import into this version.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    return version, None


@api_view(['GET'])
def health(_request):
    return Response({
        'status': 'ok',
        'app': 'Community Pattern Radar',
        'interpreter_mode': settings.INTERPRETER_MODE,
        'embedding_backend': settings.EMBEDDING_BACKEND,
    })



@api_view(['GET'])
def list_main_spaces(request):
    user = get_request_user(request)
    join_code = request.GET.get('join_code') or request.GET.get('code')

    if join_code:
        main_space = get_main_space_by_code(join_code)
        return Response(MainSpaceSerializer(main_space, context={'user': user}).data)

    if not user:
        return Response([])

    spaces = (
        MainSpace.objects
        .select_related('owner')
        .filter(models.Q(owner=user) | models.Q(memberships__user=user))
        .distinct()
        .order_by('-updated_at')
    )
    return Response(MainSpaceSerializer(spaces, many=True, context={'user': user}).data)


@api_view(['POST'])
def create_main_space(request):
    user, error_response = require_user(request)
    if error_response:
        return error_response

    name = (request.data.get('name') or '').strip()
    if not name:
        return Response({'error': 'Main name is required.'}, status=status.HTTP_400_BAD_REQUEST)

    main_space = MainSpace.objects.create(
        name=name,
        description=request.data.get('description', ''),
        join_code=generate_join_code(),
        owner=user,
        is_discoverable=parse_bool(request.data.get('is_discoverable'), default=False),
    )
    MainSpaceMembership.objects.create(
        main_space=main_space,
        user=user,
        role=MainSpaceMembership.ROLE_OWNER,
    )

    return Response(MainSpaceSerializer(main_space, context={'user': user}).data, status=status.HTTP_201_CREATED)


@api_view(['GET'])
def get_main_space(request, join_code):
    user = get_request_user(request)
    main_space = get_main_space_by_code(join_code)
    return Response(MainSpaceSerializer(main_space, context={'user': user}).data)


@api_view(['POST'])
def join_main_space(request, join_code):
    user, error_response = require_user(request)
    if error_response:
        return error_response

    main_space = get_main_space_by_code(join_code)
    MainSpaceMembership.objects.get_or_create(
        main_space=main_space,
        user=user,
        defaults={'role': MainSpaceMembership.ROLE_MEMBER},
    )
    return Response(MainSpaceSerializer(main_space, context={'user': user}).data)


@api_view(['DELETE'])
def delete_main_space(request, join_code):
    user, error_response = require_user(request)
    if error_response:
        return error_response

    main_space = get_main_space_by_code(join_code)
    if not user_is_main_admin(user, main_space):
        return Response({'error': 'Only the main owner/admin can delete this main.'}, status=status.HTTP_403_FORBIDDEN)

    name = main_space.name
    main_space.delete()
    return Response({'ok': True, 'deleted_main_space': name})


@api_view(['GET'])
def list_trees(request):
    user = get_request_user(request)
    main_code = request.GET.get('main_space') or request.GET.get('join_code') or request.GET.get('code')
    main_space = get_main_space_by_code(main_code) if main_code else None

    if not main_space:
        # No more global public main list: a main must be chosen by code/URL or membership.
        if not user:
            return Response([])
        joined_spaces = MainSpace.objects.filter(models.Q(owner=user) | models.Q(memberships__user=user)).distinct()
        trees = (
            PatternTree.objects
            .select_related('main_version', 'workspace', 'main_space')
            .filter(models.Q(main_space__in=joined_spaces) & (models.Q(is_public=True) | models.Q(workspace__user=user)))
            .distinct()
            .order_by('-updated_at')
        )
        return Response(PatternTreeSerializer(trees, many=True, context={'user': user}).data)

    public_main_trees = PatternTree.objects.filter(
        main_space=main_space,
        is_public=True,
        main_version__isnull=False,
    )

    if user:
        workspace = ensure_workspace(user)
        trees = (
            PatternTree.objects
            .select_related('main_version', 'workspace', 'main_space')
            .filter(
                models.Q(id__in=public_main_trees.values('id')) |
                models.Q(workspace=workspace, main_space=main_space)
            )
            .distinct()
            .order_by('-updated_at')
        )
    else:
        trees = (
            public_main_trees
            .select_related('main_version', 'workspace', 'main_space')
            .order_by('-updated_at')
        )

    return Response(PatternTreeSerializer(trees, many=True, context={'user': user}).data)


@api_view(['GET'])
def list_main_space_trees(request, join_code):
    user = get_request_user(request)
    main_space = get_main_space_by_code(join_code)

    public_main_trees = PatternTree.objects.filter(
        main_space=main_space,
        is_public=True,
        main_version__isnull=False,
    )

    if user:
        workspace = ensure_workspace(user)
        trees = (
            PatternTree.objects
            .select_related('main_version', 'workspace', 'main_space')
            .filter(
                models.Q(id__in=public_main_trees.values('id')) |
                models.Q(workspace=workspace, main_space=main_space)
            )
            .distinct()
            .order_by('-updated_at')
        )
    else:
        trees = (
            public_main_trees
            .select_related('main_version', 'workspace', 'main_space')
            .order_by('-updated_at')
        )

    return Response(PatternTreeSerializer(trees, many=True, context={'user': user}).data)



@api_view(['POST'])
def create_tree(request):
    user, error_response = require_user(request)
    if error_response:
        return error_response

    name = request.data.get('name', '').strip()
    if not name:
        return Response(
            {'error': 'Tree name is required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    main_code = request.data.get('main_space') or request.data.get('join_code') or request.data.get('main_space_code')
    main_space = get_main_space_by_code(main_code) if main_code else None
    create_as_main = parse_bool(request.data.get('is_public'), default=False) or parse_bool(request.data.get('as_main_tree'), default=False)

    if create_as_main and not main_space:
        return Response({'error': 'Choose a main before creating a main tree.'}, status=status.HTTP_400_BAD_REQUEST)

    if create_as_main and not user_is_main_admin(user, main_space):
        return Response({'error': 'Only the owner/admin of this main can create public main trees.'}, status=status.HTTP_403_FORBIDDEN)

    if main_space and not user_is_main_member(user, main_space):
        # If they have the code, creating a private workspace tree should also join them.
        MainSpaceMembership.objects.get_or_create(
            main_space=main_space,
            user=user,
            defaults={'role': MainSpaceMembership.ROLE_MEMBER},
        )

    workspace = ensure_workspace(user)
    version = create_pattern_tree(
        name=name,
        description=request.data.get('description', ''),
        created_by_name=request.data.get('created_by_name', user.username),
        version_name=request.data.get('version_name', 'Initial version'),
        workspace=workspace,
        main_space=main_space,
        is_public=create_as_main,
    )

    return Response(
        TreeVersionSerializer(version).data,
        status=status.HTTP_201_CREATED,
    )


@api_view(['DELETE'])
def delete_tree(request, tree_id):
    user, error_response = require_user(request)
    if error_response:
        return error_response

    tree = get_object_or_404(
        PatternTree.objects.select_related('workspace', 'main_space'),
        id=tree_id,
    )

    if not user_can_delete_tree(user, tree):
        return Response(
            {
                'error': (
                    'Only an admin can delete public main trees. '
                    'Normal users can only delete trees in their own workspace.'
                )
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    tree_name = tree.name
    tree.delete()

    return Response({
        'ok': True,
        'deleted_tree': tree_name,
    })


@api_view(['DELETE'])
def delete_my_workspace(request):
    user, error_response = require_user(request)
    if error_response:
        return error_response

    workspace = ensure_workspace(user)
    deleted_tree_count = workspace.trees.count()
    workspace_name = workspace.name

    workspace.delete()

    # Keep the account alive and create a fresh empty workspace immediately.
    fresh_workspace = ensure_workspace(user)

    return Response({
        'ok': True,
        'deleted_workspace': workspace_name,
        'deleted_tree_count': deleted_tree_count,
        'workspace': {
            'id': fresh_workspace.id,
            'name': fresh_workspace.name,
        },
    })


@api_view(['DELETE'])
def delete_tree_version(request, version_id):
    user, error_response = require_user(request)
    if error_response:
        return error_response

    version = get_object_or_404(
        TreeVersion.objects.select_related('tree', 'tree__workspace', 'tree__main_space'),
        id=version_id,
    )

    if not user_can_delete_version(user, version):
        return Response(
            {
                'error': (
                    'Only an admin can delete public main branches. '
                    'Normal users can only delete branches in their own workspace.'
                )
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    tree = version.tree

    if tree.versions.count() <= 1:
        return Response(
            {'error': 'This is the only version in the tree. Delete the tree instead.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    deleted_version_name = version.name

    if tree.main_version_id == version.id:
        replacement = (
            tree.versions
            .exclude(id=version.id)
            .order_by('-saved_at', '-created_at')
            .first()
        )
        tree.main_version = replacement
        tree.save(update_fields=['main_version', 'updated_at'])

    version.delete()

    return Response({
        'ok': True,
        'deleted_version': deleted_version_name,
        'tree_id': tree.id,
        'main_version': tree.main_version_id,
    })

@api_view(['GET'])
def list_tree_versions(request, tree_id):
    user = get_request_user(request)
    tree = get_object_or_404(PatternTree.objects.select_related('workspace', 'main_space'), id=tree_id)

    if not user_can_access_tree(user, tree):
        return Response({'error': 'You do not have access to this tree.'}, status=status.HTTP_403_FORBIDDEN)

    if user_can_edit_tree(user, tree):
        versions = tree.versions.all()
    else:
        versions = tree.versions.filter(id=tree.main_version_id)

    return Response(TreeVersionSerializer(versions, many=True).data)


@api_view(['GET'])
def get_tree_version(request, version_id):
    user = get_request_user(request)
    version = get_object_or_404(TreeVersion.objects.select_related('tree', 'tree__workspace', 'tree__main_space'), id=version_id)
    if not user_can_access_tree(user, version.tree):
        return Response({'error': 'You do not have access to this version.'}, status=status.HTTP_403_FORBIDDEN)
    if not user and version.tree.main_version_id != version.id:
        return Response({'error': 'Log in to view workspace branches.'}, status=status.HTTP_401_UNAUTHORIZED)
    return Response(tree_version_payload(version_id))


@api_view(['POST'])
def branch_tree_version(request, version_id):
    user, error_response = require_user(request)
    if error_response:
        return error_response

    source_version = get_object_or_404(TreeVersion.objects.select_related('tree', 'tree__workspace', 'tree__main_space'), id=version_id)

    if user_can_edit_tree(user, source_version.tree):
        version = create_branch_version(
            source_version_id=version_id,
            branch_name=request.data.get('branch_name', 'branch'),
            created_by_name=request.data.get('created_by_name', user.username),
            notes=request.data.get('notes', ''),
        )
    elif source_version.tree.is_public and source_version.tree.main_version_id == source_version.id:
        workspace = ensure_workspace(user)
        version = create_workspace_copy_from_main(
            source_version_id=version_id,
            workspace=workspace,
            branch_name=request.data.get('branch_name', 'workspace-copy'),
            created_by_name=request.data.get('created_by_name', user.username),
            notes=request.data.get('notes', ''),
        )
    else:
        return Response(
            {'error': 'You can only branch your own workspace versions or copy a public main version into your workspace.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    return Response(
        TreeVersionSerializer(version).data,
        status=status.HTTP_201_CREATED,
    )


@api_view(['POST'])
def save_version(request, version_id):
    user, error_response = require_user(request)
    if error_response:
        return error_response
    existing = get_object_or_404(TreeVersion.objects.select_related('tree', 'tree__workspace', 'tree__main_space'), id=version_id)
    if not user_can_edit_tree(user, existing.tree):
        return Response({'error': 'Only the workspace owner can save this version.'}, status=status.HTTP_403_FORBIDDEN)

    version = save_tree_version(
        version_id=version_id,
        name=request.data.get('name'),
        notes=request.data.get('notes', ''),
    )

    return Response(TreeVersionSerializer(version).data)


@api_view(['POST'])
def push_main(request, version_id):
    user, error_response = require_user(request)
    if error_response:
        return error_response
    existing = get_object_or_404(TreeVersion.objects.select_related('tree', 'tree__workspace', 'tree__main_space'), id=version_id)
    if not user_can_edit_tree(user, existing.tree):
        return Response({'error': 'Only the workspace owner can push this version to main.'}, status=status.HTTP_403_FORBIDDEN)

    if not existing.tree.main_space_id:
        return Response({'error': 'This tree is not linked to a main. Create or join a main, then create/copy a tree inside it before pushing.'}, status=status.HTTP_400_BAD_REQUEST)

    version = push_version_to_main(version_id)
    return Response(TreeVersionSerializer(version).data)


@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
def upload_csv(request):
    user, error_response = require_user(request)
    if error_response:
        return error_response

    file_obj = request.FILES.get('file')
    if not file_obj:
        return Response(
            {'error': 'Attach a CSV file as form field "file".'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        tree_version_id = request.data.get('tree_version_id') or None
        _version, permission_error = require_editable_version(user, tree_version_id)
        if permission_error:
            return permission_error
        merge_with_existing = parse_bool(
            request.data.get('merge_with_existing'),
            default=False,
        )

        batch = process_csv(
            file_obj,
            tree_version_id=int(tree_version_id) if tree_version_id else None,
            merge_with_existing=merge_with_existing,
        )
    except Exception as exc:
        return Response(
            {'error': str(exc)},
            status=status.HTTP_400_BAD_REQUEST,
        )

    return Response(
        UploadBatchSerializer(batch).data,
        status=status.HTTP_201_CREATED,
    )


@api_view(['POST'])
def import_paste(request):
    user, error_response = require_user(request)
    if error_response:
        return error_response

    raw_text = request.data.get('text', '')

    try:
        tree_version_id = request.data.get('tree_version_id') or None
        _version, permission_error = require_editable_version(user, tree_version_id)
        if permission_error:
            return permission_error
        merge_with_existing = parse_bool(
            request.data.get('merge_with_existing'),
            default=False,
        )

        batch = process_pasted_text(
            raw_text,
            tree_version_id=int(tree_version_id) if tree_version_id else None,
            merge_with_existing=merge_with_existing,
        )
    except Exception as exc:
        return Response(
            {'error': str(exc)},
            status=status.HTTP_400_BAD_REQUEST,
        )

    return Response(
        UploadBatchSerializer(batch).data,
        status=status.HTTP_201_CREATED,
    )


@api_view(['POST'])
def import_sample(request):
    user, error_response = require_user(request)
    if error_response:
        return error_response

    try:
        tree_version_id = request.data.get('tree_version_id') or None
        _version, permission_error = require_editable_version(user, tree_version_id)
        if permission_error:
            return permission_error
        merge_with_existing = parse_bool(
            request.data.get('merge_with_existing'),
            default=False,
        )

        batch = process_sample_data(
            tree_version_id=int(tree_version_id) if tree_version_id else None,
            merge_with_existing=merge_with_existing,
        )
    except Exception as exc:
        return Response(
            {'error': str(exc)},
            status=status.HTTP_400_BAD_REQUEST,
        )

    return Response(
        UploadBatchSerializer(batch).data,
        status=status.HTTP_201_CREATED,
    )


@api_view(['GET'])
def list_batches(_request):
    batches = UploadBatch.objects.order_by('-created_at')[:20]
    return Response(UploadBatchSerializer(batches, many=True).data)


@api_view(['GET'])
def dashboard(_request, batch_id):
    batch = get_object_or_404(UploadBatch, id=batch_id)
    clusters = IssueCluster.objects.filter(batch=batch).order_by('-priority_score')
    report = getattr(batch, 'weekly_report', None)

    return Response({
        'batch': UploadBatchSerializer(batch).data,
        'clusters': ClusterSerializer(clusters, many=True).data,
        'tree': issue_tree_payload(batch_id),
        'weekly_report': WeeklyReportSerializer(report).data if report else None,
    })


@api_view(['GET'])
def tree(_request, batch_id):
    return Response(issue_tree_payload(batch_id))


@api_view(['PATCH'])
def update_node_status(request, batch_id, cluster_id):
    user, error_response = require_user(request)
    if error_response:
        return error_response

    batch = get_object_or_404(UploadBatch.objects.select_related('tree_version__tree__workspace'), id=batch_id)
    if batch.tree_version and not user_can_edit_tree(user, batch.tree_version.tree):
        return Response({'error': 'Only the workspace owner can update this node.'}, status=status.HTTP_403_FORBIDDEN)
    cluster = get_object_or_404(IssueCluster, id=cluster_id, batch_id=batch_id)

    try:
        updated = update_cluster_status(
            cluster.id,
            request.data.get('status', cluster.status),
            request.data.get('progress_note', cluster.progress_note),
        )
    except Exception as exc:
        return Response(
            {'error': str(exc)},
            status=status.HTTP_400_BAD_REQUEST,
        )

    return Response(ClusterSerializer(updated).data)


@api_view(['POST'])
def remodel_tree(request, batch_id):
    user, error_response = require_user(request)
    if error_response:
        return error_response

    batch = get_object_or_404(UploadBatch.objects.select_related('tree_version__tree__workspace'), id=batch_id)
    if batch.tree_version and not user_can_edit_tree(user, batch.tree_version.tree):
        return Response({'error': 'Only the workspace owner can remodel this tree.'}, status=status.HTTP_403_FORBIDDEN)

    remove_completed = parse_bool(
        request.data.get('remove_completed'),
        default=True,
    )
    keep_legacy = parse_bool(
        request.data.get('keep_legacy'),
        default=False,
    )

    return Response(
        rebuild_issue_tree(
            batch_id,
            remove_completed=remove_completed,
            keep_legacy=keep_legacy,
        )
    )


@api_view(['GET'])
def search(request, batch_id):
    query = request.GET.get('q', '').strip()
    if not query:
        return Response({'results': []})

    return Response({
        'query': query,
        'results': semantic_search(batch_id, query),
    })


@api_view(['GET'])
def export_clusters(_request, batch_id):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = (
        f'attachment; filename="community-pattern-radar-batch-{batch_id}.csv"'
    )

    writer = csv.writer(response)
    writer.writerow([
        'theme',
        'category',
        'severity',
        'priority_score',
        'status',
        'post_count',
        'suggested_action',
        'examples',
    ])

    for cluster in IssueCluster.objects.filter(batch_id=batch_id).order_by('-priority_score'):
        writer.writerow([
            cluster.theme,
            cluster.category,
            cluster.severity,
            cluster.priority_score,
            cluster.status,
            cluster.post_count,
            cluster.suggested_action,
            ' | '.join(cluster.examples),
        ])

    return response


@api_view(['GET'])
def export_markdown(_request, batch_id):
    response = HttpResponse(
        markdown_report(batch_id),
        content_type='text/markdown',
    )
    response['Content-Disposition'] = (
        f'attachment; filename="community-pattern-radar-report-{batch_id}.md"'
    )
    return response


@api_view(['GET'])
def export_actions(_request, batch_id):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = (
        f'attachment; filename="community-pattern-radar-actions-{batch_id}.csv"'
    )

    writer = csv.DictWriter(
        response,
        fieldnames=[
            'issue',
            'owner',
            'priority',
            'priority_score',
            'status',
            'action',
            'evidence_count',
            'examples',
        ],
    )
    writer.writeheader()
    writer.writerows(action_backlog_rows(batch_id))

    return response