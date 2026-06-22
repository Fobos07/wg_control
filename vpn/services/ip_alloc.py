"""Allocate the next free tunnel IP for a new peer."""
import ipaddress


def _used_addresses(interface):
    used = set()
    # The server's own addresses are taken.
    for ip in interface.server_ips:
        used.add(ip)
    for peer in interface.peers.all():
        for part in peer.address.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                used.add(ipaddress.ip_interface(part).ip)
            except ValueError:
                continue
    return used


def next_free_address(interface, prefix: int = 32) -> str:
    """Return the next free host address inside the interface network.

    Returns a string like "10.8.0.2/32". Raises ValueError if the interface has
    no usable network or the pool is exhausted.
    """
    networks = interface.networks
    if not networks:
        raise ValueError("Interface has no valid tunnel network configured.")

    used = _used_addresses(interface)

    for net in networks:
        # Skip IPv6 huge ranges sensibly: iterate hosts lazily.
        hosts = net.hosts() if net.num_addresses > 2 else iter([net.network_address])
        for candidate in hosts:
            if candidate not in used:
                return f"{candidate}/{prefix}"

    raise ValueError("No free addresses left in the tunnel network.")
