from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("api/stats/", views.stats_json, name="stats_json"),

    # Peers
    path("peers/new/", views.peer_create, name="peer_create"),
    path("peers/<int:pk>/", views.peer_detail, name="peer_detail"),
    path("peers/<int:pk>/edit/", views.peer_edit, name="peer_edit"),
    path("peers/<int:pk>/delete/", views.peer_delete, name="peer_delete"),
    path("peers/<int:pk>/toggle/", views.peer_toggle, name="peer_toggle"),
    path("peers/<int:pk>/regen-keys/", views.peer_regen_keys, name="peer_regen_keys"),
    path("peers/<int:pk>/config/", views.peer_config_download, name="peer_config_download"),
    path("peers/<int:pk>/qr/", views.peer_qr, name="peer_qr"),

    # Interface settings & service actions
    path("settings/", views.interface_settings, name="interface_settings"),
    path("settings/config/", views.server_config_download, name="server_config_download"),
    path("actions/restart/", views.action_restart, name="action_restart"),
    path("actions/sync/", views.action_sync, name="action_sync"),
    path("actions/up/", views.action_up, name="action_up"),
    path("actions/down/", views.action_down, name="action_down"),
    path("actions/import/", views.action_import, name="action_import"),
]
