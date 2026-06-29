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

In-game rumble works, but Steam-generated haptics do not. On a **clean connection** (stale state cleared):

- **In-game rumble**: Games that call `SDL_RumbleJoystick()` produce rumble on Neptune motors. Confirmed with Celeste hazard impacts. Full pipeline: Host game → SDL_RumbleJoystick → SDL_hid_write → kernel UHID → BlueZ hog-ll → ATT Write Request (0x12) → handle 0x0019 → _on_haptic_write → _forward_haptic_to_neptune → write /dev/hidraw3 → Neptune motors.
- **Steam-generated haptics**: Trackpad clicks, UI feedback haptics do NOT produce rumble. These come from Steam's internal haptic system, not from `SDL_RumbleJoystick()`. The Steam haptic path uses a different code path that does not reach the Neptune motors.
- The SET_SETTINGS notification hypothesis was **TESTED AND FAILED** (caused ghost inputs). It is NOT the blocker.

### What Was Fixed This Session

1. **Rumble format**: Fixed to match InputPlumber's PackedRumbleReport — `[0xeb, 0x09, 0x00, 0x00, 0x00, left_lo, left_hi, right_lo, right_hi]` padded to 64 bytes. Old format had wrong trailing bytes.
2. **Lizard mode commands**: NEPTUNE_LIZARD_OFF_CMDS had wrong Report ID prefix (`0x01 0x00` instead of direct `0x81`). InputPlumber analysis revealed the correct format.
3. **EVIOCGRAB**: Grabs event4/event5 at startup to prevent lizard mode evdev events from reaching KDE desktop.
4. **BlueZ hog-lib.c analysis**: Confirmed `forward_report()` uses ATT Write Request (0x12), not Write Command (0x52). Previous btmon filters for 0x52 missed actual writes.
5. **Manual write test**: Writing directly to `/dev/hidrawN` on host confirmed the UHID output path works end-to-end.

## Investigation: BlueZ hog-lib.c Analysis (COMPLETED 2026-06-29)

BlueZ 5.86 source obtained from kernel.org and analyzed. The haptics pipeline is now confirmed working for in-game rumble. Key findings:

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

### What Needs to Be Tested Next

1. **Investigate Steam-generated haptics** — Trackpad clicks and UI feedback haptics do NOT produce rumble. These come from Steam's internal haptic system, not from `SDL_RumbleJoystick()`. The Steam haptic path may use a different report type (e.g., 0x81-0x85) or a different code path entirely. A real SC2 btmon capture would reveal what reports Steam sends for UI haptics.
2. **Check btmon for ATT Write Request (0x12) to handle 0x0019** — Previous btmon filter for 0x52 may have missed actual writes. The enhanced Deck logging should capture incoming writes.
3. **Verify `find_report_by_rtype()` succeeds** — If it returns NULL, `forward_report()` silently drops the write. Could be caused by wrong Report Reference descriptor or missing output report registration in BlueZ's report list.

### Phase 4: Investigate Steam-Generated Haptics

The in-game rumble pipeline is confirmed working. The remaining question is why Steam-generated haptics (trackpad clicks, UI feedback) do NOT produce rumble.

**Key observation**: Steam schedules haptics (`CPulseHapticWorkItem`) but writes fail in 0.0ms for UI haptics, while game rumble via `SDL_RumbleJoystick()` works. This suggests Steam's internal haptic system uses a different code path or report type.

**Possible hypotheses (ranked by likelihood):**

1. **Steam uses report types 0x81-0x85 for UI haptics** — The SC2 protocol has 6 haptic report types (0x80-0x85). Games use 0x80 (rumble). Steam UI may use 0x81 (pulse), 0x82 (command), etc. Our `_on_haptic_write()` only handles 0x80.

2. **Steam's internal haptic path doesn't go through SDL_hid_write()** — Steam may have a direct HID write path that bypasses SDL, or uses a different interface entirely.

3. **Steam haptics need specific register values** — SET_SETTINGS configures registers that gate haptic behavior. If certain registers aren't set correctly, Steam may skip UI haptics.

**Testing approach:**
- For each hypothesis: predict what you'd observe IF true, make ONE change, test, evaluate
- Deploy changes via: `sshpass -p 'asdf' scp src/*.py deck@172.16.16.120:/tmp/sc2-spoof/src/`
- Restart service: `sshpass -p 'asdf' ssh deck@172.16.16.120 "echo asdf | sudo -S systemctl restart sc2-hogp"`
- Connect from host: `printf 'qwerasdf\n' | sudo -S bluetoothctl connect C2:12:34:56:78:9A`
- Check btmon: `printf 'qwerasdf\n' | sudo -S timeout 10 btmon -t 2>&1 | grep -E "Write|0x52|Error|SET_REPORT"`
- Check Deck logs: `sshpass -p 'asdf' ssh deck@172.16.16.120 "echo asdf | sudo -S journalctl -u sc2-hogp --since '2 min ago' --no-pager | grep -i 'haptic\|write.*0x0019\|SET_REPORT'"`

### Phase 5: Documentation and ATT Server Compliance

With in-game rumble working, the priority shifts to:

1. **Document the working haptic pipeline** — Ensure all markdown files reflect the current status
2. **ATT Server Spec Compliance** — Implement one at a time, test each:
   - Read Blob error code (0x01 → 0x07)
   - MTU caps on Read/Notify PDUs
   - PDU length validation
   - ATT permission checking (Read + Write Request only, NOT Write Command)
   - Fix diagnostic handle labels

## Important Rules

1. **Do NOT pair with pairing code** — Use `bluetoothctl connect` only. Pairing requires clicking "yes" on KDE dialog which needs human intervention. If pairing is needed, clear bond data and reconnect.

2. **One change at a time** — Never stack fixes. If Fix A doesn't work, revert it, then try Fix B.

3. **Evidence before conclusion** — Every finding must cite specific evidence. Tag with confidence level (Confirmed/Plausible/Speculative).

4. **Spawn subagents for research** — Don't read 500+ lines of BlueZ source in the main thread. Use explore subagents.

5. **Commit progress** — After each meaningful finding, commit: `git add -A && git commit -m "finding: <description>" && git push`

6. **Stale state is the #1 cause of mysterious failures** — Every test cycle: clear bond data, restart BlueZ, reconnect.

7. **In-game rumble works, Steam haptics do not** — Games calling `SDL_RumbleJoystick()` produce rumble. Steam-generated haptics (trackpad clicks, UI feedback) use a different code path that does not reach Neptune motors. See `docs/findings-backlog.md` for details.

## Deliverables by Morning

1. **Documented status** — All markdown files reflect current state: in-game rumble works, Steam haptics do not
2. **Steam haptics investigation** — Determine why trackpad clicks and UI feedback haptics do NOT produce rumble
3. **ATT Server Spec Compliance** — Implement correctness improvements (one at a time, test each)
4. **Updated docs** — All findings documented with evidence and confidence levels
