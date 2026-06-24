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
- **Raw L2CAP ATT Server (CID 4)**: Bypasses the SteamOS BlueZ GATT listener socket binding bug (which binds only to the public address instead of the static random address). Works reliably with MTU negotiation (up to 517).
- **Just Works Pairing**: Handled automatically on the Deck using a custom D-Bus `Agent1` implementation (`src/agent.py`) which auto-confirms passkey and authorization requests.
- **Full GATT Database (74 attributes, 6 services)**: Exposes standard GAP, GATT, HID (0x1812), Battery, Device Information (0x180A), and the Valve Custom HID Service (`100f6c32-...`).
- **PnP ID Validation**: Uses USB-IF (0x02) as the Vendor ID Source with Valve's VID (0x28DE) and PID (0x1303), resolving host-side protocol errors when reading PNP_ID.
- **CCCD Cache Persistence**: Keeps track of client configuration descriptors across disconnects. When the host reconnects, notifications resume immediately.
- **Physical Deck Input Capture**: Input handler reads directly from the Neptune controller `/dev/hidraw3` interface. Lizard mode on the Deck is periodically disabled by sending output reports (`0x81` ClearDigitalMappings) via `os.write()`.
- **Neptune Auto-Recovery**: If the hidraw device crashes (e.g., from a bad feature report proxy), the input handler waits 2s and reopens it, up to 10 retries.
- **End-to-End Lizard Mode Emulation**: 
  - Standard HID Mouse (handle `0x0019`) and Keyboard (handle `0x001d`) reports are packed and notified to the host.
  - The host creates `/dev/input/eventN` for "Steam Controller 2026 Mouse" and "Steam Controller 2026 Keyboard".
  - Pointer relative movement (right trackpad) and keypresses are successfully received by the host's `evdev` system.
- **Synthetic SC2 Command Handler** (Feature Report 0x00):
  - Intercepts SC2 commands from Steam instead of proxying to Neptune (which would crash it).
  - Handles `0x83` (GET_ATTRIBUTES), `0xAE` (GET_SERIAL), `0x81` (CLEAR_MAPPINGS), `0x87` (SET_ATTRIBUTES), `0x85` (SET_MODE).
  - Returns synthetic SC2 device info so Steam recognizes the controller and proceeds to mode switch.
- **Comprehensive Diagnostic Logging** (`[DIAG]` tagged):
  - Tracks all CCCD subscriptions with human-readable handle names.
  - Logs dropped notifications (first drop + every 200th).
  - Prints full DIAGNOSTIC SUMMARY on disconnect.
  - Logs all Feature Report writes with full data.

---

## 3. What Needs to be Done

### 1. Steam Mode Switch — Test Synthetic SC2 Responses
- **Status**: Synthetic SC2 command handler is implemented and deployed. Need to test if it works.
- **What was discovered**: Steam was stuck in an infinite retry loop on Feature Report 0x00 (GET_ATTRIBUTES command 0x83). The old code proxied this to Neptune, which crashed. Now we return synthetic SC2 device info locally.
- **Test**: Run Steam on the host, watch logs for `[DIAG]` lines. If GET_ATTRIBUTES response format is correct, Steam should proceed past the retry loop to Feature Report 0x85 (mode switch).
- **Verify**: Check if `steam_input_mode` becomes `True` and gamepad/SC2 reports start flowing.

### 2. Dual Trackpads & IMU (Gyro/Accel) Forwarding
- Update the SC2 custom 45-byte report generation (`gamepad_45b`) in `src/input_handler.py` to correctly extract the trackpad coordinates and the IMU values from the Neptune 64-byte reports and package them.
- Refer to `docs/sc2-protocol.md` for the payload offsets of trackpad X/Y and IMU gyro/accel coordinates.

### 3. Auto-Reconnect Daemon & Service Reliability
- Build a reconnection daemon or logic in `main_l2cap.py` to ensure that if the Bluetooth connection is lost, advertising is restarted cleanly, and the client can reconnect without manual steps.

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
