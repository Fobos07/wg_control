#!/usr/bin/env bash
#
# wgpanel-helper — the ONLY privileged entry point for the WireGuard panel.
#
# Install to /usr/local/sbin/wgpanel-helper (root:root, chmod 750) and grant the
# app user permission to run *only this script* via sudo (see sudoers.wgpanel).
# Every action validates the interface name, so the Django app can never inject
# arbitrary commands through it.
#
# Usage: wgpanel-helper <action> <interface>
#   dump | show | status | read-config | write-config | syncconf | restart | up | down
# write-config reads the new config from stdin.

set -euo pipefail

ACTION="${1:-}"
IFACE="${2:-}"
CONFIG_DIR="/etc/wireguard"

# Strict allow-list for the interface name: letters, digits, dash, underscore.
if [[ ! "$IFACE" =~ ^[a-zA-Z0-9_-]+$ ]]; then
  echo "wgpanel-helper: invalid interface name" >&2
  exit 2
fi

CONF="$CONFIG_DIR/$IFACE.conf"

case "$ACTION" in
  dump)
    exec wg show "$IFACE" dump
    ;;
  show)
    exec wg show "$IFACE"
    ;;
  status)
    # Print "active"/"inactive"; never fail the call itself.
    systemctl is-active "wg-quick@$IFACE" || true
    ;;
  read-config)
    cat "$CONF"
    ;;
  write-config)
    umask 077
    mkdir -p "$CONFIG_DIR"
    tmp="$(mktemp "$CONF.XXXXXX")"
    cat > "$tmp"
    chmod 600 "$tmp"
    mv "$tmp" "$CONF"
    ;;
  syncconf)
    # Apply the on-disk config to the running interface without dropping peers.
    wg syncconf "$IFACE" <(wg-quick strip "$IFACE")
    ;;
  restart)
    exec systemctl restart "wg-quick@$IFACE"
    ;;
  up)
    exec systemctl start "wg-quick@$IFACE"
    ;;
  down)
    exec systemctl stop "wg-quick@$IFACE"
    ;;
  *)
    echo "wgpanel-helper: unknown action '$ACTION'" >&2
    exit 2
    ;;
esac
