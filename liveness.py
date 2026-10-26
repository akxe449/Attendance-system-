"""
Anti-spoofing (liveness detection).

Layered defence against photo / phone-screen / video-replay attacks:

 1. Random active challenge  - blink twice, OR turn head left, OR turn head right.
    The challenge is picked at random AFTER the face is recognised, so an attacker
    cannot pre-record a matching video.
 2. Identity lock            - the recognised identity must stay the same for the
    whole challenge (stops "show photo, then swap in a real person").
 3. Texture check            - blur / flatness score of the face crop (supplementary).
"""
import random
import time

import numpy as np

EAR_THRESHOLD = 0.21        # eye aspect ratio below this => eye closed
EAR_CONSEC_FRAMES = 2       # frames the eye must stay closed to count as a blink
YAW_LEFT = 0.38             # nose position ratio thresholds for head turns
YAW_RIGHT = 0.62
YAW_CENTER = (0.42, 0.58)   # must be seen before a turn is accepted
TEXTURE_MIN = 20.0          # Laplacian variance on 128x128 face crop (tune per camera)
CHALLENGE_TIMEOUT = 12.0     # seconds
REQUIRED_BLINKS = 2


def eye_aspect_ratio(eye):
    """Soukupova & Cech (2016). `eye` = 6 (x, y) points in dlib order."""
    p = np.asarray(eye, dtype=float)
    a = np.linalg.norm(p[1] - p[5])
    b = np.linalg.norm(p[2] - p[4])
    c = np.linalg.norm(p[0] - p[3])
    return (a + b) / (2.0 * c)


def yaw_ratio(landmarks):
    """0.5 = looking straight; <0.5 nose towards image-left; >0.5 towards image-right.
    Frames are mirrored before processing, so this matches what the user sees."""
    chin = landmarks["chin"]
    left, right = chin[0][0], chin[16][0]
    nose_tip = landmarks["nose_bridge"][-1][0]
    width = max(right - left, 1)
    return (nose_tip - left) / width


def texture_score(bgr_face):
    """Variance of Laplacian on a fixed-size grayscale crop (higher = sharper)."""
    import cv2
    gray = cv2.cvtColor(cv2.resize(bgr_face, (128, 128)), cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


class LivenessChallenge:
    KINDS = ("blink", "turn_left", "turn_right")

    def __init__(self, kind=None, timeout=CHALLENGE_TIMEOUT, rng=random):
        self.kind = kind or rng.choice(self.KINDS)
        self.timeout = timeout
        self.started = time.time()
        self.blinks = 0
        self._closed_frames = 0
        self._seen_center = False
        self.passed = False

    @property
    def prompt(self):
        return {
            "blink": f"Blink {REQUIRED_BLINKS} times",
            "turn_left": "Turn your head LEFT",
            "turn_right": "Turn your head RIGHT",
        }[self.kind]



    @property
    def expired(self):
        return (
                not self.passed
                and time.time() - self.started >= self.timeout
        )


    @property
    def time_left(self):
        return max(0.0, self.timeout - (time.time() - self.started))

    def update(self, landmarks):
        """Feed one frame's landmarks (face_recognition format)."""
        if self.passed:
            return
        if self.kind == "blink":
            ear = (eye_aspect_ratio(landmarks["left_eye"]) +
                   eye_aspect_ratio(landmarks["right_eye"])) / 2.0
            if ear < EAR_THRESHOLD:
                self._closed_frames += 1
            else:
                if self._closed_frames >= EAR_CONSEC_FRAMES:
                    self.blinks += 1
                self._closed_frames = 0
            if self.blinks >= REQUIRED_BLINKS:
                self.passed = True
        else:
            y = yaw_ratio(landmarks)
            if YAW_CENTER[0] <= y <= YAW_CENTER[1]:
                self._seen_center = True
            if self._seen_center:
                if self.kind == "turn_left" and y <= YAW_LEFT:
                    self.passed = True
                elif self.kind == "turn_right" and y >= YAW_RIGHT:
                    self.passed = True
