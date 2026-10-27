
import argparse
import sys
import time

import cv2
import face_recognition
import numpy as np

import db
from liveness import LivenessChallenge, TEXTURE_MIN, texture_score

MATCH_TOLERANCE = 0.50   
SCALE = 0.5              
RECHECK_EVERY = 5        
COOLDOWN = 3.0           
GREEN, RED, YELLOW, WHITE = (0, 200, 0), (0, 0, 255), (0, 215, 255), (255, 255, 255)


def best_match(known, enc):
    d = np.linalg.norm(known - enc, axis=1)
    i = int(np.argmin(d))
    return i, float(d[i])


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--course", help="course code, e.g. CS301")
    g.add_argument("--session", type=int)
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--no-texture", action="store_true", help="disable texture check")
    args = ap.parse_args()

    conn = db.init_db()
    sid_session = args.session or db.get_or_create_today_session(conn, args.course)
    session = db.get_session(conn, sid_session)
    if not session:
        sys.exit("Session not found")
    db.set_session_status(conn, sid_session, "Open")

    ids, names, known = db.load_encodings_for_session(conn, sid_session)
    if len(known) == 0:
        sys.exit("No registered faces for students enrolled in this course.")
    marked = db.marked_student_ids(conn, sid_session)
    print(f"Session {sid_session}: {session['course_code']} - {session['title']}  "
          f"({len(set(ids))} enrolled students with faces)")

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        sys.exit("Cannot open webcam")

    state, challenge, locked, tex = "SCAN", None, None, []
    banner, banner_color, banner_until, frame_no = "", WHITE, 0.0, 0

    def reset(msg, color):
        nonlocal state, challenge, locked, tex, banner, banner_color, banner_until
        state, challenge, locked, tex = "SCAN", None, None, []
        banner, banner_color, banner_until = msg, color, time.time() + COOLDOWN

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frame = cv2.flip(frame, 1)          
            frame_no += 1
            small = cv2.resize(frame, (0, 0), fx=SCALE, fy=SCALE)
            rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
            locs = face_recognition.face_locations(rgb, model="hog")
            now = time.time()

            if locs:
                loc = max(locs, key=lambda l: (l[2] - l[0]) * (l[1] - l[3]))   
                t, r, b, l = [int(v / SCALE) for v in loc]
                box_color = WHITE

                if state == "SCAN" and now >= banner_until:
                    enc = face_recognition.face_encodings(rgb, [loc])[0]
                    i, dist = best_match(known, enc)
                    if dist <= MATCH_TOLERANCE:
                        s_id = ids[i]
                        if s_id in marked:
                            banner, banner_color, banner_until = f"{names[s_id]}: already marked", YELLOW, now + COOLDOWN
                        else:
                            locked, challenge, tex, state = s_id, LivenessChallenge(), [], "CHALLENGE"
                            locked_dist = dist
                    else:
                        box_color = RED

                elif state == "CHALLENGE":
                    box_color = YELLOW
                    lm = face_recognition.face_landmarks(rgb, [loc])
                    if lm:
                        challenge.update(lm[0])
                    face_crop = frame[max(t, 0):b, max(l, 0):r]
                    if face_crop.size:
                        tex.append(texture_score(face_crop))

                    # identity lock
                    if frame_no % RECHECK_EVERY == 0:
                        enc = face_recognition.face_encodings(rgb, [loc])[0]
                        i, dist = best_match(known, enc)
                        if dist > MATCH_TOLERANCE or ids[i] != locked:
                            db.log_spoof(conn, sid_session, locked, "IDENTITY_SWITCH", challenge.kind)
                            reset("Identity changed - rejected", RED)
                            continue

                    if challenge.passed:
                        avg_tex = float(np.mean(tex)) if tex else 0.0
                        if not args.no_texture and avg_tex < TEXTURE_MIN:
                            db.log_spoof(conn, sid_session, locked, "LOW_TEXTURE", challenge.kind)
                            reset(f"Flat/blurry face ({avg_tex:.0f}) - rejected", RED)
                        else:
                            db.mark_attendance(conn, sid_session, locked, locked_dist, challenge.kind)
                            marked.add(locked)
                            reset(f"{names[locked]}: PRESENT", GREEN)
                    elif challenge.expired:
                        db.log_spoof(conn, sid_session, locked, "CHALLENGE_TIMEOUT", challenge.kind)
                        reset("Liveness failed - logged", RED)

                cv2.rectangle(frame, (l, t), (r, b), box_color, 2)
            elif state == "CHALLENGE" and challenge.expired:
                db.log_spoof(conn, sid_session, locked, "CHALLENGE_TIMEOUT", challenge.kind)
                reset("Face lost - logged", RED)

            # ---- HUD ----
            if state == "CHALLENGE":
                cv2.putText(frame, f"{names[locked]}: {challenge.prompt}  ({challenge.time_left:.0f}s)",
                            (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.75, YELLOW, 2)
            elif now < banner_until:
                cv2.putText(frame, banner, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.75, banner_color, 2)
            else:
                cv2.putText(frame, "Look at the camera", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.75, WHITE, 2)
            cv2.putText(frame, f"Present: {len(marked)}/{len(set(ids))}   [Q] close session",
                        (10, frame.shape[0] - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.6, WHITE, 2)
            cv2.imshow("Attendance", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()
        db.set_session_status(conn, sid_session, "Closed")
        print("Session closed. Absent students:")
        for row in db.absentees(conn, sid_session):
            print(f"  {row['roll_no']}  {row['full_name']}")


if __name__ == "__main__":
    main()
