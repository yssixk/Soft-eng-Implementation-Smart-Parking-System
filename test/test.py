#!/usr/bin/env python3
"""
Unit tests for the Smart Parking System.
Tests fee calculations, database operations, and plate detection helpers.
"""

import os
import unittest
from datetime import datetime, timedelta
import sqlite3
import sys



sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import calculate_fee, ParkingDB
from config import CAR_SLOTS, MOTOR_SLOTS

class TestParkingFee(unittest.TestCase):
    """Test suite for calculate_fee logic."""

    def test_grace_period(self):
        # 15 minutes or less should be free
        entry = datetime(2026, 6, 24, 12, 0, 0)
        exit_time = entry + timedelta(minutes=15)
        self.assertEqual(calculate_fee("car", entry, exit_time), 0)
        self.assertEqual(calculate_fee("motor", entry, exit_time), 0)

        exit_time_short = entry + timedelta(minutes=5)
        self.assertEqual(calculate_fee("car", entry, exit_time_short), 0)

    def test_car_fees(self):
        entry = datetime(2026, 6, 24, 12, 0, 0)

        # 16 minutes -> 1 hour (5,000)
        exit_time = entry + timedelta(minutes=16)
        self.assertEqual(calculate_fee("car", entry, exit_time), 5000)

        # 1 hour -> 1 hour (5,000)
        exit_time = entry + timedelta(hours=1)
        self.assertEqual(calculate_fee("car", entry, exit_time), 5000)

        # 1 hour 1 minute -> 2 hours (10,000)
        exit_time = entry + timedelta(hours=1, minutes=1)
        self.assertEqual(calculate_fee("car", entry, exit_time), 10000)

        # 3 hours -> 3 hours (15,000)
        exit_time = entry + timedelta(hours=3)
        self.assertEqual(calculate_fee("car", entry, exit_time), 15000)

    def test_motor_fees(self):
        entry = datetime(2026, 6, 24, 12, 0, 0)

        # 16 minutes -> 1 hour (2,000)
        exit_time = entry + timedelta(minutes=16)
        self.assertEqual(calculate_fee("motor", entry, exit_time), 2000)

        # 1 hour -> 1 hour (2,000)
        exit_time = entry + timedelta(hours=1)
        self.assertEqual(calculate_fee("motor", entry, exit_time), 2000)

        # 1 hour 1 minute -> 2 hours (2,000 + 3,000 = 5,000)
        exit_time = entry + timedelta(hours=1, minutes=1)
        self.assertEqual(calculate_fee("motor", entry, exit_time), 5000)

        # 3 hours -> 3 hours (2,000 + 2 * 3,000 = 8,000)
        exit_time = entry + timedelta(hours=3)
        self.assertEqual(calculate_fee("motor", entry, exit_time), 8000)


class TestParkingDB(unittest.TestCase):
    """Test suite for database layer operations using a temporary database."""

    TEST_DB_PATH = "test_parking_temp.db"

    def setUp(self):
        # Always remove test DB if it exists
        if os.path.exists(self.TEST_DB_PATH):
            try:
                os.remove(self.TEST_DB_PATH)
            except PermissionError:
                pass
        self.db = ParkingDB(self.TEST_DB_PATH)

    def tearDown(self):
        self.db.close()
        if os.path.exists(self.TEST_DB_PATH):
            try:
                os.remove(self.TEST_DB_PATH)
            except PermissionError:
                pass

    def test_initialization(self):
        # Verify slots were created and seeded correctly
        slots = self.db.get_slots()
        # Sum of car slots (60) and motor slots (100)
        self.assertEqual(len(slots), CAR_SLOTS + MOTOR_SLOTS)

        car_slots = self.db.get_slots("car")
        self.assertEqual(len(car_slots), CAR_SLOTS)
        self.assertEqual(car_slots[0][0], "C1")

        motor_slots = self.db.get_slots("motor")
        self.assertEqual(len(motor_slots), MOTOR_SLOTS)
        self.assertEqual(motor_slots[0][0], "M1")

        # Initial free slots count
        self.assertEqual(self.db.free_slot_count(), CAR_SLOTS + MOTOR_SLOTS)
        self.assertEqual(self.db.free_slot_count("car"), CAR_SLOTS)
        self.assertEqual(self.db.free_slot_count("motor"), MOTOR_SLOTS)

    def test_first_free_slot(self):
        self.assertEqual(self.db.first_free_slot("car"), "C1")
        self.assertEqual(self.db.first_free_slot("motor"), "M1")

    def test_student_management(self):
        student_id = "1234567"
        name = "Alice Test"

        # Not registered initially
        self.assertFalse(self.db.is_registered_student(student_id))

        # Add student
        self.db.add_student(student_id, name)
        self.assertTrue(self.db.is_registered_student(student_id))

        students = self.db.get_students()
        self.assertEqual(len(students), 1)
        self.assertEqual(students[0][0], student_id)
        self.assertEqual(students[0][1], name)

        # Remove student
        self.db.remove_student(student_id)
        self.assertFalse(self.db.is_registered_student(student_id))
        self.assertEqual(len(self.db.get_students()), 0)

    def test_check_in_check_out_regular(self):
        slot = "C1"
        plate = "B 1234 CD"
        vehicle_type = "car"
        card_id = "CARD001"

        # Ensure slot is empty
        self.assertEqual(self.db.free_slot_count("car"), CAR_SLOTS)

        # Check duplicate tap before checking in
        self.assertIsNone(self.db.check_duplicate_tap(card_id))

        # Check-in
        self.db.check_in(slot, plate, vehicle_type, card_id, is_student=False)

        # Check duplicate tap now
        duplicate = self.db.check_duplicate_tap(card_id)
        self.assertIsNotNone(duplicate)
        self.assertEqual(duplicate[1], slot)

        # Slot should be occupied now
        self.assertEqual(self.db.free_slot_count("car"), CAR_SLOTS - 1)
        self.assertEqual(self.db.first_free_slot("car"), "C2")

        # Active session by slot and card
        session_card = self.db.active_session_by_card(card_id)
        self.assertIsNotNone(session_card)
        self.assertEqual(session_card[1], slot)
        self.assertEqual(session_card[2], plate)

        session_slot = self.db.active_session_for_slot(slot)
        self.assertIsNotNone(session_slot)
        self.assertEqual(session_slot[1], plate)
        self.assertEqual(session_slot[3], card_id)

        # Check out
        res = self.db.check_out_by_card(card_id)
        self.assertIsNotNone(res)
        self.assertEqual(res["plate"], plate)
        self.assertEqual(res["slot_id"], slot)
        self.assertEqual(res["vehicle_type"], vehicle_type)
        self.assertFalse(res["is_student"])
        # Because entry and exit are almost instant, duration < 15 min, fee should be 0
        self.assertEqual(res["fee"], 0)

        # Slot should be free again
        self.assertEqual(self.db.free_slot_count("car"), CAR_SLOTS)

    def test_check_in_check_out_student(self):
        slot = "M1"
        plate = "B 5678 EF"
        vehicle_type = "motor"
        card_id = "STUDENT01"

        # Check-in student
        self.db.check_in(slot, plate, vehicle_type, card_id, is_student=True)

        # Active session by card shows is_student = 1
        session = self.db.active_session_by_card(card_id)
        self.assertEqual(session[4], 1)

        # Check out
        res = self.db.check_out_by_card(card_id)
        self.assertIsNotNone(res)
        self.assertTrue(res["is_student"])
        self.assertEqual(res["fee"], 0)

    def test_plate_detections(self):
        # Initially no unused plates
        self.assertIsNone(self.db.get_latest_unused_plate())

        # Save plate
        det_id = self.db.save_plate_detection("B 9999 AA", 0.92, "foto_plat/test.jpg")
        self.assertIsNotNone(det_id)

        # Get latest unused
        unused = self.db.get_latest_unused_plate()
        self.assertIsNotNone(unused)
        self.assertEqual(unused[0], det_id)
        self.assertEqual(unused[1], "B 9999 AA")
        self.assertEqual(unused[2], 0.92)

        # Mark as used
        self.db.mark_plate_used(det_id)
        self.assertIsNone(self.db.get_latest_unused_plate())


if __name__ == "__main__":
    unittest.main()
