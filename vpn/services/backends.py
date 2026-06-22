"""Backends that talk to the actual WireGuard interface.

`LocalWGBackend` runs on the Ubuntu server and drives WireGuard through a single
privileged helper script (see deploy/wgpanel-helper.sh) invoked via sudo. Keeping
every privileged action behind one whitelisted script keeps the sudoers grant
tiny and auditable.

`FakeWGBackend` simulates the interface so the whole panel is usable during
development on a machine without WireGuard (e.g. Windows).
"""
from __future__ import annotations

import hashlib
import logging
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings

logger = logging.getLogger("vpn")


@dataclass
class PeerStat:
    public_key: str
    endpoint: str = ""
    allowed_ips: str = ""
    latest_handshake: int = 0  # epoch seconds, 0 == never
    rx_bytes: int = 0
    tx_bytes: int = 0
    keepalive: int = 0


@dataclass
class InterfaceStatus:
    name: str
    active: bool = False
    public_key: str = ""
    listen_port: int = 0
    peers: dict[str, PeerStat] = field(default_factory=dict)


class WGError(RuntimeError):
    """Raised when a privileged WireGuard operation fails."""


# ---------------------------------------------------------------------------
# Shared dump parsing
# ---------------------------------------------------------------------------
def parse_dump(name: str, text: str) -> InterfaceStatus:
    """Parse `wg show <iface> dump` output into an InterfaceStatus."""
    status = InterfaceStatus(name=name, active=bool(text.strip()))
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return status

    # First line describes the interface: priv pub listen-port fwmark
    iface_fields = lines[0].split("\t")
    if len(iface_fields) >= 3:
        status.public_key = iface_fields[1]
        try:
            status.listen_port = int(iface_fields[2])
        except ValueError:
            pass

    # Remaining lines: pub psk endpoint allowed-ips handshake rx tx keepalive
    for line in lines[1:]:
        f = line.split("\t")
        if len(f) < 8:
            continue
        stat = PeerStat(
            public_key=f[0],
            endpoint="" if f[2] == "(none)" else f[2],
            allowed_ips="" if f[3] == "(none)" else f[3],
            latest_handshake=_int(f[4]),
            rx_bytes=_int(f[5]),
            tx_bytes=_int(f[6]),
            keepalive=0 if f[7] in ("off", "0") else _int(f[7]),
        )
        status.peers[stat.public_key] = stat
    return status


def _int(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------------------
# Local (real) backend
# ---------------------------------------------------------------------------
class LocalWGBackend:
    def __init__(self):
        self.name = settings.WG["INTERFACE"]
        self.helper = settings.WG["HELPER"]
        self.use_sudo = settings.WG["USE_SUDO"]

    def _run(self, action: str, *, stdin: str | None = None) -> str:
        cmd = []
        if self.use_sudo:
            cmd.append("sudo")
        cmd += [self.helper, action, self.name]
        logger.info("wg helper: %s", " ".join(cmd))
        try:
            proc = subprocess.run(
                cmd,
                input=stdin,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except FileNotFoundError as exc:
            raise WGError(f"Helper not found: {self.helper}") from exc
        except subprocess.TimeoutExpired as exc:
            raise WGError(f"Helper timed out: {action}") from exc
        if proc.returncode != 0:
            msg = (proc.stderr or proc.stdout or "").strip()
            raise WGError(f"`{action}` failed: {msg}")
        return proc.stdout

    def status(self) -> InterfaceStatus:
        try:
            dump = self._run("dump")
        except WGError as exc:
            logger.warning("status() failed: %s", exc)
            return InterfaceStatus(name=self.name, active=False)
        return parse_dump(self.name, dump)

    def read_config(self) -> str:
        return self._run("read-config")

    def write_config(self, text: str) -> None:
        self._run("write-config", stdin=text)

    def sync(self) -> None:
        self._run("syncconf")

    def restart(self) -> None:
        self._run("restart")

    def up(self) -> None:
        self._run("up")

    def down(self) -> None:
        self._run("down")


# ---------------------------------------------------------------------------
# Fake backend for local development
# ---------------------------------------------------------------------------
class FakeWGBackend:
    """In-memory/file-backed simulation used off the server."""

    def __init__(self):
        self.name = settings.WG["INTERFACE"]
        self.data_dir = Path(settings.WG["DEV_DATA_DIR"])
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.conf_path = self.data_dir / f"{self.name}.conf"
        self.state_path = self.data_dir / f"{self.name}.state"

    def _is_up(self) -> bool:
        if not self.state_path.exists():
            return self.conf_path.exists()
        return self.state_path.read_text().strip() == "up"

    def _set_state(self, up: bool) -> None:
        self.state_path.write_text("up" if up else "down")

    def status(self) -> InterfaceStatus:
        status = InterfaceStatus(name=self.name, active=self._is_up())
        if not status.active or not self.conf_path.exists():
            return status

        # Derive believable, slowly-changing stats for each configured peer.
        text = self.conf_path.read_text()
        now = int(time.time())
        for pub in _peer_pubkeys(text):
            seed = int(hashlib.sha256(pub.encode()).hexdigest(), 16)
            handshake_age = seed % 130  # 0..129s ago
            status.peers[pub] = PeerStat(
                public_key=pub,
                endpoint=f"203.0.113.{seed % 254 + 1}:{40000 + seed % 20000}",
                latest_handshake=now - handshake_age,
                rx_bytes=(seed % 5_000_000) + now % 1000,
                tx_bytes=(seed % 9_000_000) + now % 1000,
                keepalive=25,
            )
        return status

    def read_config(self) -> str:
        if self.conf_path.exists():
            return self.conf_path.read_text()
        return ""

    def write_config(self, text: str) -> None:
        self.conf_path.write_text(text)

    def sync(self) -> None:
        self._set_state(True)

    def restart(self) -> None:
        self._set_state(True)

    def up(self) -> None:
        self._set_state(True)

    def down(self) -> None:
        self._set_state(False)


def _peer_pubkeys(config_text: str):
    keys = []
    in_peer = False
    for raw in config_text.splitlines():
        line = raw.strip()
        if line.lower() == "[peer]":
            in_peer = True
        elif line.startswith("[") and line.lower() != "[peer]":
            in_peer = False
        elif in_peer and line.lower().startswith("publickey"):
            keys.append(line.split("=", 1)[1].strip())
    return keys


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------
def get_backend():
    choice = settings.WG["BACKEND"]
    if choice == "fake":
        return FakeWGBackend()
    if choice == "local":
        return LocalWGBackend()
    # auto
    import sys

    if sys.platform.startswith("linux"):
        return LocalWGBackend()
    return FakeWGBackend()
