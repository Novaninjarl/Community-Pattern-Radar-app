import secrets

from django.contrib.auth import authenticate, get_user_model
from django.db import transaction
from rest_framework import status
from rest_framework.response import Response

from .models import MainSpace, MainSpaceMembership, UserSession, Workspace


def bearer_token(request):
    header = request.headers.get('Authorization', '')
    if not header.lower().startswith('bearer '):
        return ''
    return header.split(' ', 1)[1].strip()


def get_request_user(request):
    token = bearer_token(request)
    if not token:
        return None

    session = (
        UserSession.objects
        .select_related('user')
        .filter(token=token)
        .first()
    )

    return session.user if session else None


def require_user(request):
    user = get_request_user(request)
    if user:
        return user, None
    return None, Response(
        {'error': 'Log in to use this workspace action.'},
        status=status.HTTP_401_UNAUTHORIZED,
    )


def user_payload(user, token=None):
    workspace = ensure_workspace(user)
    role = 'admin' if user.is_staff else 'normal'
    memberships = (
        MainSpaceMembership.objects
        .select_related('main_space')
        .filter(user=user)
        .order_by('main_space__name')
    )
    payload = {
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'role': role,
        'is_admin': user.is_staff,
        'workspace': {
            'id': workspace.id,
            'name': workspace.name,
        },
        'main_spaces': [
            {
                'id': membership.main_space_id,
                'name': membership.main_space.name,
                'join_code': membership.main_space.join_code,
                'role': membership.role,
            }
            for membership in memberships
        ],
    }
    if token:
        payload['token'] = token
    return payload


def ensure_workspace(user):
    workspace, _ = Workspace.objects.get_or_create(
        user=user,
        defaults={'name': f'{user.username} workspace'},
    )
    return workspace


@transaction.atomic
def create_user_session(username, email, password, workspace_name='', account_type='normal'):
    User = get_user_model()
    username = (username or '').strip()
    email = (email or '').strip()

    if not username:
        raise ValueError('Username is required.')
    if not password or len(password) < 6:
        raise ValueError('Password must be at least 6 characters.')
    if User.objects.filter(username__iexact=username).exists():
        raise ValueError('That username is already taken.')

    account_type = (account_type or 'normal').strip().lower()
    is_admin = account_type == 'admin'

    user = User.objects.create_user(
        username=username,
        email=email,
        password=password,
        is_staff=is_admin,
    )
    workspace = ensure_workspace(user)
    if workspace_name.strip():
        workspace.name = workspace_name.strip()
        workspace.save(update_fields=['name'])

    token = secrets.token_urlsafe(48)
    UserSession.objects.create(user=user, token=token)
    return user, token


def login_user_session(username, password):
    user = authenticate(username=(username or '').strip(), password=password or '')
    if not user:
        raise ValueError('Invalid username or password.')

    token = secrets.token_urlsafe(48)
    UserSession.objects.create(user=user, token=token)
    return user, token
