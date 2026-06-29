# Steam Deck SC2 BLE Spoof — Haptics Investigation Continuation

## Project Overview

We're building a fake Steam Controller 2026 (SC2) that spoofs a real SC2 over BLE to a host PC running Steam. The Steam Deck presents itself as an SC2 so Steam Client recognizes it with full Steam Input support (trackpads, gyro, haptics, back buttons).

## Current Status

**Working:**
- Raw L2CAP ATT server on CID 4 (bypasses BlueZ GATT bug)
- BLE connection stable, pairing works
- Input flowing: gamepad (12-byte), trackpads, gyro, back buttons (45-byte SC2 Custom reports)
- Steam Client recognizes the Deck as SC2 (PID 0x1303)
- Synthetic SC2 command handler (GET_ATTRIBUTES, GET_SERIAL, SET_SETTINGS, etc.)
- Neptune controller input capture and SC2 report mapping

**Not Working:**
- **Haptics** — The ONLY remaining blocker

## Haptics Root Cause (CONFIRMED via multi-agent investigation)

### Primary Blocker: BlueZ hog-ll SET_REPORT Failure
- BlueZ hog-ll tries SET_REPORT ~100 times/second to configure output reports and fails (487 errors in btmon)
- Without SET_REPORT success, the output report path is never established
- Steam DOES schedule `CPulseHapticWorkItem` (confirmed in Steam logs) but the write completes in 0.0ms — rejected at kernel level
- btmon shows zero ATT Write Command (0x52) packets for haptics

### Contributing Factor: SET_SETTINGS 0x09 Notification Not Delivered
- Real SC2 sends notification `[0x87, 0x01, register, 0x00 × 61]` on CHR_REPORT handle 0x0033 after each SET_SETTINGS write
- Our code intentionally skips this (to avoid phantom button presses — see `main_l2cap.py:522`)
- Steam retries SET_SETTINGS 0x09 every ~3 seconds forever, never completing the state machine

### What We Know Does NOT Block Haptics
- **`0x17252a0` is DEAD CODE** — The haptic trigger function at 0x17252a0 has ZERO callers in steamclient.so. The checks inside it (+0x320, +0x308) are irrelevant.
- **`SDL.joystick.cap.rumble` is NOT the blocker** — Steam schedules haptics despite this hint. The capability gates bit 14 (0x4000) in the capability bitmask, but Steam is already trying.
- **GATT/HID metadata is correct** — Report Map declares output report 0x80, CHR_REPORT exists at handle 0x0019 with correct properties, Report Reference is `[0x80, 0x02]`, write callback is registered.
- **`rumble_enabled`/`haptics_enabled` are dead strings** — Zero code references in steamclient.so.

## Key Files

| File | Purpose |
|------|---------|
| `AGENTS.md` | Project continuation guide — read this first |
| `HANDOFF.md` | Detailed status and what needs to happen next |
| `src/main_l2cap.py` | Entrypoint — GLib main loop, SC2 command handler, haptic forwarding |
| `src/att_server.py` | Raw L2CAP ATT server (CID 4) |
| `src/gatt_db.py` | GATT database (85 attributes, 6 services) |
| `src/input_handler.py` | Neptune HID → SC2 report mapping |
| `src/agent.py` | BlueZ Agent1 (auto-confirm pairing) |
| `docs/findings-backlog.md` | Haptics deep dive and known issues |
| `docs/sc2-protocol.md` | SC2 BLE protocol details |
| `docs/att-server-implementation.md` | ATT protocol implementation |
| `research/steamclient-reverse-session/findings.md` | RE findings from steamclient.so (sessions 1-7) |

## Environment

- **Deck IP**: 172.16.16.120
- **Deck user**: deck / asdf
- **Host sudo**: qwerasdf
- **Static BLE address**: C2:12:34:56:78:9A
- **Host BT MAC**: 9C:B6:D0:8F:97:68
- **SSH**: `sshpass -p 'asdf' ssh -o StrictHostKeyChecking=no deck@172.16.16.120`
- **Source**: `/home/philip/spoofdeck-modified/src/`

## What Was Fixed (deployed but haptics still broken)
1. Command 0x85/0x8D routing swap — FIXED in `main_l2cap.py:559-576`
2. `_handle_mode_switch` byte parsing — FIXED in `main_l2cap.py:361-383`
3. GET_SERIAL format (byte[1] 0x14 → 0x15, serial starts with 'F') — FIXED

## What To Do Next

### Priority 1: Fix SET_SETTINGS notification delivery
After processing SET_SETTINGS (command 0x87), send the echo response as a 64-byte ATT notification on CHR_REPORT handle 0x0033. Format: `[0x87, 0x01, register, 0x00 × 61]`. This matches what a real SC2 does and may unblock Steam's state machine.

### Priority 2: Diagnose why hog-ll SET_REPORT fails
Add diagnostic logging to `_handle_write_cmd()` in `att_server.py` to capture ALL incoming Write Command (0x52) packets. The btmon shows zero writes to output handles (0x0019, 0x0017), which means either hog-ll gives up after initial failure, or the writes use a different opcode.

### Priority 3: Capture fresh btmon on host
During a new connection, capture btmon to see the actual SET_REPORT ATT packets and their error responses. The current btmon capture may be missing critical initialization packets.

## Reverse Engineering Context

- Binary: `~/.steam/debian-installation/linux64/steamclient.so` (46MB)
- Key findings from RE sessions 1-7 are in `research/steamclient-reverse-session/findings.md`
- `0x17252a0` is dead code (zero callers) — don't waste time on it
- `SDL.joystick.cap.rumble` at `0x00d0d093` gates bit 14 but is NOT the blocker
- `rumble_enabled`/`haptics_enabled` are dead strings — no code references
- The haptic path goes through: Steam → SDL3 → SDL_hid_write → BlueZ hog-ll → ATT Write Command (0x52) → BLE
- BlueZ hog-ll tries SET_REPORT for output reports during HOG initialization and fails (487 errors)

## Known Gotchas

1. `aaa`/`aaaa` on steamclient.so is slow (5-10 min) — use targeted `pd`, `/x`, `/ad`, `/ai` only
2. Stale BlueZ state causes zombie disconnects — clear bond data and restart daemon
3. `btusb` kernel module reset does NOT fix stale state — it's in BlueZ user-space
4. Python 3.13 doesn't support BLE socket tuple syntax — use `ctypes.bind()`
5. `SOL_BLUETOOTH` not in Python 3.13 — use numeric constant (274)
6. Never use `ControllerMode=le` in main.conf — causes "Not Supported" error
7. btmgmt power-cycles kill hogp — always start hogp AFTER config_bt.py
