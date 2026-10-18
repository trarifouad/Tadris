-- ========== Reference / config ==========
CREATE TABLE school_years (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  label      TEXT NOT NULL UNIQUE,
  start_date TEXT NOT NULL,
  end_date   TEXT NOT NULL,
  status     TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','closed')),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
  CHECK (end_date > start_date)
);

CREATE TABLE levels (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  name        TEXT NOT NULL UNIQUE,
  order_index INTEGER NOT NULL DEFAULT 0,
  is_active   INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1))
);

CREATE TABLE subjects (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  name      TEXT NOT NULL UNIQUE,
  is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1))
);

CREATE TABLE rooms (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  name     TEXT NOT NULL UNIQUE,
  capacity INTEGER NOT NULL CHECK (capacity >= 1),
  status   TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','inactive'))
);

CREATE TABLE users (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  username      TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role          TEXT NOT NULL CHECK (role IN ('director','receptionist')),
  status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')),
  created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
  updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime'))
);

CREATE TABLE settings (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime'))
);

-- one counter per sequence and year, e.g. 'receipt:2026', 'student:2026'
CREATE TABLE counters (
  name       TEXT PRIMARY KEY,
  last_value INTEGER NOT NULL DEFAULT 0 CHECK (last_value >= 0),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime'))
);

CREATE TABLE audit_log (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     INTEGER REFERENCES users(id) ON DELETE RESTRICT,
  action      TEXT NOT NULL,
  entity_name TEXT NOT NULL,
  entity_id   INTEGER,
  old_value   TEXT,
  new_value   TEXT,
  created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime'))
);

CREATE TABLE print_log (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  document_type TEXT NOT NULL,
  document_id   INTEGER NOT NULL,
  printed_by    INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  printed_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime'))
);

-- ========== People ==========
CREATE TABLE contacts (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  full_name  TEXT NOT NULL,
  phone      TEXT,
  phone_2    TEXT,
  address    TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime'))
);

CREATE TABLE students (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  student_number TEXT NOT NULL UNIQUE,
  first_name     TEXT NOT NULL,
  last_name      TEXT NOT NULL,
  birth_date     TEXT,
  status         TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','inactive')),
  notes          TEXT,
  created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
  updated_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime'))
);

CREATE TABLE student_contacts (
  student_id      INTEGER NOT NULL REFERENCES students(id) ON DELETE RESTRICT,
  contact_id      INTEGER NOT NULL REFERENCES contacts(id) ON DELETE RESTRICT,
  relation        TEXT,
  is_main         INTEGER NOT NULL DEFAULT 0 CHECK (is_main IN (0,1)),
  can_receive_sms INTEGER NOT NULL DEFAULT 1 CHECK (can_receive_sms IN (0,1)),
  created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
  PRIMARY KEY (student_id, contact_id)
);
CREATE UNIQUE INDEX uq_student_main_contact
  ON student_contacts(student_id) WHERE is_main = 1;

CREATE TABLE teachers (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  full_name  TEXT NOT NULL,
  phone      TEXT,
  status     TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','inactive')),
  hire_date  TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime'))
);

CREATE TABLE teacher_rates (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  teacher_id    INTEGER NOT NULL REFERENCES teachers(id) ON DELETE RESTRICT,
  percentage_bp INTEGER NOT NULL CHECK (percentage_bp BETWEEN 0 AND 10000),
  valid_from    TEXT NOT NULL,
  valid_to      TEXT,
  created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
  CHECK (valid_to IS NULL OR valid_to > valid_from)
);
CREATE UNIQUE INDEX uq_teacher_rate_open
  ON teacher_rates(teacher_id) WHERE valid_to IS NULL;

-- ========== Academic ==========
CREATE TABLE registrations (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  student_id     INTEGER NOT NULL REFERENCES students(id) ON DELETE RESTRICT,
  school_year_id INTEGER NOT NULL REFERENCES school_years(id) ON DELETE RESTRICT,
  level_id       INTEGER NOT NULL REFERENCES levels(id) ON DELETE RESTRICT,
  fee_amount     INTEGER NOT NULL CHECK (fee_amount >= 0),
  status         TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','cancelled')),
  registered_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
  created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
  UNIQUE (student_id, school_year_id)
);

CREATE TABLE class_groups (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  school_year_id INTEGER NOT NULL REFERENCES school_years(id) ON DELETE RESTRICT,
  level_id       INTEGER NOT NULL REFERENCES levels(id) ON DELETE RESTRICT,
  subject_id     INTEGER NOT NULL REFERENCES subjects(id) ON DELETE RESTRICT,
  name           TEXT NOT NULL,
  price          INTEGER NOT NULL CHECK (price >= 0),
  capacity       INTEGER NOT NULL CHECK (capacity >= 1),
  start_date     TEXT NOT NULL,
  status         TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('planned','active','closed')),
  created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
  updated_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime'))
);

CREATE TABLE group_teachers (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  group_id   INTEGER NOT NULL REFERENCES class_groups(id) ON DELETE RESTRICT,
  teacher_id INTEGER NOT NULL REFERENCES teachers(id) ON DELETE RESTRICT,
  valid_from TEXT NOT NULL,
  valid_to   TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
  CHECK (valid_to IS NULL OR valid_to > valid_from)
);
CREATE UNIQUE INDEX uq_group_teacher_open
  ON group_teachers(group_id) WHERE valid_to IS NULL;

CREATE TABLE enrollments (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  student_id       INTEGER NOT NULL REFERENCES students(id) ON DELETE RESTRICT,
  group_id         INTEGER NOT NULL REFERENCES class_groups(id) ON DELETE RESTRICT,
  registration_id  INTEGER NOT NULL REFERENCES registrations(id) ON DELETE RESTRICT,
  switched_from_id INTEGER REFERENCES enrollments(id) ON DELETE RESTRICT,
  started_as_trial INTEGER NOT NULL DEFAULT 0 CHECK (started_as_trial IN (0,1)),
  enrolled_on      TEXT NOT NULL,
  left_on          TEXT,
  status           TEXT NOT NULL DEFAULT 'active'
                   CHECK (status IN ('trial','active','left','switched')),
  created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
  updated_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
  CHECK (left_on IS NULL OR left_on >= enrolled_on)
);
CREATE UNIQUE INDEX uq_enrollment_live
  ON enrollments(student_id, group_id) WHERE status IN ('trial','active');
CREATE UNIQUE INDEX uq_enrollment_one_trial
  ON enrollments(student_id) WHERE started_as_trial = 1;

CREATE TABLE timetable_slots (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  group_id   INTEGER NOT NULL REFERENCES class_groups(id) ON DELETE RESTRICT,
  room_id    INTEGER NOT NULL REFERENCES rooms(id) ON DELETE RESTRICT,
  weekday    INTEGER NOT NULL CHECK (weekday BETWEEN 1 AND 7),   -- 1=Mon .. 7=Sun
  start_time TEXT NOT NULL,                                       -- 'HH:MM'
  end_time   TEXT NOT NULL,
  valid_from TEXT NOT NULL,
  valid_to   TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
  CHECK (end_time > start_time),
  CHECK (valid_to IS NULL OR valid_to > valid_from)
);

CREATE TABLE sessions (
  id                   INTEGER PRIMARY KEY AUTOINCREMENT,
  group_id             INTEGER NOT NULL REFERENCES class_groups(id) ON DELETE RESTRICT,
  slot_id              INTEGER REFERENCES timetable_slots(id) ON DELETE RESTRICT,
  room_id              INTEGER NOT NULL REFERENCES rooms(id) ON DELETE RESTRICT,
  teacher_id           INTEGER NOT NULL REFERENCES teachers(id) ON DELETE RESTRICT,
  makeup_of_session_id INTEGER REFERENCES sessions(id) ON DELETE RESTRICT,
  date                 TEXT NOT NULL,
  start_time           TEXT NOT NULL,
  end_time             TEXT NOT NULL,
  status               TEXT NOT NULL DEFAULT 'planned'
                       CHECK (status IN ('planned','held','cancelled')),
  source               TEXT NOT NULL DEFAULT 'generated'
                       CHECK (source IN ('generated','manual','makeup')),
  cancellation_reason  TEXT,
  created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
  updated_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
  CHECK (end_time > start_time),
  CHECK (status <> 'cancelled' OR cancellation_reason IS NOT NULL)
);
CREATE UNIQUE INDEX uq_session_slot_date
  ON sessions(slot_id, date) WHERE slot_id IS NOT NULL;

CREATE TABLE attendances (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id    INTEGER NOT NULL REFERENCES sessions(id) ON DELETE RESTRICT,
  enrollment_id INTEGER NOT NULL REFERENCES enrollments(id) ON DELETE RESTRICT,
  status        TEXT NOT NULL CHECK (status IN ('present','late','absent','excused')),
  entered_by    INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  entered_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
  updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
  UNIQUE (session_id, enrollment_id)
);

-- ========== Finance ==========
-- Money = whole DZD integers. Debt is derived, never stored.
CREATE TABLE subscriptions (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  enrollment_id INTEGER NOT NULL REFERENCES enrollments(id) ON DELETE RESTRICT,
  renewal_of_id INTEGER REFERENCES subscriptions(id) ON DELETE RESTRICT,
  price         INTEGER NOT NULL CHECK (price >= 0),        -- snapshot of group price
  start_date    TEXT NOT NULL,
  end_date      TEXT NOT NULL,                              -- start + 1 month, absence never extends
  status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','ended','cancelled')),
  created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
  updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
  CHECK (end_date > start_date)
);
CREATE UNIQUE INDEX uq_subscription_renewal
  ON subscriptions(renewal_of_id) WHERE renewal_of_id IS NOT NULL;

-- A charge is an amount owed. Only 'open' / 'cancelled'; paid/partial is derived.
CREATE TABLE charges (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  registration_id INTEGER REFERENCES registrations(id) ON DELETE RESTRICT,
  subscription_id INTEGER REFERENCES subscriptions(id) ON DELETE RESTRICT,
  description     TEXT NOT NULL,
  amount          INTEGER NOT NULL CHECK (amount > 0),
  due_date        TEXT NOT NULL,
  accrual_date    TEXT NOT NULL,                            -- = subscription start_date for subscription charges
  status          TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','cancelled')),
  created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
  CHECK ((registration_id IS NULL) <> (subscription_id IS NULL))   -- exactly one
);

-- A payment is money received. Reversals use payment_voids, never negative payments.
CREATE TABLE payments (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  student_id       INTEGER NOT NULL REFERENCES students(id) ON DELETE RESTRICT,
  payer_contact_id INTEGER REFERENCES contacts(id) ON DELETE RESTRICT,
  amount           INTEGER NOT NULL CHECK (amount > 0),
  method           TEXT NOT NULL CHECK (method IN ('cash','transfer','cheque','other')),
  paid_at          TEXT NOT NULL,
  received_by      INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime'))
);

CREATE TABLE payment_voids (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  payment_id INTEGER NOT NULL UNIQUE REFERENCES payments(id) ON DELETE RESTRICT,
  reason     TEXT NOT NULL,
  voided_by  INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  voided_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime'))
);

CREATE TABLE payment_allocations (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  payment_id INTEGER NOT NULL REFERENCES payments(id) ON DELETE RESTRICT,
  charge_id  INTEGER NOT NULL REFERENCES charges(id) ON DELETE RESTRICT,
  amount     INTEGER NOT NULL CHECK (amount > 0),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
  UNIQUE (payment_id, charge_id)
);

CREATE TABLE receipts (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  payment_id INTEGER NOT NULL UNIQUE REFERENCES payments(id) ON DELETE RESTRICT,
  number     TEXT NOT NULL UNIQUE,
  issued_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime'))
);

-- Signed adjustments. Positive amount REDUCES debt (discount), negative increases it.
CREATE TABLE balance_entries (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  student_id      INTEGER NOT NULL REFERENCES students(id) ON DELETE RESTRICT,
  subscription_id INTEGER REFERENCES subscriptions(id) ON DELETE RESTRICT,
  charge_id       INTEGER REFERENCES charges(id) ON DELETE RESTRICT,
  entry_type      TEXT NOT NULL CHECK (entry_type IN ('discount','correction')),
  amount          INTEGER NOT NULL CHECK (amount <> 0),
  reason          TEXT NOT NULL,
  created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
  created_by      INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT
);

CREATE TABLE refunds (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  subscription_id INTEGER NOT NULL REFERENCES subscriptions(id) ON DELETE RESTRICT,
  amount_computed INTEGER NOT NULL CHECK (amount_computed >= 0),
  amount_final    INTEGER NOT NULL CHECK (amount_final >= 0),
  refunded_amount INTEGER NOT NULL DEFAULT 0 CHECK (refunded_amount >= 0),
  reason          TEXT NOT NULL,
  status          TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending','approved','paid','rejected')),
  approved_by     INTEGER REFERENCES users(id) ON DELETE RESTRICT,
  approved_at     TEXT,
  paid_out_at     TEXT,
  created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime'))
);

CREATE TABLE refund_allocations (
  id                    INTEGER PRIMARY KEY AUTOINCREMENT,
  refund_id             INTEGER NOT NULL REFERENCES refunds(id) ON DELETE RESTRICT,
  payment_allocation_id INTEGER NOT NULL REFERENCES payment_allocations(id) ON DELETE RESTRICT,
  amount                INTEGER NOT NULL CHECK (amount > 0),
  created_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
  UNIQUE (refund_id, payment_allocation_id)
);

-- ========== Teacher payouts (accrual: full subscription price x percentage) ==========
CREATE TABLE teacher_payouts (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  teacher_id     INTEGER NOT NULL REFERENCES teachers(id) ON DELETE RESTRICT,
  period_start   TEXT NOT NULL,
  period_end     TEXT NOT NULL,
  base_amount    INTEGER NOT NULL CHECK (base_amount > 0),
  amount_due     INTEGER NOT NULL CHECK (amount_due > 0),
  amount_paid    INTEGER NOT NULL DEFAULT 0 CHECK (amount_paid >= 0),
  receipt_number TEXT UNIQUE,
  status         TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','approved','paid')),
  paid_at        TEXT,
  created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
  CHECK (period_end >= period_start),
  UNIQUE (teacher_id, period_start, period_end)
);

CREATE TABLE payout_lines (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  payout_id     INTEGER NOT NULL REFERENCES teacher_payouts(id) ON DELETE RESTRICT,
  group_id      INTEGER NOT NULL REFERENCES class_groups(id) ON DELETE RESTRICT,
  revenue_basis INTEGER NOT NULL CHECK (revenue_basis >= 0),
  percentage_bp INTEGER NOT NULL CHECK (percentage_bp BETWEEN 0 AND 10000),  -- snapshot
  amount        INTEGER NOT NULL CHECK (amount >= 0),
  created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
  UNIQUE (payout_id, group_id)
);

CREATE TABLE payout_line_charges (
  payout_line_id INTEGER NOT NULL REFERENCES payout_lines(id) ON DELETE RESTRICT,
  charge_id      INTEGER NOT NULL REFERENCES charges(id) ON DELETE RESTRICT,
  amount         INTEGER NOT NULL CHECK (amount > 0),
  PRIMARY KEY (payout_line_id, charge_id)
);
CREATE UNIQUE INDEX uq_payout_charge_once ON payout_line_charges(charge_id);

-- ========== SMS ==========
CREATE TABLE sms_queue (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  student_id      INTEGER NOT NULL REFERENCES students(id) ON DELETE RESTRICT,
  contact_id      INTEGER NOT NULL REFERENCES contacts(id) ON DELETE RESTRICT,
  attendance_id   INTEGER REFERENCES attendances(id) ON DELETE RESTRICT,
  kind            TEXT NOT NULL,
  message         TEXT NOT NULL,
  status          TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending','sent','failed','cancelled')),
  attempts        INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  next_attempt_at TEXT,
  sent_at         TEXT,
  last_error      TEXT,
  created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime'))
);

-- ========== Backups ==========
CREATE TABLE backups (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  file_path    TEXT NOT NULL,
  size_bytes   INTEGER CHECK (size_bytes IS NULL OR size_bytes >= 0),
  checksum     TEXT,
  type         TEXT NOT NULL CHECK (type IN ('auto','manual')),
  status       TEXT NOT NULL DEFAULT 'running'
               CHECK (status IN ('running','done','failed','verified')),
  created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
  completed_at TEXT,
  verified_at  TEXT
);

CREATE TABLE restore_log (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  backup_id   INTEGER NOT NULL REFERENCES backups(id) ON DELETE RESTRICT,
  restored_by INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  result      TEXT NOT NULL CHECK (result IN ('success','failed')),
  restored_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime'))
);
