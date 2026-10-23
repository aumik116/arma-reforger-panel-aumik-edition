# Operations guide

[Back to installation and the workspace overview](../README.md).

## All servers dashboard

The totals and rows cover servers your account can access. Search and status filters narrow the rows without changing totals. Click a server row to open that server's dashboard; Start, Stop and Restart use that row's server and permissions. Stop and Restart ask for confirmation. Open and server controls stay on each row; Startup and Remove are in its More menu.

Player activity is the combined count from available rosters. A `+` on the total means some readings are missing; the chart leaves a gap rather than treating those servers as empty. Host CPU and memory cover the whole VM, while rows show individual game-process usage. Host CPU needs two samples after the panel starts.

Server rows show the Workshop preview image for the configured scenario when its configured Workshop item publishes a matching scenario ID. Metadata is cached and loads in the background. Vanilla scenarios, missing Workshop metadata and image failures display a neutral placeholder. These are Workshop item previews, not live map screenshots.

Charts keep up to 30 minutes of readings while this page is open and reset on reload. Alerts show current failures, status changes observed while the page is open, and the latest permitted administrative activity. An online-to-offline change records a stop or exit; it does not establish whether the process crashed. Player joins and leaves are not listed. If a refresh fails, the page marks the retained server readings as potentially out of date.


### Check for updates and Master update

**Check for updates** queries the public Steam build without updating game files or stopping servers. The overview shows installed Steam build IDs for servers you administer; these are not Arma version numbers.

**Master update** opens a server-selection dialog. Confirming downloads and validates a shared copy under `INSTANCE_ROOT/.software-cache` before stopping any selected server. Each selected server is then stopped, copied and validated in turn. Servers that were running when you confirmed are restarted with a process-health check; previously stopped servers stay stopped. Mission loading and player connectivity are separate from that process-health check.

This updates the public Arma dedicated-server software only. It does not change Workshop mod pins, configuration, profiles or saves. Steam validation can fetch missing/different files, so the shared download reduces repeated bulk transfers rather than guaranteeing zero additional downloads. Budget space for an additional game installation in the shared cache plus temporary replacement files. Custom beta installations are rejected.

The batch continues independently of the browser, with per-server stages and results. Selected servers are locked against conflicting panel changes and scheduled operations during the batch. A failed copy, validation or restart leaves that server stopped where service control succeeds; review the result and retry using Master update. An interrupted worker is reported as interrupted rather than completed. A shared-download failure does not stop the selected servers. Each target requires server-administrator permission; permissions are checked again before applying its update.


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

Configured mods have selection checkboxes. **Select all filtered mods** includes every matching page, and selections persist across search and pagination. **Remove selected** (or a row’s **Remove**) opens a confirmation popup: remove from configuration while retaining downloads, or remove completely. Configuration-only removal can run while the game is online and takes effect after restart. Complete removal requires server administrator access and a stopped server; it removes only the selected mods’ downloaded folders, keeps saves and unselected dependencies, and refuses deletion when remaining dependencies cannot be verified. Configuration changes are backed up through the existing configuration backup flow.

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

The compact reference layout uses local SVG icons, bundled Barlow fonts (SIL Open Font License, included under `static/fonts`), and a contour header. The Dashboard places player and resource charts above the live console and roster; additional performance readings are under More performance details. Its player chart retains 60 roster readings in browser memory, with unavailable readings shown as gaps. The Mods table includes Workshop thumbnails and shortcuts to existing saved presets. Maintenance retains the actual server software and configuration-backup controls.

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

## Mod sorting and downloaded files

The configured mod list can be sorted by load order, recently/oldest added, name A–Z/Z–A, and largest/smallest Workshop download estimate. Sorting changes the display only; Reorder remains the explicit operation that changes game load order. The sort choice is remembered in the browser.

Addition dates come from successful panel activity records for that server (up to the latest 10,000 recorded mod-addition events across the panel). Existing mods without a recorded addition are shown with unknown dates and sorted last. Edits made outside the panel do not have reliable addition dates; the displayed date is the last recorded panel addition, not a filesystem timestamp.

**Downloaded files** scans the selected server's configured Workshop directory, with search, usage filters, size sorting and refresh. It shows local metadata versions and logical disk sizes separately from Workshop download estimates. The background scan is bounded and cached for five minutes; partial results are labelled. Links are not followed.

Usage is compared with the saved configuration, not the currently loaded game process. Direct entries are Configured; reachable dependencies from local metadata are Known dependencies. When dependency metadata or the scan is incomplete, other downloads are Usage unverified. A download absent from the configuration must not automatically be treated as safe to delete. This view does not delete files.

### Live metrics

Dashboard, Network and All Servers receive server-sent resource readings about every two seconds while visible. Snapshots are shared across viewers within the panel process; idle pages close their stream. The stream rechecks account and server access on each frame and reconnects automatically. If it stalls, metrics fall back to ten-second requests. Reverse proxies must allow streaming (disable response buffering); the endpoint sends `X-Accel-Buffering: no`.

Player queries retain their ten-second cache and run separately so unavailable RCON cannot block CPU/RAM updates. Configuration, alerts, previews and player rosters retain their slower refreshes. All Servers history remains one sample every ten seconds, with the existing 30-minute in-browser limit; no new database history is written. Each open page uses one streaming connection/thread. Collection is demand-driven, so no metrics are collected for pages nobody is viewing.

## Units and staff rosters

Open **Units & rosters** from All Servers or a server workspace. This page does not require a server control grant. Only the Owner and panel administrators see all units; other accounts see their assigned units. Panel administrators create units and link servers, including servers shared by multiple units. These links grant basic health visibility, not server controls, files, credentials, or access to another unit's records. Existing server roles remain separate.

Panel administrators can use **Staff access → Add staff** within a unit to create a login, choose Staff or Unit administrator, select roster/events/attendance capabilities and optionally link a roster member in one transaction. Switch to Existing account to assign a login already created. Unit administrators use the same popup for existing accounts only. Creating a login here explicitly sets panel administration off and all-server access off, without granting server roles. A link already held by another account is rejected; editing a membership can change or clear its roster link, while removing staff access preserves the existing link and roster record. All staff use the normal panel login page. The user editor has Account, Servers and Units tabs, password reset, access filters and an unsaved-change warning. Unit administrators manage existing staff accounts in their own unit; they cannot create accounts or grant panel/server privileges. Staff can view the unit and optionally edit its roster. The last enabled unit administrator cannot be removed or disabled. The Owner remains protected.

Roster members do not need panel accounts. Enter their game name and Discord handle, select an optional recorded Reforger UUID from a linked server's player history, and choose Active, Reserve or LOA. Rank, primary billet, join date, last promotion date, LOA end date and notes are optional. LOA status is changed by staff, not automatically when the date passes. Former members are archived and can be restored; their records are retained. A person can have separate ranks, statuses, qualifications and a primary billet in each unit. There is no spreadsheet import; CSV export includes promotion estimates and neutralizes spreadsheet formulas.

Unit administrators define qualification/certification and position names. A member may hold multiple qualifications and one primary billet. Position names are suggestions for creating billets. In-use positions can be renamed with **Rename a position**, updating current and former assignments together. Removing an in-use rank or qualification requires first updating the affected roster records. Removing a position-name suggestion does not remove actual billets.

Create independent rank structures, such as Marine Enlisted, Medical and Officer, in **Ranks & qualifications**. Each member chooses an optional structure and a rank within it. Each rank defines an optional paygrade label, the minimum days since the last promotion required to enter that rank, required qualifications and an explicit next rank within the same structure. Rank names may repeat across structures; paygrade labels do not share advancement rules. Next eligibility date is the last promotion date plus the target rank's required days. Missing qualifications are shown separately. Eligibility only notifies staff; promoting someone requires manually updating their rank and last promotion date. No next rank or no last promotion date means no calculated date. Dates use the panel host's calendar date for eligibility. Configuration changes recalculate readiness without changing existing ranks or promotion dates. Billet placement has no rank or qualification requirements.

Upgrading an existing catalog places its ranks into **Existing ranks**, preserving member assignments and combining each former paygrade's requirements with the rank's own requirements. Create the desired independent structures, then edit members to move them to the appropriate structure and rank. Review their last promotion dates when switching structures. Structures and ranks used by current or archived members cannot be removed or renamed until those records are updated.

Account, membership, roster and catalog writes use transactions; roster/catalog editors reject stale unit revisions. Roster edits record before/after values in the activity log, scoped to the unit. Back up the panel SQLite database as part of regular panel backups; game-file backups alone do not include these records.

### Unit events and attendance

The unit Dashboard summarizes staffing, unassigned members, vacancies, promotion readiness, upcoming events and completed events awaiting attendance review. Events are attributed to one unit and one of its linked servers; a shared server alone never grants another unit attendance credit. Discord, RSVPs, joint-operation workflows and server reservations are not included.

Use Events to schedule a name, category, briefing/location, server, timezone, start and duration (5–1440 minutes). Weekly, biweekly and monthly recurrence creates up to 52 occurrences within the next year. Each occurrence has its own roster, evidence and review state. Monthly repeats clamp to the last day when needed. Local times remain consistent across daylight-saving changes; nonexistent local times are rejected, and an ambiguous repeated local time uses its first occurrence. Staff can edit one upcoming occurrence or it and the later scheduled series; already-started or finalized events cannot be rescheduled. Cancellation retains history and excludes the event from reports. Move or cancel upcoming/active events before unlinking their server.

Future event rosters are refreshed whenever members are saved, archived or deleted. At the start, the snapshot freezes: member ID, game name, UUID, status, expectation and exemption. Members whose join date follows the event date are excluded. Active members are expected, Reserve members are optional, and LOA members are excused until staff change their status. Later membership changes, UUID relinking or deletion do not rewrite historical snapshots. Historical attendance is retained even when a member’s current roster record and notes are permanently deleted.

The existing background player-history collector samples the live RCON player list about every 30 seconds. Each valid UUID observed within the event’s half-open start/end window records first/last observation and sample count. A single observation earns Present. These are observation timestamps, not exact connection durations; brief connections between polls may be missed. Repeated cached samples are deduplicated. No telemetry is backfilled from aggregate player history, and connections outside the event window do not count. A linked UUID is captured at event start; correcting a link afterward applies to future events, while staff can correct the earlier event manually. Non-roster UUIDs remain visible for reconciliation without receiving automatic member credit.

Open an event to inspect members, evidence, unmatched UUIDs, sample freshness and gaps. No observation stays Unknown; an offline server, RCON error, stopped collector or missing samples never becomes an automatic absence. Gaps longer than 90 seconds, failed samples or no successful samples flag review. Staff may record Present, Absent, Excused or Unknown with a required correction reason. Corrections retain actor, timestamp, before/after values and reason. Finalize after the event ends to freeze the decisions; reopening also requires a reason. No automatic finalization or automatic absence inference occurs.

The Attendance tab provides a monthly member/event grid, server filtering, all-time last-attended date and CSV export. Members not in an event snapshot display a dash. Percentages use only finalized, expected outcomes explicitly resolved to Present or Absent; pending, Unknown, Excused, LOA and optional Reserve expectations are outside the denominator. Member records show the latest 50 event entries. CSV cells protect against spreadsheet formulas.

Unit administrators automatically manage events and attendance. Staff can receive independent events and attendance capabilities in Staff access or the panel Account/Servers/Units editor. Neither grants server control, roster editing or access to another unit. Writes use SQLite transactions, event versions and series version checks to reject stale changes. Event data, sample timestamps, UUID evidence and audit records are retained in the existing panel database; include it in backups. The collector uses existing RCON credentials and does not require game mods, Discord or a new service.

### Member records

Click a member's name or **Open record** to view their unit-specific profile and staff note history. Staff can read records only in their own units; adding a note requires roster-editing permission or unit/panel administration. Notes have a server timestamp and the author's unit roster name captured at creation when their account is linked; otherwise they use the panel username. Later renames do not rewrite old note authors. They are retained when the member is archived or the author's account is removed. Notes are append-only: add a follow-up correction rather than overwriting an earlier entry. Older entries load in pages of 50 without replacing an unsaved note. The roster summary remains editable separately. Staff record notes are stored in the panel SQLite database and are not included in the general roster CSV export.

### Panel account links and deleting roster members

Unit and panel administrators can select a **Linked panel account** in a member's editor. Each account can link to one roster record per unit, including former members, and can have a different roster name in another unit. Unit administrators choose from staff already assigned to that unit; panel administrators may choose any existing account. A link identifies the person and supplies the author name for future staff notes. It does not create an account, add staff membership or grant server/panel permissions. Roster editors can see existing links but cannot change them. Deleting a login clears its roster links while retaining the members and previously authored notes.

Unit and panel administrators can use **Delete member** in the member editor. The confirmation requires the exact game name and permanently removes that unit's roster record and saved staff notes. It does not delete the linked panel account or change its access, and other units' records remain intact. Use **Former member** instead to keep the record. Audit events remain, and deleted member IDs are never reassigned to a new person.

### Navigation for unit staff

Units & rosters has a prominent shortcut near the top of each sidebar and a button in the All Servers and server workspace headings. Accounts assigned to units but with no all-server or individual server grant land directly on `/units` after login; `/servers` also redirects them there. Staff see only assigned units, with a banner explaining their current access. Read-only staff can inspect rosters, member records, qualifications, promotion readiness and linked-server health. Roster editors also get member editing and note entry. Unit administrators get their unit's staff and catalog controls; panel-wide account management, unit creation and server-link settings stay with panel administrators. A separately assigned hosting role preserves the normal All Servers landing page.

### Structured rosters and primary billets

The roster now has configurable group tabs, sections and billet slots. Unit administrators use **Structure** or **Manage structure** to add, rename, move, reorder and remove items. Groups are the top level; sections can contain subsections for platoons, squads, teams or crews; each billet belongs to a section and holds one member. Repeated billet names such as Rifleman are allowed. The hierarchy supports six levels below a group and up to 2000 items per unit. Position catalog names are suggestions when creating billets; no rank or qualification is required to occupy a slot. Promotion requirements remain separate.

Staff with roster-editing permission can fill an open billet, unassign its occupant or move a member from another billet. A member has one primary slot and an occupied slot cannot be overwritten. Assignments can also be selected in the member editor. Read-only staff can inspect the structure and open member records. Search retains the relevant group/section context, and vacancy counts use all assigned current members rather than just filtered search results. Reserve and LOA members retain their assigned billets unless staff move or unassign them.

Removing structure requires typing its name and removes its descendants and assignments, preserving the people, account links and staff notes. Those members appear under **Unassigned**. Archiving or deleting a member releases their billet. **All members** retains the searchable detailed list, including former records. Existing free-text sections and position labels are preserved, with no guessed slot assignments; staff manually place those members into the new structure. CSV exports include the primary billet and full structure path.


### Qualification records, promotion review and bulk changes

Qualifications has a matrix with member/rank search, current/former and Active/Reserve/LOA filters, group/section/unassigned scope, Holds/Missing filtering for a selected qualification, rank/name/billet sorting and checkmarks-only display. Each coverage card states the count for the search/status/section scope before Holds/Missing filtering, plus the current-unit count. Award details remain accessible from each cell, including in checkmarks-only mode.

Current award metadata is stored beside the existing roster qualification list: award date, issuing staff name within the unit and notes. New grants default the issuing staff name to the actor’s name within the unit; staff can enter the original instructor or correct a legacy issuer explicitly. Correcting a date or note leaves the issuing name unchanged unless that field is edited. The timeline separately logs the actual actor who saved each grant or correction. Revoking requires a reason and retains the earlier grant details in the timeline. Re-granting creates a new award with its own date/issuer. General member-editor qualification changes and bulk operations follow the same recording path. The member editor can set an award date and change note for newly checked qualifications; existing awards keep their metadata. At upgrade, existing held qualifications have unknown original dates and issuers, with an explicit baseline in each member record. No historic events are inferred from the current rank or qualification list.

Promotions is a manual review queue. It shows the configured next rank, eligibility date, missing qualifications and missing advancement setup. An eligible member’s review popup shows the exact rank and panel-calendar date to be applied. A required staff review note and confirmation precede the write. The server checks the unit revision, current eligibility, target rank and confirmed date inside one transaction. Policy edits, qualification revocations, other roster edits or a change of calendar date require reopening the review. The regular member editor remains available for deliberate rank/date corrections; these also enter the timeline.

The member timeline retains actor name, timestamp, before/after state and change note for ranks/promotion dates, billets and paths, qualification grants/revocations/metadata changes, and status/archive changes. Editing or moving a structure node records affected member paths, and removing a structure records released assignments. Timeline filters and cursor pagination load older changes without discarding notes in progress. Archive/restore retains the timeline. Typed-confirmation permanent deletion removes current award metadata and the member timeline as well as notes; event attendance snapshots remain independent historical records.

Bulk edit supports 1–500 distinct current members for qualification grants/revocations, Active/Reserve/LOA status, section moves and primary-billet removal. A reason is required. Section moves retain anyone already assigned beneath the target section, then allocate its vacant billets in structure order to the remaining selected members in member-ID order. No occupied billet is displaced, no extra slot is created and no rank/qualification restriction applies. Too few open billets rejects the preview. Each member’s old and proposed values are shown before a separate confirmation. The server recomputes the plan under a SQLite write transaction, checks the preview digest and unit revision, and applies all changes together. Existing held awards are left unchanged by repeated bulk grants. Future event rosters are refreshed; active and historical event snapshots stay frozen.

All new screens remain unit scoped. Viewing requires unit membership; writes require roster editing or unit/panel administration. There is no new hosting permission or automatic promotion worker. All records live in the existing panel SQLite database and are covered by its backup.


### Unit analytics and reference resources

Analytics accepts an inclusive local date range of up to 366 days and an IANA timezone. It displays recorded daily Active/Reserve/LOA/total strength, roster additions, archive/removal/restoration movements, cohort retention, finalized event turnout and current rank distribution. Strength snapshots and membership spans are seeded at installation and updated transactionally alongside profile creation, status/archive changes, restore and deletion. Dates before tracking show no strength data. Additions and departures describe panel roster changes, not inferred real-world service dates. Cohort retention is the fraction of members present at the measured start who are still on the roster at the end; a member who leaves and returns counts as retained. Starting cohorts before installation are truncated to the tracking baseline. Current rank distribution is explicitly independent of the historical date filter. Attendance trend percentages follow the report denominator: required, finalized Present/Absent decisions; Unknown/Excused and optional Reserve expectations are excluded.

SOPs and loadouts share a unit reference library with search across title, category, role and body, category/archive filters and paginated lists. SOP text is displayed literally, without executing HTML. References can include HTTP/HTTPS links; images use external image URLs loaded by the browser, without a server-side fetch or upload service. Loadout slots have a name, standard item, alternatives and notes. Edits use the unit revision to reject stale writes, store actor/time and before/after content in the unit audit table, and expose the latest 50 edit summaries. Archive a reference to hide it from current results; edit its archived entry to restore it. No reference is published outside the unit.

Award catalogs contain names, descriptions and optional image URLs. Issue an award to a roster record with a date and citation after explicit confirmation. Actor names use the account’s linked game name in that unit. Each issue snapshots the medal name/image, issuer and citation; catalog edits do not rewrite issued medals. Catalog archival blocks new issues but preserves history. Issuing the same medal again requires an explicit additional-award flag; campaign awards instead enforce one active award per member/campaign. Revocation requires a reason and retains the original issue with revoking actor/time/reason. Member drawers and the Awards tab provide paginated award histories. Permanent roster deletion removes that member’s award records and associated award audits, while archived members retain them. Membership-span IDs without stored names and aggregate strength remain for accurate analytics; historical event attendance remains governed by the existing snapshot policy.

Campaigns group same-unit events by an inclusive date window/timezone or a manual list (up to 500 selected events). Active, Completed and Archived states are staff controlled. The event picker includes the latest 1000 events and preserves older existing selections when editing. Campaigns can link an optional medal from this unit’s catalog and require 1–100 percent participation. Participation is confirmed Present / eligible finalized event snapshots. Active and Reserve membership snapshots count as eligible; LOA snapshots and manually Excused events are exempt. Missing membership snapshots do not create expectations for events before a member joined. Unknown is shown as unconfirmed participation and remains in this campaign denominator, without being relabeled Absent or changing normal attendance reports. Readiness uses the exact fraction, while displayed percentages are rounded. Cancelled and untracked events do not contribute. Deleted records can remain represented by their event snapshots but cannot receive new awards.

Campaign award approval requires the campaign to be Completed, all included tracked events to be finalized or cancelled, any date window to have ended, the member to meet the threshold, an active linked medal and no existing active award for that campaign/member. The server recomputes readiness inside the award transaction. Each candidate is approved individually with a citation; there is no automatic end-date award job. Subsequent campaign edits or attendance corrections recalculate progress without silently granting/revoking issued awards; staff may revoke and reissue when necessary. A direct manual medal issue is separate from campaign credit.

References, awards and campaigns use independent unit capabilities (references, awards, campaigns). Unit/panel administrators have all three; ordinary staff need explicit grants to write, while all staff assigned to the unit can read. Campaign-management authority alone cannot issue medals. These capabilities grant no server control, credential access or cross-unit access. API writes use CSRF, unit access checks, SQLite transactions and the shared unit revision; resource writes are also recorded in unit-scoped activity. All new tables remain in the existing panel SQLite database and its backups. Recruiting, Discord output, public embeds and collaborative map tooling remain outside this release.
