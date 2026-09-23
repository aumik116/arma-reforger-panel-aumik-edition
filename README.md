# Arma Reforger Server Management Panel

A self-hosted web panel for managing an Arma Reforger dedicated server on Linux. Control your server, configure gameplay, manage mods and monitor activity from your browser.

## Features

- **Server controls:** start, stop and restart the game server.
- **Live dashboard:** CPU, memory, native server FPS, AI/vehicle counts, network traffic, disk activity and free-space monitoring, with optional player latency telemetry.
- **Server console:** live logs with highlighted errors and warnings.
- **Detailed configuration:** grouped settings for identity, access, networking, gameplay, RCON, operating behavior and persistence.
- **Raw JSON view:** inspect and copy the complete configuration draft alongside the visual controls.
- **Named scenarios:** select built-in and discovered mod scenarios by name, or enter a custom scenario resource.
- **Mod library:** browse thumbnail cards, search by name or ID, sort, reorder, and choose 8, 16, 24 or 48 mods per page. Add and remove mods, edit pinned versions, import/export JSON lists and save reusable presets.
- **Mod download estimate:** view Workshop sizes on each card and a total across all configured mods, using pinned versions when specified. Unknown sizes are marked explicitly. The estimate excludes dependencies outside the configured list and files a player already has can reduce their download.
- **Connected players:** view player names, IDs and when the panel first observed them.
- **Administrator labels:** save a readable name beside an in-game administrator UUID or Steam ID.
- **Individual accounts:** four permission levels and a history of panel operations.
- **Responsive interface:** charcoal-and-gold styling with separate Dashboard, Server config, Mods and Administration sections.

## Installation

Use an x86_64 Linux server with Python 3.10 or newer. The installer is intended for Ubuntu and installs the required packages. Allow enough memory and disk space for your scenario, player count and Workshop mods.

### New game server and panel

```bash
git clone https://github.com/aumik116/arma-reforger-panel-aumik-edition.git
cd arma-reforger-panel-aumik-edition
sudo bash install.sh
```

The installer asks for a system user, server name, passwords, player limit, network settings and panel port. It installs SteamCMD, the dedicated server and the panel.

### Panel for an existing game server

```bash
git clone https://github.com/aumik116/arma-reforger-panel-aumik-edition.git
cd arma-reforger-panel-aumik-edition
sudo bash install.sh --panel-only
```

Provide the paths to your existing server directory, configuration file and logs when prompted.

### Open the panel

Visit `http://YOUR_SERVER_IP:8888`, or the port selected during installation. Sign in as `admin` using the panel password set during installation. You can change that password in **Administration → My account**.

## Using the panel

### Dashboard

Start, stop or restart the server and monitor its activity:

| Panel | What it measures |
|---|---|
| CPU | Arma process usage as a percentage of total host CPU capacity |
| Memory | System memory usage, with the Arma process usage shown separately |
| Network traffic | Receive and send rates across non-loopback host interfaces, including traffic from other services |
| Disk activity | Storage reads and writes attributed to the Arma process |

Charts refresh while the dashboard is visible. Counters need an initial sample before rates appear. Missing or inaccessible counters show **unavailable**. Network totals can include virtual interfaces; disk activity is not a disk-capacity indicator.

The live console displays recent server output. Full historical output remains in the server log files.

### Server config

Settings are grouped into Identity, Network, Access, Gameplay, Remote console, Operating and Persistence cards.

1. Edit the settings you want to change.
2. Select **Validate** to check the edited values without saving.
3. Select **Save configuration** to write your changes.
4. Restart the game server when ready to apply them.

Saving does not restart the server. **Use default** removes an explicit setting so the engine can use its default. Untouched settings, custom configuration fields and mods are preserved.

**Raw JSON** is a read-only view of the draft, including unsaved edits. Administrators see the complete configuration, including passwords. Managers receive a version with in-game administrator and RCON passwords omitted; the join password is still included. Copy and share it accordingly. Configuration access is restricted to Managers and Administrators.

If the configuration changes after you load it, saving is blocked to prevent overwriting newer changes. **Reload from disk** loads the latest file and asks before discarding unsaved edits.

The scenario picker displays readable names. Use **Rescan installed scenarios** after installing mods, or select **Custom scenario** to enter a resource directly. The selected scenario must be available to the game server.

Under **In-game administrators**, enter UUIDs or Steam IDs and save the configuration to update access. Each ID also has a name field with its own **Save name** button. These labels are stored in the panel and do not grant or remove administrator access.

Persistence behavior depends on the scenario. On Reforger 1.7+, the launcher respects the JSON Load latest session setting (enabled by default), without forcing it through a startup flag. **Save-file maintenance** lets you inspect and flush existing saves; the server must be stopped before flushing them.

### Mods

Add individual Workshop mods by ID or import a JSON mod list. Imports can replace the configured list or merge new entries into it. A version can be specified for each mod.

Save named presets to reuse mod lists. Applying a preset replaces the configured mods and versions without changing the scenario or restarting the game. Restart the server to load the new list, and ensure the scenario matches your chosen mods.

### Connected players and RCON

Configure the following RCON settings through **Server config → Remote console**, or add this block to your server configuration:

```json
"rcon": {
  "address": "127.0.0.1",
  "port": 19999,
  "password": "REPLACE_WITH_A_UNIQUE_RCON_PASSWORD",
  "permission": "monitor"
}
```

Restart the game server after changing its RCON listener. Keep the RCON UDP port private. If a command whitelist is configured, allow `#players`.

The panel reads the server's RCON settings automatically. `RCON_HOST`, `RCON_PORT` and `RCON_PASSWORD` in `config.env` override its connection settings; editing the server listener does not update these overrides.

The player list refreshes every ten seconds. **First observed by panel** is the time the panel first saw a player, not their exact connection time. It resets when the panel restarts.

### Performance telemetry

Server FPS reads fresh performance records from `LOG_DIR/logs_*/console.log`. The launcher enables `-logStats 1000`; restart the game after updating to enable these records. Samples expire after 15 seconds.

Player latency requires an external exporter; none is bundled. Set `GAME_TELEMETRY_FILE` in `config.env` to a UTF-8 JSON file containing a current Unix timestamp and player pings in milliseconds:

```json
{"timestamp": 1790000000, "player_pings_ms": [24, 31, 86]}
```

Replace this file atomically at least every ten seconds. Samples older than 15 seconds or without ping measurements are shown as unavailable.

### Accounts and activity

| Role | Permissions |
|---|---|
| Viewer | Status, metrics, connected players, mods and presets |
| Operator | Viewer permissions plus server controls and console logs |
| Manager | Operator permissions plus everyday server/gameplay settings, AI limits, save timing and retention, mods, presets and activity history |
| Administrator | All features, including infrastructure/security settings and account management; cannot modify the protected Owner account |

Only Administrators can change IP addresses, ports, A2S, RCON, in-game administrator access/passwords/name labels, BattlEye, fast validation, backend synchronization/shutdown behavior and the persistence Hive ID, or clear save files. Managers see these non-secret settings as **Read-only · Admin only**. Server name, scenario, join password, player limit, crossplay and browser visibility remain available to Managers.

Create individual accounts in **Administration**. Every user can change their own password. New passwords require at least 10 characters and cannot exceed 72 UTF-8 bytes.

Password changes, role changes and disabling an account invalidate its existing sessions. Administrators cannot delete or demote their own account.

The original default account is marked **Owner**. Ownership is tied to its permanent database ID, so renaming it does not remove its protection. Other Administrators cannot rename it, reset its password, change its role, disable it or delete it. The Owner can change its own username/password, but cannot be disabled, demoted or deleted through the panel. Ownership cannot be assigned when creating or editing an account.

Activity history records operations made through the panel. It does not record commands issued through SSH or directly in-game. Password values are excluded from activity records.

## Updating

From your checkout:

```bash
git pull --ff-only
sudo bash install.sh --update
```

The update replaces panel files and restarts the panel service. It preserves `config.env`, accounts, presets and activity history. It does not request a game-server restart.

The installer manages game control through `arma-server.service`. Updating replaces custom `ExecStart` overrides with the panel's launcher; other service settings are preserved. The launcher reads your saved `SERVER_DIR`, `SERVER_CONFIG` and `MAX_FPS` settings.

## Panel settings and backups

### Saved setups

Administrators can capture named backups and restore them under **Persistence → Saved setups**. For Camp Neptune, select `{394A32B84B229832}Missions/GM_CampNeptune_Persistence.conf` with its required mods. Prepare the scene, wait for a completed autosave, stop the server, then capture a backup. The panel copies existing save files; it cannot force a new game save through standard RCON.

Backups include the full local persistence directory, including player state and storage settings. They support binary save payloads and require native `meta-info.json` save-point metadata. Restore requires a stopped server, matching scenario/mod configuration/hive/recorded Steam build, and verified file hashes. A rollback snapshot is created before replacement. Keep **Load latest session** enabled, then start the server from Dashboard. Custom database/storage overrides are not supported. Camp Neptune's actual restoration of individual modded objects still depends on the scenario and those objects' persistence support.

Snapshots live in `.save-library` beside the panel; include that directory in host backups. Limits are 30 snapshots, 1 GiB and 10,000 files per snapshot. Preserve game-build compatibility when updating: game updates can invalidate older saves. This is a local-file backup library, not a guarantee that the game saved every placed object.

Persistence follows [Bohemia's server configuration](https://community.bistudio.com/wiki/Arma_Reforger%3AServer_Config) and [persistence system](https://community.bistudio.com/wiki/Arma_Reforger%3APersistence_System). Autosave interval 0 disables periodic saves only. Removing the persistence configuration restores defaults; explicitly disabling persistence requires `missionHeader.m_eSaveTypes = 0`.

### Game server software updates

Panel administrators can use **Server config → Server software** to read the installed Steam build ID, check the public Steam release, and run an update. Build IDs are Steam identifiers, not the game's displayed version number. Missing local manifests are shown as unavailable.

Stop the game server before updating. The panel runs SteamCMD with anonymous login for Arma Reforger Dedicated Server (1874900), shows its output, and leaves the game stopped afterward. Start/restart actions are blocked while a software job runs. Check the result before starting; failed updates can leave an incomplete installation. Back up your configuration and saves first. Avoid manual SteamCMD jobs or external game starts during an update.

This feature runs on Linux under the panel service account, which needs write access to the game installation and SteamCMD directories. The installer saves `STEAMCMD_PATH` for new installations. Existing installations search the sibling `steamcmd/steamcmd.sh` directory and the system SteamCMD executable; set `STEAMCMD_PATH=/absolute/path/to/steamcmd.sh` in `config.env` and restart the panel if discovery fails. The update uses the public release; custom beta installations are not supported. Update checks time out after three minutes and updates after thirty minutes.

`config.env` contains panel settings and server paths. The game's settings live in the file named by `SERVER_CONFIG`, usually `config.json`.

Common panel settings include:

```env
PANEL_PORT=8888
SERVER_DIR=/home/arma/server
SERVER_CONFIG=/home/arma/server/config.json
LOG_DIR=/home/arma/.config/ArmaReforger/logs
MAX_FPS=60
```

Restart the panel after changing `config.env`. Changes to game startup settings require a game-server restart. Once accounts exist, manage their passwords through Administration rather than changing the installation password in `config.env`.

Back up these files along with your game profile and saves:

- `config.env` and the server's `config.json`
- `.panel-data.sqlite3` — accounts, mod presets, administrator labels and activity history
- `.panel-secret` — panel session signing key

Stop the panel while copying its database for a consistent file backup. These files contain sensitive information; keep backups private.

## Service commands

```bash
# Panel
sudo systemctl status arma-panel
sudo systemctl restart arma-panel
sudo journalctl -u arma-panel -f

# Game server
sudo systemctl status arma-server
sudo systemctl start arma-server
sudo systemctl stop arma-server
sudo journalctl -u arma-server -f
```

## HTTPS and custom domains

For access over the internet, place the panel behind an HTTPS reverse proxy. An nginx location can forward requests to the panel:

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

Configure your domain and TLS certificate on the proxy. Adjust the upstream port if you selected a different panel port.

## Troubleshooting

**SteamCMD installation failed:** retain the install logs, update your checkout and rerun the installer. It keeps downloaded files between attempts. Logs are stored under `/home/arma/steamcmd/install-logs/run-*/` by default; the installer prints the path when it fails.

**Players show unavailable:** check the server's RCON listener, password, permissions, command whitelist and any overrides in `config.env`.

**A scenario is missing:** install its required mods and rescan installed scenarios. Custom resources must refer to a scenario available on the server.

**Configuration changes have no effect:** restart the game server and check its logs for settings or scenarios it could not load.

For game-specific settings, see the [Bohemia server configuration reference](https://community.bistudio.com/wiki/Arma_Reforger:Server_Config).

## License and credits

MIT — free to use, modify and distribute.

Based on the panel by [Mateusz Gołębiewski](https://mateuszgolebiewski.pl).

This fork is developed with AI assistance, including code, interface changes and documentation, using OpenAI Codex.
