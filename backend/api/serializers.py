from rest_framework import serializers

from .models import (
    Workspace,
    MainSpace,
    MainSpaceMembership,
    PatternTree,
    TreeVersion,
    UploadBatch,
    CommunityPost,
    IssueCluster,
    WeeklyReport,
)


class WorkspaceSerializer(serializers.ModelSerializer):
    user_username = serializers.CharField(source='user.username', read_only=True)

    class Meta:
        model = Workspace
        fields = '__all__'


class MainSpaceSerializer(serializers.ModelSerializer):
    owner_username = serializers.CharField(source='owner.username', read_only=True)
    member_count = serializers.SerializerMethodField()
    current_user_role = serializers.SerializerMethodField()
    can_admin = serializers.SerializerMethodField()
    share_url = serializers.SerializerMethodField()

    class Meta:
        model = MainSpace
        fields = [
            'id',
            'name',
            'description',
            'join_code',
            'owner',
            'owner_username',
            'is_discoverable',
            'created_at',
            'updated_at',
            'member_count',
            'current_user_role',
            'can_admin',
            'share_url',
        ]

    def get_member_count(self, obj):
        return obj.memberships.count()

    def get_current_user_role(self, obj):
        user = self.context.get('user') if self.context else None
        if not user:
            return None
        membership = obj.memberships.filter(user=user).first()
        return membership.role if membership else None

    def get_can_admin(self, obj):
        user = self.context.get('user') if self.context else None
        if not user:
            return False
        if getattr(user, 'is_staff', False) or obj.owner_id == user.id:
            return True
        return obj.memberships.filter(user=user, role__in=['owner', 'admin']).exists()

    def get_share_url(self, obj):
        return f'/main/{obj.join_code}'


class MainSpaceMembershipSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    main_space_name = serializers.CharField(source='main_space.name', read_only=True)

    class Meta:
        model = MainSpaceMembership
        fields = '__all__'


class PatternTreeSerializer(serializers.ModelSerializer):
    main_version_name = serializers.SerializerMethodField()
    version_count = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()
    scope = serializers.SerializerMethodField()
    main_space_name = serializers.CharField(source='main_space.name', read_only=True)
    main_space_code = serializers.CharField(source='main_space.join_code', read_only=True)

    class Meta:
        model = PatternTree
        fields = '__all__'

    def get_main_version_name(self, obj):
        return obj.main_version.name if obj.main_version else None

    def get_version_count(self, obj):
        return obj.versions.count()

    def get_can_edit(self, obj):
        user = self.context.get('user') if self.context else None
        return bool(user and obj.workspace and obj.workspace.user_id == user.id)

    def get_can_delete(self, obj):
        user = self.context.get('user') if self.context else None
        if not user:
            return False
        owns_tree = bool(obj.workspace and obj.workspace.user_id == user.id)
        can_admin_main = False
        if obj.main_space_id:
            can_admin_main = (
                bool(getattr(user, 'is_staff', False))
                or obj.main_space.owner_id == user.id
                or obj.main_space.memberships.filter(user=user, role__in=['owner', 'admin']).exists()
            )
        return owns_tree or (obj.is_public and can_admin_main)

    def get_scope(self, obj):
        user = self.context.get('user') if self.context else None

        if user and obj.workspace and obj.workspace.user_id == user.id and not obj.is_public:
            return 'workspace'

        if obj.is_public:
            return 'main'

        return 'private'


class TreeVersionSerializer(serializers.ModelSerializer):
    tree_name = serializers.CharField(source='tree.name', read_only=True)
    tree_scope = serializers.SerializerMethodField()
    parent_version_name = serializers.CharField(
        source='parent_version.name',
        read_only=True,
    )
    main_space = serializers.IntegerField(source='tree.main_space_id', read_only=True)
    main_space_code = serializers.CharField(source='tree.main_space.join_code', read_only=True)

    class Meta:
        model = TreeVersion
        fields = '__all__'

    def get_tree_scope(self, obj):
        if obj.tree and obj.tree.is_public:
            return 'main'
        return 'workspace'


class UploadBatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = UploadBatch
        fields = [
            'id',
            'filename',
            'created_at',
            'total_posts',
            'status',
            'column_map',
            'tree_version',
        ]


class PostSerializer(serializers.ModelSerializer):
    class Meta:
        model = CommunityPost
        exclude = ['embedding']


class ClusterSerializer(serializers.ModelSerializer):
    assigned_to_username = serializers.CharField(source='assigned_to.username', read_only=True)

    class Meta:
        model = IssueCluster
        fields = '__all__'


class WeeklyReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = WeeklyReport
        fields = '__all__'
