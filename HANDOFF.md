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
- **GATT Database (82 attributes, 6 services)**: GAP, GATT, HID (0x1812) with CHR_REPORT for SC2 Custom, Valve Custom HID Service, Battery, Device Information.
- **PnP ID**: USB-IF source (0x02), Valve VID (0x28DE), PID (0x1303).
- **Physical Deck Input Capture**: Reads Neptune controller `/dev/hidraw3` (64-byte HID reports).
- **Neptune Auto-Recovery**: Reopens hidraw on crash (2s delay, 10 retries).
- **Standard HID Gamepad Reports**: 12-byte reports on handle `0x0012` with buttons, analog sticks (Y axis corrected), triggers. Host creates `/dev/input/eventN` — **KDE Game Controller and Steam detect this as a generic controller**.
- **Lizard Mode Mouse/Keyboard**: Relative mouse (right trackpad) and keyboard reports on handles `0x0019`/`0x001d`.
- **Synthetic SC2 Command Handler**: Feature Report 0x00 intercepts SC2 commands (0x83 GET_ATTRIBUTES, 0xAE GET_SERIAL, 0x87 SET_SETTINGS, 0x81 CLEAR_MAPPINGS) with correct byte-level response format matching real device captures from InputPlumber.
- **Steam Client SC2 Recognition**: Steam detects Type 10 (Neptune/SC2), ProductID 4867 (0x1303), loads `controller_neptune.vdf`, auto-registers controller. Vendor-defined HID Report Map entries removed (Usage Page 0xFF00/0xFF01) to avoid generic device detection.
- **Comprehensive Diagnostic Logging** (`[DIAG]` tagged).

---

## 3. What Needs to be Done

### 1. Steam Client Input Delivery (No Input Despite SC2 Recognition)
- **Status**: Steam now recognizes the device as **Type 10 (Neptune/SC2)** with ProductID 4867 (0x1303), loads `controller_neptune.vdf` configs, and auto-registers the controller. However, **no input events reach Steam** — the controller shows in Steam Settings but buttons/sticks do nothing.
- **Root cause**: Steam reads input via `SDL_hid_read()` on the hidraw device (standard HID reports on handle 0x0012). The 12-byte gamepad reports we send are standard HID gamepad format, but Steam's SC2 driver expects the reports to match what a real SC2 sends — which is a different format (45-byte/47-byte SC2 Custom reports, NOT standard HID gamepad reports).

**Critical finding — Steam's actual communication path (from ATT logs):**

```
Phase 1: Service Discovery
  Read PnP ID (VID=0x28DE, PID=0x1303) → identifies as SC2
  Read HID Report Map, descriptors, Device Name

Phase 2: CCCD Subscriptions (ALL by hog-ll, NOT Steam)
  0x0012 (Gamepad)      ✅
  0x0019 (Mouse)        ✅
  0x001d (Keyboard)     ✅
  0x0030 (CHR_REPORT)   ✅
  0x0034 (CHR_REPORT 2) ✅
  0x0042 (Battery)      ✅
  0x0039 (Valve Custom) ❌ NEVER subscribed by anyone

Phase 3: Feature Report Handshake (all on FR 0x00, handle 0x0021)
  1. GET_ATTRIBUTES (0x83) → responded ✅
  2. Unknown (0xf2)        → responded ✅
  3. GET_SERIAL (0xae)     → responded ✅
  4. SET_SETTINGS (0x87) flurry: registers 0x32, 0x09, 0x2d, 0x22, 0x23...
  5. Unknown cmds: 0xc1, 0xdc, 0xe2
  6. CLEAR_MAPPINGS (0x81)
  7. More SET_SETTINGS with complex payloads

Phase 4: Stuck in SET_SETTINGS loop (0x87 register 0x09 and 0x2d repeating)
  Never reaches SET_MODE (0x85) → "Warning, couldn't get controller details"
  Falls back to Type 30 (generic gamepad)
```

**Key insight**: Steam does NOT use GATT notifications. All control goes through Feature Reports (ATT Write/Read on handle 0x0021). Steam opens `/dev/hidrawN` via SDL3's hidraw backend and reads input via `SDL_hid_read()`.

- **What to try next**:
  1. **Fix the input report format**: Steam's SC2 driver expects 45-byte SC2 Custom reports (Report ID 0x45), NOT 12-byte standard gamepad reports. The HID Report Map must NOT have vendor-defined entries (those break SC2 detection), but Steam still reads the 12-byte gamepad reports and ignores them because they're not SC2 format.
  2. **Possible approach**: Remove the standard HID gamepad/mouse/keyboard from the Report Map entirely (making it purely vendor-defined like the real SC2026), and send SC2-format input via Feature Reports or a different mechanism.
  3. **Investigate `device_start_input_reports`**: This is the command that tells the real SC2 to start sending input. Steam sends this during the handshake — we may need to respond to it correctly.
  4. **Unknown commands 0xf2, 0xc1, 0xdc, 0xe2**: Our responses may be wrong, causing Steam to get stuck in the SET_SETTINGS loop.
  5. **Add GetChipId (0xBA) support**: May be needed for Steam to proceed past the handshake.

### 2. Dual Trackpads & IMU (Gyro/Accel) Forwarding
- Update the SC2 custom 45-byte report generation in `src/input_handler.py` to correctly extract trackpad X/Y and IMU values from Neptune's 64-byte reports.
- Refer to `docs/sc2-protocol.md` for payload offsets.

### 3. Auto-Reconnect Daemon
- Restart advertising cleanly after disconnects.
- **Next**: Test if the 0x87 fix allows Steam to proceed to 0x81 (ClearDigitalMappings) and 0x85 (mode switch). If not, may need to add GetChipId (0xBA) support or fix other response formats.
- **Key commands in the SC2 protocol flow**:
  1. `0x83` GET_ATTRIBUTES → response: `[0x83, 0x2D, 9 attributes x 5 bytes, padding]`
  2. `0xAE` GET_SERIAL → response: `[0xAE, 0x14, 0x01, serial_ascii, padding]`
  3. `0xBA` GET_CHIP_ID → response: `[0xBA, 0x11, 0x00, 15-byte chip_id, padding]` (NOT YET IMPLEMENTED)
  4. `0x81` CLEAR_MAPPINGS → write-only (exits lizard mode)
  5. `0x85` SET_DEFAULT_DIGITAL_MAPPINGS → write-only (enters gamepad mode)
  6. `0x87` SET_SETTINGS → write-only (configures registers)
  7. `0x85` via Feature Report 0x85 → mode switch (lizard ↔ Steam Input)

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
