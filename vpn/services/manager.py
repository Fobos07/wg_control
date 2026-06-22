"""High-level orchestration: the bridge between views, the DB and WireGuard."""
from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction

from ..models import Peer, WGInterface
from . import config_parse, config_render, ip_alloc, wg_keys
from .backends import InterfaceStatus, WGError, get_backend

logger = logging.getLogger("vpn")


def get_backend_instance():
    return get_backend()


def get_interface() -> WGInterface:
    """Return the managed interface, creating a default row on first run."""
    name = settings.WG["INTERFACE"]
    interface, created = WGInterface.objects.get_or_create(name=name)
    if created:
        logger.info("Created default interface row for %s", name)
    return interface


def ensure_server_keys(interface: WGInterface) -> None:
    if not interface.private_key:
        priv, pub = wg_keys.generate_keypair()
        interface.private_key = priv
        interface.public_key = pub
        interface.save(update_fields=["private_key", "public_key", "updated_at"])
    elif not interface.public_key:
        interface.public_key = wg_keys.public_key_from_private(interface.private_key)
        interface.save(update_fields=["public_key", "updated_at"])


def apply_config(interface: WGInterface) -> None:
    """Render the server config from the DB, write it, and apply it live.

    Writing the file always succeeds first so the DB and on-disk config stay in
    step; the live `syncconf` may raise WGError if the interface is down, which
    the caller surfaces to the user.
    """
    backend = get_backend()
    text = config_render.render_server_config(interface)
    backend.write_config(text)
    backend.sync()


@transaction.atomic
def create_peer(
    interface: WGInterface,
    *,
    name: str,
    address: str | None = None,
    use_preshared_key: bool = True,
    client_dns: str = "",
    client_allowed_ips: str = "",
    persistent_keepalive=None,
    notes: str = "",
) -> Peer:
    ensure_server_keys(interface)
    priv, pub = wg_keys.generate_keypair()
    psk = wg_keys.generate_preshared_key() if use_preshared_key else ""
    if not address:
        address = ip_alloc.next_free_address(interface)

    peer = Peer.objects.create(
        interface=interface,
        name=name,
        public_key=pub,
        private_key=priv,
        preshared_key=psk,
        address=address,
        client_dns=client_dns,
        client_allowed_ips=client_allowed_ips,
        persistent_keepalive=persistent_keepalive,
        notes=notes,
    )
    return peer


def regenerate_peer_keys(peer: Peer) -> None:
    priv, pub = wg_keys.generate_keypair()
    peer.private_key = priv
    peer.public_key = pub
    peer.save(update_fields=["private_key", "public_key", "updated_at"])


def delete_peer(peer: Peer) -> None:
    peer.delete()


def import_running_config(interface: WGInterface) -> dict:
    """Import the live wg config into the DB.

    Returns a summary dict: {created, updated, interface_updated}.
    """
    backend = get_backend()
    text = backend.read_config()
    if not text.strip():
        raise WGError("The running config is empty or could not be read.")

    parsed = config_parse.parse_config(text)
    summary = {"created": 0, "updated": 0, "interface_updated": False}

    with transaction.atomic():
        iface = parsed.interface
        changed = []
        if iface.private_key and iface.private_key != interface.private_key:
            interface.private_key = iface.private_key
            interface.public_key = wg_keys.public_key_from_private(iface.private_key)
            changed += ["private_key", "public_key"]
        if iface.listen_port:
            interface.listen_port = iface.listen_port
            changed.append("listen_port")
        if iface.address:
            interface.address = iface.address
            changed.append("address")
        if iface.mtu:
            interface.mtu = iface.mtu
            changed.append("mtu")
        if iface.dns and not interface.dns:
            interface.dns = iface.dns
            changed.append("dns")
        if iface.post_up:
            interface.post_up = "\n".join(iface.post_up)
            changed.append("post_up")
        if iface.post_down:
            interface.post_down = "\n".join(iface.post_down)
            changed.append("post_down")
        if changed:
            interface.save(update_fields=list(set(changed)) + ["updated_at"])
            summary["interface_updated"] = True

        existing = {p.public_key: p for p in interface.peers.all()}
        used_names = {p.name for p in existing.values()}
        for idx, pp in enumerate(parsed.peers, start=1):
            if not pp.public_key:
                continue
            peer = existing.get(pp.public_key)
            if peer is None:
                name = pp.name or f"imported-{idx}"
                while name in used_names:
                    name = f"{name}-{idx}"
                used_names.add(name)
                Peer.objects.create(
                    interface=interface,
                    name=name,
                    public_key=pp.public_key,
                    private_key="",  # server never held the client's private key
                    preshared_key=pp.preshared_key,
                    address=pp.allowed_ips,
                    endpoint=pp.endpoint,
                    persistent_keepalive=pp.persistent_keepalive,
                )
                summary["created"] += 1
            else:
                peer.preshared_key = pp.preshared_key or peer.preshared_key
                peer.address = pp.allowed_ips or peer.address
                peer.endpoint = pp.endpoint or peer.endpoint
                if pp.name and peer.name.startswith("imported-"):
                    peer.name = pp.name
                peer.save()
                summary["updated"] += 1

    return summary


def build_dashboard(interface: WGInterface):
    """Return (status, peer_rows) for the dashboard.

    peer_rows merges DB peers with live stats keyed by public key.
    """
    backend = get_backend()
    try:
        status = backend.status()
        backend_error = ""
    except WGError as exc:
        status = InterfaceStatus(name=interface.name, active=False)
        backend_error = str(exc)

    rows = []
    for peer in interface.peers.all().order_by("name"):
        stat = status.peers.get(peer.public_key)
        rows.append({"peer": peer, "stat": stat})
    return status, rows, backend_error
