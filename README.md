# Arma Reforger Server Management Panel

Manage multiple Arma Reforger dedicated servers on one Ubuntu VM: mods, performance, players, configuration, files and scheduled operations.

The default branch is **`main`**, including the multi-server manager. Fresh Ubuntu installation, Steam downloads and systemd game startup still need real VM verification. Remote nodes are not supported yet.

## Fresh installation

Use **Ubuntu 24.04, x86_64**, a sudo account and enough disk space for each server's game files, mods and saves. The installer installs Python dependencies and prepares SteamCMD.

```bash
git clone https://github.com/aumik116/arma-reforger-panel-aumik-edition.git
cd arma-reforger-panel-aumik-edition
sudo bash install.sh
```

1. Choose the service user, panel password and panel TCP port. The defaults are `arma` and port `8888`.
2. Open `http://YOUR_VM_IP:8888` and sign in as **admin** with that password.
3. From **All servers**, choose **Create server**. Review the name, permanent server ID, player limit, FPS cap and ports.
4. Watch provisioning finish. SteamCMD downloads and validates the game; the new server then starts automatically.

The installer creates the panel first. It does not download a game server until you create one in the browser. `--panel-only` is an alias for this fresh installation flow.

Additional servers can start from defaults or copy a managed server's settings and mod selections. Passwords and saves are not copied. Existing local game files can be reused before Steam validation; each server still has its own files, ports, profile and service.

**Public IPv4 address:** leave blank for automatic detection, or enter the address players should use. For LAN-only testing, use the VM's private IPv4 address. Advertising an address does not configure NAT or prove internet connectivity.

## Units and rosters

Unit administrators can use **Administration → Customization** to upload an icon and page banner, or set a short description. Images are private to authorized unit staff, stored in the panel database (include that database in your backups). PNG, JPEG and WebP images up to 4 MB each are supported; uploads can be previewed, replaced or removed. Personal color themes remain independent.

The unit workspace groups pages under **Overview**, **Roster**, **Operations**, **Resources** and **Administration**. Administration appears only when you have permission. The selected unit and page stay in the URL for reloads and bookmarks. Each page loads its data when opened; long tables scroll sideways on smaller screens.

Open **Units & rosters** from the navigation. Panel administrators create units, link servers and create staff accounts. Use **Staff access → Add staff** inside a unit to create a login and assign its permissions in one popup (panel administrators), or assign an existing account (unit administrators). An optional roster link sets their name for unit notes and history. New logins have no server access. Unit administrators manage their own staff and rosters. Other staff see only their assigned units; hosting roles remain separate.

Create the unit's qualifications, position suggestions and independent rank structures in **Resources → Rank rules & catalogs**, then add roster members manually. Members need no login account. Game name, Discord handle, Active/Reserve/LOA status, optional rank, qualifications and promotion dates stay separate for each unit. Marine, Medical and Officer structures can each define their own ranks, advancement times and required qualifications; paygrade is only an optional label. Promotion eligibility is a staff notice, never an automatic promotion. Define groups, sections and billet slots, then place each member in one primary billet. Empty slots and staffing counts remain visible. UUIDs can be selected from recorded players on linked servers.

Promotion readiness shows a calculated date and missing qualifications, with a notice when someone is eligible for staff review. It never promotes anyone automatically. Link a panel account to its roster member to use that unit’s name when writing notes. Open a member record to read or add dated staff notes with author history. Unit administrators can archive members or permanently delete a record and its notes after confirmation. Former members retain their records, and CSV export is available. The unit **Dashboard** shows staffing, promotion readiness, upcoming events and attendance awaiting review. **Events** provides a monthly calendar with timezone-aware weekly, biweekly and monthly recurrence. **Attendance** provides a monthly member/event grid and CSV export.


### Qualifications and promotion review

The **Qualifications** tab shows a member-by-qualification matrix. Search members, filter by status/group/section, show who holds or lacks a qualification, and compare filtered coverage with the whole unit. Open a cell to see its award date, issuer and notes. Roster editors can grant, correct details or revoke an award. Existing qualifications retain unknown original dates/issuers until staff enter those details. The timeline separately records who entered or corrected them.

The **Promotions** tab lists eligible members and unmet requirements. **Review promotion** shows the proposed rank and date; a staff note and explicit confirmation are required. The server rechecks eligibility and the unit revision before changing the rank. Promotions are never automatic.

Member records include a filterable, paginated timeline for ranks/promotion dates, primary billets, qualifications and membership status. Changes made in the regular member editor, assignment controls, Structure, promotion review and bulk editor all use this history. Earlier records receive an upgrade baseline; past changes are not reconstructed. Archiving preserves history; permanent member deletion removes their timeline and award records along with their notes, while existing event attendance snapshots remain.

Choose **Bulk edit…** on the Roster tab to select up to 500 current members and grant/revoke a qualification, change status, move to open billets in a section, or remove primary assignments. Review the server-generated before/after list and confirm before applying. A section move keeps members already in that section in place and allocates its open billets to others. Insufficient vacancies or a stale roster reject the whole change. Existing awards keep their dates and issuers when a bulk grant includes someone who already holds the qualification.

### Analytics, SOPs, loadouts, awards and campaigns

- **Analytics:** choose a date range and timezone for recorded strength, roster additions/archive/removal/restoration counts, cohort retention and finalized attendance trends. Daily chart data is also available as a table. Strength and retention start when this feature is installed; earlier history is not invented. Rank distribution shows the current roster.
- **SOPs & loadouts:** search references by category, role or content. SOPs support full text and external reference links. Loadouts add an image URL and editable kit slots with standard items, alternatives and notes. References can be archived/restored; edits retain an audit history.
- **Awards:** create a unit medal/badge catalog, then issue awards with a date and citation. Each issue records the staff member’s unit name. Repeated medals require explicit confirmation; revocations require a reason and retain the original issue. Member records show medals and campaign awards. Award names/images are preserved at issue time when the catalog later changes.
- **Campaigns:** group this unit’s events by a timezone-aware date window or explicit event selection. Set a participation threshold and optionally link a catalog award. Progress uses confirmed Present outcomes divided by eligible finalized events: Reserve events count, LOA and Excused events are exempt, and Unknown means unconfirmed rather than absent. This differs from normal attendance percentages, which only count required Present/Absent decisions. Complete the campaign and finalize its tracked events before individually approving awards. Date-window campaigns must also reach the end of their window. Nothing grants or revokes campaign awards automatically.

All unit staff can view these areas. Unit administrators and panel administrators can manage them; other staff can receive **Manage SOPs / loadouts**, **Manage awards** and **Manage campaigns** independently through Add staff or the user editor. These permissions grant no hosting access. Recruiting remains deferred.

### Events and attendance

1. Link each member’s recorded UUID in their roster record.
2. Open **Events**, choose **New event**, select the unit’s server, local start time/timezone and duration, and enable attendance tracking. Recurring events create separate occurrences; staff can edit one or the remaining series.
3. During the event, the panel observes the server’s live RCON player list automatically. Seeing a linked UUID once is enough for Present; connections outside events do not count.
4. Open the event to review UUID evidence and collector gaps, save corrections with a reason, then finalize after it ends. Finalized records can be reopened with a reason. Cancelled events are excluded from reports.
5. Open **Attendance** to view a month, filter by server, or export CSV. Member records also show their latest 50 event records.

Event lists follow roster changes until the start, then preserve the member’s name, UUID and attendance expectation. Active members are expected; Reserve members are optional and LOA members are excused. Joined dates exclude events before membership. Only finalized, expected Present/Absent decisions enter the percentage; Unknown, Excused and pending outcomes are excluded.

RCON must be configured and reachable. Background player sampling runs about every 30 seconds while the panel service is running; very brief connections between samples can be missed and require staff confirmation. Unlinked UUIDs and collector gaps are visible. Missing evidence **never automatically marks a member absent**. Staff can receive separate **Manage events** and **Review attendance** permissions without roster editing or server control access.


## Update an existing installation

Run these commands inside your repository checkout:

```bash
git fetch origin
git switch main
git pull --ff-only
sudo bash install.sh --update
```

The former `multi-server-manager` work is now on `main`. If Git says it is already up to date, check `git status --short --branch` and `git log -1 --oneline`.

The update preserves accounts, settings, existing servers and legacy server access. It restarts the panel service; it does not deliberately restart the game servers. Wait for provisioning and software jobs to finish before updating.

Updates create recovery snapshots under `/var/backups/arma-panel/`. A failed update attempts to restore panel files and service settings. Automatic rollback does not rewind the live database or game saves. Take a VM backup before production updates; see [backup and recovery](docs/operations.md#backup-and-recovery).

## Find your tools

**All servers** shows summary totals, compact server rows, player and host CPU/memory charts, and recent alerts. Live charts cover up to 30 minutes collected while the page is open; they reset on reload. Start, Stop and Restart are available on each row when your role permits them, with confirmation before Stop or Restart. Open a server or use the selector at the **top of the sidebar** to switch. Switching reloads the workspace and clears its previous drafts and console cursor.

| Workspace | What you use it for |
| --- | --- |
| Dashboard | Start, stop, restart, separate process CPU/memory charts, players and notifications |
| Console | Search/filter logs, export output and send RCON commands |
| Startup | FPS cap, launch options, CPU/memory limits and diagnostics |
| Players | Live roster, observed player history, game admins and moderation |
| Scheduler | Starts, warned stops/restarts, updates, broadcasts and config backups |
| Persistence | Save settings, detected save points and named backups |
| Server config | Validated settings, scenario selection and a raw JSON draft |
| Mods | Workshop browsing, dependencies, version pins, presets and list comparisons |
| Files | Profile uploads, text editing, downloads and recoverable Trash |
| Network | Listeners, ports, network settings and host traffic |
| Administration | Staff access, activity, Discord notifications and maintenance |

**Account settings** is a separate page for your password and theme. Everyone uses the same layout. Color choices are Tactical (the charcoal/amber/olive default), Original (classic amber), Ocean, Forest, Light and Field (olive and parchment); the login page uses the last palette remembered by that browser.

Stop and restart ask for confirmation. Controls block repeated clicks while an action runs and show failures. Unavailable status is distinct from a stopped server.

For limits, advanced settings and workflow details, use the [operations guide](docs/operations.md).

## Staff access and networking

New staff accounts have no server access until assigned. In **Administration → Accounts**, grant Viewer, Operator, Manager or Server administrator separately for each server. Panel administrator access controls account management and is separate from server roles. Existing accounts retain their prior access on upgrade. The original Owner account remains protected.

Set up RCON in **Server config → Remote console**. Use a unique password and keep it on loopback or a private network. Admin RCON is required for panel commands and moderation; scheduled warnings and broadcasts also require the Server Admin Tools mod. **Do not forward RCON publicly.**

The panel does not configure UFW, firewall rules, router forwarding or NAT. Configure the panel's TCP port and each server's game/query UDP ports yourself. For remote panel access, use an HTTPS reverse proxy. Check your current forwarding targets when troubleshooting a join failure.

## Service checks and Owner recovery

For the panel and a managed server with ID `training`:

```bash
sudo systemctl status arma-panel.service
sudo journalctl -u arma-panel.service -n 50 --no-pager
sudo systemctl status arma-server@training.service
sudo journalctl -u arma-server@training.service -n 50 --no-pager
```

Replace `training` with your server ID. An upgraded unmanaged installation uses `arma-server.service` instead.

To recover a forgotten Owner password, run this from an up-to-date checkout on the VM:

```bash
sudo bash install.sh --reset-owner-password
```

It prompts for a new password and invalidates the Owner's existing sessions. It requires local sudo access; the old password is not needed.

## Development and VM validation

Automated checks require Python with Flask/bcrypt, plus Node.js for the frontend tests:

```bash
python3 -m unittest discover -s tests
node tests/frontend_regressions.cjs
bash -n install.sh
```

Configuration tests bind temporary UDP ports, so run them where socket binding is permitted. Automated checks do not establish Steam download success, systemd startup, mission readiness or public connectivity. Follow the [Ubuntu VM checklist](docs/operations.md#ubuntu-vm-checklist) before production deployment. Persistence save selection and named backups remain WIP pending real-server verification.

## License and credits

MIT, as described by the [upstream project](https://github.com/mateuszgolebiewski-code/arma-reforger-panel).

Based on Mateusz Gołębiewski's original panel, including upstream contributions by [YoussefKababe](https://github.com/YoussefKababe). This fork is developed with AI assistance using OpenAI Codex. Bundled Chart.js retains its [MIT license](static/chart.LICENSE.txt).
