#!/usr/bin/env python3
"""
Smart Parking System — Database Layer
---------------------------------------
ParkingDB class, fee calculation, schema management.
All database logic lives here — GUI and detectors import this.
"""

import sqlite3
import math
import os
from datetime import datetime

from config import (
    DB_PATH, SCHEMA_VERSION, CAR_SLOTS, MOTOR_SLOTS,
    GRACE_PERIOD_MINUTES,
    CAR_RATE_FIRST_HOUR, CAR_RATE_ADDITIONAL,
    MOTOR_RATE_FIRST_HOUR, MOTOR_RATE_ADDITIONAL,
    PLATE_IMAGE_DIR,
)


# ---------------------------------------------------------------------------
# FEE CALCULATION
# ---------------------------------------------------------------------------
def calculate_fee(vehicle_type, entry_time, exit_time):
    """Calculate parking fee based on vehicle type and duration.

    Rules:
    - First 15 minutes: FREE
    - Car: Rp 5.000 per hour (flat), billed in whole hours (rounded up)
    - Motorcycle: Rp 2.000 for the first hour, Rp 3.000 each additional hour
    """
    total_seconds = (exit_time - entry_time).total_seconds()
    minutes = total_seconds / 60

    if minutes <= GRACE_PERIOD_MINUTES:
        return 0

    hours = math.ceil(minutes / 60)  # round up to whole hours, min 1

    if vehicle_type == "car":
        return hours * CAR_RATE_FIRST_HOUR
    else:  # motor
        if hours <= 1:
            return MOTOR_RATE_FIRST_HOUR
        else:
            return MOTOR_RATE_FIRST_HOUR + (hours - 1) * MOTOR_RATE_ADDITIONAL


# ---------------------------------------------------------------------------
# DATABASE LAYER
# ---------------------------------------------------------------------------
class ParkingDB:
    """SQLite database with schema for two-zone parking, student IDs,
    e-money card tracking, and plate detections."""

    def __init__(self, path=DB_PATH):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self._init_schema()

    # --- schema -----------------------------------------------------------
    def _init_schema(self):
        cur = self.conn.cursor()

        # Schema versioning
        cur.execute(
            "CREATE TABLE IF NOT EXISTS schema_info (version INTEGER)"
        )
        cur.execute("SELECT version FROM schema_info")
        row = cur.fetchone()

        if row is None or row[0] != SCHEMA_VERSION:
            # Wipe old tables and start fresh
            for tbl in ("sessions", "slots", "students",
                        "plate_detections", "schema_info"):
                cur.execute(f"DROP TABLE IF EXISTS {tbl}")

            cur.execute("CREATE TABLE schema_info (version INTEGER)")
            cur.execute(
                "INSERT INTO schema_info (version) VALUES (?)",
                (SCHEMA_VERSION,),
            )

            cur.execute("""
                CREATE TABLE slots (
                    slot_id   TEXT PRIMARY KEY,
                    vehicle_type TEXT NOT NULL,
                    occupied  INTEGER NOT NULL DEFAULT 0
                )
            """)

            cur.execute("""
                CREATE TABLE sessions (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    slot_id     TEXT    NOT NULL,
                    plate       TEXT    NOT NULL,
                    vehicle_type TEXT   NOT NULL,
                    card_id     TEXT    NOT NULL,
                    is_student  INTEGER NOT NULL DEFAULT 0,
                    entry_time  TEXT    NOT NULL,
                    exit_time   TEXT,
                    fee         REAL
                )
            """)

            cur.execute("""
                CREATE TABLE students (
                    student_id    TEXT PRIMARY KEY,
                    name          TEXT NOT NULL,
                    registered_at TEXT NOT NULL
                )
            """)

            cur.execute("""
                CREATE TABLE plate_detections (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    plate_text  TEXT    NOT NULL,
                    confidence  REAL,
                    image_path  TEXT,
                    detected_at TEXT    NOT NULL,
                    used        INTEGER NOT NULL DEFAULT 0
                )
            """)

            # Seed car slots C1–C60
            for i in range(1, CAR_SLOTS + 1):
                cur.execute(
                    "INSERT INTO slots (slot_id, vehicle_type) VALUES (?, 'car')",
                    (f"C{i}",),
                )
            # Seed motor slots M1–M100
            for i in range(1, MOTOR_SLOTS + 1):
                cur.execute(
                    "INSERT INTO slots (slot_id, vehicle_type) VALUES (?, 'motor')",
                    (f"M{i}",),
                )
            self.conn.commit()

    # --- slot queries -----------------------------------------------------
    def get_slots(self, vehicle_type=None):
        cur = self.conn.cursor()
        if vehicle_type:
            cur.execute(
                "SELECT slot_id, occupied FROM slots "
                "WHERE vehicle_type = ? ORDER BY LENGTH(slot_id), slot_id",
                (vehicle_type,),
            )
        else:
            cur.execute(
                "SELECT slot_id, occupied FROM slots "
                "ORDER BY LENGTH(slot_id), slot_id"
            )
        return cur.fetchall()

    def free_slot_count(self, vehicle_type=None):
        cur = self.conn.cursor()
        if vehicle_type:
            cur.execute(
                "SELECT COUNT(*) FROM slots "
                "WHERE occupied = 0 AND vehicle_type = ?",
                (vehicle_type,),
            )
        else:
            cur.execute("SELECT COUNT(*) FROM slots WHERE occupied = 0")
        return cur.fetchone()[0]

    def first_free_slot(self, vehicle_type):
        cur = self.conn.cursor()
        cur.execute(
            "SELECT slot_id FROM slots "
            "WHERE occupied = 0 AND vehicle_type = ? "
            "ORDER BY LENGTH(slot_id), slot_id LIMIT 1",
            (vehicle_type,),
        )
        row = cur.fetchone()
        return row[0] if row else None

    # --- anti-double-tap --------------------------------------------------
    def check_duplicate_tap(self, card_id):
        """Return (session_id, slot_id) if this card already has an
        active (un-exited) session, else None."""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT id, slot_id FROM sessions "
            "WHERE card_id = ? AND exit_time IS NULL LIMIT 1",
            (card_id,),
        )
        return cur.fetchone()

    # --- check-in / check-out ---------------------------------------------
    def check_in(self, slot_id, plate, vehicle_type, card_id, is_student=False):
        cur = self.conn.cursor()
        cur.execute(
            "UPDATE slots SET occupied = 1 WHERE slot_id = ?", (slot_id,)
        )
        cur.execute(
            "INSERT INTO sessions "
            "(slot_id, plate, vehicle_type, card_id, is_student, entry_time) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                slot_id,
                plate.upper().strip(),
                vehicle_type,
                card_id,
                1 if is_student else 0,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        self.conn.commit()

    def active_session_by_card(self, card_id):
        cur = self.conn.cursor()
        cur.execute(
            "SELECT id, slot_id, plate, vehicle_type, is_student, entry_time "
            "FROM sessions "
            "WHERE card_id = ? AND exit_time IS NULL "
            "ORDER BY id DESC LIMIT 1",
            (card_id,),
        )
        return cur.fetchone()

    def active_session_for_slot(self, slot_id):
        cur = self.conn.cursor()
        cur.execute(
            "SELECT id, plate, entry_time, card_id, is_student, vehicle_type "
            "FROM sessions "
            "WHERE slot_id = ? AND exit_time IS NULL "
            "ORDER BY id DESC LIMIT 1",
            (slot_id,),
        )
        return cur.fetchone()

    def check_out_by_card(self, card_id):
        """Check out by card/student ID.  Returns a result dict or None."""
        session = self.active_session_by_card(card_id)
        if not session:
            return None

        session_id, slot_id, plate, vehicle_type, is_student, entry_str = session
        entry_time = datetime.fromisoformat(entry_str)
        exit_time = datetime.now()

        fee = 0 if is_student else calculate_fee(vehicle_type, entry_time, exit_time)

        cur = self.conn.cursor()
        cur.execute(
            "UPDATE sessions SET exit_time = ?, fee = ? WHERE id = ?",
            (exit_time.isoformat(timespec="seconds"), fee, session_id),
        )
        cur.execute(
            "UPDATE slots SET occupied = 0 WHERE slot_id = ?", (slot_id,)
        )
        self.conn.commit()

        return {
            "plate": plate,
            "slot_id": slot_id,
            "vehicle_type": vehicle_type,
            "is_student": bool(is_student),
            "entry_time": entry_time,
            "exit_time": exit_time,
            "duration_minutes": (exit_time - entry_time).total_seconds() / 60,
            "fee": fee,
        }

    # --- student management -----------------------------------------------
    def is_registered_student(self, student_id):
        cur = self.conn.cursor()
        cur.execute(
            "SELECT 1 FROM students WHERE student_id = ?", (student_id,)
        )
        return cur.fetchone() is not None

    def add_student(self, student_id, name):
        cur = self.conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO students (student_id, name, registered_at) "
            "VALUES (?, ?, ?)",
            (student_id, name, datetime.now().isoformat(timespec="seconds")),
        )
        self.conn.commit()

    def remove_student(self, student_id):
        cur = self.conn.cursor()
        cur.execute("DELETE FROM students WHERE student_id = ?", (student_id,))
        self.conn.commit()

    def get_students(self):
        cur = self.conn.cursor()
        cur.execute(
            "SELECT student_id, name, registered_at "
            "FROM students ORDER BY student_id"
        )
        return cur.fetchall()

    # --- plate detections -------------------------------------------------
    def save_plate_detection(self, plate_text, confidence, image_path):
        """Save a plate detection record."""
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO plate_detections "
            "(plate_text, confidence, image_path, detected_at) "
            "VALUES (?, ?, ?, ?)",
            (
                plate_text,
                confidence,
                image_path,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_latest_unused_plate(self):
        """Get the most recent unused plate detection."""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT id, plate_text, confidence, image_path, detected_at "
            "FROM plate_detections "
            "WHERE used = 0 "
            "ORDER BY id DESC LIMIT 1"
        )
        return cur.fetchone()

    def mark_plate_used(self, detection_id):
        """Mark a plate detection as used (linked to a session)."""
        cur = self.conn.cursor()
        cur.execute(
            "UPDATE plate_detections SET used = 1 WHERE id = ?",
            (detection_id,),
        )
        self.conn.commit()

    # --- history / reporting ----------------------------------------------
    def history(self, limit=50):
        cur = self.conn.cursor()
        cur.execute(
            "SELECT slot_id, plate, vehicle_type, card_id, is_student, "
            "       entry_time, exit_time, fee "
            "FROM sessions ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return cur.fetchall()

    def todays_revenue(self):
        cur = self.conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        cur.execute(
            "SELECT COALESCE(SUM(fee), 0) FROM sessions "
            "WHERE exit_time LIKE ? AND is_student = 0",
            (f"{today}%",),
        )
        return cur.fetchone()[0]

    def close(self):
        self.conn.close()
