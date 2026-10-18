-- Phase 2: student list, contact lookup by phone, duplicate checks.
CREATE INDEX ix_students_name             ON students(last_name, first_name);
CREATE INDEX ix_students_status           ON students(status);
CREATE INDEX ix_student_contacts_contact  ON student_contacts(contact_id);
CREATE INDEX ix_contacts_phone            ON contacts(phone);
CREATE INDEX ix_contacts_phone_2          ON contacts(phone_2);
