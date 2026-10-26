
"""Database access layer for the attendance system."""

import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

BASE = Path(__file__).parent
DB_PATH = Path(os.environ.get("ATTENDANCE_DB", BASE / "attendance.db"))
SCHEMA_PATH = BASE / "schema.sql"


def get_conn():
    """Create a SQLite connection with foreign-key enforcement enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(reset=False):
    """Initialize the database, optionally resetting it.

    Callers must close any existing connections before requesting a reset.
    """
    if reset and DB_PATH.exists():
        # Do not silently ignore a failed reset. On Windows, an open
        # connection may prevent deletion, and the caller must resolve it.
        DB_PATH.unlink()

    conn = get_conn()

    try:
        schema = SCHEMA_PATH.read_text(encoding="utf-8")
        conn.executescript(schema)
        conn.commit()
    except Exception:
        conn.close()
        raise

    return conn


# ---------------------------------------------------------------- students

def get_or_create_department(conn, name):
    row = conn.execute(
        "SELECT dept_id FROM department WHERE dept_name = ?",
        (name,),
    ).fetchone()

    if row:
        return row["dept_id"]

    cur = conn.execute(
        "INSERT INTO department(dept_name) VALUES (?)",
        (name,),
    )
    conn.commit()
    return cur.lastrowid


def get_student_by_roll(conn, roll_no):
    return conn.execute(
        "SELECT * FROM student WHERE roll_no = ?",
        (roll_no,),
    ).fetchone()


def add_student(conn, roll_no, full_name, email, dept_id, semester):
    cur = conn.execute(
        """
        INSERT INTO student
            (roll_no, full_name, email, dept_id, semester)
        VALUES (?, ?, ?, ?, ?)
        """,
        (roll_no, full_name, email, dept_id, semester),
    )
    conn.commit()
    return cur.lastrowid


def enroll(conn, student_id, course_code):
    row = conn.execute(
        "SELECT course_id FROM course WHERE course_code = ?",
        (course_code,),
    ).fetchone()

    if not row:
        raise ValueError(f"Unknown course code: {course_code}")

    conn.execute(
        """
        INSERT OR IGNORE INTO enrollment(student_id, course_id)
        VALUES (?, ?)
        """,
        (student_id, row["course_id"]),
    )
    conn.commit()


# ---------------------------------------------------------------- face data

def save_encoding(conn, student_id, encoding):
    """Save a face encoding as a binary vector."""
    blob = np.asarray(encoding, dtype=np.float64).tobytes()

    conn.execute(
        "INSERT INTO face_encoding(student_id, encoding) VALUES (?, ?)",
        (student_id, blob),
    )
    conn.commit()


def load_all_encodings(conn):
    """Return student IDs and the matrix of all stored face encodings."""
    rows = conn.execute(
        "SELECT student_id, encoding FROM face_encoding"
    ).fetchall()

    ids = [row["student_id"] for row in rows]

    matrix = (
        np.array([
            np.frombuffer(row["encoding"], dtype=np.float64)
            for row in rows
        ])
        if rows
        else np.empty((0, 128))
    )

    return ids, matrix


def load_encodings_for_session(conn, session_id):
    """Load face encodings belonging to students enrolled in a session."""
    rows = conn.execute(
        """
        SELECT s.student_id, s.full_name, f.encoding
        FROM class_session cs
        JOIN enrollment e
            ON e.course_id = cs.course_id
        JOIN student s
            ON s.student_id = e.student_id
        JOIN face_encoding f
            ON f.student_id = s.student_id
        WHERE cs.session_id = ?
        """,
        (session_id,),
    ).fetchall()

    ids = [row["student_id"] for row in rows]
    names = {row["student_id"]: row["full_name"] for row in rows}

    matrix = (
        np.array([
            np.frombuffer(row["encoding"], dtype=np.float64)
            for row in rows
        ])
        if rows
        else np.empty((0, 128))
    )

    return ids, names, matrix


# ---------------------------------------------------------------- sessions

def get_or_create_today_session(conn, course_code, minutes=60):
    course = conn.execute(
        "SELECT course_id FROM course WHERE course_code = ?",
        (course_code,),
    ).fetchone()

    if not course:
        raise ValueError(f"Unknown course code: {course_code}")

    today = datetime.now().strftime("%Y-%m-%d")

    row = conn.execute(
        """
        SELECT session_id
        FROM class_session
        WHERE course_id = ?
          AND session_date = ?
          AND status IN ('Scheduled', 'Open')
        ORDER BY start_time
        LIMIT 1
        """,
        (course["course_id"], today),
    ).fetchone()

    if row:
        return row["session_id"]

    now = datetime.now()

    cur = conn.execute(
        """
        INSERT INTO class_session
            (course_id, session_date, start_time, end_time)
        VALUES (?, ?, ?, ?)
        """,
        (
            course["course_id"],
            today,
            now.strftime("%H:%M"),
            (now + timedelta(minutes=minutes)).strftime("%H:%M"),
        ),
    )

    conn.commit()
    return cur.lastrowid


def set_session_status(conn, session_id, status):
    conn.execute(
        "UPDATE class_session SET status = ? WHERE session_id = ?",
        (status, session_id),
    )
    conn.commit()


def get_session(conn, session_id):
    return conn.execute(
        """
        SELECT cs.*, c.course_code, c.title
        FROM class_session cs
        JOIN course c ON c.course_id = cs.course_id
        WHERE cs.session_id = ?
        """,
        (session_id,),
    ).fetchone()


# ---------------------------------------------------------------- attendance

def marked_student_ids(conn, session_id):
    rows = conn.execute(
        "SELECT student_id FROM attendance WHERE session_id = ?",
        (session_id,),
    ).fetchall()

    return {row["student_id"] for row in rows}


def mark_attendance(
    conn,
    session_id,
    student_id,
    distance=None,
    challenge=None,
):
    """Insert attendance. Return False if already marked."""
    if student_id in marked_student_ids(conn, session_id):
        return False

    conn.execute(
        """
        INSERT INTO attendance
            (session_id, student_id, match_distance, liveness_challenge)
        VALUES (?, ?, ?, ?)
        """,
        (session_id, student_id, distance, challenge),
    )

    conn.commit()
    return True


def log_spoof(conn, session_id, student_id, reason, challenge=None):
    conn.execute(
        """
        INSERT INTO spoof_attempt
            (session_id, student_id, reason, challenge)
        VALUES (?, ?, ?, ?)
        """,
        (session_id, student_id, reason, challenge),
    )
    conn.commit()


def absentees(conn, session_id):
    return conn.execute(
        """
        SELECT s.roll_no, s.full_name
        FROM class_session cs
        JOIN enrollment e
            ON e.course_id = cs.course_id
        JOIN student s
            ON s.student_id = e.student_id
        WHERE cs.session_id = ?
          AND NOT EXISTS (
              SELECT 1
              FROM attendance a
              WHERE a.session_id = cs.session_id
                AND a.student_id = s.student_id
          )
        ORDER BY s.roll_no
        """,
        (session_id,),
    ).fetchall()

