from django.urls import path

from . import views

urlpatterns = [
    path('health/', views.health),

    path('auth/register/', views.register),
    path('auth/login/', views.login),
    path('auth/me/', views.me),
    path('auth/logout/', views.logout),

    path('main-spaces/', views.list_main_spaces),
    path('main-spaces/create/', views.create_main_space),
    path('main-spaces/<str:join_code>/', views.get_main_space),
    path('main-spaces/<str:join_code>/join/', views.join_main_space),
    path('main-spaces/<str:join_code>/delete/', views.delete_main_space),
    path('main-spaces/<str:join_code>/trees/', views.list_main_space_trees),

    path('trees/', views.list_trees),
    path('trees/create/', views.create_tree),
    path('trees/<int:tree_id>/delete/', views.delete_tree),
    path('trees/<int:tree_id>/versions/', views.list_tree_versions),
    path('workspace/delete/', views.delete_my_workspace),

    path('tree-versions/<int:version_id>/', views.get_tree_version),
    path('tree-versions/<int:version_id>/branch/', views.branch_tree_version),
    path('tree-versions/<int:version_id>/delete/', views.delete_tree_version),
    path('tree-versions/<int:version_id>/save/', views.save_version),
    path('tree-versions/<int:version_id>/push-main/', views.push_main),

    path('uploads/', views.list_batches),
    path('upload/', views.upload_csv),
    path('import/paste/', views.import_paste),
    path('import/sample/', views.import_sample),

    path('batches/<int:batch_id>/dashboard/', views.dashboard),
    path('batches/<int:batch_id>/tree/', views.tree),
    path('batches/<int:batch_id>/tree/remodel/', views.remodel_tree),
    path(
        'batches/<int:batch_id>/tree/nodes/<int:cluster_id>/status/',
        views.update_node_status,
    ),

    path('batches/<int:batch_id>/search/', views.search),

    path('batches/<int:batch_id>/export/', views.export_clusters),
    path('batches/<int:batch_id>/export/markdown/', views.export_markdown),
    path('batches/<int:batch_id>/export/actions/', views.export_actions),
]
