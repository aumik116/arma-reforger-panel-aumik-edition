# Arma Reforger Server Management Panel

A self-hosted web panel for one Arma Reforger dedicated server on Linux.

## What it does

- Start, stop and restart the server; monitor CPU, RAM, FPS, players, AI, vehicles, network and disk activity.
- View and filter live logs, use RCON, and inspect network listeners.
- Edit server settings through grouped controls or inspect the raw JSON draft.
- Manage Workshop mods, version pins, load order and presets. Review current Workshop releases before changing pins.
- Edit game-profile text files with a diff and automatic backup. Logs and the main server config are read-only in Files.
- Manage panel accounts and view an activity history.

Game configuration and mod changes take effect after a game-server restart. The panel does not restart the game automatically when you save them.

## Install

Use an x86_64 Ubuntu server with Python 3.10 or newer. The installer sets up the panel's dependencies.

For a new game server and panel:

```bash
git clone https://github.com/aumik116/arma-reforger-panel-aumik-edition.git
cd arma-reforger-panel-aumik-edition
sudo bash install.sh
```

To add the panel to an existing game server, run `sudo bash install.sh --panel-only` instead and provide the existing server paths when prompted.

Open `http://YOUR_SERVER_IP:8888`, or the port chosen during installation. Sign in as `admin` with the password you set in the installer.

## Everyday use

**Dashboard** shows server controls, live metrics and the current player list. Network rates are host-wide and may include other services. Player names and IDs need working RCON; FPS and AI/vehicle counts come from game logs.

**Server config** lets you edit settings, select a scenario by name, validate changes and save. `Use default` removes an explicit value. The Raw JSON view shows the current draft, including unsaved edits. Restart the game server to apply saved changes.

**Mods** supports adding mods, importing or exporting JSON lists, reordering, and saving presets. The Updates tab compares pinned versions with the current Workshop release; select changes, review them, then save. Unpinned mods already use the latest release. Workshop metadata may be cached for up to one hour.

**Persistence** exposes the game's native save settings. The selected scenario must support persistence; panel settings cannot add that support to a scenario. Stop the game server before using **Flush saves**.

**Files** lets Administrators review and edit UTF-8 text files in the game profile. Each save backs up the previous file under `.file-backups`. Server logs and the main server config are read-only here. File edits do not reload a mod or restart the game.

**Console** filters recent logs and exports the visible lines. Connect, Disconnect, Kill and Chat are log filters. RCON shortcuts fill the command box for review; press Enter or Execute to send. Broadcast requires the Server Admin Tools mod.

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

To update the **game server**, stop it first, then use **Server config → Server software**. The panel runs SteamCMD and leaves the game stopped afterward; start it once you have checked the result. The panel service account needs write access to the game and SteamCMD directories.

## Files and service commands

`config.env` holds panel settings and paths, including `PANEL_PORT`, `SERVER_DIR`, `SERVER_CONFIG`, `LOG_DIR` and `STEAMCMD_PATH`. Restart `arma-panel` after editing it. Back up `config.env`, the game config, `.panel-data.sqlite3`, `.panel-secret` and the game profile. Keep these backups private; stop the panel while copying its database.

```bash
sudo systemctl status arma-panel
sudo journalctl -u arma-panel -n 50 --no-pager
sudo systemctl status arma-server
sudo journalctl -u arma-server -n 50 --no-pager
```

For internet access, put the panel behind an HTTPS reverse proxy. If players are unavailable, check the RCON listener, password, permission, whitelist and any `RCON_*` overrides in `config.env`. If a configuration change has no effect, restart the game server and check its log.

For game settings, see [Bohemia's server configuration reference](https://community.bistudio.com/wiki/Arma_Reforger:Server_Config).

## License and credits

MIT — free to use, modify and distribute.

Based on the panel by [Mateusz Gołębiewski](https://mateuszgolebiewski.pl). This fork is developed with AI assistance, including code, interface changes and documentation, using OpenAI Codex.
