-- Demo queries for viva / report.  Run:  sqlite3 attendance.db < queries.sql
.headers on
.mode column

-- 1. JOIN (4 tables): attendance with student, course and faculty
SELECT s.roll_no, s.full_name, c.course_code, f.full_name AS faculty, cs.session_date, a.status
FROM attendance a
JOIN student s        ON s.student_id = a.student_id
JOIN class_session cs ON cs.session_id = a.session_id
JOIN course c         ON c.course_id = cs.course_id
JOIN faculty f        ON f.faculty_id = c.faculty_id
ORDER BY cs.session_date DESC LIMIT 10;

-- 2. VIEW: attendance percentage
SELECT roll_no, course_code, attended, total_sessions, attendance_pct FROM v_attendance_summary;

-- 3. VIEW: defaulters (< 75%)
SELECT roll_no, full_name, course_code, attendance_pct FROM v_defaulters ORDER BY attendance_pct;

-- 4. GROUP BY + HAVING: courses whose average attendance is below 80%
SELECT course_code, ROUND(AVG(attendance_pct),1) AS avg_pct
FROM v_attendance_summary GROUP BY course_code HAVING AVG(attendance_pct) < 80;

-- 5. NOT EXISTS (correlated subquery): absentees of session 1
SELECT s.roll_no, s.full_name
FROM class_session cs
JOIN enrollment e ON e.course_id = cs.course_id
JOIN student s    ON s.student_id = e.student_id
WHERE cs.session_id = 1
  AND NOT EXISTS (SELECT 1 FROM attendance a WHERE a.session_id = cs.session_id AND a.student_id = s.student_id);

-- 6. LEFT JOIN: students with NO face samples registered yet
SELECT s.roll_no, s.full_name
FROM student s LEFT JOIN face_encoding f ON f.student_id = s.student_id
WHERE f.encoding_id IS NULL;

-- 7. WINDOW FUNCTION: rank students by attendance inside each course
SELECT course_code, roll_no, attendance_pct,
       RANK() OVER (PARTITION BY course_code ORDER BY attendance_pct DESC) AS rnk
FROM v_attendance_summary;

-- 8. Late-arrival count per student
SELECT s.roll_no, COUNT(*) AS late_count
FROM attendance a JOIN student s ON s.student_id = a.student_id
WHERE a.status = 'Late' GROUP BY s.student_id ORDER BY late_count DESC;

-- 9. Security: spoof attempts by reason
SELECT reason, COUNT(*) AS attempts FROM spoof_attempt GROUP BY reason ORDER BY attempts DESC;

-- 10. Security: students whose face was used in 2+ spoof attempts
SELECT s.roll_no, s.full_name, COUNT(*) AS n
FROM spoof_attempt sp JOIN student s ON s.student_id = sp.student_id
GROUP BY s.student_id HAVING COUNT(*) >= 2;

-- 11. Daily attendance trend
SELECT cs.session_date, COUNT(a.attendance_id) AS marked
FROM class_session cs LEFT JOIN attendance a ON a.session_id = cs.session_id
GROUP BY cs.session_date ORDER BY cs.session_date;

-- 12. TRANSACTION demo
BEGIN;
UPDATE class_session SET status = 'Closed' WHERE status = 'Open';
ROLLBACK;
