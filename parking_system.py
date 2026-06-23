#!/usr/bin/env python3
"""
Smart Parking System
---------------------
GUI parking management system with two-zone layout (Car + Motorcycle),
student ID free parking, e-money payment, and gate simulation.

Layout matches the real-life parking lot diagram:
- Left:   Car Parking Only (60 slots in 2 sections)
- Center: Service Lane
- Right:  Motorcycle Parking Only (100 slots)
- Bottom: Entry Gate (Ticket/Tap) and Exit Gate

Features:
- Student ID tap → free parking (rate negated)
- E-Money / Flash Card for non-students
- First 15 minutes free for all
- Anti-double-tap protection
- Gate safety timer (stays open until vehicle passes)

"""

import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from datetime import datetime
import math
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "parking.db")

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
CAR_SLOTS = 60
MOTOR_SLOTS = 100

# Pricing (Indonesian Rupiah)
CURRENCY = "Rp"
GRACE_PERIOD_MINUTES = 15        # free if exit within this time

CAR_RATE_FIRST_HOUR = 5000       # flat per hour
CAR_RATE_ADDITIONAL = 5000       # same flat rate each additional hour

MOTOR_RATE_FIRST_HOUR = 2000     # first hour
MOTOR_RATE_ADDITIONAL = 3000     # each additional hour after the first

# Gate safety: seconds the gate stays open for the vehicle to pass
CAR_GATE_OPEN_DURATION = 8
MOTOR_GATE_OPEN_DURATION = 5

# Schema version – bump when DB schema changes to auto-recreate tables
SCHEMA_VERSION = 2


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
    and e-money card tracking."""

    def __init__(self, path=DB_PATH):
        self.conn = sqlite3.connect(path)
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
            for tbl in ("sessions", "slots", "students", "schema_info"):
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
    def check_in(self, slot_id, plate, vehicle_type, card_id, is_student):
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


# ---------------------------------------------------------------------------
# GUI LAYER
# ---------------------------------------------------------------------------
class ParkingApp(tk.Tk):
    """Main application window.  Layout mirrors the real parking lot:
    car zone (left), service lane (center), motorcycle zone (right),
    entry/exit gates (bottom)."""

    # -- colour palette ----------------------------------------------------
    SLOT_FREE_CAR = "#27ae60"
    SLOT_OCC_CAR = "#c0392b"
    SLOT_FREE_MOTOR = "#2ecc71"
    SLOT_OCC_MOTOR = "#e74c3c"
    BG = "#ecf0f1"
    HEADER_BG = "#2c3e50"
    LANE_BG = "#f39c12"
    GATE_BG = "#2c3e50"
    GATE_OPEN = "#2ecc71"
    GATE_CLOSED = "#e74c3c"

    def __init__(self):
        super().__init__()
        self.title("\U0001f17f\ufe0f  Smart Parking System")
        self.geometry("1400x860")
        self.configure(bg=self.BG)
        self.minsize(1200, 750)

        self.db = ParkingDB()
        self.slot_buttons: dict[str, tk.Button] = {}

        # gate state
        self.entry_gate_open = False
        self.exit_gate_open = False
        self._entry_timer_id = None
        self._exit_timer_id = None

        self._build_header()
        self._build_body()
        self._build_gates()
        self._build_footer()

        self.refresh_slots()
        self.refresh_history()
        self.after(1000, self._tick)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # =================================================================== #
    #  UI CONSTRUCTION                                                      #
    # =================================================================== #
    def _build_header(self):
        hdr = tk.Frame(self, bg=self.HEADER_BG, height=55)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        tk.Label(
            hdr,
            text="\U0001f17f\ufe0f  Smart Parking System",
            font=("Helvetica", 16, "bold"),
            bg=self.HEADER_BG,
            fg="white",
        ).pack(side="left", padx=20)

        self.stats_lbl = tk.Label(
            hdr, text="", font=("Helvetica", 10), bg=self.HEADER_BG, fg="#ecf0f1"
        )
        self.stats_lbl.pack(side="right", padx=20)

    # ------------------------------------------------------------------ #
    def _build_body(self):
        body = tk.Frame(self, bg=self.BG)
        body.pack(fill="both", expand=True, padx=8, pady=4)

        body.columnconfigure(0, weight=3)   # car zone
        body.columnconfigure(1, weight=0)   # service lane
        body.columnconfigure(2, weight=4)   # motor zone
        body.columnconfigure(3, weight=3)   # activity log
        body.rowconfigure(0, weight=1)

        self._build_car_zone(body)
        self._build_service_lane(body)
        self._build_motor_zone(body)
        self._build_activity_log(body)

    def _build_car_zone(self, parent):
        frame = tk.LabelFrame(
            parent,
            text="  \U0001f697  CAR PARKING ONLY (ONLY MOBIL)  ",
            bg="#dfe6e9",
            font=("Helvetica", 10, "bold"),
            fg="#2c3e50",
            padx=4,
            pady=4,
        )
        frame.grid(row=0, column=0, sticky="nsew", padx=(0, 2))

        # --- scrollable wrapper so it works on small screens ---
        canvas = tk.Canvas(frame, bg="#dfe6e9", highlightthickness=0)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg="#dfe6e9")
        inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        # mouse-wheel (local only, not bind_all)
        def _car_scroll(event):
            canvas.yview_scroll(-1 * (event.delta // 120), "units")

        canvas.bind("<MouseWheel>", _car_scroll)
        inner.bind("<MouseWheel>", _car_scroll)

        # Upper section
        tk.Label(
            inner,
            text="\u25b8 Upper Section (C1\u2013C30)",
            bg="#dfe6e9",
            font=("Helvetica", 8, "bold"),
            fg="#2c3e50",
        ).grid(row=0, column=0, columnspan=6, sticky="w", padx=4, pady=(2, 1))

        for i in range(1, 31):
            r, c = divmod(i - 1, 6)
            sid = f"C{i}"
            btn = tk.Button(
                inner,
                text=f"{sid}\nFREE",
                width=7,
                height=2,
                bg=self.SLOT_FREE_CAR,
                fg="white",
                font=("Helvetica", 7, "bold"),
                relief="flat",
                bd=1,
                command=lambda s=sid: self.on_slot_click(s),
            )
            btn.grid(row=r + 1, column=c, padx=2, pady=2)
            self.slot_buttons[sid] = btn

        # separator
        ttk.Separator(inner, orient="horizontal").grid(
            row=7, column=0, columnspan=6, sticky="ew", pady=4
        )

        # Lower section
        tk.Label(
            inner,
            text="\u25b8 Lower Section (C31\u2013C60)",
            bg="#dfe6e9",
            font=("Helvetica", 8, "bold"),
            fg="#2c3e50",
        ).grid(row=8, column=0, columnspan=6, sticky="w", padx=4, pady=(2, 1))

        for i in range(31, 61):
            r, c = divmod(i - 31, 6)
            sid = f"C{i}"
            btn = tk.Button(
                inner,
                text=f"{sid}\nFREE",
                width=7,
                height=2,
                bg=self.SLOT_FREE_CAR,
                fg="white",
                font=("Helvetica", 7, "bold"),
                relief="flat",
                bd=1,
                command=lambda s=sid: self.on_slot_click(s),
            )
            btn.grid(row=r + 9, column=c, padx=2, pady=2)
            self.slot_buttons[sid] = btn

        # Legend
        leg = tk.Frame(inner, bg="#dfe6e9")
        leg.grid(row=20, column=0, columnspan=6, pady=(6, 2))
        tk.Label(
            leg, text="\u25cf Free", fg=self.SLOT_FREE_CAR, bg="#dfe6e9",
            font=("Helvetica", 8, "bold"),
        ).pack(side="left", padx=8)
        tk.Label(
            leg, text="\u25cf Occupied", fg=self.SLOT_OCC_CAR, bg="#dfe6e9",
            font=("Helvetica", 8, "bold"),
        ).pack(side="left", padx=8)
        tk.Label(
            leg, text="\U0001f393 Student", fg="#8e44ad", bg="#dfe6e9",
            font=("Helvetica", 8, "bold"),
        ).pack(side="left", padx=8)

    def _build_service_lane(self, parent):
        lane = tk.Frame(parent, bg=self.LANE_BG, width=28)
        lane.grid(row=0, column=1, sticky="ns", padx=2)
        lane.grid_propagate(False)

        # vertical text
        tk.Label(lane, text="", bg=self.LANE_BG).pack(pady=15)
        for ch in "SERVICE LANE":
            tk.Label(
                lane, text=ch, bg=self.LANE_BG, fg="white",
                font=("Helvetica", 9, "bold"),
            ).pack(pady=0)

    def _build_motor_zone(self, parent):
        frame = tk.LabelFrame(
            parent,
            text="  \U0001f3cd\ufe0f  MOTORCYCLE PARKING ONLY (ONLY MOTOR)  ",
            bg="#d5f5e3",
            font=("Helvetica", 10, "bold"),
            fg="#1a5276",
            padx=4,
            pady=4,
        )
        frame.grid(row=0, column=2, sticky="nsew", padx=(2, 4))

        # Scrollable canvas with both vertical and horizontal scrollbars
        canvas = tk.Canvas(frame, bg="#d5f5e3", highlightthickness=0)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        hsb = ttk.Scrollbar(frame, orient="horizontal", command=canvas.xview)
        inner = tk.Frame(canvas, bg="#d5f5e3")
        inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        # Grid layout: canvas fills center, scrollbars on edges
        canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        # Mouse wheel: vertical scroll + Shift+wheel for horizontal
        def _on_mousewheel(event):
            canvas.yview_scroll(-1 * (event.delta // 120), "units")

        def _on_shift_mousewheel(event):
            canvas.xview_scroll(-1 * (event.delta // 120), "units")

        canvas.bind("<MouseWheel>", _on_mousewheel)
        canvas.bind("<Shift-MouseWheel>", _on_shift_mousewheel)
        inner.bind("<MouseWheel>", _on_mousewheel)
        inner.bind("<Shift-MouseWheel>", _on_shift_mousewheel)

        for i in range(1, MOTOR_SLOTS + 1):
            r, c = divmod(i - 1, 10)
            sid = f"M{i}"
            btn = tk.Button(
                inner,
                text=f"{sid}\nFREE",
                width=7,
                height=2,
                bg=self.SLOT_FREE_MOTOR,
                fg="white",
                font=("Helvetica", 7, "bold"),
                relief="flat",
                bd=1,
                command=lambda s=sid: self.on_slot_click(s),
            )
            btn.grid(row=r, column=c, padx=2, pady=2)
            self.slot_buttons[sid] = btn
            # Bind scroll on buttons too so scrolling works when hovering over them
            btn.bind("<MouseWheel>", _on_mousewheel)
            btn.bind("<Shift-MouseWheel>", _on_shift_mousewheel)

        # Legend
        leg = tk.Frame(inner, bg="#d5f5e3")
        leg.grid(row=11, column=0, columnspan=10, pady=(6, 2))
        tk.Label(
            leg, text="\u25cf Free", fg=self.SLOT_FREE_MOTOR, bg="#d5f5e3",
            font=("Helvetica", 8, "bold"),
        ).pack(side="left", padx=8)
        tk.Label(
            leg, text="\u25cf Occupied", fg=self.SLOT_OCC_MOTOR, bg="#d5f5e3",
            font=("Helvetica", 8, "bold"),
        ).pack(side="left", padx=8)
        tk.Label(
            leg, text="\U0001f393 Student", fg="#8e44ad", bg="#d5f5e3",
            font=("Helvetica", 8, "bold"),
        ).pack(side="left", padx=8)

    def _build_activity_log(self, parent):
        frame = tk.LabelFrame(
            parent,
            text="  \U0001f4cb  Recent Activity  ",
            bg=self.BG,
            font=("Helvetica", 10, "bold"),
            padx=4,
            pady=4,
        )
        frame.grid(row=0, column=3, sticky="nsew", padx=(4, 0))

        cols = ("slot", "plate", "type", "in", "out", "fee")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", height=22)
        hdrs = {
            "slot": "Slot",
            "plate": "Plate",
            "type": "Type",
            "in": "Entry",
            "out": "Exit",
            "fee": f"Fee ({CURRENCY})",
        }
        widths = {"slot": 42, "plate": 62, "type": 35, "in": 62, "out": 62, "fee": 55}
        for c in cols:
            self.tree.heading(c, text=hdrs[c])
            self.tree.column(c, width=widths[c], anchor="center")
        self.tree.pack(fill="both", expand=True, side="left")

        sb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=sb.set)
        sb.pack(side="right", fill="y")

    # ------------------------------------------------------------------ #
    def _build_gates(self):
        gate = tk.Frame(self, bg=self.GATE_BG, height=110)
        gate.pack(fill="x", padx=8, pady=(0, 4))
        gate.pack_propagate(False)

        # ---- Entry Gate ----
        ef = tk.Frame(gate, bg=self.GATE_BG)
        ef.pack(side="left", fill="both", expand=True, padx=10)

        tk.Label(
            ef, text="\U0001f6a7 ENTRY GATE (TICKET / TAP CARD)",
            bg=self.GATE_BG, fg="white", font=("Helvetica", 11, "bold"),
        ).pack(pady=(8, 2))

        self.entry_status = tk.Label(
            ef, text="\U0001f534 CLOSED", bg=self.GATE_BG,
            fg=self.GATE_CLOSED, font=("Helvetica", 10, "bold"),
        )
        self.entry_status.pack()

        self.entry_countdown = tk.Label(
            ef, text="", bg=self.GATE_BG, fg="#f1c40f", font=("Helvetica", 9),
        )
        self.entry_countdown.pack()

        bf = tk.Frame(ef, bg=self.GATE_BG)
        bf.pack(pady=4)

        self.entry_stu_btn = tk.Button(
            bf, text="\U0001f468\u200d\U0001f393 Tap Student ID",
            bg="#8e44ad", fg="white", font=("Helvetica", 9, "bold"),
            relief="flat", padx=10, pady=5, command=self.entry_student_tap,
        )
        self.entry_stu_btn.pack(side="left", padx=5)

        self.entry_em_btn = tk.Button(
            bf, text="\U0001f4b3 Tap E-Money / Flash Card",
            bg="#2980b9", fg="white", font=("Helvetica", 9, "bold"),
            relief="flat", padx=10, pady=5, command=self.entry_emoney_tap,
        )
        self.entry_em_btn.pack(side="left", padx=5)

        tk.Label(
            ef, text="\u25c4\u2500\u2500 ENTRY ROAD \u2500\u2500\u25ba",
            bg=self.GATE_BG, fg="#95a5a6", font=("Helvetica", 8),
        ).pack()

        # ---- divider ----
        tk.Frame(gate, bg="#7f8c8d", width=2).pack(
            side="left", fill="y", padx=5, pady=10
        )

        # ---- Exit Gate ----
        xf = tk.Frame(gate, bg=self.GATE_BG)
        xf.pack(side="right", fill="both", expand=True, padx=10)

        tk.Label(
            xf, text="\U0001f6a7 EXIT GATE (EXIT TICKET)",
            bg=self.GATE_BG, fg="white", font=("Helvetica", 11, "bold"),
        ).pack(pady=(8, 2))

        self.exit_status = tk.Label(
            xf, text="\U0001f534 CLOSED", bg=self.GATE_BG,
            fg=self.GATE_CLOSED, font=("Helvetica", 10, "bold"),
        )
        self.exit_status.pack()

        self.exit_countdown = tk.Label(
            xf, text="", bg=self.GATE_BG, fg="#f1c40f", font=("Helvetica", 9),
        )
        self.exit_countdown.pack()

        bf2 = tk.Frame(xf, bg=self.GATE_BG)
        bf2.pack(pady=4)

        self.exit_stu_btn = tk.Button(
            bf2, text="\U0001f468\u200d\U0001f393 Tap Student ID",
            bg="#8e44ad", fg="white", font=("Helvetica", 9, "bold"),
            relief="flat", padx=10, pady=5, command=self.exit_student_tap,
        )
        self.exit_stu_btn.pack(side="left", padx=5)

        self.exit_em_btn = tk.Button(
            bf2, text="\U0001f4b3 Tap E-Money / Flash Card",
            bg="#2980b9", fg="white", font=("Helvetica", 9, "bold"),
            relief="flat", padx=10, pady=5, command=self.exit_emoney_tap,
        )
        self.exit_em_btn.pack(side="left", padx=5)

        tk.Label(
            xf, text="\u25c4\u2500\u2500 EXIT ROAD \u2500\u2500\u25ba",
            bg=self.GATE_BG, fg="#95a5a6", font=("Helvetica", 8),
        ).pack()

    # ------------------------------------------------------------------ #
    def _build_footer(self):
        ft = tk.Frame(self, bg=self.BG)
        ft.pack(fill="x", side="bottom", pady=(0, 6))

        tk.Button(
            ft, text="\U0001f465 Manage Students", bg="#8e44ad", fg="white",
            font=("Helvetica", 9, "bold"), relief="flat", padx=10, pady=5,
            command=self.open_student_manager,
        ).pack(side="left", padx=15)

        tk.Button(
            ft, text="\U0001f504 Refresh", bg="#7f8c8d", fg="white",
            font=("Helvetica", 9, "bold"), relief="flat", padx=10, pady=5,
            command=lambda: (self.refresh_slots(), self.refresh_history()),
        ).pack(side="left", padx=5)

        tk.Label(
            ft,
            text=(
                f"\U0001f3cd\ufe0f Motor: {CURRENCY} {MOTOR_RATE_FIRST_HOUR:,}/1st hr"
                f" + {CURRENCY} {MOTOR_RATE_ADDITIONAL:,}/hr  |  "
                f"\U0001f697 Car: {CURRENCY} {CAR_RATE_FIRST_HOUR:,}/hr  |  "
                f"\u23f1 First {GRACE_PERIOD_MINUTES} min FREE"
            ),
            bg=self.BG,
            font=("Helvetica", 9),
            fg="#7f8c8d",
        ).pack(side="right", padx=15)

    # =================================================================== #
    #  GATE LOGIC                                                           #
    # =================================================================== #
    def _open_gate(self, gate, vehicle_type):
        """Open entry or exit gate with a safety countdown."""
        dur = (
            CAR_GATE_OPEN_DURATION
            if vehicle_type == "car"
            else MOTOR_GATE_OPEN_DURATION
        )
        if gate == "entry":
            self.entry_gate_open = True
            self.entry_status.config(text="\U0001f7e2 OPEN", fg=self.GATE_OPEN)
            self.entry_stu_btn.config(state="disabled")
            self.entry_em_btn.config(state="disabled")
            self._gate_tick("entry", dur)
        else:
            self.exit_gate_open = True
            self.exit_status.config(text="\U0001f7e2 OPEN", fg=self.GATE_OPEN)
            self.exit_stu_btn.config(state="disabled")
            self.exit_em_btn.config(state="disabled")
            self._gate_tick("exit", dur)

    def _gate_tick(self, gate, remaining):
        if remaining <= 0:
            self._close_gate(gate)
            return
        lbl = self.entry_countdown if gate == "entry" else self.exit_countdown
        lbl.config(text=f"Gate closing in {remaining}s \u2013 vehicle passing\u2026")
        timer_id = self.after(1000, self._gate_tick, gate, remaining - 1)
        if gate == "entry":
            self._entry_timer_id = timer_id
        else:
            self._exit_timer_id = timer_id

    def _close_gate(self, gate):
        if gate == "entry":
            self.entry_gate_open = False
            self.entry_status.config(text="\U0001f534 CLOSED", fg=self.GATE_CLOSED)
            self.entry_countdown.config(text="")
            self.entry_stu_btn.config(state="normal")
            self.entry_em_btn.config(state="normal")
            self._entry_timer_id = None
        else:
            self.exit_gate_open = False
            self.exit_status.config(text="\U0001f534 CLOSED", fg=self.GATE_CLOSED)
            self.exit_countdown.config(text="")
            self.exit_stu_btn.config(state="normal")
            self.exit_em_btn.config(state="normal")
            self._exit_timer_id = None

    # =================================================================== #
    #  VEHICLE TYPE PICKER                                                  #
    # =================================================================== #
    def _ask_vehicle_type(self):
        dlg = tk.Toplevel(self)
        dlg.title("Vehicle Type")
        dlg.geometry("320x160")
        dlg.configure(bg=self.BG)
        dlg.transient(self)
        dlg.grab_set()
        dlg.resizable(False, False)

        result = [None]

        tk.Label(
            dlg, text="Select vehicle type:", bg=self.BG,
            font=("Helvetica", 12, "bold"),
        ).pack(pady=18)

        bf = tk.Frame(dlg, bg=self.BG)
        bf.pack(pady=10)

        def pick(v):
            result[0] = v
            dlg.destroy()

        tk.Button(
            bf, text="\U0001f697  Car", bg="#3498db", fg="white",
            font=("Helvetica", 11, "bold"), relief="flat", padx=20, pady=8,
            command=lambda: pick("car"),
        ).pack(side="left", padx=10)

        tk.Button(
            bf, text="\U0001f3cd\ufe0f  Motorcycle", bg="#27ae60", fg="white",
            font=("Helvetica", 11, "bold"), relief="flat", padx=20, pady=8,
            command=lambda: pick("motor"),
        ).pack(side="left", padx=10)

        self.wait_window(dlg)
        return result[0]

    # =================================================================== #
    #  ENTRY FLOWS                                                          #
    # =================================================================== #
    def entry_student_tap(self):
        if self.entry_gate_open:
            return

        sid = simpledialog.askstring("Student ID", "Tap / Enter Student ID:")
        if not sid:
            return
        sid = sid.strip()

        if not self.db.is_registered_student(sid):
            messagebox.showerror(
                "Not Registered",
                f"Student ID '{sid}' is not registered.\n"
                "Please register at the admin office.",
            )
            return

        dup = self.db.check_duplicate_tap(sid)
        if dup:
            messagebox.showerror(
                "Double Tap",
                f"This Student ID is already checked in at slot {dup[1]}.\n"
                "You cannot tap twice.",
            )
            return

        vtype = self._ask_vehicle_type()
        if not vtype:
            return

        slot = self.db.first_free_slot(vtype)
        if not slot:
            zone = "Car" if vtype == "car" else "Motorcycle"
            messagebox.showwarning("Full", f"No free {zone} slots available.")
            return

        plate = simpledialog.askstring(
            "Plate Number",
            f"Enter vehicle plate number:\n(Assigned to slot {slot})",
        )
        if not plate:
            return

        self.db.check_in(slot, plate, vtype, sid, is_student=True)
        self.refresh_slots()
        self.refresh_history()

        messagebox.showinfo(
            "\u2705 Student Check-In",
            f"Welcome, Student!\n\n"
            f"Slot: {slot}\n"
            f"Plate: {plate.upper().strip()}\n"
            f"Fee: FREE (Student)",
        )
        self._open_gate("entry", vtype)

    def entry_emoney_tap(self):
        if self.entry_gate_open:
            return

        card = simpledialog.askstring(
            "E-Money / Flash Card", "Tap / Enter Card ID:"
        )
        if not card:
            return
        card = card.strip()

        dup = self.db.check_duplicate_tap(card)
        if dup:
            messagebox.showerror(
                "Double Tap",
                f"This card is already checked in at slot {dup[1]}.\n"
                "You cannot tap twice.",
            )
            return

        vtype = self._ask_vehicle_type()
        if not vtype:
            return

        slot = self.db.first_free_slot(vtype)
        if not slot:
            zone = "Car" if vtype == "car" else "Motorcycle"
            messagebox.showwarning("Full", f"No free {zone} slots available.")
            return

        plate = simpledialog.askstring(
            "Plate Number",
            f"Enter vehicle plate number:\n(Assigned to slot {slot})",
        )
        if not plate:
            return

        self.db.check_in(slot, plate, vtype, card, is_student=False)
        self.refresh_slots()
        self.refresh_history()

        if vtype == "car":
            rate_info = f"{CURRENCY} {CAR_RATE_FIRST_HOUR:,}/hr"
        else:
            rate_info = (
                f"{CURRENCY} {MOTOR_RATE_FIRST_HOUR:,}/1st hr + "
                f"{CURRENCY} {MOTOR_RATE_ADDITIONAL:,}/hr"
            )

        messagebox.showinfo(
            "\u2705 E-Money Check-In",
            f"Slot: {slot}\n"
            f"Plate: {plate.upper().strip()}\n"
            f"Card: {card}\n\n"
            f"Rate: {rate_info}\n"
            f"First {GRACE_PERIOD_MINUTES} minutes FREE",
        )
        self._open_gate("entry", vtype)

    # =================================================================== #
    #  EXIT FLOWS                                                           #
    # =================================================================== #
    def exit_student_tap(self):
        if self.exit_gate_open:
            return

        sid = simpledialog.askstring("Student ID", "Tap / Enter Student ID:")
        if not sid:
            return
        sid = sid.strip()

        result = self.db.check_out_by_card(sid)
        if not result:
            messagebox.showerror(
                "Not Found",
                "No active parking session found for this Student ID.",
            )
            return

        dur = self._fmt_dur(result["duration_minutes"])

        messagebox.showinfo(
            "\u2705 Student Check-Out",
            f"Goodbye, Student!\n\n"
            f"Slot: {result['slot_id']}\n"
            f"Plate: {result['plate']}\n"
            f"Duration: {dur}\n"
            f"Fee: FREE (Student)",
        )
        self.refresh_slots()
        self.refresh_history()
        self._open_gate("exit", result["vehicle_type"])

    def exit_emoney_tap(self):
        if self.exit_gate_open:
            return

        card = simpledialog.askstring(
            "E-Money / Flash Card", "Tap / Enter Card ID:"
        )
        if not card:
            return
        card = card.strip()

        result = self.db.check_out_by_card(card)
        if not result:
            messagebox.showerror(
                "Not Found",
                "No active parking session found for this card.",
            )
            return

        dur = self._fmt_dur(result["duration_minutes"])
        fee = result["fee"]

        if fee == 0:
            fee_line = (
                f"Fee: FREE (within {GRACE_PERIOD_MINUTES}-min grace period)"
            )
        else:
            fee_line = f"Fee: {CURRENCY} {fee:,.0f}"

        messagebox.showinfo(
            "\u2705 E-Money Check-Out",
            f"Slot: {result['slot_id']}\n"
            f"Plate: {result['plate']}\n"
            f"Duration: {dur}\n"
            f"{fee_line}\n\n"
            f"Amount deducted from e-money.",
        )
        self.refresh_slots()
        self.refresh_history()
        self._open_gate("exit", result["vehicle_type"])

    # =================================================================== #
    #  SLOT CLICK – info only                                               #
    # =================================================================== #
    def on_slot_click(self, slot_id):
        session = self.db.active_session_for_slot(slot_id)
        if session is None:
            messagebox.showinfo(
                f"Slot {slot_id}",
                f"Slot {slot_id} is FREE.\n\n"
                "Use the gate buttons below to check in a vehicle.",
            )
            return

        _, plate, entry_str, card_id, is_student, vtype = session
        entry_dt = datetime.fromisoformat(entry_str)
        elapsed = (datetime.now() - entry_dt).total_seconds() / 60
        dur = self._fmt_dur(elapsed)
        vname = "Car" if vtype == "car" else "Motorcycle"

        if is_student:
            fee_now = 0
            user_line = f"\U0001f393 Student (FREE) \u2013 ID: {card_id}"
        else:
            fee_now = calculate_fee(vtype, entry_dt, datetime.now())
            user_line = f"\U0001f4b3 E-Money \u2013 Card: {card_id}"

        messagebox.showinfo(
            f"Slot {slot_id}",
            f"Slot: {slot_id}  ({vname})\n"
            f"Plate: {plate}\n"
            f"User: {user_line}\n"
            f"Entry: {entry_str.replace('T', ' ')}\n"
            f"Duration: {dur}\n"
            f"Current Fee: {CURRENCY} {fee_now:,.0f}",
        )

    # =================================================================== #
    #  REFRESH / STATS                                                      #
    # =================================================================== #
    def refresh_slots(self):
        for slot_id, occupied in self.db.get_slots():
            btn = self.slot_buttons.get(slot_id)
            if not btn:
                continue
            is_car = slot_id.startswith("C")
            if occupied:
                session = self.db.active_session_for_slot(slot_id)
                plate = session[1] if session else "?"
                is_stu = session[4] if session else False
                color = self.SLOT_OCC_CAR if is_car else self.SLOT_OCC_MOTOR
                tag = " \U0001f393" if is_stu else ""
                btn.config(text=f"{slot_id}\n{plate}{tag}", bg=color)
            else:
                color = self.SLOT_FREE_CAR if is_car else self.SLOT_FREE_MOTOR
                btn.config(text=f"{slot_id}\nFREE", bg=color)
        self._update_stats()

    def refresh_history(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        for (slot_id, plate, vtype, card_id, is_stu,
             entry, exit_, fee) in self.db.history():
            entry_d = entry.replace("T", " ")[5:]   # compact: drop year
            exit_d = exit_.replace("T", " ")[5:] if exit_ else "\u2014"
            if is_stu:
                fee_d = "FREE"
            elif fee is not None:
                fee_d = f"{fee:,.0f}"
            else:
                fee_d = "\u2014"
            vicon = "\U0001f697" if vtype == "car" else "\U0001f3cd\ufe0f"
            self.tree.insert(
                "", "end",
                values=(slot_id, plate, vicon, entry_d, exit_d, fee_d),
            )

    def _update_stats(self):
        cf = self.db.free_slot_count("car")
        mf = self.db.free_slot_count("motor")
        co = CAR_SLOTS - cf
        mo = MOTOR_SLOTS - mf
        rev = self.db.todays_revenue()
        now = datetime.now().strftime("%H:%M:%S")
        self.stats_lbl.config(
            text=(
                f"\U0001f697 Car: {cf}/{CAR_SLOTS} free  |  "
                f"\U0001f3cd\ufe0f Motor: {mf}/{MOTOR_SLOTS} free  |  "
                f"\U0001f4b0 Revenue: {CURRENCY} {rev:,.0f}  |  "
                f"\U0001f550 {now}"
            )
        )

    def _tick(self):
        self._update_stats()
        self.after(1000, self._tick)

    # =================================================================== #
    #  STUDENT MANAGEMENT DIALOG                                            #
    # =================================================================== #
    def open_student_manager(self):
        dlg = tk.Toplevel(self)
        dlg.title("\U0001f465 Student Management")
        dlg.geometry("520x420")
        dlg.configure(bg=self.BG)
        dlg.transient(self)
        dlg.grab_set()

        tk.Label(
            dlg, text="Registered Students", bg=self.BG,
            font=("Helvetica", 13, "bold"),
        ).pack(pady=10)

        tf = tk.Frame(dlg, bg=self.BG)
        tf.pack(fill="both", expand=True, padx=15)

        cols = ("id", "name", "registered")
        tree = ttk.Treeview(tf, columns=cols, show="headings", height=12)
        tree.heading("id", text="Student ID")
        tree.heading("name", text="Name")
        tree.heading("registered", text="Registered At")
        tree.column("id", width=130, anchor="center")
        tree.column("name", width=190, anchor="w")
        tree.column("registered", width=150, anchor="center")
        tree.pack(fill="both", expand=True, side="left")

        sb = ttk.Scrollbar(tf, orient="vertical", command=tree.yview)
        tree.configure(yscroll=sb.set)
        sb.pack(side="right", fill="y")

        def refresh():
            for r in tree.get_children():
                tree.delete(r)
            for sid, name, reg in self.db.get_students():
                tree.insert(
                    "", "end",
                    values=(sid, name, reg.replace("T", " ")),
                )

        refresh()

        bf = tk.Frame(dlg, bg=self.BG)
        bf.pack(pady=10)

        def add():
            s = simpledialog.askstring(
                "Add Student", "Enter Student ID:", parent=dlg
            )
            if not s:
                return
            n = simpledialog.askstring(
                "Add Student", "Enter Student Name:", parent=dlg
            )
            if not n:
                return
            self.db.add_student(s.strip(), n.strip())
            refresh()
            messagebox.showinfo(
                "Success",
                f"Student '{n.strip()}' (ID: {s.strip()}) registered.",
                parent=dlg,
            )

        def remove():
            sel = tree.selection()
            if not sel:
                messagebox.showwarning(
                    "Select", "Select a student to remove.", parent=dlg
                )
                return
            s = tree.item(sel[0])["values"][0]
            if messagebox.askyesno(
                "Confirm", f"Remove student ID '{s}'?", parent=dlg
            ):
                self.db.remove_student(str(s))
                refresh()

        tk.Button(
            bf, text="\u2795 Add Student", bg="#27ae60", fg="white",
            font=("Helvetica", 10, "bold"), relief="flat", padx=12, pady=5,
            command=add,
        ).pack(side="left", padx=8)

        tk.Button(
            bf, text="\u2796 Remove Student", bg="#e74c3c", fg="white",
            font=("Helvetica", 10, "bold"), relief="flat", padx=12, pady=5,
            command=remove,
        ).pack(side="left", padx=8)

        tk.Button(
            bf, text="Close", bg="#7f8c8d", fg="white",
            font=("Helvetica", 10, "bold"), relief="flat", padx=12, pady=5,
            command=dlg.destroy,
        ).pack(side="left", padx=8)

    # =================================================================== #
    #  HELPERS                                                              #
    # =================================================================== #
    @staticmethod
    def _fmt_dur(minutes):
        if minutes < 60:
            return f"{int(minutes)} min"
        h = int(minutes // 60)
        m = int(minutes % 60)
        return f"{h}h {m}m"

    def _on_close(self):
        for tid in (self._entry_timer_id, self._exit_timer_id):
            if tid:
                self.after_cancel(tid)
        self.db.close()
        self.destroy()


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app = ParkingApp()
    app.mainloop()
