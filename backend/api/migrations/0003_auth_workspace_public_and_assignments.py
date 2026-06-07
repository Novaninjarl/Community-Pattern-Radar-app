# Generated manually for workspace login/public main flow.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('api', '0002_patterntree_workspace_treeversion_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='UserSession',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('token', models.CharField(max_length=96, unique=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('last_used_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='api_sessions', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddField(
            model_name='workspace',
            name='user',
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='workspace', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='patterntree',
            name='is_public',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='issuecluster',
            name='assigned_to',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='assigned_issue_clusters', to=settings.AUTH_USER_MODEL),
        ),
    ]
