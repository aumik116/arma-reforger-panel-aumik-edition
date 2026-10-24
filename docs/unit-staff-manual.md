# FIELDHQ unit staff manual

A guide for unit staff using the roster, personnel records, events and attendance tools. You do not need hosting access to do unit work.

For server administration, see the [full user manual](user-manual.md). For help with your login or permissions, contact your unit administrator or panel administrator.

## Contents

1. [Getting started](#1-getting-started)
2. [Your access and workspace](#2-your-access-and-workspace)
3. [Daily staff workflow](#3-daily-staff-workflow)
4. [Roster and member records](#4-roster-and-member-records)
5. [Assignments and positions](#5-assignments-and-positions)
6. [Qualifications and promotions](#6-qualifications-and-promotions)
7. [Events and attendance](#7-events-and-attendance)
8. [SOPs, loadouts, awards and campaigns](#8-sops-loadouts-awards-and-campaigns)
9. [Unit administrator tasks](#9-unit-administrator-tasks)
10. [Common problems](#10-common-problems)
11. [Quick reference](#11-quick-reference)

## 1. Getting started

1. Open the panel address supplied by your administrator.
2. Sign in using your panel username and password. Staff use the normal panel login page.
3. Unit-only staff land in **Units & rosters**. If you also have hosting access, choose **Units** or **Units & rosters** in the navigation.
4. Select your unit. If you belong to several units, check the selected unit before editing anything.
5. Choose a workspace area, then its page.

A panel account is your login. A roster record is a person in a unit. Most roster members do not need panel accounts.

Use **Account settings** to change your password or color theme. Your theme changes your colors, not the unit's branding or page layout. Original also gives panels and controls square corners and firmer borders.

### Help while you work

Choose **Help** in the panel header for guidance on the current unit page. Follow the links to read the full unit staff manual inside the panel, search its text, or download the PDF. Help does not discard edits in your current form.

## 2. Your access and workspace

Ordinary staff see only their assigned units. Panel administrators have broader access. There are just two unit roles:

| Role | Access |
| --- | --- |
| **Staff** | Manage rosters, notes, assignments, qualifications, promotion reviews, events, attendance, SOPs/loadouts, awards and campaigns in assigned units |
| **Unit administrator** | All Staff functions, plus staff access, rank rules/catalogs, structure, branding and permanent member deletion |

There are no individual permission checkboxes. Existing Staff assignments receive the standard Staff access automatically after the update. A unit role does not grant permission to start, stop, configure or update game servers; hosting access is assigned separately.

### Where to find things

| Workspace area | Pages |
| --- | --- |
| Overview | Dashboard, Analytics |
| Roster | Roster, Qualifications, Promotions, Awards |
| Operations | Events, Attendance, Campaigns, Linked servers |
| Resources | SOPs & loadouts, Rank rules & catalogs |
| Administration | Structure, Staff access, Customization; available when permitted |

The unit Dashboard summarizes staffing, upcoming events and work awaiting review. Analytics summarizes recorded trends. **Linked servers** provides basic health for the unit's servers; opening their hosting workspace needs separate access.

If a button is missing or disabled, ask an administrator to check your unit role. Linking a server to the unit or linking your account to a member does not grant that permission.

## 3. Daily staff workflow

### Before an event

1. Select the correct unit.
2. Check the event's server, start time, timezone, duration and attendance tracking.
3. Confirm new members have their correct recorded UUID linked.
4. Review Active, Reserve and LOA statuses.
5. Coordinate server readiness with hosting staff if you do not have server access.

### After an event

1. Open the event and review attendance evidence and any collection gaps.
2. Make corrections with reasons.
3. Finalize the event after it has ended, when permitted.
4. Record earned qualifications, personnel notes or award issues as appropriate.
5. Review promotion eligibility; eligibility does not itself promote anyone.

Save each form and wait for success before closing or switching units. If the panel reports that data changed, refresh and review the latest records rather than trying to overwrite another staff member's work.

## 4. Roster and member records

### Find a member

Open **Roster → Roster**. Search and use the available filters to find the person. A unit may show a flat member list, organized billets, or both views. Groups and ranks are optional.

Open the member's record for personnel details, dated notes, qualifications, awards, attendance and the recorded change timeline.

### Add or edit a member

With roster permission:

1. Add a roster member, or open an existing member's editor.
2. Enter the game name and optional Discord handle.
3. Select Active, Reserve or LOA.
4. Enter the joined date and, if used, rank structure, rank, last-promotion date and primary billet.
5. Assign qualifications and save.

A person can belong to multiple units with different names, ranks, qualifications and statuses. Updating this unit's record does not update their other units.

### Link their game identity

In the editor's **Recorded player UUID** section:

1. Search their recorded name or UUID.
2. Select the correct identity from players observed on this unit's linked servers.
3. Save the member.

A matching display name is not enough for automatic attendance; it uses the linked UUID. If no identity is available, leave it unlinked and return after the person has been recorded on a linked server. Ask hosting staff to check player detection if recording is unavailable.

### Link their panel account

If the member also has a staff login, select their **Linked panel account** and save. This gives the panel an association between the login and the person's name in this unit.

The link does not create a login or grant access. The unit role is assigned separately.

### Write a personnel note

1. Open the member record.
2. Read existing notes for context.
3. Add the new note and save.
4. Confirm it appears with its date and author.

When your account is linked to your own member record in this unit, note authorship uses your unit name. If you use another name in a different unit, that unit's link supplies its own name. Ask an administrator to correct your link if authorship is wrong; do not change the subject member's identity to fix the author.

The member timeline records changes from when history collection began. Older records may have an upgrade baseline rather than a complete earlier history.

### Status, archive or delete

| Choice | Use it when |
| --- | --- |
| Active | The member is normally expected at tracked events |
| Reserve | Attendance is optional |
| LOA | The member is on leave and excused from attendance expectations; record an optional end date |
| Former member / archive | They have left, but their personnel record should be retained |
| Permanent deletion | An authorized administrator intends to remove the personnel record and its notes/history |

Archiving is the normal choice when you want to keep a former member's record. Permanent deletion is a separate administrator action with confirmation. Captured historical event attendance snapshots remain even after a roster record is deleted.

### Bulk changes and CSV

**Bulk edit…** lets permitted staff select members for supported qualification, status or assignment changes. Review the before/after list before confirming. Section moves need enough open billets; insufficient space or a stale roster rejects the batch.

CSV export provides a spreadsheet copy of roster information. Exporting does not create a full panel backup.

## 5. Assignments and positions

A flat roster needs no organization structure. Units using slots organize people into:

- **Groups:** broad containers, such as a platoon or staff organization.
- **Sections:** subdivisions, such as HQ, a squad or a mortar section.
- **Billets:** actual assignable slots, such as Platoon Sergeant, Vehicle Commander or Company Medic.

Position suggestions are reusable names. A suggestion alone does not create or fill a billet.

To assign someone, use the slot's assignment controls or the member editor's **Primary billet** field. Each member has one primary billet. Moving them leaves the old slot open. Empty slots remain visible with staffing counts.

Rank and qualifications do not block billet assignments. Use your unit's own staffing policy when deciding whom to place.

Unit administrators create and remove groups, sections and billets in **Administration → Structure**. Removing organizational items and permanently deleting a member are different actions; read the form's consequences before saving.

## 6. Qualifications and promotions

### Grant or correct a qualification

1. Open **Roster → Qualifications**.
2. Find the member and qualification in the matrix.
3. Open the cell.
4. Grant the qualification or correct its date, issuer and notes, then save.

Use search and status/group/section filters to inspect coverage. You can also identify who holds or lacks a qualification. Revocation requires the relevant edit access.

Older qualifications may lack original award dates or issuers. Enter known details rather than inventing them; the timeline separately records your correction. Existing qualification metadata is retained when a bulk grant includes someone who already holds it.

### Understand promotion eligibility

The member needs:

- The correct rank structure and current rank.
- A configured next rank.
- A last-promotion date.
- Enough elapsed time and the next rank's required qualifications.

The panel adds **the next rank's time requirement** to the last-promotion date. For example, a 30-day requirement after June 1 gives July 1. Reaching that date does not satisfy missing qualifications.

Marine, Medical and Officer paths can have separate rules. An optional paygrade label does not combine their progression.

### Review a promotion

1. Open **Roster → Promotions**.
2. Review the member's readiness and missing requirements.
3. Choose **Review promotion** when eligible and permitted.
4. Review the proposed rank/date, enter the required staff note and confirm.

The panel rechecks eligibility and record changes before applying. A stale record needs another review. **Promotions are never automatic.** Follow the unit's approval policy even when the panel says someone is eligible.

Rank paths, time requirements and qualification names are maintained by permitted administrators in **Resources → Rank rules & catalogs**.

## 7. Events and attendance

### Create an event

With event permission:

1. Open **Operations → Events** and choose **New event**.
2. Select this unit's linked server.
3. Enter the local start time, explicit timezone and duration.
4. Enable attendance tracking if attendance should count.
5. Set recurrence if needed and save.
6. Review the calendar entry.

Weekly, biweekly and monthly recurrence creates separate occurrences. When editing a series, check whether the action affects one event or the remaining series.

Creating an event does not reserve or automatically start the game server. Coordinate shared-server use with hosting staff.

### What automatic attendance counts

A linked UUID observed once on the event's selected server during its tracked event window is enough for Present. Logging in outside an event does not count.

Collection needs a running panel service and a successful live player query. Sampling normally occurs about every 30 seconds; a brief connection between samples may be missed.

The event's membership list follows roster changes until the event starts, then preserves names, UUIDs and expectations. A joined date excludes events before membership.

### Membership status is not an attendance outcome

| Roster status | Event expectation |
| --- | --- |
| Active | Normally expected |
| Reserve | Optional |
| LOA | Excused |

Present, Absent, Excused and Unknown describe event outcomes. They are separate from the person's roster status.

### Review, correct and finalize

With attendance permission:

1. Open the event after it ends.
2. Inspect UUID evidence and collection gaps.
3. Review uncertain outcomes. Missing evidence during an outage is not proof of absence.
4. Save corrections with the required reason.
5. Finalize when the record is ready.

Finalized records can be reopened with a reason when correction is needed. Cancelled events are excluded from reporting.

Use **Operations → Attendance** for the monthly member/event grid, server filtering and CSV export. Normal attendance percentages include finalized, expected Present/Absent decisions. Optional Reserve, LOA/Excused, Unknown and pending decisions are excluded.

Member records show recent attendance, but the Attendance page is the place to inspect the unit's monthly results.

## 8. SOPs, loadouts, awards and campaigns

### SOPs and loadouts

Under **Resources → SOPs & loadouts**, search by category, role or text. Permitted staff can maintain SOP text and external links, or loadouts with an image URL, kit slots, alternatives and notes. Archive obsolete references to retain editing history.

### Awards

Under **Roster → Awards**, permitted staff maintain the medal/badge catalog and issue awards with a date and citation. These awards are separate from promotion qualifications.

Repeated issues require explicit confirmation. Revocation requires a reason and retains the original issue. Issued names/images are preserved if the catalog later changes.

### Campaigns

Under **Operations → Campaigns**, permitted staff group events using a timezone-aware date window or explicit selection, set a participation threshold and optionally link an award.

Campaign progress uses confirmed Present outcomes against eligible finalized events. Reserve events count here; LOA and Excused are exempt. Unknown is unconfirmed. This differs from the normal attendance percentage.

Complete the campaign and finalize its tracked events before approving member awards. Date-window campaigns must reach their end. The panel does not automatically grant or revoke campaign awards.

### Analytics

Under **Overview → Analytics**, choose a date range and timezone to inspect recorded strength, membership changes, retention and finalized attendance trends. Charts also have table data.

Collection starts when the feature is installed; earlier history is not reconstructed. Rank distribution describes the current roster.

## 9. Unit administrator tasks

This section is for staff who also hold unit administrator authority.

### Staff access

1. Open **Administration → Staff access → Add staff**.
2. Select an existing panel account and choose Staff or Unit administrator.
3. Optionally link the account to its member record in this unit.
4. Save and confirm the assignment.

Panel administrators can create a new login through this flow; unit administrators assign existing accounts. Ask a panel administrator for new credentials when needed.

Removing unit staff access does not delete the login, remove the roster record or revoke separately assigned server roles. Review those separately when someone leaves.

### Structure and catalogs

Create groups, sections and billets in Structure. Maintain independent rank paths, qualifications and position suggestions under Rank rules & catalogs. Review the effect of rule changes on existing members' eligibility.

### Branding

Use **Administration → Customization** for the unit description, icon and banner. PNG, JPEG and WebP images up to 4 MB each are supported. Use a square icon and wide banner, preview them and save.

Branding belongs to the unit. Personal color themes remain independent.

Panel administrators handle unit creation and server linking. Unit administration does not by itself grant game-server controls.

## 10. Common problems

| Problem | What to check |
| --- | --- |
| My unit is missing | Ask an administrator to verify your unit staff assignment. |
| I can read a page but cannot edit | Ask an administrator to check whether the task requires Unit administrator. |
| I cannot open a linked server | Hosting access is separate; contact hosting staff. |
| A member has no recorded UUID to select | Confirm the unit links the correct server, then have the player connect and check player recording with hosting staff. |
| Attendance did not mark someone Present | Check linked UUID, selected server, event window/tracking and collector evidence. |
| An attendance outcome is Unknown | Review collection gaps and available evidence; do not assume it means Absent. |
| Promotion readiness has no date | Check structure, current/next rank and last-promotion date. |
| The date passed but the member is not eligible | Check missing qualifications and whether the member is archived. |
| A note uses my login name instead of my unit name | Ask an administrator to link your account to your roster record in this unit. |
| A slot move fails | Refresh the roster and check available billets in the destination section. |
| Saving reports that the record changed | Reopen/refresh, review the latest information and reapply the intended edit. |
| Historical charts have gaps | Earlier history may not have been collected. Review the stated collection period. |

When asking for help, include the unit, page, member/event concerned, time and exact error. Do not share passwords. Include screenshots only where the recipient is authorized to see the personnel information.

## 11. Quick reference

| I need to… | Go to… |
| --- | --- |
| Add or edit a member | Roster → Roster |
| Write a personnel note | Open the member record |
| Link a UUID or panel account | Edit the roster member |
| Change Active/Reserve/LOA | Edit the roster member, or permitted bulk editing |
| Move someone into a position | Primary billet or the slot's assignment controls |
| Grant a certification | Roster → Qualifications |
| Review eligible promotions | Roster → Promotions |
| Create an operation | Operations → Events |
| Correct/finalize attendance | Open the event |
| Review a month or export attendance | Operations → Attendance |
| Find unit SOPs or kits | Resources → SOPs & loadouts |
| Issue a medal | Roster → Awards |
| Check campaign participation | Operations → Campaigns |
| Assign unit staff access | Administration → Staff access; administrator permission required |
| Edit icon or banner | Administration → Customization; administrator permission required |

**Before saving:** check the unit, person/event, dates and proposed change. **After saving:** wait for success and confirm the record reflects the intended result.
