# Steam Client Analysis

## Installation Location

```
~/.steam/steam/
├── steamclient.so          (47.7 MB)
├── config/
│   └── chord_triton.vdf
├── firmware/
│   ├── IBEX_FW_6941BF08.fw
│   ├── PROTEUS_FW_6941BF87.fw
│   └── hardwareupdater.cfg
├── resource/
│   └── blefirmwareupdate.png
└── ...
```

## Controller Configuration

### chord_triton.vdf

```
"controller_neptune"
{
    "name"    "Steam Controller"
    "type"    "controller_neptune"
    ...
}
```

Key finding: The `controller_type` is `controller_neptune` — this is the same type used for the Steam Deck controller. The SC2 (Triton) uses the same configuration.

### Controller Type Enumeration

From `steamclient.so`, the following controller types are enumerated:
- `controller_steamcontroller_gordon` — Original Steam Controller
- `controller_neptune` — Steam Deck / SC2
- `controller_triton` — SC2 (alternate name)
- `controller_ps4` — PlayStation 4
- `controller_xbox360` — Xbox 360
- `controller_xboxone` — Xbox One
- `controller_switch` — Nintendo Switch
- And others...

The SC2 is treated as a `controller_neptune` by Steam Client.

## Firmware Files

### IBEX_FW_6941BF08.fw (367 KB)

- **Target**: Triton/SC2 BLE controller
- **Timestamp**: 0x6941BF08 (Unix timestamp)
- **Size**: 367 KB
- **Purpose**: BLE firmware update for the SC2

### PROTEUS_FW_6941BF87.fw (185 KB)

- **Target**: Puck (USB dongle)
- **Timestamp**: 0x6941BF87 (Unix timestamp)
- **Size**: 185 KB
- **Purpose**: Firmware update for the USB dongle

### hardwareupdater.cfg

```
TRITON_FW_TS:6941BF08
PROTEUS_FW_TS:6941BF87
```

Firmware timestamps used for version checking during update.

## steamclient.so Analysis (47.7 MB)

### Key Functions/Strings Found

| String | Purpose |
|--------|---------|
| `toggle_lizard` | Toggle lizard mode (basic keyboard/mouse emulation) |
| `is_mode_switching_supported` | Check if device supports mode switching |
| `CExitLizardModeWorkItem` | Work item to exit lizard mode |
| `device_send_feature_report` | Send HID feature report to device |
| `device_get_serial_number_string` | Get device serial number |
| `toggle_lizard` | Lizard mode toggle command |

### Subsystems Identified

1. **BT Manager**: Full Bluetooth management (pairing, connection, HID)
2. **HID I/O Thread**: Reads/writes HID reports via BLE or USB
3. **Triton Pairing System**: Handles SC2 pairing and bonding
4. **Firmware Update**: BLE and USB firmware update system
5. **Steam Input**: Controller input processing and remapping

### BLE PIDs / GATT UUIDs

**Not found in readable strings** — BLE PIDs, GATT UUIDs, and HID service UUIDs are compiled as hex constants in the binary, not as readable strings. This is expected for performance and obfuscation.

## BLE Firmware Update

- `blefirmwareupdate.png` — UI asset for BLE firmware update progress
- Localization files contain strings for BLE firmware update dialogs
- The update process is handled by the BT Manager subsystem

## udev Rules

### 60-steam-input.rules

```
# Valve Steam Controller
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="28de", MODE="0660", TAG+="uaccess"
KERNEL=="hidraw*", ATTRS{../idVendor}=="28de", RUN+="/bin/sh -c 'echo 1 > /sys$devpath/device/power/wakeup'"
```

- Valve VID 0x28DE is allowed for hidraw access
- udev wakeup is enabled for power management
- This allows the `deck` user to access the vendor HID interface

## Implications for SC2 Spoof

### What Steam Client Expects

1. **BLE advertisement** with SC2-specific service UUID
2. **GATT service** matching SC2 profile
3. **Input reports** in SC2 format (report 0x45)
4. **Feature reports** for mode switching
5. **Device Information** service with correct VID/PID

### What We Must Provide

1. **Service UUID**: `100F6C32-1735-4313-B402-38567131E5F3`
2. **Input Characteristics**: Notify-enabled, report 0x45 format
3. **Report Characteristic**: For feature report responses
4. **Device Info**: VID 0x28DE, PID 0x1303, "Valve Software"
5. **Lizard Mode**: Start in lizard mode, switch on Steam Client request

### What Steam Client Does NOT Expect

- HID report descriptors (handled internally by Steam)
- Standard HID service UUID (uses Valve custom UUID)
- Standard USB HID protocol (custom BLE protocol)
- Any specific MAC address (pairing-based)

## Testing with Steam Client

To test the SC2 spoof with Steam Client:

1. Start GATT server on Deck
2. Open Steam on host PC
3. Go to Settings → Controller
4. The device should appear as "Steam Controller 2026"
5. Input should be recognized in the controller test

If the device does not appear:
- Check BLE advertisement is active
- Verify GATT service is registered
- Check Steam Client logs for connection attempts
- Verify input report format matches SC2 specification
