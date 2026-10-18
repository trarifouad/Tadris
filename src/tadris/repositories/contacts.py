"""SQL for contacts and their links to students. The service owns transactions and audit."""


def insert(conn, full_name: str, phone: str | None, phone_2: str | None,
           address: str | None) -> int:
    cur = conn.execute(
        "INSERT INTO contacts(full_name, phone, phone_2, address) VALUES (?, ?, ?, ?)",
        (full_name, phone, phone_2, address),
    )
    return int(cur.lastrowid)


def get(conn, contact_id: int):
    return conn.execute(
        "SELECT id, full_name, phone, phone_2, address FROM contacts WHERE id = ?",
        (contact_id,),
    ).fetchone()


def update(conn, contact_id: int, full_name: str, phone: str | None, phone_2: str | None,
           address: str | None) -> None:
    conn.execute(
        "UPDATE contacts SET full_name = ?, phone = ?, phone_2 = ?, address = ? WHERE id = ?",
        (full_name, phone, phone_2, address, contact_id),
    )


def with_phone(conn, phone: str) -> list:
    return conn.execute(
        """
        SELECT id, full_name, phone, phone_2, address
          FROM contacts
         WHERE phone = ? OR phone_2 = ?
         ORDER BY id
        """,
        (phone, phone),
    ).fetchall()


def link(conn, student_id: int, contact_id: int, relation: str | None, is_main: bool,
         can_receive_sms: bool) -> None:
    conn.execute(
        """
        INSERT INTO student_contacts(student_id, contact_id, relation, is_main, can_receive_sms)
        VALUES (?, ?, ?, ?, ?)
        """,
        (student_id, contact_id, relation, int(is_main), int(can_receive_sms)),
    )


def get_link(conn, student_id: int, contact_id: int):
    return conn.execute(
        """
        SELECT student_id, contact_id, relation, is_main, can_receive_sms
          FROM student_contacts
         WHERE student_id = ? AND contact_id = ?
        """,
        (student_id, contact_id),
    ).fetchone()


def update_link(conn, student_id: int, contact_id: int, relation: str | None,
                can_receive_sms: bool) -> None:
    conn.execute(
        """
        UPDATE student_contacts
           SET relation = ?, can_receive_sms = ?
         WHERE student_id = ? AND contact_id = ?
        """,
        (relation, int(can_receive_sms), student_id, contact_id),
    )


def main_contact_id(conn, student_id: int) -> int | None:
    row = conn.execute(
        "SELECT contact_id FROM student_contacts WHERE student_id = ? AND is_main = 1",
        (student_id,),
    ).fetchone()
    return None if row is None else int(row[0])


def set_main(conn, student_id: int, contact_id: int) -> None:
    # Clear first: the partial unique index allows only one is_main = 1 row per student.
    conn.execute(
        "UPDATE student_contacts SET is_main = 0 WHERE student_id = ? AND is_main = 1",
        (student_id,),
    )
    conn.execute(
        "UPDATE student_contacts SET is_main = 1 WHERE student_id = ? AND contact_id = ?",
        (student_id, contact_id),
    )


def unlink(conn, student_id: int, contact_id: int) -> None:
    conn.execute(
        "DELETE FROM student_contacts WHERE student_id = ? AND contact_id = ?",
        (student_id, contact_id),
    )


def count_for_student(conn, student_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM student_contacts WHERE student_id = ?",
        (student_id,),
    ).fetchone()
    return int(row[0])


def for_student(conn, student_id: int) -> list:
    """The student's contacts, main contact first."""
    return conn.execute(
        """
        SELECT c.id AS contact_id, c.full_name, c.phone, c.phone_2, c.address,
               sc.relation, sc.is_main, sc.can_receive_sms
          FROM student_contacts sc
          JOIN contacts c ON c.id = sc.contact_id
         WHERE sc.student_id = ?
         ORDER BY sc.is_main DESC, sc.created_at, c.id
        """,
        (student_id,),
    ).fetchall()


def students_of(conn, contact_id: int, exclude_student_id: int | None = None) -> list:
    return conn.execute(
        """
        SELECT s.id, s.student_number, s.first_name, s.last_name
          FROM student_contacts sc
          JOIN students s ON s.id = sc.student_id
         WHERE sc.contact_id = ? AND s.id IS NOT ?
         ORDER BY s.last_name, s.first_name
        """,
        (contact_id, exclude_student_id),
    ).fetchall()
