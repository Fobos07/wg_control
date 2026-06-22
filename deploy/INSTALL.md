# Deploying the WireGuard panel on Ubuntu

This installs the panel **on the same server that runs WireGuard**, served by
gunicorn behind nginx, with all privileged WireGuard actions funnelled through a
single sudo-whitelisted helper script.

Assumes WireGuard is already installed and `wg0` exists (or will be created).

## 1. System packages

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip nginx wireguard
```

## 2. Application user and code

```bash
sudo useradd --system --create-home --home-dir /opt/wg_control --shell /usr/sbin/nologin wgpanel
sudo mkdir -p /opt/wg_control
# Copy the project into /opt/wg_control (git clone, scp, rsync, ...)
sudo chown -R wgpanel:wgpanel /opt/wg_control
```

## 3. Python environment

```bash
cd /opt/wg_control
sudo -u wgpanel python3 -m venv .venv
sudo -u wgpanel .venv/bin/pip install -r requirements.txt
```

## 4. Configuration (.env)

```bash
sudo -u wgpanel cp .env.example .env
sudo -u wgpanel nano .env
```

Set at least:

```
DJANGO_SECRET_KEY=<run: python3 -c "import secrets; print(secrets.token_urlsafe(50))">
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=vpn.example.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://vpn.example.com
WGPANEL_INTERFACE=wg0
WGPANEL_BACKEND=local
```

## 5. Install the privileged helper + sudoers rule

```bash
sudo install -m 750 -o root -g root deploy/wgpanel-helper.sh /usr/local/sbin/wgpanel-helper
sudo install -m 440 -o root -g root deploy/sudoers.wgpanel /etc/sudoers.d/wgpanel
sudo visudo -cf /etc/sudoers.d/wgpanel        # must report "parsed OK"
```

Quick check that the app user can reach WireGuard:

```bash
sudo -u wgpanel sudo /usr/local/sbin/wgpanel-helper status wg0
```

## 6. Database, static files, admin user

```bash
cd /opt/wg_control
sudo -u wgpanel .venv/bin/python manage.py migrate
sudo -u wgpanel .venv/bin/python manage.py collectstatic --noinput
sudo -u wgpanel .venv/bin/python manage.py createsuperuser
```

## 7. gunicorn service

```bash
sudo install -m 644 deploy/wgpanel.service /etc/systemd/system/wgpanel.service
sudo systemctl daemon-reload
sudo systemctl enable --now wgpanel
sudo systemctl status wgpanel
```

## 8. nginx

```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-available/wgpanel
# edit server_name
sudo ln -s /etc/nginx/sites-available/wgpanel /etc/nginx/sites-enabled/wgpanel
sudo nginx -t && sudo systemctl reload nginx
```

### TLS (strongly recommended)

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d vpn.example.com
```

## 9. First use

1. Log in at `https://vpn.example.com/`.
2. Go to **Settings**, set the **Public endpoint host** (your server's public IP
   or DNS name) and confirm the listen port / tunnel address, then **Save & apply**.
3. If you already have peers in `wg0.conf`, click **Import from wg0.conf** on the
   dashboard to pull them into the panel.
4. Add peers, download their `.conf` or scan the QR code.

## How applying changes works

The database is the source of truth. On any change the panel renders
`/etc/wireguard/wg0.conf` from the DB, writes it atomically (via the helper), and
runs `wg syncconf` to apply it live **without dropping existing peers**. Use
**Restart service** for a full `systemctl restart wg-quick@wg0` when needed.

> Because the panel rewrites `wg0.conf` from the database, run **Import** once
> before making changes so any hand-written peers are captured first.

## Updating

```bash
cd /opt/wg_control
sudo -u wgpanel git pull          # or re-copy files
sudo -u wgpanel .venv/bin/pip install -r requirements.txt
sudo -u wgpanel .venv/bin/python manage.py migrate
sudo -u wgpanel .venv/bin/python manage.py collectstatic --noinput
sudo systemctl restart wgpanel
```
