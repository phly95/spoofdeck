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
│  │     └─ Serves GATT database (74 attributes)         │ │
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
- **Synthetic SC2 Command Handler**: Feature Report 0x00 intercepts SC2 commands (0x83 GET_ATTRIBUTES, 0xAE GET_SERIAL, 0x87 SET_SETTINGS, etc.) with correct byte-level response format matching real device captures from InputPlumber.
- **CHR_REPORT SC2 Custom in HID Service**: Report IDs 0x45 (45-byte) and 0x47 (47-byte) in HID Service for hog-ll subscription, PLUS Valve Custom Service for Steam identification. Dual notification targets.
- **Comprehensive Diagnostic Logging** (`[DIAG]` tagged).

---

## 3. What Needs to be Done

### 1. Steam Controller 2026 Recognition (Proprietary Input Format)
- **Status**: Adding CHR_REPORT for SC2 Custom to the HID Service causes Steam to detect the device as a **generic controller** instead of a **Steam Controller 2026**. The vendor-defined HID Report Map entries change the kernel's uhid device type.
- **Root cause**: The HID Report Map defines the device type. Vendor-defined collections (Usage Page 0xFF01) create generic HID devices. The Valve Custom HID Service alone is not enough for Steam to use SC2-specific input handling.

**Critical finding — two configurations tested:**

| | Config A: SC2 Recognized, No Input | Config B: Generic Controller, Input Works |
|---|---|---|
| **Valve Custom HID Service** | ✅ With CCCDs + NOTIFY | ✅ With CCCDs + NOTIFY |
| **CHR_REPORT in HID Service** | ❌ Not present | ✅ Report IDs 0x45, 0x47 |
| **HID Report Map** | Standard only (Gamepad, Mouse, Keyboard) | Standard + Vendor-defined (0xFF01) for 0x45, 0x47 |
| **hog-ll subscribes to SC2 Custom** | ❌ No (Valve Service not in HID) | ✅ Yes (CHR_REPORT in HID) |
| **Kernel uhid device type** | SC2-specific (via PnP ID + standard HID only) | Generic HID (vendor collections confuse parser) |
| **Steam sees** | Steam Controller 2026 | Generic gamepad |
| **Input delivery** | ❌ Notifications dropped (no CCCD on Valve handles) | ✅ Notifications reach host via CHR_REPORT |

The vendor-defined HID Report Map entries (Usage Page 0xFF01) are what break SC2 identification. The kernel's HID parser uses the Report Map to determine device type, and vendor-defined collections result in a generic HID device.

- **What to try next**:
  1. Investigate how InputPlumber's host-side driver discovers and reads from the Valve Custom HID Service — it may bypass hog-ll entirely and use raw GATT characteristics.
  2. Consider running InputPlumber on the host instead of relying on hog-ll.
  3. Research whether there's a way to tell hog-ll to forward Valve Custom Service data to Steam.

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
