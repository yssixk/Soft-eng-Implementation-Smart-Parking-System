#!/usr/bin/env python3
"""
Smart Parking System — Entry Point
------------------------------------
Launch the parking management GUI.

Usage:
    python main.py
"""

from gui import ParkingApp


if __name__ == "__main__":
    app = ParkingApp()
    app.mainloop()
