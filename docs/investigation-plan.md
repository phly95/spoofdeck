# Investigation Plan: Haptics Fix

## Core Rules

### 1. Evidence Before Conclusion

Every finding must cite specific evidence: a log line, a hex dump, a code reference. If you can't point to evidence, it's a hypothesis — tag it as such.

**Confidence levels** (use these in all findings):
- **Confirmed** — Directly observed in logs/code/capture
- **Plausible** — Consistent with evidence, alternatives exist
- **Speculative** — Inference from limited evidence

Bad: "SET_REPORT fails because the server doesn't handle Write Command."
Good: "On a clean connection (stale state cleared), btmon shows zero Write Command (0x52) packets. BlueZ hog-ll never attempts SET_REPORT."

### 2. Hypothesis Lifecycle

Every hypothesis must go through:
1. **Form** it (tag confidence)
2. **Predict** what you'd observe IF true
3. **Test** (one change at a time)
4. **Evaluate** (did prediction match?)
5. **Update** confidence

Never stack fixes. If Fix A doesn't work, revert it, then try Fix B.

### 3. One Change Per Test Cycle

Deploy one change, capture results, evaluate. Don't add diagnostic logging AND fix the notification AND change error codes simultaneously. You won't know which change helped.

---

## What We Know (Verified)

| Finding | Evidence | Confidence |
|---------|----------|------------|
| In-game rumble works via SDL_RumbleJoystick() | Celeste hazard impacts confirmed; full pipeline verified end-to-end | Confirmed |
| Steam-generated haptics (trackpad clicks, UI feedback) do NOT produce rumble | Tested with Steam UI; no rumble observed. These use a different code path. | Confirmed |
| Haptics path is `UHID_OUTPUT` -> `forward_report()`, NOT `UHID_SET_REPORT` -> `set_report()` | BlueZ 5.86 source analysis (2026-06-29), hog-lib.c lines 746-778 | Confirmed |
| `forward_report()` uses ATT Write Request (0x12), NOT Write Command (0x52) | Our CHR_REPORT has `GATT_CHR_PROP_WRITE`, hog-lib.c line 770 | Confirmed |
| `forward_report()` silently drops writes if `find_report_by_rtype()` returns NULL | hog-lib.c line 754: `DBG("Unable to find report")` + return | Confirmed |
| `find_report()` bug: uses `hog->flags` instead of `hog->uhid_flags` for numbered flag | hog-lib.c lines 698-701. Coincidentally works: `hog->flags`=0x02 matches `UHID_DEV_NUMBERED_OUTPUT_REPORTS`=0x02 | Confirmed |
| `bt_uhid_create()` doesn't set `ev.u.create2.flags` — kernel `report_numbered = false` | hog-lib.c lines 989-1019 | Confirmed |
| Rumble format matches InputPlumber's PackedRumbleReport | `[0xeb, 0x09, 0x00, 0x00, 0x00, left_lo, left_hi, right_lo, right_hi]` padded to 64 bytes | Confirmed |
| Lizard mode commands use direct 0x81 (no Report ID prefix) | NEPTUNE_LIZARD_OFF_CMDS in input_handler.py; EVIOCGRAB grabs event4/event5 | Confirmed |
| SET_SETTINGS notification hypothesis DISPROVEN | Test caused ghost inputs, reverted (2026-06-28) | Confirmed |
| `set_report()` is kernel-initiated (device probe), NOT triggered by Steam writes | BlueZ 5.86 source analysis, hog-lib.c lines 845-900 | Confirmed |
| `0x17252a0` is dead code (zero callers) | Multiple analysis methods agree | Confirmed |
| **0x8F gate (VERIFIED)**: `[esi+0x17c]` [64-bit: `[r15+0x208]`] at `0x0123e5fb` [64-bit: `0x10d4da0`] gates 0x8F dispatch. `YieldingRunTestProgram` at [NEEDS RE-ANALYSIS] [64-bit: `0x015677f4`] is the ONLY setter (instruction at `0x0178a140` [64-bit: `0x0156781c`]: `mov byte [esi+0x17c], 1`). On native, flag set during init → 0x8F dispatched. On BLE, flag stays 0 → 0x8F never dispatched. Dispatcher at [NEEDS RE-ANALYSIS] [64-bit: `0x015675a8`] branches on `[edi+0x1d8]` [64-bit: `[rdi+0x1d8]`]: state 1-2 → YieldingRunTestProgram path, state 3-4 → different path. **However, what 0x1d8 represents is UNVERIFIED** — may be graphics API type (1=GL, 2=Vulkan, 3/4=D3D12) not controller state. Values 3/4 never written as immediates. GDB watchpoint is the definitive test. | Native Deck strace capture (124 HIDIOCSFEATURE, 16 are 0x8F) + BLE ATT logs (0x8F never appears). | Confirmed (gate), Unverified (0x1d8 meaning) |
| **Controller IS registered on BLE**: serial "F0000-0000-00000000" accepted by Steam. "Skipping usage report" is normal. | Steam logs show "Auto-Registering controller: F0000-0000-00000000" | Confirmed |
| **BLE connection drops after ~30s** | Live test 2026-06-29: supervision timeout | Confirmed |
| **Native vs BLE GET_SERIAL differs**: Native write data `ae 15 01 05 12...`, BLE: `ae 15 04 00 34 5e...`. Our handler ignores write data. | strace capture vs ATT logs | Confirmed |

## What We Don't Know

> **⚠️ NOTE: All binary addresses below are from the 32-bit binary (`ubuntu12_32/steamclient.so`).** 64-bit equivalents from the old analysis are shown in `[64-bit: ...]` brackets. Addresses marked `[NEEDS RE-ANALYSIS]` have not been verified in the 32-bit binary. **Do NOT use 64-bit addresses for GDB or binary patching.**

| Question | Current Best Guess | What Would Confirm/Refute |
|----------|-------------------|--------------------------|
| Why does Steam retry GET_SERIAL 19+ times on BLE? | Native and BLE send different serial hashes. Steam may compute a hash from the write data and compare it to the response. | Test with native serial hash format to see if retry count drops. |
| What does `[rdi+0x1d8]` actually hold for BLE devices? | **UNVERIFIED** — May be graphics API type (1=GL, 2=Vulkan, 3/4=D3D12) instead of controller state. Values 3/4 never written as immediates. | GDB watchpoint on `[rdi+0x1d8]` during BLE connection init — 5-minute test vs hours of static analysis. |
| What triggers the call to [NEEDS RE-ANALYSIS] [64-bit: `0x015675a8`]? | Invoked indirectly via vtable dispatch during controller registration. Vtable is runtime-constructed. | GDB backtrace from breakpoint at [NEEDS RE-ANALYSIS] [64-bit: `0x015675a8`]. |
| Will the LD_PRELOAD patch work? | 55-65% probability. BUT first verify what [edi+0x1d8] holds — if it's not a controller state, the dispatcher logic may be different from what we think. | GDB watchpoint first, then LD_PRELOAD if dispatcher path is confirmed. |
| Why is [r12+0x08] BLE flag never read? | The handler sets this flag but it's never consumed. The BLE vs USB distinction may be made elsewhere (product ID dispatch, protobuf enum, etc.). | GDB trace on reads to handler+0x08 during connection init. |

---

## Investigation Steps

### Step 0: Clear Stale State (EVERY test cycle)

Before every deployment/test:
```bash
# Host
printf 'qwerasdf\n' | sudo -S rm -rf /var/lib/bluetooth/9C:B6:D0:8F:97:68/C2:12:34:56:78:9A
printf 'qwerasdf\n' | sudo -S rm -rf /var/lib/bluetooth/cache
printf 'qwerasdf\n' | sudo -S systemctl restart bluetooth
```
Then restart Deck service. This is NOT optional — stale state is the #1 cause of mysterious failures.

### Step 1: Examine Existing Evidence (Before Writing Any Code)

1. Open `scratch/btmon_handshake.txt`
2. Find ALL ATT Error Response (0x01) packets — extract error code, handle, request opcode
3. Find ALL ATT Write Request (0x12) packets — extract handle, data (**NOT just 0x52!**)
4. Find ALL ATT Write Command (0x52) packets — extract handle, data
5. Count: how many 0x12 per handle? How many 0x52 per handle? How many errors per error code?
6. Check specifically for 0x12 to handle 0x0019 — this is where `forward_report()` sends haptics

**This step is now partially resolved.** In-game rumble via `SDL_RumbleJoystick()` is confirmed working. The remaining question is why Steam-generated haptics (trackpad clicks, UI feedback) do NOT produce rumble.

### Step 2: Add Diagnostic Logging (One Change)

Add to `_handle_write_cmd()` AND `_handle_write()` in `att_server.py`:
- Log ALL incoming Write Request (0x12) packets: handle, data, timestamp
- Log ALL incoming Write Command (0x52) packets: handle, data, timestamp
- Log whether the write triggered a callback
- Log the callback result

**Key**: `forward_report()` uses ATT Write Request (0x12), NOT Write Command (0x52). We must log both opcodes to see if haptic writes arrive.

### Step 3: Deploy, Capture, Compare

1. Deploy updated code to Deck
2. Start btmon on host: `printf 'qwerasdf\n' | sudo -S btmon -t -w /tmp/btmon_capture.log &`
3. Connect from host: `bluetoothctl connect C2:12:34:56:78:9A`
4. Wait 30 seconds
5. Capture Deck logs
6. Compare btmon vs Deck logs — do they agree?

### Step 4: GDB Watchpoint on [edi+0x1d8] (RECOMMENDED NEXT STEP)

The root cause of the gate mechanism is fully verified: `[esi+0x17c]` [64-bit: `[r15+0x208]`] at `0x0123e5fb` [64-bit: `0x10d4da0`] stays 0 on BLE, so 0x8F is never dispatched. The only setter is `YieldingRunTestProgram` at `0x0178a140` [64-bit: `0x0156781c`], reached through a controller message dispatcher at [NEEDS RE-ANALYSIS] [64-bit: `0x015675a8`] that branches on `[edi+0x1d8]` [64-bit: `[rdi+0x1d8]`].

**However, what `[edi+0x1d8]` represents is UNVERIFIED.** Recent investigation found:
- The function at [NEEDS RE-ANALYSIS] [64-bit: `0x01559070`] writes `[object+0x1d8]` = graphics API type (1=GL, 2=Vulkan, 3=D3D12, 4=D3D12)
- Values 3 and 4 are NEVER written as immediate values to 0x1d8
- The BLE handler at [NEEDS RE-ANALYSIS] [64-bit: `0x010c4e0c`] sets `[ebp+0x08] = 1` (BLE flag, [64-bit: `[r12+0x08]`]) but this is NEVER READ
- The controller constructor reads `[parent+0x1B0]` into `[controller+0x1d8]`, but it gets overwritten later
- The vtable containing [NEEDS RE-ANALYSIS] [64-bit: `0x015675a8`] is runtime-constructed

**Meta-lesson: Static analysis produced contradictory findings. A 5-minute GDB watchpoint would resolve this definitively.**

**Recommended approach**: Set a GDB watchpoint on `[edi+0x1d8]` during BLE connection init:
1. Attach GDB to steamclient.so process (loads `ubuntu12_32/steamclient.so`, NOT `linux64/steamclient.so`)
2. Set watchpoint: `watch *(uint32_t*)(edi + 0x1d8)`
3. Trigger BLE connection
4. Observe what value is read by the dispatcher at [NEEDS RE-ANALYSIS] [64-bit: `0x015675a8`]
5. This reveals whether 0x1d8 is a controller state, graphics API type, or something else

**Expected outcomes:**
- **If value is 1-2**: The "state 1-2 vs 3-4" theory is confirmed. LD_PRELOAD patch is the next step.
- **If value is 3-4**: Confirms BLE gets different state. Need to understand WHY and how to change it.
- **If value is something else entirely**: The dispatcher logic is different from what static analysis suggests. Need to re-examine the branching.
- **If watchpoint never fires**: The dispatcher at [NEEDS RE-ANALYSIS] [64-bit: `0x015675a8`] may not be the right function. Need to trace how 0x8F dispatch actually works.

### Step 5: ~~SET_SETTINGS Notification~~ DISPROVEN

The SET_SETTINGS notification hypothesis was tested on 2026-06-28 and **failed**. Sending 45-byte ack notifications on handle 0x0033 caused ghost inputs (phantom button presses). The notification was reverted. This step is no longer applicable.

### Step 6: LD_PRELOAD Implementation (AFTER Step 4 GDB Verification)

**Prerequisite**: GDB watchpoint in Step 4 must confirm what `[edi+0x1d8]` holds and that the dispatcher at [NEEDS RE-ANALYSIS] [64-bit: `0x015675a8`] is the right function.

1. Build C library that patches `je [target]` at `0x0123e601` [64-bit: `0x10d4da6`] to `nop nop`
2. Deploy to Deck, test with `LD_PRELOAD=/path/to/libpatch.so`
3. If Steam haptics start working → done, commit the library
4. If Steam crashes → GDB watchpoint on `[esi+0x17c]` [64-bit: `[r15+0x208]`] reveals gate controller
5. If no change → secondary gate exists, continue investigation

---

## Rules for Subagents

1. **Ask for raw evidence, not conclusions**
   - Bad: "Analyze why SET_REPORT fails"
   - Good: "Find all ATT Error Response packets in btmon_handshake.txt, extract error codes, return as table"

2. **If a subagent states a conclusion, ask for the evidence**
   - "What specific log line supports that?"

3. **Delegate mechanical tasks, keep decisions in main thread**
   - Delegate: log parsing, SSH operations, file reading
   - Keep: code changes, investigation decisions, hypothesis ranking

---

## Recovery (When Things Break)

1. Clear bond data + restart BlueZ (host)
2. Restart Deck service
3. If Deck BT broken: restart bluetooth + re-apply config_bt.py
4. Nuclear: reboot host

---

*Last updated: 2026-06-30 (addresses converted from 64-bit to 32-bit equivalents)*
