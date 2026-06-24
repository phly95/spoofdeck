# Steam Deck Hardware Findings

## Device Information

- **Serial**: FY2S443045FD
- **Controller VID**: 0x28DE (Valve)
- **Controller PID**: 0x1205
- **Product Name**: Valve Software Steam Controller
- **Serial Number**: 123456789ABCDEF
- **Operating System**: SteamOS (Arch Linux based)
- **GLib**: 2.84.3
- **BlueZ**: 5.86
- **Python**: 3.13

## USB Interfaces

The Steam Deck presents 5 USB interfaces when connected via USB:

| Interface | Class | SubClass | Protocol | Description |
|-----------|-------|----------|----------|-------------|
| 0 | 0x03 | 0x00 | 0x02 | HID Mouse |
| 1 | 0x03 | 0x01 | 0x01 | HID Keyboard |
| 2 | 0x03 | 0x00 | 0x00 | Vendor HID (Steam Input) |
| 3 | 0x02 | 0x02 | 0x01 | Audio (2 channels, 16-bit) |
| 4 | 0x0A | 0x00 | 0x00 | CDC Data |

## HID Report Descriptors

### hidraw0 — Mouse Interface

```
Usage Page (Generic Desktop)
Usage (Mouse)
Collection (Application)
  Usage (Pointer)
  Collection (Physical)
    Report Count (3)
    Report Size (1)
    Usage Page (Button)
    Usage Minimum (1)
    Usage Maximum (3)
    Logical Minimum (0)
    Logical Maximum (1)
    Input (Data, Var, Abs)           ; 3 button bits
    Report Count (1)
    Report Size (5)
    Input (Cnst, Var, Abs)           ; 5-bit padding
    Report Size (8)
    Report Count (2)
    Usage Page (Generic Desktop)
    Usage (X)
    Usage (Y)
    Logical Minimum (-127)
    Logical Maximum (127)
    Input (Data, Var, Rel)           ; X/Y relative 8-bit
    Report Size (8)
    Report Count (1)
    Usage (Wheel)
    Logical Minimum (-127)
    Logical Maximum (127)
    Input (Data, Var, Rel)           ; Wheel
    Report Size (8)
    Report Count (1)
    Usage (Pan)
    Logical Minimum (-127)
    Logical Maximum (127)
    Input (Data, Var, Rel)           ; Horizontal pan
  End Collection
End Collection
```

### hidraw1 — Keyboard Interface

Standard boot keyboard descriptor:
- 8 modifier bits (Ctrl, Shift, Alt, GUI × left/right)
- 1 byte reserved
- 6 key codes (standard 6-key rollover)
- LED output report (5 bits: Num Lock, Caps Lock, Scroll Lock, Compose, Kana)

### hidraw3 — Vendor Steam Input Interface

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

## Raw HID Data (hidraw3)

### Feature Report 0 (Read)

Returns device identification:
```
87 03 09 ...
```
- 0x87: Report type
- 0x03: Version?
- 0x09: Unknown

### Input Report 0x01

Returns 64 bytes of raw input data. This is the vendor-specific input used by the Steam Client for proprietary communication.

## Driver: hid-steam

The `hid-steam` kernel driver handles:
- hidraw0 (mouse interface)
- hidraw1 (keyboard interface)
- hidraw3 (vendor Steam Input interface)

The driver creates:
- **Virtual Xbox 360 pad** (`/dev/input/event10`, `/dev/input/js0`)
- **Motion sensors** as a separate input device

The virtual Xbox 360 pad is what applications see when the Deck is in USB mode.

## Bluetooth Adapter

| Property | Value |
|----------|-------|
| Adapter | Qualcomm QCA |
| Bluetooth Version | 5.3 |
| Roles | Central + Peripheral |
| Advertising Instances | 16 |
| Address | <DECK_BT_MAC_PUBLIC> |
| Name | steamdeck |
| Supported Settings | LE, Static Address, Wide Band Speech, etc. |

The adapter supports the **peripheral role**, which is required for advertising GATT services. Most laptop BT adapters only support central role.

The 16 advertising instances allow multiple concurrent advertisements, though we only need one for the SC2 spoof.

## Input Devices

| Device | Type | Description |
|--------|------|-------------|
| event10 | Virtual Xbox 360 | Created by hid-steam driver |
| js0 | Joystick | Virtual Xbox 360 pad |
| Motion sensors | IMU/Accelerometer | Separate input device |

## Storage

- Root filesystem: btrfs
- steamos-readonly: enabled by default
- Must disable with `steamos-readonly disable` before making system changes

## Key Observations

1. **The Deck already has a Steam Controller identity** — it presents as VID 0x28DE PID 0x1205, not as a generic HID device.

2. **The hid-steam driver handles the heavy lifting** — it parses vendor HID reports and creates virtual Xbox 360 pad.

3. **BLE peripheral mode is supported** — the Qualcomm QCA adapter supports advertising, which is critical for our GATT server.

4. **No firmware files in the Steam installation** — firmware is managed separately by the system updater.

5. **The vendor HID interface (hidraw3) is the key** — this is where raw Steam Controller communication happens.
