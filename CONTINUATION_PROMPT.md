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

### Not Working
- **Steam-generated haptics** — Trackpad clicks, UI feedback haptics do NOT produce rumble. These come from Steam's internal haptic system, not from `SDL_RumbleJoystick()`. The Steam haptic path uses a different code path that does not reach Neptune motors.

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

## Next: Investigate Steam-Generated Haptics

The in-game rumble pipeline works. The remaining question is why Steam-generated haptics (trackpad clicks, UI feedback) do NOT produce rumble.

**Key observation**: Steam schedules haptics (`CPulseHapticWorkItem`) but writes fail in 0.0ms for UI haptics, while game rumble via `SDL_RumbleJoystick()` works.

**Native Deck vs BLE comparison (2026-06-29):**
- **Native Deck**: Steam sends 124 HIDIOCSFEATURE calls in 35 seconds. 0x8F (haptic feedback) appears 16 times on native but NEVER on BLE. **Confidence: Confirmed**
- **BLE**: Steam sends full command suite (0x87×55, 0x81×8, 0xAE×19, 0x83×1) but 0x8F never appears. GET_SERIAL retries 19 times on BLE vs 4 on native. **Confidence: Confirmed**
- **Controller IS registered** on BLE — serial "F0000-0000-00000000" accepted. **Confidence: Confirmed**
- **Native vs BLE GET_SERIAL write data differs** — different serial hashes. Our handler ignores write data and returns fixed synthetic serial. **Confidence: Confirmed**

**Possible hypotheses (ranked by likelihood):**

1. **0x8F haptic feedback command is the gate** — 0x8F appears 16 times on native but NEVER on BLE. This command may gate haptic dispatch. Subagent claims `[r15+0x208]` at `0x10d4da0` gates 0x8F dispatch, and `YieldingRunTestProgram` at `0x15677f4` is the ONLY function that sets this flag. **WARNING: `strings` on steamclient.so shows NO "YieldingRunTestProgram" string. This may be a hallucination. Needs verification. Confidence: Unverified**

2. **Steam uses report types 0x81-0x85 for UI haptics** — The SC2 protocol has 6 haptic report types (0x80-0x85). Games use 0x80 (rumble). Steam UI may use 0x81 (pulse), 0x82 (command), etc. Our `_on_haptic_write()` only handles 0x80.

3. **Steam's internal haptic path doesn't go through SDL_hid_write()** — Steam may have a direct HID write path that bypasses SDL, or uses a different interface entirely.

4. **Steam haptics need specific register values** — SET_SETTINGS configures registers that gate haptic behavior. If certain registers aren't set correctly, Steam may skip UI haptics.

**Testing approach:**
- For each hypothesis: predict what you'd observe IF true, make ONE change, test, evaluate
- Deploy changes via: `sshpass -p 'asdf' scp src/*.py deck@172.16.16.120:/tmp/sc2-spoof/src/`
- Restart service on Deck (see deployment workflow above)
- Connect from host: `printf 'qwerasdf\n' | sudo -S bluetoothctl connect C2:12:34:56:78:9A`
- Check btmon: `printf 'qwerasdf\n' | sudo -S timeout 10 btmon -t 2>&1 | grep -E "Write|0x52|Error|SET_REPORT"`
- Check Deck logs: `sshpass -p 'asdf' ssh deck@172.16.16.120 "echo asdf | sudo -S journalctl -u sc2-hogp --since '2 min ago' --no-pager | grep -i 'haptic\|write.*0x0019\|SET_REPORT'"`

## Important Rules

1. **One change at a time** — Never stack fixes. If Fix A doesn't work, revert it, then try Fix B.

2. **Evidence before conclusion** — Every finding must cite specific evidence. Tag with confidence level (Confirmed/Plausible/Speculative).

3. **Spawn subagents for research** — Don't read 500+ lines of BlueZ source in the main thread. Use explore subagents.

4. **Commit progress** — After each meaningful finding, commit: `git add -A && git commit -m "finding: <description>" && git push`

5. **Stale state is the #1 cause of mysterious failures** — Every test cycle: clear bond data, restart BlueZ, reconnect.

6. **In-game rumble works, Steam haptics do not** — Games calling `SDL_RumbleJoystick()` produce rumble. Steam-generated haptics (trackpad clicks, UI feedback) use a different code path that does not reach Neptune motors. See `docs/findings-backlog.md` for details.

## Reference: InputPlumber Analysis

InputPlumber source cloned to `/tmp/InputPlumber/`. Key findings:

| Topic | InputPlumber Approach | Our Current State |
|-------|----------------------|-------------------|
| Rumble format | `PackedRumbleReport` — `[0xeb, 0x09, 0x00, 0x00, 0x00, left_lo, left_hi, right_lo, right_hi]` padded to 64 bytes | ✅ Fixed to match |
| Lizard mode disable | `0x81` ClearDigitalMappings every 2 seconds + `0x87` register writes for permanent settings | ✅ Fixed format |
| Lizard mode evdev | `hid-steam` creates event4/event5 via `usbhid`, NOT via `hid-steam` module | ✅ EVIOCGRAB grabs them |
| Hidraw access | Opens `/dev/hidraw*` via `hidapi`, coexists with `hid-steam` driver | ✅ Same approach |

**Key insight from InputPlumber**: `ClearDigitalMappings` (0x81) only suppresses keyboard lizard mode for ~2 seconds. The controller firmware automatically re-enables it. Must re-send periodically. Mouse emulation (RPadMode) is disabled permanently via register writes.

## Reference: BlueZ hog-lib.c Analysis

BlueZ 5.86 source at `/tmp/bluez-5.86/profiles/input/hog-lib.c`.

| Function | Line | Purpose |
|----------|------|---------|
| `forward_report()` | 746-778 | Handles UHID_OUTPUT (haptics from Steam) — uses ATT Write Request (0x12) |
| `set_report()` | 845-900 | Handles UHID_SET_REPORT (kernel-initiated) — NOT the haptics path |
| `find_report_by_rtype()` | 740 | Finds report by type+ID |
| `find_report()` | 693-706 | BUG: uses `hog->flags` instead of `hog->uhid_flags` for numbered flag |

The haptics path is `UHID_OUTPUT` → `forward_report()`, NOT `UHID_SET_REPORT` → `set_report()`. SET_REPORT is kernel-initiated (device probe), not triggered by Steam writes.

## Deliverables

1. **Steam haptics investigation** — Determine why trackpad clicks and UI feedback haptics do NOT produce rumble
2. **ATT Server Spec Compliance** — Implement correctness improvements (one at a time, test each)
3. **Updated docs** — All findings documented with evidence and confidence levels
