from django.contrib import admin

from .models import Peer, WGInterface


@admin.register(WGInterface)
class WGInterfaceAdmin(admin.ModelAdmin):
    list_display = ("name", "listen_port", "address", "endpoint_host")
    readonly_fields = ("public_key", "created_at", "updated_at")


@admin.register(Peer)
class PeerAdmin(admin.ModelAdmin):
    list_display = ("name", "interface", "primary_ip", "enabled", "created_at")
    list_filter = ("interface", "enabled")
    search_fields = ("name", "public_key", "address")
    readonly_fields = ("created_at", "updated_at")
