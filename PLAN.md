# Tadris: Detailed Development Plan

Offline-first desktop application for a private tutoring school (soutien scolaire) in Algeria.
Stack: Python 3.12+, PySide6, SQLite (WAL), reportlab, openpyxl, PyInstaller. UI language: French (Arabic later).

Estimated effort: 3 to 4 months part-time (about 10 to 15 hours per week).

---

## 1. Business rules already decided

| Topic | Rule |
|---|---|
| Subscriptions | Monthly, fixed price snapshot copied from the group at creation. `end_date = start_date + 1 month`. Student absence never extends or changes a subscription. |
| Money | Whole DZD integers. Debt is always derived (charges minus valid allocations minus adjustments). Never store a running debt column. |
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

**Goal:** the front desk can register and find students.

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

**Goal:** the school structure and weekly timetable exist in the system.

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

**Goal:** a student is registered for the year and placed in groups.

**Flow**

1. Registration: student plus school year plus level; fee amount snapshot from settings or manual; creates the registration charge.
2. Enrollment: choose a group of the same year and level; status `active`, or `trial` if it is the first free trial.
3. Switch group: old enrollment becomes `switched`, new enrollment points to it through `switched_from_id`.
4. Leave group: set `left_on` and status `left`.
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

**Goal:** monthly subscriptions with renewal.

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

**Goal:** daily operation: print the list, take attendance.

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

**Goal:** receive money, print receipts, know each student's debt.

**Services**

- `debt.for_student(conn, student_id)`: sum of open charges minus allocations of non-voided payments minus adjustments. Per charge and total.
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

**Goal:** handle discounts, corrections and money returned.

**Services**

- `adjustments.add(student, charge or subscription, type, amount, reason)`: type is `discount` or `correction`; director approval for amounts over a configurable limit.
- `refunds.request(subscription, amount_final, reason)`: stores the computed suggestion and the final amount; status `pending`.
- `refunds.approve` (director), `refunds.pay_out`, `refunds.reject`.
- On approval or payment, create `refund_allocations` against the original payment allocations so the cap is enforced per payment.

**Screens**

- Student page, adjustments tab.
- Refund request dialog and a director approval queue.

**Rules**

- A refund never exceeds paid minus already refunded (trigger).
- Paid or rejected refunds are locked.
- Define in writing whether a refund also cancels the subscription and its charge.

**Tests**

- Refund cap across several payments.
- Locked refund rejects edits.
- Debt view reflects discounts and corrections.

**Acceptance:** a refund can never exceed what was paid, and every adjustment appears in the audit log.

**Time:** 1 week.

---

## Phase 9: Teacher payouts (Full v1 milestone)

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
| 4 | Mid-month join: full or prorated first subscription | Full price starting at the enrollment date |
| 4 | Group switch mid-month: money effect | New subscription from the switch date, old one cancelled, difference handled as adjustment, director approves |
| 5 | Non-renewed student: still allowed in class? | Warning on the attendance screen, no hard block |
| 3 / 6 | Timetable slot validity | **Decided:** half-open `[valid_from, valid_to)`, same as rates and subscriptions. Adjacent periods that share a boundary date do not overlap. |
| 6 | Holidays storage | `holidays` table with date and label |
| 7 | Receipt paper | A4 first, thermal later |
| 7 | Overpayment | Keep as credit on the student |
| 7 | Debt limit | Warning at a configurable amount, director override |
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
