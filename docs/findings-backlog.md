# Findings Backlog

> Current open problems, known facts, and what to try next.

---

## Registration Status: STABLE

No zombie disconnects, no errors. `BYieldingCompleteSteamControllerRegistration` completed. `CPulseHapticWorkItem` being created. Controller fully activated.

**Working**: Gamepad, trackpads, gyro, back buttons, standard HID input, in-game rumble via SDL_RumbleJoystick().
**Not working**: Steam-generated haptics (trackpad clicks, UI feedback) do NOT produce rumble.

---

## Haptic Pipeline Status

### What Works

**In-game rumble** — Games that call `SDL_RumbleJoystick()` produce rumble on Neptune motors. Confirmed with Celeste hazard impacts.

### What Doesn't Work

**Steam-generated haptics** — Trackpad clicks, UI feedback haptics, and other Steam-internal haptic events do NOT produce rumble. These use a different code path than `SDL_RumbleJoystick()`.

### Confirmed: Full Haptic Pipeline (In-Game Rumble)
```
Game → SDL_RumbleJoystick(low_freq, high_freq)
  → SDL_hid_write(device, buffer, 10)
  → write("/dev/hidrawN") → kernel hidraw
  → uhid_hid_output_raw() → UHID_OUTPUT event → BlueZ
  → forward_report() → find_report_by_rtype()
  → gatt_write_char() [ATT 0x12] → handle 0x0019
  → _on_haptic_write() → _forward_haptic_to_neptune()
  → write PackedRumbleReport to /dev/hidraw3
  → Neptune dual ERM motors vibrate
```

### SC2 Haptic Format (Report ID 0x80)
```
Byte 0:   0x80 (report ID)
Byte 1:   type (uint8) — 0 = HAPTIC_TYPE_OFF
Byte 2-3: intensity (uint16 LE)
Byte 4-5: left.speed (uint16 LE) — low_frequency_rumble
Byte 6:   left.gain (int8) — 0
Byte 7-8: right.speed (uint16 LE) — high_frequency_rumble
Byte 9:   right.gain (int8) — 0
```

### Rumble Format (InputPlumber's PackedRumbleReport)
```
64-byte struct: [0xeb, 0x09, 0x00, 0x00, 0x00, left_lo, left_hi, right_lo, right_hi, ...]
- 0xeb: TriggerRumbleCommand
- 0x09: report_size
- left_lo/hi: left motor intensity (uint16 LE)
- right_lo/hi: right motor intensity (uint16 LE)
```

### BlueZ hog-lib.c Analysis (Confirmed)

1. **Haptics path is `UHID_OUTPUT` → `forward_report()`** — NOT `UHID_SET_REPORT` → `set_report()`. `set_report()` is kernel-initiated (device probe), not triggered by Steam writes.
2. **`forward_report()` uses ATT Write Request (0x12), NOT Write Command (0x52)** — Our CHR_REPORT has `GATT_CHR_PROP_WRITE`, so `forward_report()` calls `gatt_write_char()` (0x12) instead of `gatt_write_cmd()` (0x52).
3. **`forward_report()` silently drops writes if report not found** — `find_report_by_rtype()` returns NULL when no matching output report is registered.
4. **`find_report()` bug: uses `hog->flags` instead of `hog->uhid_flags`** — Coincidence: `hog->flags`=0x02 matches `UHID_DEV_NUMBERED_OUTPUT_REPORTS`=0x02.
5. **`bt_uhid_create()` doesn't set `ev.u.create2.flags`** — Kernel `report_numbered = false`.

### Why Steam-Generated Haptics Don't Work

Steam-generated haptics use a different code path than `SDL_RumbleJoystick()`. The 0x8F haptic command is gated behind the `[esi+0x17c]` flag which never gets set on BLE (see Init Chain Stall below). The Steam haptic system does not produce output that reaches the Neptune motors through the SDL_hid_write path.

---

## Init Chain Stall (Root Cause of Missing Steam Haptics)

### The Problem

The controller initialization chain stalls because `CGetControllerInfoWorkItem::RunFunc` (0x01218840) calls vtable[5] (which internally calls `SDL_hid_read_timeout`) and gets **0 bytes**. It retries 51 × 100ms = 5.1 seconds, then fails. The init chain stalls before the haptic gate (`[esi+0x17c]`) is ever set.

### Verified Init Chain (Ghidra)
```
CHIDIOThread_Main (0x011b3a60) — creates worker threads
  → CWorkItemThread (0x011d5850) — processes HID read/write work items
    → CGetControllerInfoWorkItem::RunFunc (0x01218840)
      → vtable[5](param_2, buffer) — calls SDL_hid_read_timeout
      → Gets 0 bytes, sleeps 100ms, retries (iVar6++)
      → After 51 retries: "too many read failures"
      → After timeout: "CGetControllerInfoWorkItem::RunFunc: timeout"
    → EYldWaitForControllerDetails (0x011cee30)
      → 2-second timeout, returns success/timeout/error
```

### Notification Pipeline (BlueZ 5.86 source)
```
1. Our Python sends ATT Notification on handle 0x0012
2. report_value_cb() (hog-lib.c:323) strips 3-byte ATT header
3. bt_uhid_input(uhid, report->numbered ? report->id : 0, data, len)
4. If uhid->started is false: events QUEUED, not delivered to /dev/hidrawN
5. When UHID_START received: queue flushed → delivered to /dev/hidrawN
6. SDL_hid_read_timeout() reads from /dev/hidrawN
```

### Most Likely Cause of 0 Bytes

CGetControllerInfoWorkItem starts reading BEFORE notifications reach `/dev/hidrawN`. Possible reasons:
1. Input handler hasn't started sending yet (Neptune device not available)
2. CCCD writes haven't been processed (notification handles not registered)
3. UHID_CREATE2 → UHID_START takes too long

### What We Know Works

KDE detects the gamepad, game rumble flows. The notification pipeline DOES work eventually. The issue is timing during the first 5 seconds.

---

## The 0x8F Gate

The gate at `[esi+0x17c]` is **entirely in steamclient.so**, not firmware. Firmware handles 0x8F correctly as a standard command.

- **Gate SET** at `0x0178a140`: `mov byte [esi+0x17c], 1`
- **Gate CLEAR** at `0x0173ce00` (`RecvMsgAppStatus`): `*(param_2 + 0x17c) = 0`
- **Gate CHECK** at `0x0123e5fb`: `cmp byte [esi+0x17c], 0` → skips 0x8F dispatch if gate==0
- On native Deck, gate gets set during init → 0x8F commands are dispatched
- On BLE, gate stays 0 → 0x8F commands are never dispatched
- **Root cause**: Init chain stalls before gate is set (see above)

---

## Open Questions

1. **Why does Steam retry GET_SERIAL 19+ times on BLE?** Native write data: `ae 15 01 05 12...` vs BLE: `ae 15 04 00 34 5e...`. Steam may compute a hash from the write data and compare it to the response.
2. **What does `[esi+0x1d8]` actually hold for BLE devices?** UNVERIFIED — may be graphics API type (1=GL, 2=Vulkan, 3/4=D3D12) instead of controller state. Values 3/4 never written as immediates. GDB watchpoint is the definitive test.
3. **What triggers the call to the controller message dispatcher (0x015675a8)?** Invoked indirectly through vtable dispatch — vtable is runtime-constructed. What vtable entry does our BLE device use?
4. **Why is handler+0x08 BLE flag never read?** The handler at `0x010c4e0c` sets `[r12+0x08] = 1` (BLE flag) but it's never consumed. The BLE vs USB distinction may be made elsewhere.

---

## Next Steps

### 1. GDB Watchpoint on [esi+0x1d8] (RECOMMENDED NEXT STEP)

The root cause of the gate mechanism is verified: `[esi+0x17c]` stays 0 on BLE, so 0x8F is never dispatched. The only setter is `YieldingRunTestProgram`, reached through a dispatcher that branches on `[esi+0x1d8]`. But what `[esi+0x1d8]` represents is UNVERIFIED.

**Setup**:
1. Attach GDB to steamclient.so process (loads `ubuntu12_32/steamclient.so`, NOT `linux64/steamclient.so`)
2. Set watchpoint: `watch *(uint32_t*)(esi + 0x1d8)`
3. Trigger BLE connection
4. Observe what value is read by the dispatcher at `0x015675a8`

**Expected outcomes:**
- **Value 1-2**: State 1-2 theory confirmed → LD_PRELOAD patch is next step
- **Value 3-4**: BLE gets different state → need to understand WHY
- **Value something else**: Dispatcher logic differs from static analysis → re-examine branching
- **Watchpoint never fires**: Wrong function → trace how 0x8F dispatch actually works

**Alternative (zero-effort):** Capture Steam's `controller.txt` logs and `btmon` ATT traffic during a BLE connection. The controller.txt logs contain the exact error messages from CGetControllerInfoWorkItem, and btmon shows ATT traffic timing (when CCCDs are written, when our first notification arrives, when UHID_START fires). This can identify the timing gap without GDB.

### 2. LD_PRELOAD Patch for 0x8F Gate (AFTER GDB Verification)

**Prerequisite**: GDB watchpoint must confirm what `[esi+0x1d8]` holds.

1. Build C library that patches `je` at `0x0123e601` to `nop nop`
2. Deploy to Deck, test with `LD_PRELOAD=/path/to/libpatch.so`
3. If Steam haptics start working → done, commit the library
4. If Steam crashes → GDB watchpoint on `[esi+0x17c]` reveals gate controller
5. If no change → secondary gate exists, continue investigation

---

## ATT Server Correctness (Not Blocking, But Should Fix)

These are correctness improvements, not blockers. Fix one at a time, test between each.

1. **Command 0x85/0x8D routing swap** — `main_l2cap.py:556-564` has 0x85 and 0x8D swapped
2. **Write Command (0x52) doesn't process CCCD writes** — `att_server.py:445-454`
3. **Read/Write don't check attribute permissions** — `att_server.py:350-443`
4. **Diagnostic handle labels are wrong** — `att_server.py:504-510, 525-531`
5. **Read Blob uses wrong error code** — `att_server.py:379` (0x01 → 0x07)
6. **Feature Reports missing from Report Map** — `gatt_db.py`
7. **13 of 21 protocol commands unhandled** — fall through to zero-echo
8. **No MTU cap on Read/Notify PDUs** — `att_server.py:350-443`
9. **`_client_cccds` keyed by BLE address** — random addresses change across connections

---

*Last updated: 2026-07-01*
