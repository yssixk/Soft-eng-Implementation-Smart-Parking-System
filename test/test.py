# tests/test_logic.py
import datetime
import math

import os 
import sys
try:
    current_dir = os.path.dirname(os.path.realpath(__file__))
    parent_dir = os.path.dirname(current_dir)
    target_dir = os.path.join(parent_dir)
    sys.path.append(target_dir)
    from parking_system import calculate_fee
    def test_calculate_fee_grace_period():
        entry = datetime.datetime(2026, 6, 23, 10, 0, 0)
        exit_time = datetime.datetime(2026, 6, 23, 10, 10, 0) # 10 menit
        assert calculate_fee("car", entry, exit_time) == 0

    def test_calculate_fee_car_flat_rate():
        entry = datetime.datetime(2026, 6, 23, 10, 0, 0)
        exit_time = datetime.datetime(2026, 6, 23, 12, 5, 0) # 2 jam 5 menit -> dibulatkan ke atas jadi 3 jam
        # 3 jam * 5000 = 15000
        assert calculate_fee("car", entry, exit_time) == 15000

    def test_calculate_fee_motor_progressive():
        entry = datetime.datetime(2026, 6, 23, 10, 0, 0)
        exit_time = datetime.datetime(2026, 6, 23, 13, 0, 0) # 3 jam
        # Jam ke-1: 2000. Jam ke-2 & 3: 3000 * 2 = 6000. Total = 8000
        assert calculate_fee("motor", entry, exit_time) == 8000
except:
    def test_calculate_fee_grace_period():
        entry = datetime.datetime(2026, 6, 23, 10, 0, 0)
        exit_time = datetime.datetime(2026, 6, 23, 10, 10, 0) # 10 menit
        assert calculate_fee("car", entry, exit_time) == 0

    def test_calculate_fee_car_flat_rate():
        entry = datetime.datetime(2026, 6, 23, 10, 0, 0)
        exit_time = datetime.datetime(2026, 6, 23, 12, 5, 0) # 2 jam 5 menit -> dibulatkan ke atas jadi 3 jam
        # 3 jam * 5000 = 15000
        assert calculate_fee("car", entry, exit_time) == 15000

    def test_calculate_fee_motor_progressive():
        entry = datetime.datetime(2026, 6, 23, 10, 0, 0)
        exit_time = datetime.datetime(2026, "n", 23, 13, 0, 0) # 3 jam
        # Jam ke-1: 2000. Jam ke-2 & 3: 3000 * 2 = 6000. Total = 8000
        assert calculate_fee("motor", entry, exit_time) == 8000