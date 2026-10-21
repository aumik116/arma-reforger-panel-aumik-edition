# Operations guide

[Back to installation and the workspace overview](../README.md).

## All servers dashboard

The totals and rows cover servers your account can access. Search and status filters narrow the rows without changing totals. Click a server row to open that server's dashboard; Start, Stop and Restart use that row's server and permissions. Stop and Restart ask for confirmation.

Player activity is the combined count from available rosters. A `+` on the total means some readings are missing; the chart leaves a gap rather than treating those servers as empty. Host CPU and memory cover the whole VM, while rows show individual game-process usage. Host CPU needs two samples after the panel starts.

Server rows show the Workshop preview image for the configured scenario when its configured Workshop item publishes a matching scenario ID. Metadata is cached and loads in the background. Vanilla scenarios, missing Workshop metadata and image failures display a neutral placeholder. These are Workshop item previews, not live map screenshots.

Charts keep up to 30 minutes of readings while this page is open and reset on reload. Alerts show current failures, status changes observed while the page is open, and the latest permitted administrative activity. An online-to-offline change records a stop or exit; it does not establish whether the process crashed. Player joins and leaves are not listed. If a refresh fails, the page marks the retained server readings as potentially out of date.

## Servers and configuration

Each managed server has its own game installation, JSON configuration, profile, Workshop directory, logs, backups, reserved ports and `arma-server@ID.service` unit. The default instance root is `instances/` inside the panel directory. Set `INSTANCE_ROOT` before creating servers; do not move registered directories manually.

Blank creation ports are allocated automatically, avoiding registered and currently bound UDP ports. Ports remain reserved while servers are stopped. Save configuration through **Server config** so validation and reservation checks run. Restart the selected game server to apply settings or mod changes; saving does not restart it automatically.

**Use default** removes an explicit configuration value. Raw JSON shows the current draft, including unsaved edits. Concurrent changes are rejected so an old draft cannot overwrite a newer configuration.

New installations use manager mode. Upgraded installations retain an **Existing server** entry for their original unmanaged server. Panel accounts and personal settings work even when no game server exists.

### Creating and removing servers

Creation can copy settings and mod selections, but excludes passwords and saves. RCON receives a fresh random password and binds to loopback. Local game files may be copied from a ready server before Steam validation; they are independent copies, not hard links. A missing or busy source falls back to downloading. Game-file reuse excludes configuration, saves, logs and Workshop downloads.

**Progress / retry** shows provisioning output and failure diagnostics. Retry can resume interrupted downloads. Successful installations are enabled at boot and started automatically. A running process does not prove that the mission loaded or a player can join.

**Remove** requires typing the server ID, stops/disables its service and releases port reservations. Files move to `instances/.removed/`; their disk space is not reclaimed. Removal is refused while provisioning or a software job holds the server lock.

## Mods and scenarios

Use **Mods** to browse the official Workshop, add dependencies, import/export JSON, reorder mods and save scenario-plus-mod presets. Existing mod-only presets still work. Workshop browsing supports search, categories, sorting, pagination and release selection.

New mods and dependencies track the latest release unless explicitly pinned. Existing dependency pins are preserved. Adding dependencies refuses conflicting pins; historical releases do not guess dependency versions. Removing a mod keeps its dependencies because another mod may require them.

The update review compares pinned versions with current Workshop releases. Select changes, review them and save. Metadata may be cached for up to an hour; public Workshop outages can temporarily prevent previews or updates. Previews expire after five minutes and refuse changes if the configured list changed.

Terrain details can preview a scenario and its required mod additions together. Saving requires both Mods and Configuration permissions. Scenario metadata describes the current Workshop release; update an older pinned terrain release before using that action.

**Compare lists** accepts an ArmaHQ server or pasted mod JSON. Review missing mods, extras and differing versions individually. ArmaHQ data can lag behind the live server. Configuration backups and activity history apply to saved changes. Restart the game afterward.

The PlayStation warning compares estimated configured mod sizes against 25 GB. Unknown sizes remain estimates; use the displayed metadata status when reviewing compatibility.

## Players, RCON and telemetry

The live roster needs working RCON. For a command whitelist, allow `#players`; use RCON permission `admin` for panel commands and moderation. Bind to `127.0.0.1` when the panel and game share a VM. Keep RCON private.

The Linux panel service samples player history every 30 seconds, even with the browser closed. History records first/last observations, not exact join/leave times, and can miss short connections. History starts when collection is installed.

Server administrators can kick a connected player, ban an identity temporarily or permanently, and remove bans. Kicks refresh the roster to resolve the identity's current session slot. Ban lists are paginated, with a current-page filter and raw reply fallback. Moderation reasons and durations are recorded in Activity; the game does not supply those reasons in its list. Command submission alone does not prove enforcement: refresh the roster or ban list.

Game-admin grants are separate from bans and apply after a game-server restart. Console shortcuts fill the command box for review; Enter or Execute sends the command. Broadcast requires Server Admin Tools.

FPS and AI/vehicle readings come from game logs. Network rates describe the host and can include other services. Missing readings stay unavailable; they do not prove the server is stopped. Diagnostics check local configuration, files, listeners, free space and helpers; they cannot certify mission readiness or external connectivity.

## Startup and resources

Startup settings apply on the next server start. The FPS cap accepts `0` for no cap. Advanced launch controls include noSound, forceUpdate, noThrow, singleThreadedUpdate, optional AI population/batch limits and a 1–10 second statistics interval. Defaults preserve the existing launch command.

CPU selection accepts logical CPU checkboxes or ranges. **Use all CPUs** removes the restriction. Memory uses decimal MB; `0` means unlimited. The soft target requests memory reclamation under pressure. The hard cap can terminate the game process.

| Preset | Logical CPUs | Soft memory target |
| --- | --- | --- |
| Unrestricted | All | Unlimited |
| Small | Up to 2 | 4,000 MB |
| Standard | Up to 4 | 8,000 MB |
| Large | Up to 8 | 16,000 MB |

Presets use the lowest numbered available CPUs, clear the hard cap and preserve FPS and other launch options. They do not reserve resources. Review the draft before saving it.

Resource enforcement requires Linux with cgroup v2 and the updated root-owned helper. Settings use systemd AllowedCPUs, MemoryHigh and MemoryMax. A local Windows preview can display/save settings but cannot enforce them.

## Scheduler

Schedules belong to one server and use the **VM's local clock**, not the browser timezone. Supported actions are start, stop, restart, game update, broadcast and configuration backup. Choose a one-off time, 1–720 hour interval, or daily/weekly schedule. Calendar jobs skip nonexistent daylight-saving times and run a repeated time once.

The installed Linux panel service executes jobs with the browser closed. No default jobs are created. Schedules can be edited, paused, resumed and removed; run history supports filters, pagination and preparing a one-off retry. Each execution rechecks its creator's administrator access.

Stops, restarts and updates warn connected players at five minutes and one minute through Server Admin Tools `#message` with admin RCON. A disruptive run is skipped if a warning fails/is missed or the running process changes. A scheduled restart leaves an already stopped server stopped. A successful update restores the previous running state; a failed/interrupted update leaves the game stopped for review.

**Run now** creates a separate one-off job. Start, broadcast and backup run on the next tick. Stop, restart and update wait six minutes to allow warnings. Broadcast requires the game running. Configuration backup includes server JSON only, not world saves.

Jobs more than 90 seconds late fail instead of catching up. Interrupted work is recorded as interrupted. Pausing/removing a schedule affects future runs and does not cancel an update already underway. Removing a server disables its schedules. Database claims and a file lock prevent duplicate scheduler execution. A Windows preview does not execute jobs.

## Files and persistence

### Profile files and Trash

Assigned server administrators can browse Profile, Workshop, Game files, Logs, Backups and Server config. Profile supports uploads, new folders/text files, rename, text editing with diff review, and deletion to recoverable Trash. Other locations are read-only; use Server config to change validated settings.

Uploads are limited to 50 MiB per file. Folder uploads retain the selected folder name and nested paths inside the current profile folder. Existing directories merge; conflicting files are skipped, and remaining uploads continue. Browsers omit empty folders. Completed uploads and created folders remain after partial failure; retry skips existing files. Rename or move an existing file to Trash before uploading a replacement.

Supported UTF-8 text files can be edited with automatic backups. Links and paths outside the selected root are refused. Trash keeps deleted files on disk until restored. Restore a parent folder first and resolve destination conflicts before restoring its children. File operations do not restart the game or reload a mod.

### Saves

Persistence shows game save settings and detected save points. **Save selection and named backups remain WIP pending real-server verification.** The selected scenario must support persistence; an autosave interval alone does not prove a save was written.

After an autosave, a completed save point can be kept as a named backup or pinned for startup. The panel keeps a copy outside normal game retention and remembers the startup selection per scenario. Verify that the chosen save belongs to the scenario; metadata does not reliably identify its map.

Stop the game and clear its pinned startup save before using **Flush saves**. This deletes world-session and per-player saves from known save folders; server settings are retained. Include the profile and retained save archives in VM backups.

### Storage accounting

Dashboard storage scans game files, mods, profile/saves, logs, backups, Trash and server configuration in a background worker. Results are cached for ten minutes. Time/file limits produce a partial-result notice. Links are ignored; nested roots and same-folder hard links are not double-counted. File sizes may differ from filesystem allocation when reflinks/shared storage are used. Displays use decimal GB/MB.

## Notifications and personal settings

Dashboard shows the selected server's events and Discord delivery status. In **Administration → Notifications**, server administrators can configure a Discord webhook, routine-event delivery and an optional role ID to mention. Failures remain eligible for delivery when a webhook is configured. Blank input preserves the saved webhook; Remove clears it. The saved secret URL is not returned to the browser.

Monitoring distinguishes panel-controlled stops from unexpected process changes. Initial observation establishes a baseline. Repeated failures are suppressed for five minutes. Delivery tries up to three times, observes rate-limit delays and records failures. Messages do not include passwords, logs or configuration values; only the configured role can be mentioned. Saving settings cancels queued messages. The database retains the latest 1,000 events per server; the UI shows 100. Monitoring and delivery require the Linux service. Use **Send test message** to check your webhook.

**Account settings** changes your password and theme without requiring server access. Password changes require the current password, keep the current session signed in and invalidate other sessions. Staff/access management remains in Administration. Login uses the browser's remembered theme; signed-in pages load the account's saved preference. The layout is shared by all accounts; the color picker changes only the palette. Tactical uses the charcoal/amber/olive mockup palette and is the default for accounts without a saved preference. Original retains the pre-refresh amber colors. Ocean, Forest, Light and Field (olive and parchment) complete the six color options. Existing saved colors remain selected.

The interface before the field-layout refresh is saved at Git tag `backup/pre-field-operations-fb3c1d2`. Reverting the refresh commit restores that interface without changing server files or account data. Changing color themes does not revert the layout.

| Role | Access |
| --- | --- |
| Viewer | Server status and read-only overview data |
| Operator | Viewer access, lifecycle controls and logs |
| Manager | Operator access, gameplay settings, mods and activity |
| Server administrator | Advanced server settings, files, startup, moderation and schedules |
| Panel administrator | Staff accounts, access assignments and server creation; server access is assigned separately |

Server roles apply to named servers. Advanced all-server defaults are available when intentionally needed. Access changes invalidate existing sessions. The original Owner is protected from changes by other administrators.

An optional installable app uses the same live panel. It requires a supported browser and a secure context such as HTTPS. It has no offline management mode and does not serve cached API responses after a connection failure.

## Backup and recovery

Back up the installed panel directory, including `config.env`, `.panel-secret`, `.panel-data.sqlite3` and retained save selections/archives, plus the instance root and any external legacy game profile/configuration paths. The default panel directory is `/home/arma/panel`; custom service users or settings can change it. Preserve instance registration and files together. Stop the panel while copying its SQLite database, or use a consistent database backup. Keep backups private because they contain credentials.

| Backup | Includes | Does not replace |
| --- | --- | --- |
| Configuration library | Latest 20 server JSON versions, including passwords | Profile/world-save backups |
| Named save backup | A selected completed save point | A full VM backup |
| Panel update recovery | Panel files, affected service settings and a consistent database copy when present | Game files/saves or full rollback |
| VM backup/snapshot | The VM state captured by your backup system | External storage and router configuration |

Configuration backups are created before panel-managed JSON changes. Review/restore them in **Administration → Maintenance**. The default library is `.panel-config-backups` beside the server JSON; restoring also backs up the current JSON.

Panel update snapshots live under `/var/backups/arma-panel/update-*`. Copy/service/restart failures trigger attempted file/service rollback. The live database is not automatically rewound; restoring the saved database is a separate manual recovery step. This recovery checks panel service activity, not game connectivity.

To update game software manually, stop that server and open **Administration → Maintenance → Server software**. SteamCMD leaves it stopped; inspect the result before starting it. The service account needs write access to the game and SteamCMD directories. Custom beta installations require updates outside the panel.

## Ubuntu VM checklist

Use the test VM before production:

1. Install the panel fresh, sign in and create a server from defaults.
2. Confirm the Steam download/validation finishes and its systemd unit stays running.
3. Inspect Console, verify the mission loads and join the server. Test public connectivity separately from LAN/private joins.
4. Create a second server by copying settings/mods. Check different ports, separate files, fresh passwords and no copied saves.
5. Change configuration/mods and operate each server independently. Test a restricted staff account.
6. Reboot and check both services, profiles and logs. Interrupt a download and test Retry.
7. Check RCON/players, scheduled warnings/actions, backups, themes and notification delivery.
8. Test an update of an existing legacy installation separately; fresh installation does not exercise that path.

The panel does not configure firewall/NAT rules. Check the router's current forwarding targets before diagnosing a join failure. Keep RCON private.

For game settings, use [Bohemia's server configuration reference](https://community.bistudio.com/wiki/Arma_Reforger:Server_Config).
