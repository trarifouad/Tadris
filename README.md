# Tadris | تدريس

Offline-first desktop application for a private tutoring school (soutien scolaire) in Algeria.

Tadris runs on a single computer with no internet connection. It replaces paper registers and spreadsheets for the director and the reception desk.

> **Status:** Phase 2 done (students and contacts). Phase 3 (academic setup) next. UI language: French (Arabic later).

## How it works

- **Subscriptions are monthly.** The group price is copied onto the subscription at creation. `end_date = start_date + 1 month`. Student absence never extends or changes a subscription.
- **Money is whole DZD integers.** Debt is always derived (charges minus valid allocations minus adjustments). There is no stored running-balance column.
- **Payments are immutable.** Corrections are new rows (`payment_voids`), never negative payments.
- **Teacher pay** is a percentage of group revenue on an accrual basis: the full subscription price of the month, whether or not the student has paid yet. Rates and prices are snapshots.
- **One free trial** per student, ever. No hard deletes; status changes instead.

## Features (v1)

- Students and guardians, yearly registration numbers
- Groups, rooms, weekly timetable with overlap protection
- Attendance for generated sessions (does not change subscription dates)
- Monthly subscriptions, renewals, numbered receipts
- Partial payments, derived debt, director voids
- Teacher payouts as a percentage of accrued group revenue
- Director and receptionist roles
- Local verified backups

## Tech stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.12+ |
| UI | PySide6 (Qt) |
| Database | SQLite (WAL mode, foreign keys on) |
| Documents | ReportLab (PDF: receipts, sheets, slips) |
| Packaging | PyInstaller |

## Getting started

Python 3.12+. Primary target is Windows 10/11; development on Linux is fine.

```bash
git clone https://github.com/<your-username>/tadris.git
cd tadris
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m tadris
```

```bash
pytest -q
ruff check .
```

## Project structure

```
src/tadris/
├── ui/             # PySide6 windows, dialogs, theme (never imports sqlite3)
├── services/       # Business logic, transactions, audit, permissions
├── repositories/   # SQL only, one file per aggregate
├── db/             # Connection, migrations, trigger-error translation
├── core/           # Money, dates, errors, context, permissions, passwords
├── i18n/           # French strings
└── __main__.py     # Entry point
tests/              # Schema, trigger and service tests
```

The UI never touches the database. Services open `BEGIN IMMEDIATE` transactions and write `audit_log`. SQLite triggers are the last line of defense.

## Roadmap

See `PLAN.md` for phases and `DESIGN.md` for the UI system.

- **V1:** single-computer desktop app, French UI, monthly subscriptions
- **Later:** Arabic (RTL), multi-machine sync, parent portal

## License

Private unless a license file is added.
