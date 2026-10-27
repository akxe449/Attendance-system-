
import random
from datetime import date, timedelta

import db

DEPTS = ["Computer Science", "Information Technology"]
FACULTY = [("Dr. Meera Sharma", "meera@college.edu", 1),
           ("Prof. Rakesh Verma", "rakesh@college.edu", 1),
           ("Dr. Anita Joshi", "anita@college.edu", 2)]
COURSES = [("CS301", "Database Management Systems", 5, 1, 1, "09:00"),
           ("CS302", "Operating Systems", 5, 1, 2, "10:00"),
           ("IT304", "Computer Networks", 5, 2, 3, "11:00")]
STUDENTS = [  # roll, name, dept_id, attendance probability (to create some defaulters)
    ("21CS001", "Aarav Sharma", 1, 0.95), ("21CS002", "Diya Patel", 1, 0.90),
    ("21CS003", "Rohan Gupta", 1, 0.60), ("21CS004", "Ananya Singh", 1, 0.85),
    ("21CS005", "Kabir Mehta", 1, 0.50), ("21IT001", "Ishita Rao", 2, 0.92),
    ("21IT002", "Vihaan Kumar", 2, 0.70), ("21IT003", "Saanvi Nair", 2, 0.88),
]


def main():
    rnd = random.Random(42)
    conn = db.init_db(reset=True)

    for d in DEPTS:
        conn.execute("INSERT INTO department(dept_name) VALUES (?)", (d,))
    for n, e, d in FACULTY:
        conn.execute("INSERT INTO faculty(full_name, email, dept_id) VALUES (?,?,?)", (n, e, d))
    for code, title, sem, dept, fac, _ in COURSES:
        conn.execute("INSERT INTO course(course_code, title, semester, dept_id, faculty_id) VALUES (?,?,?,?,?)",
                     (code, title, sem, dept, fac))
    prob = {}
    for roll, name, dept, p in STUDENTS:
        cur = conn.execute("INSERT INTO student(roll_no, full_name, email, dept_id, semester) VALUES (?,?,?,?,5)",
                           (roll, name, f"{roll.lower()}@college.edu", dept))
        prob[cur.lastrowid] = p
        codes = ["CS301", "CS302"] if dept == 1 else ["CS301", "IT304"]
        for c in codes:
            db.enroll(conn, cur.lastrowid, c)
    conn.commit()

    # 8 past sessions per course with synthetic attendance
    today = date.today()
    for code, _, _, _, _, start in COURSES:
        cid = conn.execute("SELECT course_id FROM course WHERE course_code=?", (code,)).fetchone()[0]
        enrolled = [r[0] for r in conn.execute("SELECT student_id FROM enrollment WHERE course_id=?", (cid,))]
        for k in range(8, 0, -1):
            day = (today - timedelta(days=k)).isoformat()
            hh = int(start[:2])
            sess = conn.execute(
                "INSERT INTO class_session(course_id, session_date, start_time, end_time, status) VALUES (?,?,?,?, 'Open')",
                (cid, day, start, f"{hh + 1:02d}:00")).lastrowid
            for s in enrolled:
                if rnd.random() < prob[s]:
                    minute = rnd.choice([0, 1, 2, 3, 5, 8, 12, 15])   # >10 => trigger marks Late
                    conn.execute(
                        "INSERT INTO attendance(session_id, student_id, marked_at, match_distance, liveness_challenge) "
                        "VALUES (?,?,?,?,?)",
                        (sess, s, f"{day} {start[:2]}:{minute:02d}:30", round(rnd.uniform(0.25, 0.45), 3),
                         rnd.choice(["blink", "turn_left", "turn_right"])))
            conn.execute("UPDATE class_session SET status='Closed' WHERE session_id=?", (sess,))
            if rnd.random() < 0.25:
                conn.execute("INSERT INTO spoof_attempt(session_id, student_id, reason, challenge, detected_at) VALUES (?,?,?,?,?)",
                             (sess, rnd.choice(enrolled), rnd.choice(["CHALLENGE_TIMEOUT", "IDENTITY_SWITCH", "LOW_TEXTURE"]),
                              "blink", f"{day} {start[:2]}:05:00"))
    conn.commit()
    print("Seeded demo data. Try:  python reports.py summary   |   python reports.py defaulters")


if __name__ == "__main__":
    main()
