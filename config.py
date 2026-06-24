#!/usr/bin/env python3
"""
Smart Parking System — Configuration
--------------------------------------
All constants, paths, and tuning parameters in one place.
"""

import os

# ---------------------------------------------------------------------------
# PATHS
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, "parking.db")
SLOTS_CONFIG = os.path.join(SCRIPT_DIR, "slots_config.json")
REFERENCE_IMAGE = os.path.join(SCRIPT_DIR, "reference.jpg")
PLATE_IMAGE_DIR = os.path.join(SCRIPT_DIR, "foto_plat")

# ---------------------------------------------------------------------------
# PARKING LAYOUT
# ---------------------------------------------------------------------------
CAR_SLOTS = 60
MOTOR_SLOTS = 100

# ---------------------------------------------------------------------------
# PRICING (Indonesian Rupiah)
# ---------------------------------------------------------------------------
CURRENCY = "Rp"
GRACE_PERIOD_MINUTES = 15          # free if exit within this time

CAR_RATE_FIRST_HOUR = 5000         # flat per hour
CAR_RATE_ADDITIONAL = 5000         # same flat rate each additional hour

MOTOR_RATE_FIRST_HOUR = 2000       # first hour
MOTOR_RATE_ADDITIONAL = 3000       # each additional hour after the first

# ---------------------------------------------------------------------------
# GATE SAFETY
# ---------------------------------------------------------------------------
CAR_GATE_OPEN_DURATION = 8         # seconds the gate stays open
MOTOR_GATE_OPEN_DURATION = 5

# ---------------------------------------------------------------------------
# DATABASE
# ---------------------------------------------------------------------------
SCHEMA_VERSION = 3                 # bumped for plate_detections table

# ---------------------------------------------------------------------------
# CAMERA / DROIDCAM
# ---------------------------------------------------------------------------
DEFAULT_DROIDCAM_URL = "http://192.168.0.168:4747/video"

# ---------------------------------------------------------------------------
# PARKING DETECTOR (slot occupancy)
# ---------------------------------------------------------------------------
DIFF_THRESHOLD = 30                # per-pixel brightness change to count
OCCUPIED_PERCENT = 12              # % of ROI pixels that must differ → occupied
UPDATE_INTERVAL_SEC = 2            # how often to push status to database
