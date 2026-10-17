# Tadris | تدريس

Offline-first desktop application for managing a private tutoring school (école de soutien scolaire) in Algeria.

Tadris runs on a single computer with no internet connection. It replaces paper registers and spreadsheets for the director and the reception desk.

> **Status:** In development (Version 1)

## Features

- **Students & guardians:** registration, profiles, yearly registration numbers
- **Teachers:** multiple salary methods, including percentage of revenue
- **Groups & timetable:** groups, rooms, recurring sessions, overlap protection
- **Attendance:** a session is deducted from the balance only when the student attends
- **Subscriptions:** session-based, with balance tracking and expiry alerts
- **Payments & receipts:** partial payments, configurable maximum debt, numbered receipts
- **Expenses & reports:** PDF and Excel exports
- **Access control:** Director and Receptionist roles with permissions
- **Backups:** local database backup and restore

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.12+ |
| UI | PySide6 (Qt) |
| Database | SQLite (WAL mode, foreign keys on) |
| Reports | ReportLab (PDF), openpyxl (Excel) |
| Packaging | PyInstaller |

## Getting Started

### Requirements

- Python 3.12+
- Windows 10/11 (primary target)

### Install and run

```bash
git clone https://github.com/<your-username>/tadris.git
cd tadris
python -m venv .venv
.venv\Scripts\activate        # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python -m tadris
```

### Build an executable

```bash
pyinstaller tadris.spec
```

## Project Structure

```
tadris/
├── ui/          # PySide6 windows, dialogs and widgets
├── services/    # Business logic (subscriptions, payments, salaries)
├── db/          # SQLite schema, migrations, repositories
├── reports/     # PDF and Excel generation
└── __main__.py  # Entry point
```

The UI never touches the database directly. All rules live in `services/`, which keeps the app ready for a future sync layer.

## Roadmap

- **V1:** single-computer desktop app, French UI
- **Later:** Arabic (RTL) interface, parent/student app via a server API, sync, Excel import, discounts, academic-year archival

## License

Choose a license (MIT is a common default), or keep the repo private if this is a commercial product for a client.
