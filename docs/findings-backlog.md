# Findings Backlog

> Current open problems, known facts, and what to try next.

---

## Registration Status: STABLE

Serial format `F0000-0000-00000000`. `BYieldingCompleteSteamControllerRegistration` completed. `CPulseHapticWorkItem` being created. Controller fully activated.

**"Deck Controller PCB Serial# invalid"** — cosmetic only. BLE PCB validation in `FUN_0122e4c0`; does NOT block registration.
**"Controller Serial# invalid"** — BLOCKING. `V_strncmp` check requires `serial[0]='F'` (0x46), `byte[2]=0x01` (success status).

**Working**: Gamepad, trackpads, gyro, back buttons, standard HID input, in-game rumble via SDL_RumbleJoystick().
**Not working**: Steam-generated haptics (trackpad clicks, UI feedback) do NOT produce rumble.

---

## Haptic Architecture

### Path 1: Firmware-Local Haptics (SC2 nRF52840 only)
Trackpad touch, button press, grip touch/detouch generate haptic feedback entirely within firmware.
- Modules: `haptics-sequencer-touchpad`, `haptics-sequencer-gri-v3`, `haptics_sequencer`
- Scripts are firmware-internal, selected by ID (host does NOT upload patterns)
- Triggered by firmware events (FUN_00015170 → FUN_0003347c)
- **Not available to SpoofDeck** — Deck's Neptune controller lacks SC2's haptic sequencer

### Path 2: Game Rumble via 0x80 (WORKS on any transport)
Games calling SDL_RumbleJoystick() → SDL_hid_write() → UHID → hog-ll → ATT Write Request → _on_haptic_write() → Neptune ERM motors
- Uses 0x80 output report (9 bytes)
- NOT gated by [esi+0x17c]
- Works on USB, Dongle, and BLE

### Path 3: Steam-Generated Haptics via 0x8F (USB/Dongle ONLY)
Steam UI → CPulseHapticWorkItem → 0x8F sub-command dispatcher → firmware haptic script trigger
- 0x8F is a multiplexed command envelope (sub-command byte selects haptic effect)
- Firmware receives 0x8F and plays the corresponding internal haptic script
- **BLOCKED on BLE by design** — see 0x8F Gate section below

### Confirmed: In-Game Rumble Pipeline
```
Game → SDL_RumbleJoystick(low_freq, high_freq)
  → SDL_hid_write(device, buffer, 10)
  → write("/dev/hidrawN") → kernel hidraw
  → uhid_hid_output_raw() → UHID_OUTPUT → BlueZ
  → forward_report() → gatt_write_char() [ATT 0x12] → handle 0x0019
  → _on_haptic_write() → _forward_haptic_to_neptune()
  → PackedRumbleReport to /dev/hidraw3 → Neptune ERM motors
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
```

### BlueZ hog-lib.c Analysis (Confirmed)
1. Haptics path is `UHID_OUTPUT` → `forward_report()` — NOT `UHID_SET_REPORT` → `set_report()`
2. `forward_report()` uses ATT Write Request (0x12), NOT Write Command (0x52)
3. `forward_report()` silently drops writes if report not found
4. `find_report()` bug: uses `hog->flags` instead of `hog->uhid_flags`
5. `bt_uhid_create()` doesn't set `ev.u.create2.flags`

---

## Init Chain Timing Fix

The init chain in CGetControllerInfoWorkItem::RunFunc stalls because SDL_hid_read_timeout gets 0 bytes. The fix sends multiple zero notifications when CCCDs are enabled to pre-fill the UHID queue:
- First notification is consumed by UHID device creation (UHID_CREATE2), not forwarded as UHID_INPUT2
- Subsequent notifications become UHID_INPUT2 and reach /dev/hidrawN
- 5 notifications sent with staggered delays (10-50ms) via threading to avoid blocking ATT thread
- Requires `import time as _time` and `import threading as _threading` (was broken when `time` was not imported at module level)

Note: Even with init chain completing, Steam haptics still don't work on BLE due to the 0x8F gate (see below).

---

## The 0x8F Gate (BLE Design Limitation, NOT a Bug)

The gate at `[esi+0x17c]` is entirely in steamclient.so. The gate CHECK at `0x0123e5fb` skips 0x8F dispatch when `[esi+0x17c] == 0`.

**This is a design decision, not a bug.** BLE controllers (PID 0x1303) get controller state 3-4 at `[rdi+0x1d8]`, which routes through a 16-byte allocation path that NEVER sets the gate. USB/Dongle controllers (PIDs 0x1302, 0x1304) get state 1-2, which routes through a 0x210-byte path (YieldingRunTestProgram) that DOES set `[esi+0x17c] = 1`.

| Transport | PID | State | Gate | 0x8F Dispatched? |
|-----------|-----|-------|------|:-----------------:|
| USB | 0x1302 | 1-2 | Open | YES |
| Dongle/Puck | 0x1304 | 1-2 | Open | YES |
| BLE direct | 0x1303 | 3-4 | Closed | NO |

**A real SC2 over BLE direct also does NOT get Steam haptics.** The SC2 only gets haptics through the Puck dongle, which presents as USB (state 1-2).

Native Deck capture (35s): 16× 0x8F commands. BLE capture: 0× 0x8F commands.

---

## Previously Open Questions (Resolved)

1. ~~Why does Steam retry GET_SERIAL 19+ times?~~ — GET_SERIAL byte[2] must be 0x01 (success status). Values 0x00 or 0x04 trigger "Controller Serial# invalid" (BLOCKING). Serial[0] must be 'F' (0x46) per V_strncmp with count=1 at 0x10c29b3.
2. ~~What does [esi+0x160] hold for BLE?~~ — Confirmed: BLE controllers get state 3-4 at [rdi+0x1d8], which routes to the 16-byte allocation path that never opens the haptic gate.
3. What triggers the controller message dispatcher (0x015675a8)? — Invoked through vtable dispatch; vtable is runtime-constructed.
4. Why is handler+0x08 BLE flag never read? — BLE vs USB distinction made elsewhere in PID dispatch table.

---

## Next Steps

### 1. LD_PRELOAD Patch for 0x8F Gate (RECOMMENDED)

The only remaining option for Steam haptics on BLE. Gate CHECK at `0x0123e5fb` can be patched with `nop nop` to unconditionally dispatch 0x8F commands.

**Probability**: 55-65% — the init chain timing fix is implemented and working, so the gate is the only remaining barrier.

1. Build C library that patches `je` at `0x0123e601` to `nop nop`
2. Deploy to Deck, test with `LD_PRELOAD=/path/to/libpatch.so`
3. If Steam haptics start working → done, commit the library
4. If Steam crashes → secondary gate exists, continue investigation
5. If no change → haptics pipeline blocked elsewhere, re-examine

### 2. ATT Server Spec Compliance (Not Blocking)

These are correctness improvements, not blockers. Fix one at a time, test between each.

1. Read Blob error code (0x01 → 0x07)
2. MTU caps on Read/Notify PDUs
3. PDU length validation
4. ATT permission checking
5. Diagnostic handle labels

### 3. Full Firmware Dump

`ibex_firmware.bin` is 33.4% of nRF52840's 1MB flash. Command descriptors at 0x59b10–0x5a332 beyond the dump. J-Link/SWD needed for full flash dump and further firmware RE.

---

*Last updated: 2026-07-02*
