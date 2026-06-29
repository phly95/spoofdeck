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

## What We Don't Know

| Question | Current Best Guess | What Would Confirm/Refute |
|----------|-------------------|--------------------------|
| Why do Steam-generated haptics not produce rumble? | Steam's internal haptic system uses a different code path than `SDL_RumbleJoystick()`. Trackpad clicks and UI feedback haptics do not reach Neptune motors. | A real SC2 btmon capture would show what reports Steam sends for UI haptics. |
| What report types does Steam use for UI haptics? | Possibly 0x81-0x85 (pulse, command, LFO, sweep, script) rather than 0x80 (rumble) | Check btmon for non-0x80 output reports during Steam UI interaction |
| Does `find_report_by_rtype()` succeed for in-game rumble? | Yes — confirmed by working end-to-end pipeline with Celeste | N/A — already confirmed |
| Do haptic writes reach our ATT server via 0x12? | Yes — confirmed by working end-to-end pipeline with Celeste | N/A — already confirmed |
| Is 0x8F the gate for Steam haptics? | 0x8F appears 16 times on native but NEVER on BLE. This may gate haptic dispatch. | Verify with `strings` on steamclient.so for "YieldingRunTestProgram". Binary analysis needed. |
| Does the GET_SERIAL write data affect haptics? | Native and BLE send different serial hashes. Our handler ignores write data. | Test with native serial hash format to see if haptics appear. |

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

### Step 4: Investigate Steam-Generated Haptics

In-game rumble is confirmed working. The remaining question is why Steam-generated haptics (trackpad clicks, UI feedback) do NOT produce rumble.

**New evidence from 2026-06-29 session:**
- Native Deck sends 0x8F (haptic feedback) 16 times during initialization. BLE NEVER sends 0x8F. **Confidence: Confirmed**
- This is the most significant difference between native and BLE haptics behavior.
- The 0x8F command may gate haptic dispatch in steamclient.so.

**If 0x8F is the gate:**
- We need to respond to 0x8F Feature Report writes on handle 0x0024.
- Our current handler returns zero-padded echo for unknown commands.
- Need to verify: does the response format matter, or is the write itself sufficient?

**If Steam uses report types 0x81-0x85 for UI haptics:**
- Our `_on_haptic_write()` only handles 0x80 (rumble). Add handlers for 0x81-0x85.
- Check btmon for non-0x80 output reports during Steam UI interaction.

**If Steam's internal haptic path doesn't go through SDL_hid_write():**
- Steam may have a direct HID write path that bypasses SDL.
- Check if Steam writes to a different device file.

**If Steam haptics need specific register values:**
- SET_SETTINGS configures registers that gate haptic behavior.
- Check if certain registers aren't set correctly for UI haptics.

### Step 5: ~~If Step 4 Fix Works — Add SET_SETTINGS Notification~~ DISPROVEN

The SET_SETTINGS notification hypothesis was tested on 2026-06-28 and **failed**. Sending 45-byte ack notifications on handle 0x0033 caused ghost inputs (phantom button presses). The notification was reverted. This step is no longer applicable.

**Updated priority**: After confirming in-game rumble works, focus on investigating Steam-generated haptics (trackpad clicks, UI feedback). These use a different code path than `SDL_RumbleJoystick()`.

### Step 6: Verify End-to-End

1. Deck logs show `_on_haptic_write()` being called (for ATT Write Request 0x12 to handle 0x0019) — **CONFIRMED for in-game rumble**
2. btmon shows ATT Write Request (0x12) to handle 0x0019 (NOT Write Command 0x52) — **CONFIRMED for in-game rumble**
3. Steam logs show haptic work items completing in > 0.0ms — **CONFIRMED for in-game rumble**
4. Audible rumble during gameplay — **CONFIRMED with Celeste hazard impacts**
5. **Remaining**: Steam-generated haptics (trackpad clicks, UI feedback) do NOT produce rumble — investigate in Step 4

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

*Last updated: 2026-06-29*
