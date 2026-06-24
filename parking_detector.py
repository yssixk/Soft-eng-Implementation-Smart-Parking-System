#!/usr/bin/env python3
"""
Parking Slot Occupancy Detector
--------------------------------
Uses DroidCam (phone as IP camera) + OpenCV to detect whether
parking slots are occupied or empty in real-time.

Two modes:
  1. CALIBRATE — Draw rectangles over parking slots on the camera feed,
                  assign slot IDs (C1, M1, etc.), and capture a reference
                  image of the empty lot.
  2. DETECT    — Continuously compare the live feed against the reference
                  to determine which slots are occupied, and optionally
                  update the parking system database.
"""

import cv2
import numpy as np
import json
import os
import sqlite3
import sys
from datetime import datetime

from config import (
    DEFAULT_DROIDCAM_URL,
    DIFF_THRESHOLD,
    OCCUPIED_PERCENT,
    UPDATE_INTERVAL_SEC,
    DB_PATH,
    SLOTS_CONFIG,
    REFERENCE_IMAGE,
)


# ---------------------------------------------------------------------------
# DETECTOR
# ---------------------------------------------------------------------------
class ParkingDetector:
    def __init__(self, source):
        self.source = source
        self.slots: list[dict] = []
        self.reference = None
        self.cap = None

        self._load_config()
        if os.path.exists(REFERENCE_IMAGE):
            self.reference = cv2.imread(REFERENCE_IMAGE)
            print(f"[OK] Loaded reference image from {REFERENCE_IMAGE}")

    # --- persistence ------------------------------------------------------
    def _load_config(self):
        if os.path.exists(SLOTS_CONFIG):
            with open(SLOTS_CONFIG, "r") as f:
                self.slots = json.load(f)
            print(f"[OK] Loaded {len(self.slots)} slot(s) from {SLOTS_CONFIG}")

    def _save_config(self):
        with open(SLOTS_CONFIG, "w") as f:
            json.dump(self.slots, f, indent=2)
        print(f"[OK] Saved {len(self.slots)} slot(s) to {SLOTS_CONFIG}")

    # --- camera -----------------------------------------------------------
    def _connect(self):
        print(f"[..] Connecting to {self.source} ...")
        self.cap = cv2.VideoCapture(self.source)
        if not self.cap.isOpened():
            print(f"[ERROR] Cannot open camera at: {self.source}")
            print("        Make sure DroidCam is running and the URL is correct.")
            return False
        print("[OK] Camera connected!")
        return True

    def _release(self):
        if self.cap:
            self.cap.release()
        cv2.destroyAllWindows()

    # ===================================================================== #
    #  CALIBRATION MODE                                                      #
    # ===================================================================== #
    def calibrate(self, prefix=None):
        if not self._connect():
            return

        # Ask for slot ID prefix (skip if pre-supplied, e.g. from GUI)
        print("\n=== CALIBRATION MODE ===")
        if prefix is None:
            print("Slot ID prefix examples: C (for car), M (for motorcycle)")
            prefix = input("Enter slot ID prefix [C]: ").strip().upper() or "C"
        else:
            prefix = prefix.strip().upper() or "C"

        # Find the next number for this prefix
        existing_nums = [
            int(s["id"][len(prefix):])
            for s in self.slots
            if s["id"].startswith(prefix) and s["id"][len(prefix):].isdigit()
        ]
        next_num = max(existing_nums, default=0) + 1

        print(f"\nSlots will be named {prefix}{next_num}, {prefix}{next_num+1}, ...")
        print()
        print("Controls:")
        print("  CLICK + DRAG  →  Draw a slot rectangle")
        print("  S             →  Save slot configuration")
        print("  R             →  Capture reference image (empty lot)")
        print("  U             →  Undo last slot")
        print("  C             →  Clear ALL slots")
        print("  Q / ESC       →  Quit calibration")
        print()

        # Mouse callback state
        drawing = [False]
        start_pt = [None]
        temp_rect = [None]

        def on_mouse(event, x, y, flags, _):
            nonlocal next_num
            if event == cv2.EVENT_LBUTTONDOWN:
                drawing[0] = True
                start_pt[0] = (x, y)
                temp_rect[0] = None
            elif event == cv2.EVENT_MOUSEMOVE and drawing[0]:
                temp_rect[0] = (start_pt[0], (x, y))
            elif event == cv2.EVENT_LBUTTONUP and drawing[0]:
                drawing[0] = False
                if start_pt[0]:
                    ex, ey = x, y
                    x1 = min(start_pt[0][0], ex)
                    y1 = min(start_pt[0][1], ey)
                    x2 = max(start_pt[0][0], ex)
                    y2 = max(start_pt[0][1], ey)
                    # ignore tiny accidental clicks
                    if (x2 - x1) > 15 and (y2 - y1) > 15:
                        slot_id = f"{prefix}{next_num}"
                        self.slots.append(
                            {"id": slot_id, "x1": x1, "y1": y1, "x2": x2, "y2": y2}
                        )
                        next_num += 1
                        print(f"  + Added {slot_id}  ({x1},{y1})→({x2},{y2})")
                temp_rect[0] = None

        win = "Calibrate Parking Slots"
        cv2.namedWindow(win, cv2.WINDOW_NORMAL)
        cv2.setMouseCallback(win, on_mouse)

        while True:
            ret, frame = self.cap.read()
            if not ret:
                continue

            display = frame.copy()

            # Draw saved slots
            for s in self.slots:
                color = (0, 255, 0) if s["id"].startswith(prefix) else (255, 200, 0)
                cv2.rectangle(display, (s["x1"], s["y1"]), (s["x2"], s["y2"]), color, 2)
                # Label background
                (tw, th), _ = cv2.getTextSize(s["id"], cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                cv2.rectangle(display, (s["x1"], s["y1"] - th - 6),
                              (s["x1"] + tw + 4, s["y1"]), color, -1)
                cv2.putText(display, s["id"], (s["x1"] + 2, s["y1"] - 4),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

            # Draw in-progress rectangle
            if temp_rect[0]:
                cv2.rectangle(display, temp_rect[0][0], temp_rect[0][1],
                              (0, 255, 255), 2)

            # HUD
            hud = (
                f"Slots: {len(self.slots)} | "
                f"Prefix: {prefix} | "
                f"S=Save  R=Reference  U=Undo  C=Clear  Q=Quit"
            )
            cv2.putText(display, hud, (10, 28),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3)
            cv2.putText(display, hud, (10, 28),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)

            cv2.imshow(win, display)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):  # q or ESC
                break
            elif key == ord("s"):
                self._save_config()
            elif key == ord("r"):
                self.reference = frame.copy()
                cv2.imwrite(REFERENCE_IMAGE, frame)
                print(f"  [REF] Reference image saved → {REFERENCE_IMAGE}")
            elif key == ord("u"):
                if self.slots:
                    removed = self.slots.pop()
                    next_num -= 1
                    print(f"  - Removed {removed['id']}")
                else:
                    print("  (nothing to undo)")
            elif key == ord("c"):
                self.slots.clear()
                next_num = 1
                print("  [CLEAR] All slots removed")

        self._release()

    # ===================================================================== #
    #  DETECTION MODE                                                        #
    # ===================================================================== #
    def detect(self):
        """Run continuous occupancy detection and show live results."""
        if not self.slots:
            print("[ERROR] No slots configured. Run calibration first (mode 1).")
            return
        if self.reference is None:
            print("[ERROR] No reference image. Capture one during calibration (press R).")
            return
        if not self._connect():
            return

        print("\n=== DETECTION MODE ===")
        print(f"Monitoring {len(self.slots)} slot(s)...")
        print()
        print("Controls:")
        print("  R        →  Recapture reference from current frame")
        print("  +/-      →  Adjust sensitivity (occupied threshold)")
        print("  D        →  Toggle database updates")
        print("  Q / ESC  →  Quit")
        print()

        ref_gray = cv2.cvtColor(self.reference, cv2.COLOR_BGR2GRAY)
        ref_gray = cv2.GaussianBlur(ref_gray, (21, 21), 0)

        occupied_pct = OCCUPIED_PERCENT
        db_enabled = True
        last_db_update = 0

        while True:
            ret, frame = self.cap.read()
            if not ret:
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (21, 21), 0)

            display = frame.copy()
            statuses: dict[str, bool] = {}

            for slot in self.slots:
                x1, y1, x2, y2 = slot["x1"], slot["y1"], slot["x2"], slot["y2"]

                # Bounds check
                h, w = gray.shape[:2]
                x1c, y1c = max(0, x1), max(0, y1)
                x2c, y2c = min(w, x2), min(h, y2)
                if x2c <= x1c or y2c <= y1c:
                    continue

                roi_ref = ref_gray[y1c:y2c, x1c:x2c]
                roi_cur = gray[y1c:y2c, x1c:x2c]

                if roi_ref.shape != roi_cur.shape:
                    continue

                # --- difference analysis ---
                diff = cv2.absdiff(roi_ref, roi_cur)
                _, thresh = cv2.threshold(diff, DIFF_THRESHOLD, 255, cv2.THRESH_BINARY)
                total_px = thresh.shape[0] * thresh.shape[1]
                changed_px = cv2.countNonZero(thresh)
                change_pct = (changed_px / total_px) * 100 if total_px > 0 else 0

                is_occupied = change_pct > occupied_pct
                statuses[slot["id"]] = is_occupied

                # --- draw overlay ---
                color = (0, 0, 255) if is_occupied else (0, 200, 0)
                label = "OCCUPIED" if is_occupied else "FREE"
                alpha = 0.3

                # Semi-transparent fill
                overlay = display.copy()
                cv2.rectangle(overlay, (x1c, y1c), (x2c, y2c), color, -1)
                cv2.addWeighted(overlay, alpha, display, 1 - alpha, 0, display)

                # Border
                cv2.rectangle(display, (x1c, y1c), (x2c, y2c), color, 2)

                # Slot ID label
                cv2.putText(display, f"{slot['id']}: {label}",
                            (x1c, y1c - 8), cv2.FONT_HERSHEY_SIMPLEX,
                            0.5, color, 2)

                # Change percentage
                cv2.putText(display, f"{change_pct:.0f}%",
                            (x1c + 4, y2c - 8), cv2.FONT_HERSHEY_SIMPLEX,
                            0.4, (255, 255, 255), 1)

            # --- HUD ---
            free_count = sum(1 for v in statuses.values() if not v)
            occ_count = sum(1 for v in statuses.values() if v)
            db_status = "ON" if db_enabled else "OFF"
            hud = (
                f"FREE: {free_count}  OCCUPIED: {occ_count}  |  "
                f"Threshold: {occupied_pct}%  |  DB: {db_status}  |  "
                f"Q=Quit  R=NewRef  +/-=Sensitivity  D=ToggleDB"
            )
            # Black bar at top
            cv2.rectangle(display, (0, 0), (display.shape[1], 38), (0, 0, 0), -1)
            cv2.putText(display, hud, (10, 26),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 1)

            cv2.imshow("Parking Occupancy Detection", display)

            # --- update DB periodically ---
            now = cv2.getTickCount() / cv2.getTickFrequency()
            if db_enabled and (now - last_db_update) >= UPDATE_INTERVAL_SEC:
                self._update_db(statuses)
                last_db_update = now

            # --- key handling ---
            key = cv2.waitKey(50) & 0xFF
            if key in (ord("q"), 27):
                break
            elif key == ord("r"):
                self.reference = frame.copy()
                ref_gray = cv2.cvtColor(self.reference, cv2.COLOR_BGR2GRAY)
                ref_gray = cv2.GaussianBlur(ref_gray, (21, 21), 0)
                cv2.imwrite(REFERENCE_IMAGE, frame)
                print("  [REF] Reference image updated")
            elif key == ord("+") or key == ord("="):
                occupied_pct = min(80, occupied_pct + 2)
                print(f"  Threshold → {occupied_pct}%")
            elif key == ord("-") or key == ord("_"):
                occupied_pct = max(2, occupied_pct - 2)
                print(f"  Threshold → {occupied_pct}%")
            elif key == ord("d"):
                db_enabled = not db_enabled
                print(f"  Database updates: {'ON' if db_enabled else 'OFF'}")

        self._release()

    # --- database ---------------------------------------------------------
    def _update_db(self, statuses: dict[str, bool]):
        """Push occupancy status into parking.db."""
        if not os.path.exists(DB_PATH):
            return
        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            for slot_id, occupied in statuses.items():
                cur.execute(
                    "UPDATE slots SET occupied = ? WHERE slot_id = ?",
                    (1 if occupied else 0, slot_id),
                )
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"  [DB ERROR] {e}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    print("=" * 55)
    print("   PARKING SLOT OCCUPANCY DETECTOR")
    print("   DroidCam + OpenCV")
    print("=" * 55)

    # --- camera source ---
    print(f"\nDroidCam URL (default: {DEFAULT_DROIDCAM_URL})")
    print("  Or enter a number (0, 1, ...) for a built-in webcam")
    raw = input("Camera source: ").strip()

    if not raw:
        source = DEFAULT_DROIDCAM_URL
    elif raw.isdigit():
        source = int(raw)
    else:
        source = raw

    detector = ParkingDetector(source)

    # --- mode ---
    print()
    print("  1  →  Calibrate  (define parking slot regions)")
    print("  2  →  Detect     (monitor occupancy live)")
    print("  3  →  Both       (calibrate, then detect)")
    choice = input("\nMode [1/2/3]: ").strip()

    if choice == "1":
        detector.calibrate()
    elif choice == "2":
        detector.detect()
    elif choice == "3":
        detector.calibrate()
        print("\n--- Calibration done. Starting detection... ---\n")
        # Reload in case user saved new config
        detector._load_config()
        detector.detect()
    else:
        print("Invalid choice. Exiting.")


if __name__ == "__main__":
    main()
