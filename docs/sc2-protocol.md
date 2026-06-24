# Steam Controller 2026 BLE Protocol

## Device Identification

| Mode | VID | PID | Product Name |
|------|-----|-----|--------------|
| BLE | 0x28DE | 0x1303 | Steam Controller 2026 |
| USB (wired) | 0x28DE | 0x1302 | Steam Controller 2026 |
| Puck (dongle) | 0x28DE | 0x1304 | Steam Controller Puck |

- **Manufacturer**: Valve Software
- **Vendor ID**: 0x28DE (Valve)
- **PnP ID PID**: 0x0003

## GATT Service UUID

```
100F6C32-1735-4313-B402-38567131E5F3
```

This is the primary HID service UUID for the Steam Controller 2026 BLE profile. It is NOT the standard HID service (0x1812) — it is a Valve custom UUID.

## Characteristics

| Characteristic | UUID | Properties | Description |
|---------------|------|------------|-------------|
| Input Report 1 | `100F6C7A-...` | Read, Notify | Input report (report ID 0x45) |
| Input Report 2 | `100F6C7C-...` | Read, Notify | Input report (report ID 0x47) |
| Report | `100F6C34-1735-4313-B402-38567131E5F3` | Read, Write, Write Without Response | Output/feature report |

## Input Report Formats

### Report 0x45 (45 bytes) — Primary Input

```
Offset  Size  Description
0       1     Report ID (0x45)
1       1     Sequence number (incrementing)
2       4     Button state (32-bit bitmask)
6       1     Left trigger
7       1     Right trigger
8       2     Left stick X
10      2     Left stick Y
12      2     Right stick X
14      2     Right stick Y
16      2     Left trackpad X
18      2     Left trackpad Y
20      2     Right trackpad X
22      2     Right trackpad Y
24      2     IMU accelerometer X
26      2     IMU accelerometer Y
28      2     IMU accelerometer Z
30      2     IMU gyroscope X
32      2     IMU gyroscope Y
34      2     IMU gyroscope Z
36      4     IMU timestamp (32-bit, microseconds)
40      2     IMU quaternion W (fixed-point)
42      2     IMU quaternion X (fixed-point)
44      2     IMU quaternion Y (fixed-point)
46      2     IMU quaternion Z (fixed-point)
```

**Total: 48 bytes** (45 reported + overhead)

Note: This report does NOT include quaternion — it uses 32-bit timestamp only.

### Report 0x47 (47 bytes) — Extended Input

Same as 0x45 but adds 16-bit trackpad timestamp fields.

### Report 0x42 (53 bytes) — USB Input

Same as 0x45 but adds full quaternion (4 × 16-bit) to the IMU data.

## Button Bitmask (32-bit)

```
Bit 0:  A
Bit 1:  B
Bit 2:  X
Bit 3:  Y
Bit 4:  Left Bumper
Bit 5:  Right Bumper
Bit 6:  Left Grip
Bit 7:  Right Grip
Bit 8:  Start
Bit 9:  Steam
Bit 10: Left Pad Click
Bit 11: Right Pad Click
Bit 12: Left Stick Click
Bit 13: Right Stick Click (reserved)
Bit 14: Left D-Pad Up
Bit 15: Left D-Pad Down
Bit 16: Left D-Pad Left
Bit 17: Left D-Pad Right
Bit 18: Right D-Pad Up
Bit 19: Right D-Pad Down
Bit 20: Right D-Pad Left
Bit 21: Right D-Pad Right
Bit 22: Left Trackpad Touch
Bit 23: Right Trackpad Touch
Bit 24-31: Reserved / Extended
```

## HID Descriptor (Vendor Interface)

```
Usage Page (0xFF00)        ; Vendor-defined
Usage (0x01)               ; Vendor usage
Collection (Application)
  Report ID (0x00)
  Report Size (8)
  Report Count (64)
  Input (Data, Var, Abs)   ; 64-byte vendor input report
  Report ID (0x00)
  Report Size (8)
  Report Count (64)
  Output (Data, Var, Abs)  ; 64-byte vendor output report
End Collection
```

The vendor HID interface uses Usage Page 0xFF00 with 64-byte I/O reports. This is used for raw vendor communication (firmware updates, feature reports).

## Mode Switching

The SC2 starts in **Lizard Mode** (basic keyboard/mouse emulation):
- Left trackpad: mouse movement
- Right trackpad: scroll
- Buttons: keyboard keys
- Triggers: left/right mouse buttons

To switch to **Steam Input Mode** (full controller input):
1. Steam Client sends a feature report to the device
2. Device switches from lizard mode to Steam Input mode
3. Device begins sending full controller input reports

Key strings from Steam Client:
- `toggle_lizard` — toggle lizard mode
- `is_mode_switching_supported` — check if mode switching is available
- `CExitLizardModeWorkItem` — work item to exit lizard mode

## Feature Reports

| Report ID | Direction | Description |
|-----------|-----------|-------------|
| 0x00 | Device → Host | Device identification (0x87 0x03 0x09...) |
| 0x01 | Device → Host | Device capabilities |
| 0x85 | Host → Device | Mode switch (lizard/Steam Input) |
| 0x86 | Host → Device | Configuration |
| 0x87 | Host → Device | Calibration data |

## Pairing

The SC2 uses standard BLE pairing:
1. Device advertises with SC2-specific service UUID
2. Host scans and connects
3. Pairs using Just Works or Passkey
4. Discovers GATT services
5. Subscribes to input report notifications
6. Sends feature report to switch out of lizard mode
7. Begins receiving controller input

## Comparison with Steam Deck (Neptune)

The Steam Deck controller ("Neptune") uses:
- VID: 0x28DE
- PID: 0x1205
- 5 USB interfaces (mouse, keyboard, vendor HID, audio, CDC)
- Separate motion sensor input device
- Virtual Xbox 360 pad via hid-steam driver

The SC2 BLE profile is significantly simpler, using a single GATT service with characteristics for input/output.
