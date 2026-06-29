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
│  │     └─ Serves GATT database (85 attributes, 6 services)│ │
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
- **GATT Database (85 attributes, 6 services)**: GAP, GATT, HID (0x1812) with CHR_REPORT for SC2 Custom + Haptic Output, Valve Custom HID Service, Battery, Device Information.
- **PnP ID**: USB-IF source (0x02), Valve VID (0x28DE), PID (0x1303).
- **Physical Deck Input Capture**: Reads Neptune controller `/dev/hidraw3` (64-byte HID reports).
- **Neptune Auto-Recovery**: Reopens hidraw on crash (2s delay, 10 retries).
- **45-byte SC2 Custom Reports**: Full Triton 32-bit button bitmask (verified from SDL3 `TritonButtons` enum), analog sticks, triggers, trackpads, IMU, force sensors. Sent on CHR_REPORT handles 0x0033 and 0x004f.
- **Standard HID Gamepad Reports**: 12-byte reports on handle `0x0012` with buttons, analog sticks (Y axis corrected), triggers. Host creates `/dev/input/eventN`.
- **Lizard Mode Mouse/Keyboard**: Relative mouse (right trackpad) and keyboard reports on handles `0x0019`/`0x001d`.
- **Lizard mode properly disabled** — NEPTUNE_LIZARD_OFF_CMDS uses direct 0x81 command (no Report ID prefix). EVIOCGRAB grabs event4/event5 at startup to prevent lizard mode evdev events from reaching KDE desktop.
- **Trackpads work** — Left/right trackpad X/Y data flows in 45-byte reports.
- **Gyro works** — IMU accelerometer and gyroscope data flows in 45-byte reports.
- **Back buttons work** — L4/L5/R4/R5 paddle data flows in button bitmask.
- **Synthetic SC2 Command Handler**: Feature Report 0x00 intercepts SC2 commands:
  - `0x83` GET_ATTRIBUTES - responds with synthetic device info (capabilities bitmask 0x4169bfff)
  - `0xAE` GET_SERIAL - responds with serial number
  - `0xBA` GET_CHIP_ID - responds with 15-byte chip ID
  - `0x87` SET_SETTINGS - acknowledges, stores register values
  - `0x89` GET_SETTINGS_VALUES - returns stored register values
  - `0x81` CLEAR_MAPPINGS - acknowledges
  - `0x85` SET_DEFAULT_DIGITAL_MAPPINGS - acknowledges
  - `0x8D` SET_CONTROLLER_MODE - mode switch (lizard ↔ Steam Input)
  - Unknown commands echoed with zero payload
- **Haptic forwarding works for in-game rumble** — Full pipeline confirmed end-to-end with Celeste hazard impacts. Host game calls `SDL_RumbleJoystick()` → SDL writes output report to `/dev/hidrawN` → kernel `UHID_OUTPUT` → BlueZ hog-ll `forward_report()` → ATT Write Request (0x12) to handle 0x0019 → `_on_haptic_write()` → `_forward_haptic_to_neptune()` → writes PackedRumbleReport to `/dev/hidraw3` → Neptune dual ERM motors vibrate. Rumble format matches InputPlumber's PackedRumbleReport: `[0xeb, 0x09, 0x00, 0x00, 0x00, left_lo, left_hi, right_lo, right_hi]` padded to 64 bytes.
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

### 1. ~~Fix Zombie Disconnect~~ RESOLVED (2026-06-26)
- **Status**: Registration is now **stable**. `BYieldingCompleteSteamControllerRegistration` completes. No zombie disconnects. Input flows on handle 0x0012.
- **Root cause was stale BlueZ state** — cached bonding keys, CCCD states, and HOG profile state from previous sessions blocked SET_REPORT. Host PC reboot cleared it.
- **Fix for future breakage**:
  ```
  sudo rm -rf /var/lib/bluetooth/<HOST_BT_MAC>/C2:12:34:56:78:9A
  sudo rm -rf /var/lib/bluetooth/cache
  sudo systemctl restart bluetooth
  ```
  Then restart Deck's sc2-hogp service. `rmmod btusb` does NOT fix this — stale state is in BlueZ user-space.

### 2. ~~Fix Encryption Error~~ RESOLVED (2026-06-26)
- **Status**: Cleared after host PC reboot. Same root cause as zombie disconnect — stale BlueZ state.

### 3. Haptics

#### In-Game Rumble: WORKS
- **Status**: Full haptic pipeline confirmed end-to-end. Games that call `SDL_RumbleJoystick()` produce rumble on the Neptune motors.
- **Confirmed with**: Celeste hazard impacts.
- **Pipeline**: Host game → `SDL_RumbleJoystick()` → `SDL_hid_write()` → `/dev/hidrawN` → kernel `UHID_OUTPUT` → BlueZ hog-ll `forward_report()` → ATT Write Request (0x12) to handle 0x0019 → `_on_haptic_write()` → `_forward_haptic_to_neptune()` → writes PackedRumbleReport to `/dev/hidraw3` → Neptune dual ERM motors vibrate.
- **Rumble format**: Matches InputPlumber's PackedRumbleReport — `[0xeb, 0x09, 0x00, 0x00, 0x00, left_lo, left_hi, right_lo, right_hi]` padded to 64 bytes. Written to Neptune via `os.write()` on `/dev/hidraw3`.

#### Steam-Generated Haptics: DO NOT WORK
- **Status**: Trackpad clicks, UI feedback haptics, and other Steam-internal haptic events do NOT produce rumble.
- **Root cause**: These come from Steam's own haptic system, not from `SDL_RumbleJoystick()`. The Steam haptic path uses a different code path that does not reach the Neptune motors. Only games that explicitly call `SDL_RumbleJoystick()` produce rumble.
- **Known dead end**: `0x17252a0` (haptic trigger function in steamclient.so) has ZERO callers — confirmed dead code.

#### Native Deck vs BLE Haptics Comparison (2026-06-29)

**Native Deck (HIDIOCSFEATURE capture):**
- Steam sends 124 HIDIOCSFEATURE calls in 35 seconds during initialization.
- Command breakdown: 0x87 SET_SETTINGS (61), 0x81 ClearDigitalMappings (38), **0x8F Haptic (16)**, 0xAE GET_SERIAL (4), 0x83 GET_ATTRIBUTES (2), 0xC1/0xDC/0xE2 (1 each).
- **0x8F (haptic feedback) appears 16 times on native but NEVER on BLE.** **Confidence: Confirmed**
- 0x8F appears during initialization (positions 9,10 right after SET_SETTINGS) and during steady state.
- All commands go through HIDIOCSFEATURE (SET_FEATURE), NOT write() (output report).
- Initial handshake sequence: 0x83 → 0xAE → 0xAE → 0x81 → 0x87×4 → 0x8F×2 → 0x81 → 0x87 → ...

**BLE Handshake:**
- Steam DOES send the full command suite on BLE: 0x87×55, 0x81×8, 0xAE×19 (retrying), 0x83×1, 0xC1/0xDC/0xE2/0xF2×1. **Confidence: Confirmed**
- GET_SERIAL retries 19 times on BLE vs 4 on native. **Confidence: Confirmed**
- SET_SETTINGS 0x09 retries every 3 seconds on BLE. **Confidence: Confirmed**
- **Controller IS registered** (controller_ui.txt shows "Auto-Registering controller: F0000-0000-00000000, 12345678"). **Confidence: Confirmed**
- "Skipping usage report" is normal behavior (happens on both native and BLE). **Confidence: Confirmed**

**Native vs BLE GET_SERIAL write data differs:**
- Native: `ae 15 01 05 12 00 00 02 00 00 00 00 0a 2b 12 a9 62 04 3c b0 c6 69`
- BLE: `ae 15 04 00 34 5e bc e8 5c d7 8f c5 c8 d8 8f c5 a0 48 a7 e8 07 00`
- Write data differs between native and BLE (different serial hashes). Our handler ignores write data and returns fixed synthetic serial. **Confidence: Confirmed**

**0x8F gate hypothesis (UNVERIFIED):**
- Subagent claimed `[r15+0x208]` at `0x10d4da0` gates 0x8F dispatch.
- Subagent claimed `YieldingRunTestProgram` at `0x15677f4` is the ONLY function that sets this flag.
- **WARNING**: `strings` on steamclient.so shows NO "YieldingRunTestProgram" string. This may be a hallucination. Needs verification. **Confidence: Unverified**

- **What was fixed this session**:
  1. **Rumble format**: Fixed to match InputPlumber's PackedRumbleReport — `[0xeb, 0x09, 0x00, 0x00, 0x00, left_lo, left_hi, right_lo, right_hi]` padded to 64 bytes. Old format had wrong trailing bytes.
  2. **Lizard mode commands**: NEPTUNE_LIZARD_OFF_CMDS had wrong Report ID prefix (`0x01 0x00` instead of direct `0x81`). InputPlumber analysis revealed the correct format.
  3. **EVIOCGRAB**: Grabs event4/event5 at startup to prevent lizard mode evdev events from reaching KDE desktop.
  4. **BlueZ hog-lib.c analysis**: Confirmed `forward_report()` uses ATT Write Request (0x12), not Write Command (0x52). Previous btmon filters for 0x52 missed actual writes.
  5. **Manual write test**: Writing directly to `/dev/hidrawN` on host confirmed the UHID output path works end-to-end.

### 4. ATT Server Spec Compliance (LOW PRIORITY)
- **Status**: Registration works without these fixes. These are correctness improvements that could prevent issues with different host stacks or future BlueZ versions.
- **Items (implement one at a time, test each)**:
  1. **Read Blob error code** (`att_server.py:379`) — Returns `ATT_ERR_INVALID_HANDLE` (0x01) when offset >= value length. Should be `ATT_ERR_INVALID_OFFSET` (0x07).
  2. **MTU cap on Read/Notify PDUs** — Full values sent without truncating to MTU. Works in practice (MTU exchange happens first) but violates spec.
  3. **PDU length validation** — No length checks before `struct.unpack` in `_handle_pdu`. Could crash on malformed PDUs.
  4. **ATT permission checking** — No `ATT_PROP_READ`/`ATT_PROP_WRITE` flag checking on Read/Write Request handlers. **DO NOT check permissions on Write Command** — Feature Report 0x00 has `ATT_PROP_WRITE` but not `ATT_PROP_WRITE_NO_RSP`.
  5. **Diagnostic handle labels** (`att_server.py:504-510, 525-531`) — Stale hardcoded handles for Mouse, Keyboard, SC2 Custom CH1/CH2. Only Gamepad (0x0012) is correct.

### 5. SC2 Custom Reports (0x003c) — CCCD Not Always Enabled (MEDIUM PRIORITY)
- **Status**: CCCD on handle 0x003c not always written by BlueZ hog-ll after reconnect. Host sees generic gamepad instead of full SC2. Trackpads, gyro, and back buttons still work (data flows on 0x0033).
- **What to try**:
  1. Investigate why hog-ll sometimes skips 0x003c CCCD write
  2. Check if dual notification targets (Valve Custom Service + HID Service CHR_REPORT) cause confusion
  3. Compare btmon captures between successful and failed CCCD enables

### 5. Command Routing (MEDIUM PRIORITY)
- **Status**: 0x85/0x8D swapped. Per protocol doc, 0x85 = SET_DEFAULT_DIGITAL_MAPPINGS, 0x8D = SET_CONTROLLER_MODE. Code has them reversed.
- **Fix**: Swap the routing in `main_l2cap.py:556-564`.

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

### 6. Haptic Feedback — In-Game Rumble Works, Steam Haptics Do Not

- **In-game rumble works**: Full pipeline confirmed with Celeste. Games calling `SDL_RumbleJoystick()` produce rumble. See section 3 above for full pipeline details.
- **Steam-generated haptics do not work**: Trackpad clicks, UI feedback haptics use a different code path. See section 3 above.
- **BlueZ hog-lib.c analysis (2026-06-29)**: The haptics path is `UHID_OUTPUT` -> `forward_report()` using ATT Write Request (0x12), NOT Write Command (0x52). Our CHR_REPORT has `GATT_CHR_PROP_WRITE` which causes `forward_report()` to use `gatt_write_char()` (0x12) instead of `gatt_write_cmd()` (0x52).
- **SET_SETTINGS notification hypothesis TESTED AND FAILED**: Sending 45-byte ack notifications on handle 0x0033 caused ghost inputs. The missing notification is NOT the haptics blocker.
- **Note**: The SET_SETTINGS 0x09 retry loop is confirmed to be noise (not a blocker). It does not affect haptics.

### 7. Dual Trackpads & IMU (Gyro/Accel) Forwarding
- **Status**: 45-byte SC2 Custom report with trackpad X/Y, IMU (accel/gyro), and force sensors is **already implemented** in `input_handler.py`. The data flows correctly from Neptune HID → SC2 report.
- **Remaining**: Steam may need specific settings enabled to activate gyro/trackpad features (registers 0x27 IMU_MODE, etc.). CCCDs on 0x003c must be enabled first.

### 8. Auto-Reconnect Daemon
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
- **Haptic path**: Uses SDL_hid_write() (output reports), NOT SDL_hid_send_feature_report(). Report ID 0x80, 10 bytes. Lizard mode must be OFF for haptics to work. In-game rumble via SDL_RumbleJoystick() works end-to-end. Steam-generated haptics (trackpad clicks, UI feedback) do not reach Neptune motors.
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
