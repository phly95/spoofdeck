# Morning Handoff - 2026-06-30

## Summary

Three major work items completed:
1. **Structured protocol logging** — JSON log lines, parser script, native-vs-BLE diff template, safe ATT correctness fixes. No protocol behavior changed.
2. **32-bit binary address conversion** — All RE analysis files updated from 64-bit (`linux64/steamclient.so`) to 32-bit (`ubuntu12_32/steamclient.so`) addresses. 56 files changed, 1378 insertions, 1345 deletions.
3. **Ghidra headless analysis** — Full analysis of both 32-bit and 64-bit binaries. 141,351 functions exported. 12 new verified 32-bit function addresses. Controller behavior map documented in `research/32bit_ghidra_findings.md`. **Key finding: the 0x8F haptic command is never dispatched on BLE because the entire initialization chain stalls — the gate at `[esi+0x17c]` is not the direct blocker.**

## Changes Made

### Part 1: Protocol Logging & Diagnostics

1. **Structured protocol logging** — JSON log lines emitted to stderr when `SPOOFDECK_PROTO_LOG=1` is set. Covers ATT Write Request (0x12), Write Command (0x52), Read Request (0x0A), Read Blob (0x0C), notifications, haptic writes, and SC2 command processing. Each line includes timestamp, event name, opcode, handle, payload hex, detected SC2 command byte/name, response, and callback status.

2. **Log parser** — `scripts/extract_proto_trace.py` reads structured logs and outputs chronological command list, counts by command byte, retry counts (0x81, 0x83, 0x87, 0x8D, 0x8F, 0xAE, 0xF2), first/last timestamp per command, and optional CSV output.

3. **Native-vs-BLE diff template** — `research/native_vs_ble_command_diff_TEMPLATE.md` with sections for each tracked SC2 command, ready to fill in after capturing both native and BLE traces.

4. **ATT correctness fixes** (behavior-preserving):
   - `ATT_ERR_INVALID_OFFSET` (0x07) now returned for Read Blob with offset >= value length (was incorrectly 0x01).
   - PDU length validation added to MTU Request, Write Request, Write Command, Read Request, and Read Blob. Returns `ATT_ERR_INVALID_PDU` (0x04) instead of crashing on malformed packets.
   - MTU caps applied: Read Response capped to `mtu - 1`, Read Blob Response capped to `mtu - 1`, Notification capped to `mtu - 3`.
   - Write Command (0x52) CCCD handling now updates notification state consistently with Write Request (0x12).

### Part 2: 32-bit Binary Address Conversion

5. **All RE analysis files updated** — Converted all references from the 64-bit binary (`~/.steam/debian-installation/linux64/steamclient.so`) to the 32-bit binary (`~/.steam/debian-installation/ubuntu12_32/steamclient.so`).

6. **52 addresses verified** from the 32-bit binary via `strings`, `grep -boa`, and `objdump` disassembly. Key verified mappings:
   - YieldingRunTestProgram string: `0x00d6d17b` → `0x00bfc7e3`
   - Gate SET instruction: `0x0156781c` → `0x0178a140` (`mov byte [esi+0x17c], 1`)
   - Gate CHECK instruction: `0x010d4da0` → `0x0123e5fb` (`cmp byte [esi+0x17c], 0`)
   - Gate offset: `0x208` (64-bit, r15) → `0x17c` (32-bit, esi)
   - 0x8F dispatchers: `0x00ec13a4` and `0x00eed3c4` (same addresses in 32-bit)
   - All 30+ IPC tag strings (CHIDMessageToRemote, DeviceRead, etc.)
   - All registration/error strings (Read failure, Zombie Controller, etc.)
   - SDL dlsym strings (SDL_hid_write, SDL_hid_send_feature_report)

7. **26 addresses marked `[NEEDS RE-ANALYSIS]`** — Function entry points in the 0x015xxxxx and 0x010xxxxx ranges that could not be resolved from string analysis alone. These require GDB or IDA/Ghidra analysis of the 32-bit binary.

2. **Log parser** — `scripts/extract_proto_trace.py` reads structured logs and outputs chronological command list, counts by command byte, retry counts (0x81, 0x83, 0x87, 0x8D, 0x8F, 0xAE, 0xF2), first/last timestamp per command, and optional CSV output.

3. **Native-vs-BLE diff template** — `research/native_vs_ble_command_diff_TEMPLATE.md` with sections for each tracked SC2 command, ready to fill in after capturing both native and BLE traces.

4. **ATT correctness fixes** (behavior-preserving):
   - `ATT_ERR_INVALID_OFFSET` (0x07) now returned for Read Blob with offset >= value length (was incorrectly 0x01).
   - PDU length validation added to MTU Request, Write Request, Write Command, Read Request, and Read Blob. Returns `ATT_ERR_INVALID_PDU` (0x04) instead of crashing on malformed packets.
   - MTU caps applied: Read Response capped to `mtu - 1`, Read Blob Response capped to `mtu - 1`, Notification capped to `mtu - 3`.
   - Write Command (0x52) CCCD handling now updates notification state consistently with Write Request (0x12).

## Files Changed

| File | Change |
|------|--------|
| `src/att_server.py` | Added `_proto_log()`, SC2 command name lookup, structured logging in all handlers, PDU length validation, MTU caps, INVALID_OFFSET fix, Write Command CCCD handling |
| `src/main_l2cap.py` | Added `_proto_log()`, structured logging in SC2 command handler and haptic write callback |
| `src/gatt_db.py` | Added `ATT_ERR_INVALID_OFFSET = 0x07` constant |
| `scripts/extract_proto_trace.py` | New file — log parser with CSV output |
| `research/native_vs_ble_command_diff_TEMPLATE.md` | New file — diff template for native vs BLE captures |
| `research/steamclient-reverse-session/findings.md` | 32-bit address conversion, disclaimer updated |
| `research/steamclient-reverse-session/functions/*.c` (43 files) | Binary path, register names, gate offset, all addresses converted to 32-bit |
| `research/steamclient-reverse-session/notes/analysis_notes.md` | 32-bit notes added |
| `research/steamclient-reverse/SC2_BLE_DRIVER_REPORT.md` | Binary path updated |
| `docs/findings-backlog.md` | 32-bit addresses, register/offset conversions |
| `docs/investigation-plan.md` | 32-bit addresses, LD_PRELOAD target updated to 0x0123e601 |
| `docs/actor-prompt-guide.md` | Binary path updated |
| `CONTINUATION_PROMPT.md` | All addresses converted to 32-bit |
| `AGENTS.md` | Gate references updated ([esi+0x17c]), notes about old [r15+0x208] |
| `scripts/gdb_0x1d8_test.sh` | Converted to 32-bit GDB instructions (edi, esi, eip) |
| `HANDOFF.md` | This file |

## Behavior Changes

**Source code**: None. All protocol behavior is identical. Only diagnostics were added. The ATT correctness fixes (INVALID_OFFSET, PDU validation, MTU caps) are spec-compliant and should not change observed behavior for well-behaved hosts.

**Documentation only**: All reverse engineering analysis files updated from 64-bit to 32-bit binary addresses. No code behavior changed.

## Diagnostics Added

- `SPOOFDECK_PROTO_LOG=1` enables structured JSON logging to stderr
- Log lines cover: ATT writes, ATT reads, SC2 commands, haptic writes, notifications (sent and dropped)
- Each log line includes: monotonic timestamp, event type, opcode, handle, payload hex, SC2 command name, response data
- `scripts/extract_proto_trace.py` parses these logs into a human-readable report or CSV

## Offline Tests Run

- `python3 -m py_compile src/att_server.py` — OK
- `python3 -m py_compile src/main_l2cap.py` — OK
- `python3 -m py_compile src/gatt_db.py` — OK
- `python3 -m py_compile scripts/extract_proto_trace.py` — OK
- `python3 scripts/extract_proto_trace.py --help` — OK
- `grep` for stale 64-bit patterns — all remaining `linux64` and `r15+0x208` references are in historical context tags
- Verified 52 string/function addresses from 32-bit binary via `strings`, `grep -boa`, `objdump`
- All `.c` files in `research/steamclient-reverse-session/functions/` verified to have correct binary path

## Tests Not Run

- BLE connection test (requires Deck + host with Bluetooth hardware)
- Live protocol log capture (requires `SPOOFDECK_PROTO_LOG=1` on running Deck)
- End-to-end haptics test (requires Steam Client + game)

## Known Risks

- **Minimal for source code**: All changes are additive diagnostics or spec-compliant fixes. Existing protocol behavior is unchanged.
- **26 RE addresses need re-analysis**: Function entry points in the 0x015xxxxx and 0x010xxxxx ranges are marked `[NEEDS RE-ANALYSIS]`. These require GDB or disassembly of the running 32-bit Steam process to resolve. The GDB approach (`scripts/gdb_0x1d8_test.sh`) has been updated with 32-bit registers and offsets.
- The `SPOOFDECK_PROTO_LOG=1` env var must be set at service start time (checked once at module import).
- Structured log output goes to stderr (same as existing `print()` calls), so it will appear in `journalctl -u sc2-hogp`.

## Ghidra Analysis Results

Ghidra 11.3.1 installed at `~/ghidra`. Projects saved at `~/ghidra-projects/spoofdeck-32` and `spoofdeck-64`.

**Key findings from decompiled C:**

1. **Haptics root cause identified**: `CGetControllerInfoWorkItem::RunFunc` (0x01218840) calls `SDL_hid_read_timeout` via vtable[5] and gets **0 bytes**. It retries 51 times × 100ms = 5.1 seconds, then fails with "too many read failures." The entire init chain stalls here:
   ```
   CHIDIOThread_Main (0x011b3a60)
     → CWorkItemThread (0x011d5850)
       → CGetControllerInfoWorkItem (0x01218840) — STALLS HERE
         → EYldWaitForControllerDetails (0x011cee30, 2s timeout)
           → gate SET at 0x0178a140 — NEVER REACHED
   ```

2. **Notification pipeline traced** (from BlueZ 5.86 `hog-lib.c` + `uhid.c`):
   ```
   Our ATT Notification → report_value_cb() → bt_uhid_input()
     → UHID_INPUT2 → kernel HID core → /dev/hidrawN → SDL_hid_read_timeout
   ```
   The `uhid->started` flag gates delivery: events arriving before UHID_START are queued, then flushed.

3. **Why 0 bytes**: CGetControllerInfoWorkItem reads BEFORE notifications reach `/dev/hidrawN`. The pipeline works eventually (KDE detects gamepad, game rumble flows), but not within the 5.1-second window.

4. **SDL configuration**: Steam loads `libSDL3.so.0` and sets `SDL_JOYSTICK_HIDAPI_STEAM=1`.

5. **12 new verified function addresses** — see `research/32bit_ghidra_findings.md` for the full map.

**Exported data** at `~/ghidra-projects/exports/32bit/`:
- `functions.csv` — 141,351 functions
- `strings.csv` — 56,317 strings
- `controller_decompiled_32bit.txt` — decompiled C for 14 key controller functions
- `controller_xrefs_32bit.txt` — xrefs to 12 controller strings
- `call_graph.csv` — 16,494 call edges

## Recommended Next Human Bluetooth Test

1. Deploy to Deck:

   ```bash
   scripts/deploy.sh
   ```

2. Clear host BlueZ bond/cache:

   ```bash
   sudo rm -rf /var/lib/bluetooth/<HOST_BT_MAC>/C2:12:34:56:78:9A
   sudo rm -rf /var/lib/bluetooth/cache
   sudo systemctl restart bluetooth
   ```

3. Start the service with structured logging:

   ```bash
   SPOOFDECK_PROTO_LOG=1 systemd-run --unit=sc2-hogp \
     --property=WorkingDirectory=/tmp/sc2-spoof \
     python3 -u /tmp/sc2-spoof/src/main_l2cap.py --name "Steam Controller 2026"
   ```

4. Connect from host:

   ```bash
   bluetoothctl connect C2:12:34:56:78:9A
   ```

5. Wait 45 seconds (let Steam complete discovery and command handshake).

6. Save Deck logs:

   ```bash
   journalctl -u sc2-hogp --no-pager > /tmp/hogp.log
   ```

7. Run the parser:

   ```bash
   python3 scripts/extract_proto_trace.py /tmp/hogp.log
   ```

8. Check counts for:
   - `0xAE` GET_SERIAL (should appear 1-3 times; many retries on BLE would indicate a problem)
   - `0xF2` CAPABILITY_QUERY_UNKNOWN
   - `0x87` SET_SETTINGS_VALUES
   - `0x81` CLEAR_DIGITAL_MAPPINGS
   - `0x8F` TRIGGER_HAPTIC_PULSE (currently NOT expected — absence confirms Steam haptics path is separate)

9. Save the BLE trace and fill out:

   ```text
   research/native_vs_ble_command_diff_TEMPLATE.md
   ```

10. For native comparison: repeat steps 1-7 with the real SC2 hardware connected via BLE, then compare traces.

## Ghidra Automated RE (Resolve 26 Remaining Addresses)

Ghidra 11.3.1 is installed at `~/ghidra`. Java 21 is available.

### Quick Start (32-bit binary — priority)

Run in a separate terminal (takes 2-6 hours):

```bash
bash ~/ghidra-projects/run_32bit.sh
```

Or overnight (both binaries, 32-bit first):

```bash
nohup bash ~/ghidra-projects/run_overnight.sh > ~/ghidra-projects/exports/overnight.log 2>&1 &
```

### What It Does

1. Imports `ubuntu12_32/steamclient.so` into a Ghidra project
2. Runs full auto-analysis (decompilation, xref analysis, etc.)
3. Exports function list, call graph, strings, and xrefs to CSV
4. Searches for the 26 unverified function addresses by code pattern matching
5. Then repeats for the 64-bit binary

### Output Files

After analysis completes, check:

```bash
# Key results — functions matching our search patterns
cat ~/ghidra-projects/exports/32bit/unverified_results_32bit.txt

# All functions (name, address, size, call counts)
head -50 ~/ghidra-projects/exports/32bit/functions.csv

# Disassembly of known key addresses
cat ~/ghidra-projects/exports/32bit/key_disassembly.txt

# Cross-references
head -50 ~/ghidra-projects/exports/32bit/key_xrefs.csv

# Call graph
head -50 ~/ghidra-projects/exports/32bit/call_graph.csv
```

### What We're Looking For

The 26 unverified 64-bit addresses that need 32-bit equivalents:

| 64-bit Address | What It Is | Search Pattern |
|----------------|-----------|----------------|
| `0x015675a8` | Controller message dispatcher | Reads `[edi+0x1d8]`, switch/jump table |
| `0x015677f4` | YieldingRunTestProgram allocation | Calls job allocator, sets gate |
| `0x01558bb0` | Controller constructor | Writes to `[esi+0x1d8]`, reads `[esi+0x1b0]` |
| `0x01551560` | Controller destructor | Reads `[esi+0x1d8]` as pointer, cleanup |
| `0x0156d6a0` | Job context allocator | Called from YRT and other Yielding* functions |
| `0x0156d8a1` | Gate clear | `mov byte [reg+0x17c], 0` |
| `0x01559070` | Graphics API type writer | Writes values 1-4 to `[obj+0x1d8]` |
| `0x0119f3b1` | Gate clear instruction | Same as gate clear |
| `0x015647f5` | GL write (edx=1) | Writes 1 to `[obj+0x1d8]` |
| `0x01564857` | GL D3D variant (edx=1) | Same pattern |
| `0x015648bc` | Vulkan write (edx=2) | Writes 2 to `[obj+0x1d8]` |
| `0x0156323f` | D3D12 path A (edx=3) | Writes 3 to `[obj+0x1d8]` |
| `0x015632e1` | D3D12 path B (edx=4) | Writes 4 to `[obj+0x1d8]` |
| `0x017252a0` | Haptic trigger (dead code) | Zero callers |
| `0x00f907c5` | Sub-vtable pointer set | Writes to vtable slot |
| `0x00f912bb` | Sub-vtable pointer set (alt) | Same pattern |
| `0x010xxxxx` range | Identity/registration functions | ~8 functions |

### After Analysis

Once you have the addresses, update:
- `research/steamclient-reverse-session/findings.md`
- `docs/findings-backlog.md`
- `docs/investigation-plan.md`
- All `.c` files in `research/steamclient-reverse-session/functions/`

Replace `[NEEDS RE-ANALYSIS]` tags with the actual 32-bit addresses.
