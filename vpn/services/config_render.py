"""Render WireGuard configuration text from the database models."""


def render_server_config(interface) -> str:
    """Render the full /etc/wireguard/<iface>.conf for the server."""
    lines = ["[Interface]"]
    lines.append(f"Address = {interface.address}")
    lines.append(f"ListenPort = {interface.listen_port}")
    if interface.private_key:
        lines.append(f"PrivateKey = {interface.private_key}")
    if interface.mtu:
        lines.append(f"MTU = {interface.mtu}")
    for raw in interface.post_up.splitlines():
        if raw.strip():
            lines.append(f"PostUp = {raw.strip()}")
    for raw in interface.post_down.splitlines():
        if raw.strip():
            lines.append(f"PostDown = {raw.strip()}")

    for peer in interface.peers.filter(enabled=True).order_by("name"):
        lines.append("")
        lines.append(f"# {peer.name}")
        lines.append("[Peer]")
        lines.append(f"PublicKey = {peer.public_key}")
        if peer.preshared_key:
            lines.append(f"PresharedKey = {peer.preshared_key}")
        lines.append(f"AllowedIPs = {peer.address}")
        if peer.endpoint:
            lines.append(f"Endpoint = {peer.endpoint}")

    return "\n".join(lines) + "\n"


def render_client_config(peer) -> str:
    """Render a client-side config for a peer.

    Requires the peer's private key (known when the panel generated the peer).
    """
    interface = peer.interface
    lines = ["[Interface]"]
    if peer.private_key:
        lines.append(f"PrivateKey = {peer.private_key}")
    else:
        lines.append("# PrivateKey unknown to the server (imported peer).")
        lines.append("# PrivateKey = <paste the client's private key here>")
    lines.append(f"Address = {peer.address}")
    dns = peer.effective_dns()
    if dns:
        lines.append(f"DNS = {dns}")
    if interface.mtu:
        lines.append(f"MTU = {interface.mtu}")

    lines.append("")
    lines.append("[Peer]")
    lines.append(f"PublicKey = {interface.public_key}")
    if peer.preshared_key:
        lines.append(f"PresharedKey = {peer.preshared_key}")
    lines.append(f"AllowedIPs = {peer.effective_allowed_ips()}")
    if interface.endpoint:
        lines.append(f"Endpoint = {interface.endpoint}")
    keepalive = peer.effective_keepalive()
    if keepalive:
        lines.append(f"PersistentKeepalive = {keepalive}")

    return "\n".join(lines) + "\n"
