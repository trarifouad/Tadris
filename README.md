# Tadris | تدريس

Offline-first desktop application for a private tutoring school (soutien scolaire) in Algeria.

Tadris runs on a single computer with no internet connection. It replaces paper registers and spreadsheets for the director and the reception desk.

> **Status:** version 1.0.0. Phases 0 to 12 are done. Next: the Windows build and a pilot at the school (phase 13 in `PLAN.md`). UI language: French (Arabic later).

## How it works

- **Subscriptions are monthly.** The group price is copied onto the subscription at creation. `end_date = start_date + 1 month`. Student absence never extends or changes a subscription.
- **Money is whole DZD integers.** Debt is always derived (charges minus valid allocations). There is no stored running-balance column.
- **Payments are immutable.** A payment recorded by mistake is voided by the director (`payment_voids`), never edited or made negative. No discounts and no refunds in V1.
- **Teacher pay** is a percentage of group revenue on an accrual basis: the full subscription price of the month, whether or not the student has paid yet. Rates and prices are snapshots.
- **One free trial** per student, ever. No hard deletes; status changes instead.
- **Everything is audited.** Every write runs in one transaction with its `audit_log` entry; the director reads them in the Journal.

## Features (v1)

- Students and guardians, yearly registration numbers
- Groups, rooms, weekly timetable with overlap protection, holidays, cancelled and moved sessions
- Attendance for generated sessions (does not change subscription dates), printable sheets
- Monthly subscriptions, renewals, numbered receipts (80 mm thermal tickets)
- Partial payments, derived debt, director voids, the day's cash
- Teacher payouts as a percentage of accrued group revenue, with signed slips
- Dashboard: today's sessions, money received, late payers, free places, the day's backup
- WhatsApp messages to parents (click to chat: Tadris itself sends nothing)
- Director and receptionist roles; passwords changed, reset and accounts disabled in the app; a recovery code for a forgotten director password
- Journal: who did what and when (director, read only)
- Verified backups (daily, on close, before a migration), a second location (USB drive or synced folder), restore with a safety copy
- A safe start: one Tadris at a time per database, a check of the computer's date, unexpected errors written to a log

## Tech stack

| Layer | Technology |
| --- | --- |
| Language | Python 3.12+ |
| UI | PySide6 (Qt) |
| Database | SQLite (WAL mode, foreign keys on) |
| Documents | ReportLab (PDF: receipts, sheets, slips) |
| Packaging | PyInstaller |

## Getting started

Python 3.12+. Primary target is Windows 10/11; development on Linux is fine.

```bash
git clone https://github.com/trarifouad/Tadris.git
cd Tadris
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m tadris
```

The first start opens a wizard that creates the director account and shows the recovery code to write down.

A demo school to try things on (a copy, never the real data):

```bash
python scripts/seed_demo.py data/demo.db
TADRIS_DB=data/demo.db python -m tadris
```

Tests and lint:

```bash
pytest -q
ruff check .
```

### Where the data lives

| What | Where |
| --- | --- |
| Database | `tadris.db` in the user data folder: `%LOCALAPPDATA%\Tadris` on Windows, `~/.local/share/Tadris` on Linux |
| Backups | `backups/` next to the database |
| Printed documents | `documents/` next to the database |
| Log of unexpected errors | `logs/tadris.log` next to the database |

### Environment variables

| Variable | Effect |
| --- | --- |
| `TADRIS_DB=path/to/copy.db` | Opens another database file (a copy for manual tests). The file must exist; an empty file starts the first-run wizard. Its backups, documents and log go next to it. |
| `TADRIS_SCALE=1.5` | The app's zoom. Linux defaults to 1.25 (most Windows laptops); Windows follows its own display scale. |

## Project structure

```text
src/tadris/
├── ui/             # PySide6 windows, dialogs, theme (never imports sqlite3)
├── services/       # Business logic, transactions, audit, permissions
├── repositories/   # SQL only, one file per aggregate
├── db/             # Connection, migrations, trigger-error translation
├── documents/      # Printed PDFs: receipts, attendance sheets, payout slips
├── domain/         # Data classes passed between layers
├── core/           # Money, dates, errors, context, permissions, passwords
├── i18n/           # French strings
└── __main__.py     # Entry point
scripts/            # Demo seed, manual check scripts, font build
tests/              # Schema, trigger, service and UI tests
```

The UI never touches the database. Services open `BEGIN IMMEDIATE` transactions and write `audit_log`. SQLite triggers are the last line of defense.

## Roadmap

See `PLAN.md` for phases and `DESIGN.md` for the UI system.

- **V1:** single-computer desktop app, French UI, monthly subscriptions
- **Later:** reports with PDF and Excel exports, refunds, Arabic (RTL), multi-machine sync, parent portal

## License

Private unless a license file is added.
