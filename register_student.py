"""
Enrol a student: stores profile + several face encodings in the database.

Webcam :  python register_student.py --roll 21CS001 --name "Aarav Sharma" --dept "Computer Science" --semester 5 --courses CS301,CS302
Photos :  python register_student.py --roll 21CS001 --name "Aarav Sharma" --dept "Computer Science" --semester 5 --images ./photos/aarav
"""
import argparse
import sys
from pathlib import Path

import cv2
import face_recognition
import numpy as np

import db

DUPLICATE_DISTANCE = 0.40   # a new face this close to ANOTHER student's face = suspicious


def encodings_from_images(folder):
    out = []
    for p in sorted(Path(folder).glob("*")):
        if p.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            continue
        img = face_recognition.load_image_file(str(p))
        locs = face_recognition.face_locations(img)
        if len(locs) != 1:
            print(f"  skip {p.name}: found {len(locs)} faces (need exactly 1)")
            continue
        out.append(face_recognition.face_encodings(img, locs)[0])
    return out


def encodings_from_webcam(samples, camera):
    cap = cv2.VideoCapture(camera)
    if not cap.isOpened():
        sys.exit("Cannot open webcam")
    out = []
    print(f"Press SPACE to capture a sample ({samples} needed), Q to abort.")
    while len(out) < samples:
        ok, frame = cap.read()
        if not ok:
            break
        frame = cv2.flip(frame, 1)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        locs = face_recognition.face_locations(rgb, model="hog")
        for (t, r, b, l) in locs:
            cv2.rectangle(frame, (l, t), (r, b), (0, 200, 0) if len(locs) == 1 else (0, 0, 255), 2)
        cv2.putText(frame, f"Samples {len(out)}/{samples}  [SPACE] capture  [Q] quit", (10, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.imshow("Register", frame)
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if key == 32:
            if len(locs) != 1:
                print("  need exactly one face in frame")
                continue
            out.append(face_recognition.face_encodings(rgb, locs)[0])
            print(f"  captured {len(out)}/{samples}  (tip: vary your angle/expression slightly)")
    cap.release()
    cv2.destroyAllWindows()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--roll", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--dept", required=True)
    ap.add_argument("--semester", type=int, required=True)
    ap.add_argument("--email")
    ap.add_argument("--courses", default="", help="comma separated course codes, e.g. CS301,CS302")
    ap.add_argument("--samples", type=int, default=5)
    ap.add_argument("--images", help="folder of photos instead of webcam")
    ap.add_argument("--camera", type=int, default=0)
    args = ap.parse_args()

    conn = db.init_db()
    encs = encodings_from_images(args.images) if args.images else encodings_from_webcam(args.samples, args.camera)
    if not encs:
        sys.exit("No face samples captured - nothing saved.")

    # Integrity check: does this face already belong to a DIFFERENT student?
    ids, mat = db.load_all_encodings(conn)
    existing = db.get_student_by_roll(conn, args.roll)
    if len(mat):
        for e in encs:
            d = np.linalg.norm(mat - e, axis=1)
            i = int(np.argmin(d))
            if d[i] < DUPLICATE_DISTANCE and (not existing or ids[i] != existing["student_id"]):
                sys.exit(f"This face is already registered to student_id={ids[i]}. Aborting.")

    if existing:
        sid = existing["student_id"]
        print(f"Roll {args.roll} exists - adding {len(encs)} more face samples.")
    else:
        dept_id = db.get_or_create_department(conn, args.dept)
        sid = db.add_student(conn, args.roll, args.name, args.email, dept_id, args.semester)
    for e in encs:
        db.save_encoding(conn, sid, e)
    for code in filter(None, (c.strip() for c in args.courses.split(","))):
        db.enroll(conn, sid, code)
    print(f"Saved {len(encs)} samples for {args.name} (student_id={sid}).")


if __name__ == "__main__":
    main()
