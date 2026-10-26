-- ============================================================
--  Attendance using Face Recognition & Anti-Spoofing
--  Database schema (SQLite) - normalized to 3NF
-- ============================================================
PRAGMA foreign_keys = ON;

-- ---------- Master tables ----------
CREATE TABLE IF NOT EXISTS department (
    dept_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    dept_name   TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS student (
    student_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    roll_no     TEXT NOT NULL UNIQUE,
    full_name   TEXT NOT NULL,
    email       TEXT UNIQUE,
    dept_id     INTEGER NOT NULL
                REFERENCES department(dept_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    semester    INTEGER NOT NULL CHECK (semester BETWEEN 1 AND 8),
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS faculty (
    faculty_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name   TEXT NOT NULL,
    email       TEXT NOT NULL UNIQUE,
    dept_id     INTEGER NOT NULL
                REFERENCES department(dept_id) ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS course (
    course_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    course_code TEXT NOT NULL UNIQUE,
    title       TEXT NOT NULL,
    semester    INTEGER NOT NULL CHECK (semester BETWEEN 1 AND 8),
    dept_id     INTEGER NOT NULL
                REFERENCES department(dept_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    faculty_id  INTEGER NOT NULL
                REFERENCES faculty(faculty_id) ON UPDATE CASCADE ON DELETE RESTRICT
);

-- ---------- Biometric data (1 student -> many face samples) ----------
CREATE TABLE IF NOT EXISTS face_encoding (
    encoding_id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id  INTEGER NOT NULL
                REFERENCES student(student_id) ON DELETE CASCADE,
    encoding    BLOB NOT NULL CHECK (length(encoding) = 1024),  -- 128 x float64
    captured_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- ---------- M:N  student <-> course ----------
CREATE TABLE IF NOT EXISTS enrollment (
    student_id  INTEGER NOT NULL
                REFERENCES student(student_id) ON DELETE CASCADE,
    course_id   INTEGER NOT NULL
                REFERENCES course(course_id) ON DELETE CASCADE,
    enrolled_on TEXT NOT NULL DEFAULT (date('now','localtime')),
    PRIMARY KEY (student_id, course_id)
);

-- ---------- Lectures ----------
CREATE TABLE IF NOT EXISTS class_session (
    session_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id    INTEGER NOT NULL
                 REFERENCES course(course_id) ON DELETE CASCADE,
    session_date TEXT NOT NULL,                 -- YYYY-MM-DD
    start_time   TEXT NOT NULL,                 -- HH:MM
    end_time     TEXT NOT NULL,                 -- HH:MM
    status       TEXT NOT NULL DEFAULT 'Scheduled'
                 CHECK (status IN ('Scheduled','Open','Closed')),
    UNIQUE (course_id, session_date, start_time)
);

-- ---------- Attendance (one row per student per session) ----------
CREATE TABLE IF NOT EXISTS attendance (
    attendance_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id         INTEGER NOT NULL
                       REFERENCES class_session(session_id) ON DELETE CASCADE,
    student_id         INTEGER NOT NULL
                       REFERENCES student(student_id) ON DELETE CASCADE,
    marked_at          TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    status             TEXT NOT NULL DEFAULT 'Present'
                       CHECK (status IN ('Present','Late')),
    match_distance     REAL,           -- face distance (lower = better match)
    liveness_challenge TEXT,           -- which anti-spoof challenge was passed
    UNIQUE (session_id, student_id)    -- no duplicate attendance
);

-- ---------- Security audit log ----------
CREATE TABLE IF NOT EXISTS spoof_attempt (
    attempt_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL
                REFERENCES class_session(session_id) ON DELETE CASCADE,
    student_id  INTEGER                       -- identity the face claimed to be
                REFERENCES student(student_id) ON DELETE SET NULL,
    reason      TEXT NOT NULL
                CHECK (reason IN ('CHALLENGE_TIMEOUT','IDENTITY_SWITCH','LOW_TEXTURE')),
    challenge   TEXT,
    detected_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- ---------- Indexes ----------
CREATE INDEX IF NOT EXISTS idx_face_student     ON face_encoding(student_id);
CREATE INDEX IF NOT EXISTS idx_attendance_stud  ON attendance(student_id);
CREATE INDEX IF NOT EXISTS idx_session_course   ON class_session(course_id, session_date);
CREATE INDEX IF NOT EXISTS idx_spoof_session    ON spoof_attempt(session_id);

-- ============================================================
--  TRIGGERS  (business rules enforced inside the database)
-- ============================================================

-- Rule 1: only students enrolled in the course may be marked present
CREATE TRIGGER IF NOT EXISTS trg_attendance_enrolled
BEFORE INSERT ON attendance
WHEN NOT EXISTS (
    SELECT 1
    FROM class_session cs
    JOIN enrollment e ON e.course_id = cs.course_id
    WHERE cs.session_id = NEW.session_id AND e.student_id = NEW.student_id
)
BEGIN
    SELECT RAISE(ABORT, 'Student is not enrolled in this course');
END;

-- Rule 2: attendance can only be marked while the session is Open
CREATE TRIGGER IF NOT EXISTS trg_attendance_session_open
BEFORE INSERT ON attendance
WHEN (SELECT status FROM class_session WHERE session_id = NEW.session_id) <> 'Open'
BEGIN
    SELECT RAISE(ABORT, 'Session is not open for attendance');
END;

-- Rule 3: more than 10 minutes after start time => status becomes 'Late'
CREATE TRIGGER IF NOT EXISTS trg_attendance_late
AFTER INSERT ON attendance
WHEN (
    SELECT (julianday(NEW.marked_at) - julianday(cs.session_date || ' ' || cs.start_time)) * 1440
    FROM class_session cs WHERE cs.session_id = NEW.session_id
) > 10
BEGIN
    UPDATE attendance SET status = 'Late' WHERE attendance_id = NEW.attendance_id;
END;

-- ============================================================
--  VIEWS
-- ============================================================

-- Attendance percentage of every student in every enrolled course
CREATE VIEW IF NOT EXISTS v_attendance_summary AS
SELECT s.student_id, s.roll_no, s.full_name,
       c.course_id, c.course_code, c.title,
       t.total_sessions, t.attended,
       CASE WHEN t.total_sessions = 0 THEN 0.0
            ELSE ROUND(100.0 * t.attended / t.total_sessions, 2) END AS attendance_pct
FROM (
    SELECT e.student_id, e.course_id,
           (SELECT COUNT(*) FROM class_session cs
             WHERE cs.course_id = e.course_id
               AND cs.status IN ('Open','Closed'))              AS total_sessions,
           (SELECT COUNT(*) FROM attendance a
              JOIN class_session cs ON cs.session_id = a.session_id
             WHERE a.student_id = e.student_id
               AND cs.course_id = e.course_id)                  AS attended
    FROM enrollment e
) t
JOIN student s ON s.student_id = t.student_id
JOIN course  c ON c.course_id  = t.course_id;

-- Students below the 75% rule
CREATE VIEW IF NOT EXISTS v_defaulters AS
SELECT * FROM v_attendance_summary
WHERE total_sessions > 0 AND attendance_pct < 75;

-- One line per session with head-count
CREATE VIEW IF NOT EXISTS v_session_report AS
SELECT cs.session_id, c.course_code, cs.session_date, cs.start_time, cs.status,
       (SELECT COUNT(*) FROM enrollment e WHERE e.course_id = cs.course_id) AS enrolled,
       (SELECT COUNT(*) FROM attendance a WHERE a.session_id = cs.session_id) AS present,
       (SELECT COUNT(*) FROM spoof_attempt sp WHERE sp.session_id = cs.session_id) AS spoof_attempts
FROM class_session cs
JOIN course c ON c.course_id = cs.course_id;
