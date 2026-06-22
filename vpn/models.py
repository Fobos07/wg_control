import ipaddress

from django.db import models


class WGInterface(models.Model):
    """A WireGuard interface (e.g. wg0).

    The panel is built around a single interface for now, but modelling it as a
    row keeps the door open for multiple interfaces later.
    """

    name = models.CharField(
        "Interface name", max_length=32, unique=True, default="wg0"
    )

    # Server keypair.
    private_key = models.CharField("Server private key", max_length=64, blank=True)
    public_key = models.CharField("Server public key", max_length=64, blank=True)

    listen_port = models.PositiveIntegerField("Listen port", default=51820)

    # Server's address(es) inside the tunnel, with CIDR. Comma-separated.
    # Example: "10.8.0.1/24" — the /24 defines the pool peers are drawn from.
    address = models.CharField("Tunnel address", max_length=255, default="10.8.0.1/24")

    # Public host/IP that clients dial (without the port).
    endpoint_host = models.CharField("Public endpoint host", max_length=255, blank=True)

    dns = models.CharField(
        "Client DNS", max_length=255, blank=True,
        help_text="Comma-separated DNS servers handed to clients (optional).",
    )
    mtu = models.PositiveIntegerField("MTU", null=True, blank=True)

    client_allowed_ips = models.CharField(
        "Default client AllowedIPs",
        max_length=255,
        default="0.0.0.0/0, ::/0",
        help_text="Routes pushed into generated client configs.",
    )
    persistent_keepalive = models.PositiveIntegerField(
        "Client PersistentKeepalive", null=True, blank=True, default=25
    )

    post_up = models.TextField("PostUp", blank=True)
    post_down = models.TextField("PostDown", blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "WireGuard interface"
        verbose_name_plural = "WireGuard interfaces"

    def __str__(self):
        return self.name

    @property
    def endpoint(self) -> str:
        if not self.endpoint_host:
            return ""
        return f"{self.endpoint_host}:{self.listen_port}"

    @property
    def networks(self):
        """Tunnel networks derived from `address`, as ip_network objects."""
        nets = []
        for part in self.address.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                nets.append(ipaddress.ip_interface(part).network)
            except ValueError:
                continue
        return nets

    @property
    def server_ips(self):
        """The server's own host addresses inside the tunnel."""
        ips = []
        for part in self.address.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                ips.append(ipaddress.ip_interface(part).ip)
            except ValueError:
                continue
        return ips


class Peer(models.Model):
    interface = models.ForeignKey(
        WGInterface, on_delete=models.CASCADE, related_name="peers"
    )

    name = models.CharField(max_length=120)

    public_key = models.CharField(max_length=64)
    # Empty for imported peers whose private key the server never held.
    private_key = models.CharField(max_length=64, blank=True)
    preshared_key = models.CharField(max_length=64, blank=True)

    # The peer's tunnel IP(s); becomes AllowedIPs in the server config.
    # Example: "10.8.0.2/32".
    address = models.CharField("Tunnel address", max_length=255)

    # Optional per-peer overrides for the generated client config.
    client_dns = models.CharField(max_length=255, blank=True)
    client_allowed_ips = models.CharField(max_length=255, blank=True)
    persistent_keepalive = models.PositiveIntegerField(null=True, blank=True)

    # Rarely needed (site-to-site); a static endpoint for this peer.
    endpoint = models.CharField(max_length=255, blank=True)

    enabled = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["interface", "public_key"],
                name="unique_peer_pubkey_per_interface",
            )
        ]

    def __str__(self):
        return self.name

    @property
    def has_private_key(self) -> bool:
        return bool(self.private_key)

    @property
    def primary_ip(self) -> str:
        """First tunnel IP without the CIDR suffix, for display."""
        first = self.address.split(",")[0].strip()
        return first.split("/")[0] if first else ""

    def effective_dns(self) -> str:
        return self.client_dns or self.interface.dns

    def effective_allowed_ips(self) -> str:
        return self.client_allowed_ips or self.interface.client_allowed_ips

    def effective_keepalive(self):
        if self.persistent_keepalive is not None:
            return self.persistent_keepalive
        return self.interface.persistent_keepalive
