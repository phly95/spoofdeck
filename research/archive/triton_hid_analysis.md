# Triton (SC2) Firmware HID Input Report Analysis

**Firmware**: `ibex_firmware.bin` (350,528 bytes / 0x55940)  
**Platform**: Nordic nRF52840, ARM Cortex-M4F, Zephyr RTOS  
**Analysis date**: 2026-06-30  

---

## 1. HID Report Descriptor

Found at firmware offset `0x49a26` (and duplicate at `0x49ecb`). The descriptor defines these report IDs:

| Report ID | Direction | Size | Type | Description |
|-----------|-----------|------|------|-------------|
| 0x40 | Input | ~6B | Mouse | Buttons(2b), X/Y(8b signed relative), Hatswitch, AC Pan |
| 0x41 | Input | 7B | Keyboard | 8 modifier keys + 6 keycodes |
| 0x42 | Input | 53B | Vendor | Vendor-defined input |
| 0x43 | Input | 14B | Vendor | Vendor-defined input |
| 0x44 | Input | 5B | Vendor | Vendor-defined input |
| **0x45** | **Input** | **45B** | **Vendor** | **Main gamepad report** |
| 0x47 | Input | 47B | Vendor | Extended report (not found in descriptor, see notes) |
| 0x79 | Input | 1B | Vendor | Vendor-defined input |
| 0x7B | Input | 12B | Vendor | Vendor-defined input |
| 0x80 | Output | 9B | Vendor | Haptics (rumble) |
| 0x81 | Output | 7B | Vendor | Lizard mode clear |
| 0x82 | Output | 3B | Vendor | Vendor-defined output |
| 0x83 | Output | 9B | Vendor | Vendor-defined output |
| 0x84 | Output | 8B | Vendor | Vendor-defined output |
| 0x85 | Output | 3B | Vendor | Vendor-defined output |
| 0x86 | Output | 3B | Vendor | Vendor-defined output |
| 0x87-0x89 | Output | 63B | Vendor | Large output reports |
| 0x01 | Feature | 63B | Vendor | Command channel |
| 0x02 | Feature | 63B | Vendor | Command channel |

**Note**: All 0x45 report data uses Usage Page `0xFF00` (vendor) with Usage `0x45`. The report data is entirely vendor-defined — no structured sub-fields are declared in the HID descriptor. Steam Client interprets the 45 raw bytes based on its own internal knowledge of the SC2 protocol.

---

## 2. Report 0x45 Construction Pipeline

### Data Flow Diagram

```
Neptune Controller Input (hidraw3)
        │
        ▼
┌──────────────────────────────────────────┐
│  FUN_000167d0 — Main Controller Loop     │
│  (processes trackpads, sticks, IMU)      │
│                                          │
│  ├─ FUN_00011498 (IMU processing)        │
│  │   ├─ FUN_0003ab58 (read IMU axes)     │
│  │   ├─ FUN_00011460 (scale IMU data)    │
│  │   ├─ FUN_00019598/00019530 (filter)   │
│  │   └─ FUN_00014064(local_5c, type=7)   │  ← writes IMU+trackpad data
│  │                                       │
│  ├─ FUN_0004373e (scale trackpad raw)    │
│  │   └─ DAT_00035d50 (calibration data)  │
│  │                                       │
│  ├─ FUN_0001672c(0, ...) — Left trackpad │
│  │   └─ FUN_00014064(local_34)          │  ← writes left trackpad
│  │                                       │
│  ├─ FUN_0001672c(1, ...) — Right trackpad│
│  │   └─ FUN_00014064(local_34)          │  ← writes right trackpad
│  │                                       │
│  ├─ FUN_0003a790(DAT_..., local_2c)      │
│  │   └─ FUN_00014064(local_2c)          │  ← writes stick/trigger data
│  │                                       │
│  ├─ FUN_0003a790(DAT_..., local_2a)      │
│  │   └─ FUN_00014064(local_2c)          │  ← writes stick/trigger data
│  │                                       │
│  └─ FUN_00013fe0() — SEND REPORT         │
│      ├─ FUN_00013858() — check ready     │
│      ├─ FUN_000138d0() — alloc buffer    │
│      ├─ Set report ID: *puVar5 = 0x45    │
│      ├─ Copy 45 bytes from state buffer  │
│      └─ FUN_00013980() — BLE notify     │
└──────────────────────────────────────────┘
```

### Key Functions

| Function | Address | Size | Role |
|----------|---------|------|------|
| `FUN_00013fe0` | `0x00013fe0` | 118B | **Report sender** — allocates buffer, sets Report ID 0x45, copies 45 bytes from state buffer, sends via BLE notification |
| `FUN_00014064` | `0x00014064` | 470B | **State updater** — receives typed input commands (0-7) and writes to the 45-byte report data buffer at `DAT_00014200` |
| `FUN_000167d0` | `0x000167d0` | 1014B | **Main controller loop** — processes trackpads, IMU, sticks, calls `FUN_00013fe0` to send report |
| `FUN_00013858` | `0x00013858` | 6B | Check if report sending is allowed |
| `FUN_000138d0` | `0x000138d0` | 30B | Allocate report buffer from pool |
| `FUN_00013980` | `0x00013980` | varies | Send report via BLE GATT notification |

---

## 3. Report 0x45 — Byte Layout (45 Bytes)

The 45-byte report data is built by `FUN_00014064` which writes to a state structure at `DAT_00014200`. The report buffer is then copied as-is by `FUN_00013fe0`.

### Structure Layout

```
Offset  Size  Field                    Source Type
──────  ────  ───────────────────────  ──────────────
0x00    1B    Sequence counter         Incremented each report send
0x01    4B    Flags + Button bitmask   Case 4: 20-bit buttons + 12-bit flags
0x05    2B    Left trigger             Case 2: uint16 (0-0xFFFF)
0x07    2B    Right trigger            Case 3: uint16 (0-0xFFFF)
0x09    2B    Left stick X             Case 0: int16 (signed)
0x0B    2B    Left stick Y             Case 0: int16 (signed)
0x0D    2B    Right stick X            Case 1: int16 (signed)
0x0F    2B    Right stick Y            Case 1: int16 (signed)
0x11    2B    Gyroscope X              Case 5: uint16
0x13    2B    Gyroscope Y              Case 5: uint16
0x15    2B    Gyroscope Z              Case 5: uint16
0x17    2B    Accelerometer X          Case 6: uint16
0x19    2B    Accelerometer Y          Case 6: uint16
0x1B    2B    Accelerometer Z          Case 6: uint16
0x1D    4B    Trackpad left X/Y        Case 7: 2x int16
0x21    4B    Trackpad left X2/Y2      Case 7: 2x int16
0x25    2B    Trackpad left touch      Case 7: uint16
0x27    4B    Trackpad right X/Y       Case 7: 2x int16
0x2B    2B    Trackpad right touch     Case 7: uint16
──────  ────
Total:  0x2D = 45 bytes
```

**Note on offset 0x00**: The copy loop in `FUN_00013fe0` copies 45 bytes from `DAT_00014058` to the report buffer (after the Report ID byte). The first byte is a sequence counter that increments with each report.

### Flags Word (Offset 0x01)

The 32-bit flags word at offset 0x01 contains:

```
Bit  0-19:  Button bitmask (20 bits)
Bit 20:     Accelerometer active/touch flag
Bit 21:     Accelerometer secondary flag
Bit 22:     (unused or reserved)
Bit 23:     Right trigger active (set when trigger > 0)
Bit 24:     Gyroscope active/touch flag
Bit 25:     Gyroscope secondary flag
Bit 26:     (unused or reserved)
Bit 27:     Left trigger active (set when trigger > 0)
Bit 28:     Accelerometer mode flag
Bit 29:     Gyroscope mode flag
Bit 30-31:  (unused or reserved)
```

---

## 4. Input Source Mapping — `FUN_00014064` Command Types

`FUN_00014064` is the central state update function. It receives a command struct:
- `param_1[0]` = command type (0-7)
- `param_1[4..]` = payload data

### Case 0: Left Stick
```c
// Writes int16 X/Y to offsets 0x09, 0x0B in state structure
*(short *)(DAT_00014200 + 9) = sVar2;   // Left stick X
*(short *)(iVar5 + 0xb) = sVar3;        // Left stick Y

// Deadzone: if max(|X|, |Y|) < 0xfa1 (4001), set deadzone flag = 0
// Otherwise deadzone flag = 1
```

### Case 1: Right Stick
```c
// Writes int16 X/Y to offsets 0x0D, 0x0F in state structure
*(short *)(DAT_00014200 + 0xd) = sVar2;  // Right stick X
*(short *)(iVar5 + 0xf) = sVar3;         // Right stick Y
// Same deadzone logic as Case 0
```

### Case 2: Left Trigger
```c
// Writes uint16 to offset 0x05
*(ushort *)(DAT_00014200 + 5) = *(ushort *)(param_1 + 4);

// Sets bit 27 (0x8000000) in flags if trigger value != 0
if (trigger_val != 0)
    flags |= 0x8000000;
else
    flags &= ~0x8000000;
```

### Case 3: Right Trigger
```c
// Writes uint16 to offset 0x07
*(ushort *)(DAT_00014200 + 7) = *(ushort *)(param_1 + 4);

// Sets bit 23 (0x800000) in flags if trigger value != 0
if (trigger_val != 0)
    flags |= 0x800000;
else
    flags &= ~0x800000;
```

### Case 4: Buttons (20-bit bitmask)
```c
// Lower 20 bits of param_1[1] become button state
uint button_mask = *(uint *)(param_1 + 4) & 0xfffff;
flags = (flags & 0xfff00000) | button_mask;  // Merge with upper flag bits
```

The 20-bit button bitmask maps to (from firmware string analysis):
```
Bit 0:   (possibly QAS / quick access)
Bit 1:   Dpad Up
Bit 2:   Dpad Down  
Bit 3:   Dpad Left
Bit 4:   Dpad Right
Bit 5:   A (Right lower grip)
Bit 6:   B (Right upper grip)
Bit 7:   X (Left lower grip)
Bit 8:   Y (Left upper grip)
Bit 9:   Left Bumper
Bit 10:  Right Bumper
Bit 11:  Left View (Select/Back)
Bit 12:  Right View (Start)
Bit 13:  Left Thumbstick click
Bit 14:  Right Thumbstick click
Bit 15:  Steam button
Bit 16:  Left upper grip (L4)
Bit 17:  Left lower grip (L5)
Bit 18:  Right upper grip (R4)
Bit 19:  Right lower grip (R5)
```

**NOTE**: This bit assignment is inferred from the firmware string order and SC2 protocol conventions. The exact bit positions need verification against a real SC2 capture or Steam's internal mapping tables. The firmware string order (at `0x50d90`) is:
`QAS, R_THUMB, MENU, R_UPPER_GRIP, R_LOWER_GRIP, R_BUMPER, Dpad up/down/left/right, Steam, Left upper grip, Left lower grip, Left bumper, Left view, Left thumbstick`

### Case 5: Gyroscope
```c
// Writes 3x int16 (X, Y, Z) to offsets 0x11, 0x13, 0x15
*(undefined2 *)(DAT_00014200 + 0x11) = *(undefined2 *)(param_1 + 4);  // Gyro X
*(undefined2 *)(iVar5 + 0x13) = *(undefined2 *)(param_1 + 6);          // Gyro Y
*(undefined2 *)(iVar5 + 0x15) = *(undefined2 *)(param_1 + 8);          // Gyro Z

// Flags for gyro state:
// param_1[10] != 0 → set bit 24 (gyro active)
// param_1[13] != 0 → set bit 29 (gyro mode)
// param_1[11] != 0 → set bit 25 (gyro secondary)
// param_1[12] != 0 → set bit 26 (gyro additional)
```

### Case 6: Accelerometer
```c
// Writes 3x int16 (X, Y, Z) to offsets 0x17, 0x19, 0x1B
*(undefined2 *)(DAT_00014200 + 0x17) = *(undefined2 *)(param_1 + 4);  // Accel X
*(undefined2 *)(iVar5 + 0x19) = *(undefined2 *)(param_1 + 6);          // Accel Y
*(undefined2 *)(iVar5 + 0x1b) = *(undefined2 *)(param_1 + 8);          // Accel Z

// Flags for accel state:
// param_1[10] != 0 → set bit 20 (accel active)
// param_1[13] != 0 → set bit 28 (accel mode)
// param_1[11] != 0 → set bit 21 (accel secondary)
// param_1[12] != 0 → set bit 22 (accel additional)
```

### Case 7: Trackpad + IMU combined
```c
// Writes multi-field data to offsets 0x1D-0x2C
*(undefined4 *)(DAT_00014200 + 0x1d) = *(undefined4 *)(param_1 + 4);  // 4B trackpad L X/Y
*(undefined4 *)(iVar5 + 0x21) = uVar9;                                  // 4B trackpad L X2/Y2
*(undefined2 *)(iVar6 + 4) = *(undefined2 *)(param_1 + 0xc);            // 2B trackpad L touch
*(undefined4 *)(iVar5 + 0x27) = *(undefined4 *)(param_1 + 0xe);         // 4B trackpad R X/Y
*(undefined2 *)(iVar6 + 10) = *(undefined2 *)(param_1 + 0x12);          // 2B trackpad R touch
```

---

## 5. Analog Input Processing (Calibration/Scaling)

### FUN_0004373e — Trackpad Calibration (126 bytes)

Converts raw ADC/SPI sensor values to 0-0xFFFF unsigned range using FPU:

```c
uint FUN_0004373e(uint raw_value) {
    // Read calibration max from DAT_00035d50 + 0x60
    int max_raw = (1 << *(byte*)(DAT_00035d50 + 0x60)) - 1;
    
    // Get calibration offset via FUN_000436be(DAT_00035d50 + 0x50, &max_raw)
    int result = FUN_000436be(DAT_00035d50 + 0x50, &max_raw);
    if (result != 0) return 0;  // Error: return zero
    
    float max_f = VectorSignedToFloat(max_raw, ...);
    float range_f = VectorSignedToFloat(max_range, ...);
    float raw_f = VectorSignedToFloat(raw_value, ...);
    
    float scaled = raw_f / (max_f / range_f);  // Scale to range
    
    if (scaled <= 0.0) return 0;
    if (scaled >= DAT_00035d54) return 0xFFFF;  // Clamp to max
    return VectorFloatToUnsigned(scaled, 3) & 0xFFFF;
}
```

### FUN_00043746 — IMU/Secondary Calibration (8 bytes)

Same algorithm as FUN_0004373e but reads calibration from `DAT_00035d50 + 0x10`:

```c
uint FUN_00043746(uint raw_value) {
    int max_raw = (1 << *(byte*)(DAT_00035d50 + 0x10)) - 1;
    int result = FUN_000436be(DAT_00035d50, &max_raw);
    // ... same scaling/clamping as FUN_0004373e ...
}
```

### Calibration Data Structure (`DAT_00035d50`)

This is the central calibration table for all sensors:
- Offset `0x10`: Bit width for IMU ADC resolution
- Offset `0x50`: IMU calibration parameters
- Offset `0x60`: Bit width for trackpad ADC resolution
- Offset `0x10` region: Trackpad calibration parameters

The functions `FUN_0004373e` and `FUN_00043746` use ARM Cortex-M4F FPU intrinsics (`VectorSignedToFloat`, `VectorFloatToUnsigned`) for hardware floating-point conversion.

---

## 6. Trackpad Data Processing

### Trackpad Touch Pipeline (in `FUN_000167d0`)

The main controller loop processes two trackpad entries with stride `0x3c` bytes:

```
Trackpad state entries at DAT_00016a78:
  Entry 0 (left):  offset -8 (mode), -6 (X raw), -4 (Y raw), -2 (touch)
  Entry 1 (right): offset +0x30 (mode), +0x32 (X raw), +0x34 (Y raw), +0x36 (touch)

Processing:
1. Check mode == 2 or 0x81 (active touch)
2. Scale X/Y through FUN_0004373e (trackpad calibration)
3. Get deadzone threshold via FUN_00013c30(0x44)
4. Call FUN_00015170 for touch event generation
```

### Trackpad Calibration Offset (in `FUN_000167d0`)

For each trackpad touch point:
```
1. Read raw X/Y from sensor struct
2. Add calibration offset from psVar20[] (left) or psVar25[] (right)
3. Clamp to [1, 0xFFFF] range
4. Byte-swap via FUN_00043746
5. Validate via FUN_0003a596 (checks all 4 corners have valid range)
```

### FUN_00015170 — Trackpad Touch Event (144 bytes)

Generates a haptic/event trigger when the trackpad is touched:
```
Input: param_1 = state struct, param_2/3 = X/Y scaled, param_4 = pressure
Logic:
  diff = |X - Y|  (diagonal difference for touch detection)
  if diff > 99:
    touch_active = 1
    Apply scaling factors from DAT_00015200/DAT_00015204
    Generate event via FUN_0003347c (haptic trigger on touch)
    Set touch pressure via FUN_0003360c/FUN_00033620
```

### FUN_0001672c — Individual Trackpad Handler (154 bytes)

Called for left (param_1=0) and right (param_1=1) trackpads:
```
1. Query trackpad mode via FUN_00013c30(0x2e)
2. If mode==1: Raw passthrough via FUN_00035ea8 (byte swap)
3. If mode==2: Direct assignment
4. Otherwise: Apply calibration via FUN_0003a600
5. Store results to DAT_000167c8 + DAT_000167cc
6. Build command struct: type = *(param_2 + 0xd0), X, Y
7. Call FUN_00014064 to update state
```

---

## 7. IMU Data Processing

### IMU Processing Chain (in `FUN_00011498` — 546 bytes)

```
1. Read 3-axis raw data via FUN_0003ab58(device, 3, &data)
   - Returns raw X, Y, Z as int32

2. Scale to angular rate:
   X_scaled = FUN_00011460(&raw_X) / 0x3d   (÷61)
   Y_scaled = FUN_00011460(&raw_Y) / 0x3d
   Z_scaled = FUN_00011460(&raw_Z) / 0x3d

3. Apply sensor fusion filter:
   FUN_00019598(&X_scaled)  — gyro calibration
   FUN_00019530(&Y_scaled)  — bias correction

4. Read accelerometer data via FUN_0003ab58(device, 7, &data)
   - Scale via FUN_00011460 (same as gyro)
   - Apply bias subtraction if DAT_000116dc flag is set
   - Scale factor: / 0x17d7 (÷6103)

5. Gyro drift compensation (if time delta valid):
   fVar10 = fPrevGyro / fTimeDelta + fNewGyro
   Stored in pfVar4[0..2] (3-axis gyro state)

6. Read additional accel data via FUN_0003ab58(device, 8, &data)

7. Read temp/additional sensor via FUN_0003ab58(device, 0x40, &data)

8. Build command struct:
   local_5c[0] = 7 (type: IMU+trackpad)
   local_5c[4..7] = accel X/Y/Z scaled
   local_5c[8..15] = gyro data
   local_5c[16..19] = additional data
   local_5c[20..23] = temperature/secondary data
   
9. Call FUN_00014064(local_5c)
```

### IMU Sensor Access IDs

| ID  | Sensor | Description |
|-----|--------|-------------|
| 3   | Gyroscope | Raw 3-axis gyroscope data |
| 7   | Accelerometer | Primary 3-axis accelerometer data |
| 8   | Accelerometer | Secondary accelerometer (or temperature-compensated) |
| 0x3d | Bias | Gyroscope bias calibration data |
| 0x3e | Mode | IMU mode query |
| 0x40 | Secondary | Additional sensor data (temperature?) |

### IMU Calibration Strings

From firmware binary at `0x51xxx`:
```
"cal/sensors/gyroscope/bias"     — Gyro bias calibration file
"settings/sensors/imu"           — IMU settings root
"settings/sensors/imu/gyro_threshold"  — Gyro deadzone threshold
"settings/sensors/imu/mode"      — IMU operating mode
"settings/sensors/imu/mounting_matrix"  — Board mounting orientation matrix
"settings/sensors/imu/use_bias"  — Whether to apply bias correction
"gyro_dz_threshold"             — Gyro deadzone threshold value
```

---

## 8. Haptic/Rumble Output Reports

### Output Report 0x80 (9 bytes)

The haptic output report is received from the host (Steam Client) and forwarded to the Neptune controller:

```
From host → ATT Write Request → _on_haptic_write()
Format: [0x80, cmd_type, 0, 0, 0, left_speed, left_hi, right_speed, right_hi]

Forwarded to Neptune as PackedRumbleReport:
[0xeb, 0x09, 0x00, 0x00, 0x00, left_lo, left_hi, right_lo, right_hi] (64 bytes)
```

### Output Report 0x81 (7 bytes)

Used to disable lizard mode on the Neptune controller:
```
Direct command: [0x81, ...] — clears digital mappings
Must be re-sent periodically (~2 seconds) as lizard mode auto-re-enables
```

---

## 9. Firmware String References

### HID/Controller Strings (from binary analysis)

| Address | String | Context |
|---------|--------|---------|
| `0x48824` | `Failed to send full HID report %d` | Error in report send |
| `0x48846` | `ibex_input` | Input subsystem name |
| `0x491a0` | `hid_stream` | HID streaming thread |
| `0x49741` | `Unable to send hid report` | Error in report send |
| `0x50d90` | `buttons` | Button endpoint name |
| `0x50e31` | `Left thumbstick` | Stick name |

### Endpoint Names (firmware `0x50c00+`)

```
QAS, R_THUMB, MENU, R_UPPER_GRIP, R_LOWER_GRIP, R_BUMPER,
Dpad up, Dpad down, Dpad left, Dpad right, Steam,
Left upper grip, Left lower grip, Left bumper, Left view, Left thumbstick
```

### I2C Device Names

| Device | Address | Description |
|--------|---------|-------------|
| `olympus@2c` | 0x2C | Trackpad controller (Olympus) |
| `mp2733@4b` | 0x4B | Battery charger IC |
| `slg4l48185@10` | 0x10 | GreenPAK programmable GPIO |
| `puck-pilot-gpio` | — | Puck/Gyro GPIO interface |

### Haptic System Strings

```
"haptics-sequencer-touchpad"    — Trackpad click haptic sequencer
"haptics-sequencer-gri-v3"      — Grip/rumble haptic sequencer
"haptics_sequencer"             — Main haptic sequencer
"channel-left"                  — Left motor channel
"channel-right"                 — Right motor channel
```

---

## 10. State Machine Overview

### Report Send Cycle (`FUN_000167d0`)

The main controller loop runs at a fixed rate (likely 100-200Hz based on timer constants):

```
Loop iteration:
1. Process left/right trackpad touch events (2 entries, stride 0x3c)
2. Process trackpad raw data (2 entries, stride 0xd4) with calibration
3. Wait for synchronization via FUN_00036a2c
4. Process timing synchronization via FUN_00036a2c
5. Read timing via thunk_FUN_00037978
6. Generate trackpad touch events via FUN_00043726
7. Send trackpad left/right via FUN_0001672c(0/1, ...)
8. Send stick/trigger data via FUN_0003a790 × 2
9. SEND REPORT: FUN_00013fe0()
10. Send haptic event: FUN_00013b68()
11. Measure cycle time, repeat (65 cycles per super-frame at 0x41)
```

### BLE Report Flow

```
Firmware state buffer (DAT_00014200, 45 bytes)
    │
    ▼
FUN_00013fe0():
    1. FUN_00013858() → check if BLE connection ready
    2. FUN_000138d0() → allocate BLE TX buffer
    3. puVar5[0] = 0x45 → set Report ID
    4. Copy 45 bytes from state buffer to puVar5[1..45]
    5. Increment sequence counter at state buffer[0]
    6. FUN_00013980(puVar5) → send via GATT notification
```

---

## 11. Key DAT_ References

| DAT_ Address | Type | Description |
|-------------|------|-------------|
| `DAT_00013860` | byte* | Report-send-ready flag |
| `DAT_000138f0` | void* | Report buffer pool |
| `DAT_00013c40` | short* | Mode/state lookup table (56 entries × 2 bytes) |
| `DAT_00014058` | byte* | Pointer to report data source buffer (45 bytes) |
| `DAT_00014200` | byte* | Controller state structure (written by FUN_00014064) |
| `DAT_00014204` | byte* | Controller state + 4 (alias for field access) |
| `DAT_00015284` | uint* | State change observer table |
| `DAT_00015288` | uint* | Observer table end |
| `DAT_00035d50` | void* | Calibration data structure |
| `DAT_00035d54` | float | Max scaling constant (clamping limit) |

---

## 12. Architectural Notes

1. **Single state buffer pattern**: All input sources (sticks, triggers, buttons, IMU, trackpad) write to a single shared 45-byte state buffer at `DAT_00014200` via `FUN_00014064`. This buffer is then copied atomically (with IRQ masking via `setBasePriority(0x40)`) to the BLE TX buffer in `FUN_00013fe0`.

2. **IRQ protection**: `FUN_00013fe0` masks interrupts to priority 0x40 (or higher) during the 45-byte copy to prevent tearing from concurrent `FUN_00014064` writes.

3. **Sequence counter**: The first byte of the state buffer is a sequence counter incremented after each report send. This allows the host to detect missed reports.

4. **Observer pattern**: After state updates, `FUN_00014064` iterates an observer table (`DAT_00015284`-`DAT_00015288`) to notify registered callbacks of state changes. Each observer has an activation mask and start/stop callbacks.

5. **No Report ID in descriptor sub-fields**: The HID descriptor declares report 0x45 as a flat 45-byte vendor blob. Steam Client internally parses the bytes based on its own protocol knowledge (the SC2 protocol spec).

6. **Calibration applied in firmware**: All analog values (sticks, triggers, IMU, trackpad) are calibrated and scaled to standard ranges (0-0xFFFF for unsigned, signed int16 for sticks) before being placed in the report buffer. The host receives pre-calibrated values.
