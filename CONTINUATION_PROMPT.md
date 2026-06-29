# SC2 BLE Spoof — Autonomous Haptics Investigation

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

## The Problem

Everything works except haptics. On a **clean connection** (stale state cleared):

- Host sends only Write Requests (0x12) to handle 0x0024 (SET_SETTINGS 0x87) every 3 seconds
- **Zero Write Commands (0x52)** — host never sends haptic output reports
- **Zero SET_REPORT attempts** — hog-ll never tries to configure output reports
- Steam schedules haptics (`CPulseHapticWorkItem`) but write completes in 0.0ms (rejected at kernel level)

The SET_SETTINGS notification hypothesis was **TESTED AND FAILED** (caused ghost inputs). It is NOT the blocker.

The root cause is: **hog-ll's `forward_report()` path is the haptics mechanism, but writes may not be reaching our ATT server, OR `find_report_by_rtype()` is returning NULL and silently dropping them.**

## Investigation: BlueZ hog-lib.c Analysis (COMPLETED 2026-06-29)

BlueZ 5.86 source obtained from kernel.org and analyzed. Key findings:

### Critical Finding: Haptics Path is `UHID_OUTPUT` → `forward_report()`, NOT `UHID_SET_REPORT`

The haptics path when Steam writes to `/dev/hidrawN`:
```
Steam → SDL_hid_write() → write("/dev/hidrawN") → kernel hidraw
  → uhid_hid_output_raw() → UHID_OUTPUT event → BlueZ
  → forward_report() → find_report_by_rtype() → gatt_write_char/gatt_write_cmd
  → ATT Write Request (0x12) or Write Command (0x52) → our ATT server
```

**NOT** `UHID_SET_REPORT` → `set_report()`. SET_REPORT is kernel-initiated (device probe), not triggered by Steam writes.

### Key Code References (hog-lib.c)

| Function | Line | Purpose |
|----------|------|---------|
| `forward_report()` | 746-778 | Handles UHID_OUTPUT (haptics from Steam) |
| `set_report()` | 845-900 | Handles UHID_SET_REPORT (kernel-initiated) |
| `find_report_by_rtype()` | 740 | Finds report by type+ID |
| `find_report()` | 693-706 | Searches report list, **BUG: uses `hog->flags` instead of `hog->uhid_flags` for numbered flag** |
| `report_cmp()` | 674-685 | Compares reports, **ignores ID when numbered=false** |
| `uhid_create()` | 989-1019 | Creates UHID device, registers callbacks |
| `report_map_read_cb()` | 1054 | Called after Report Map read, triggers uhid_create() |

### Forward Report Flow (lines 746-778)

```c
forward_report(uhid, user_data):
  1. ev = bt_uhid_get_event(uhid)           // Get UHID_OUTPUT event
  2. report = find_report_by_rtype(hog,      // Find matching report
       HOG_REPORT_TYPE_OUTPUT,
       ev->u.output.numbered,               // From kernel (false for our device)
       ev->u.output.id)                     // 0x80
  3. if (!report) → DBG("Unable to find report") + return  // SILENT DROP
  4. if (hog->attrib == NULL) → return      // Connection down
  5. Strip Report ID if numbered
  6. Write to BLE device:
     - if properties & GATT_CHR_PROP_WRITE → gatt_write_char() [ATT 0x12]
     - else if properties & GATT_CHR_PROP_WRITE_WITHOUT_RESP → gatt_write_cmd() [ATT 0x52]
```

**CRITICAL**: Our CHR_REPORT has BOTH properties (0x0E), so it uses `gatt_write_char()` → **ATT Write Request (0x12)**, NOT Write Command (0x52).

### Previous btmon Filter Was Wrong

The btmon filter looked for 0x52 (Write Command), but `forward_report()` uses 0x12 (Write Request) because our CHR_REPORT has `GATT_CHR_PROP_WRITE`. **We may have missed actual writes!**

### Find Report Bug (line 698-701)

```c
find_report(hog, type, numbered, id):
  if (type == HOG_REPORT_TYPE_OUTPUT)
    numbered = !!(hog->flags & UHID_DEV_NUMBERED_OUTPUT_REPORTS);
  // hog->flags = 0x02 (HID Info byte 3 = "Normally Connectable")
  // UHID_DEV_NUMBERED_OUTPUT_REPORTS = 0x02 (bit 1)
  // Result: numbered = true (COINCIDENCE!)
```

This bug means `numbered=true` for all output reports, which affects how `report_cmp()` matches (line 677-685).

### Set Report Flow (lines 845-900) — NOT the haptics path

`set_report()` is triggered by kernel HID core, NOT by Steam writes. It handles `UHID_SET_REPORT` events. This is for device configuration (LED states, etc.), not for sending haptic output data.

### Why SET_REPORT Was Blamed

Previous analysis conflated two different things:
1. `UHID_SET_REPORT` — kernel-initiated, for device configuration
2. `UHID_OUTPUT` — host-initiated, for sending output data (haptics)

The "output report path" for haptics is `UHID_OUTPUT`, not `UHID_SET_REPORT`. The kernel doesn't need SET_REPORT to succeed before allowing output writes.

### What Needs to Be Tested

1. **Check for ATT Write Request (0x12) to handle 0x0019** in btmon, NOT just 0x52
2. **Check Deck logs for "Write Request: handle=0x0019"** — the enhanced logging should capture this
3. **Manually test UHID output path** — write to `/dev/hidrawN` on host, check if write reaches Deck
4. **If no writes arrive** — the issue is upstream (kernel UHID or BlueZ forward_report not being called)

### Phase 4: Test Hypotheses

Based on Phase 2 findings, form hypotheses and test them one at a time:

**Possible hypotheses (ranked by likelihood):**

1. **hog-ll doesn't SET_REPORT because output reports aren't enabled in uhid** — The uhid device setup might not advertise output report capability. Check `bt_uhid_set_report_size()` or similar.

2. **hog-ll requires SET_PROTOCOL before SET_REPORT** — The HID Control Point (handle 0x0010) might need a specific protocol mode set first. Check if our server handles Control Point writes correctly.

3. **hog-ll needs the Report Map to be read before attempting SET_REPORT** — If the Report Map read fails or returns wrong data, hog-ll might skip output report configuration.

4. **Steam/SDL doesn't request haptics because capabilities bitmask is wrong** — The GET_ATTRIBUTES response returns `0x4169bfff`. Check if bit 37 (haptics) is set. If not, Steam might skip haptic initialization.

5. **hog-ll only SET_REPORTs after receiving specific SET_SETTINGS** — Steam might need to write certain settings registers before hog-ll enables output. Check if our SET_SETTINGS handler stores values correctly.

**Testing approach:**
- For each hypothesis: predict what you'd observe IF true, make ONE change, test, evaluate
- Deploy changes via: `sshpass -p 'asdf' scp src/*.py deck@172.16.16.120:/tmp/sc2-spoof/src/`
- Restart service: `sshpass -p 'asdf' ssh deck@172.16.16.120 "echo asdf | sudo -S systemctl restart sc2-hogp"`
- Connect from host: `printf 'qwerasdf\n' | sudo -S bluetoothctl connect C2:12:34:56:78:9A`
- Check btmon: `printf 'qwerasdf\n' | sudo -S timeout 10 btmon -t 2>&1 | grep -E "Write|0x52|Error|SET_REPORT"`
- Check Deck logs: `sshpass -p 'asdf' ssh deck@172.16.16.120 "echo asdf | sudo -S journalctl -u sc2-hogp --since '2 min ago' --no-pager | grep -i 'haptic\|write.*0x0019\|SET_REPORT'"`

### Phase 5: If No Writes Arrive on handle 0x0019

If the enhanced logging shows NO writes to handle 0x0019 (neither 0x12 nor 0x52):

1. **Check if UHID device is created** — `ls -la /dev/hidraw*` on host. If no hidraw device exists, the UHID device was never created.

2. **Check if Steam writes to /dev/hidrawN** — Use `strace` on Steam or write directly:
   ```bash
   sudo bash scripts/test_haptic_write.sh /dev/hidrawN
   ```
   If the manual write succeeds but Steam's writes don't, the issue is in Steam's haptic scheduling.

3. **Check BlueZ logs** — Look for `forward_report` or `Unable to find report` messages. BlueZ's `DBG()` is usually compiled out, but `error()` messages should appear.

4. **Check kernel UHID logs** — `dmesg | grep -i uhid` for any UHID errors.

5. **Verify Report Map parsing** — BlueZ's hog-lib.c parses the Report Map during GATT discovery. If parsing fails, reports are never added to the list and `find_report_by_rtype()` returns NULL. Check for any parsing errors in BlueZ logs.

## Important Rules

1. **Do NOT pair with pairing code** — Use `bluetoothctl connect` only. Pairing requires clicking "yes" on KDE dialog which needs human intervention. If pairing is needed, clear bond data and reconnect.

2. **One change at a time** — Never stack fixes. If Fix A doesn't work, revert it, then try Fix B.

3. **Evidence before conclusion** — Every finding must cite specific evidence. Tag with confidence level (Confirmed/Plausible/Speculative).

4. **Spawn subagents for research** — Don't read 500+ lines of BlueZ source in the main thread. Use explore subagents.

5. **Commit progress** — After each meaningful finding, commit: `git add -A && git commit -m "finding: <description>" && git push`

6. **Stale state is the #1 cause of mysterious failures** — Every test cycle: clear bond data, restart BlueZ, reconnect.

7. **The answer is likely in hog-lib.c** — The `hog_set_report()` function, the `hog_halt()` function, and the initialization sequence are the key areas.

## Deliverables by Morning

1. **Root cause** — Why doesn't hog-ll attempt SET_REPORT on the clean connection?
2. **Fix** — If fixable, implement and deploy
3. **If not fixable** — Document exactly why (BlueZ limitation, hardware limitation, etc.) and what workaround might exist
4. **Updated docs** — All findings documented with evidence and confidence levels
