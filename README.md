# wg_control — WireGuard control panel

A self-hosted Django web panel for managing a WireGuard server: create and delete
peers, generate and download client configs (with QR codes), restart the service,
and import existing peers from `wg0.conf`.

Designed to run **on the same Ubuntu server as WireGuard**, driving `wg` /
`wg-quick` / `systemctl` through a single sudo-whitelisted helper script.

## Features

- 🔐 Single-admin login (Django auth)
- 📊 Dashboard with interface status and **live per-peer stats** (handshake,
  transfer) that refresh automatically
- ➕ Create peers — keys + preshared key generated for you, next free tunnel IP
  auto-assigned
- 📥 Per-peer client config: copy, download `.conf`, or scan a QR code
- ✏️ Edit / enable / disable / delete peers; regenerate keys
- ♻️ Apply config live (`wg syncconf`, no peer drops) or full service restart
- 📤 **Import** existing peers and interface settings from the running `wg0.conf`
- ⚙️ Edit interface settings (endpoint, DNS, MTU, routes, PostUp/Down)

## Architecture

```
Browser ── nginx ── gunicorn ── Django (vpn app)
                                   │
                                   ├── DB (SQLite)  ← source of truth
                                   └── WGBackend
                                        ├── LocalWGBackend → sudo wgpanel-helper → wg / wg-quick / systemctl
                                        └── FakeWGBackend  → simulated, for dev on Windows/macOS
```

The **database is the source of truth**. Any change re-renders
`/etc/wireguard/wg0.conf` and applies it with `wg syncconf`. Run **Import** once
to capture pre-existing peers before editing.

The backend is selected by `WGPANEL_BACKEND` (`auto` | `local` | `fake`).
`auto` uses the real backend on Linux and the fake one elsewhere, so you can run
the full UI locally without WireGuard.

## Local development

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate
# Linux/mac: source .venv/bin/activate
pip install -r requirements.txt

copy .env.example .env          # cp on Linux/mac; defaults are dev-friendly
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open http://127.0.0.1:8000/. On a non-Linux machine the **fake backend** is used
automatically — added peers get simulated live stats so the whole panel works.

## Production deployment

See [deploy/INSTALL.md](deploy/INSTALL.md) for the full Ubuntu setup
(gunicorn + nginx + systemd + sudo helper + TLS).

## Security notes

- Every privileged action goes through one script (`wgpanel-helper`) that
  validates the interface name; sudoers grants the app user **only** that script.
- The app runs as an unprivileged `wgpanel` user.
- Put it behind HTTPS and restrict access (firewall / VPN / basic auth) — it
  controls your VPN.
```
