"""All the SQL the dashboard needs (no Streamlit in here, so it can be tested on its own).

Most queries read from the views in schema.sql:
    v_attendance_summary, v_defaulters, v_session_report
"""
import pandas as pd

import db


def _df(sql, params=()):
    conn = db.get_conn()
    try:
        return pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()


def db_ready():
    """True if the tables exist and there is at least one student."""
    try:
        return int(_df("SELECT COUNT(*) AS n FROM student")["n"][0]) > 0
    except Exception:
        return False


# ---------------------------------------------------------------- lookups
def courses():
    return _df("SELECT course_code, title FROM course ORDER BY course_code")


def departments():
    return _df("SELECT dept_name FROM department ORDER BY dept_name")


# ---------------------------------------------------------------- headline numbers
def kpis(threshold=75):
    one = lambda sql, p=(): int(_df(sql, p).iloc[0, 0])
    return {
        "students": one("SELECT COUNT(*) FROM student"),
        "courses": one("SELECT COUNT(*) FROM course"),
        "sessions": one("SELECT COUNT(*) FROM class_session WHERE status IN ('Open','Closed')"),
        "marked": one("SELECT COUNT(*) FROM attendance"),
        "late": one("SELECT COUNT(*) FROM attendance WHERE status = 'Late'"),
        "spoofs": one("SELECT COUNT(*) FROM spoof_attempt"),
        "no_face": one("SELECT COUNT(*) FROM student s WHERE NOT EXISTS "
                       "(SELECT 1 FROM face_encoding f WHERE f.student_id = s.student_id)"),
        "defaulters": one("SELECT COUNT(DISTINCT student_id) FROM v_attendance_summary "
                          "WHERE total_sessions > 0 AND attendance_pct < ?", (threshold,)),
        "avg_pct": float(_df("SELECT COALESCE(AVG(attendance_pct),0) FROM v_attendance_summary").iloc[0, 0]),
    }


# ---------------------------------------------------------------- attendance
def summary(course=None, dept=None):
    sql = """SELECT v.roll_no, v.full_name, d.dept_name, v.course_code, v.title,
                    v.attended, v.total_sessions, v.attendance_pct
               FROM v_attendance_summary v
               JOIN student s    ON s.student_id = v.student_id
               JOIN department d ON d.dept_id = s.dept_id
              WHERE 1=1"""
    p = []
    if course:
        sql += " AND v.course_code = ?"; p.append(course)
    if dept:
        sql += " AND d.dept_name = ?"; p.append(dept)
    return _df(sql + " ORDER BY v.course_code, v.roll_no", p)


def course_averages():
    return _df("""SELECT course_code, ROUND(AVG(attendance_pct),1) AS avg_pct,
                         COUNT(*) AS students
                    FROM v_attendance_summary GROUP BY course_code ORDER BY course_code""")


def student_overall():
    """One row per student: total attended / total sessions across all courses."""
    return _df("""SELECT roll_no, full_name, SUM(attended) AS attended,
                         SUM(total_sessions) AS total,
                         ROUND(100.0 * SUM(attended) / SUM(total_sessions), 1) AS pct
                    FROM v_attendance_summary WHERE total_sessions > 0
                   GROUP BY student_id ORDER BY pct DESC""")


def defaulters(threshold=75):
    if threshold == 75:   # the 75% rule is exactly what the v_defaulters view stores
        return _df("""SELECT roll_no, full_name, course_code, attended, total_sessions, attendance_pct
                        FROM v_defaulters ORDER BY attendance_pct""")
    return _df("""SELECT roll_no, full_name, course_code, attended, total_sessions, attendance_pct
                    FROM v_attendance_summary
                   WHERE total_sessions > 0 AND attendance_pct < ?
                   ORDER BY attendance_pct""", (threshold,))


def daily_trend():
    return _df("""SELECT cs.session_date AS day, c.course_code,
                         COUNT(a.attendance_id) AS present,
                         (SELECT COUNT(*) FROM enrollment e WHERE e.course_id = cs.course_id) AS enrolled
                    FROM class_session cs
                    JOIN course c ON c.course_id = cs.course_id
                    LEFT JOIN attendance a ON a.session_id = cs.session_id
                   WHERE cs.status IN ('Open','Closed')
                   GROUP BY cs.session_id ORDER BY cs.session_date""")


def monthly_attendance():
    return _df("""SELECT strftime('%Y-%m', cs.session_date) AS month,
                         COUNT(a.attendance_id) AS marked
                    FROM class_session cs LEFT JOIN attendance a ON a.session_id = cs.session_id
                   GROUP BY month ORDER BY month""")


def status_split():
    return _df("SELECT status, COUNT(*) AS n FROM attendance GROUP BY status")


def late_by_student():
    return _df("""SELECT s.roll_no, s.full_name, COUNT(*) AS late_count
                    FROM attendance a JOIN student s ON s.student_id = a.student_id
                   WHERE a.status = 'Late' GROUP BY s.student_id ORDER BY late_count DESC""")


def heatmap(course_code):
    """student x session grid: 1 = present/late, 0 = absent."""
    return _df("""SELECT s.roll_no, cs.session_date AS day,
                         CASE WHEN a.attendance_id IS NULL THEN 'Absent'
                              ELSE a.status END AS status
                    FROM class_session cs
                    JOIN course c      ON c.course_id = cs.course_id
                    JOIN enrollment e  ON e.course_id = cs.course_id
                    JOIN student s     ON s.student_id = e.student_id
                    LEFT JOIN attendance a ON a.session_id = cs.session_id AND a.student_id = s.student_id
                   WHERE c.course_code = ? AND cs.status IN ('Open','Closed')
                   ORDER BY s.roll_no, cs.session_date""", (course_code,))


def by_weekday():
    return _df("""SELECT CASE strftime('%w', cs.session_date)
                            WHEN '0' THEN 'Sun' WHEN '1' THEN 'Mon' WHEN '2' THEN 'Tue'
                            WHEN '3' THEN 'Wed' WHEN '4' THEN 'Thu' WHEN '5' THEN 'Fri'
                            ELSE 'Sat' END AS weekday,
                         strftime('%w', cs.session_date) AS wd_no,
                         COUNT(a.attendance_id) AS marked
                    FROM class_session cs LEFT JOIN attendance a ON a.session_id = cs.session_id
                   GROUP BY wd_no ORDER BY wd_no""")


# ---------------------------------------------------------------- sessions
def sessions():
    return _df("""SELECT session_id, course_code, session_date, start_time, status,
                         enrolled, present, spoof_attempts
                    FROM v_session_report ORDER BY session_date DESC, start_time DESC""")


def session_present(session_id):
    return _df("""SELECT s.roll_no, s.full_name, a.status, a.marked_at,
                         ROUND(a.match_distance,3) AS distance, a.liveness_challenge AS challenge
                    FROM attendance a JOIN student s ON s.student_id = a.student_id
                   WHERE a.session_id = ? ORDER BY a.marked_at""", (session_id,))


def session_absent(session_id):
    conn = db.get_conn()
    try:
        rows = db.absentees(conn, session_id)
    finally:
        conn.close()
    return pd.DataFrame([dict(r) for r in rows], columns=["roll_no", "full_name"])


# ---------------------------------------------------------------- security
def spoof_log():
    return _df("""SELECT sp.detected_at, c.course_code, COALESCE(s.roll_no,'unknown') AS claimed_roll,
                         sp.reason, sp.challenge
                    FROM spoof_attempt sp
                    JOIN class_session cs ON cs.session_id = sp.session_id
                    JOIN course c ON c.course_id = cs.course_id
                    LEFT JOIN student s ON s.student_id = sp.student_id
                   ORDER BY sp.detected_at DESC""")


def spoof_by_reason():
    return _df("SELECT reason, COUNT(*) AS attempts FROM spoof_attempt GROUP BY reason ORDER BY attempts DESC")


def spoof_by_course():
    return _df("""SELECT c.course_code, COUNT(*) AS attempts
                    FROM spoof_attempt sp
                    JOIN class_session cs ON cs.session_id = sp.session_id
                    JOIN course c ON c.course_id = cs.course_id
                   GROUP BY c.course_code""")


def challenge_usage():
    return _df("""SELECT liveness_challenge AS challenge, COUNT(*) AS n
                    FROM attendance WHERE liveness_challenge IS NOT NULL
                   GROUP BY liveness_challenge""")


def match_distances():
    return _df("SELECT match_distance FROM attendance WHERE match_distance IS NOT NULL")


# ---------------------------------------------------------------- students / faces
def student_list():
    return _df("""SELECT s.roll_no, s.full_name, d.dept_name, s.semester, s.email,
                         (SELECT COUNT(*) FROM face_encoding f WHERE f.student_id = s.student_id) AS face_samples
                    FROM student s JOIN department d ON d.dept_id = s.dept_id
                   ORDER BY s.roll_no""")


def student_courses(roll_no):
    return _df("""SELECT course_code, title, attended, total_sessions, attendance_pct
                    FROM v_attendance_summary WHERE roll_no = ? ORDER BY course_code""", (roll_no,))


def student_history(roll_no):
    return _df("""SELECT cs.session_date AS day, c.course_code, a.status, a.marked_at
                    FROM attendance a
                    JOIN student s ON s.student_id = a.student_id
                    JOIN class_session cs ON cs.session_id = a.session_id
                    JOIN course c ON c.course_id = cs.course_id
                   WHERE s.roll_no = ? ORDER BY cs.session_date DESC""", (roll_no,))


def table_counts():
    names = ["department", "student", "faculty", "course", "face_encoding", "enrollment",
             "class_session", "attendance", "spoof_attempt"]
    rows = [(n, int(_df(f"SELECT COUNT(*) FROM {n}").iloc[0, 0])) for n in names]
    return pd.DataFrame(rows, columns=["table", "rows"])
