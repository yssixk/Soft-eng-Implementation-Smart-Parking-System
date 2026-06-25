#!/usr/bin/env python3
"""
Smart Parking System — GUI Layer
----------------------------------
ParkingApp(tk.Tk) — main application window with:
- Car zone (left), Service lane (center), Motorcycle zone (right)
- Entry/Exit gate simulation
- Camera detector control panel
- Plate detection integration at entry
- Auto-refresh from database
"""

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from datetime import datetime
import threading
import os
import json

from config import (
    CAR_SLOTS, MOTOR_SLOTS, CURRENCY, GRACE_PERIOD_MINUTES,
    CAR_RATE_FIRST_HOUR, CAR_RATE_ADDITIONAL,
    MOTOR_RATE_FIRST_HOUR, MOTOR_RATE_ADDITIONAL,
    CAR_GATE_OPEN_DURATION, MOTOR_GATE_OPEN_DURATION,
    DIFF_THRESHOLD, OCCUPIED_PERCENT,
    UPDATE_INTERVAL_SEC, SLOTS_CONFIG, REFERENCE_IMAGE, DB_PATH,
    DEFAULT_DROIDCAM_URL,
)
from database import ParkingDB, calculate_fee


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
    SLOT_DETECTED = "#e67e22"      # amber for camera-detected
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

        # detector state
        self._detector_thread = None
        self._detector_stop = threading.Event()
        self._detector_running = False

        self._build_header()
        self._build_body()
        self._build_gates()
        self._build_detector_panel()
        self._build_footer()

        self.refresh_slots()
        self.refresh_history()
        self.after(1000, self._tick)
        self.after(3000, self._auto_refresh)
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
    def _build_detector_panel(self):
        """Camera Detector control panel."""
        panel = tk.LabelFrame(
            self,
            text="  \U0001f4f7  Camera Detector  ",
            bg="#34495e",
            fg="white",
            font=("Helvetica", 10, "bold"),
            padx=8,
            pady=4,
        )
        panel.pack(fill="x", padx=8, pady=(0, 4))

        row = tk.Frame(panel, bg="#34495e")
        row.pack(fill="x")

        # Parking camera source entry (for slot occupancy detection)
        tk.Label(
            row, text="Parking camera source:", bg="#34495e", fg="white",
            font=("Helvetica", 9),
        ).pack(side="left", padx=(0, 5))

        self.occupancy_cam_url_var = tk.StringVar(value=DEFAULT_DROIDCAM_URL)
        occ_url_entry = tk.Entry(
            row, textvariable=self.occupancy_cam_url_var, width=35,
            font=("Helvetica", 9),
        )
        occ_url_entry.pack(side="left", padx=(0, 10))

        # Buttons
        self.start_det_btn = tk.Button(
            row, text="\u25b6 Start Detection", bg="#27ae60", fg="white",
            font=("Helvetica", 9, "bold"), relief="flat", padx=8, pady=3,
            command=self._start_detector,
        )
        self.start_det_btn.pack(side="left", padx=3)

        self.stop_det_btn = tk.Button(
            row, text="\u23f9 Stop", bg="#e74c3c", fg="white",
            font=("Helvetica", 9, "bold"), relief="flat", padx=8, pady=3,
            command=self._stop_detector, state="disabled",
        )
        self.stop_det_btn.pack(side="left", padx=3)

        tk.Button(
            row, text="\U0001f527 Calibrate", bg="#2980b9", fg="white",
            font=("Helvetica", 9, "bold"), relief="flat", padx=8, pady=3,
            command=self._open_calibration,
        ).pack(side="left", padx=3)

        tk.Button(
            row, text="\U0001f4f8 Capture Ref", bg="#8e44ad", fg="white",
            font=("Helvetica", 9, "bold"), relief="flat", padx=8, pady=3,
            command=self._capture_reference,
        ).pack(side="left", padx=3)



        # Status label
        self.det_status_lbl = tk.Label(
            row, text="\U0001f534 STOPPED", bg="#34495e", fg="#e74c3c",
            font=("Helvetica", 9, "bold"),
        )
        self.det_status_lbl.pack(side="right", padx=10)

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
    #  PLATE INPUT DIALOG                                                    #
    # =================================================================== #
    def _detect_plate_dialog(self):
        """Ask the user to type a license plate number.
        Returns the plate string, or None if cancelled."""
        plate = simpledialog.askstring(
            "Plate Number", "Enter license plate number:"
        )
        if plate:
            plate = plate.strip().upper()
            if len(plate) < 2:
                messagebox.showwarning(
                    "Invalid Plate",
                    "Plate number is too short. Please enter a valid plate.",
                )
                return None
        return plate if plate else None

    # =================================================================== #
    #  SLOT PICKER DIALOG                                                    #
    # =================================================================== #
    def _pick_slot_dialog(self, vehicle_type):
        """Show a dialog with a grid of slots. User clicks to pick one.
        Returns the chosen slot_id, or None if cancelled.

        Only shows slots of the given vehicle_type.
        FREE slots are green and clickable; OCCUPIED slots are red/disabled.
        """
        dlg = tk.Toplevel(self)
        vname = "Car" if vehicle_type == "car" else "Motorcycle"
        dlg.title(f"\U0001f17f\ufe0f  Pick a {vname} Slot")
        dlg.configure(bg="#2c3e50")
        dlg.transient(self)
        dlg.grab_set()
        dlg.resizable(True, True)

        result = [None]

        # Header
        tk.Label(
            dlg, text=f"Select a {vname} Parking Slot",
            bg="#2c3e50", fg="white",
            font=("Helvetica", 13, "bold"),
        ).pack(pady=(12, 4))

        tk.Label(
            dlg, text="\u2705 Green = FREE (click to select)    \u274c Red = OCCUPIED",
            bg="#2c3e50", fg="#bdc3c7",
            font=("Helvetica", 9),
        ).pack(pady=(0, 8))

        # Scrollable frame
        container = tk.Frame(dlg, bg="#2c3e50")
        container.pack(fill="both", expand=True, padx=10, pady=(0, 5))

        canvas = tk.Canvas(container, bg="#2c3e50", highlightthickness=0)
        vsb = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg="#2c3e50")
        inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        def _scroll(event):
            canvas.yview_scroll(-1 * (event.delta // 120), "units")
        canvas.bind("<MouseWheel>", _scroll)
        inner.bind("<MouseWheel>", _scroll)

        # Get slot data from DB
        all_slots = self.db.get_slots(vehicle_type)
        cols = 6 if vehicle_type == "car" else 10

        for idx, (slot_id, occupied) in enumerate(all_slots):
            r, c = divmod(idx, cols)

            def pick(sid=slot_id):
                result[0] = sid
                dlg.destroy()

            if occupied:
                # Check if there's an active session to show plate
                session = self.db.active_session_for_slot(slot_id)
                if session:
                    plate = session[1]
                    is_stu = session[4]
                    tag = " \U0001f393" if is_stu else ""
                    txt = f"{slot_id}\n{plate}{tag}"
                    color = "#f39c12" if is_stu else (
                        self.SLOT_OCC_CAR if vehicle_type == "car"
                        else self.SLOT_OCC_MOTOR
                    )
                else:
                    txt = f"{slot_id}\n\U0001f4f7 DETECTED"
                    color = self.SLOT_DETECTED

                btn = tk.Button(
                    inner, text=txt, width=8, height=2,
                    bg=color, fg="white", disabledforeground="#cccccc",
                    font=("Helvetica", 7, "bold"), relief="flat",
                    state="disabled",
                )
            else:
                color = (self.SLOT_FREE_CAR if vehicle_type == "car"
                         else self.SLOT_FREE_MOTOR)
                btn = tk.Button(
                    inner, text=f"{slot_id}\nFREE", width=8, height=2,
                    bg=color, fg="white", activebackground="#1abc9c",
                    font=("Helvetica", 7, "bold"), relief="flat",
                    command=pick,
                )

            btn.grid(row=r, column=c, padx=2, pady=2)
            # Enable scroll on buttons too
            btn.bind("<MouseWheel>", _scroll)

        # Cancel button
        tk.Button(
            dlg, text="\u274c Cancel", bg="#e74c3c", fg="white",
            font=("Helvetica", 10, "bold"), relief="flat", padx=15, pady=6,
            command=dlg.destroy,
        ).pack(pady=(5, 12))

        # Set window size based on content
        if vehicle_type == "car":
            dlg.geometry("580x500")
        else:
            dlg.geometry("850x550")

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

        # Plate input
        plate = self._detect_plate_dialog()
        if not plate:
            return

        # Let user pick their slot
        slot = self._pick_slot_dialog(vtype)
        if not slot:
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

        # Plate input
        plate = self._detect_plate_dialog()
        if not plate:
            return

        # Let user pick their slot
        slot = self._pick_slot_dialog(vtype)
        if not slot:
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
    #  CAMERA DETECTOR INTEGRATION                                          #
    # =================================================================== #
    def _start_detector(self):
        """Start parking slot occupancy detection in a background thread."""
        if self._detector_running:
            return

        # Check prerequisites
        if not os.path.exists(SLOTS_CONFIG):
            messagebox.showwarning(
                "No Slots Configured",
                "No slot configuration found.\n"
                "Please calibrate first using the \U0001f527 Calibrate button.",
            )
            return

        if not os.path.exists(REFERENCE_IMAGE):
            messagebox.showwarning(
                "No Reference Image",
                "No reference image found.\n"
                "Please capture a reference image first.",
            )
            return

        self._detector_stop.clear()
        self._detector_running = True
        self.start_det_btn.config(state="disabled")
        self.stop_det_btn.config(state="normal")

        # Load slot count for status display
        try:
            with open(SLOTS_CONFIG, "r") as f:
                slots = json.load(f)
            slot_count = len(slots)
        except Exception:
            slot_count = "?"

        self.det_status_lbl.config(
            text=f"\U0001f7e2 DETECTING ({slot_count} slots)",
            fg="#2ecc71",
        )

        self._detector_thread = threading.Thread(
            target=self._detector_loop, daemon=True
        )
        self._detector_thread.start()

    def _stop_detector(self):
        """Stop the occupancy detection thread."""
        self._detector_stop.set()
        self._detector_running = False
        self.start_det_btn.config(state="normal")
        self.stop_det_btn.config(state="disabled")
        self.det_status_lbl.config(
            text="\U0001f534 STOPPED", fg="#e74c3c",
        )

    def _detector_loop(self):
        """Background thread: connect to camera, detect slot occupancy,
        write results to parking.db periodically."""
        import cv2
        import numpy as np
        import sqlite3
        import time

        source = self.occupancy_cam_url_var.get()

        # Load config
        try:
            with open(SLOTS_CONFIG, "r") as f:
                slots = json.load(f)
        except Exception as e:
            self.after(0, lambda: messagebox.showerror(
                "Config Error", f"Cannot load slots_config.json:\n{e}"
            ))
            self.after(0, self._stop_detector)
            return

        reference = cv2.imread(REFERENCE_IMAGE)
        if reference is None:
            self.after(0, lambda: messagebox.showerror(
                "Reference Error", "Cannot load reference.jpg"
            ))
            self.after(0, self._stop_detector)
            return

        ref_gray = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
        ref_gray = cv2.GaussianBlur(ref_gray, (21, 21), 0)

        cap = cv2.VideoCapture(source)
        if not cap.isOpened():
            self.after(0, lambda: messagebox.showerror(
                "Camera Error",
                f"Cannot open camera at: {source}\n"
                "Make sure DroidCam is running.",
            ))
            self.after(0, self._stop_detector)
            return

        last_db_update = 0

        while not self._detector_stop.is_set():
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.1)
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (21, 21), 0)

            statuses = {}
            for slot in slots:
                x1, y1 = slot["x1"], slot["y1"]
                x2, y2 = slot["x2"], slot["y2"]

                h, w = gray.shape[:2]
                x1c, y1c = max(0, x1), max(0, y1)
                x2c, y2c = min(w, x2), min(h, y2)
                if x2c <= x1c or y2c <= y1c:
                    continue

                roi_ref = ref_gray[y1c:y2c, x1c:x2c]
                roi_cur = gray[y1c:y2c, x1c:x2c]
                if roi_ref.shape != roi_cur.shape:
                    continue

                diff = cv2.absdiff(roi_ref, roi_cur)
                _, thresh = cv2.threshold(
                    diff, DIFF_THRESHOLD, 255, cv2.THRESH_BINARY
                )
                total_px = thresh.shape[0] * thresh.shape[1]
                changed_px = cv2.countNonZero(thresh)
                change_pct = (changed_px / total_px) * 100 if total_px > 0 else 0

                statuses[slot["id"]] = change_pct > OCCUPIED_PERCENT

            # Update DB periodically
            now = time.time()
            if (now - last_db_update) >= UPDATE_INTERVAL_SEC:
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
                except Exception:
                    pass
                last_db_update = now

            time.sleep(0.05)  # ~20fps

        cap.release()

    def _open_calibration(self):
        """Open a Tkinter-based calibration window.

        Uses a Canvas with live camera feed for drawing slot rectangles.
        No cv2.imshow/namedWindow needed — works with headless OpenCV.
        """
        import cv2
        import time as _time
        from PIL import Image, ImageTk

        source = self.occupancy_cam_url_var.get()
        if source.isdigit():
            source = int(source)

        # Ask for slot prefix
        prefix = simpledialog.askstring(
            "Slot Prefix",
            "Enter slot ID prefix:\n"
            "  C = Car slots (C1, C2, ...)\n"
            "  M = Motorcycle slots (M1, M2, ...)",
            initialvalue="C",
        )
        if not prefix:
            return
        prefix = prefix.strip().upper() or "C"

        # Load existing slots
        slots = []
        if os.path.exists(SLOTS_CONFIG):
            try:
                with open(SLOTS_CONFIG, "r") as f:
                    slots = json.load(f)
            except Exception:
                pass

        # Find the next number for this prefix
        existing_nums = [
            int(s["id"][len(prefix):])
            for s in slots
            if s["id"].startswith(prefix) and s["id"][len(prefix):].isdigit()
        ]
        next_num = [max(existing_nums, default=0) + 1]

        # --- Build calibration dialog ---
        dlg = tk.Toplevel(self)
        dlg.title("\U0001f527 Calibrate Parking Slots")
        dlg.configure(bg="#2c3e50")
        dlg.transient(self)
        dlg.resizable(True, True)

        # Info bar
        info_var = tk.StringVar(value=f"Prefix: {prefix} | Slots: {len(slots)} | Drag to draw rectangles")
        tk.Label(
            dlg, textvariable=info_var, bg="#34495e", fg="white",
            font=("Helvetica", 10, "bold"), anchor="w", padx=10, pady=5,
        ).pack(fill="x")

        # Canvas for camera + drawing
        canvas = tk.Canvas(dlg, bg="#1a1a2e", width=640, height=480, cursor="crosshair")
        canvas.pack(padx=5, pady=5)

        # Button bar
        btn_frame = tk.Frame(dlg, bg="#2c3e50")
        btn_frame.pack(fill="x", padx=5, pady=(0, 5))

        # Drawing state
        draw_start = [None]
        temp_rect_id = [None]
        stop_cam = threading.Event()
        current_frame = [None]
        scale_info = [1.0, 0, 0]  # scale, display_w, display_h

        def update_info():
            info_var.set(
                f"Prefix: {prefix} | Slots: {len(slots)} | "
                f"Next: {prefix}{next_num[0]}"
            )

        def on_mouse_down(event):
            draw_start[0] = (event.x, event.y)

        def on_mouse_drag(event):
            if draw_start[0] is None:
                return
            if temp_rect_id[0]:
                canvas.delete(temp_rect_id[0])
            temp_rect_id[0] = canvas.create_rectangle(
                draw_start[0][0], draw_start[0][1], event.x, event.y,
                outline="#00ffff", width=2, dash=(4, 4),
            )

        def on_mouse_up(event):
            if draw_start[0] is None:
                return
            if temp_rect_id[0]:
                canvas.delete(temp_rect_id[0])
                temp_rect_id[0] = None

            sx, sy = draw_start[0]
            ex, ey = event.x, event.y
            draw_start[0] = None

            # Convert canvas coords back to original frame coords
            sc = scale_info[0]
            if sc <= 0:
                return
            x1 = int(min(sx, ex) / sc)
            y1 = int(min(sy, ey) / sc)
            x2 = int(max(sx, ex) / sc)
            y2 = int(max(sy, ey) / sc)

            # Ignore tiny accidental clicks
            if (x2 - x1) < 15 or (y2 - y1) < 15:
                return

            slot_id = f"{prefix}{next_num[0]}"
            slots.append({"id": slot_id, "x1": x1, "y1": y1, "x2": x2, "y2": y2})
            next_num[0] += 1
            update_info()

        canvas.bind("<ButtonPress-1>", on_mouse_down)
        canvas.bind("<B1-Motion>", on_mouse_drag)
        canvas.bind("<ButtonRelease-1>", on_mouse_up)

        def save_config():
            with open(SLOTS_CONFIG, "w") as f:
                json.dump(slots, f, indent=2)
            messagebox.showinfo(
                "Saved",
                f"Saved {len(slots)} slot(s) to {SLOTS_CONFIG}",
                parent=dlg,
            )

        def capture_ref():
            if current_frame[0] is not None:
                cv2.imwrite(REFERENCE_IMAGE, current_frame[0])
                messagebox.showinfo(
                    "Reference Captured",
                    f"Reference image saved to:\n{REFERENCE_IMAGE}\n\n"
                    "Make sure the parking lot was EMPTY!",
                    parent=dlg,
                )

        def undo_last():
            if slots:
                removed = slots.pop()
                next_num[0] -= 1
                update_info()

        def clear_all():
            if messagebox.askyesno("Clear All", "Remove ALL slots?", parent=dlg):
                slots.clear()
                next_num[0] = 1
                update_info()

        tk.Button(
            btn_frame, text="\U0001f4be Save", bg="#27ae60", fg="white",
            font=("Helvetica", 9, "bold"), relief="flat", padx=10, pady=4,
            command=save_config,
        ).pack(side="left", padx=3)

        tk.Button(
            btn_frame, text="\U0001f4f8 Capture Ref", bg="#8e44ad", fg="white",
            font=("Helvetica", 9, "bold"), relief="flat", padx=10, pady=4,
            command=capture_ref,
        ).pack(side="left", padx=3)

        tk.Button(
            btn_frame, text="\u21a9 Undo", bg="#e67e22", fg="white",
            font=("Helvetica", 9, "bold"), relief="flat", padx=10, pady=4,
            command=undo_last,
        ).pack(side="left", padx=3)

        tk.Button(
            btn_frame, text="\U0001f5d1 Clear All", bg="#e74c3c", fg="white",
            font=("Helvetica", 9, "bold"), relief="flat", padx=10, pady=4,
            command=clear_all,
        ).pack(side="left", padx=3)

        tk.Button(
            btn_frame, text="\u274c Close", bg="#7f8c8d", fg="white",
            font=("Helvetica", 9, "bold"), relief="flat", padx=10, pady=4,
            command=dlg.destroy,
        ).pack(side="right", padx=3)

        # --- Camera feed thread ---
        def camera_loop():
            try:
                cap = cv2.VideoCapture(source)
                if not cap.isOpened():
                    try:
                        dlg.after(0, lambda: info_var.set(
                            f"\u274c Cannot connect to camera at: {source}"
                        ))
                    except tk.TclError:
                        pass
                    return

                # Warm up
                for _ in range(10):
                    cap.read()
                    _time.sleep(0.03)

                while not stop_cam.is_set():
                    ret, frame = cap.read()
                    if not ret:
                        _time.sleep(0.05)
                        continue

                    current_frame[0] = frame.copy()
                    display = frame.copy()

                    # Load reference for occupancy detection
                    ref_img = None
                    if os.path.exists(REFERENCE_IMAGE):
                        ref_img = cv2.imread(REFERENCE_IMAGE)

                    if ref_img is not None and len(slots) > 0:
                        # --- Occupancy detection (same logic as parking_detector.py) ---
                        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                        gray = cv2.GaussianBlur(gray, (21, 21), 0)
                        ref_gray = cv2.cvtColor(ref_img, cv2.COLOR_BGR2GRAY)
                        ref_gray = cv2.GaussianBlur(ref_gray, (21, 21), 0)

                        free_count = 0
                        occ_count = 0

                        for s in slots:
                            x1, y1, x2, y2 = s["x1"], s["y1"], s["x2"], s["y2"]
                            fh, fw = gray.shape[:2]
                            x1c, y1c = max(0, x1), max(0, y1)
                            x2c, y2c = min(fw, x2), min(fh, y2)
                            if x2c <= x1c or y2c <= y1c:
                                continue

                            roi_ref = ref_gray[y1c:y2c, x1c:x2c]
                            roi_cur = gray[y1c:y2c, x1c:x2c]
                            if roi_ref.shape != roi_cur.shape:
                                continue

                            diff = cv2.absdiff(roi_ref, roi_cur)
                            _, thresh = cv2.threshold(diff, DIFF_THRESHOLD, 255, cv2.THRESH_BINARY)
                            total_px = thresh.shape[0] * thresh.shape[1]
                            changed_px = cv2.countNonZero(thresh)
                            change_pct = (changed_px / total_px) * 100 if total_px > 0 else 0

                            is_occupied = change_pct > OCCUPIED_PERCENT

                            if is_occupied:
                                occ_count += 1
                            else:
                                free_count += 1

                            # Color: RED = occupied, GREEN = free
                            color = (0, 0, 255) if is_occupied else (0, 200, 0)
                            label = "OCCUPIED" if is_occupied else "FREE"

                            # Semi-transparent fill
                            overlay = display.copy()
                            cv2.rectangle(overlay, (x1c, y1c), (x2c, y2c), color, -1)
                            cv2.addWeighted(overlay, 0.3, display, 0.7, 0, display)

                            # Border
                            cv2.rectangle(display, (x1c, y1c), (x2c, y2c), color, 2)

                            # Slot ID + status label
                            cv2.putText(
                                display, f"{s['id']}: {label}",
                                (x1c, y1c - 8),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2,
                            )
                            # Change percentage
                            cv2.putText(
                                display, f"{change_pct:.0f}%",
                                (x1c + 4, y2c - 8),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1,
                            )

                        # Update info bar with occupancy counts
                        try:
                            dlg.after(0, lambda f=free_count, o=occ_count: info_var.set(
                                f"Prefix: {prefix} | Slots: {len(slots)} | "
                                f"\u2705 FREE: {f}  \u274c OCC: {o} | "
                                f"Next: {prefix}{next_num[0]}"
                            ))
                        except tk.TclError:
                            pass
                    else:
                        # No reference — just draw green outlines
                        for s in slots:
                            clr = (0, 255, 0) if s["id"].startswith(prefix) else (255, 200, 0)
                            cv2.rectangle(display, (s["x1"], s["y1"]), (s["x2"], s["y2"]), clr, 2)
                            cv2.putText(
                                display, s["id"], (s["x1"] + 2, s["y1"] + 16),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, clr, 1,
                            )

                    # Convert to Tkinter image
                    display_rgb = cv2.cvtColor(display, cv2.COLOR_BGR2RGB)
                    h, w = display_rgb.shape[:2]
                    # Scale to fit canvas
                    cw = canvas.winfo_width() or 640
                    ch = canvas.winfo_height() or 480
                    sc = min(cw / w, ch / h, 1.0)
                    nw, nh = int(w * sc), int(h * sc)
                    scale_info[0] = sc
                    scale_info[1] = nw
                    scale_info[2] = nh

                    if sc < 1.0:
                        display_rgb = cv2.resize(display_rgb, (nw, nh))

                    img = Image.fromarray(display_rgb)
                    imgtk = ImageTk.PhotoImage(image=img)

                    try:
                        canvas.imgtk = imgtk
                        canvas.delete("bg")
                        canvas.create_image(0, 0, anchor="nw", image=imgtk, tags="bg")
                        canvas.tag_lower("bg")
                    except tk.TclError:
                        break

                    _time.sleep(0.03)

                cap.release()
            except Exception:
                pass

        cam_thread = threading.Thread(target=camera_loop, daemon=True)
        cam_thread.start()

        def on_close():
            stop_cam.set()
            dlg.destroy()

        dlg.protocol("WM_DELETE_WINDOW", on_close)
        update_info()
        self.wait_window(dlg)
        stop_cam.set()

    def _capture_reference(self):
        """Capture a frame from the webcam as the reference image.

        DroidCam network streams need a warmup — the first few reads
        often return empty frames, so we discard several before capturing.
        """
        import cv2
        import time

        source = self.occupancy_cam_url_var.get()
        if source.isdigit():
            source = int(source)
        cap = cv2.VideoCapture(source)
        if not cap.isOpened():
            messagebox.showerror(
                "Camera Error",
                f"Cannot open camera at: {source}\n"
                "Make sure DroidCam is running and the URL is correct.",
            )
            return

        # Warm up: discard first frames while the stream buffers
        frame = None
        for _ in range(30):  # try up to 30 frames (~1 second)
            ret, f = cap.read()
            if ret and f is not None:
                frame = f
            time.sleep(0.03)

        cap.release()

        if frame is not None:
            cv2.imwrite(REFERENCE_IMAGE, frame)
            messagebox.showinfo(
                "Reference Captured",
                f"Reference image saved to:\n{REFERENCE_IMAGE}\n\n"
                "Make sure the parking lot was EMPTY when captured!",
            )
        else:
            messagebox.showerror(
                "Capture Failed",
                "Could not read a frame from the camera.\n"
                "Try again — make sure DroidCam is active.",
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
                if session:
                    plate = session[1]
                    is_stu = session[4]
                    if is_stu:
                        color = "#f39c12"  # orange for student
                    else:
                        color = self.SLOT_OCC_CAR if is_car else self.SLOT_OCC_MOTOR
                    tag = " \U0001f393" if is_stu else ""
                    btn.config(text=f"{slot_id}\n{plate}{tag}", bg=color)
                else:
                    # Camera-detected (no session)
                    btn.config(
                        text=f"{slot_id}\n\U0001f4f7 DETECTED",
                        bg=self.SLOT_DETECTED,
                    )
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

    def _auto_refresh(self):
        """Auto-refresh slot buttons every 3 seconds to pick up
        changes from the background detector thread."""
        self.refresh_slots()
        self.after(3000, self._auto_refresh)

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
        # Stop detector if running
        if self._detector_running:
            self._detector_stop.set()
        for tid in (self._entry_timer_id, self._exit_timer_id):
            if tid:
                self.after_cancel(tid)
        self.db.close()
        self.destroy()
