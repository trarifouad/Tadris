import sqlite3

import pytest


def test_foreign_keys_enabled(conn):
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_role_check(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO users(username,password_hash,role) VALUES('a','x','admin')")


def test_one_main_contact_per_student(conn):
    conn.execute("INSERT INTO students(student_number,first_name,last_name) VALUES('2026-0001','A','B')")
    conn.execute("INSERT INTO contacts(full_name) VALUES('P1')")
    conn.execute("INSERT INTO contacts(full_name) VALUES('P2')")
    conn.execute("INSERT INTO student_contacts(student_id,contact_id,is_main) VALUES(1,1,1)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO student_contacts(student_id,contact_id,is_main) VALUES(1,2,1)")


def test_one_open_teacher_rate(conn):
    conn.execute("INSERT INTO teachers(full_name) VALUES('T')")
    conn.execute("INSERT INTO teacher_rates(teacher_id,percentage_bp,valid_from) VALUES(1,5000,'2026-09-01')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO teacher_rates(teacher_id,percentage_bp,valid_from) VALUES(1,6000,'2026-10-01')")
