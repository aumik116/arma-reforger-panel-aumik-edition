# Arma Reforger Server Management Panel

A self-hosted web panel for multiple Arma Reforger dedicated servers on one Linux VM.

## What it does

- Start, stop and restart the server; monitor CPU, RAM, FPS, players, AI, vehicles, network and disk activity.
- View and filter live logs, use RCON, and inspect network listeners.
- Edit server settings through grouped controls or inspect the raw JSON draft.
- Manage Workshop mods, version pins, load order and scenario-plus-mod presets. Review current Workshop releases before changing pins.
- Edit game-profile text files with a diff and automatic backup. Logs and the main server config are read-only in Files.
- Manage panel accounts and view an activity history.

Game configuration and mod changes take effect after a game-server restart. The panel does not restart the game automatically when you save them.

## Install

Use an x86_64 Ubuntu server with Python 3.10 or newer. The installer sets up the panel's dependencies.

For a new manager installation:

```bash
git clone --branch multi-server-manager https://github.com/aumik116/arma-reforger-panel-aumik-edition.git
cd arma-reforger-panel-aumik-edition
sudo bash install.sh
```

Fresh installation prepares the panel and SteamCMD only. Sign in as `admin` and create your first server in the browser; it starts automatically after installation. Additional servers can start from defaults or copy a managed server’s settings and mods. Set Public IPv4 address when automatic detection is unsuitable behind NAT. Firewall and router rules remain your responsibility. `--panel-only` is an alias for this installation flow. Existing installations should use `--update`, which retains their settings and servers.

Open `http://YOUR_SERVER_IP:8888`, or the port chosen during installation. Sign in as `admin` with the password you set in the installer.

## Everyday use

The dashboard places status and controls above summary cards, with performance
charts on the left and players/console on the right. The square controls and
original amber palette remain the default. Open **Appearance** in the sidebar
to choose Original, Ocean, Forest, or Light. The preference is saved to your
account and applies across servers; it does not change another user's theme.

All original sidebar workspaces remain directly accessible. The dashboard prioritizes
simulation FPS and places host memory, disk activity and latency under **More
performance details**. Configuration uses compact cards, with player name labels
under an expandable section. The Mods toolbar keeps search and adding mods visible;
**View & order** contains display and sorting controls.

**Dashboard** shows server controls, live metrics and the current player list. Network rates are host-wide and may include other services. Player names and IDs need working RCON; FPS and AI/vehicle counts come from game logs.

**Players** adds live search, identity copying and per-server player history. The Linux panel service samples running servers every 30 seconds even with the browser closed; dashboard queries also update history. First/last observed timestamps describe panel observations, not exact connection/disconnection times, and short connections between samples may be missed. History starts when this version is installed. Administrators can grant or remove in-game access here; a game-server restart applies those changes. Existing game-admin controls remain in Server config.

**Startup** lets administrators save an FPS cap (0 disables it) for managed servers or the original server. It shows launch paths, process/build status and recent output. Changes apply on the next game-server start; startup settings are stored in the panel database, without rewriting `config.env`. The original Servers dialog's FPS control still works.

**Scheduler** lets administrators create one-time jobs or repeat them every 6/12/24 hours or 7 days. Dates are entered/displayed in the browser's timezone and stored as UTC timestamps. Repeats use elapsed hours, so local clock times can change across daylight-saving transitions. Schedules belong to the selected server; no default jobs are created.

The installed Linux `app.py` service runs the scheduler; it must stay active, but the browser can be closed. A file lock prevents duplicate scheduler loops and database claims prevent replaying a run. Jobs more than 90 seconds late fail instead of catching up; work interrupted by a panel restart is recorded as interrupted. Pause/removal affects future runs and does not cancel an update already in progress. Removing a managed server disables its schedules, and each execution rechecks its creator's administrator access.

Scheduled restarts and game updates warn at 5 minutes and 1 minute using Server Admin Tools `#message` over admin RCON. A running server's run is skipped if either warning failed/missed or its process changed. Restarts leave stopped servers stopped. Successful updates restart only servers that were running beforehand; failed/interrupted updates leave them stopped for review. **Configuration backup** copies only the server JSON into the existing backup library (20 versions); world saves are not included. Scheduler and run history, player history and startup caps persist in `.panel-data.sqlite3`; include that database in your VM backups.

**Server config** lets you edit settings, select a scenario by name, validate changes and save. `Use default` removes an explicit value. The Raw JSON view shows the current draft, including unsaved edits. Restart the game server to apply saved changes.

**Mods** supports adding mods, importing or exporting JSON lists, reordering, and saving scenario-plus-mod presets. Existing mod-only presets still work. The Updates tab compares pinned versions with the current Workshop release; select changes, review them, then save. Unpinned mods already use the latest release. Workshop metadata may be cached for up to one hour.

**Configuration backups** are created before panel-managed server JSON changes. Administrators can review and restore the latest 20 versions in **Administration → Maintenance**. Backups live in `.panel-config-backups` beside the server JSON; they include passwords but not game saves. Restoring also backs up the current JSON.

**Mods → Compare lists** compares your configured mods with an ArmaHQ server or pasted mod JSON. Search a name/address or paste a server URL. Missing mods, extras and version differences have individual checkboxes; review and apply only the changes you want. ArmaHQ data may lag behind the live server. Restart the game server after changing mods.

**Persistence** has Settings, Save points and Named backups tabs. Save selection and named backups are marked WIP pending production verification. It shows the game's save settings and detected session save points. After an autosave, you can keep a named backup and select a save point to load on every server start; the panel preserves a copy outside the game's normal save retention. Startup selections are remembered per scenario. The selected scenario must support persistence; an autosave interval alone does not mean a save was written. Stop the game server and clear its pinned startup save before using **Flush saves**.

**Files** lets Administrators review and edit UTF-8 text files in the game profile. Each save backs up the previous file under `.file-backups`. Server logs and the main server config are read-only here. File edits do not reload a mod or restart the game.

**Console** filters recent logs and exports the visible lines. Connect, Disconnect, Kill and Chat are event filters; Hide RCON removes RCON lines from the log view. RCON shortcuts fill the command box for review; press Enter or Execute to send. Broadcast requires the Server Admin Tools mod.

## RCON and accounts

Set up RCON in **Server config → Remote console**. Bind it to `127.0.0.1`, choose a private UDP port and a unique password, then restart the game server. Allow `#players` if you use a command whitelist. To send commands from the panel, set the game's RCON permission to `admin`. Keep the RCON port off the public internet.

The panel supports Viewer, Operator, Manager and Administrator accounts. Operators can control the server and read logs. Managers can also change gameplay settings and mods. Administrators manage infrastructure settings, files and accounts. Other Administrators cannot change the original Owner account. Every user can change their own password in **Administration**.

## Update

From the repository checkout:

```bash
git pull --ff-only
sudo bash install.sh --update
```

This updates panel files and restarts the panel service. It keeps `config.env`, accounts, presets and activity history. It does not restart the game server.

Before updating production, take a VM backup or snapshot and wait for installations and game updates to finish. The updater saves installed panel files and affected service settings in a private `/var/backups/arma-panel/update-*` directory. If copying, service configuration, or the panel restart fails, it restores those files and attempts to restart the previous panel. The update still exits with an error so the failure is visible. This checks service activity, not game connectivity.

Each recovery directory also contains a consistent `panel-data.sqlite3` backup when the database exists. Automatic rollback keeps the live database and game saves; restoring a database is a separate manual recovery step. Keep your VM backup for a full rollback, especially across database schema changes. Recovery snapshots contain secrets: keep them private.

Port allocation reserves the original server's configured ports even while it is stopped. Changes to managed servers' ports through the panel update their reservations and reject conflicts with other servers. Restart the affected game server after editing ports, and adjust your own firewall/forwarding rules.

To update the **game server**, stop it first, then use **Server config → Server software**. The panel runs SteamCMD and leaves the game stopped afterward; start it once you have checked the result. The panel service account needs write access to the game and SteamCMD directories.

## Files and service commands

`config.env` holds panel settings and paths, including `PANEL_PORT`, `SERVER_DIR`, `SERVER_CONFIG`, `LOG_DIR` and `STEAMCMD_PATH`. Restart `arma-panel` after editing it. Back up `config.env`, the game config, `.panel-data.sqlite3`, `.panel-secret`, `.panel-save-selection.json`, `.panel-save-archives` and the game profile. Keep these backups private; stop the panel while copying its database.

```bash
sudo systemctl status arma-panel
sudo journalctl -u arma-panel -n 50 --no-pager
sudo systemctl status arma-server
sudo journalctl -u arma-server -n 50 --no-pager
```

For internet access, put the panel behind an HTTPS reverse proxy. If players are unavailable, check the RCON listener, password, permission, whitelist and any `RCON_*` overrides in `config.env`. If a configuration change has no effect, restart the game server and check its log.

For game settings, see [Bohemia's server configuration reference](https://community.bistudio.com/wiki/Arma_Reforger:Server_Config).

## Multiple servers on one VM

Local multi-server support is under development. Create Server is implemented
and covered by simulated tests; a complete Ubuntu VM run has not yet been
verified. The existing interface styling is retained.

Run the current installer (or `sudo bash install.sh --update` for an existing
panel) once to install the instance service template and root-owned helper.
An administrator can then use **Servers → Create Server** to start from defaults
or copy an existing server's settings and mod selections. Each instance gets
its own game installation, config, profile, logs, workshop directory, and
service. Passwords and saves are not copied; RCON gets a new random password
and listens on loopback.

Blank ports are allocated automatically, avoiding registered and currently bound
UDP ports. Custom ports are checked for conflicts. The detached installer shows
output through **Progress / retry**, which can resume interrupted downloads.
Verified installations are enabled at boot and started automatically. A running
process does not prove the mission has loaded or players can connect.

Creation seeds the new installation from local game files when available. It
prefers the selected copy source, otherwise the existing installation or another
ready instance. Files are copied independently, not hard-linked; configuration,
saves, logs, and Workshop downloads are excluded from this game-file copy.
SteamCMD still validates the installation and retrieves missing or updated
files. A missing or busy source falls back to normal installation.

The selector at the top of the sidebar reloads the page to clear the previous instance's forms and
console cursor. **Existing server** targets the original installation. Creation
and installation output require administrator permission. Existing roles apply
to all instances; per-server account assignments are not implemented.

The default instance root is `instances/` inside the panel directory. Set
`INSTANCE_ROOT` in `config.env` before registering instances to use another
location. Back up this root and the registry in `.panel-data.sqlite3` together.
Do not move registered directories manually.

Provisioning does not change host firewall rules or router/NAT forwarding.
Allow the chosen game/query UDP ports before testing external connectivity.
Use **Startup** in the server list to set an instance's FPS cap (0 disables it).
Restart that instance to apply changes. **Remove** requires typing the server ID,
stops/disables its service, and releases its reserved ports. Files are retained
under `instances/.removed/`; this does not reclaim their disk space. Removal is
refused while provisioning or a software job holds the instance's file lock.

For Ubuntu 24 validation:

1. Run the updated installer; create a default server and watch installation.
2. Inspect Console and confirm a player can join.
3. Copy its settings/mods into a second server; confirm its ports differ.
4. Edit, stop, and restart each independently.
5. Reboot the VM and verify both services and their separate saves/logs.
6. Test an interrupted download and use Retry to resume it.

## License and credits

MIT — free to use, modify and distribute.

Based on the panel by [Mateusz Gołębiewski](https://mateuszgolebiewski.pl). This fork is developed with AI assistance, including code, interface changes and documentation, using OpenAI Codex.
