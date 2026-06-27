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
- **Bonding Key Mismatch Fix**: After Deck BT restart, stale LTK on host causes `[Errno 38] ENOSYS` on `conn.recv()`. Fix: `bluetoothctl remove C2:12:34:56:78:9A` then re-pair. For cumulative BlueZ state corruption (zombie disconnects, CCCDs not enabled), clear bond data:
  ```
  sudo rm -rf /var/lib/bluetooth/<HOST_BT_MAC>/C2:12:34:56:78:9A
  sudo rm -rf /var/lib/bluetooth/cache
  sudo systemctl restart bluetooth
  ```
  Then restart Deck's sc2-hogp service. Note: `rmmod btusb && modprobe btusb` does NOT fix this — stale state is in BlueZ user-space.
- **Comprehensive Diagnostic Logging** (`[DIAG]` tagged).

---

## 3. What Needs to be Done

### 1. Fix Zombie Disconnect (PRIMARY BLOCKER)
- **Status**: The identity slot at `controller+slot*0xe8+0x200` must be populated before the zombie timer fires (~10s). Feature report WRITE commands arrive ~150s after connection — too late. Controller becomes zombie within 10 seconds of opening. 44 registration attempts, 412 zombie disconnections since Jun 24.
- **CONFIRMED PRE-EXISTING (2026-06-26)**: Tested old commit `1b6bfde` (yesterday 6:51 PM) — same zombie disconnect. Both root issues existed before our changes.
- **Root cause chain**:
  1. BLE connection → GATT discovery → reads FR 0x00 → returns zeros (no pending response)
  2. BlueZ creates UHID device → Steam opens controller → starts feature report processing
  3. Feature report WRITE commands arrive ~150s after connection (too late)
  4. Zombie timer fires at ~10s → identity slot empty → DISCONNECT
  5. Identity slot populated by feature report processing code at 0x10d4e6c
  6. Feature report processing requires UHID device + Steam's HID API calls
  7. Race condition: zombie timer fires before feature report processing completes
- **Steam controller log shows**:
  ```
  CGetControllerInfoWorkItem::RunFunc: Read failure. (×10)
  Warning, couldn't get controller details for SC, PID=4867
  GetControllerInfo failed - executed 1, success 0
  Controller uses V1 HID protocol via BLE
  !! Steam controller device opened for index 0
  Steam Controller reserving XInput slot 0
  Controller PollState Changed from 0 to 1
  Disconnecting zombie controller 0  (6-13 seconds later)
  ```
- **RE findings**:
  - `0x1070620` is a 7-check gate function (zombie check + registration identity)
  - Checks: bounds, vtable, connection exists, connection state (1 or 4), **slot ready flag at slot+0x200**
  - Identity slot populated by `QueueFetchingControllerDetails` at 0x1092820
  - Serial validation at 0x26b1ac0 (V_strncmp) checks first byte == 'F' (0x46)
  - `CGetControllerInfoWorkItem` failure does NOT block registration (separate code path)
- **What to try next**:
  1. Find a way to populate the identity slot without waiting for Steam's feature report writes
  2. Investigate why feature report WRITE commands are delayed ~150s
  3. Consider bypassing the zombie check (e.g., manipulating connection state)

### 2. Fix Encryption Error (SECONDARY BLOCKER)
- **Status**: `set_report_cb() Error: Encryption Key Size is insufficient` blocks SET_REPORT. This is a BlueZ HOG profile internal issue — not caused by our code. Confirmed PRE-EXISTING (tested old commit `1b6bfde`).
- **BREAKTHROUGH (2026-06-26 evening)**: After host PC reboot, input IS flowing. The stale BlueZ state from previous sessions was blocking SET_REPORT. A reboot cleared it. This explains why the issues appeared pre-existing — the cached state persisted across code deploys.
- **Root cause**: Stale bonding keys, LTK, or HOG profile state from previous BLE sessions was cached by BlueZ. When a new connection was established, BlueZ tried to use the old state, causing SET_REPORT to fail with "Encryption Key Size is insufficient".
- **Fix**: Reboot the host PC to clear BlueZ cache. Or: `bluetoothctl remove C2:12:34:56:78:9A` + restart bluetooth service.
- **What we tried**:
  - Removed `BT_SECURITY_MEDIUM` from att_server.py — error persists
  - Tested old version — same error (because stale state was still cached)
  - Rebooted host PC — error cleared, input works

### 3. GET_SERIAL Format (FIXED)
- **Status**: FIXED in current commit. byte[1] changed from 0x14 to 0x15 (matches write command). Serial must start with 'F' (0x46) to pass V_strncmp validation at 0x26b1ac0.
- **Validation**: `V_strncmp` at 0x26b1ac0 compares first byte of serial against pattern at 0xd69c60 (first byte = 0x46 = 'F'). If validation fails, serial is replaced with "DOCKED_SLOT".
- **Response format** (23 bytes):
  ```
  byte[0] = 0xAE (command echo)
  byte[1] = 0x15 (payload length, matches write command byte[1])
  byte[2] = 0x01 (success status)
  bytes[3-22] = serial number (20 bytes, starts with 'F')
  ```

### 4. Haptic Feedback (HOST NOT SENDING)
- **Status**: The haptic forwarding code is ready and correct — `_on_haptic_write()` on handle 0x0019 parses both 10-byte and 9-byte payloads. However, **the host never sends haptic output reports** — btmon capture confirmed zero ATT Write Command (0x52) packets during a test session. The issue is upstream in Steam/hog-ll.
- **RE findings**: Haptics use `SDL_hid_write()` (output reports, NOT feature reports). Lizard mode must be OFF for haptics to work.
- **Note**: The SET_SETTINGS 0x09 retry loop is confirmed to be noise (not a blocker). It does not affect haptics.
- **What to try next**:
  1. Fix the controller registration first — haptics won't work until the controller is stable
  2. Get a real SC2 btmon capture to see if haptics work on a real device

### 4. Dual Trackpads & IMU (Gyro/Accel) Forwarding
- **Status**: 45-byte SC2 Custom report with trackpad X/Y, IMU (accel/gyro), and force sensors is **already implemented** in `input_handler.py`. The data flows correctly from Neptune HID → SC2 report.
- **Remaining**: Steam may need specific settings enabled to activate gyro/trackpad features (registers 0x27 IMU_MODE, etc.).

### 6. Auto-Reconnect Daemon
- **Status**: Advertising refresh on disconnect is **already implemented** in `main_l2cap.py:_schedule_adv_refresh()`.
- **Remaining**: Ensure clean re-advertising after disconnects without manual intervention.
- **Key commands in the SC2 protocol flow**:
  1. `0x83` GET_ATTRIBUTES → response: `[0x83, 0x2D, 9 attributes x 5 bytes, padding]`
  2. `0xF2` Unknown (1-byte payload varies: 0x01, 0x02, etc.) → response: `[0xF2, 0x00, zeros]` (STILL WRONG — needs real SC2 capture)
  3. `0xAE` GET_SERIAL → response: `[0xAE, 0x14, 0x01, serial_ascii, padding]`
  4. `0xBA` GET_CHIP_ID → response: `[0xBA, 0x11, 0x00, 15-byte chip_id, padding]`
  5. `0x87` SET_SETTINGS → write-only (configures registers), verification read NEVER happens (by design — SDL3 confirms fire-and-forget)
  6. `0x89` GET_SETTINGS_VALUES → response: stored register values
  7. `0xC1`/`0xDC`/0xE2` Unknown → echo with zero payload
  8. `0x81` CLEAR_MAPPINGS → write-only (exits lizard mode)
  9. `0x85` SET_DEFAULT_DIGITAL_MAPPINGS → write-only (enters gamepad mode)
  10. `0x8D` SET_CONTROLLER_MODE → mode switch (lizard ↔ Steam Input)

### 7. Reverse Engineering Findings (from steamclient.so)
- **ControllerDetails_tE**: 84 bytes (0x54), ready_flag at offset 0x3c must be 1. Set by QueueFetchingControllerDetails at 0x01092820. Fields come from controller object offsets 0x84-0xd4.
- **Product ID check**: 0x1303 is in recognized range (0x1302-0x1305). Other recognized types: 0x1142, 0x1220, 0x1201-0x1206, 0x1101-0x1102.
- **Haptic path**: Uses SDL_hid_write() (output reports), NOT SDL_hid_send_feature_report(). Report ID 0x80, 10 bytes. Lizard mode must be OFF for haptics to work.
- **SET_SETTINGS is fire-and-forget**: SDL3 confirms no `SDL_hid_get_feature_report()` after send. State machine at 0x010d466b skips VERIFY because r13 is NULL. `[r15+0x208]` is a "test mode" flag — always 0 in normal operation.
- **0x1070620 is the zombie check / registration identity gate**: 7-check gate function. Checks bounds, vtable, connection state (1 or 4), and **slot ready flag at controller+slot*0xe8+0x200**. Same function used by both zombie check and registration.
- **Identity slot populated by feature report processing**: Code at 0x10d4e6c processes GET_ATTRIBUTES/GET_SERIAL/0xf2 responses and writes to identity slot. Unique ID at slot+0x200 is the serial number — first byte MUST be non-zero.
- **Serial validation**: V_strncmp at 0x26b1ac0 checks first byte == 'F' (0x46). Pattern at 0xd69c60.
- **CGetControllerInfoWorkItem**: Reads controller details from IPC pipe (hiddevicepipesteam.cpp). Retries 51 times with 100ms sleep. Fails because IPC pipe read returns 0 bytes. Does NOT block registration — only affects account queries.
- **CHIDIOThread**: Processes HID I/O work items. String at 0x00d6fbc2. SET_SETTINGS work items are queued here.
- **IPC pipe**: hiddevicepipesteam.cpp (string at 0x00c8ce9a). Connects steamclient.so to CHIDIOThread. Uses protobuf messages (CHIDMessageToRemote/CHIDMessageFromRemote).
- **SDL_hid_send_feature_report**: Resolved via dlsym at 0x01760fa2, stored at 0x02c69a28.
- **0xf2 command**: Per-category capability query dispatched via switch/case. Response format: `[0xf2, category, length, data...]`.
- **Encryption error**: `set_report_cb() Error: Encryption Key Size is insufficient` is PRE-EXISTING. Persists without BT_SECURITY_MEDIUM. BlueZ HOG profile internal issue.
- **RE session files**: research/steamclient-reverse-session/ contains findings.md, functions/, notes/
  - `functions/controller_identity_check.c` — 0x1070620 disassembly (7-check gate)
  - `functions/registration_data_flow.c` — What data registration needs from ATT server
  - `functions/zombie_disconnect.c` — Zombie check conditions (state-based, not timer)
  - `functions/serial_validation.c` — V_strncmp validation (first byte == 'F')
  - `functions/serial_format.c` — Serial number format requirements
  - `functions/slot_data_population.c` — Identity slot vs ControllerDetails analysis
  - `functions/get_attributes_format.c` — GET_ATTRIBUTES response format
  - `functions/get_serial_format.c` — GET_SERIAL response format (byte[1]=0x15)
  - `functions/notification_trigger.c` — Why ATT notifications won't trigger feature report processing
  - `functions/ipc_pipe_fix.c` — IPC pipe analysis (populates ControllerDetails, not identity slot)
  - `functions/handshake_completion.c` — SET_SETTINGS retry is noise, registration runs independently
  - `functions/hid_write_failure.c` — vtable[0x10] skipped because [r15+0x208]=0
  - `functions/retry_mechanism.c` — 3-second retry for failed HID writes
  - `functions/sdl3_verification.c` — SDL3 confirms fire-and-forget
  - `functions/set_settings_path.c` — SET_SETTINGS goes through state machine
  - `functions/verify_branch.c` — r13=NULL causes VERIFY skip

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
