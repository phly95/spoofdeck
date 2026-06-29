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
- **Steam-generated haptics** — Trackpad clicks, UI feedback haptics do NOT produce rumble. 0x8F never appears on BLE. Root cause verified: `[r15+0x208]` at `0x10d4da0` stays 0, gate skips 0x8F dispatch.

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

### Primary Hypothesis: `[r15+0x208]` Gate (VERIFIED)

**The gate at `0x10d4da0`:**
```asm
0x010d4da0: cmp byte [r15 + 0x208], 0    ; Check HID output path established flag
0x010d4da8: movzx eax, byte [r15 + 0xe1]
0x010d4db0: je 0x10d4fd0                ; If flag==0 → SKIP entire vtable dispatch
```

**Only ONE instruction sets this flag to 1:**
```
0x0156781c: mov byte [r15+0x208], 1    ; in YieldingRunTestProgram
```

**`YieldingRunTestProgram` at `0x015677f4` (VERIFIED):**
1. Allocates 0x210-byte state machine object
2. Calls `0x156d6a0` (HID device init)
3. **Sets `[r15+0x208] = 1`** ← THE GATE
4. Starts retry timer
5. Registers with controller system

**Why it doesn't run on BLE (UPDATED 2026-06-29):** The function at `0x015675a8` (18,300 bytes, 52 basic blocks) is a **controller message dispatcher** that branches on `[rdi+0x1d8]` (controller state/type). If state is 1-2, it takes the path that includes `YieldingRunTestProgram`. If state is 3-4, it takes a different path. On BLE, the controller state is different, so the `YieldingRunTestProgram` path is never taken.

**IMPORTANT CLARIFICATION:** The `[reg+0x1b0] = 1` flag found at `0x15e2xxx` addresses is from SteamOS **update management** functions (YieldingCheckForUpdateBIOS, YieldingCheckForUpdateOS, BYieldingRunAPIJob, etc.) — completely unrelated to controllers. The `0x156d6a0` function they call is a **general-purpose job context allocator**, not HID-specific.

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

1. **LD_PRELOAD patch for 0x8F gate (RECOMMENDED)** — Patch `je 0x10d4fd0` at `0x10d4da6` to `nop nop` at runtime. This forces 0x8F dispatch regardless of `[r15+0x208]` gate. 55-65% probability of working. If it crashes, GDB watchpoint reveals what gate controls. If it works, Steam haptics (trackpad clicks, UI feedback) will flow to Neptune motors.
2. **Why does Steam retry GET_SERIAL 19+ times on BLE?** Our handler returns valid response with 'F'-prefixed serial. Is Steam checking the write data hash? The native Deck write data has `01 05 12 00 00 02` at bytes 2-7, while BLE has `04 00 34 5e bc e8`. Steam might compute a hash from the write data and compare it to the response.
3. **What controller state does `[rdi+0x1d8]` hold for BLE devices?** If it's 3-4 instead of 1-2, `YieldingRunTestProgram` is never reached. This is a controller type/state field set during device initialization.
4. **What triggers the call to `0x015675a8`?** It's invoked indirectly (no direct `call` in binary) — likely through a vtable dispatch set up during controller registration. What vtable entry does our BLE device use?

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

### Verified Addresses
| Address | Function/Label | Status |
|---------|---------------|--------|
| `0x015677f4` | YieldingRunTestProgram | **VERIFIED** — string at 0x00d6d17b |
| `0x0156781c` | `mov byte [r15+0x208], 1` | **VERIFIED** — the only write that enables 0x8F |
| `0x010d4da0` | Gate check: `cmp byte [r15+0x208], 0` | **VERIFIED** |
| `0x010d4e6c` | Feature report state machine | **VERIFIED** |
| `0x010d4e14` | vtable[0x10] dispatch | **VERIFIED** |
| `0x026b1ac0` | V_strncmp (serial validation) | **VERIFIED** — count=1, checks byte[0]=='F' |

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
