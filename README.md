# 🚗 Smart Parking System with Real-Time CV Occupancy Detection

An integrated, lightweight smart parking solution designed for parking lot management. The system consists of a visual desktop dashboard for operators and a real-time computer vision slot occupancy detector using **OpenCV** and **DroidCam** (or any IP/MJPEG camera).

---

## 🛠️ Project Structure

*   **`parking_system.py`**: The Tkinter GUI desktop dashboard for monitoring slot availability, billing, simulation of entry/exit gates, and handling e-money payments/student ID taps.
*   **`parking_detector.py`**: The OpenCV-based computer vision script that connects to your IP camera stream, calibrates parking slot boundaries, detects whether a slot is occupied/empty, and automatically synchronizes the status to the system database.
*   **`parking.db`**: SQLite database storing the state of each parking slot, user sessions, rates, and transaction logs.
*   **`slots_config.json`**: Generated configuration file containing the coordinates (Regions of Interest) of the calibrated parking slots.
*   **`reference.jpg`**: Reference image captured during calibration of the empty parking lot.

---

## 🌟 Key Features

### 🖥️ Dashboard (`parking_system.py`)
*   **Symmetrical Two-Zone Layout**: Modeled after a real-life parking lot (60 Car slots, 100 Motorcycle slots) separated by a service lane.
*   **Dynamic Slot Status**: Updates immediately. Shows vehicle plate numbers, type, or "FREE" inside each slot.
*   **Flexible Payment Rules**:
    *   First **15 minutes free** (grace period).
    *   **Student ID Integration**: Student tap gets free parking (automatically sets fee to Rp 0).
    *   **E-Money/Flash Card** payment simulation for non-students.
*   **Gate Simulation**: Complete entry/exit gate animation with safety auto-close timers.

### 📷 Vision-Based Detector (`parking_detector.py`)
*   **IP Camera Integration**: Streams live video feed over network protocols (default: DroidCam standard stream).
*   **Interactive Calibration**: Draw, resize, clear, or undo bounding boxes directly on the live camera stream using mouse click-and-drag.
*   **Smart Detection**: Compares live video frame changes within the calibrated boxes against a reference image of the empty lot.
*   **Auto-Update Database**: When occupancy changes are detected, it updates the slot status in `parking.db` in real-time.

---

## ⚙️ Installation & Requirements

1.  **Python 3.x**
2.  Install the required packages:
    ```bash
    pip install opencv-python numpy
    ```

---

## 🚀 How to Use

### Step 1: Run the Dashboard
Start the parking lot monitoring dashboard first. This will initialize the local `parking.db` database.
```bash
python parking_system.py
```

### Step 2: Calibrate & Detect Slots
Connect a camera (e.g., your smartphone using DroidCam at `http://<your-phone-ip>:4747/video`).

1.  Start the detector script:
    ```bash
    python parking_detector.py
    ```
2.  By default, the script starts in **CALIBRATION Mode**:
    *   Select your slot type prefix (`C` for Car or `M` for Motorcycle) on startup.
    *   **Click and drag** to draw bounding boxes over the parking slots shown in the camera view. Bounding boxes are auto-assigned IDs (e.g. C1, C2, M1).
    *   Press **`U`** to undo the last drawn box.
    *   Press **`C`** to clear all boxes.
    *   Ensure the parking lot is completely empty, then press **`R`** to capture a reference image (`reference.jpg`).
    *   Press **`S`** to save your slot configuration to `slots_config.json`.
3.  Once calibrated, press **`Q`** (or `ESC`) to close the calibration window. The script will automatically reload into **DETECTION Mode** using your saved configuration.
4.  In **DETECTION Mode**:
    *   Watch the live feed. Bounding boxes will dynamically turn **Red** (occupied) or **Green** (empty).
    *   Press **`D`** to enable/disable syncing the live status updates straight to the SQLite `parking.db` database.
    *   Use **`+`** or **`-`** to fine-tune the pixel-change detection sensitivity in real-time.

---

## ⌨️ Control Keys Reference

| Key | Calibration Mode | Detection Mode |
|---|---|---|
| **`R`** | Capture/Reset Reference Image | Recapture Reference Image |
| **`S`** | Save configuration | — |
| **`U`** | Undo last slot box | — |
| **`C`** | Clear all slot boxes | — |
| **`+`** / **`-`** | — | Increase / Decrease Sensitivity |
| **`D`** | — | Enable / Disable Database Sync |
| **`Q`** / **`ESC`** | Quit Calibration Mode | Exit Script |

---

## ❓ Troubleshooting Connection (DroidCam)
If `parking_detector.py` fails to connect to your phone's camera stream:
1.  **Check IP & Port**: Open the DroidCam app on your phone. Make sure the Wifi IP and port match the input URL (e.g. `http://192.168.0.168:4747/video`).
2.  **Same Network**: Ensure your PC and phone are connected to the exact same Wi-Fi SSID.
3.  **One connection limit**: DroidCam only allows one connection at a time. Make sure the DroidCam desktop client or a web browser tab is not already using the camera.
4.  **AP Isolation**: Some routers prevent local wireless devices from talking to each other. Check your router settings for "AP Isolation" or "Client Isolation" and disable it.
