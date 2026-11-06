import importlib.util
from datetime import date
from pathlib import Path

from tadris.db.connection import connect

SEED = Path(__file__).resolve().parents[1] / "scripts" / "seed_demo.py"


def test_seed_fills_an_average_school(tmp_path, capsys):
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
    statuses = {row[0] for row in conn.execute("SELECT status FROM teacher_payouts")}
    assert statuses <= {"paid", "approved"}
    assert conn.execute("SELECT COUNT(*) FROM payout_line_charges").fetchone()[0] > 0
    # Paid once over: no payout counts a month that ends after its date.
    assert conn.execute(
        "SELECT COUNT(*) FROM payout_line_charges plc JOIN payout_lines l "
        "ON l.id = plc.payout_line_id JOIN teacher_payouts p ON p.id = l.payout_id "
        "JOIN charges c ON c.id = plc.charge_id JOIN subscriptions s ON s.id = c.subscription_id "
        "WHERE s.end_date > p.period_end").fetchone()[0] == 0
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
    assert conn.execute("SELECT COUNT(*) FROM students").fetchone()[0] >= 150
    assert conn.execute("SELECT COUNT(*) FROM class_groups").fetchone()[0] == 38
    # The workshops: « Tous niveaux » takes pupils of other levels, and adults of its own.
    assert [row[0] for row in conn.execute("SELECT name FROM levels WHERE is_open = 1")] == [
        "Tous niveaux"]
    assert {row[0] for row in conn.execute("SELECT name FROM subjects WHERE is_workshop = 1")
            } == {"Calligraphie", "Arts plastiques"}
    in_workshops = conn.execute(
        "SELECT rl.name = gl.name FROM enrollments e JOIN class_groups g ON g.id = e.group_id "
        "JOIN levels gl ON gl.id = g.level_id JOIN registrations r ON r.id = e.registration_id "
        "JOIN levels rl ON rl.id = r.level_id WHERE gl.is_open = 1").fetchall()
    assert {row[0] for row in in_workshops} == {0, 1}
    paid = conn.execute("SELECT COUNT(*) FROM payments").fetchone()[0]
    conn.close()
    assert "registered for the year" in capsys.readouterr().out
    seed.main(db)  # a second run takes no payments again
    conn = connect(db)
    assert conn.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == paid
    conn.close()
