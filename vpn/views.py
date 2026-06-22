import io
import time

import qrcode
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import InterfaceForm, PeerCreateForm, PeerEditForm
from .models import Peer
from .services import config_render, manager
from .services.backends import WGError

ONLINE_WINDOW = 180  # seconds since last handshake to count a peer as online


def _serialize_stat(stat):
    """Turn a PeerStat (or None) into a JSON-friendly dict."""
    if stat is None:
        return {"online": False, "handshake_ago": None, "rx": 0, "tx": 0, "endpoint": ""}
    ago = None
    online = False
    if stat.latest_handshake:
        ago = max(0, int(time.time()) - stat.latest_handshake)
        online = ago <= ONLINE_WINDOW
    return {
        "online": online,
        "handshake_ago": ago,
        "rx": stat.rx_bytes,
        "tx": stat.tx_bytes,
        "endpoint": stat.endpoint,
    }


def _apply(request, interface):
    """Push the DB state to WireGuard, reporting failures as warnings."""
    try:
        manager.apply_config(interface)
        return True
    except WGError as exc:
        messages.warning(
            request,
            f"Saved, but applying it live failed: {exc}. "
            "Bring the interface up or restart the service to apply.",
        )
        return False


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@login_required
def dashboard(request):
    interface = manager.get_interface()
    manager.ensure_server_keys(interface)
    status, rows, backend_error = manager.build_dashboard(interface)

    if backend_error:
        messages.error(request, f"WireGuard backend error: {backend_error}")

    peer_rows = [
        {"peer": r["peer"], "stat": r["stat"], "live": _serialize_stat(r["stat"])}
        for r in rows
    ]
    online = sum(1 for r in peer_rows if r["live"]["online"])

    return render(
        request,
        "vpn/dashboard.html",
        {
            "interface": interface,
            "status": status,
            "peer_rows": peer_rows,
            "online_count": online,
            "total_count": len(peer_rows),
        },
    )


@login_required
def stats_json(request):
    interface = manager.get_interface()
    status, rows, backend_error = manager.build_dashboard(interface)
    peers = {
        r["peer"].public_key: _serialize_stat(r["stat"]) for r in rows
    }
    online = sum(1 for p in peers.values() if p["online"])
    return JsonResponse(
        {
            "active": status.active,
            "error": backend_error,
            "online_count": online,
            "total_count": len(peers),
            "peers": peers,
        }
    )


# ---------------------------------------------------------------------------
# Peers
# ---------------------------------------------------------------------------
@login_required
def peer_create(request):
    interface = manager.get_interface()
    manager.ensure_server_keys(interface)

    if request.method == "POST":
        form = PeerCreateForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            try:
                peer = manager.create_peer(
                    interface,
                    name=cd["name"],
                    address=cd["address"] or None,
                    use_preshared_key=cd["use_preshared_key"],
                    client_dns=cd["client_dns"],
                    client_allowed_ips=cd["client_allowed_ips"],
                    persistent_keepalive=cd["persistent_keepalive"],
                    notes=cd["notes"],
                )
            except ValueError as exc:
                messages.error(request, str(exc))
            else:
                _apply(request, interface)
                messages.success(request, f"Peer “{peer.name}” created.")
                return redirect("peer_detail", pk=peer.pk)
    else:
        # Preview the address that would be auto-assigned.
        suggested = ""
        try:
            from .services.ip_alloc import next_free_address

            suggested = next_free_address(interface)
        except ValueError:
            pass
        form = PeerCreateForm()
        if suggested:
            form.fields["address"].help_text = (
                f"Leave blank to auto-assign (next free: {suggested})."
            )

    return render(request, "vpn/peer_form.html", {"form": form, "interface": interface})


@login_required
def peer_detail(request, pk):
    peer = get_object_or_404(Peer, pk=pk)
    client_config = config_render.render_client_config(peer)
    return render(
        request,
        "vpn/peer_detail.html",
        {
            "peer": peer,
            "interface": peer.interface,
            "client_config": client_config,
        },
    )


@login_required
def peer_edit(request, pk):
    peer = get_object_or_404(Peer, pk=pk)
    if request.method == "POST":
        form = PeerEditForm(request.POST, instance=peer)
        if form.is_valid():
            form.save()
            _apply(request, peer.interface)
            messages.success(request, "Peer updated.")
            return redirect("peer_detail", pk=peer.pk)
    else:
        form = PeerEditForm(instance=peer)
    return render(
        request,
        "vpn/peer_form.html",
        {"form": form, "interface": peer.interface, "peer": peer, "editing": True},
    )


@login_required
@require_POST
def peer_delete(request, pk):
    peer = get_object_or_404(Peer, pk=pk)
    name = peer.name
    interface = peer.interface
    manager.delete_peer(peer)
    _apply(request, interface)
    messages.success(request, f"Peer “{name}” deleted.")
    return redirect("dashboard")


@login_required
@require_POST
def peer_toggle(request, pk):
    peer = get_object_or_404(Peer, pk=pk)
    peer.enabled = not peer.enabled
    peer.save(update_fields=["enabled", "updated_at"])
    _apply(request, peer.interface)
    state = "enabled" if peer.enabled else "disabled"
    messages.success(request, f"Peer “{peer.name}” {state}.")
    return redirect(request.POST.get("next") or "peer_detail", pk=peer.pk)


@login_required
@require_POST
def peer_regen_keys(request, pk):
    peer = get_object_or_404(Peer, pk=pk)
    manager.regenerate_peer_keys(peer)
    _apply(request, peer.interface)
    messages.success(
        request,
        f"New keys generated for “{peer.name}”. The client must use the new config.",
    )
    return redirect("peer_detail", pk=peer.pk)


@login_required
def peer_config_download(request, pk):
    peer = get_object_or_404(Peer, pk=pk)
    text = config_render.render_client_config(peer)
    filename = _safe_filename(peer.name) + ".conf"
    response = HttpResponse(text, content_type="text/plain")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
def peer_qr(request, pk):
    peer = get_object_or_404(Peer, pk=pk)
    if not peer.has_private_key:
        raise Http404("No private key available to build a client QR code.")
    text = config_render.render_client_config(peer)
    img = qrcode.make(text)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return HttpResponse(buf.getvalue(), content_type="image/png")


# ---------------------------------------------------------------------------
# Interface settings & service actions
# ---------------------------------------------------------------------------
@login_required
def interface_settings(request):
    interface = manager.get_interface()
    manager.ensure_server_keys(interface)
    if request.method == "POST":
        form = InterfaceForm(request.POST, instance=interface)
        if form.is_valid():
            form.save()
            _apply(request, interface)
            messages.success(request, "Interface settings saved.")
            return redirect("interface_settings")
    else:
        form = InterfaceForm(instance=interface)

    server_config = config_render.render_server_config(interface)
    return render(
        request,
        "vpn/settings.html",
        {"form": form, "interface": interface, "server_config": server_config},
    )


@login_required
def server_config_download(request):
    interface = manager.get_interface()
    text = config_render.render_server_config(interface)
    response = HttpResponse(text, content_type="text/plain")
    response["Content-Disposition"] = f'attachment; filename="{interface.name}.conf"'
    return response


@login_required
@require_POST
def action_restart(request):
    interface = manager.get_interface()
    backend = manager.get_backend_instance()
    try:
        backend.restart()
        messages.success(request, f"Service wg-quick@{interface.name} restarted.")
    except WGError as exc:
        messages.error(request, f"Restart failed: {exc}")
    return redirect("dashboard")


@login_required
@require_POST
def action_sync(request):
    interface = manager.get_interface()
    if _apply(request, interface):
        messages.success(request, "Configuration re-applied from the database.")
    return redirect("dashboard")


@login_required
@require_POST
def action_up(request):
    backend = manager.get_backend_instance()
    try:
        backend.up()
        messages.success(request, "Interface brought up.")
    except WGError as exc:
        messages.error(request, f"Could not bring the interface up: {exc}")
    return redirect("dashboard")


@login_required
@require_POST
def action_down(request):
    backend = manager.get_backend_instance()
    try:
        backend.down()
        messages.success(request, "Interface brought down.")
    except WGError as exc:
        messages.error(request, f"Could not bring the interface down: {exc}")
    return redirect("dashboard")


@login_required
@require_POST
def action_import(request):
    interface = manager.get_interface()
    try:
        summary = manager.import_running_config(interface)
    except WGError as exc:
        messages.error(request, f"Import failed: {exc}")
    else:
        messages.success(
            request,
            "Imported from the running config: "
            f"{summary['created']} new peer(s), {summary['updated']} updated"
            + (", interface settings updated." if summary["interface_updated"] else "."),
        )
    return redirect("dashboard")


def _safe_filename(name: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in "-_" else "-" for c in name).strip("-")
    return cleaned or "client"
