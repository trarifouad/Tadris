import importlib.util
from pathlib import Path

from tadris.db.connection import connect

SEED = Path(__file__).resolve().parents[1] / "scripts" / "seed_demo.py"


def test_seed_fills_phases_4_to_7(tmp_path, capsys):
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
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    paid = conn.execute("SELECT COUNT(*) FROM payments").fetchone()[0]
    conn.close()
    assert "registered for the year" in capsys.readouterr().out
    seed.main(db)  # a second run takes no payments again
    conn = connect(db)
    assert conn.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == paid
    conn.close()
