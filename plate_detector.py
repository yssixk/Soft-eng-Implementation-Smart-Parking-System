#!/usr/bin/env python3
"""
License Plate Detector
-----------------------
Uses the local webcam + pytesseract to detect and read license plates
in real-time.

Pipeline:
  1. Capture frame from webcam
  2. Detect plate region using Haar cascade
  3. Read plate text using pytesseract
  4. Save plate image to foto_plat/ directory
  5. Record detection in parking.db via ParkingDB
"""

import cv2
import os
import re
import time
from datetime import datetime

from config import DB_PATH, PLATE_IMAGE_DIR
from database import ParkingDB


# ---------------------------------------------------------------------------
# PLATE DETECTOR
# ---------------------------------------------------------------------------
class PlateDetector:
    """Real-time license plate detector using Haar cascade + pytesseract."""

    def __init__(self, source=0):
        self.source = source
        self.cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_russian_plate_number.xml"
        )
        import pytesseract
        self.pytesseract = pytesseract
        self.cap = None
        self.db = ParkingDB()

    # --- camera -----------------------------------------------------------
    def _connect(self):
        """Connect to camera — same pattern as parking_detector.py."""
        print(f"[..] Connecting to {self.source} ...")
        if isinstance(self.source, int):
            self.cap = cv2.VideoCapture(self.source, cv2.CAP_DSHOW)
        else:
            self.cap = cv2.VideoCapture(self.source)
        if not self.cap.isOpened():
            print(f"[ERROR] Cannot open camera at: {self.source}")
            print("        Make sure the webcam is available and the source is correct.")
            return False
        try:
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        print("[OK] Camera connected!")
        return True

    def _release(self):
        """Release camera and destroy OpenCV windows."""
        if self.cap:
            self.cap.release()
        cv2.destroyAllWindows()

    # --- core detection ---------------------------------------------------
    def detect_from_frame(self, frame):
        """Detect plate from a single frame.

        Returns:
            tuple: (plate_text, plate_image, confidence) if a plate is found,
                   or (None, None, 0) if nothing is detected.
        """
        # 1. Convert to grayscale for cascade detection
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # 2. Detect plate regions using Haar cascade
        plates = self.cascade.detectMultiScale(
            gray,
            scaleFactor=1.05,
            minNeighbors=3,
            minSize=(30, 30),
        )

        best_text = None
        best_image = None
        best_confidence = 0

        # 3. Process each detected plate region
        for (x, y, w, h) in plates:
            cropped = frame[y : y + h, x : x + w]
            gray_crop = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
            gray_crop = cv2.resize(
                gray_crop,
                (
                    max(200, cropped.shape[1] * 2),
                    max(60, cropped.shape[0] * 2),
                ),
                interpolation=cv2.INTER_CUBIC,
            )
            _, thresh_plate = cv2.threshold(
                gray_crop, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
            )
            data = self.pytesseract.image_to_data(
                thresh_plate,
                output_type=self.pytesseract.Output.DICT,
                config="--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
            )

            words = [
                w.strip().upper()
                for w in data["text"]
                if isinstance(w, str) and w.strip()
            ]
            cleaned = re.sub(r"[^A-Z0-9 ]", "", " ".join(words)).strip()

            confs = []
            for c in data["conf"]:
                try:
                    ci = int(c)
                except Exception:
                    continue
                if ci >= 0:
                    confs.append(ci)
            confidence = sum(confs) / len(confs) / 100 if confs else 0.0

            if len(cleaned) >= 3 and confidence > best_confidence:
                best_text = cleaned
                best_image = cropped
                best_confidence = confidence

        if best_text:
            return best_text, best_image, best_confidence
        return None, None, 0

    # --- save detection ---------------------------------------------------
    def save_plate(self, text, img, confidence):
        """Save plate image to foto_plat/ and record to parking.db."""
        os.makedirs(PLATE_IMAGE_DIR, exist_ok=True)
        timestamp_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"{timestamp_str}_{text}.jpg"
        filepath = os.path.join(PLATE_IMAGE_DIR, filename)
        cv2.imwrite(filepath, img)
        self.db.save_plate_detection(text, confidence, filepath)
        print(
            f"[{timestamp_str}] Detected: {text} "
            f"(conf: {confidence:.0%}) | Saved: {filepath}"
        )

    # --- live detection loop ----------------------------------------------
    def run(self):
        """Live plate detection — press Q or ESC to quit."""
        if not self._connect():
            return

        print("\n=== PLATE DETECTION MODE ===")
        print("Controls:")
        print("  Q / ESC  →  Quit")
        print()

        last_saved_text = ""
        last_saved_time = 0

        reconnect_count = 0
        while True:
            ret, frame = self.cap.read()
            if not ret:
                reconnect_count += 1
                time.sleep(0.05)
                if reconnect_count >= 20:
                    print("[WARN] Frame read failed repeatedly, reconnecting camera...")
                    self.cap.release()
                    if isinstance(self.source, int):
                        self.cap = cv2.VideoCapture(self.source, cv2.CAP_DSHOW)
                    else:
                        self.cap = cv2.VideoCapture(self.source)
                    if self.cap.isOpened():
                        try:
                            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                        except Exception:
                            pass
                        reconnect_count = 0
                    continue
                continue
            reconnect_count = 0
            display = frame.copy()

            # Detect plates
            text, plate_img, confidence = self.detect_from_frame(frame)

            if text and len(text) >= 3:
                # Find plate regions again for drawing on the display frame
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                plates = self.cascade.detectMultiScale(
                    gray,
                    scaleFactor=1.05,
                    minNeighbors=3,
                    minSize=(30, 30),
                )
                for (x, y, w, h) in plates:
                    cv2.rectangle(display, (x, y), (x + w, y + h), (255, 0, 0), 2)
                    cv2.putText(
                        display,
                        text,
                        (x, y - 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.9,
                        (36, 255, 12),
                        2,
                    )

                # Cooldown: don't save the same plate within 5 seconds
                current_time = time.time()
                if text != last_saved_text or (current_time - last_saved_time > 5):
                    self.save_plate(text, plate_img, confidence)
                    last_saved_text = text
                    last_saved_time = current_time

            # --- HUD (black bar at top) ---
            cv2.rectangle(
                display, (0, 0), (display.shape[1], 38), (0, 0, 0), -1
            )
            hud = "PLATE DETECTOR | Q=Quit"
            if text:
                hud = f"Detected: {text} ({confidence:.0%}) | Q=Quit"
            cv2.putText(
                display, hud, (10, 26),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1,
            )

            cv2.imshow("Plate Detector", display)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):  # Q or ESC
                break

        self._release()
        self.db.close()


# ---------------------------------------------------------------------------
# CLI ENTRY POINT
# ---------------------------------------------------------------------------
def main():
    print("=" * 55)
    print("   LICENSE PLATE DETECTOR")
    print("   Webcam + pytesseract")
    print("=" * 55)

    print("\nWebcam source (default: 0)")
    print("  Or enter an IP camera URL if needed")
    raw = input("Camera source: ").strip()

    if not raw:
        source = 0
    elif raw.isdigit():
        source = int(raw)
    else:
        source = raw

    detector = PlateDetector(source)
    detector.run()


if __name__ == "__main__":
    main()
