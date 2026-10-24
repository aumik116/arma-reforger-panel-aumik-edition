# FIELDHQ user manual

This manual is for people using the web panel to manage Arma Reforger servers and unit records. Installation, service recovery and host administration are covered in the [operations guide](operations.md).

For a guide focused on unit work, use the [unit staff manual](unit-staff-manual.md).

The panel currently manages servers on one host. A unit is an organizational workspace; a server is a game-server installation. Linking the two does not automatically give unit staff permission to control the server.

## Contents

1. [Sign in and find your workspace](#1-sign-in-and-find-your-workspace)
2. [Accounts, roles and access](#2-accounts-roles-and-access)
3. [All servers](#3-all-servers)
4. [Create or clone a server](#4-create-or-clone-a-server)
5. [Dashboard and console](#5-dashboard-and-console)
6. [Settings, scenarios and startup](#6-settings-scenarios-and-startup)
7. [Mods and the addition queue](#7-mods-and-the-addition-queue)
8. [Presets](#8-presets)
9. [Players and announcements](#9-players-and-announcements)
10. [Schedules and updates](#10-schedules-and-updates)
11. [Files, saves and recovery](#11-files-saves-and-recovery)
12. [Set up a unit](#12-set-up-a-unit)
13. [Manage the roster and member records](#13-manage-the-roster-and-member-records)
14. [Structure, positions and billets](#14-structure-positions-and-billets)
15. [Qualifications and promotions](#15-qualifications-and-promotions)
16. [Events and attendance](#16-events-and-attendance)
17. [References, awards, campaigns and analytics](#17-references-awards-campaigns-and-analytics)
18. [Common problems](#18-common-problems)
19. [Quick operating checklists](#19-quick-operating-checklists)

## 1. Sign in and find your workspace

1. Open the panel address provided by your administrator.
2. Sign in with your panel username and password. Unit staff use the same login page as hosting staff.
3. Choose **Hosting** for servers or **Units** / **Units & rosters** for unit work.
4. In Hosting, select a server and choose **Open**, or use the server selector in its workspace.
5. In Units, select your unit, then the workspace area and page you need.

Only units and servers available to your account appear. A unit-only staff account may have no hosting workspace to open. A roster member does not need a panel account.

### Your account and theme

Open **Account settings** to change your password or color theme. Themes save to your account automatically. They keep the same layout and features. Original also uses square corners, firmer borders and rectangular controls for a boxier appearance.

Available themes: Slate, Field Desk, Operations, Tactical, Original, Field, Forest and Light. Field Desk and Light provide light appearances.

### Saving and restarting

| Action | When it takes effect |
| --- | --- |
| Save a roster record, note or reference | After the save succeeds |
| Change your theme | Immediately; preference is saved automatically |
| Add a mod to the queue | Queue only; active configuration is unchanged |
| Add queued mods or save a mod/configuration change | Configuration is saved; game changes load at the next start/restart |
| Save startup/resource settings | Next server start |
| Start, Stop or Restart | Begins a server operation immediately after any confirmation |
| Create a schedule | Saves a future job; the panel service executes it |

Switching servers reloads the workspace. Save or discard edits before switching. If the panel reports that something changed since you opened a form, refresh it and review the latest information before trying again.

### Help inside the panel

Choose **Help** in the header to read guidance for the current server tab or unit page. The help window links to the relevant manual section and both full manuals. In the manual page, use text search or Download PDF for a printable copy. Opening help does not discard your current form edits.

## 2. Accounts, roles and access

There are separate layers of access:

- **Panel owner / panel administrator:** panel-wide account and unit administration. The owner retains overall authority.
- **Server role:** what an account may do on a particular server, or on all servers if explicitly granted that scope.
- **Unit role and permissions:** what staff may do in a particular unit.
- **Game administrator:** an identity in the Reforger server's in-game admin list. This is separate from a panel login.

### Server roles

The table describes the role capabilities. An administrator must also assign the relevant server access.

| Role | Typical capabilities |
| --- | --- |
| Viewer | Read server information |
| Operator | Viewer capabilities, logs, Start/Stop/Restart |
| Manager | Operator capabilities, mod management, permitted configuration changes and activity |
| Administrator | Advanced server configuration, files, moderation, startup, schedules and maintenance |

Panel-wide powers depend on panel administration and access assignments as well as the server role. Being an administrator of one server does not automatically make someone the panel owner.

### Create or edit an account

Panel administrators use the user-management controls in **Administration**:

1. Create an account or choose **Edit** on an existing user.
2. Use the **Account**, **Servers** and **Units** tabs to assign the relevant access.
3. Review the assignments and save.
4. Give a new user their username, initial password and panel address through your normal staff process.

Use the separate password-reset action when someone needs replacement credentials. Disabling an account prevents it from being used to sign in. Deleting an account has additional membership and ownership checks.

### Unit staff

There are two unit roles. **Staff** manage rosters, notes, assignments, qualifications, promotion reviews, events, attendance, SOPs/loadouts, awards and campaigns. **Unit administrators** additionally manage staff access, rank rules/catalogs, structure, branding and permanent member deletion. There are no individual permission switches. Unit authority grants no automatic hosting control.

Inside a unit, **Administration → Staff access → Add staff** lets permitted administrators assign an existing account. Panel administrators can also create a new staff login there. Link the account to its roster member when applicable; this provides the person's unit-specific name for notes and history.

## 3. All servers

**All servers** is the hosting overview. Its counters summarize the fleet and host; rows show individual servers. Use search, unit and status filters to narrow the list.

Common row actions:

- **Open:** enter that server's workspace.
- **Start:** launch a stopped server.
- **Stop:** disconnect players and stop the game process after confirmation.
- **Restart:** stop and start the server after confirmation.
- **Startup:** open launch settings and diagnostics, when permitted.
- **Clone:** prepare a new server from this server's settings.
- **Remove:** remove the server from the panel, with a choice about its files.

A running process is not proof that a mission has finished loading or that players can reach it. Check logs and try joining when confirming readiness.

### Read the counters correctly

- Host CPU, host memory and filesystem capacity describe the host, not one game process.
- Server CPU and memory describe that server's process. CPU usage may exceed 100% when multiple cores are in use.
- An unknown player count is shown as unavailable rather than assumed to be zero.
- Live metrics normally arrive about every two seconds, with a polling fallback. Other information updates less frequently. Hidden browser tabs pause routine display updates.

### Storage

Choose **Storage** for measurements and free-space counters. Panel administrators see the host overview; other staff see measurements for servers they can access.

Measurements are requested in the background and cached for ten minutes. A partial result means the scan hit its time/file limit or could not read some files. Refresh to request a new measurement.

**Logical size** is the sum of file sizes. It can differ from actual disk consumption because local mod copies may share physical blocks through copy-on-write. Filesystem usage also includes other files on the host.

Panel administrators can open **Clean up deleted servers** from Storage. Review the retained folder and type its server ID before permanent deletion. This can find recognized server folders left by older removals. Unrecognized folders are excluded; an empty list does not prove the entire host has no unused files.

## 4. Create or clone a server

Creating servers requires panel administration access.

### Create from defaults

1. On **All servers**, choose **New server**.
2. Enter a name and permanent **Server ID**. IDs use lowercase letters, digits and hyphens, beginning with a letter.
3. Leave the starting configuration at defaults, or select an existing server.
4. Review the player limit and FPS cap.
5. Enter the public IPv4 address if needed. Blank uses automatic detection.
6. Leave custom ports blank for automatic allocation, or enter unused ports deliberately.
7. Choose **Create and start server**.
8. Watch provisioning and startup output. If installation is interrupted, use the offered progress/retry controls.

Creating a server installs and starts it. The public address field does not configure your router, firewall or NAT.

### Clone an existing server

1. Choose **Clone** on its All Servers row.
2. Review the suggested name, new ID, source, player limit and FPS cap.
3. Review address/port settings, then choose **Create and start server**.

The clone copies configuration and mod selections, with fresh endpoints and separate server files. Passwords, in-game administrator assignments and save files are not copied. Existing local game/mod downloads can be reused; this is not a shared writable installation.

## 5. Dashboard and console

The dashboard is arranged as:

1. Population counters: players, AI and vehicles; uptime and resource counters.
2. CPU and memory charts.
3. Network traffic and server simulation FPS.
4. Full-width console preview.
5. Storage breakdown and disk activity.
6. Expandable player and additional details.

Network traffic covers host interfaces and can include traffic unrelated to this game server. Simulation FPS is the server's simulation rate, not a player's graphics frame rate. Missing telemetry remains unavailable until the appropriate server data is collected.

### Use the console

Open **Console**, or choose **Open console** from the dashboard.

- Search or filter the output to find errors, warnings, player events or other messages.
- Pause auto-scroll while reading older lines.
- Toggle performance messages if they obscure other output.
- Export the displayed log when sharing a problem with your administrator.
- Use the command controls only if your role permits RCON commands.

Console messages are game output. **Activity** is the separate history of panel actions and the accounts that performed them.

### Activity history

Panel Activity records who performed panel actions and when. Open Administration → Activity and filter the recorded actions. Mod history focuses on mod changes. This is separate from live game console output; earlier events that were never recorded cannot be reconstructed.

## 6. Settings, scenarios and startup

### Edit configuration

1. Open the server and choose **Server config**.
2. Open the relevant settings category.
3. Make your changes and review the unsaved-change indicator.
4. Save, then start/restart when ready for the game to use them.

Use Discard/Reload to abandon edits. Reloading after another staff member changed the configuration avoids overwriting their work. Some fields are administrator-only even when Managers can change other settings.

### Pick a map or scenario

1. Choose **Browse maps & scenarios** in Server config, or **Browse installed scenarios** in Workshop.
2. Search by name and filter built-in or Workshop content.
3. Review the source and description. Thumbnails appear when available.
4. Choose **Use scenario**. If its installed owning mod is not configured, the action may instead say **Use scenario + add mod**; mod permission is also required.
5. Start/restart when ready.

Use **Rescan installed scenarios** after installing new content. If ownership cannot be identified locally, check the configured mod list before starting. A scenario absent from local discovery may still require a custom scenario resource in Server config.

### Startup and resources

**Startup** contains the FPS cap, CPU allocation, memory targets and supported advanced launch options.

- An FPS cap of **0** disables the cap.
- Blank CPU ranges mean all CPUs; resource presets fill the draft for review.
- A soft memory target encourages memory reclamation under pressure.
- A hard memory cap can terminate the game if exceeded.
- Saving startup settings does not restart the game.

Use **Startup diagnostics** and recent output when a server fails to start. Avoid changing advanced AI or single-threaded options without a specific reason.

### Network readings

The Network page shows host interface traffic and available player/network readings. Host traffic includes other services and other game servers; dividing it by the player count is only a rough estimate. Review game/query/RCON endpoints and listener information when investigating connectivity. Public reachability still depends on firewall, routing and NAT outside the panel. Supported configuration edits apply on the next game-server start.

## 7. Mods and the addition queue

The Mods pages separate different tasks:

| Page | Purpose |
| --- | --- |
| Workshop | Find mods and inspect published details/dependencies |
| Configured | Manage the server's saved mod list |
| Downloaded files | Inspect local files and their relationship to configuration |
| Updates | Review available version changes |
| Compare lists | Compare another server or JSON list and choose changes |
| Presets | Save and apply reusable configurations |

A configured mod is selected for use at startup. A downloaded mod has files on disk. Neither label alone proves what an already-running game process loaded.

### Add one mod now

1. Find it in **Workshop**.
2. Choose **Add now**.
3. Review the proposed configuration changes and dependencies.
4. Save the changes.
5. Start/restart the server when ready.

“Add now” saves the configuration through a review flow; it does not force an immediate restart.

### Queue several additions

1. Choose **Add to queue** on the desired Workshop cards.
2. Open **Review queue**.
3. Review only the pending additions, including known dependencies.
4. Use a row's **Remove** button to take that mod out of the queue. It does not remove an existing configured mod or delete files.
5. Check the storage estimate counter. Unknown sizes are identified separately.
6. Choose **Add queued mods** to merge additions into the current configuration, or **Cancel** to close and keep the queue.

The queue does not display or replace the server's entire existing mod list. Adding the queue does not restart the server. Removing a queued dependency does not establish that the remaining mods will work without it.

### Latest and pinned versions

**Latest** means there is no explicit version pin. Reforger handles any required update/download when the game starts. A **pin** requests a specific release.

For supported addition/review flows, if an unpinned addition matches a pin configured on an accessible running server, a popup offers:

- Latest release; or
- A matching pinned release, with the source server names.

Choose deliberately, then continue. A queued choice is remembered. Matching a pin can be useful for a shared event; it does not prove compatibility with every other mod.

### Automatic local copying

The panel looks for compatible downloads on other servers your account can access. A pinned mod needs the exact version; an unpinned mod can start from the newest detected local copy, with Reforger handling further updates.

- On a stopped server, additions can be copied in the background.
- On a running server, copying waits until its next start/restart.
- Copy-on-write is used when supported; otherwise an ordinary independent copy is made.
- Existing destination downloads are not overwritten by this reuse step.
- If no suitable copy is available, normal downloading handles it.

No extra checkbox is required. This also applies to imports, presets and known dependencies.

### Find recently added or unused-looking mods

Use the Configured list's sorting controls, including **Recently added**. This means added to this server's configuration, not published recently on Workshop. Older changes without recorded history may lack an exact added date.

Use **Downloaded files** to filter mods not in configuration. Dependencies can be needed without being directly configured. “Usage unverified” means the panel lacks complete metadata, not that the files are safe to delete.

### Remove mods

1. Select the configured mods using their checkboxes.
2. Choose the bulk removal action.
3. Review the list and select the removal mode:
   - **Configuration only:** remove selections but keep downloaded files.
   - **Complete removal:** remove selections and their local downloads.
4. Read dependency warnings. You can also include mods that depend on the selected items.
5. Complete the acknowledgement and confirm.

Complete removal requires the game server to be stopped and the necessary administrator permission. Unknown dependency metadata does not by itself block removal, but unsafe filesystem conditions can still prevent deleting files. Removing a dependency may make other content fail to load.

### Import, export and compare

Use Configured's **Actions** for JSON import/export. Review the import mode before saving: adding/merging and replacing have different effects.

**Compare lists** accepts an ArmaHQ server or pasted JSON. Select the additions, removals or version differences you want, then review the changes. Source information can lag behind the game server. Matching a source version may create an explicit pin. Compare again after applying if further differences remain.

## 8. Presets

There is one **Mods → Presets** page. The contents selector offers:

| Contents | What is saved |
| --- | --- |
| Mods only | Configured mod list and version pins |
| Scenario + mods | Scenario plus configured mod list |
| Full gameplay setup | Scenario, mods and supported player-limit, visibility, crossplay, gameplay and AI settings |

Credentials, ports, in-game administrator assignments, persistence configuration and save files are excluded. A preset is not a world/save backup.

### Save or overwrite

1. Configure the server and save any pending edits.
2. Open Presets and choose the contents.
3. Enter a name and choose **Save current setup**.
4. To replace an existing preset, select it, review the contents choice and choose **Overwrite selected**.

New presets belong to this server. Older shared sets are retained and labeled **Shared legacy**. Editing a shared legacy preset affects the shared set.

### Apply a preset

1. Select it and choose **Review / switch**.
2. Review settings, mod additions/removals, pins and available size estimates.
3. Choose **Apply preset**.
4. Start/restart when ready.

Full gameplay setups require a stopped server. Mods-only and scenario/mod presets save configuration without automatically restarting. Applying a preset can remove existing configured mods that are not in that preset; downloaded files are retained.

Deleting a preset removes the saved setup, not the live server configuration or downloaded mods.

## 9. Players and announcements

### Connected players and recorded history

Open **Players**:

- **Connected** shows a successful live roster query.
- **Player history** shows identities previously observed on this server, with first/last-seen information.
- **Player sessions** shows separate observed visits and approximate duration.

Session records begin when this feature starts collecting. Older aggregate first/last-seen records cannot reconstruct past visits. Samples normally occur about every 30 seconds in the panel service; brief connections may be missed. Query errors do not confirm a departure. Gaps over 90 seconds split observations instead of counting the entire gap as playtime.

Use **Copy identity** when linking a player or providing an ID to another permitted staff member. Server administrators can use the moderation controls, review live bans, or grant/revoke in-game administrator access. Changes to the configured game-admin list need a restart.

### Send or schedule a message

1. On Players or Scheduler, choose **Player announcement / warned restart**.
2. Choose Send now, Schedule message, or Schedule restart with warnings.
3. Enter a message or choose a template. For delayed actions, enter the delay in minutes.
4. Review and submit.

Messages require working admin RCON and Server Admin Tools `#message` support. A sent RCON command is not proof that every player saw the message.

Warned restarts require at least six minutes of lead time and use automatic five-minute and one-minute warnings. Review or cancel pending jobs in Scheduler.

## 10. Schedules and updates

### Schedule work

1. Open **Scheduler** on the intended server.
2. Enter a name, action and future first-run time.
3. Choose once, a supported hourly interval, daily or weekly recurrence.
4. Review the clock information shown by the form and save.
5. Review the schedule list and **Run history** for outcomes.

Scheduling uses the host/server clock shown in the form. This is separate from the explicit timezones used by unit events. The Linux panel service must remain running; an open browser is not required.

Running servers need successful five-minute and one-minute warnings before scheduled restart, stop or update operations. Missed/failed warnings skip the run. Missed jobs are reported instead of blindly replayed. A schedule owner's permissions are rechecked at execution.

**Run on next tick** queues eligible non-disruptive work. **Queue with warnings** schedules disruptive work with lead time. These do not alter the original recurring schedule.

### Check and update server software

On **All servers**:

1. Choose **Check for updates** to inspect build status.
2. Choose **Master update** when ready to install server software.
3. Select the servers to update.
4. Review the running/stopped indicators and restart behavior.
5. Confirm and follow progress.

The workflow downloads the server software once and distributes/validates it for selected installations. Previously running servers are stopped and restarted on success; previously stopped servers stay stopped. Failures may leave affected servers stopped for inspection.

Master update covers the game-server software, not Workshop mods. Do not assume an immediate Master update has the scheduler's advance warning sequence; plan downtime or notify players first.

### Server notifications

Server administrators can configure notifications under Administration → Notifications. Settings belong to the selected server. Review the event choices and any configured delivery destination, save, and use the offered test action to confirm delivery. Notification history is separate from live game logs; a notification does not prove a mission is reachable by players.

## 11. Files, saves and recovery

### Files

Use **Files** to browse permitted server locations, upload files and edit supported text files. Save edits explicitly. Deleted items moved to panel Trash can be restored through its controls.

A normal file deletion to Trash is different from permanent server deletion or complete mod removal. Read the operation's confirmation rather than assuming all deletions are reversible.

### Persistence

Use **Persistence** for the game's save settings, startup save selection and available save maintenance/backup controls.

- Confirm the intended scenario before choosing a startup save.
- Saving persistence settings does not immediately reload the world.
- Deleting/resetting world or player saves is destructive; review the exact scope shown in the confirmation.
- Configuration backups do not contain world saves, Workshop downloads or the entire host.

### Configuration backups

In **Administration → Maintenance**, review saved configuration versions before restoring. The current configuration is backed up before a restoration. Restart afterward when needed to use the restored settings.

Scheduler's **Backup** action is a configuration backup, not a full server backup. Arrange host/database/save backups separately with your administrator.

### Remove a server

1. On All servers, choose **Remove**.
2. Review the server and folder.
3. Choose retain files or permanently delete them.
4. Type the exact server ID and confirm.

The server is stopped before removal. Retained files can be cleaned up later through Storage. Permanent deletion includes that installation's game files, mods, profile/saves, logs and backups. It cannot be undone through the panel.

## 12. Set up a unit

Panel administrators create units and link servers. Unit administrators then manage the permitted unit records and staff.

A practical setup order:

1. Create the unit and link its game server(s).
2. Assign its unit administrators and staff.
3. Under **Resources → Rank rules & catalogs**, define qualifications, position suggestions and any rank structures.
4. If using organized slots, build **Administration → Structure**.
5. Add members manually to the roster and link recorded UUIDs.
6. Create events with attendance tracking.

The workspace groups pages under Overview, Roster, Operations, Resources and Administration. Pages appear according to permissions. A unit can use a flat member roster without building groups or sections.

### Branding

Under **Administration → Customization**, set a short description, icon and banner. Upload PNG, JPEG or WebP images up to 4 MB each. A square icon and wide banner work best. Preview, replace or remove images, then save.

Branding belongs to the unit. It does not replace an individual staff member's personal color theme.

## 13. Manage the roster and member records

### Add a member

1. Open the unit's **Roster** and add a roster member.
2. Enter their game name and optional Discord handle.
3. Choose Active, Reserve or LOA.
4. Add optional rank structure/rank, primary billet, joined date and last-promotion date.
5. Assign qualifications and save.

Ranks and organizational structure are optional. Each unit keeps its own record: the same person can have different names, ranks, qualifications and statuses in different units.

### Link a recorded UUID

In the member editor, search recorded player names or UUIDs from the unit's linked servers and select the correct identity. Leave it blank if they have not yet been recorded, then return after they play.

A game name alone does not link attendance. Verify the selected identity belongs to the intended person.

### Link a panel account

Choose the person's **Linked panel account** in their roster record. This associates the login with that member's unit name for note authorship. Linking does not grant unit or server permissions; staff access is assigned separately.

### Open a member's record

Open the member record to see their details, qualifications, medals, attendance and recorded timeline. Add a dated staff note for persistent context. The author uses their linked name in that unit when available, so the same staff login can use different unit names in different units.

The timeline records changes from when collection began. An upgrade baseline is not a reconstruction of older history.

### Status, archiving and deletion

| Choice | Meaning |
| --- | --- |
| Active | Normally expected for tracked events |
| Reserve | Optional attendance expectation |
| LOA | Excused from attendance expectations; an optional end date can be recorded |
| Former member / archive | Keep the record and history, exclude it from the current roster |
| Permanent deletion | Remove the member record, notes, timeline and qualification records after confirmation |

Historical attendance snapshots already captured for events remain when a roster record is permanently deleted. Archive members when you want to retain their personnel record.

### Bulk editing and export

Use **Bulk edit…** to select current members and change supported statuses, qualifications or assignments. Review the generated before/after list before confirming. A move into a section needs enough available slots; stale data or insufficient vacancies reject the batch.

Use roster CSV export when you need a spreadsheet copy. There is no requirement to maintain or import a separate spreadsheet.

## 14. Structure, positions and billets

Use the flat roster for a simple list. Use Structure when you want an organization chart made of occupied and open slots.

- **Groups:** broad containers, such as a platoon or staff organization.
- **Sections:** subdivisions, such as platoon HQ, a squad or a mortar section.
- **Billets:** actual assignable slots, such as Platoon Sergeant, Rifleman or Vehicle Commander.
- **Position suggestions/catalog entries:** reusable names; a name in the catalog is not itself an occupied slot.

In **Administration → Structure**, create the groups and sections you need, then add billets. Assign a member through the slot controls or their **Primary billet** field.

Each member has one primary billet. Empty billets remain visible and contribute to open/filled counts. Assigning a member to a different billet leaves their old one open. Rank and qualification requirements do not restrict assignments.

Review the consequences before removing a group, section or billet. These tools change organization and assignments; permanent member deletion is a separate roster action.

## 15. Qualifications and promotions

### Qualifications/certifications

Create the qualification catalog first. On **Qualifications**, use the member-by-qualification matrix to inspect coverage, filter members, and identify who holds or lacks an award.

Open a cell to grant a qualification, correct its date/issuer/notes, or revoke it when permitted. Previously imported/older assignments may have unknown original dates or issuers until staff correct them. The timeline records who made the correction.

### Rank structures

Create separate structures when advancement differs: for example Marine, Medical and Officer. Define each rank's name, optional paygrade label, next rank, time requirement and required qualifications.

**The next rank's time requirement is added to the member's last-promotion date.** For example: if the next rank requires 30 days and the member was last promoted on June 1, the date requirement becomes July 1. Missing qualifications still prevent eligibility. Enter an accurate last-promotion date so the panel can calculate readiness.

A paygrade label does not merge different advancement paths. Members select the appropriate rank structure in their own unit record.

### Review a promotion

1. Open **Promotions** and inspect readiness or missing requirements.
2. Choose **Review promotion** for an eligible member.
3. Review the proposed rank and date, enter the required staff note and confirm.
4. If the roster or eligibility changed, refresh and review again.

Eligibility is a notice for staff. The panel never automatically promotes a member.

## 16. Events and attendance

### Create an event

1. Open **Operations → Events** and choose **New event**.
2. Select the linked server, local start time, explicit timezone and duration.
3. Enable attendance tracking.
4. Choose recurrence if needed: weekly, biweekly or monthly options create separate occurrences.
5. Save and review the calendar.

Recurring events can be edited for one occurrence or the remaining series as offered by the form. There is no shared-server reservation calendar or joint-unit attendance workflow.

### How automatic attendance works

- The member must have the correct recorded UUID linked.
- The event must track attendance on the selected linked server.
- The panel service must be collecting a successful live player list.
- Seeing that UUID once during the event is enough to count as Present.
- Connections outside tracked events do not count.

Membership status and attendance outcomes are different things. Active/Reserve/LOA describe the roster; Present/Absent/Excused/Unknown describe an event record.

Event membership follows roster changes until the event starts, then preserves the relevant names, UUIDs and expectations. Joined dates exclude events before membership.

### Review and finalize

1. Open the event after it ends.
2. Review automatic evidence and any collector gaps.
3. Correct outcomes if necessary and give the required reason.
4. Finalize the event.
5. Use Attendance to inspect the monthly grid or export CSV.

Missing evidence is not always proof of absence: an unavailable collector can leave Unknown outcomes. Finalized records can be reopened with a reason. Cancelled events are excluded from reporting.

Normal attendance percentages use finalized, expected Present/Absent decisions. Reserve is optional; LOA/Excused, Unknown and pending outcomes are excluded from that percentage. Attendance information is for authorized unit staff.

## 17. References, awards, campaigns and analytics

### SOPs and loadouts

Use **SOPs & loadouts** to search references by category, role or text. Permitted staff can create SOP text/external links and loadouts with image URLs, kit slots, alternatives and notes. Archive obsolete references rather than losing their editing history.

### Awards

Create medals/badges in the unit award catalog, then issue them to members with a date and citation. Repeated issues require explicit confirmation. Revoking an award requires a reason and retains the original issue history.

Issued names/images are preserved if the catalog later changes. These awards are separate from qualifications used in promotion requirements.

### Campaigns

Create a campaign from a timezone-aware event window or explicit event selection. Set its participation threshold and optional linked award. Review progress, complete the campaign and finalize its tracked events before approving member awards.

Campaign progress uses confirmed Present outcomes against eligible finalized events. Reserve events count here; LOA and Excused are exempt. Unknown remains unconfirmed. This is different from the normal attendance percentage. Date-window campaigns must also reach the window's end. Awards are never automatically granted or revoked.

### Analytics

Choose a date range and timezone to view recorded strength, membership changes, retention and finalized attendance trends. Tables accompany the charts. Strength/retention collection starts when the feature is installed; earlier history is not invented. Rank distribution describes the current roster.

## 18. Common problems

| What you see | What to do |
| --- | --- |
| A unit, server or action is missing | Ask an administrator to check unit membership/role and direct server roles separately. |
| Server says Online but nobody can join | Check mission/startup output, game/query ports, advertised address, firewall and NAT. Ask the host administrator if needed. |
| Player count is unavailable | Check the selected server's RCON configuration/reachability. Do not treat unavailable as zero. |
| Message or restart warnings fail | Verify admin RCON and Server Admin Tools `#message` support. Read Scheduler run history; failed warnings can skip a run. |
| A scheduled job did not run | Check the shown server clock, panel service/worker status, owner permissions and run history. Missed jobs are not automatically replayed. |
| Queue storage total looks too small | Unknown sizes are not included in the known total. Metadata estimates are not physical disk measurements. |
| A queued mod is absent from Review queue | It may already be configured, or another staff member may have changed the queue. Refresh the review. |
| Removed mod still has files | Configuration-only removal retains downloads. Inspect Downloaded files and use complete removal on a stopped server if intended. |
| A new scenario is missing | Rescan installed scenarios and confirm its mod actually downloaded. Check the full scenario resource if discovery cannot identify it. |
| Preset or queue reports stale data | Reopen the review; another change occurred. Review the new state before applying. |
| Member has no attendance | Check UUID linkage, linked server, event timing/tracking and collector evidence. Logging in outside an event does not count. |
| Member has no promotion date | Check their rank structure, next-rank rule and last-promotion date. Missing qualifications still block readiness. |
| The theme changes but the layout does not | Expected: all themes share the same layout. |
| A form has different controls from this manual | Confirm the panel is updated and check your permissions. Features may be hidden for your account. |

When reporting a problem, include the server/unit name, page and action, time, exact error, and relevant output or a screenshot. Do not include passwords, private tokens or full credentials.

## 19. Quick operating checklists

### Before an operation

1. Select the correct server and unit.
2. Apply the intended preset while stopped if using a full setup.
3. Review scenario/mod selections and finish any queued additions.
4. Start the server, inspect mission output and confirm a player can join.
5. Confirm the unit event uses this server/timezone and tracks attendance.
6. Check important members have their correct UUIDs linked.

### After an operation

1. Review event evidence and collector gaps.
2. Correct outcomes with reasons and finalize attendance.
3. Add necessary member notes, qualifications or award records.
4. Stop the server if it is no longer needed, or leave it running according to your unit's policy.

### Before maintenance

1. Notify affected staff/players and choose a downtime window.
2. Confirm what your backups actually contain; configuration backups are not save/host backups.
3. Stop affected servers when the operation requires it.
4. Review update/removal selections carefully.
5. Inspect results and start only the servers that should be running.
6. Confirm the mission and player connectivity afterward.
