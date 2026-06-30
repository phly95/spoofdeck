# SC2 BLE Spoof — Continuation Prompt

## Boot Sequence

1. Read `AGENTS.md` — full project context, architecture, how to run
2. Read `docs/investigation-plan.md` — methodology rules, confidence scale, hypothesis lifecycle
3. Read `HANDOFF.md` — current status
4. Read `docs/findings-backlog.md` — what's been tried, what hasn't
5. Read `research/steamclient-reverse-session/findings.md` — RE context
6. Then proceed to investigation below

## Environment

```
Deck IP:       172.16.16.120
Deck SSH:      sshpass -p 'asdf' ssh -o StrictHostKeyChecking=no deck@172.16.16.120
Deck sudo:     echo 'asdf' | sudo -S <cmd>
Host sudo:     printf 'qwerasdf\n' | sudo -S <cmd>
BLE address:   C2:12:34:56:78:9A
Host BT MAC:   9C:B6:D0:8F:97:68
Source:        /home/philip/spoofdeck-modified/src/
Remote dest:   /tmp/sc2-spoof/src/
```

Source `pii.env` for credentials before scripts.

## Current Status

### Working
- In-game rumble via `SDL_RumbleJoystick()` — Celeste hazard impacts confirmed working
- Full pipeline: Host game → SDL_RumbleJoystick → SDL_hid_write → kernel UHID → BlueZ hog-ll → ATT Write Request (0x12) → handle 0x0019 → `_on_haptic_write` → `_forward_haptic_to_neptune` → write `/dev/hidraw3` → Neptune motors
- Lizard mode disabled — EVIOCGRAB on event4/event5 + periodic `0x81` ClearDigitalMappings commands
- Controller IS registered on host — serial "F0000-0000-00000000" accepted, configs loaded

### Not Working
- **Steam-generated haptics** — Trackpad clicks, UI feedback haptics do NOT produce rumble. 0x8F never appears on BLE.

### ⚠️ CRITICAL: Wrong Binary Analyzed (2026-06-29)
All binary analysis in this project was done on `linux64/steamclient.so` (46MB, 64-bit). **Steam loads `ubuntu12_32/steamclient.so` (49MB, 32-bit i386).** Every address, function offset, and disassembly from the RE sessions is WRONG for the running process. The conceptual findings (gate mechanism, YieldingRunTestProgram, job system) likely apply to both binaries, but every specific address must be re-derived from the 32-bit binary or verified via GDB.

Evidence:
- Steam process: ELF 32-bit LSB pie executable (i386)
- YieldingRunTestProgram string: 32-bit=`0x00bfc7e3`, 64-bit=`0x00d6d17b`
- Dispatcher at offset 0x015675a8: 32-bit=`in al,dx` (0xec), 64-bit=`push rbp` (0x55)

**The GDB approach works on the running 32-bit process regardless of binary version.**

### What Was Fixed (2026-06-29)
1. **Rumble format** — Fixed to match InputPlumber's PackedRumbleReport: `[0xeb, 0x09, 0x00, 0x00, 0x00, left_lo, left_hi, right_lo, right_hi]` padded to 64 bytes
2. **Lizard mode commands** — NEPTUNE_LIZARD_OFF_CMDS had wrong Report ID prefix (`0x01 0x00` → direct `0x81`)
3. **EVIOCGRAB** — Grabs event4/event5 at startup to prevent lizard mode evdev events from reaching KDE desktop
4. **BlueZ hog-lib.c analysis** — Confirmed `forward_report()` uses ATT Write Request (0x12), not Write Command (0x52)
5. **Manual write test** — Writing directly to `/dev/hidrawN` on host confirmed UHID output path works end-to-end

## Deployment Workflow

```bash
# 1. Deploy source files to Deck
sshpass -p 'asdf' scp -o StrictHostKeyChecking=no src/*.py deck@172.16.16.120:/tmp/sc2-spoof/src/

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
   echo asdf | sudo -S journalctl -u sc2-hogp -n 15 --no-pager 2>&1"

# 3. Clear stale bond data on host
printf 'qwerasdf\n' | sudo -S rm -rf /var/lib/bluetooth/9C:B6:D0:8F:97:68/C2:12:34:56:78:9A
printf 'qwerasdf\n' | sudo -S rm -rf /var/lib/bluetooth/cache
printf 'qwerasdf\n' | sudo -S systemctl restart bluetooth

# 4. Scan and connect
printf 'qwerasdf\n' | sudo -S bluetoothctl --timeout 30 scan on
printf 'qwerasdf\n' | sudo -S bluetoothctl connect C2:12:34:56:78:9A
```

## Investigation: Steam-Generated Haptics (Primary Focus)

### The Problem
In-game rumble works, but Steam-generated haptics (trackpad clicks, UI feedback) do NOT produce rumble. On a **clean connection** (stale state cleared):

### Evidence: Native Deck vs BLE (2026-06-29)

**Native Deck strace capture (124 HIDIOCSFEATURE calls in 35s):**
```
Command frequency:
  0x87 SET_SETTINGS: 61 times
  0x81 ClearDigitalMappings: 38 times
  0x8F Haptic feedback: 16 times  ← THIS IS THE KEY
  0xAE GET_SERIAL: 4 times
  0x83 GET_ATTRIBUTES: 2 times
  0xC1/0xDC/0xE2: 1 time each
```

**BLE handshake (from Deck ATT server logs):**
```
Command frequency:
  0x87 SET_SETTINGS: 55 times
  0xAE GET_SERIAL: 19 times (retrying)
  0x81 ClearDigitalMappings: 8 times
  0x83 GET_ATTRIBUTES: 1 time
  0xC1/0xDC/0xE2/0xF2: 1 time each
  0x8F Haptic feedback: 0 times  ← NEVER APPEARS
```

**Key finding: 0x8F appears 16 times on native but NEVER on BLE.** This is the actual gate.

**Controller IS registered on BLE** — Steam logs show:
```
Controller 0 connected, configuring it now...
Serial: F0000-0000-00000000
Auto-Registering controller: F0000-0000-00000000, 12345678
```

**Native 0x8F data format:**
```
0x8F 0x08 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x02...  (sub=0x00)
0x8F 0x08 0x01 0x00 0x00 0x00 0x00 0x00 0x00 0x02...  (sub=0x01)
```

0x8F appears during initialization (positions 9,10 right after SET_SETTINGS) and during steady state.

### Primary Hypothesis: `[r15+0x208]` Gate (VERIFIED in 64-bit binary, UNVERIFIED in 32-bit)

**NOTE: All addresses below are from the 64-bit binary (`linux64/steamclient.so`). The 32-bit binary has different code at these offsets. The concepts are likely the same, but addresses must be re-derived.**

**The gate at `0x10d4da0` (64-bit offset):**
```asm
0x010d4da0: cmp byte [r15 + 0x208], 0    ; Check HID output path established flag
0x010d4da8: movzx eax, byte [r15 + 0xe1]
0x010d4db0: je 0x10d4fd0                ; If flag==0 → SKIP entire vtable dispatch
```

**Only ONE instruction sets this flag to 1 (64-bit offset):**
```
0x0156781c: mov byte [r15+0x208], 1    ; in YieldingRunTestProgram
```

**What we know (conceptual, applies to both binaries):**
- YieldingRunTestProgram is a job in Steam's job system (job.cpp)
- It spawns a subprocess and waits for it (60s timeout)
- If it succeeds, [obj+0x208] = 1 (haptic gate opens)
- If [obj+0x208] stays 0, 0x8F haptic commands are never dispatched

**What we DON'T know (needs GDB on 32-bit process):**
- Does the dispatcher run at all during BLE connection?
- What value does [rdi+0x1d8] hold? (may be graphics API type, not controller state)
- Is [0x208] ever set to 1 on BLE?

### ATT Write Response Format (VERIFIED WORKING)

ATT Write Response (0x13) is correct — single byte, standard BLE spec. BlueZ's `set_report_cb()` receives status=0 and calls `bt_uhid_set_report_reply()` with success. **The Write Response path is NOT the problem.**

### Evidence from Live Connection Test (2026-06-29)

**Clean connection test results (host BlueZ debug + Deck ATT logs):**
1. MTU exchange: 517/517 ✅
2. GATT discovery: 6 services, all characteristics found ✅
3. CCCDs enabled: 0x0012 (Gamepad), 0x001c (Mouse), 0x0020 (Keyboard), 0x0033 (SC2 Custom), 0x0037 (SC2 Custom 0x47), 0x0045 (Battery) ✅
4. Feature Report writes/reads: All commands flow correctly ✅
5. Commands sent: 0x83 GET_ATTRIBUTES, 0xF2 category query, 0xAE GET_SERIAL (19+ retries), 0x87 SET_SETTINGS (registers 0x32, 0x09, 0x30, 0x18, 0x35), 0x81 CLEAR_MAPPINGS (many)
6. **0x8F Haptic: NEVER APPEARS** ❌
7. Connection drops after ~30 seconds (supervision timeout) ❌

**Key difference from native Deck:**
- Native: GET_SERIAL succeeds after 4 retries → initialization proceeds → `YieldingRunTestProgram` runs → 0x8F dispatched
- BLE: GET_SERIAL retries 19+ times → initialization stalls → `YieldingRunTestProgram` never runs → 0x8F never dispatched

**Host BlueZ `get_report_cb()` error was from accidental double-restart of bluetoothd — NOT a real error.** The second clean connection had no errors.

### What to Investigate Next

1. **GDB watchpoint on running 32-bit Steam process (RECOMMENDED NEXT STEP)** — The 0x8F gate mechanism exists in the 32-bit binary but at different addresses. GDB works on the running process regardless. Set a breakpoint on the dispatcher (found via YieldingRunTestProgram string reference) and read [rdi+0x1d8] and [0x208]. This takes 5 minutes and gives definitive answers.
2. **LD_PRELOAD patch for 0x8F gate (AFTER GDB VERIFICATION)** — Once the correct addresses are found in the 32-bit binary, patch the conditional jump to force 0x8F dispatch. 55-65% probability of working.
3. **Why does Steam retry GET_SERIAL 19+ times on BLE?** Our handler returns valid response with 'F'-prefixed serial. Steam might compute a hash from the write data.

## Important Rules

1. **One change at a time** — Never stack fixes. If Fix A doesn't work, revert it, then try Fix B.

2. **Evidence before conclusion** — Every finding must cite specific evidence. Tag with confidence level (Confirmed/Plausible/Speculative).

3. **Spawn subagents for research** — Don't read 500+ lines of BlueZ source in the main thread. Use explore subagents.

4. **Commit progress** — After each meaningful finding, commit: `git add -A && git commit -m "finding: <description>" && git push`

5. **Stale state is the #1 cause of mysterious failures** — Every test cycle: clear bond data, restart BlueZ, reconnect.

6. **In-game rumble works, Steam haptics do not** — Games calling `SDL_RumbleJoystick()` produce rumble. Steam-generated haptics (trackpad clicks, UI feedback) use a different code path that does not reach Neptune motors.

## Reference: Native Deck Strace Capture

To capture the native Deck handshake:
```bash
# On Deck, kill Steam first
killall steam

# Deploy and run capture script
sshpass -p 'asdf' scp scripts/capture_native.sh deck@172.16.16.120:/tmp/
sshpass -p 'asdf' ssh deck@172.16.16.120 "chmod +x /tmp/capture_native.sh && bash /tmp/capture_native.sh"
# Start Steam on Deck when prompted
```

The script watches for `/dev/hidraw4` to appear, then straces the owner PID with `-f` (follow forks).

## Reference: InputPlumber Analysis

InputPlumber source cloned to `/tmp/InputPlumber/`. Key findings:

| Topic | InputPlumber Approach | Our Current State |
|-------|----------------------|-------------------|
| Rumble format | `PackedRumbleReport` — `[0xeb, 0x09, 0x00, 0x00, 0x00, left_lo, left_hi, right_lo, right_hi]` padded to 64 bytes | Fixed to match |
| Lizard mode disable | `0x81` ClearDigitalMappings every 2 seconds + `0x87` register writes for permanent settings | Fixed format |
| Lizard mode evdev | `hid-steam` creates event4/event5 via `usbhid`, NOT via `hid-steam` module | EVIOCGRAB grabs them |
| Hidraw access | Opens `/dev/hidraw*` via `hidapi`, coexists with `hid-steam` driver | Same approach |

## Reference: BlueZ hog-lib.c Analysis

BlueZ 5.86 source at `/tmp/bluez-5.86/profiles/input/hog-lib.c`.

| Function | Line | Purpose |
|----------|------|---------|
| `forward_report()` | 746-778 | Handles UHID_OUTPUT (haptics from Steam) — uses ATT Write Request (0x12) |
| `set_report()` | 845-900 | Handles UHID_SET_REPORT (kernel-initiated) — NOT the haptics path |
| `find_report_by_rtype()` | 740 | Finds report by type+ID |
| `find_report()` | 693-706 | BUG: uses `hog->flags` instead of `hog->uhid_flags` for numbered flag |

The haptics path is `UHID_OUTPUT` → `forward_report()`, NOT `UHID_SET_REPORT` → `set_report()`. SET_REPORT is kernel-initiated (device probe), not triggered by Steam writes.

## Reference: Audit Findings (2026-06-29)

### ⚠️ All Addresses Below Are 64-bit Offsets (WRONG for Running Process)

These addresses are from `linux64/steamclient.so`. Steam loads `ubuntu12_32/steamclient.so`. The concepts are likely the same, but addresses must be re-derived from the 32-bit binary or verified via GDB.

| 64-bit Offset | Function/Label | Status |
|---------|---------------|--------|
| `0x015675a8` | Dispatcher (18,300 bytes) | **VERIFIED in 64-bit** — but offset is WRONG in 32-bit |
| `0x015677f4` | YieldingRunTestProgram | **VERIFIED in 64-bit** — string at 0x00d6d17b (64-bit), 0x00bfc7e3 (32-bit) |
| `0x0156781c` | `mov byte [r15+0x208], 1` | **VERIFIED in 64-bit** — but offset is WRONG in 32-bit |
| `0x010d4da0` | Gate check | **VERIFIED in 64-bit** — but offset is WRONG in 32-bit |

### What's True Regardless of Binary
- YieldingRunTestProgram is a job that spawns a subprocess and waits
- If it succeeds, [obj+0x208] = 1 (haptic gate opens)
- If [obj+0x208] stays 0, 0x8F is never dispatched
- The handler's +0x08 BLE flag is NEVER READ (verified on 64-bit, likely same on 32-bit)
- Values 3 and 4 are never statically written to offset 0x1d8

### Hallucinated Addresses (DO NOT USE)
| File | Claimed | Actual | Issue |
|------|---------|--------|-------|
| `haptic_payload.c` | TriggerHapticPulse at 0x013205a3 | 0x013205a3 is IClientTimeline dispatcher | String at 0x00ab33f0, not 0x00ab43f0 |
| `haptic_payload.c` | ForceSimpleHapticEvent at 0x01322dae | 0x01322dae is IClientVideo dispatcher | String at 0x00ab33b0, not 0x00ab43b0 |
| `haptic_payload.c` | CRumbleThread at 0x0111b370, string at 0x00aa5b00 | String is at 0x00aa4ae0 | Address off by ~0x1000 |

## Deliverables

1. **Steam haptics investigation** — Determine why 0x8F never appears on BLE, fix it
2. **ATT Server Spec Compliance** — Implement correctness improvements (one at a time, test each)
3. **Updated docs** — All findings documented with evidence and confidence levels
