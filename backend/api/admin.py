from django.contrib import admin
from .models import UploadBatch, CommunityPost, IssueCluster, WeeklyReport
admin.site.register([UploadBatch, CommunityPost, IssueCluster, WeeklyReport])
