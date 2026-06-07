from django.conf import settings
from django.db import models


class UserSession(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='api_sessions',
    )
    token = models.CharField(max_length=96, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Session for {self.user.username}'



class Workspace(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='workspace',
    )
    name = models.CharField(max_length=120, default='Default workspace')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name




class MainSpace(models.Model):
    name = models.CharField(max_length=180)
    description = models.TextField(blank=True, default='')
    join_code = models.CharField(max_length=32, unique=True, db_index=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='owned_main_spaces',
    )
    is_discoverable = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f'{self.name} ({self.join_code})'


class MainSpaceMembership(models.Model):
    ROLE_OWNER = 'owner'
    ROLE_ADMIN = 'admin'
    ROLE_MEMBER = 'member'

    ROLE_CHOICES = [
        (ROLE_OWNER, 'Owner'),
        (ROLE_ADMIN, 'Admin'),
        (ROLE_MEMBER, 'Member'),
    ]

    main_space = models.ForeignKey(
        MainSpace,
        on_delete=models.CASCADE,
        related_name='memberships',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='main_space_memberships',
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_MEMBER)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('main_space', 'user')
        ordering = ['main_space_id', 'role', 'user_id']

    def __str__(self):
        return f'{self.user} in {self.main_space} as {self.role}'


class PatternTree(models.Model):
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name='trees',
    )
    main_space = models.ForeignKey(
        MainSpace,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='trees',
        help_text='Shared main/project space this tree belongs to. Workspace copies keep the same main_space.',
    )
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True, default='')
    created_by_name = models.CharField(max_length=120, blank=True, default='')
    is_public = models.BooleanField(default=True)

    main_version = models.ForeignKey(
        'TreeVersion',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return self.name


class TreeVersion(models.Model):
    STATUS_DRAFT = 'draft'
    STATUS_SAVED = 'saved'
    STATUS_MAIN = 'main'
    STATUS_ARCHIVED = 'archived'

    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_SAVED, 'Saved'),
        (STATUS_MAIN, 'Main'),
        (STATUS_ARCHIVED, 'Archived'),
    ]

    tree = models.ForeignKey(
        PatternTree,
        on_delete=models.CASCADE,
        related_name='versions',
    )
    name = models.CharField(max_length=160)
    branch_name = models.CharField(max_length=120, default='main')
    created_by_name = models.CharField(max_length=120, blank=True, default='')

    parent_version = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='child_versions',
    )

    status = models.CharField(
        max_length=24,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
    )
    notes = models.TextField(blank=True, default='')

    snapshot = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    saved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.tree.name} / {self.name}'


class UploadBatch(models.Model):
    filename = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    total_posts = models.IntegerField(default=0)
    status = models.CharField(max_length=32, default='processing')
    column_map = models.JSONField(default=dict, blank=True)

    tree_version = models.ForeignKey(
        TreeVersion,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='batches',
    )

    def __str__(self):
        return f'{self.filename} ({self.total_posts})'


class CommunityPost(models.Model):
    batch = models.ForeignKey(
        UploadBatch,
        on_delete=models.CASCADE,
        related_name='posts',
    )
    text = models.TextField()
    cleaned_text = models.TextField()

    created_at_raw = models.CharField(max_length=128, blank=True, default='')
    user_id = models.CharField(max_length=255, blank=True, default='')
    channel = models.CharField(max_length=255, blank=True, default='')
    post_url = models.URLField(blank=True, default='')

    report_count = models.IntegerField(default=0)
    upvotes = models.IntegerField(default=0)
    moderation_status = models.CharField(max_length=128, blank=True, default='')

    embedding = models.JSONField(default=list, blank=True)
    cluster_label = models.IntegerField(default=-1)

    created_at = models.DateTimeField(auto_now_add=True)


class IssueCluster(models.Model):
    STATUS_UNTOUCHED = 'untouched'
    STATUS_NEEDS_REVIEW = 'needs_review'
    STATUS_CONFIRMED = 'confirmed'
    STATUS_PLANNED = 'planned'
    STATUS_IN_PROGRESS = 'in_progress'
    STATUS_PARTIALLY_RESOLVED = 'partially_resolved'
    STATUS_COMPLETED = 'completed'
    STATUS_BLOCKED = 'blocked'
    STATUS_WONT_FIX = 'wont_fix'
    STATUS_NOT_AFFECTED = 'not_affected'
    STATUS_LEGACY = 'legacy'

    STATUS_CHOICES = [
        (STATUS_UNTOUCHED, 'Untouched'),
        (STATUS_NEEDS_REVIEW, 'Needs review'),
        (STATUS_CONFIRMED, 'Confirmed'),
        (STATUS_PLANNED, 'Planned'),
        (STATUS_IN_PROGRESS, 'In progress'),
        (STATUS_PARTIALLY_RESOLVED, 'Partially resolved'),
        (STATUS_COMPLETED, 'Resolved'),
        (STATUS_BLOCKED, 'Blocked'),
        (STATUS_WONT_FIX, "Won't fix"),
        (STATUS_NOT_AFFECTED, 'Not affected'),
        (STATUS_LEGACY, 'Legacy'),
    ]

    STATUS_SOURCE_MANUAL = 'manual'
    STATUS_SOURCE_PROPAGATED = 'propagated'
    STATUS_SOURCE_SYSTEM = 'system'

    STATUS_SOURCE_CHOICES = [
        (STATUS_SOURCE_MANUAL, 'Manual'),
        (STATUS_SOURCE_PROPAGATED, 'Propagated'),
        (STATUS_SOURCE_SYSTEM, 'System'),
    ]

    batch = models.ForeignKey(
        UploadBatch,
        on_delete=models.CASCADE,
        related_name='clusters',
    )
    source_version = models.ForeignKey(
        TreeVersion,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='clusters',
    )

    label = models.IntegerField()
    theme = models.CharField(max_length=255)
    category = models.CharField(max_length=100)
    severity = models.CharField(max_length=32)
    priority_score = models.FloatField(default=0)
    suggested_action = models.TextField()

    post_count = models.IntegerField(default=0)
    examples = models.JSONField(default=list, blank=True)

    status = models.CharField(
        max_length=32,
        choices=STATUS_CHOICES,
        default=STATUS_UNTOUCHED,
    )
    progress_note = models.TextField(blank=True, default='')
    status_source = models.CharField(
        max_length=24,
        choices=STATUS_SOURCE_CHOICES,
        default=STATUS_SOURCE_MANUAL,
    )
    status_confidence = models.FloatField(default=1.0)
    status_source_cluster = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='propagated_status_targets',
    )
    status_reason = models.TextField(blank=True, default='')
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='assigned_issue_clusters',
    )
    completed_at = models.DateTimeField(null=True, blank=True)

    parent_cluster = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='children',
    )
    relationship_type = models.CharField(max_length=64, blank=True, default='')
    relationship_score = models.FloatField(default=0)
    relationship_reason = models.TextField(blank=True, default='')

    tree_depth = models.IntegerField(default=0)
    tree_order = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)


class WeeklyReport(models.Model):
    batch = models.OneToOneField(
        UploadBatch,
        on_delete=models.CASCADE,
        related_name='weekly_report',
    )
    summary = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)