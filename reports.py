
import argparse
import csv

import db


def show(rows, headers):
    rows = [tuple(r) for r in rows]
    if not rows:
        print("(no rows)")
        return
    widths = [max(len(str(h)), *(len(str(r[i])) for r in rows)) for i, h in enumerate(headers)]
    line = "  ".join(str(h).ljust(w) for h, w in zip(headers, widths))
    print(line)
    print("-" * len(line))
    for r in rows:
        print("  ".join(str(v).ljust(w) for v, w in zip(r, widths)))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("summary"); p.add_argument("--course")
    p = sub.add_parser("defaulters"); p.add_argument("--threshold", type=float, default=75)
    p = sub.add_parser("session"); p.add_argument("id", type=int)
    sub.add_parser("sessions")
    sub.add_parser("spoofs")
    p = sub.add_parser("export"); p.add_argument("out")
    a = ap.parse_args()

    conn = db.init_db()
    if a.cmd == "summary":
        q = "SELECT roll_no, full_name, course_code, attended, total_sessions, attendance_pct FROM v_attendance_summary"
        params = ()
        if a.course:
            q += " WHERE course_code = ?"; params = (a.course,)
        show(conn.execute(q + " ORDER BY course_code, roll_no", params),
             ["Roll", "Name", "Course", "Attended", "Total", "%"])
    elif a.cmd == "defaulters":
        show(conn.execute(
            """SELECT roll_no, full_name, course_code, attended, total_sessions, attendance_pct
                 FROM v_attendance_summary
                WHERE total_sessions > 0 AND attendance_pct < ?
                ORDER BY attendance_pct""", (a.threshold,)),
            ["Roll", "Name", "Course", "Attended", "Total", "%"])
    elif a.cmd == "session":
        print("PRESENT / LATE")
        show(conn.execute(
            """SELECT s.roll_no, s.full_name, a.status, a.marked_at, ROUND(a.match_distance,3), a.liveness_challenge
                 FROM attendance a JOIN student s ON s.student_id = a.student_id
                WHERE a.session_id = ? ORDER BY a.marked_at""", (a.id,)),
            ["Roll", "Name", "Status", "Marked at", "Distance", "Challenge"])
        print("\nABSENT")
        show([(r["roll_no"], r["full_name"]) for r in db.absentees(conn, a.id)], ["Roll", "Name"])
    elif a.cmd == "sessions":
        show(conn.execute("SELECT session_id, course_code, session_date, start_time, status, enrolled, present, spoof_attempts "
                          "FROM v_session_report ORDER BY session_date DESC, start_time DESC"),
             ["ID", "Course", "Date", "Start", "Status", "Enrolled", "Present", "Spoofs"])
    elif a.cmd == "spoofs":
        show(conn.execute(
            """SELECT sp.detected_at, c.course_code, COALESCE(s.roll_no,'?'), sp.reason, sp.challenge
                 FROM spoof_attempt sp
                 JOIN class_session cs ON cs.session_id = sp.session_id
                 JOIN course c ON c.course_id = cs.course_id
                 LEFT JOIN student s ON s.student_id = sp.student_id
                ORDER BY sp.detected_at DESC"""),
             ["When", "Course", "Claimed roll", "Reason", "Challenge"])
    elif a.cmd == "export":
        rows = conn.execute("SELECT * FROM v_attendance_summary ORDER BY course_code, roll_no").fetchall()
        with open(a.out, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(rows[0].keys() if rows else [])
            w.writerows([tuple(r) for r in rows])
        print(f"Wrote {len(rows)} rows to {a.out}")


if __name__ == "__main__":
    main()
