# Handoff Guide — Steam Deck to SC2 BLE Spoof Project

This document provides a summary of the current architecture, what is currently working, what needs to be done next, and the recommended approaches.

---

## 1. Project Goal & Current Architecture
We present the **Steam Deck** as a **Steam Controller 2026 (SC2 / Triton)** over **Bluetooth Low Energy** so that the host PC's Steam Client recognizes it natively and supports full Steam Input features (trackpads, gyro, haptics, back buttons).

### Architecture Overview
```
┌──────────────────────────────────────────────────────────┐
│                    Steam Deck (Peripheral)                 │
│                                                          │
│  ┌─────────────────────────────────────────────────────┐ │
│  │  main_l2cap.py                                      │ │
│  │  ├─ GLib main loop (BlueZ D-Bus advertising)        │ │
│  │  ├─ Agent1 (auto-confirm pairing via dbus-python)   │ │
│  │  └─ Raw L2CAP ATT server thread                     │ │
│  │     └─ Binds to C2:12:34:56:78:9A CID 4             │ │
│  │     └─ Handles ATT PDU exchange (MTU, discovery)    │ │
│  │     └─ Serves GATT database (82 attributes, 6 services)│ │
│  └─────────────────────────────────────────────────────┘ │
│                                                          │
│  BlueZ handles:                                          │
│  ├─ SMP pairing (kernel, CID 6)                          │
│  └─ LE advertising (LEAdvertisingManager1)               │
│                                                          │
│  Input Source: /dev/hidraw3 (Neptune HID state reports)   │
│  ├─ input_handler.py reads 64-byte Neptune reports       │
│  ├─ Maps buttons/sticks/triggers to SC2 format           │
│  └─ Sends as ATT notifications (Mouse/Keyboard/Gamepad)  │
└──────────────────────────────────────────────────────────┘
              │
              │ BLE (static random addr C2:12:34:56:78:9A)
              ▼
┌──────────────────────────────────────────────────────────┐
│                    Host PC (Central)                      │
│                                                          │
│  BlueZ hog-ll driver → /dev/hidrawN                      │
│   └─ Standard evdev events (eventN) for Mouse/Keyboard   │
│   └─ Steam Client reads raw hidraw for Steam Input       │
└──────────────────────────────────────────────────────────┘
```

---

## 2. What is Working
- **Raw L2CAP ATT Server (CID 4)**: Bypasses the SteamOS BlueZ GATT listener socket binding bug.
- **Just Works Pairing**: Auto-confirm via D-Bus `Agent1`.
- **GATT Database (74 attributes, 6 services)**: GAP, GATT, HID (0x1812) with CHR_REPORT for SC2 Custom + Haptic Output, Valve Custom HID Service, Battery, Device Information.
- **PnP ID**: USB-IF source (0x02), Valve VID (0x28DE), PID (0x1303).
- **Physical Deck Input Capture**: Reads Neptune controller `/dev/hidraw3` (64-byte HID reports).
- **Neptune Auto-Recovery**: Reopens hidraw on crash (2s delay, 10 retries).
- **45-byte SC2 Custom Reports**: Full Triton 32-bit button bitmask (verified from SDL3 `TritonButtons` enum), analog sticks, triggers, trackpads, IMU, force sensors. Sent on CHR_REPORT handles 0x0033 and 0x003c.
- **Standard HID Gamepad Reports**: 12-byte reports on handle `0x0012` with buttons, analog sticks (Y axis corrected), triggers. Host creates `/dev/input/eventN`.
- **Lizard Mode Mouse/Keyboard**: Relative mouse (right trackpad) and keyboard reports on handles `0x0019`/`0x001d`.
- **Synthetic SC2 Command Handler**: Feature Report 0x00 intercepts SC2 commands:
  - `0x83` GET_ATTRIBUTES - responds with synthetic device info (capabilities bitmask 0x4169bfff)
  - `0xAE` GET_SERIAL - responds with serial number
  - `0xBA` GET_CHIP_ID - responds with 15-byte chip ID
  - `0x87` SET_SETTINGS - acknowledges, stores register values
  - `0x89` GET_SETTINGS_VALUES - returns stored register values
  - `0x81` CLEAR_MAPPINGS - acknowledges
  - `0x85` SET_DEFAULT_DIGITAL_MAPPINGS - handles mode switch
  - Unknown commands echoed with zero payload
- **Haptic forwarding code ready** — `_on_haptic_write()` handler on handle 0x0019 correctly parses both 10-byte (with Report ID) and 9-byte (stripped) haptic payloads and forwards to Neptune. However, **the host never sends haptic output reports** — btmon capture confirmed zero ATT Write Command (0x52) packets. The issue is upstream in Steam/hog-ll.
- **Feature Report Proxy to Neptune**: Non-SC2 Feature Reports proxied to Neptune hardware via `ioctl`.
- **Steam Client SC2 Recognition**: Steam detects Type 10 (Neptune/SC2), ProductID 4867 (0x1303), loads `controller_neptune.vdf`, auto-registers controller. 45-byte SC2 Custom reports (Report ID 0x45) verified flowing to `/dev/hidrawN` via hexdump.
- **Bonding Key Mismatch Fix**: After Deck BT restart, stale LTK on host causes `[Errno 38] ENOSYS` on `conn.recv()`. Fix: `bluetoothctl remove C2:12:34:56:78:9A` then re-pair.
- **Comprehensive Diagnostic Logging** (`[DIAG]` tagged).

---

## 3. What Needs to be Done

### 1. Fix SET_SETTINGS Register 0x09 Verification Loop (PRIMARY BLOCKER)
- **Status**: This is NOT a haptics issue — it blocks ALL functionality (input, gyro, trackpads, haptics) because controller registration never completes. Steam sends SET_SETTINGS 0x09 (lizard mode OFF) and **the verification read never happens** — zero ATT Read Requests follow the SET_SETTINGS write. However, the full handshake DOES work: GET_ATTRIBUTES (0x83), 0xf2, GET_SERIAL (0xAE) all get write-then-read cycles (BlueZ sends real ATT Read Requests 0x0a to handle 0x0024). This proves the verification mechanism works — it just doesn't fire for SET_SETTINGS specifically. **The state machine at 0x010d466b should toggle between SEND and VERIFY, but never reaches VERIFY for SET_SETTINGS.** Root cause is likely that SET_SETTINGS uses a different IPC path than the verification read, or the state machine has a condition that prevents the toggle. **Known bug in response format**: `payload_len + 1` (line 464, main_l2cap.py) should be `payload_len` — length byte is 0x04 instead of 0x03.
- **RE findings**: The SET_SETTINGS buffer format is `[0x01, 0x87, 0x03, register, value_lo, value_hi, ...]`. Register 0x09 = SETTING_LIZARD_MODE, value 0 = LIZARD_MODE_OFF. Lizard mode must be OFF for haptics to work. The verification reads FR 0x00 back and does a byte-by-byte comparison of the echoed command bytes.
- **What to try next**:
  1. Investigate why the state machine never reaches VERIFY for SET_SETTINGS — trace the binary at 0x010d4e1a to find the condition that prevents the toggle
  2. Check if SET_SETTINGS uses a different IPC path than the verification read
  3. Fix the `payload_len + 1` → `payload_len` bug (line 464, main_l2cap.py)
  4. Check if the ControllerDetails_tE.ready_flag (offset 0x3c) is the real blocker

### 2. `set_report_cb()` ATT Error (NOT THE ROOT CAUSE)
- **Status**: The error is `ATT_ERR_INSUFFICIENT_ENCRYPTION_KEY_SIZE (0x0C)`, NOT 0x0E (Unlikely Error). This is a transient error — BlueZ clears the slot, replies to UHID, and continues. No degraded state, no blocked queue, no state machine affected. GET_REPORT works fine after the error. **This is NOT the root cause of the SET_SETTINGS loop.**
- **What was confirmed**: BlueZ's HOG profile sends the error to UHID, which passes it to the kernel, which passes it to Steam. But the error doesn't block subsequent operations.

### 3. Haptic Feedback (HOST NOT SENDING)
- **Status**: The haptic forwarding code is ready and correct — `_on_haptic_write()` on handle 0x0019 parses both 10-byte and 9-byte payloads. However, **the host never sends haptic output reports** — btmon capture confirmed zero ATT Write Command (0x52) packets during a test session. The issue is upstream in Steam/hog-ll.
- **RE findings**: Haptics use `SDL_hid_write()` (output reports, NOT feature reports). Lizard mode must be OFF for haptics to work. The SET_SETTINGS 0x09 loop may be blocking haptics because Steam thinks lizard mode is still enabled.
- **What to try next**:
  1. Fix the SET_SETTINGS 0x09 loop — lizard mode must be OFF for haptics
  2. Get a real SC2 btmon capture to see the correct verification response

### 4. Dual Trackpads & IMU (Gyro/Accel) Forwarding
- **Status**: 45-byte SC2 Custom report with trackpad X/Y, IMU (accel/gyro), and force sensors is **already implemented** in `input_handler.py`. The data flows correctly from Neptune HID → SC2 report.
- **Remaining**: Steam may need specific settings enabled to activate gyro/trackpad features (registers 0x27 IMU_MODE, etc.).

### 5. Auto-Reconnect Daemon
- **Status**: Advertising refresh on disconnect is **already implemented** in `main_l2cap.py:_schedule_adv_refresh()`.
- **Remaining**: Ensure clean re-advertising after disconnects without manual intervention.
- **Root cause hypothesis**: The `set_report_cb()` ATT error (BlueZ returns 0x0E to a SET_REPORT Write Request) puts the HOG profile in a broken state where it cannot send feature report reads. This explains why the verification never reads FR 0x00.
- **Key commands in the SC2 protocol flow**:
  1. `0x83` GET_ATTRIBUTES → response: `[0x83, 0x2D, 9 attributes x 5 bytes, padding]`
  2. `0xF2` Unknown (1-byte payload varies: 0x01, 0x02, etc.) → response: `[0xF2, 0x00, zeros]` (STILL WRONG — needs real SC2 capture)
  3. `0xAE` GET_SERIAL → response: `[0xAE, 0x14, 0x01, serial_ascii, padding]`
  4. `0xBA` GET_CHIP_ID → response: `[0xBA, 0x11, 0x00, 15-byte chip_id, padding]`
  5. `0x87` SET_SETTINGS → write-only (configures registers), now includes ack notification
  6. `0x89` GET_SETTINGS_VALUES → response: stored register values
  7. `0xC1`/`0xDC`/0xE2` Unknown → echo with zero payload
  8. `0x81` CLEAR_MAPPINGS → write-only (exits lizard mode)
  9. `0x85` SET_DEFAULT_DIGITAL_MAPPINGS → write-only (enters gamepad mode)
  10. `0x8D` SET_CONTROLLER_MODE → mode switch (lizard ↔ Steam Input)

### 5. Reverse Engineering Findings (from steamclient.so)
- **ControllerDetails_tE**: 84 bytes (0x54), ready_flag at offset 0x3c must be 1. Set by QueueFetchingControllerDetails at 0x01092820. Fields come from controller object offsets 0x84-0xd4.
- **Product ID check**: 0x1303 is in recognized range (0x1302-0x1305). Other recognized types: 0x1142, 0x1220, 0x1201-0x1206, 0x1101-0x1102.
- **Haptic path**: Uses SDL_hid_write() (output reports), NOT SDL_hid_send_feature_report(). Report ID 0x80, 10 bytes. Lizard mode must be OFF for haptics to work.
- **SET_SETTINGS format**: `[0x01, 0x87, 0x03, register, value_lo, value_hi, ...]`. Register 0x09 = SETTING_LIZARD_MODE, value 0 = OFF.
- **0xf2 command**: Per-category capability query dispatched via switch/case. Exact response format unknown.
- **RE session files**: ~/steamclient-reverse-session/ contains findings.md, functions/, notes/

---

## 4. How to Run & Verify

### Start the Service on the Deck
```bash
# 1. Restart bluetooth and apply custom LE config
echo <DECK_PASSWORD> | sudo -S systemctl stop sc2-hogp bluetooth
echo <DECK_PASSWORD> | sudo -S systemctl start bluetooth
sleep 2
echo <DECK_PASSWORD> | sudo -S python3 /tmp/config_bt.py

# 2. Run the deployment script to copy latest code and start the service
./scripts/deploy.sh
```

### Connect on the Host
```bash
# Connect using bluetoothctl (avoid 'pair' to prevent BR/EDR classic bonding timeouts)
bluetoothctl connect C2:12:34:56:78:9A
```

### Listen to Input Events on the Host
```bash
# Find and monitor relative mouse movement and keypress events
echo <HOST_SUDO_PASSWORD> | sudo -S python3 -u scratch/listen_events.py
```
