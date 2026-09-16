# Arma Reforger Server Management Panel

A lightweight, self-hosted web panel for managing your **Arma Reforger dedicated server** on Linux. The all-in-one installer sets up everything from scratch — SteamCMD, the game server, and the panel — on a clean Ubuntu VPS.

---

## Features

- **Connected players** — username dropdown with player ID, identity and first-observed time, queried through RCON
- **Mod presets** — save, overwrite, apply and delete named mod lists, including versions
- **Individual accounts** — Administrator, Manager, Operator and Viewer roles enforced on every API request
- **Activity history** — persistent actor, timestamp, result and mod changes for panel operations
- **English interface** — all panel labels, feedback, login and PWA text in English

- **One-command install** — sets up SteamCMD, downloads the Arma Reforger server and installs the panel automatically
- **Server control** — Start, stop and restart your server from the browser
- **Real-time monitoring** — Live CPU and RAM charts updated every 3 seconds
- **Live log streaming** — Server console logs with colour-coded output (errors, warnings, network events)
- **Mission selector** — 41 built-in missions including all vanilla and RHS — Status Quo scenarios
- **Mod management** — Add and remove Workshop mods directly from the panel
- **Config editor** — Edit server name, scenario, passwords without touching the filesystem
- **PWA support** — Installable as a native app on Android and iOS
- **Single config file** — All settings in one `config.env`, no code editing required

---

## Requirements

| Component | Requirement |
|-----------|-------------|
| OS | Ubuntu 20.04 / 22.04 / 24.04 |
| Architecture | x86_64 |
| RAM | 4 GB minimum, 8 GB recommended |
| Disk | 20 GB free (Arma server is ~15 GB) |
| Python | 3.10+ (installed automatically) |

## Accounts, presets and activity

On the first launch of this version, the panel creates an `admin` account using
your existing panel password. Sign in with username `admin` and that password.
Existing shared-password sessions must sign in again. Change your password in
**My account**, then create individual accounts in **User accounts**.

| Role | Permissions |
|------|-------------|
| Viewer | Status, metrics, connected players, configured mods and saved presets |
| Operator | Viewer permissions plus start/stop/restart and server console logs |
| Manager | Operator permissions plus configuration, persistence, mods, presets and activity history |
| Administrator | All features plus create, edit, disable and delete accounts |

Password changes, role changes and disabling an account invalidate its previous
sessions. Administrators cannot delete or demote their own account. Passwords
are bcrypt hashed; new passwords require at least 10 characters (maximum 72
UTF-8 bytes).

**Save current mods as preset** snapshots the configured mod list and versions.
**Apply selected preset** replaces that list without changing the mission or
automatically restarting the server. Restart a running server to load the new
mods. Check that your chosen mission is supported by the applied mods.

Activity history covers actions performed through this panel, including server
controls, config changes, mod additions/removals/imports, presets, accounts and
persistence. It records successful and failed authorized operations. It does
not capture external SSH, systemd or in-game admin commands. Password values are
never included in activity records.

Accounts, presets and history are stored in `.panel-data.sqlite3` next to
`app.py`, preserved by `install.sh --update`. Back it up along with
`.panel-secret` and `config.env`. Once accounts exist, changing the bootstrap
password in `config.env` does not change their passwords; use account management.

## Connected-player setup

The panel queries native Reforger `#players` over RCON. Enable an `rcon` block in
your server's `config.json`, using a unique password, then restart the server:

```json
"rcon": {
  "address": "127.0.0.1",
  "port": 19999,
  "password": "REPLACE_WITH_A_UNIQUE_RCON_PASSWORD",
  "permission": "monitor"
}
```

The panel reads these settings automatically. `RCON_HOST`, `RCON_PORT` and
`RCON_PASSWORD` in `config.env` can override its connection settings. Keep the
RCON UDP port private. Ensure any RCON command whitelist allows `#players`.
The client sends `@logout` after each query (supported by Reforger 1.2.1+).

The dropdown refreshes every ten seconds. **First observed by panel** means when
the panel first saw that player during monitoring; it is not an authoritative
connection duration and resets when the panel restarts. Unconfigured, failed or
unrecognized queries display **unavailable**, not a misleading zero count.
Live RCON behavior must be verified against your installed game-server version.

References: [Bohemia server configuration](https://community.bistudio.com/wiki/Arma_Reforger:Server_Config),
[server commands](https://community.bistudio.com/wiki/Arma_Reforger:Server_Management),
[BattlEye RCON protocol](https://www.battleye.com/downloads/BERConProtocol.txt).

## Development checks

With Flask and bcrypt installed, run `python -m unittest discover -s tests -v`.
Tests use temporary configurations and mock server processes and RCON sockets;
they do not start or stop a real game server.

---

## Installation

### Option A — Full install (recommended for a fresh VPS)

Sets up everything: SteamCMD, Arma Reforger Dedicated Server, and the management panel.

```bash
git clone https://github.com/aumik116/arma-reforger-panel-aumik-edition.git
cd arma-reforger-panel-aumik-edition
sudo bash install.sh
```

The installer will ask you for:
- System username (default: `arma`)
- Server name, game password, admin password
- Max players, game port, public IP
- Panel web password and port

After ~15 minutes your server is running and the panel is accessible at:
```
http://YOUR_SERVER_IP:8888
```

---

### Option B — Panel only (server already installed)

If you already have Arma Reforger server running and only want the web panel:

```bash
git clone https://github.com/aumik116/arma-reforger-panel-aumik-edition.git
cd arma-reforger-panel-aumik-edition
sudo bash install.sh --panel-only
```

The installer will ask for your existing server paths (`SERVER_DIR`, `config.json`, log directory).

---

### Option C — Update panel files only

After pulling a new version from GitHub:

```bash
git pull
sudo bash install.sh --update
```

This copies updated panel files and restarts the service. Your `config.env` is preserved.

---

## Configuration

All settings live in `config.env` (created automatically by the installer):

```env
# Password for the panel web UI
PANEL_PASSWORD=changeme

# Port the panel listens on
PANEL_PORT=8888

# Path to your Arma Reforger server binary directory
SERVER_DIR=/home/arma/server

# Full path to your server config.json
SERVER_CONFIG=/home/arma/server/config.json

# Arma Reforger log directory
LOG_DIR=/home/arma/.config/ArmaReforger/logs

# Server FPS cap (passed as -maxFPS on startup)
MAX_FPS=60
```

After editing, restart the panel:
```bash
sudo systemctl restart arma-panel
```

---

## Useful Commands

```bash
# ── Panel ──────────────────────────────────────────────────
sudo systemctl status arma-panel      # check panel status
sudo systemctl restart arma-panel     # restart panel
sudo journalctl -u arma-panel -f      # live panel logs

# ── Arma Server ────────────────────────────────────────────
sudo systemctl start arma-server      # start server
sudo systemctl stop arma-server       # stop server
sudo systemctl status arma-server     # check server status
sudo journalctl -u arma-server -f     # live server logs

# ── Update ─────────────────────────────────────────────────
git pull && sudo bash install.sh --update
```

---

## HTTPS / Domain (optional)

To access the panel over HTTPS with a custom domain, use nginx as a reverse proxy with a Let's Encrypt certificate.

Nginx config example:
```nginx
location / {
    proxy_pass http://127.0.0.1:8888;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;
    proxy_read_timeout 3600;
}
```

If you use **HestiaCP**, add a subdomain through its web interface — it handles SSL automatically.

---

## Project Structure

```
arma-reforger-panel/
├── app.py               # Flask backend — API, server control, metrics
├── index.html           # Main panel UI (English)
├── login.html           # Login screen
├── config.env           # Your local config (excluded from git)
├── config.env.example   # Config template
├── install.sh           # All-in-one installer
├── static/
│   ├── manifest.json        # PWA manifest
│   ├── service-worker.js    # PWA service worker
│   ├── icon-192.png         # App icon
│   └── icon-512.png         # App icon (large)
└── README.md
```

---

## RHS — Status Quo

The panel includes mission IDs for all RHS — Status Quo scenarios. They appear automatically in the mission dropdown once you add the [RHS mod](https://reforger.armaplatform.com/workshop/595F2BF2F44836FB-RHS-Status-Quo) to your server.

---

## Contributing

Pull requests and issues are welcome. Open an issue on GitHub if you run into problems or want to suggest a feature.

---

## License

MIT — free to use, modify and distribute.

---

*Built by [Mateusz Gołębiewski](https://mateuszgolebiewski.pl)*
