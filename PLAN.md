# Tadris: Detailed Development Plan

Offline-first desktop application for a private tutoring school (soutien scolaire) in Algeria.
Stack: Python 3.12+, PySide6, SQLite (WAL), reportlab, openpyxl, PyInstaller. UI language: French (Arabic later).

Estimated effort: 3 to 4 months part-time (about 10 to 15 hours per week).

---

## 1. Business rules already decided

| Topic | Rule |
|---|---|
| Subscriptions | Monthly, fixed price snapshot copied from the group at creation. `end_date = start_date + 1 month`. Student absence never extends or changes a subscription. |
| Money | Whole DZD integers. Debt is always derived (charges minus valid allocations). Never store a running debt column. |
| Discounts | None. A student always owes the full price of each month and fee: no remises, no corrections (decided in phase 8). |
| Refunds | None in V1 (decided after phase 12; refund tables archived in 0015). A mistaken payment is voided by the director; money handed back is handled outside the app until V2. |
| Payments | Immutable. Corrections are new rows (`payment_voids`, never negative payments). |
| Teacher pay | Percentage of group revenue, accrual basis: the full subscription price of the month, whether or not the student has paid yet. One percentage per teacher, applied to each of their groups. Example: 60% of 60,000 plus 60% of 120,000 = 108,000. |
| Rates and prices | Snapshots. Never recompute an old month from today's price or rate. |
| Trial | One free trial per student, ever. |
| Deletion | No hard deletes. Soft delete through `status`. |
| Audit | Every financial operation runs in `BEGIN IMMEDIATE ... COMMIT` and writes `audit_log` in the same transaction. |
| Roles | `director` and `receptionist`. |
| Weekday | 1 = Monday ... 7 = Sunday. |
| Dates | ISO-8601 text. Subscription, rate, group-teacher and timetable-slot periods are half-open `[from, to)`. |

## 2. Architecture

```
UI (PySide6 pages, dialogs, widgets)
        |  calls only
Services (business logic, transactions, audit, permissions)
        |  calls only
Repositories (SQL only, one file per aggregate)
        |
SQLite (schema, constraints, triggers = last line of defense)
```

Rules:

1. The UI never imports `sqlite3` or repositories.
2. Services open transactions with `db.connection.transaction()` and write `audit_log`.
3. Triggers protect invariants (money, overlaps, capacity). Services hold workflow logic (session generation, payout calculation).
4. All user-facing strings come from `i18n/fr.py`.
5. Business errors are `BusinessRuleError` subclasses with a French message. Services translate trigger error text into them.

## 3. Definition of done (every phase)

- [ ] Migration added (if schema changed), never edit an applied migration after the first real use.
- [ ] Repository and service written, with permission checks.
- [ ] Tests written and `pytest -q` is green.
- [ ] `ruff check .` is clean.
- [ ] UI page works end to end with seed data.
- [ ] French strings in `i18n/fr.py`, none hardcoded.
- [ ] Committed with a clear message and tagged `phase-N`.

## 4. Git workflow

- `main` always works. Work on short branches: `feat/students`, `feat/payments`.
- Commit messages: `feat(scope): ...`, `fix(scope): ...`, `test(scope): ...`, `chore: ...`.
- Tag each finished phase: `git tag phase-3 && git push --tags`.
- `.gitignore` must contain `.venv/`, `data/`, `*.db*`, `*.egg-info/`, `dist/`, `build/`.

## 5. Testing strategy

| Layer | Tool | What to test |
|---|---|---|
| Schema and triggers | pytest + in-memory SQLite (`conn`, `seeded` fixtures) | Every CHECK, unique index and trigger has a passing and a failing case |
| Services | pytest | Business flows: enroll, subscribe, pay, refund, payout. Includes permission denials |
| Money invariants | pytest | Property-style checks: sum of allocations never exceeds payment or charge, debt equals hand-calculated value |
| UI | Manual script + a few `pytest-qt` smoke tests | Pages open, forms validate, errors display |
| Release | Manual checklist | See phase 13 |

---

## Phase 0: Database foundation

**Status:** done. Schema 0001–0004, enrollment INSERT and UPDATE triggers, half-open timetable slots, tests green. Tagged `phase-0`.

**Goal:** a database that refuses invalid data by itself.

**Tasks**

1. Confirm `pytest -q` is green with all migrations 0001 to 0004.
2. Remove the duplicate `seeded` fixture from `test_finance.py` if it still exists.
3. Make sure `*.egg-info/` is untracked.
4. Tag `phase-0`.

**Acceptance:** about 31 tests pass; a fresh database migrates to version 4.

**Time:** 0.5 day.

---

## Phase 1: Core layer and login

**Status:** done. Core layer, auth, settings, audit and counter services, first-run wizard, login, role-based main window, user accounts in Paramètres, Encre theme with bundled fonts. 234 tests green. Tagged `phase-1`. Services run their SQL directly for now; the repository layer starts in phase 2.

**Goal:** the foundations every service depends on, and a working login.

**Files**

```
core/money.py          format_dzd(int) -> "3 000 DA", parse_dzd(str) -> int
core/dates.py          add_one_month(date), iso(), today(), weekday_1_to_7(date)
core/errors.py         BusinessRuleError, PermissionDenied, NotFound, ValidationError
core/context.py        UserContext(user_id, username, role)
core/permissions.py    ACTIONS map: role -> allowed actions, require(ctx, action)
core/security.py       hash_password / verify_password (hashlib.scrypt or argon2)
db/errors.py           translate sqlite3.IntegrityError message -> BusinessRuleError (French)
services/audit.py      log(conn, ctx, action, entity, entity_id, old, new)
services/counters.py   next_value(conn, name) inside the caller's transaction
services/auth.py       login(username, password), create_user, change_password
services/settings.py   get/set typed settings (school name, address, phone, defaults)
ui/login_dialog.py
ui/main_window.py      sidebar with role-based entries, status bar showing user
ui/first_run.py        create the director account and school name on first start
```

**Details**

- `add_one_month`: handle month ends (31 Jan becomes 28 Feb, 29 in leap years). Test it thoroughly.
- Counters use names such as `student:2026` and `receipt:2026` so numbers reset per year. Increment inside the same transaction as the insert.
- Lock rule: three failed logins only add a short delay, never a permanent lockout (offline single-machine use).
- Receptionist cannot: void payments, approve refunds, see payouts, change settings, override rules.

**Tests**

- Money parsing and formatting round trip.
- `add_one_month` for 31 Jan, 29 Feb, 30 Nov, 31 Dec.
- Counter gives gap-free sequential numbers; two connections do not collide.
- Wrong password rejected; disabled user rejected.
- Permission matrix: each action for each role.
- Translated integrity errors produce French messages.

**Acceptance:** you can log in as director or receptionist and the sidebar shows different entries.

**Time:** 1 to 1.5 weeks.

---

## Phase 2: Students and contacts

**Status:** done. Repository layer started (`repositories/students.py`, `repositories/contacts.py`); migration 0005 adds search indexes. Students list (search, status filter, sortable columns, whole-row hover and selection), student dialog with optional main contact, detail page with a working Contacts tab and placeholder tabs. Reusable date field: slashes inserted while typing, calendar with day, month and year views. Seed script `scripts/seed_demo.py PATH.db`. 377 tests green. Tagged `phase-2`.

**Decisions taken in this phase**

- Deactivate and reactivate are director-only (`student.deactivate`, `student.reactivate`). Deactivation is refused while the student has a `trial` or `active` enrollment.
- Phones are stored normalized (`0661902547`; `+213`/`00213` and Arabic-Indic digits accepted) and shown as `0661 90 25 47`. Mobiles are 10 digits (05/06/07), landlines 9 (02/03/04). A contact needs a name and a phone.
- Search is accent and case insensitive through the SQL function `fold()` registered in `connect()`. Every word must match a first name, last name, number or phone; a query made of digits is matched whole against numbers and phones.
- Duplicate warning: same folded name with equal birth dates (or either unknown), or a shared contact phone (often a sibling). Shown as an amber banner; submitting again creates the student.
- Contacts are shared between siblings: a new contact whose phone is on file is offered for linking instead of being duplicated. Editing a shared contact changes it for every linked student, and the dialog says so.
- The first contact always becomes main. The main contact cannot be unchecked or removed while others exist; another contact must be made main first. Removing a contact deletes only the `student_contacts` link (audited); the contact row stays.

**Screens**

- Students list: search by name, number or phone; filters by status; sortable columns.
- Student form: first name, last name, birth date, notes, status.
- Contacts tab: add several parents or guardians, relation, main contact toggle, `can_receive_sms`.
- Student detail page shell with empty tabs for registration, groups, payments (filled in later phases).

**Services**

- `students.create / update / deactivate / search / get`.
- Student number format `YYYY-NNNN` from the counter.
- Duplicate warning (same name and birth date or same phone), not a hard block.

**Rules**

- Exactly one main contact per student (partial unique index already enforces it). The service swaps the main contact in one transaction.
- Deactivate instead of delete.

**Tests**

- Create student gets sequential numbers.
- Changing the main contact never leaves two or zero.
- Search by partial name and phone.
- Receptionist can create and edit but not deactivate (or allow it, decide and test).

**Acceptance:** a student with two contacts can be created, edited and deactivated, never deleted.

**Time:** 1 week.

---

## Phase 3: Academic setup

**Status:** done. Services and repositories for school years, levels and subjects (`catalog`), rooms, teachers with rate history, groups with teacher history, and the weekly timetable; migrations 0006 (one open year, lookup indexes), 0007 (rooms checked against enrolled students) and 0008 (`school_years.opened_on`). Paramètres tabs (school details and hours, users, years, levels, subjects, rooms), Enseignants and Groupes pages (list and detail), Emploi du temps grid by room, group or teacher. Pages are built on first visit and reload each time they are shown again. Seed script fills the school structure too. 527 tests green. Tagged `phase-3`.

**Decisions taken in this phase**

- One open year at a time (service rule and unique index). A year created while another is open waits as "à venir" (status `closed`, `opened_on` empty) until it is first opened, even once its start date has passed (the previous year may still be open at la rentrée): its groups and slots can be prepared; registrations and enrollments stay in the open year (phase 4). Opening a year requires closing the current one. Closing a year closes its groups and ends their slots. A year closed by mistake can be reopened until its end date; a finished year cannot (migration 0008 adds `opened_on`).
- Groups, prices and teacher changes are director-only (`group.manage`). The front desk manages timetable slots (`timetable.manage`). Years, levels, subjects and rooms are director-only (`academic.manage`), readable by both (`academic.view`). Rates are visible to the director only.
- Rates: basis points in half-open periods; a new rate closes the current one on its start date (no gap, no overlap). Same start date = correction, refused once an approved or paid payout covers it. Teacher changes on a group follow the same rule, refused once that teacher was paid for the group.
- Level, subject and start date of a group are fixed once it has students; the school year never changes. Changing the start date moves the first teacher period with it (refused past a planned teacher change); moving it later also moves its slots' start (slots over before it are removed; refused once a slot has sessions).
- A group's teacher is the one assigned on a given date: a change can be planned for later and only shows from its date, in the groups list, the timetable and the teacher pages. Its date must fall between the group's start and the end of the year. Queries take today's date from the service rather than SQLite's clock.
- Closing a group ends its running slots today and removes slots that never produced a session (the slot triggers do not look at group status, so a closed group must free its rooms).
- Editing a slot without sessions changes it in place; with sessions it ends today and a new slot takes over. Removing follows the same split.
- A room must fit the students actually enrolled (trial or active), not the group's maximum: a group planned for 16 with 5 students can meet in a 5-seat room. While it meets there, the smallest room among its running or future slots caps its enrollments, so its seats are min(capacity, smallest room), shown on the group page. A room cannot shrink below the enrolled students of a group using it. Migration 0007 replaces the phase 0 triggers that compared group capacity with room capacity.
- Conflict messages name the clash: room, group, and teacher (one teacher, two groups at the same time: a service rule that follows the teacher history, so a teacher is busy in a group only during their period there). The room is checked first.
- School opening hours (Paramètres, École tab, same every day; default 08:00–20:00 until set): every slot must fit inside them; changing them is refused while a running or future slot of an open group falls outside, naming it. The grid shows exactly these hours and the slot dialog offers times inside them. The École tab also edits the school name, address and phone (keys that existed without a screen).
- The timetable week starts on Saturday; times are typed freely (17h30, 1730) or picked by quarter hour, and the service stores them as 'HH:MM' whatever the caller sends. A past week still shows the slots of groups closed since (closing ends their slots, so validity alone decides).
- The École tab saves all or nothing in one transaction.
- Every service write goes through `atomic()` (phase 2 services moved to it), so trigger errors always reach the user in French.

**Screens**

1. School years: create, open, close. Only one open year at a time (service rule).
2. Levels and subjects: add, reorder, activate or deactivate.
3. Rooms: name, capacity, status.
4. Teachers: list, form, rate history (percentage in %, stored as basis points), current rate shown.
5. Groups: year, level, subject, name, price, capacity, start date, teacher with history, status.
6. Timetable: weekly grid (Monday to Sunday by room or by group), add and edit slots, conflict errors shown inline.

**Services**

- `school_years`, `levels`, `subjects`, `rooms`, `teachers`, `groups`, `timetable`.
- Changing a teacher rate closes the current row (`valid_to`) and opens a new one in one transaction, with audit.
- Changing a group teacher does the same on `group_teachers`.
- Changing a group price affects only future subscriptions (price is a snapshot).

**Tests**

- Rate change keeps history, no overlap, no gap.
- Group teacher change keeps history.
- Slot overlap messages in French for room and group conflicts.
- Capacity rules between group and room.

**Acceptance:** a full week timetable for several groups can be built with no conflicts, and invalid changes show readable messages.

**Time:** 1.5 to 2 weeks.

---

## Phase 4: Registration and enrollment

**Status:** done. Migrations 0009 (enrollment triggers) and 0010 (one level per student, no override). Services and repositories for registrations (register, change level, cancel, fee charge) and enrollments (enroll, trial, confirm, leave, switch, director override for another level); closing a group or a year makes its students leave. Student page: Inscription tab and Groupes tab with their dialogs; group page: Élèves tab with seats, trials and past students; Paramètres → École: default registration fee. `TADRIS_DB` opens another database file (a copy) for manual tests; `scripts/manual/` holds the manual check scripts; the seed script registers and places students. 662 tests green.

**Decisions taken in this phase**

- Joining a group that already started is normal and needs no override (migration 0009 drops the 'group already started' rule and the `override:enrollment_start` key). The entry date lies between the group's start and the end of the year; it defaults to today, or to the group's first day if it has not started.
- An enrollment update re-checks placement only when student, group or registration change, and seats only when an enrollment becomes live again: leaving, switching or confirming a trial works in a closed or full group and after a level override. A left or switched enrollment needs `left_on`; a switch points to an enrollment of the same student (0009).
- Registration: one per student and year, in the open year only, for an active student and an active level. The fee is a snapshot: the default (`defaults.registration_fee`, École tab) or typed at the desk, both audited; a fee above 0 creates the registration charge, due on the registration day. `registered_at` comes from the service clock.
- Change level: both roles, while the student is in no group of the year. Cancel: director only (`registration.cancel`), with a reason; refused while the student is in a group or once part of the fee was paid; the open fee charge is cancelled. Registering again reuses the row (unique per year) with a new fee charge.
- A student may be in several groups under one registration, never twice at once in the same group, and only in groups of their registration's level: refused for everyone, the director included (migration 0010 removed the `override:enrollment_level` key from the triggers). To change level, the student leaves their groups, then « Changer le niveau ». Enrollments of another level made before 0010 keep an « Autre niveau » note and can still leave or switch.
- One subject once: a second group of the same subject and level is refused at the desk with a hint to « Changer de groupe »; the director may allow it with a reason (audited as `overrides: ["same_subject"]`); this is the only enrollment override left. Switching within a subject needs nothing.
- One place at a time: a student cannot be in two groups whose running or future slots meet (same day, overlapping hours, from the entry date). Refused for everyone on enroll and switch (the group being left does not count), and when a slot is added or moved; the message names the student and the other group.
- One free trial per student, ever. Confirming keeps the seat. A switched trial stays a trial in the new group without using the trial again.
- Leaving: today by default, backdated at most to the entry date or the last recorded attendance, never in the future (the seat is freed at once). Switch: the old enrollment ends on the switch date, the new one starts that day (or on the new group's first day).
- Closing a group or a year makes its live students leave that day (`groups.release`); reopening does not bring them back. The confirmation says how many students leave.
- Money effect of a mid-month join or a switch: decided with subscriptions in phase 5 (phase 4 creates no subscription).

**Flow**

1. Registration: student plus school year plus level; fee amount snapshot from settings or manual; creates the registration charge.
2. Enrollment: choose a group of the same year and level; status `active`, or `trial` if it is the first free trial.
3. Switch group: old enrollment becomes `switched`, new enrollment points to it through `switched_from_id`.
4. Leave group: set `left_on` and status `left`.

**Note from the phase 3 review:** the enrollment triggers can be bypassed by the `override:enrollment_level` and `override:enrollment_start` rows in `settings`. A director override must set the row and remove it inside the same `atomic()` transaction as the enrollment, never leave it set, and be audited.
5. Director override: enroll in another level, or after the group start date. The service sets the settings override key inside the transaction, writes `audit_log` with the reason, and clears the key.

**Screens**

- Registration dialog from the student page.
- "Enroll in group" dialog showing only valid groups, with free places.
- Group page: student list with status, free places, trial badge.

**Open decisions (resolve before coding)**

- First subscription when joining mid-month: full price, or prorated by days? (Default proposal: full price for a full month starting at the enrollment date.)
- Group switch mid-month: new subscription starts immediately and the old one is cancelled with a refund rule, or the old one runs to its end? Define the exact money effect and write tests first.

**Tests**

- Cannot enroll without registration; cannot enroll across years.
- Level mismatch blocked, allowed with override and audit entry.
- Capacity enforced; trial only once.
- Switch and leave keep history.

**Acceptance:** all enrollment rules from 0004 enforced through the UI with readable errors.

**Time:** 1.5 weeks.

---

## Phase 5: Subscriptions

**Status:** done. No schema change. Service and repository for subscriptions (create, start, renew, renew many, cancel, mark ended at app start, the desk's lists); the first month is created by the enrollment service. Student page: Abonnements tab (renew, start, cancel); sidebar: Abonnements page (ending within 7 days, ended and not renewed, without any month; double-click opens the student); group page: bulk renewal. Seed entry dates spread over September and October so the lists have rows. 716 tests green.

**Decisions taken in this phase**

- First month: full price for a full month from the entry date (each student has their own cycle; no prorating). Created automatically, in the same transaction: on enrolling as active, from the entry date; on confirming a trial, from the confirmation (or the group's first day if later): the trial days are free.
- Switch mid-month: the running month stays with the old group (and its teacher); the new group's first month starts when it ends, at the new group's price (on the switch date when no month runs). No money moves, even if prices differ. Past the end of the year, no month is created and the switch is not blocked. A switched trial stays free.
- Leaving keeps the running month unchanged; refunds come in phase 8.
- Renewal is manual (both roles), from the student page, the Abonnements page or a group page (bulk: every row ticked, untick who stops, all or nothing). Only the latest month of a live paid enrollment in an open group is renewed; the next month starts on its end date, or later after a gap, never earlier, never after the end of the year. The price is the group's on the renewal day. `renewal_of_id` stays unique even for a cancelled renewal: renewing again then leaves the link out.
- Month ends follow `add_one_month`: 31 Jan → 28 Feb → 28 Mar (each month starts on the previous end).
- Cancel: director only (`subscription.cancel`), with a reason; refused once part of the month was paid (refund first, phase 8) or once its charge is in a teacher payout; the charge is cancelled and the period is free again. A paid enrollment left without any month shows in « Sans abonnement » with « Nouvel abonnement ».
- A free group (price 0) gets months without charges. Display states: à venir, en cours, se termine bientôt (7 days or less), terminé, annulé. At app start, months past their last day are marked `ended` (audited without a user).

**Services**

- `subscriptions.create(enrollment, start_date)`: price from the group snapshot, `end_date = add_one_month(start)`, creates a subscription charge with `accrual_date = start_date` and `due_date = start_date`.
- `subscriptions.renew(subscription)`: new subscription starting on the previous `end_date`, `renewal_of_id` set (unique, one renewal only).
- `subscriptions.cancel`: sets status `cancelled` and cancels the charge. Blocked if the charge is already in a payout.
- App-start job: mark subscriptions past `end_date` as `ended`.

**Screens**

- Student detail, subscriptions tab: current, history, renew button.
- "Expiring in 7 days" list, "Expired and not renewed" list.
- Bulk renewal helper for a group: select students, preview, confirm.

**Rules**

- Only one non-cancelled subscription covers any date for an enrollment.
- Absence never changes dates.
- Trial enrollments get no subscription charge.

**Tests**

- Renewal chain with no gap or overlap.
- Cancelled subscription frees the period.
- Cancel after payout is refused.
- Month-end start dates (31 Jan renewal lands on 28 Feb then 28 Mar logic is stable and documented).

**Acceptance:** renewals chain without overlap and the expiring lists are correct.

**Time:** 1 week.

---

## Phase 6: Sessions and attendance

**Status:** done. Migration 0011 (holidays). Services: holidays, session generator and session actions (`sessions`), attendance, printing (reportlab, `documents/`). Paramètres → Vacances; sidebar Présences (day or week, filters, cancel, restore, makeup, substitute, Régénérer, week sheet); attendance screen (status buttons, save, corrections, print); student page Présences tab. Seed adds holidays, a cancelled session with its makeup, a substitute and today's attendance. 795 tests green.

**Decisions taken in this phase**

- Holidays are periods with a label, both days included (a single day has the same start and end), in a `holidays` table; the director manages them in Paramètres → Vacances; periods never overlap (service and trigger).
- Sessions are generated for the next 14 days (today included): at app start, when a slot is added, and with « Régénérer ». One per slot meeting that day, in its room, with the group's teacher on that date; skipped on holidays, for closed groups, outside a slot's validity, before the group starts or after its year. Never duplicated (unique slot and date, cancelled sessions included). A generated session that would clash is skipped and reported.
- A pending session (generated, planned, today or later, no attendance) is a forecast: it is discarded and generated again when a slot changes or ends, a holiday is added, moved or removed, the group's start moves, or a teacher change applies (only the sessions with the old teacher: a substitute stays). Every other session is history and is kept. The phase 3 rules (change a slot in place or end it, delete a slot or end it, move a group's start) now count kept sessions only.
- Cancel: both roles, reason required, planned sessions only (not once attendance is taken). Restore: if the room, teacher and group are still free and no makeup exists. Makeup: one per cancelled session, any date from the group's start to the end of the year, within opening hours; room, teacher, group and the group's students must be free, the room must fit the students of that day. Substitute: one session only, teacher active and free; the group's teacher again removes it. Closing a group or a year cancels what is still planned from today (« Groupe clôturé »).
- « Reporter » (after phase 12, from the timetable): one session of a week moves to another day, time, room or teacher of the same week (Saturday to Friday), from today on, with a reason. In one transaction it is cancelled and a makeup takes its place; the slot is never changed, so the other weeks are untouched. The grid shows that week as it goes: the moved session muted (« Reportée au jeu. 22/10 »), its makeup at the new place (« Rattrapage du mar. 20/10 »). « Annuler le report » cancels the makeup (not held yet) and restores the session. A planned session with attendance, or a past one, cannot be moved. Both roles (`session.manage`). Audited as `session.reschedule` / `session.undo_reschedule`.
- Attendance: the group's students on the session date (left_on included, so a switch day lists the student in both groups), trial students marked « Essai », paid students with no month covering the date marked « Mois non renouvelé » (listed normally, no block). From the session's day on, never before; corrections by both roles at any time, each save audited with every change (old → new); the first save marks the session held.
- Printing: PDF files in a `documents` folder next to the database, opened in the system viewer. Session sheet (A4 portrait, boxes ticked when recorded) and a group's week sheet (A4 landscape, letters P/R/A/E, « — » when not in the group that day). Font Readex Pro (French accents now, Arabic later). Every print is written to `print_log`.

**Services**

- `session_generator.run(conn, days_ahead=14)`: creates sessions from active timetable slots. Safe to rerun (unique on slot and date). Skips closed groups, dates outside slot validity, and dates in a `holidays` setting.
- Run on app start and from a "regenerate" button.
- Cancel a session with a mandatory reason. Create a makeup session linked by `makeup_of_session_id`.
- Substitute teacher: set `sessions.teacher_id` for that session only.
- `attendance.save(session, rows)`: present, late, absent, excused for valid enrollments on that date.

**Screens**

- Today and week view of sessions.
- Attendance entry: student list, quick status buttons, save.
- Printable attendance sheet (PDF) per session or per group per week; logs to `print_log`.
- Student detail, attendance tab: history and absence count.

**Holidays**

Add a `holidays` table or a settings JSON list in this phase. Decide which and add a migration.

**Tests**

- Generator is idempotent and respects slot validity and holidays.
- Attendance rejects enrollments not valid on the date (trigger).
- Cancelled sessions are ignored in overlap checks.
- Makeup session links correctly.

**Acceptance:** opening a session shows the right students; attendance can be saved and corrected; the sheet prints.

**Time:** 1.5 weeks.

---

## Phase 7: Payments and receipts (MVP milestone)

**Status:** done. No schema change (the 0001 tables and 0003 triggers already guard payments). Repository `payments`; services `debt` (derived per charge and in total: owed, late, credit; debtors list; warning) and `payments` (record: the credit pays the oldest charges first, then the new money oldest due first or on the lines chosen, receipt `R2026-00001` from the year's counter, all in one transaction with audit; void, director only; cash report); receipt PDF (A4, PAYÉ or ANNULÉ stamp as a grey outline, DUPLICATA on a reprint). Student page: Paiements tab (what is left to pay, history, receipt printed on payment, void); payment dialog (preview, chosen lines, payer, "Encaisser 2 500 DA"); sidebar: Paiements page (late payers with group, amount and days filters; cash of the day per method and cashier). Debt warning in the enroll, switch, renew and payment dialogs above a threshold set in Paramètres → École (never a block). Seed takes payments. Phase 0–7 review: every trigger message now has a failing test (`test_triggers_last_line.py`; 54 of 54 fire), old databases (phase 3, phase 6) upgrade and keep working. 897 tests green.

**Goal:** receive money, print receipts, know each student's debt.

**Services**

- `debt.for_student(conn, student_id)`: sum of open charges minus allocations of non-voided payments (the adjustments planned here were dropped in phase 8). Per charge and total.
- `payments.record(student, amount, method, payer_contact, auto_allocate=True)`: inserts payment, allocates oldest due charge first (override possible), creates the receipt number from the counter, all in one transaction with audit. An unallocated remainder stays as credit and is visible in the debt view.
- `payments.void(payment, reason)`: director only; blocked by triggers if used in a payout or refunded.
- `receipts.render_pdf(receipt_id)`: school header from settings, student, items paid, remaining balance, receipt number, cashier.

**Screens**

- Student page, payments tab: debt summary, "Receive payment" dialog, history, void action for the director.
- Debtors list: filter by group, by amount, by overdue days.
- Daily cash report: total received per method and per cashier.

**Open decisions**

- Receipt paper: A4 or thermal 80 mm.
- Maximum debt before a warning or block on new enrollment or renewal.
- Overpayment: keep as credit, or require exact allocation.

**Tests**

- Allocation order, partial payments, overpayment credit.
- Debt equals the hand-calculated figure for several scenarios.
- Void restores debt; cannot void after payout (trigger).
- Receipt numbers sequential and unique, no gaps after a rolled-back transaction.

**Acceptance:** the front desk can run a full day: enroll, subscribe, take payments, print receipts, take attendance.

**Time:** 2 weeks.

> **MVP reached.** This is enough to replace paper at the desk. Add a basic automatic backup right after this phase (see phase 12, task 1) before any real data goes in.

---

## Phase 8: Adjustments and refunds

**Status:** done. Migration 0012: `refunds` rebuilt to target one charge (a month or the registration fee) with who asked, the number, the method and who paid out; `balance_entries` dropped (no adjustments). Repository and service `refunds` (options with a suggestion, request, approve, reject, pay out, queue, the day's refunds); refund slip PDF (`RB2026-00001`, REMBOURSÉ stamp, signed by whoever takes the money). Student page: Remboursements tab; sidebar Paiements: « Remboursements à traiter » queue; cash of the day nets the refunds; cancelling a month or a registration looks at what was paid and not refunded. Seed asks three refunds. 943 tests green; every trigger message (58) has a failing test; a phase 7 database upgrades and keeps every money rule.

**Decisions taken in this phase**

- No discounts: the school gives no remises nor corrections (decided after a first version had them). A student owes the full price of each month and fee; the teacher's share is always the percentage of that full price. The adjustments table (`balance_entries`, never written before) is dropped in 0012.
- A refund hands back money paid on one charge; it never changes what is owed. A month refunded in full stays paid; cancelling it is then allowed (cancelling a month or a registration looks at what was paid and not refunded). A refund does not cancel the subscription or its charge by itself: the director cancels the month afterwards if it should not count.
- Refunds target a charge, so the registration fee can be refunded before a registration is cancelled (0001 allowed months only; the table was empty and is rebuilt in 0012).
- Flow: the desk asks (pending), the director approves (the amount may change) or rejects (reason in the audit log), the desk pays out an approved refund. Paying out takes the money back from the payments that paid the charge, latest first, never more than each one gave (trigger), numbers it `RB2026-00001` from the year's counter and prints the slip. A payment with money refunded can no longer be voided (0003).
- Suggestion: for a month, what was paid and kept beyond the value of the days used (until the day the student left, or today; a date can be typed), at the month's price, rounded up for the school; for the fee, everything kept (the director decides).
- Not covered: money paid and allocated to no charge (credit) cannot be refunded (parking lot).

**Removed from V1 (after phase 12).** The school has not opened; the refund workflow waits for V2. Migration 0015 drops the refund triggers and renames `refunds` and `refund_allocations` to `archived_refunds` and `archived_refund_allocations`, read-only (trigger): a database that recorded refunds keeps them, and a payment some of whose money was handed back still cannot be voided (`trg_void_rules` follows the rename). Gone: the service and repository, the student page's « Remboursements », the « Remboursements à traiter » queue, the refund slip, the refunds in the cash of the day (the drawer is cash received minus teachers paid in cash), the « Remboursé » and « Net encaissé » columns, the `refund.*` permissions and the demo refunds. Cancelling a month or a registration is refused once anything was paid on it; a payment recorded by mistake is voided by the director (a void is not a refund: it undoes an erroneous entry). Money handed back exceptionally is handled outside the app by the director and noted. 1140 tests green.

**Goal (as planned):** handle discounts, corrections and money returned. Discounts and corrections were dropped (see the decisions above).

**Services**

- ~~`adjustments.add(...)`~~: dropped, no discounts.
- `refunds.request(subscription, amount_final, reason)`: stores the computed suggestion and the final amount; status `pending`.
- `refunds.approve` (director), `refunds.pay_out`, `refunds.reject`.
- On approval or payment, create `refund_allocations` against the original payment allocations so the cap is enforced per payment.

**Screens**

- Student page, refunds tab (the planned adjustments tab was dropped).
- Refund request dialog and a director approval queue.

**Rules**

- A refund never exceeds paid minus already refunded (trigger).
- Paid or rejected refunds are locked.
- Define in writing whether a refund also cancels the subscription and its charge.

**Tests**

- Refund cap across several payments.
- Locked refund rejects edits.
- ~~Debt view reflects discounts and corrections~~ (dropped).

**Acceptance:** a refund can never exceed what was paid, and every refund step appears in the audit log.

**Time:** 1 week.

---

## Phase 9: Teacher payouts (Full v1 milestone)

**Status:** done. Migration 0013: `payout_lines` rebuilt with one line per group and rate (a trigger checks each month's rate is the teacher's on its first day); `teacher_payouts` gains who approved and when, the method and who paid; draft → approved → paid, never back, and approving checks the totals are exactly the lines (triggers). Repository and service `payouts` (what is owed up to a date, build a draft, rebuild, delete, the monthly run, stale months, approve, pay with `PE2026-00001`, lines, months per student, history, the day's payouts); payout slip PDF (groups, total, every month student by student, signed by the teacher; BROUILLON, APPROUVÉ or PAYÉ). Sidebar « Paiements enseignants » (director): « Payer jusqu'au », « Préparer les brouillons », what each teacher is owed, payouts with their actions, detail with groups and « Détail par élève »; teacher page: Paiements tab (director); the director's cash of the day counts teachers paid in cash. Seed runs the payouts up to the end of last month. 995 tests green; every trigger message (64) has a failing test; a phase 8 database upgrades and its payouts match an independent recomputation.

**Decisions taken in this phase**

- A payout takes every month not paid to the teacher yet with a first day up to the chosen date (at most the end of the current month), not only that month's: a month renewed late (starting in a period already approved) goes into the next payout instead of being lost. Its period runs from the first day of its oldest month to that date.
- The teacher of a month is the group's teacher on its first day; the rate is the teacher's on that day (snapshot). One line per group and rate (0013 replaced 0001's one line per group): a rate change, or a late month from before it, gives a second line. Each line is rounded down once.
- No discounts: a month counts at its full price, paid or not. A month refunded in part still counts in full; a month refunded in full and then cancelled no longer counts (open charges only).
- One draft per teacher: building again replaces it; a draft can be deleted. Approving locks it as it is (a warning names the months entered since, which go to the next payout). Paying hands over the whole amount, numbered, with its method; the slip opens to be signed. Director only; teacher pay never shows to the desk (the cash of the day counts it for the director only).
- A teacher without a rate on a month's first day cannot be paid until the rate is added; the monthly run reports it and prepares the others.

**Goal:** pay teachers their percentage correctly and permanently.

**Services**

- `payouts.build_draft(teacher, period_start, period_end)`:
  1. For each group the teacher taught in the period, find subscription charges with `accrual_date` in the period, status `open`, not already in `payout_line_charges`, where the teacher was the group teacher on the accrual date.
  2. `revenue_basis` = sum of charge amounts, `percentage_bp` = the teacher's rate on that date (snapshot), `amount = revenue_basis * percentage_bp // 10000`.
  3. Insert `payout_lines` and `payout_line_charges`, plus the `teacher_payouts` totals, as `draft`.
- Draft can be rebuilt (delete lines and recreate) until approved.
- `payouts.approve`, `payouts.mark_paid(amount_paid, receipt_number)`.
- Payout slip PDF per teacher: groups, student counts, revenue, percentage, amount.

**Screens**

- Payouts list per period; build draft; detail with per-group lines and per-student breakdown.
- Reports: payout history per teacher.

**Rules**

- Once approved or paid, the payout and its lines are locked (triggers).
- A charge is paid to a teacher once (unique index).
- A charge in an approved payout can no longer be cancelled (trigger); corrections are done manually by the director with audit.

**Tests**

- Your example: 60% of 60,000 plus 60% of 120,000 = 108,000 with two groups.
- Rate change mid-year: old payouts unchanged.
- Teacher change mid-period: charges attributed by accrual date.
- Rebuilding a draft does not double count.
- Locked payout rejects changes.

**Acceptance:** monthly payout run for all teachers produces correct slips and locks the period.

**Time:** 1.5 weeks.

> **Full v1 reached.**

---

## Phase 10: Dashboard and reports

**Status:** done. No schema change. Repository and service `reports` (dashboard; revenue by month and by group; debt by age; attendance by group and by student; teacher summary; student list; audit log with filters), each report a `ReportTable` of raw values that the screen, the PDF (`documents/report_pdf.py`, landscape when wide) and the Excel file (`documents/report_xlsx.py`, real numbers and dates, same total row) all show. New permission `report.finance` (director). Sidebar: Tableau de bord (four stat cards, today's sessions, months ending this week, largest debts, group fill; double-click opens the student, « Voir tout » opens the page) and Rapports (one tab per report the user may see, filters, PDF and Excel; Journal for the director with the entry's before and after). Each export is written to the audit log (`report.export`). 1046 tests green; every report matches a hand count (`test_reports.py`) and, on the demo seed, an independent SQL count.

**Decisions taken in this phase**

- A month or fee counts in the month of its accrual date (a month on its first day, the fee on the registration day); cancelled ones are left out. « Réglé » is what payments not voided paid on them, whenever they were paid; « Encaissé » is the money received in the month, whatever it paid; « Remboursé » is what was handed back in the month. So a month's « Facturé − Réglé » is still owed, and « Encaissé » matches the days' cash reports.
- Money (revenue, teacher summary, the dashboard's money card) is the director's; the receptionist sees sessions, renewals, debt, attendance, the student list and group fill.
- Attendance rate = (present + late) / (present + late + absent): an excused absence is left out; cancelled sessions do not count.
- Debt by age: each late charge from its due date, in 0–30, 31–60, 61–90 and over 90 days; the credit pays the oldest first (as a payment would), so the buckets add up to the debtors list.
- Teacher summary: groups and students today; paid during the school year; waiting (drafts and approved); « À préparer » is what a draft built today would pay (same rate rule as the payout).
- The audit log viewer shows at most 1 000 entries, latest first, and says so when the limit is reached.

**Goal:** the director sees the school's state at a glance.

**Dashboard cards**

- Sessions today and tonight.
- Subscriptions expiring this week.
- Total debt and top debtors.
- Revenue this month (charged vs collected).
- Group fill rates.

**Reports (screen, PDF and Excel)**

- Revenue per month and per group.
- Debtors by age.
- Attendance rate per group and per student.
- Teacher summary: groups, students, amounts due and paid.
- Student list export.
- Audit log viewer with filters (director only).

**Tests**

- Report queries against a seeded dataset with known totals.
- Excel export opens and totals match the screen.

**Acceptance:** each report matches hand-calculated figures on seed data.

**Time:** 1.5 weeks.

---

## Phase 11: SMS

**Goal:** automatic notifications, never blocking the desk.

**Design**

- `sms_queue` is the only entry point; services enqueue, a background worker (QThread or timer) sends.
- Provider adapter interface: `send(phone, text) -> result`. Implementations: `FakeProvider` (tests), then the real one (decide: USB modem, Android phone gateway, or an Algerian SMS API).
- Retries with backoff (`attempts`, `next_attempt_at`), final status `failed` with `last_error`.
- Templates in French with placeholders (student name, date, amount).
- Triggers for messages: absence, subscription expiring, payment received, debt reminder.
- Respect `can_receive_sms` at enqueue time and skip duplicate messages for the same attendance.

**Screens**

- Queue view (pending, sent, failed) with a retry button.
- Template editor in settings.

**Tests**

- Retry and backoff logic with the fake provider.
- Contacts with `can_receive_sms = 0` never get messages.
- Worker survives provider errors and app restarts.

**Acceptance:** messages go through the queue, failures are retried, and the failed list is visible.

**Time:** 1 to 1.5 weeks.

---

## Phase 12: Backup, audit and settings

**Goal:** the school can never lose its data.

**Status:** done, except the SMS provider setting, which comes with phase 11. Migration-free (the 0001 `backups` and `restore_log` tables). Task 3, retention: see below. Task 4, second location: Paramètres → Sauvegardes, a folder chosen once (it must exist then); each verified copy is also written to `<folder>/Tadris-<school id>/` (a random id kept in `settings`, so two computers sharing a drive never touch each other's copies), as `.part` then renamed, its checksum compared; the same retention there, by file name; a drive not plugged in warns (`backup.mirror_failed`, shown in the Journal) and never stops the copy. Task 5, restore (`services/restore.py`, director only, permission `backup.restore`): a copy from the list or any file is checked first (opens, `PRAGMA integrity_check`, a Tadris database with an active director, not from a later version, and the recorded checksum for one of the list); then a safety copy (`…-avant-restauration.db`, never removed); then the copy is written over the open database with SQLite's online backup API (no file swapped under the app, WAL kept), migrated if older; the list of copies on disk is the one from before; `restore_log` and the Journal (`backup.restore`, with who really did it) record it; back to the login screen and the start-of-day jobs run again. A failure half-way puts the safety copy back and is logged as `failed`. « Sauvegarder maintenant » makes a manual copy. Task 6, settings: the École tab adds a default monthly price for a new group and two receipt lines (one under the address on receipts and slips, one at the foot of receipts and refund slips); it scrolls on a small screen. Task 7: Paramètres → À propos (app version, database version, database file); a database from a later version, or a migration that fails (its transaction rolled back), stops the app with a message naming the copy taken just before. Acceptance checked: a copy made on one computer, restored on a fresh install elsewhere, reopens with the same rows, passes the integrity check, and every page opens. 1176 tests green.

**Tasks**

1. Automatic backup on app close and daily: SQLite online backup API or `VACUUM INTO`, never a raw file copy in WAL mode. Store file path, size and checksum in `backups`.
2. Verify each backup: open it, run `PRAGMA integrity_check`, compare the checksum, set `verified_at`.
3. Retention: keep the last 14 daily and 12 monthly copies.
4. Copy to a second location (USB drive or a synced folder), configurable.
5. Restore flow: choose a backup, verify, replace the database after confirmation, write `restore_log`. Always take a safety copy first.
6. Settings screen: school info, receipt header and footer, holidays, SMS provider, default prices, override limits, backup folders.
7. Schema version shown in an About page; failed migrations stop the app with a clear message and a backup taken beforehand.

**Tests**

- Backup and restore round trip yields an identical row count in every table.
- Corrupted backup detected by verification.
- Retention deletes only the right files.

**Acceptance:** a backup restored on another machine opens correctly.

**Time:** 1 week. The basic backup (tasks 1 and 2) is done right after phase 7.

**Basic backup: done** (after phase 9, before phase 10). No schema change (the 0001 `backups` table). Service `backup` and repository `backups`: a copy with SQLite's online backup API, written as `.part` then renamed, switched to a single self-contained file; sha256 and size recorded; verified (read-only open, `PRAGMA integrity_check`, checksum) to `verified`, else `failed` with a `backup.failed` audit entry. Taken once a day at start (and by an hourly timer if the app stays open past midnight), on close, and before any migration of an existing database (if that copy fails the app stops instead of migrating). A failure warns and never blocks the desk. Backups go in `backups/` next to the database in use, so a `TADRIS_DB` test copy never mixes with the school's. 1010 tests green. Still to do in this phase: a second location (4), restore (5), the settings and About screens (6, 7).

**Retention (task 3): done.** After each verified copy: kept are the 3 latest copies, the latest of each of the last 14 days that have one and of each of the last 12 months (days and months without a copy do not count, so holidays never empty the folder); manual copies and copies a restore used are never removed; a failed or interrupted copy goes after 14 days. A file that cannot be removed keeps its row for next time; each cleanup is a `backup.prune` audit entry (by the app). Printed documents and report exports in the app's documents folder are removed at start after 30 days (reports) or 90 days (receipts, slips, sheets: printed again with « DUPLICATA »); a file saved with « Enregistrer sous » is never touched. A student's Paiements tab comes a page at a time; « À préparer » (teacher pay not in a payout yet) is summed by the database in one query.

---

## Phase 13: Packaging and pilot

**Goal:** a real school uses it for a full month.

**Tasks**

1. Build with PyInstaller on Windows (and test the exe on a clean Windows 10 or 11 machine). Use Python 3.12 or 3.13 for the build if 3.14 causes packaging problems.
2. Bundle migrations and resources; verify they load from the frozen app.
3. Installer (Inno Setup or similar), desktop shortcut, data folder in the user profile.
4. Review all French strings; fix truncated labels and alignment.
5. Performance check with a seeded database of 1,500 students and 3 years of history.
6. Write a one-page user guide for the receptionist and one for the director.
7. Manual test script covering every phase (see checklist below).
8. Pilot: run next to the paper system for 2 to 4 weeks, collect issues, fix, release.

**Release checklist**

- [ ] Fresh install creates the database and the first-run wizard works.
- [ ] Upgrade from the previous version migrates cleanly (test with a copy of real data).
- [ ] Backup, restore and integrity check pass.
- [ ] Day close: cash report matches physical cash.
- [ ] Month close: payouts match a hand calculation for two teachers.
- [ ] Printing works on the school's actual printer.
- [ ] Antivirus does not quarantine the exe (sign it if possible).

**Time:** 2 to 3 weeks including the pilot.

---

## 6. Timeline (part-time, approximate)

| Weeks | Phases | Milestone |
|---|---|---|
| 1 | 0, start of 1 | Database finished |
| 2 to 3 | 1 | Login and core |
| 4 | 2 | Students |
| 5 to 6 | 3 | Academic setup |
| 7 to 8 | 4, 5 | Enrollment and subscriptions |
| 9 to 10 | 6 | Sessions and attendance |
| 11 to 12 | 7 + basic backup | **MVP** |
| 13 | 8 | Refunds |
| 14 to 15 | 9 | **Full v1** |
| 16 to 17 | 10, 11 | Reports and SMS |
| 18 | 12 | Backup, settings |
| 19 to 21 | 13 | Packaging and pilot |

## 7. Decisions to resolve (with the phase that needs each)

| Needed before | Question | Default proposal |
|---|---|---|
| 5 | Mid-month join: full or prorated first subscription | **Decided:** full price for a full month from the entry date |
| 5 | Group switch mid-month: money effect | **Decided:** the running month stays with the old group; the new group's first month starts when it ends |
| 6 | Non-renewed student: still allowed in class? | **Decided:** « Mois non renouvelé » badge on the attendance screen, no block |
| 3 / 6 | Timetable slot validity | **Decided:** half-open `[valid_from, valid_to)`, same as rates and subscriptions. Adjacent periods that share a boundary date do not overlap. |
| 6 | Holidays storage | **Decided:** `holidays` table of periods (start, end included, label) |
| 7 | Receipt paper | **Decided:** thermal 80 mm tickets for receipts and refund slips (A4 first, changed after phase 12) |
| 7 | Overpayment | **Decided:** kept as credit; it pays the oldest charges first when the next payment is recorded |
| 7 | Debt limit | **Decided:** a warning in the enroll, switch, renew and payment dialogs once the late debt reaches the threshold in Paramètres (0 = off); never a block, so no override |
| 11 | SMS provider | Decide after testing a real modem or phone gateway |
| 13 | Arabic RTL in v1 | French only until after the pilot |

## 8. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Money bugs | Every financial feature ships with scenario tests; debt and payout totals checked against hand-calculated values |
| Editing applied migrations | After first real data, only add new numbered migrations; test upgrades on a copy |
| Data loss | Backups early (after phase 7), verified, copied to a second location |
| Timetable edge cases | Holidays, cancellations and makeups designed in phase 6, not patched later |
| UI freezing | Long jobs (backup, SMS, report export) run in worker threads |
| Windows-only issues while developing on Linux | Use `pathlib` and `platformdirs`; build and test the exe on Windows by phase 7 |
| Scope creep | Anything outside this plan goes to a v2 list |
| Python 3.14 with PySide6 or PyInstaller | Pin and test on 3.12 or 3.13 before the first release |

## 9. Parking lot (v2)

- Arabic RTL interface.
- Multiple branches or multi-machine sync.
- Parent portal or mobile app.
- Online payments.
- Teacher fixed-salary or per-session pay methods.
- Exams, grades and report cards.
- Inventory of books and materials.
- Remises (discounts) and corrections: built then dropped in phase 8 by decision; the school charges the full price.
- Refunds (built in phase 8, removed from V1 after phase 12, rows archived): request, director approval and payout with allocation to the original payments, numbered slip, cash and reports. Decisions already taken for V2: the suggestion counts the sessions held up to the departure (from the timetable, absences count as used); a month starts at the first session attended (moved only within the original month, renewals moved with it); the fee is refundable through the normal request only before any attendance, otherwise by director exception; a departure date changed after a request means reject and ask again; an impossible makeup is decided by the director; refunds do not lower teacher pay; credit beyond what is owed may be refunded; a paid refund is corrected by a numbered reversal (director, full or part).
- Refund a student's credit (money paid and allocated to no charge), e.g. paid in advance and gone before the next month was created.
