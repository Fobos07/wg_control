"""Parse an existing wg0.conf into structured data for import."""
from dataclasses import dataclass, field


@dataclass
class ParsedInterface:
    private_key: str = ""
    listen_port: int | None = None
    address: str = ""
    mtu: int | None = None
    dns: str = ""
    post_up: list[str] = field(default_factory=list)
    post_down: list[str] = field(default_factory=list)


@dataclass
class ParsedPeer:
    name: str = ""
    public_key: str = ""
    preshared_key: str = ""
    allowed_ips: str = ""
    endpoint: str = ""
    persistent_keepalive: int | None = None


@dataclass
class ParsedConfig:
    interface: ParsedInterface = field(default_factory=ParsedInterface)
    peers: list[ParsedPeer] = field(default_factory=list)


def _split_kv(line: str):
    key, _, value = line.partition("=")
    return key.strip().lower(), value.strip()


def parse_config(text: str) -> ParsedConfig:
    """Parse WireGuard config text. Comments above a [Peer] become its name."""
    config = ParsedConfig()
    section = None
    current_peer = None
    pending_comment = ""

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            # Remember the last comment; used as the peer label.
            pending_comment = line.lstrip("#").strip()
            continue

        lower = line.lower()
        if lower == "[interface]":
            section = "interface"
            pending_comment = ""
            continue
        if lower == "[peer]":
            section = "peer"
            current_peer = ParsedPeer(name=pending_comment)
            config.peers.append(current_peer)
            pending_comment = ""
            continue

        if "=" not in line:
            continue
        key, value = _split_kv(line)

        if section == "interface":
            iface = config.interface
            if key == "privatekey":
                iface.private_key = value
            elif key == "listenport":
                iface.listen_port = _to_int(value)
            elif key == "address":
                iface.address = value
            elif key == "mtu":
                iface.mtu = _to_int(value)
            elif key == "dns":
                iface.dns = value
            elif key == "postup":
                iface.post_up.append(value)
            elif key == "postdown":
                iface.post_down.append(value)
        elif section == "peer" and current_peer is not None:
            if key == "publickey":
                current_peer.public_key = value
            elif key == "presharedkey":
                current_peer.preshared_key = value
            elif key == "allowedips":
                current_peer.allowed_ips = value
            elif key == "endpoint":
                current_peer.endpoint = value
            elif key == "persistentkeepalive":
                current_peer.persistent_keepalive = _to_int(value)

    return config


def _to_int(value: str):
    try:
        return int(value.strip())
    except (TypeError, ValueError):
        return None
