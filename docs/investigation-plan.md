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
| Haptics path is `UHID_OUTPUT` -> `forward_report()`, NOT `UHID_SET_REPORT` -> `set_report()` | BlueZ 5.86 source analysis (2026-06-29), hog-lib.c lines 746-778 | Confirmed |
| `forward_report()` uses ATT Write Request (0x12), NOT Write Command (0x52) | Our CHR_REPORT has `GATT_CHR_PROP_WRITE`, hog-lib.c line 770 | Confirmed |
| `forward_report()` silently drops writes if `find_report_by_rtype()` returns NULL | hog-lib.c line 754: `DBG("Unable to find report")` + return | Confirmed |
| `find_report()` bug: uses `hog->flags` instead of `hog->uhid_flags` for numbered flag | hog-lib.c lines 698-701. Coincidentally works: `hog->flags`=0x02 matches `UHID_DEV_NUMBERED_OUTPUT_REPORTS`=0x02 | Confirmed |
| `bt_uhid_create()` doesn't set `ev.u.create2.flags` — kernel `report_numbered = false` | hog-lib.c lines 989-1019 | Confirmed |
| Previous btmon filter for 0x52 may have missed actual writes | `forward_report()` uses 0x12 (Write Request), not 0x52 | Confirmed |
| SET_SETTINGS notification hypothesis DISPROVEN | Test caused ghost inputs, reverted (2026-06-28) | Confirmed |
| `set_report()` is kernel-initiated (device probe), NOT triggered by Steam writes | BlueZ 5.86 source analysis, hog-lib.c lines 845-900 | Confirmed |
| On clean connection, zero Write Commands (0x52), zero SET_REPORT attempts, only Write Requests (0x12) to handle 0x0024 every 3s | Fresh btmon capture (2026-06-28) | Confirmed |
| Steam schedules haptics but writes fail in 0.0ms | Steam log files | Confirmed |
| Our code skips SET_SETTINGS notification | `main_l2cap.py:522-525` (comment) | Confirmed |
| GATT metadata for haptic output is correct | `gatt_db.py`, `main_l2cap.py` | Confirmed |
| `0x17252a0` is dead code (zero callers) | Multiple analysis methods agree | Confirmed |

## What We Don't Know

| Question | Current Best Guess | What Would Confirm/Refute |
|----------|-------------------|--------------------------|
| Do haptic writes reach our ATT server via 0x12? | Unknown — `forward_report()` uses 0x12 (Write Request), but we only filtered btmon for 0x52. Previous captures may have missed writes. | Check btmon for ATT Write Request (0x12) to handle 0x0019. Enhanced Deck logging should capture incoming writes. |
| Does `find_report_by_rtype()` succeed? | Unknown — if it returns NULL, `forward_report()` silently drops the write. Could be caused by wrong Report Reference descriptor or missing output report registration in BlueZ's report list. | Add logging to `_on_haptic_write()` to confirm if writes arrive. Check BlueZ report list initialization. |
| Does BlueZ require SET_REPORT before output works? | **Previously assumed yes, but uncertain** — `set_report()` is kernel-initiated, not host-initiated. The kernel may not need SET_REPORT to succeed before allowing `UHID_OUTPUT` events. | Test: manually write to `/dev/hidrawN` on host, check if write reaches Deck. |
| Does SET_SETTINGS notification affect haptics? | **NO — disproven by test** | N/A — tested 2026-06-28, caused ghost inputs |
| Why does Steam not schedule haptics? | Steam DOES schedule haptics (`CPulseHapticWorkItem` in logs) but writes fail in 0.0ms. The issue is at the kernel/BlueZ level, not Steam scheduling. | Test manual write to `/dev/hidrawN` to bypass Steam scheduling. |

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

**This step alone may reveal the root cause.** Previous btmon filters only checked for 0x52 (Write Command), but `forward_report()` uses 0x12 (Write Request) because our CHR_REPORT has `GATT_CHR_PROP_WRITE`. We may have missed actual haptic writes.

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

### Step 4: Fix Based on Findings

**If haptic writes (0x12 to handle 0x0019) reach our ATT server:**
- Check if `_on_haptic_write()` is being called
- Check if `find_report_by_rtype()` succeeds in BlueZ (may need BlueZ debug logging)
- The issue is in BlueZ's `forward_report()` -> `find_report_by_rtype()` returning NULL

**If haptic writes never reach our ATT server:**
- The issue is in BlueZ's `forward_report()` not being called at all
- Check if `UHID_OUTPUT` events are generated by the kernel
- Check if BlueZ's uhid callback is registered correctly
- Manually test: write to `/dev/hidrawN` on host, check if write reaches Deck

**If SET_REPORT (0x52) appears but no haptic writes (0x12):**
- SET_REPORT is kernel-initiated (device probe), not host-initiated
- The absence of SET_REPORT means the kernel hasn't probed the device for reports
- This may or may not affect `UHID_OUTPUT` — test manually

### Step 5: ~~If Step 4 Fix Works — Add SET_SETTINGS Notification~~ DISPROVEN

The SET_SETTINGS notification hypothesis was tested on 2026-06-28 and **failed**. Sending 45-byte ack notifications on handle 0x0033 caused ghost inputs (phantom button presses). The notification was reverted. This step is no longer applicable.

**Updated priority**: After confirming whether haptic writes reach the ATT server (Step 4), focus on the `forward_report()` -> `find_report_by_rtype()` path. If writes arrive but are silently dropped, the issue is in BlueZ's report matching logic.

### Step 6: Verify End-to-End

1. Deck logs show `_on_haptic_write()` being called (for ATT Write Request 0x12 to handle 0x0019)
2. btmon shows ATT Write Request (0x12) to handle 0x0019 (NOT Write Command 0x52)
3. Steam logs show haptic work items completing in > 0.0ms
4. (Optional) Audible rumble during gameplay

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
