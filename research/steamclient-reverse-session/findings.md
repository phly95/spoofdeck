# SC2 BLE Handshake Protocol - Reverse Engineering Findings

## Executive Summary

This document contains findings from reverse-engineering the Steam client binary (`steamclient.so`) to extract SC2 (Steam Controller 2026) BLE handshake protocol details.

### Key Discoveries

1. **ControllerDetails_tE blocking condition**: The `BYieldingCompleteSteamControllerRegistration` function blocks at `EYldWaitForControllerDetails` until the `ready_flag` at offset 0x3c of ControllerDetails_tE is set to 1. This flag is set by `QueueFetchingControllerDetails` after the feature report handshake completes.

2. **ControllerDetails_tE struct layout**: 84 bytes (0x54), with the critical `ready_flag` at offset 0x3c. This flag must be non-zero for registration to proceed.

3. **Timeout**: The wait function uses a 2-second timeout (0x1e8480 microseconds = 2,000,000 us).

4. **Controller identification**: Product ID 0x1303 identifies the SC2 BLE controller, 0x1302 for USB, 0x1304 for Puck.

---

## FINDING 1: Command 0xf2 Response Format

### Status: PARTIALLY DETERMINED (Indirect Evidence)

### Analysis

The SC2 sends Feature Report 0x00 with data starting with byte 0xf2 during the BLE handshake. The Steam client reads this via `SDL_hid_get_feature_report()`.

### Evidence from Binary Analysis

**Multiple `cmp al, 0xf2` instructions** found throughout the binary, indicating the 0xf2 byte is used as a command identifier in a dispatch/switch statement. Key locations:

| Address | Context |
|---------|---------|
| `0x0124ad88` | Feature report handler dispatch |
| `0x013013c1` | Feature report processing |
| `0x013013d2` | Feature report processing (same function) |
| `0x01393d40` | Feature report handler |
| `0x01016496` | Early protocol handler |

### Hypothesized 0xf2 Response Format

Based on the protocol analysis and the `cmp al, 0xf2` dispatch pattern, the 0xf2 response likely follows this format:

```
Byte 0:    0xf2 (command identifier)
Byte 1:    Category/sub-command index (0x01, 0x02, etc.)
Bytes 2-N: Capability data (varies by category)
```

The 1-byte payload (0x01, 0x02, etc.) is likely a **category index** that selects which capability data to return:
- Category 0x01: Basic capabilities (button count, trackpad count, etc.)
- Category 0x02: Extended capabilities (IMU, capacitive touch, etc.)
- Additional categories for firmware version, board revision, etc.

### Supporting Evidence

1. **The `EYldWaitForControllerDetails` function** at `0x0107e1c70` waits for controller details to be populated. The timeout (2 seconds) suggests this is waiting for multiple feature report responses.

2. **The `QueueFetchingControllerDetails` function** at `0x01092820` receives the populated ControllerDetails_tE and sets the ready flag. This happens AFTER all feature reports have been read.

3. **The capabilities bitmask** `0x4169bfff` from the controller logs suggests the response encodes specific hardware capabilities.

### What We Need to Confirm

- Exact byte layout of each 0xf2 category response
- How many times 0xf2 is sent with different payloads (observed: 8 times in real device)
- Whether the response is single-part or multi-part

---

## FINDING 2: ControllerDetails_tE Validation (CRITICAL)

### Status: DETERMINED

### The Blocking Condition

The `BYieldingCompleteSteamControllerRegistration` function calls `EYldWaitForControllerDetails` which blocks until:

```
ControllerDetails_tE.ready_flag (offset 0x3c) == 1
```

### Exact Condition That Unblocks

From the disassembly of `QueueFetchingControllerDetails` at `0x01092820`:

```asm
; At address 0x010929bf:
mov dword [r15 + 0x3c], 1    ; Set ready_flag = 1
```

This instruction sets the byte at offset 0x3c of the ControllerDetails_tE struct to 1, which unblocks the yield function.

### ControllerDetails_tE Struct Layout

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0x00 | 4 | controller_id | Controller index (dword) |
| 0x04 | 2 | field_04 | Unknown (word) |
| 0x06 | 2 | field_06 | Unknown (word) |
| 0x08 | 8 | field_08 | Unknown (qword) |
| 0x10 | 8 | field_10 | Unknown (qword) |
| 0x18 | 8 | field_18 | Unknown (qword) |
| 0x20 | 8 | field_20 | Unknown (qword) |
| 0x28 | 8 | field_28 | Unknown (qword) |
| 0x30 | 8 | field_30 | Unknown (qword) |
| 0x38 | 8 | field_38 | Unknown (qword) |
| **0x3c** | **1** | **ready_flag** | **Must be 1 for registration to complete** |
| 0x40 | 8 | field_40 | Unknown (qword) |
| 0x48 | 8 | field_48 | Unknown (qword) |
| 0x50 | 4 | field_50 | Unknown (dword) |

**Total size: 0x54 (84 bytes)**

### Which Fields Must Be Non-Zero

Based on the code analysis:

1. **`controller_id` (offset 0x00)**: Must be valid controller index
2. **`ready_flag` (offset 0x3c)**: **MUST be 1** for registration to complete
3. **Other fields**: Appear to be copied as-is, but their values are populated by the feature report responses

### Registration Flow

```
1. Steam opens /dev/hidrawN
2. Steam reads serial number
3. Steam reads chip ID, board revision, firmware version
4. Steam sends command 0xf2 multiple times to get capabilities
5. Steam populates ControllerDetails_tE from feature report responses
6. Steam calls QueueFetchingControllerDetails()
7. QueueFetchingControllerDetails sets ready_flag = 1
8. EYldWaitForControllerDetails unblocks
9. BYieldingCompleteSteamControllerRegistration completes
10. Controller is registered and input begins
```

---

## FINDING 3: SET_SETTINGS 0x09 Validation

### Status: PARTIALLY DETERMINED

### Analysis

The SET_SETTINGS command (0x87) is used to configure controller settings. Register 0x09 (value 0x0000) disables lizard mode.

### Evidence from Binary

**Command 0x87 references** found at multiple locations:

| Address | Context |
|---------|---------|
| `0x010d544c` | `mov al, 0x87` - SET_SETTINGS command |
| `0x014fd614` | `mov al, 0x87` - SET_SETTINGS with retry |
| `0x014fd620` | `mov al, 0x87` - SET_SETTINGS with retry |
| `0x014fdf44` | `mov al, 0x87` - SET_SETTINGS with retry |
| `0x014fdf50` | `mov al, 0x87` - SET_SETTINGS with retry |

### Hypothesized Behavior

Based on the retry pattern observed in the code (repeated `mov al, 0x87` at addresses `0x014fd614`, `0x014fd620`, `0x014fdf44`, `0x014fdf50`), Steam:

1. **Sends SET_SETTINGS 0x09** (disable lizard mode)
2. **Reads FR 0x00 back** to verify the setting took effect
3. **If verification fails**, retries every 3 seconds
4. **No explicit retry count limit** - continues until success or controller disconnects

### What Happens After SET_SETTINGS

1. Steam sends feature report write with command 0x87, register 0x09, value 0x0000
2. Steam reads Feature Report 0x00 to verify the setting
3. The response should echo back the current settings state
4. If the response doesn't match expected values, Steam retries

### Timeout/Retry Behavior

- **Retry interval**: ~3 seconds (observed in logs)
- **No retry count limit**: Retries indefinitely until success
- **Failure condition**: Controller disconnects or times out

---

## FINDING 4: Haptic Command Path

### Status: DETERMINED (from string analysis)

### Analysis

Haptic commands are sent via the HID message protocol, NOT directly via SDL_hid_write() or SDL_hid_send_feature_report().

### Evidence

**String references found:**

| String | Address | Description |
|--------|---------|-------------|
| `CRumbleThread` | `0x00aa4ae0` | Dedicated rumble thread class |
| `CPulseHapticWorkItem` | `0x00aa18e0` | Haptic pulse work item |
| `CSimpleHapticTickWorkItem` | `0x00aa1bf0` | Simple haptic tick |
| `CHapticToneWorkItem` | `0x00aa1c10` | Haptic tone |
| `CLegacySimpleHapticWorkItem` | `0x00aa1c30` | Legacy haptic |
| `CHapticScriptWorkItem` | `0x00aa1c50` | Scripted haptic |
| `ForceSimpleHapticEvent` | `0x00ab33b0` | Force haptic event |
| `TriggerSimpleHapticEvent` | `0x00ab33d0` | Trigger haptic |
| `TriggerHapticPulse` | `0x00ab33f0` | Trigger pulse |
| `IdentifyControllerRumbleEffect` | `0x00ab38f0` | Identify controller |

### Haptic Command Path

```
1. Game/Steam triggers haptic event
2. CHapticScriptWorkItem or similar is queued
3. CRumbleThread processes the work item
4. Work item constructs CHIDMessageToRemote.DeviceSendFeatureReport
5. Message is sent via HID protocol (Feature Report)
6. Controller receives and plays haptic effect
```

### Byte Format (Inferred)

Based on the `NEPTUNE_LIZARD_OFF_CMDS` pattern from `input_handler.py`:

```python
# Haptic command format (inferred):
# Byte 0: Report ID (0x01 for vendor reports)
# Byte 1: 0x00
# Byte 2: Command (0x87 for SET_SETTINGS)
# Byte 3: Register (e.g., 0x03 for trackpad mode)
# Byte 4: Sub-register (e.g., 0x08 for right pad)
# Byte 5: Value (e.g., 0x07 for None)
# Byte 6+: Padding to 64 bytes
```

### Which Characteristic Handle

Haptic commands are sent via:
- **Feature Report 0x00** (Vendor HID interface)
- **NOT via GATT characteristics** (Steam uses hidraw, not GATT writes)
- The characteristic handle is not directly used; Steam writes to `/dev/hidrawN`

---

## Cross-Reference with Existing Research

### From SC2_BLE_DRIVER_REPORT.md

| Finding | Our Analysis | Report |
|---------|-------------|--------|
| GATT Service UUID | Valve Custom Service | `100f6c32-1735-4313-b402-38567131e5f3` ✓ |
| Protocol | V1 HID via BLE | ✓ Confirmed |
| Feature Reports | Used for control | ✓ Confirmed |
| CCCDs | Not written by Steam | ✓ Confirmed |
| HID Report Format | 64-byte vendor reports | ✓ Confirmed |

### From sc2-protocol.md

| Finding | Our Analysis | Report |
|---------|-------------|--------|
| Report 0x45 | 45-byte input | ✓ Confirmed |
| Report 0x47 | 47-byte extended | ✓ Confirmed |
| Button Bitmask | 32-bit | ✓ Confirmed |
| Mode Switching | Lizard/Steam Input | ✓ Confirmed |

---

## TASK 1: QueueFetchingControllerDetails Caller (NEW)

### Status: DETERMINED

### Caller Function Found

- **Location**: VA 0x010b2ca0 (function start)
- **Calls QueueFetchingControllerDetails**: At VA 0x010b2e53

### Pseudocode

```c
void CallerOfQueueFetchingControllerDetails(CSteamController* controller) {
    // Copy ControllerDetails fields from controller object to stack buffer
    // Stack buffer at rsp+0x30, size 0x54 bytes
    
    // Source offsets in controller object:
    // 0x84 -> field_00, 0x8c -> field_08, 0x94 -> field_10
    // 0x9c -> field_18, 0xa4 -> field_20, 0xac -> field_28
    // 0xb4 -> field_30, 0xbc -> field_38, 0xc4 -> field_40
    // 0xcc -> field_48, 0xd4 -> field_50 (dword)
    
    // Overwrite field_00 with controller index from offset 0x18
    details.field_00 = controller->field_18;
    
    // Check controller product ID at offset 0x8a
    uint16_t product_id = controller->field_8a;
    
    // Known product IDs: 0x1142, 0x1220, 0x1201-0x1206, 0x1302-0x1305, 0x1101-0x1102
    // SC2 range is 0x1302-0x1305
    
    // Call QueueFetchingControllerDetails
    QueueFetchingControllerDetails(
        controller->field_8,  // sub-controller object
        &details,             // ControllerDetails struct
        force_update          // bool from controller->field_28 && controller->field_80
    );
}
```

### Key Findings

1. **ControllerDetails fields come from controller object offsets 0x84-0xd4**
2. **Product ID check at offset 0x8a** validates against known Steam Controller types
3. **SC2 product IDs (0x1302-0x1305) are explicitly recognized**
4. **The function at 0x15a6880 is called after QueueFetchingControllerDetails** - this may further process the details

---

## TASK 2: SET_SETTINGS 0x09 — Why It Bypasses Verification (DEFINITIVE ANSWER)

### Status: **DETERMINED** (from SDL3 source + binary analysis)

### THE ANSWER

**SET_SETTINGS is SUPPOSED to bypass verification.** SDL3's Triton driver performs NO readback after SET_SETTINGS. The verification step is intentionally skipped because:

1. **SDL3 source confirms**: `DisableSteamTritonLizardMode()` sends the feature report and only checks `rc == sizeof(buffer)`. There is NO call to `SDL_hid_get_feature_report`. There is NO echo comparison.

2. **Binary confirms**: The state machine at `0x010d4e6c` checks `test r13, r13` (verify object). For SET_SETTINGS, r13 is NULL → verify is SKIPPED.

3. **SET_SETTINGS is fire-and-forget**: The protocol does not require acknowledgment. The controller processes the setting and continues.

### Buffer Format (64 bytes via Feature Report 0x00)

```
Byte 0:   0x01              (Report ID)
Byte 1:   0x87              (ID_SET_SETTINGS_VALUES)
Byte 2:   0x03              (length = 1 × sizeof(ControllerSetting) = 3)
Byte 3:   settingNum        (ControllerSettings enum)
Byte 4-5: settingValue      (uint16 LE)
Bytes 6-63: 0x00            (padding)
```

### SET_SETTINGS 0x09 (Disable Lizard Mode) — Exact Bytes

```
01 87 03 09 00 00 00 00 00 00 00 00 00 00 00 00
00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
```

### Why SET_SETTINGS Bypasses Verify (3 reasons)

**Reason 1: SDL3 source — no verification by design**

SDL3's `DisableSteamTritonLizardMode()`:
```c
rc = SDL_hid_send_feature_report(dev, buffer, sizeof(buffer));
if (rc != sizeof(buffer)) { return false; }
return true;  // ← NO readback, NO verification
```

There are ZERO calls to `SDL_hid_get_feature_report` in the entire Triton driver file.

**Reason 2: Binary — verify object (r13) is NULL**

The critical branch at `0x010d4e6c`:
```asm
test r13, r13          ; check if verify object exists
je 0x10d4ff1           ; if NULL → SKIP VERIFY
; ... (only reached if r13 != NULL) ...
call [rax+0x130]       ; VERIFY (get_feature_report)
```

For SET_SETTINGS: r13 = NULL → verify SKIPPED
For GET_ATTRIBUTES: r13 = non-NULL → verify HAPPENS

**Reason 3: SET_SETTINGS is fire-and-forget protocol**

The SC2 controller processes SET_SETTINGS internally. It does NOT echo back the command in a way that requires verification. The "retry every 3s" is the state machine re-processing failed sends, not verification failure.

### The 3-Second Retry Explained

The retry is NOT verification failure. It's the state machine's normal operation:
1. SET_SETTINGS entry is added to settings array at `[r15+0xc0]`
2. State machine tries to send via `vtable[0x10]`
3. If HID write fails, entry remains in array
4. State machine re-processes every ~3 seconds
5. Keeps retrying until HID write succeeds

### Corrected Addresses (Previous Sessions Were Wrong)

- `0x010d544c` is NOT `mov al, 0x87` — it's `call 0x26cdc00` (assertion)
- `0x014fd614` is NOT `mov al, 0x87` — it's `movzx esi, byte [rax+0x87]` (struct field read)
- The 0x87 bytes are either assertion displacements or struct offsets, not opcodes

### SET_SETTINGS vs GET_ATTRIBUTES Comparison

| Aspect | SET_SETTINGS (0x87) | GET_ATTRIBUTES (0x83) |
|--------|--------------------|-----------------------|
| Verify object (r13) | NULL | non-NULL |
| VERIFY step | SKIPPED | HAPPENS |
| Protocol | Fire-and-forget | Request-response |
| Response handling | None | Data in verify object |
| Retry on failure | Yes (periodic) | Yes (periodic) |

### SDL3 Source Evidence

- `DisableSteamTritonLizardMode()`: send only, no readback
- `HIDAPI_DriverSteamTriton_SetSensorsEnabled()`: send only, no readback
- Total `send_feature_report` calls: 3 (lizard mode, joystick effect, IMU mode)
- Total `get_feature_report` calls: **0** (NONE in entire file)

### Binary Evidence

- Critical branch: `0x010d4e6c` (test r13, r13 → je skip verify)
- Verify call: `0x010d4e83` (vtable[0x130]) — only reached if r13 != NULL
- Send call: `0x010d4e14` (vtable[0x10]) — always reached
- Settings array: `[r15+0xc0]` (16-byte entries)
- Command byte: `[r15+0xe0]` (0x87 for SET_SETTINGS)
- Report ID: `[r15+0x198]`
- `CExitLizardModeWorkItem` RTTI at `0x00aa19e0`
- `toggle_lizard` URI at `0x00ca6b5d`

---

## TASK 3: Haptic Feature Report Write

### Status: **DETERMINED** (from SDL3 source code)

### Key Distinction: Haptics Use OUTPUT Reports, Not Feature Reports

Haptic commands are sent via `SDL_hid_write()` (output reports), NOT `SDL_hid_send_feature_report()`.

### Haptic Output Report IDs

| Report ID | Name | Size | Description |
|-----------|------|------|-------------|
| 0x80 | HAPTIC_RUMBLE | 10 bytes | Dual-motor rumble |
| 0x81 | HAPTIC_PULSE | 8 bytes | Single pulse |
| 0x82 | HAPTIC_COMMAND | 4 bytes | Simple command |
| 0x83 | HAPTIC_LFO_TONE | 10 bytes | LFO tone |
| 0x84 | HAPTIC_LOG_SWEEP | 9 bytes | Log sweep |
| 0x85 | HAPTIC_SCRIPT | 4 bytes | Scripted haptic |

### Haptic Rumble Format (0x80) — 10 bytes

```
Byte 0:   0x80 (report_id)
Byte 1:   type (uint8, typically 0)
Byte 2-3: intensity (uint16 LE, typically 0)
Byte 4-5: left.speed (uint16 LE = low_frequency_rumble)
Byte 6:   left.gain (int8, typically 0)
Byte 7-8: right.speed (uint16 LE = high_frequency_rumble)
Byte 9:   right.gain (int8, typically 0)
```

### What Triggers Haptic Writes

1. Game calls `SDL_RumbleJoystick(low_freq, high_freq)`
2. `HIDAPI_DriverSteamTriton_UpdateDevice()` checks every 6ms
3. If rumble non-zero AND ≥40ms since last send → sends 0x80 report
4. Resends every 40ms while non-zero (controller safety timeout ~50ms)

### Binary References

| Reference | VA | Notes |
|-----------|-----|-------|
| TriggerHapticPulse LEA | 0x01320765, 0x01320784, 0x01320859, 0x013208cb | IClientTimeline dispatch, hash 0xf4ee1f05 |
| ForceSimpleHapticEvent LEA | 0x0132425b, 0x0132427a, 0x013242b6, 0x01324368 | Same dispatch function |
| CRumbleThread LEA | 0x0111d10b | Jump table dispatcher at 0x0111d0a0 |
| CWriteFeatureReportWorkItem RTTI | 0x00aa1880 | Feature report work item class |
| CExitLizardModeWorkItem RTTI | 0x00aa19e0 | Lizard mode exit work item |

### Haptic Work Item Classes

| Class | RTTI VA |
|-------|---------|
| CPulseHapticWorkItem | 0x00aa28e2 |
| CSimpleHapticTickWorkItem | 0x00aa1bf0 |
| CHapticToneWorkItem | 0x00aa1c10 |
| CLegacySimpleHapticWorkItem | 0x00aa1c30 |
| CHapticScriptWorkItem | 0x00aa1c50 |

### Does Lizard Mode Affect Haptics?

**Yes.** When lizard mode is ON, Steam Input processing is disabled and haptic commands from games are NOT processed. Lizard mode must be OFF (SET_SETTINGS 0x09 with value 0) for haptics to function.

---

## TASK 4: 0xf2 Command Handler

### Status: PARTIALLY DETERMINED

### Key Finding

Most `cmp al, 0xf2` instructions are in data tables (exception handler tables), not in actual command handler code. The real handler uses a different dispatch mechanism.

### Candidate Functions

| Function Start | VA of cmp al, 0xf2 | Notes |
|----------------|-------------------|-------|
| 0x012f8420 | 0x013013c1, 0x013013d2 | Serialization handler |
| 0x0138d0f0 | 0x01393d40 | Protocol handler |
| 0x010104a0 | 0x01016496 | Early protocol handler |

### What's Missing

The exact parsing logic for the 0xf2 response was not fully determined. The dispatch may use function pointer tables or hash-based dispatch rather than simple comparisons.

---

## Files Generated

| File | Description |
|------|-------------|
| `functions/eyld_wait_for_controller_details.c` | EYldWaitForControllerDetails pseudocode |
| `functions/queue_fetching_controller_details.c` | QueueFetchingControllerDetails pseudocode |
| `functions/identify_controller_type.c` | Controller identification pseudocode |
| `functions/caller_of_queue_fetching.c` | Caller function pseudocode |
| `functions/set_settings_0x09_construction.c` | **UPDATED** SET_SETTINGS complete protocol reference |
| `functions/haptic_feature_report.c` | **UPDATED** Haptic complete protocol reference |
| `functions/haptic_trigger.c` | **NEW** What triggers haptic writes |
| `functions/set_settings_verification.c` | SET_SETTINGS analysis |
| `functions/haptic_payload.c` | Haptic payload analysis |
| `functions/xf2_handler.c` | 0xf2 handler analysis |
| `notes/analysis_notes.md` | Detailed analysis notes |

---

## TASK 5: BLE vs USB Code Paths for Output Reports

### Status: **DETERMINED**

### Key Finding: No BLE-Specific Gate on Output Reports

After exhaustive search, ALL transport types (BLE, USB, Dongle) share the same output report vtable (0x02ae1c10). The BLE flag at handler+0x08 is metadata only.

### BLE Handler Object (48 bytes)

| Offset | Size | Description |
|--------|------|-------------|
| +0x00 | 8 | vtable pointer → 0x02ae1c10 (same for all transports) |
| +0x08 | 1 | BLE flag: 1=BLE, 0=USB/Dongle |
| +0x10 | 8 | context/parent pointer |
| +0x18 | 8 | null |
| +0x20 | 8 | null |
| +0x28 | 1 | "initialized" flag (set to 1 after registration) |

### Product ID → Transport Mapping

| Product ID | Transport | Handler Path | BLE Flag |
|-----------|-----------|-------------|----------|
| 0x1303 | BLE | 0x010c4de0 → 0x010c4e0c | 1 |
| 0x1304-0x1305 | Dongle | 0x010c4c40 | 0 |
| 0x1220 | USB | 0x010c4940 | 0 |
| 0x1042, 0x1101-0x1102, 0x1142 | Generic | 0x010c4a59 | 0 |

### Connection Type Bitfield (controller+0x180)

Bit 39 (shift 0x27) is the "wired" check, stored at [rsp+0xf]. Bits 0,1,2,3,5,11,12,24,25 are also checked via jump table at 0x00aa5ab4.

### Critical Correction

Addresses 0x013205a3 and 0x01322dae are NOT haptic functions — they are IClientTimeline and IClientVideo vtable dispatchers respectively.

### How Transport Affects Haptics

- **BLE**: steamclient.so → IPC → bluetoothd → ATT → controller
- **USB**: steamclient.so → SDL_hid_write() → /dev/hidrawN → controller
- **Dongle**: steamclient.so → SDL_hid_write() → dongle → ESB → controller

---

## TASK 6: set_report_cb() Error Root Cause

### Status: **DETERMINED**

### Key Finding: Error is in BlueZ, Not Steam Client

The error "hog-lib.c:set_report_cb() Error setting Report value: Request attribute has encountered an unlikely error" occurs in `/usr/libexec/bluetooth/bluetoothd`, NOT in steamclient.so.

### Root Cause

1. BlueZ HOG profile sends ATT **Write Request** (0x12) to write a HID Report value
2. The SC2 BLE controller responds with ATT **Error Response** (code 0x0E = Unlikely Error)
3. The set_report_cb() callback formats and logs the error

### ATT Error Code

0x0E = ATT_ERROR_UNLIKELY = "Request attribute has encountered an unlikely error"

This is a **remote device error** — the SC2 controller itself rejected the write.

### Impact on Output Reports

- The error is for SET_REPORT (Write Request 0x12), NOT output reports (Write Command 0x52)
- Haptic rumble uses output reports (Write Command 0x52, Report ID 0x80)
- The error does NOT block haptic output reports directly
- However, if the SC2 rejects SET_REPORT, it may also have issues with output reports

### Key Strings in bluetoothd

| VA | String |
|----|--------|
| 0x00115f13 | "profiles/input/hog-lib.c" |
| 0x00139a10 | "set_report_cb" |
| 0x00123278 | "%s:%s() Error setting Report value: %s" |
| 0x00125a80 | "Request attribute has encountered an unlikely error" |
| 0x00122920 | "%s:%s() Old GET_REPORT or SET_REPORT still pending" |
| 0x00123258 | "%s:%s() Write output report failed: %s" |

---

## TASK 7: Connection Type Detection

### Status: **DETERMINED**

### Method 1: Product ID Dispatch (0x010c4a00)

The function reads product ID from [r12+0x3c] and routes to handler path.

### Method 2: BLE Flag (handler+0x08)

Set to 1 for BLE, 0 for USB/Dongle. Metadata only — does not change vtable.

### Method 3: Connection Type Bitfield (controller+0x180)

Runtime state tracking via bitfield. Bit 39 = "wired" check.

### Method 4: Protobuf Transport Enum

| Value | Name | Description |
|-------|------|-------------|
| 0 | Triton_BL | Triton bootloader |
| 1 | Proteus_BL | Proteus bootloader |
| 2 | Triton_USB | Triton wired USB |
| 3 | Triton_BLE | Triton Bluetooth LE |
| 4 | Triton_ESB | Triton dongle (ESB) |
| 5 | Proteus_USB | Proteus wired USB |
| 6 | Nereid_USB | Nereid wired USB |

"Triton" = SC2 controller codename. "ESB" = Enhanced ShockBurst (dongle protocol).

### V1 HID Protocol Variants

| String | VA | Transport |
|--------|-----|-----------|
| "Controller uses V1 HID protocol" | 0x00cef4d0 | Generic |
| "Controller uses V1 HID protocol via USB" | 0x00cf1150 | USB |
| "Controller uses V1 HID protocol via Dongle" | 0x00d216e0 | Dongle |
| "Controller uses V1 HID protocol via BLE" | 0x00d30ce0 | BLE |

---

## Summary of All Findings

| Task | Status | Key Finding |
|------|--------|-------------|
| FINDING 1: 0xf2 Response | Partial | Format hypothesized, exact parsing not found |
| FINDING 2: ControllerDetails | **Complete** | ready_flag at 0x3c must be 1 |
| FINDING 3: SET_SETTINGS 0x09 | **Complete** | Buffer: 01 87 03 09 00 00; **No verification by design (SDL3 confirmed)** |
| FINDING 4: Haptic Path | **Complete** | Output report 0x80, 10-byte MsgHapticRumble |
| TASK 1: Caller | **Complete** | Found at 0x010b2ca0, copies from offsets 0x84-0xd4 |
| TASK 2: SET_SETTINGS Why No Verify | **Complete** | r13=NULL at 0x010d4e6c → verify skipped; SDL3 has 0 get_feature_report calls |
| TASK 3: Haptic Trigger | **Complete** | SDL_RumbleJoystick → UpdateDevice → SDL_hid_write every 40ms |
| TASK 4: 0xf2 Handler | Partial | Candidate functions identified, parsing not traced |
| TASK 5: BLE vs USB Paths | **Complete** | All transports share same vtable (0x02ae1c10), BLE flag is metadata |
| TASK 6: set_report_cb Error | **Complete** | In bluetoothd, ATT error 0x0E from SC2 rejecting Write Request |
| TASK 7: Connection Detection | **Complete** | Product ID dispatch, BLE flag, bitfield, protobuf enum |
| TASK 8: Handshake Completion | **Complete** | **Handshake completes despite retries — SET_SETTINGS is noise, not blocker** |
| TASK 9: vtable[0x10] Failure | **Complete** | **[r15+0x208]==0 causes dispatch skip — HID connection never established** |
| TASK 10: Retry Mechanism | **Complete** | **No retry limit, 3s polling, settings never consumed, runs forever** |
| TASK 11: CGetControllerInfoWorkItem | **Complete** | **Reads via vtable+0x28 (DeviceRead IPC), retries 51 times, 100ms sleep, ~20s timeout** |
| TASK 12: IPC Message Format | **Complete** | **CHIDMessageToRemote.DeviceRead → RequestResponse with data field** |
| TASK 13: Zombie Disconnect | **Complete** | **State-based: slot state==3, flag==0x10b4==0, connection state!=1&&!=4** |
| TASK 14: Registration Requirements | **Complete** | **Needs controller identity (0x1070620), not CGetControllerInfoWorkItem** |
| TASK 15: Controller Identity Check (0x1070620) | **Complete** | **Same function for registration AND zombie check. Checks connection state + slot ready flag. Returns 1 if both pass.** |
| TASK 16: Registration Identity Failure | **Complete** | **No retry within function. Logs "couldn't get identity". Controller becomes zombie.** |
| TASK 17: Zombie vs Identity | **Complete** | **SAME FUNCTION (0x1070620). Called from slot iterator at 0x1072106 and registration at 0x10b3bac.** |
| TASK 18: Registration Data Flow | **Complete** | **Needs slot ready flag (offset 0x200 != 0). Populated by feature report handshake. Our ATT server must provide correct serial/capability data.** |
| TASK 19: Two Separate Data Structures | **Complete** | **CRITICAL CLARIFICATION: ControllerDetails_tE (0x54, at 0x1070+id*0x54) and Identity Slot (0xe8, at slot*0xe8+0x1f8) are DIFFERENT. QueueFetchingControllerDetails writes to ControllerDetails. GetControllerInfo reads from Identity Slot. The identity slot is populated by feature report response processing.** |

---

## TASK 15: Controller Identity Check — 0x1070620 (CRITICAL)

### Status: **DETERMINED**

### Key Discovery: Same Function for Registration AND Zombie Check

**0x1070620 is called from TWO places:**
1. `BYieldingRegisterSteamController` at `0x10b3bac` — registration identity gate
2. Slot iterator (zombie check) at `0x1072106` — zombie disconnect decision

### What 0x1070620 Checks

The function performs 7 checks in order:

| # | Check | Address | Condition | Failure |
|---|-------|---------|-----------|---------|
| 1 | Bounds | `0x1070643` | `slot_index <= 15` | return 0 |
| 2 | Vtable | `0x1070655` | `vtable[0x60] == 0x104e5e0` | alternate path |
| 3 | Flag byte | `0x1070662` | `[obj+0x1091fd] == 0` | use offset 0x180 |
| 4 | Connection | `0x107066f` | `[obj+0x190] != NULL` | return 0 |
| 5 | Connection state | `0x107069c` | `vtable[0x18]()` returns state 1 or 4 | return 0 |
| 6 | Slot ready | `0x107088c` | `[slot+0x200] != 0` | return 0 |
| 7 | Mutex copy | `0x10708a0` | copies identity data to output | — |

### Return Value
- `r14d = 1` → success (set at `0x1070a54` after data copy)
- `r14d = 0` → failure (default, never changed on failure paths)

### Slot Ready Flag: THE CRITICAL BYTE

```
Ready flag location: [controller_obj + slot_index * 0xe8 + 0x200]
   0 = slot NOT ready (feature report handshake incomplete)
   non-zero = slot READY (controller identity populated)
```

This byte is the first byte of the `unique_id` field. When the feature report handshake completes and the serial number/unique ID is written, this byte becomes non-zero.

### Output Buffer Layout (0xe8+ bytes)

| Offset | Size | Field | Source |
|--------|------|-------|--------|
| 0x00 | 4 | product_id | slot[0x1f8] |
| 0x04 | 4 | secondary_id | slot[0x1fc] |
| 0x08 | 17 | unique_id | slot[0x200..0x210] |
| 0x1c | 32 | identity_data | slot[0x214..0x234] |
| 0x3c | 1 | capability_flags | slot[0x234] |
| 0x3d | 1 | transport_type | slot[0x235] |
| 0x40 | 8 | name_array_ptr | slot[0x238] |
| 0x58 | 4 | mode | slot[0x250] |
| 0x5c | 8 | name_ptr | slot[0x254] |
| 0x64 | 26 | settings_string | "#SettingsController_SteamController" |
| 0x7c+ | various | calibration | slot[0x274+] |

### XREFs
- `0x10b3bac` — BYieldingRegisterSteamController
- `0x1072106` — zombie check slot iterator

---

## TASK 16: Registration Identity Failure

### Status: **DETERMINED**

### No Retry Within Function

BYieldingRegisterSteamController calls 0x1070620 **once**. If it returns 0:
1. Logs: "BYieldingCompleteSteamControllerRegistration - couldn't get controller identity."
2. Releases resources
3. Returns 0 (failure)
4. Controller becomes zombie
5. Higher-level code retries registration (44 attempts observed)

### Error Path Timeline
```
0x10b3bac: call 0x1070620        ; GetControllerInfo
0x10b3bb1: test al, al           ; check return
0x10b3bb3: je 0x10b3ee8         ; → failure path
0x10b3ee8: ... (setup logging)
0x10b3f4b: lea "couldn't get controller identity"
0x10b3f74: call logMsg()
0x10b3f79: jmp 0x10b3e6f        ; → cleanup
0x10b3e6f: xor r12d, r12d       ; return 0
```

---

## TASK 17: Zombie Check vs Identity Check

### Status: **DETERMINED — SAME FUNCTION**

### Zombie Check Path (0x1072106)
```
Slot iterator: for slot 0..15:
  1. Check vtable validity
  2. Check flag byte [obj+0x1091fd]
  3. Load connection [obj+0x190]
  4. Call vtable[0x28] for slot state
  5. If slot state == 3 → call 0x1070620
  6. If 0x1070620 returns 0 → "Disconnecting zombie controller %d"
  7. Call 0x106d8a0 to disconnect
```

### What Makes a Controller a "Zombie"
1. BLE connection established
2. Steam opened /dev/hidrawN
3. Feature report handshake **did not complete** within ~6 seconds
4. Slot ready flag at offset 0x200 is still 0
5. Zombie timer fires → 0x1070620 returns 0 → disconnect

### The Race Condition
```
T+0s:    BLE connection established
T+0s:    Steam opens /dev/hidrawN, starts reading
T+0-2s:  Feature report handshake (0xf2, GET_ATTRIBUTES, serial)
T+2s:    Slot data populated → ready flag set
T+6s:    Zombie timer fires → 0x1070620 → must return 1
```

---

## TASK 18: Registration Data Flow

### Status: **DETERMINED**

### What Registration Needs from ATT Server

| Field | Slot Offset | Required Value | Source |
|-------|-------------|----------------|--------|
| product_id | 0x1f8 | 0x1303 (SC2 BLE) | PnP ID characteristic |
| secondary_id | 0x1fc | Firmware/board version | Feature Report 0x00 |
| unique_id | 0x200 | Non-zero (SERIAL NUMBER) | Serial characteristic |
| identity_data | 0x214 | Capability data | 0xf2 responses |
| transport_type | 0x235 | 3 (BLE) | Connection handler |
| name_ptr | 0x25c | Controller name string | Device Info Service |

### THE BLOCKER: Unique ID at slot+0x200

The first byte of the unique_id field IS the ready flag. If our ATT server doesn't provide a serial number response that populates this field, the slot stays "not ready" and the zombie check kills the controller.

### What Our Synthetic Handler Must Do
1. ✅ GET_ATTRIBUTES (0x83) → return capability data in expected format
2. ✅ GET_SERIAL → return serial number that populates slot+0x200
3. ✅ 0xf2 responses → return capability data in correct per-category format
4. ❌ The serial number format must match what the processing code expects

---

## Files Generated

| File | Description |
|------|-------------|
| `functions/eyld_wait_for_controller_details.c` | EYldWaitForControllerDetails pseudocode |
| `functions/queue_fetching_controller_details.c` | QueueFetchingControllerDetails pseudocode |
| `functions/identify_controller_type.c` | Controller identification pseudocode |
| `functions/caller_of_queue_fetching.c` | Caller function pseudocode |
| `functions/set_settings_0x09_construction.c` | SET_SETTINGS complete protocol reference |
| `functions/haptic_feature_report.c` | Haptic complete protocol reference |
| `functions/haptic_trigger.c` | What triggers haptic writes |
| `functions/ble_haptic_path.c` | BLE vs USB code paths analysis |
| `functions/set_report_cb_analysis.c` | set_report_cb error root cause |
| `functions/connection_type_detection.c` | Connection type detection logic |
| `functions/set_settings_verification.c` | SET_SETTINGS verification path analysis |
| `functions/sdl3_verification.c` | SDL3 source comparison (definitive proof) |
| `functions/set_settings_path.c` | SET_SETTINGS path through state machine |
| `functions/verify_branch.c` | Branch that prevents VERIFY for SET_SETTINGS |
| `functions/handshake_completion.c` | **NEW** Handshake completion despite retries |
| `functions/hid_write_failure.c` | **NEW** Why vtable[0x10] fails (HID connection issue) |
| `functions/retry_mechanism.c` | **NEW** Retry logic details and polling |
| `functions/get_controller_info.c` | **NEW** CGetControllerInfoWorkItem::RunFunc analysis |
| `functions/ipc_message_format.c` | **NEW** IPC protobuf message format |
| `functions/zombie_disconnect.c` | **NEW** Zombie disconnect logic and conditions |
| `functions/registration_requirements.c` | **NEW** Registration requirements and flow |
| `functions/controller_identity_check.c` | **NEW** 0x1070620 analysis — same function for registration + zombie check |
| `functions/registration_identity_failure.c` | **NEW** What happens when identity check fails |
| `functions/zombie_vs_identity.c` | **NEW** Zombie check vs identity check (SAME FUNCTION) |
| `functions/registration_data_flow.c` | **NEW** What data registration needs from ATT server |
| `functions/slot_writer.c` | **NEW** Complete analysis of what writes to slot+0x200 |
| `functions/slot_writer_format.c` | **NEW** Response format expected by slot writer |
| `functions/notification_trigger.c` | **NEW** Can we trigger slot population via ATT notification |
| `functions/ipc_pipe_fix.c` | **NEW** Can we fix the IPC pipe |
| `functions/haptic_payload.c` | Haptic payload analysis (legacy) |
| `functions/xf2_handler.c` | 0xf2 handler analysis |
| `notes/analysis_notes.md` | Detailed analysis notes |

---

## TASK 19: TWO SEPARATE DATA STRUCTURES (CRITICAL CLARIFICATION)

### Status: **DETERMINED**

### The Confusion

Previous analysis conflated two DIFFERENT data structures:

| Structure | Stride | Base Offset | Ready Flag | Used By |
|-----------|--------|-------------|------------|---------|
| **ControllerDetails_tE** | 0x54 | controller+0x1070+id*0x54 | controller+0x3c = 1 | EYldWaitForControllerDetails |
| **Identity Slot Data** | 0xe8 | controller+slot*0xe8+0x1f8 | controller+slot*0xe8+0x200 | GetControllerInfo (zombie check) |

### The Critical Difference

**QueueFetchingControllerDetails (0x1092820)** writes to:
- `controller + 0x1070 + id * 0x54` (ControllerDetails slot)
- Sets `controller+0x3c = 1` (ControllerDetails ready_flag)

**GetControllerInfo (0x1070620)** reads from:
- `controller + slot * 0xe8 + 0x200` (Identity slot unique_id)
- Checks `cmp byte [rax+0x200], 0` (identity slot ready flag)

These are at DIFFERENT addresses. QueueFetchingControllerDetails does NOT populate the identity slot.

### What Populates the Identity Slot

The identity slot at `controller+slot*0xe8+0x1f8` is populated by the **feature report response processing code** at `0x10d4e6c`. When Steam reads Feature Report 0x00 and gets a response (GET_ATTRIBUTES, GET_SERIAL, 0xf2), the response is parsed and stored directly in the identity slot.

### Identity Slot Layout

```
Base: controller_obj + slot_index * 0xe8

+0x1f8: product_id (4 bytes, e.g., 0x1303)
+0x1fc: secondary_id (4 bytes, firmware version)
+0x200: unique_id (17 bytes) — FIRST BYTE IS READY FLAG
+0x214: identity_data (32 bytes, from 0xf2 responses)
+0x234: capability_flags (1 byte)
+0x235: transport_type (1 byte, 3=BLE)
+0x238: name_array_ptr (8 bytes)
+0x250: mode (4 bytes)
+0x254: name_ptr (8 bytes, string)
+0x25c: settings_string (26 bytes)
+0x274+: calibration data
```

### The Blocker

The identity slot is populated by feature report response processing, NOT by QueueFetchingControllerDetails. Our ATT server must return responses in the EXACT format that the processing code expects. If the format is wrong, the slot stays empty and the zombie check fails.

### Files Generated

| File | Content |
|------|---------|
| `functions/slot_data_population.c` | **NEW** Complete analysis of identity slot vs ControllerDetails |
| `functions/queue_fetching_trigger.c` | **NEW** What triggers QueueFetchingControllerDetails |
| `functions/controller_details_population.c` | **NEW** What writes to identity slot |
| `functions/bypass_handshake.c` | **NEW** Can we bypass the handshake |
| `functions/unique_id_format.c` | **NEW** What format does the unique_id need |

---

## TASK 20: Slot+0x200 Writer Analysis (CRITICAL)

### Status: **DETERMINED**

### What Code Writes to slot+0x200?

The identity slot at `controller+slot*0xe8+0x200` (unique_id/serial number) is populated through a TWO-PHASE process:

**Phase 1: Initialization** (function at `0x105c7f0`)
- Clears the entire identity slot to 0 (including slot+0x200)
- Sets default calibration values
- Writes `slot+0x1f8 = slot_index`, `slot+0x1fc = flags`
- Sets `controller+0x3c = 1` (ControllerDetails ready_flag)
- Does **NOT** write slot+0x200 (unique_id stays 0)

**Phase 2: Feature Report Response Processing**
- The state machine at `0x10d4e6c` processes GET_ATTRIBUTES/GET_SERIAL/0xf2 responses
- Responses are stored in the state machine object (r15+0xc0 settings array)
- A separate function reads from the state machine and writes to the identity slot
- The unique_id at slot+0x200 is written when the serial number response is processed

### The Critical Write Path

The write to slot+0x200 is NOT a single instruction. It happens through a chain:

1. **Feature Report Processing State Machine** (`0x10d4e6c`)
   - Receives response data from ATT layer
   - Dispatches based on command byte (0x83=GET_ATTRIBUTES, 0x84=GET_SERIAL, 0xf2=CAPABILITIES)
   - Stores parsed data in internal structures

2. **Identity Slot Population** (within function at `0x105cb50`, controller.cpp)
   - Large function (~500 instructions) that processes controller data
   - Reads from the state machine's internal data structures
   - Writes to identity slot at `controller+slot*0xe8+0x1f8`
   - The unique_id at slot+0x200 is written from the parsed serial number

3. **Identity Data Copy** (function at `0x105ca80`)
   - Checks: `cmp byte [rbp + rax + 0x200], 0` (slot+0x200 must be non-zero)
   - If non-zero: copies 0x21 bytes from source buffer to slot+0x214 (identity_data)
   - ASSERTION if zero: `"m_rgControllerIDs[unControllerIndex].rgchSerialNumber[0]"`

### The Blocker

The zombie check at `0x107088c` reads:
```
cmp byte [rax+0x200], 0    ; rax = controller + slot*0xe8
jne 0x10708a0               ; if non-zero → success
```

For this check to pass, slot+0x200 must be non-zero. This happens ONLY when the feature report handshake completes and the serial number is written to the identity slot.

The feature report handshake requires BlueZ hog-lib.c to send ATT Read Requests (0x0A) for Feature Reports. This never happens because hog-lib.c is reactive — it only sends requests in response to host (USB) requests via the UHID_GET_REPORT path.

### Response Format Expected

The feature report processing code expects responses starting with a command byte:

| Command | Byte 0 | Payload | Stored In |
|---------|--------|---------|-----------|
| GET_ATTRIBUTES | 0x83 | Product ID, secondary ID, capabilities | slot+0x1f8, +0x1fc, +0x234 |
| GET_SERIAL | 0x84 | Serial number string | slot+0x200 (17 bytes, first byte MUST be non-zero) |
| CAPABILITIES | 0xf2 | Category + capability data | slot+0x214 (32 bytes, concatenated) |

### Can We Trigger via ATT Notification?

**NO.** ATT Notifications (0x1B) on Feature Report characteristic handle 0x0024 will NOT work because:
1. hog-lib.c's `report_value_cb()` only processes Input Reports (Report Type = 0x01)
2. Feature Reports (Report Type = 0x03) are NOT processed through the notification path
3. Feature Reports are accessed via GET_REPORT path (ATT Read Request 0x0A)
4. The GET_REPORT path is triggered by `SDL_hid_get_feature_report()` → `ioctl(HIDIOCGFEATURE)` → `UHID_GET_REPORT` → hog-lib.c

### Can We Fix the IPC Pipe?

**NO — IPC pipe is NOT the solution.** The IPC pipe "hiddevicepipesteam" is used by `CGetControllerInfoWorkItem` to read controller details. However:
1. The IPC pipe populates ControllerDetails_tE (at `controller+0x1070+id*0x54`)
2. The zombie check reads from the identity slot (at `controller+slot*0xe8+0x200`)
3. These are DIFFERENT data structures at DIFFERENT memory addresses
4. Fixing the IPC pipe would NOT populate the identity slot

### The Real Fix

The real fix is to make BlueZ's hog-lib.c send ATT Read Requests for Feature Reports. This requires:
1. Ensuring the Feature Report characteristic has the correct Report Reference descriptor (Report Type = 0x03)
2. Ensuring hog-lib.c registers a GET_REPORT handler for this characteristic
3. Ensuring the UHID_GET_REPORT request reaches hog-lib.c

### Binary References

| Address | Function | Description |
|---------|----------|-------------|
| `0x105c7f0` | InitializeSlotDefaults | Clears identity slot, sets defaults |
| `0x105ca80` | CopyIdentityData | Requires slot+0x200 != 0, copies identity data |
| `0x105cb50` | MainControllerSetup | Large function, reads/writes identity slot |
| `0x1070620` | GetControllerInfo | Zombie check, reads slot+0x200 |
| `0x10d4e6c` | FeatureReportStateMachine | Processes FR 0x00 responses |
| `0x1092820` | QueueFetchingControllerDetails | Writes ControllerDetails (NOT identity slot) |

---

## TASK 21: EXACT Feature Report Response Formats (CRITICAL)

### Status: **DETERMINED**

### The Function at 0x10c1f5f

This is the INITIAL controller setup function. For SC2 BLE (PID 0x1303), it handles the complete feature report handshake. The function:

1. **Reads Feature Report 0x00 (GET_SERIAL, command 0xAE)** — multiple retries
2. **Reads Feature Report 0x00 (GET_ATTRIBUTES, command 0x83)** — one round
3. **Processes response data** — extracts PID, serial, capabilities
4. **Returns populated output struct** — caller copies to identity slot

### GET_ATTRIBUTES (0x83) Response Format

**Write command** (SET_REPORT): `[0x83, 0x00]` (2 bytes)
**Read response** (GET_REPORT): 62 bytes (0x3E)

Response byte layout:
```
Byte 0:    0x83 (command echo — MUST match)
Byte 1:    N = attribute byte count (MUST be > 0, multiple of 5)
Byte 2+:   N bytes of attribute data (N/5 groups of 5 bytes each)
Bytes 2+N to 61: zeros (padding)
```

Each attribute group (5 bytes):
```
Byte 0: Tag (0x00-0x0b, MUST be <= 0x0b)
Byte 1-4: Value (uint32 little-endian)
```

Jump table at `0x00aa3f98` dispatches based on tag. Only tag 1 confirmed:
- **Tag 1**: Writes VID:PID to output struct. VID hardcoded to 0x28de, PID from value low word.

Validation at `0x10c2c48-0x10c2c6a`:
- byte[1] must be non-zero
- count/5 gives number of attribute groups
- byte[1] <= 4 → simple path, byte[1] > 4 → multi-group path
- First attribute tag at byte[2] must be <= 0x0b

**Our current response `83 2d 01 03 13 00 00 02 ff bf 69 41...` format is CORRECT.**

### GET_SERIAL (0xAE) Response Format

**Write command** (SET_REPORT): `[0xAE, 0x15, 0x01, 0x00 × 20]` (23 bytes)
**Read response** (GET_REPORT): 23 bytes (0x17)

Response byte layout:
```
Byte 0:    0xAE (command echo — MUST match)
Byte 1:    Length/info byte (should match write command byte[1] = 0x15)
Byte 2:    Status: 0x01 = valid serial, anything else = invalid
Bytes 3-22: Serial number (20 bytes, ASCII string, null-padded)
```

Validation flow:
- byte[0] must be 0xAE
- byte[2] must be 0x01 (if not → "Controller Serial# invalid")
- Then call `0x26b1ac0` with serial data at offset 3 → if returns non-zero, serial rejected
- If validation passes: memcpy 20 bytes to output+0x3d

**BUG IN OUR RESPONSE: byte[1] = 0x14 but should be 0x15 (matching write command)**

### Report ID Prefix: NONE

The command byte IS the first byte of the HID feature report data. No Report ID prefix. Evidence:
- Write commands start with command byte (0x83, 0xAE)
- Response checks byte[0] against command byte
- BLE HID: ATT Read Response contains just report data, no Report ID

### The "Invalid or missing unit serial number" Error

The message at string `0xcaedd8` is from a DIFFERENT code path (identity slot validation at `0x105cb50`), NOT from the Feature Report processing. The serial "SC2DECK001" reaches Steam but is rejected because:

1. The validation function at `0x26b1ac0` rejects the serial format
2. The expected format is likely MAC-derived: "VID-PID-hash" (e.g., "28de-1303-2efea7d")
3. Steam replaces invalid serials with generated defaults

### Files Generated

| File | Content |
|------|---------|
| `functions/get_attributes_format.c` | **NEW** Complete 0x83 response format analysis |
| `functions/get_serial_format.c` | **NEW** Complete 0xAE response format analysis |
| `functions/xf2_format.c` | **NEW** 0xf2 format (partially determined) |
| `functions/report_id_prefix.c` | **NEW** No Report ID prefix (confirmed) |

---

## SESSION 6 (2026-06-26 afternoon) — Key Breakthroughs

### Finding: BlueZ DOES Send ATT Read Requests for Feature Reports

The GET_REPORT path works. BlueZ's hog-lib.c sends ATT Read Requests (0x0A) for Feature Report 0x00 during GATT discovery AND when Steam opens the controller. Our ATT server receives them and returns responses.

**Evidence**: Deck logs show `Read Request: handle=0x0024` and `FR 0x00 READ called`.

### Finding: GET_SERIAL Format Bug

**Bug**: byte[1] was 0x14 but write command sends 0x15. These must match.

**Fix**: Changed byte[1] from 0x14 to 0x15. Also: serial must start with 'F' (0x46) to pass V_strncmp validation at 0x26b1ac0.

**Old format**: `[0xAE, 0x14, 0x01, "SC2DECK001", ...]` → rejected
**New format**: `[0xAE, 0x15, 0x01, "F0000-0000-00000000", ...]` → accepted

### Finding: Serial Validation is V_strncmp

The validation function at 0x26b1ac0 is `V_strncmp` from Valve's vstdlib. It's called with `count=1`, so it only checks the **first byte** of the serial against the pattern at 0xd69c60. First byte must be 0x46 ('F').

### Finding: Identity Slot Populated by Feature Report Processing

The identity slot at `controller+slot*0xe8+0x200` is populated by the feature report response processing code at 0x10d4e6c. This code runs when Steam reads Feature Report 0x00 and gets responses. The serial number (unique_id) at slot+0x200 is the ready flag — first byte must be non-zero.

### Finding: Zombie Disconnect is PRE-EXISTING

Tested old commit `1b6bfde` (yesterday 6:51 PM) — same zombie disconnect and encryption error. Both issues existed before our changes. Input was probably always intermittent, working briefly during the window before the zombie timer fires.

### Finding: Encryption Error is PRE-EXISTING

`set_report_cb() Error: Encryption Key Size is insufficient` persists even without BT_SECURITY_MEDIUM. This is a BlueZ HOG profile internal issue — not caused by our code.

### Finding: Feature Report WRITE Commands Arrive Late

Feature report WRITE commands (SET_REPORT) arrive ~150 seconds after connection. The zombie timer fires at ~10 seconds. The identity slot is never populated because the writes arrive too late.

### Files Generated

| File | Content |
|------|---------|
| `functions/controller_identity_check.c` | **NEW** 0x1070620 disassembly (7-check gate) |
| `functions/registration_data_flow.c` | **NEW** What data registration needs |
| `functions/zombie_disconnect.c` | **NEW** Zombie check conditions |
| `functions/serial_validation.c` | **NEW** V_strncmp validation analysis |
| `functions/serial_format.c` | **NEW** Serial number format requirements |
| `functions/slot_data_population.c` | **NEW** Identity slot vs ControllerDetails |
| `functions/notification_trigger.c` | **NEW** Why ATT notifications won't work |
| `functions/ipc_pipe_fix.c` | **NEW** IPC pipe analysis |

---

*Analysis date: 2026-06-25 (updated 2026-06-28, sessions 1-7)*
*Binary analyzed: `~/.steam/debian-installation/linux64/steamclient.so` (46,488,096 bytes)*
*SDL3 source: `src/joystick/hidapi/SDL_hidapi_steam_triton.c` (GitHub)*
*BlueZ binary: `/usr/libexec/bluetooth/bluetoothd`*
*Tools used: radare2, objdump, Python scripts, SDL3 source code*

---

## SESSION 7 (2026-06-28) — Haptics Root Cause Analysis

### Finding: `0x17252a0` is DEAD CODE

The haptic trigger function at `0x17252a0` has **ZERO callers** in the entire 46MB binary. Searched via:
- E8 call-rel32 scan (Python)
- 64-bit pointer search
- 32-bit value search
- LEA [rip+disp32] search
- Relocation search (.rela.dyn + .rela.plt)
- GOT/.got.plt search
- .data.rel.ro vtable search
- MOV imm64 search
- Jump table dispatch search
- objdump disassembly grep
- radare2 `axt`

All returned zero matches. The function exists but is never invoked. Checks inside it (+0x320, +0x308) are downstream and irrelevant to the current blocking.

### Finding: SDL.joystick.cap.rumble is NOT the Blocker

The string `SDL.joystick.cap.rumble` at `0x00d0d093` IS referenced in code at `0x0176a25d`. The code queries it via `[0x02c6a868]` (likely `SDL_GetHintBoolean`) and gates bit 14 (0x4000) in the capability bitmask. However, Steam IS scheduling haptics (`CPulseHapticWorkItem` appears in Steam logs), so this capability check is NOT the blocker.

### Finding: Primary Blocker is hog-ll SET_REPORT Failure

BlueZ hog-ll tries SET_REPORT ~100 times/second and fails (487 errors in btmon). Without SET_REPORT success, the output report path is never established and haptic writes from Steam are rejected at kernel level. Steam schedules `CPulseHapticWorkItem` but the write completes in 0.0ms (rejected).

### Finding: SET_SETTINGS 0x09 Notification Not Delivered

Real SC2 sends notification `[0x87, 0x01, register, 0x00 × 61]` on handle 0x0033 after each SET_SETTINGS write. Our code intentionally skips this (to avoid phantom button presses). Steam retries every ~3 seconds, never completing the state machine.

### Finding: GATT/HID Metadata is Correct

Report Map declares output report 0x80, CHR_REPORT exists at handle 0x0019 with correct properties, Report Reference is `[0x80, 0x02]`, write callback is registered. All checks pass. The issue is upstream in BlueZ/Steam, not in our GATT database.

### Files Generated

| File | Content |
|------|---------|
| `functions/haptic_dead_code_analysis.c` | **NEW** Analysis of 0x17252a0 and its lack of callers |
| `functions/sdl_rumble_capability.c` | **NEW** SDL.joystick.cap.rumble analysis |
| `functions/set_report_failure.c` | **NEW** hog-ll SET_REPORT failure analysis |

---

## SESSION 8 (2026-06-29) — Native Deck vs BLE Haptics Comparison

### Finding: 0x8F Haptic Feedback Command Appears on Native but NOT on BLE

**Status: CONFIRMED**

Native Deck HIDIOCSFEATURE capture shows 124 calls in 35 seconds during initialization. Command breakdown:
- 0x87 SET_SETTINGS: 61 calls
- 0x81 ClearDigitalMappings: 38 calls
- **0x8F Haptic: 16 calls**
- 0xAE GET_SERIAL: 4 calls
- 0x83 GET_ATTRIBUTES: 2 calls
- 0xC1/0xDC/0xE2: 1 each

**0x8F appears 16 times on native but NEVER on BLE.** This is the most significant difference between native and BLE haptics behavior. **Confidence: Confirmed**

### Finding: 0x8F Appears During Initialization and Steady State

**Status: CONFIRMED**

0x8F appears during initialization (positions 9,10 right after SET_SETTINGS commands) and during steady state. This suggests 0x8F is not just an initialization command but an ongoing haptic feedback mechanism. **Confidence: Confirmed**

### Finding: All Commands Go Through HIDIOCSFEATURE

**Status: CONFIRMED**

All commands on native Deck go through HIDIOCSFEATURE (SET_FEATURE), NOT write() (output report). This means the haptic commands are Feature Reports, not Output Reports. **Confidence: Confirmed**

### Finding: Initial Handshake Sequence on Native

**Status: CONFIRMED**

The initial handshake sequence on native Deck is:
```
0x83 → 0xAE → 0xAE → 0x81 → 0x87×4 → 0x8F×2 → 0x81 → 0x87 → ...
```
**Confidence: Confirmed**

### Finding: BLE Handshake Sends Full Command Suite

**Status: CONFIRMED**

Steam DOES send the full command suite on BLE:
- 0x87×55 SET_SETTINGS
- 0x81×8 ClearDigitalMappings
- 0xAE×19 GET_SERIAL (retrying)
- 0x83×1 GET_ATTRIBUTES
- 0xC1/0xDC/0xE2/0xF2×1 each

**Confidence: Confirmed**

### Finding: GET_SERIAL Retries Differ Between Native and BLE

**Status: CONFIRMED**

GET_SERIAL retries 19 times on BLE vs 4 on native. This suggests the BLE path has more difficulty completing the serial handshake. **Confidence: Confirmed**

### Finding: Controller IS Registered on BLE

**Status: CONFIRMED**

controller_ui.txt shows "Auto-Registering controller: F0000-0000-00000000, 12345678". The serial "F0000-0000-00000000" IS accepted by Steam. **Confidence: Confirmed**

### Finding: "Skipping usage report" is Normal

**Status: CONFIRMED**

"Skipping usage report" is normal behavior that happens on both native and BLE. This is NOT an error. **Confidence: Confirmed**

### Finding: Native vs BLE GET_SERIAL Write Data Differs

**Status: CONFIRMED**

Native GET_SERIAL write data: `ae 15 01 05 12 00 00 02 00 00 00 00 0a 2b 12 a9 62 04 3c b0 c6 69`
BLE GET_SERIAL write data: `ae 15 04 00 34 5e bc e8 5c d7 8f c5 c8 d8 8f c5 a0 48 a7 e8 07 00`

Write data differs between native and BLE (different serial hashes). Our handler ignores write data and returns fixed synthetic serial. **Confidence: Confirmed**

### Finding: 0x8F Gate Hypothesis (UNVERIFIED)

**Status: UNVERIFIED — May Be Hallucination**

Subagent claimed:
- `[r15+0x208]` at `0x10d4da0` gates 0x8F dispatch
- `YieldingRunTestProgram` at `0x15677f4` is the ONLY function that sets this flag

**WARNING**: `strings` on steamclient.so shows NO "YieldingRunTestProgram" string. This may be a hallucination from the subagent. Needs verification via binary analysis. **Confidence: Unverified**

### Finding: Native Deck HID Capture Method

**Status: CONFIRMED**

- strace with `-f` flag (follow forks) on the Steam process
- Must capture from BEFORE Steam opens the hidraw device
- Watch for `/dev/hidraw4` to appear, then strace the owner PID with `-f`
- HIDIOCSFEATURE calls use Report ID 0x00 (first byte)
- All calls are 65 bytes (Report ID + 64 bytes payload)
**Confidence: Confirmed**

### Finding: ATT Server Write Response Handling

**Status: CONFIRMED**

Feature Report writes arrive as ATT Write Request (0x12) on handle 0x0024. Our handler stores the write data and sends ATT Write Response. Need to verify: does the response format match what BlueZ's UHID layer expects? **Confidence: Write arrival Confirmed, response format Unverified**

### Implications for Steam Haptics Investigation

The 0x8F command is the most promising lead for understanding why Steam-generated haptics do not work on BLE. Possible explanations:

1. **0x8F gates haptic dispatch** — If 0x8F is required for haptics to function, its absence on BLE explains why Steam-generated haptics don't work.
2. **0x8F is a haptic feedback acknowledgment** — On native, the controller sends 0x8F back to Steam. On BLE, our handler returns zero-padded echo, which may not match the expected format.
3. **0x8F is irrelevant** — Its absence on BLE may be coincidental, and the real blocker is elsewhere.

The next step is to investigate whether responding to 0x8F with the correct format enables Steam haptics on BLE.

### Files Generated

| File | Content |
|------|---------|
| `functions/native_hidio_csfeature_capture.c` | **NEW** Analysis of native Deck HIDIOCSFEATURE calls |
| `functions/ble_handshake_comparison.c` | **NEW** Native vs BLE handshake comparison |
| `functions/0x8f_haptic_gate.c` | **NEW** Analysis of 0x8F as potential haptic gate |
| `functions/serial_write_data_diff.c` | **NEW** Native vs BLE GET_SERIAL write data differences |
