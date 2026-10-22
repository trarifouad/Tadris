import importlib.util
from datetime import date
from pathlib import Path

from tadris.db.connection import connect

SEED = Path(__file__).resolve().parents[1] / "scripts" / "seed_demo.py"


def test_seed_fills_phases_4_to_9(tmp_path, capsys):
    spec = importlib.util.spec_from_file_location("seed_demo", SEED)
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    db = tmp_path / "demo.db"
    seed.main(db)
    conn = connect(db)
    statuses = {row[0] for row in conn.execute("SELECT DISTINCT status FROM enrollments")}
    assert {"active", "left", "switched"} <= statuses
    assert conn.execute("SELECT COUNT(*) FROM registrations").fetchone()[0] > 10
    assert conn.execute("SELECT COUNT(*) FROM settings WHERE key LIKE 'override:%'"
                        ).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM holidays").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM sessions WHERE source = 'makeup'").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM sessions WHERE status = 'cancelled'"
                        ).fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM payments").fetchone()[0] > 10
    assert conn.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == conn.execute(
        "SELECT COUNT(*) FROM payments").fetchone()[0]
    assert conn.execute("SELECT COUNT(*) FROM payment_voids").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(DISTINCT received_by) FROM payments").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM archived_refunds").fetchone()[0] == 0  # no refunds in V1
    statuses = [row[0] for row in conn.execute("SELECT status FROM teacher_payouts ORDER BY id")]
    assert statuses and statuses[0] == "paid" and set(statuses[1:]) <= {"approved"}
    assert conn.execute("SELECT COUNT(*) FROM payout_line_charges").fetchone()[0] > 0
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    # The year is lived day by day: history, not only today.
    today = date.today().isoformat()
    assert conn.execute("SELECT COUNT(DISTINCT substr(paid_at, 1, 10)) FROM payments"
                        ).fetchone()[0] > 10
    assert conn.execute("SELECT COUNT(*) FROM attendances a JOIN sessions s "
                        "ON s.id = a.session_id WHERE s.date < ?", (today,)).fetchone()[0] > 100
    assert conn.execute("SELECT COUNT(*) FROM subscriptions WHERE renewal_of_id IS NOT NULL"
                        ).fetchone()[0] > 5
    assert conn.execute("SELECT COUNT(*) FROM students").fetchone()[0] >= 50
    assert conn.execute("SELECT COUNT(*) FROM class_groups").fetchone()[0] == 34
    paid = conn.execute("SELECT COUNT(*) FROM payments").fetchone()[0]
    conn.close()
    assert "registered for the year" in capsys.readouterr().out
    seed.main(db)  # a second run takes no payments again
    conn = connect(db)
    assert conn.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == paid
    conn.close()
