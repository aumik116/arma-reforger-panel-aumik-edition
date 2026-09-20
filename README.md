# Arma Reforger Panel — Aumik Edition

A self-hosted Linux panel for managing an Arma Reforger dedicated server.
Maintained by [aumik116](https://github.com/aumik116/arma-reforger-panel-aumik-edition).

Based on [Arma Reforger Panel](https://github.com/mateuszgolebiewski-code/arma-reforger-panel)
by **Mateusz Gołębiewski**. Credit for the original project belongs to him.

**This fork is vibe coded:** its modifications were developed with AI assistance
using OpenAI Codex. Local automated checks do not establish compatibility with
every live server setup. Back up your installation before updating.

## Features

- Start, stop, and restart the game; view console logs.
- CPU, RAM, native server FPS, network traffic, disk activity, and free-space monitoring.
- Connected-player roster through RCON; optional player-ping telemetry.
- Configuration, scenario discovery, mod imports, and saved mod presets.
- Persistence settings and save deletion while the game is stopped.
- Individual accounts, role permissions, and history of panel actions.

## Install

Use an x86_64 Ubuntu host with Python 3.10+, at least 20 GB free for installation,
and additional space for mods and saves. Ubuntu 22.04 or 24.04 provides a suitable
system Python; the installer does not upgrade older Python versions to 3.10.
Full and panel-only installation install Flask and bcrypt.

```bash
git clone https://github.com/aumik116/arma-reforger-panel-aumik-edition.git
cd arma-reforger-panel-aumik-edition
sudo bash install.sh
```

For an existing game server, use `sudo bash install.sh --panel-only` instead.
Enter its paths and Linux username when prompted.

Open `http://YOUR_SERVER_IP:8888` (or your chosen port). On first launch, log in
as `admin` with the panel password entered during installation. Panel accounts
are separate from in-game admin permissions.

The installer does not configure your firewall. Defaults are TCP 8888 for the
panel, UDP 2001 for the game, and UDP 17777 for A2S. Use HTTPS through a reverse
proxy or an SSH tunnel for remote panel access; direct HTTP is unencrypted.

## Update or migrate from the original project

Run the updater from **this fork's checkout**, not the original repository.
For migration, clone this fork into a separate directory using the command above.
The updater locates the installed panel through `arma-panel.service`.

```bash
git pull --ff-only
sudo apt-get update
sudo apt-get install -y python3-flask python3-bcrypt
sudo bash install.sh --update
```

The update preserves `config.env`, accounts, presets, and history and restarts
the panel. It also configures `arma-server.service` and limited sudo permission
for game start/stop. It replaces the game service's launch command; review custom
launch arguments before migrating. It does not request a game restart.
Restart the game once afterward to enable native FPS logging (`-logStats 1000`).

Existing shared-password installations gain an `admin` account using the saved
panel password. Once accounts exist, change passwords through the panel;
editing the bootstrap password in `config.env` does not update them.

## Configuration and backups

The default panel directory is `/home/arma/panel`. See
[config.env.example](config.env.example) for paths and optional settings.
Restart `arma-panel` after editing `config.env`.

Back up `config.env`, `.panel-secret`, and `.panel-data.sqlite3` from the panel
directory, plus the game's `config.json` and profile/save directory. Stop the
panel while copying its SQLite database for a consistent backup.

| Role | Access |
|---|---|
| Viewer | Status, metrics, players, configured mods, and presets |
| Operator | Viewer access plus game controls and console logs |
| Manager | Operator access plus configuration, persistence, mods, presets, and history |
| Administrator | All features, including account management |

Applying a mod preset replaces configured mods without changing the mission or
restarting the game. Restart the game to load mod/configuration changes.

## Connected players

Add an `rcon` object to the game's `config.json`, then restart the game:

```json
"rcon": {
  "address": "127.0.0.1",
  "port": 19999,
  "password": "REPLACE_WITH_A_UNIQUE_PASSWORD",
  "permission": "monitor"
}
```

Keep RCON private. If using a command whitelist, allow `#players` and `@logout`.
The panel reads RCON settings automatically; overrides are in `config.env.example`.
The roster refreshes every ten seconds. “First observed” is when the panel first
saw a player, not their exact join time.

## Metrics

Charts retain 60 samples in the open browser page and refresh each second while
the Dashboard is visible. CPU measures the game process as a share of total host
capacity; RAM shows system usage with game-process usage underneath. Network
traffic covers host interfaces except loopback and may double-count virtual
interfaces. Disk activity covers the device containing `SERVER_DIR`. Unsupported
metrics display unavailable. Free-space warnings trigger below 10% or 5 GiB
remaining. Event markers cover panel game controls and mod changes.

FPS reads fresh performance records from `LOG_DIR/logs_*/console.log`. The
launcher enables `-logStats 1000`; samples expire after 15 seconds.

**Player ping requires an external exporter; none is bundled.** Set
`GAME_TELEMETRY_FILE` in `config.env` to a UTF-8 JSON file with this schema:

```json
{"timestamp": 1790000000, "player_pings_ms": [24, 31, 86]}
```

Use the current Unix timestamp and one nonnegative, finite ping in milliseconds
per player. Replace the file atomically at least every ten seconds. Samples
older than 15 seconds or without ping measurements are unavailable.

## Troubleshooting and checks

```bash
sudo systemctl status arma-panel arma-server
sudo journalctl -u arma-panel -n 100 --no-pager
sudo journalctl -u arma-server -n 100 --no-pager
```

SteamCMD installation diagnostics are under
`/home/arma/steamcmd/install-logs/run-*/` (adjust for a custom user).

Local checks, with Flask and bcrypt installed:

```bash
python -m unittest discover -s tests -v
bash tests/test_installer.sh
bash tests/test_service_install.sh
```

Tests use temporary files and mocked game processes, not a live game server.

## License and attribution

The inherited README identifies the project as MIT licensed. This checkout has
no standalone LICENSE file; consult the
[original repository](https://github.com/mateuszgolebiewski-code/arma-reforger-panel)
for its licensing terms and notices. Original author:
[Mateusz Gołębiewski](https://mateuszgolebiewski.pl). Aumik Edition is an independently
maintained, AI-assisted fork.
