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

### Primary Blocker: BlueZ hog-ll Never Attempts SET_REPORT
- On a clean connection (stale state cleared), BlueZ hog-ll never tries to configure output reports via SET_REPORT
- Without SET_REPORT, the output report path is never established
- Steam DOES schedule `CPulseHapticWorkItem` (confirmed in Steam logs) but the write completes in 0.0ms — rejected at kernel level
- btmon shows zero ATT Write Command (0x52) packets for haptics

### ~~Contributing Factor: SET_SETTINGS 0x09 Notification Not Delivered~~ — DISPROVEN
- ~~Real SC2 sends notification `[0x87, 0x01, register, 0x00 × 61]` on CHR_REPORT handle 0x0033 after each SET_SETTINGS write~~
- ~~Our code intentionally skips this (to avoid phantom button presses — see `main_l2cap.py:522`)~~
- ~~Steam retries SET_SETTINGS 0x09 every ~3 seconds forever, never completing the state machine~~
- **TESTED AND FAILED (2026-06-28)**: Sending 45-byte ack notifications on handle 0x0033 caused ghost inputs (phantom button presses). The notification was reverted. This is NOT the haptics blocker.

### What We Know Does NOT Block Haptics
- **`0x17252a0` is DEAD CODE** — The haptic trigger function at 0x17252a0 has ZERO callers in steamclient.so. The checks inside it (+0x320, +0x308) are irrelevant.
- **`SDL.joystick.cap.rumble` is NOT the blocker** — Steam schedules haptics despite this hint. The capability gates bit 14 (0x4000) in the capability bitmask, but Steam is already trying.
- **GATT/HID metadata is correct** — Report Map declares output report 0x80, CHR_REPORT exists at handle 0x0019 with correct properties, Report Reference is `[0x80, 0x02]`, write callback is registered.
- **`rumble_enabled`/`haptics_enabled` are dead strings** — Zero code references in steamclient.so.

## GATT Handle Map

Key handles for haptic debugging:

| Handle | UUID | Description |
|--------|------|-------------|
| 0x000A | 0x2800 | HID Service Declaration |
| 0x000C | 0x2A4A | HID Information Value |
| 0x000E | 0x2A4B | Report Map Value (77 bytes) |
| 0x0010 | 0x2A4C | HID Control Point Value |
| 0x0012 | 0x2A4D | **Gamepad Input (Report ID 0x01)** — 12 bytes, CCCD at 0x0014 |
| 0x0016 | 0x2A4D | Output (Report ID 0x02) — 1 byte |
| **0x0019** | **0x2A4D** | **Haptic Output (Report ID 0x80)** — 10 bytes, Report Ref `[80, 02]` at 0x001A |
| 0x001C | 0x2A4D | Mouse Input (Report ID 0x03) — 4 bytes, CCCD at 0x001E |
| 0x0020 | 0x2A4D | Keyboard Input (Report ID 0x04) — 8 bytes, CCCD at 0x0022 |
| **0x0024** | **0x2A4D** | **Feature Report 0x00 — 64 bytes (SC2 command channel)**, Report Ref at 0x0025 |
| 0x0027 | 0x2A4D | Feature Report 0x01 — 64 bytes, Report Ref at 0x0028 |
| 0x002A | 0x2A4D | Feature Report 0x85 — 64 bytes (mode switch), Report Ref at 0x002B |
| **0x0033** | **0x2A4D** | **SC2 Custom CHR_REPORT (Report ID 0x45)** — 45 bytes, CCCD at 0x0035 |
| 0x0037 | 0x2A4D | SC2 Custom CHR_REPORT (Report ID 0x47) — 47 bytes, CCCD at 0x0039 |
| 0x003C | 0x2A19 | Battery Level — CCCD at 0x003D |
| 0x004F | Custom | Valve Custom Service SC2_INPUT_CH1 — 45 bytes, CCCD at 0x0050 |

## Key Files

| File | Purpose |
|------|---------|
| `AGENTS.md` | Project continuation guide — read this first |
| `HANDOFF.md` | Detailed status and what needs to happen next |
| `CONTINUATION_PROMPT.md` | This file — quick start for new agents |
| `src/main_l2cap.py` | Entrypoint — GLib main loop, SC2 command handler, haptic forwarding |
| `src/att_server.py` | Raw L2CAP ATT server (CID 4) |
| `src/gatt_db.py` | GATT database (85 attributes, 6 services) |
| `src/input_handler.py` | Neptune HID → SC2 report mapping |
| `src/agent.py` | BlueZ Agent1 (auto-confirm pairing) |
| `src/adv.py` | BLE advertisement (LEAdvertisement1 D-Bus object) |
| `src/bluez.py` | BlueZ D-Bus helpers |
| `docs/findings-backlog.md` | Haptics deep dive and known issues |
| `docs/sc2-protocol.md` | SC2 BLE protocol details |
| `docs/att-server-implementation.md` | ATT protocol implementation |
| `research/steamclient-reverse-session/findings.md` | RE findings from steamclient.so (sessions 1-7) |
| `scripts/deploy.sh` | Deploy source files to Deck and restart service |
| `scripts/config_bt.py` | Configure BT adapter (bredr off, static addr) |
| `scripts/diagnose.sh` | Full Deck status diagnostic |

## Environment

- **Deck IP**: 172.16.16.120
- **Deck user**: deck / asdf
- **Deck sudo**: asdf
- **Host sudo**: qwerasdf
- **Static BLE address**: C2:12:34:56:78:9A
- **Host BT MAC**: 9C:B6:D0:8F:97:68
- **SSH**: `sshpass -p 'asdf' ssh -o StrictHostKeyChecking=no deck@172.16.16.120`
- **Source**: `/home/philip/spoofdeck-modified/src/`
- **Remote destination**: `/tmp/sc2-spoof/src/`

## Deployment Workflow

```bash
# 1. Deploy source files to Deck
sshpass -p 'asdf' scp -o StrictHostKeyChecking=no /home/philip/spoofdeck-modified/src/*.py deck@172.16.16.120:/tmp/sc2-spoof/src/

# 2. Restart service on Deck
sshpass -p 'asdf' ssh -o StrictHostKeyChecking=no deck@172.16.16.120 \
  "echo asdf | sudo -S systemctl stop sc2-hogp 2>/dev/null; \
   echo asdf | sudo -S systemctl reset-failed sc2-hogp 2>/dev/null; \
   echo asdf | sudo -S systemctl start bluetooth 2>/dev/null; \
   sleep 2; \
   echo asdf | sudo -S python3 /tmp/config_bt.py 2>&1; \
   sleep 1; \
   echo asdf | sudo -S systemd-run --remain-after-exit --unit=sc2-hogp --property=WorkingDirectory=/tmp/sc2-spoof python3 -u /tmp/sc2-spoof/src/main_l2cap.py --name 'Steam Controller 2026' 2>&1; \
   sleep 3; \
   echo asdf | sudo -S journalctl -u sc2-hogp -n 20 --no-pager 2>&1"

# 3. Connect from host
printf 'qwerasdf\n' | sudo -S bluetoothctl --timeout 15 connect C2:12:34:56:78:9A

# 4. Check Deck logs
sshpass -p 'asdf' ssh -o StrictHostKeyChecking=no deck@172.16.16.120 "echo asdf | sudo -S journalctl -u sc2-hogp --since '2 min ago' --no-pager 2>&1 | tail -40"
```

## Where to Find Logs

### Steam Logs (on host)
Steam writes controller logs to files. Look for:
```bash
# Find recent Steam logs mentioning haptics
find /tmp -name "*.log" -newer /tmp -exec grep -l "haptic\|rumble\|CPulseHapticWorkItem\|CWriteFeatureReportWorkItem" {} \; 2>/dev/null
find ~/.steam -name "*.log" -exec grep -l "haptic\|rumble" {} \; 2>/dev/null

# Check Steam's controller support logs
find ~/.steam -name "controller*.txt" -o -name "controller*.log" 2>/dev/null | head -10
```

The logs that show `CPulseHapticWorkItem(0) — running 0.0ms` confirm Steam IS scheduling haptics but the write fails instantly.

### btmon Captures
- Existing captures: `scratch/btmon_handshake.txt`, `scratch/sc2_haptic_test.log`
- To capture fresh: `printf 'qwerasdf\n' | sudo -S btmon -t -w /tmp/btmon_capture.log &` on host, then connect from Deck

### Deck Logs
```bash
# Last 40 lines
sshpass -p 'asdf' ssh deck@172.16.16.120 "echo asdf | sudo -S journalctl -u sc2-hogp -n 40 --no-pager 2>&1"

# Filter for haptics/SET_SETTINGS
sshpass -p 'asdf' ssh deck@172.16.16.120 "echo asdf | sudo -S journalctl -u sc2-hogp --since '2 min ago' --no-pager 2>&1 | grep -i 'SET_SETTINGS\|0x87\|FEATURE REPORT\|haptic\|notification.*0x87'"
```

## What Was Fixed (deployed but haptics still broken)

1. **Command 0x85/0x8D routing swap** — `main_l2cap.py:559-576`. Command 0x85 (SET_DEFAULT_DIGITAL_MAPPINGS) now just acknowledges, 0x8D (SET_CONTROLLER_MODE) handles mode switch.
2. **`_handle_mode_switch` byte parsing** — `main_l2cap.py:361-383`. For SC2 command 0x8D, reads mode from `value[3]` (correct offset) instead of `value[0]` (Report ID).
3. **GET_SERIAL format** — byte[1] changed from 0x14 to 0x15 (matches write command), serial starts with 'F' (0x46) to pass V_strncmp validation.

## ~~Exact Code Change for SET_SETTINGS Notification~~ — DISPROVEN

**DO NOT IMPLEMENT** — This was tested on 2026-06-28 and caused ghost inputs (phantom button presses). The notification was reverted. The missing SET_SETTINGS notification is NOT the haptics blocker.

The hypothesis was: After processing SET_SETTINGS (command 0x87), send the echo response as a 64-byte ATT notification on CHR_REPORT handle 0x0033. This was tested and failed.

## What To Do Next

### Priority 1: Diagnose why hog-ll never attempts SET_REPORT
On a clean connection (stale state cleared), BlueZ hog-ll never tries to configure output reports via SET_REPORT. Add diagnostic logging to `_handle_write_cmd()` in `att_server.py` to capture ALL incoming Write Command (0x52) packets. **Key unknown**: whether SET_REPORT writes reach our ATT server or fail upstream in BlueZ.

### Priority 2: Capture fresh btmon on host
During a new connection, capture btmon to see the actual initialization sequence. The fresh btmon evidence (2026-06-28) shows zero Write Commands (0x52) — host never sends haptic output reports. Connection is clean with only Write Requests (0x12) to handle 0x0024 (SET_SETTINGS 0x87) every 3 seconds.

## Reverse Engineering Context

- Binary: `~/.steam/debian-installation/linux64/steamclient.so` (46MB)
- Key findings from RE sessions 1-7 are in `research/steamclient-reverse-session/findings.md`
- `0x17252a0` is dead code (zero callers) — don't waste time on it
- `SDL.joystick.cap.rumble` at `0x00d0d093` gates bit 14 but is NOT the blocker
- `rumble_enabled`/`haptics_enabled` are dead strings — no code references
- The haptic path goes through: Steam → SDL3 → SDL_hid_write → BlueZ hog-ll → ATT Write Command (0x52) → BLE
- BlueZ hog-ll never attempts SET_REPORT for output reports on a clean connection. Without SET_REPORT, the output report path is never established and haptic writes from Steam are rejected at kernel level.

## Known Gotchas

1. `aaa`/`aaaa` on steamclient.so is slow (5-10 min) — use targeted `pd`, `/x`, `/ad`, `/ai` only
2. Stale BlueZ state causes zombie disconnects — clear bond data and restart daemon
3. `btusb` kernel module reset does NOT fix stale state — it's in BlueZ user-space
4. Python 3.13 doesn't support BLE socket tuple syntax — use `ctypes.bind()`
5. `SOL_BLUETOOTH` not in Python 3.13 — use numeric constant (274)
6. Never use `ControllerMode=le` in main.conf — causes "Not Supported" error
7. btmgmt power-cycles kill hogp — always start hogp AFTER config_bt.py
8. `pii.env` has credentials — source it before running scripts: `source pii.env`
