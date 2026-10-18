import pytest

from tadris.core import security
from tadris.db.connection import connect
from tadris.db.migrate import migrate
from tadris.services import auth as auth_service

security.N = 2**4


@pytest.fixture
def conn():
    auth_service._reset_failures()
    c = connect(":memory:")
    migrate(c)
    yield c
    c.close()

@pytest.fixture
def seeded(conn):
    conn.executescript("""
    INSERT INTO school_years(label,start_date,end_date) VALUES('2026-2027','2026-09-01','2027-06-30');
    INSERT INTO levels(name) VALUES('3AM');
    INSERT INTO subjects(name) VALUES('Math');
    INSERT INTO users(username,password_hash,role) VALUES('u','x','director');
    INSERT INTO students(student_number,first_name,last_name) VALUES('2026-0001','A','B');
    INSERT INTO teachers(full_name) VALUES('T');
    INSERT INTO registrations(student_id,school_year_id,level_id,fee_amount) VALUES(1,1,1,2000);
    INSERT INTO class_groups(school_year_id,level_id,subject_id,name,price,capacity,start_date)
      VALUES(1,1,1,'G1',3000,10,'2026-09-01');
    INSERT INTO enrollments(student_id,group_id,registration_id,enrolled_on) VALUES(1,1,1,'2026-09-01');
    INSERT INTO group_teachers(group_id,teacher_id,valid_from) VALUES(1,1,'2026-08-01');
    INSERT INTO subscriptions(enrollment_id,price,start_date,end_date)
      VALUES(1,3000,'2026-09-01','2026-10-01');
    INSERT INTO charges(subscription_id,description,amount,due_date,accrual_date)
      VALUES(1,'Sept',3000,'2026-09-01','2026-09-01');
    INSERT INTO payments(student_id,amount,method,paid_at,received_by)
      VALUES(1,3000,'cash','2026-09-02T10:00:00',1);
    """)
    return conn
