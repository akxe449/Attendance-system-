
"""Run: python -m unittest -v (no camera or face_recognition needed)"""
import os
import sqlite3
import tempfile
import unittest

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["ATTENDANCE_DB"] = _tmp.name
_tmp.close()

import numpy as np  # noqa: E402
import db  # noqa: E402
import liveness  # noqa: E402


def eye(open_=True):
    h = 6 if open_ else 1
    return [
        (0, 5),
        (3, 5 - h / 2),
        (7, 5 - h / 2),
        (10, 5),
        (7, 5 + h / 2),
        (3, 5 + h / 2),
    ]


def lm(open_=True, nose_x=50):
    return {
        "left_eye": eye(open_),
        "right_eye": eye(open_),
        "chin": [(0, 0)] + [(50, 100)] * 15 + [(100, 0)],
        "nose_bridge": [
            (50, 0),
            (50, 10),
            (50, 20),
            (nose_x, 30),
        ],
    }


class DatabaseRules(unittest.TestCase):

    def setUp(self):
        self.conn = db.init_db(reset=True)
        c = self.conn

        c.execute("INSERT INTO department(dept_name) VALUES ('CS')")
        c.execute(
            "INSERT INTO faculty(full_name,email,dept_id) "
            "VALUES ('F','f@x',1)"
        )
        c.execute(
            "INSERT INTO course(course_code,title,semester,dept_id,faculty_id) "
            "VALUES ('C1','T',5,1,1)"
        )

        for i in (1, 2):
            c.execute(
                "INSERT INTO student(roll_no,full_name,dept_id,semester) "
                "VALUES (?,?,1,5)",
                (f"R{i}", f"S{i}"),
            )

        # Student 2 is intentionally not enrolled.
        c.execute(
            "INSERT INTO enrollment(student_id,course_id) VALUES (1,1)"
        )
        c.execute(
            "INSERT INTO class_session"
            "(course_id,session_date,start_time,end_time,status) "
            "VALUES (1,'2025-01-10','09:00','10:00','Open')"
        )
        c.commit()

    def tearDown(self):
        if getattr(self, "conn", None) is not None:
            self.conn.close()
            self.conn = None

    def test_mark_and_duplicate(self):
        self.assertTrue(
            db.mark_attendance(self.conn, 1, 1, 0.3, "blink")
        )
        self.assertFalse(
            db.mark_attendance(self.conn, 1, 1, 0.3, "blink")
        )

        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO attendance(session_id,student_id) VALUES (1,1)"
            )

    def test_not_enrolled_blocked(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO attendance(session_id,student_id) VALUES (1,2)"
            )

    def test_closed_session_blocked(self):
        db.set_session_status(self.conn, 1, "Closed")

        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO attendance(session_id,student_id) VALUES (1,1)"
            )

    def test_late_trigger(self):
        self.conn.execute(
            "INSERT INTO attendance(session_id,student_id,marked_at) "
            "VALUES (1,1,'2025-01-10 09:25:00')"
        )
        status = self.conn.execute(
            "SELECT status FROM attendance"
        ).fetchone()[0]
        self.assertEqual(status, "Late")

    def test_on_time(self):
        self.conn.execute(
            "INSERT INTO attendance(session_id,student_id,marked_at) "
            "VALUES (1,1,'2025-01-10 09:05:00')"
        )
        status = self.conn.execute(
            "SELECT status FROM attendance"
        ).fetchone()[0]
        self.assertEqual(status, "Present")

    def test_views_and_absentees(self):
        self.conn.execute(
            "INSERT INTO attendance(session_id,student_id,marked_at) "
            "VALUES (1,1,'2025-01-10 09:01:00')"
        )

        row = self.conn.execute(
            "SELECT * FROM v_attendance_summary WHERE student_id=1"
        ).fetchone()

        self.assertEqual(
            (
                row["total_sessions"],
                row["attended"],
                row["attendance_pct"],
            ),
            (1, 1, 100.0),
        )

        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM v_defaulters"
            ).fetchone()[0],
            0,
        )

        db.set_session_status(self.conn, 1, "Closed")

        self.conn.execute(
            "INSERT INTO class_session"
            "(course_id,session_date,start_time,end_time,status) "
            "VALUES (1,'2025-01-11','09:00','10:00','Closed')"
        )

        percentage = self.conn.execute(
            "SELECT attendance_pct FROM v_defaulters"
        ).fetchone()[0]

        self.assertEqual(percentage, 50.0)

    def test_encoding_roundtrip_and_cascade(self):
        vector = np.random.rand(128)
        db.save_encoding(self.conn, 1, vector)

        ids, matrix = db.load_all_encodings(self.conn)

        self.assertEqual(ids, [1])
        self.assertTrue(np.allclose(matrix[0], vector))

        self.conn.execute("DELETE FROM student WHERE student_id=1")

        count = self.conn.execute(
            "SELECT COUNT(*) FROM face_encoding"
        ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_spoof_log(self):
        db.log_spoof(
            self.conn, 1, 1, "CHALLENGE_TIMEOUT", "blink"
        )

        with self.assertRaises(sqlite3.IntegrityError):
            db.log_spoof(self.conn, 1, 1, "NOT_A_REASON")


class Liveness(unittest.TestCase):

    def test_ear(self):
        self.assertGreater(
            liveness.eye_aspect_ratio(eye(True)),
            liveness.EAR_THRESHOLD,
        )
        self.assertLess(
            liveness.eye_aspect_ratio(eye(False)),
            liveness.EAR_THRESHOLD,
        )

    def test_blink_challenge_passes(self):
        challenge = liveness.LivenessChallenge("blink")

        for _ in range(2):
            challenge.update(lm(True))
            challenge.update(lm(False))
            challenge.update(lm(False))
            challenge.update(lm(True))

        self.assertTrue(challenge.passed)

    def test_open_eyes_photo_fails(self):
        challenge = liveness.LivenessChallenge("blink")

        for _ in range(100):
            challenge.update(lm(True))

        self.assertFalse(challenge.passed)

    def test_turn_requires_center_then_turn(self):
        challenge = liveness.LivenessChallenge("turn_right")

        challenge.update(lm(nose_x=70))
        self.assertFalse(challenge.passed)

        challenge.update(lm(nose_x=50))
        challenge.update(lm(nose_x=70))

        self.assertTrue(challenge.passed)

    def test_wrong_direction_fails(self):
        challenge = liveness.LivenessChallenge("turn_left")

        challenge.update(lm(nose_x=50))
        challenge.update(lm(nose_x=70))

        self.assertFalse(challenge.passed)

    def test_timeout(self):
        challenge = liveness.LivenessChallenge("blink", timeout=0.0)
        self.assertTrue(challenge.expired)


if __name__ == "__main__":
    unittest.main()
