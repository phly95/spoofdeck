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
| On clean connection, SET_REPORT is never attempted | Fresh btmon capture (2026-06-28) shows zero Write Commands (0x52) | Confirmed |
| btmon shows zero 0x52 packets for haptics | `scratch/btmon_handshake.txt` | Confirmed |
| Host sends only Write Requests (0x12) to handle 0x0024 every 3s (SET_SETTINGS 0x87) | Fresh btmon capture (2026-06-28) | Confirmed |
| Zero ATT errors on the wire — connection is clean | Fresh btmon capture (2026-06-28) | Confirmed |
| Steam schedules haptics but writes fail in 0.0ms | Steam log files | Confirmed |
| Our code skips SET_SETTINGS notification | `main_l2cap.py:522-525` (comment) | Confirmed |
| SET_SETTINGS notification hypothesis DISPROVEN | Test caused ghost inputs, reverted | Confirmed |
| GATT metadata for haptic output is correct | `gatt_db.py`, `main_l2cap.py` | Confirmed |
| `0x17252a0` is dead code (zero callers) | Multiple analysis methods agree | Confirmed |
| Earlier "487 errors" and ATT 0x0E errors were from stale state | Fresh connection shows zero errors | Confirmed |

## What We Don't Know

| Question | Current Best Guess | What Would Confirm/Refute |
|----------|-------------------|--------------------------|
| Why doesn't hog-ll attempt SET_REPORT? | Unknown — may be Steam not recognizing haptic support, or some initialization step failing silently | Examine BlueZ hog-lib.c for SET_REPORT trigger conditions; check if capabilities bitmask matches Steam's expectations |
| Do SET_REPORT writes reach our ATT server? | Unknown — they may fail in BlueZ before reaching L2CAP | Add diagnostic logging to `_handle_write_cmd()` to capture all incoming Write Command (0x52) packets |
| What opcode does hog-ll use for haptics? | Probably Write Command (0x52) — but zero observed on clean connection | Check BlueZ source or btmon of working device |
| Does BlueZ require SET_REPORT before output works? | Yes (per HID spec) — confirmed by the fact that output reports fail without it | Check BlueZ source for SET_REPORT prerequisite logic |
| Does SET_SETTINGS notification affect haptics? | **NO — disproven by test** | N/A — tested 2026-06-28, caused ghost inputs |

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
3. Find ALL Write Command (0x52) packets — extract handle, data
4. Count: how many 0x52 per handle? How many errors per error code?
5. Find the exact error code for SET_REPORT failures

**This step alone may reveal the root cause.** If the error is "Insufficient Authentication" vs "Attribute Not Found" vs "Write Not Permitted" — each points to a completely different fix.

### Step 2: Add Diagnostic Logging (One Change)

Add to `_handle_write_cmd()` in `att_server.py`:
- Log ALL incoming Write Command (0x52) packets: handle, data, timestamp
- Log whether the write triggered a callback
- Log the callback result

This tells us what the host is actually sending vs what we think it's sending.

### Step 3: Deploy, Capture, Compare

1. Deploy updated code to Deck
2. Start btmon on host: `printf 'qwerasdf\n' | sudo -S btmon -t -w /tmp/btmon_capture.log &`
3. Connect from host: `bluetoothctl connect C2:12:34:56:78:9A`
4. Wait 30 seconds
5. Capture Deck logs
6. Compare btmon vs Deck logs — do they agree?

### Step 4: Fix Based on Findings

**If SET_REPORT writes reach our ATT server:**
- Examine the error code in the ATT Error Response
- Check if the handle has write permissions in the GATT database

**If SET_REPORT writes never reach our ATT server (hog-ll fails upstream):**
- The issue is earlier in the BlueZ stack
- Check BlueZ hog-lib.c for SET_REPORT trigger conditions
- Check if the capabilities bitmask (0x4169bfff) matches what Steam expects
- Check if some initialization step fails silently before SET_REPORT is attempted

**If no 0x52 packets appear at all:**
- hog-ll isn't sending them
- The issue is earlier in the BlueZ stack
- Check if SET_REPORT succeeds first (it might be a prerequisite)

### Step 5: ~~If Step 4 Fix Works — Add SET_SETTINGS Notification~~ DISPROVEN

The SET_SETTINGS notification hypothesis was tested on 2026-06-28 and **failed**. Sending 45-byte ack notifications on handle 0x0033 caused ghost inputs (phantom button presses). The notification was reverted. This step is no longer applicable.

**Updated priority**: After fixing the basic write path (Step 4), focus on diagnosing why SET_REPORT fails — whether the writes reach our ATT server or fail upstream in BlueZ.

### Step 6: Verify End-to-End

1. Deck logs show `_on_haptic_write()` being called
2. btmon shows ATT Write Command (0x52) to handle 0x0019
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

*Last updated: 2026-06-28*
