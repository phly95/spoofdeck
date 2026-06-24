# ATT Server Implementation Guide

## Overview

The raw L2CAP ATT server handles all Attribute Protocol (ATT) PDU exchange on CID 4. It bypasses BlueZ's built-in GATT server (which has an address binding bug on SteamOS).

## Architecture

```
Host sends ATT PDU → Kernel L2CAP → Our raw socket (CID 4) → _handle_pdu() → response
```

## ATT Opcodes Implemented

| Opcode | Name | Status | Handler |
|--------|------|--------|---------|
| 0x01 | Error Response | ✅ | `_send_error()` |
| 0x02/0x03 | Exchange MTU | ✅ | `_handle_mtu_req()` |
| 0x04/0x05 | Find Information | ✅ | `_handle_find_info()` |
| 0x08/0x09 | Read By Type | ✅ | `_handle_read_by_type()` |
| 0x0A/0x0B | Read Request | ✅ | `_handle_read()` |
| 0x0C/0x0D | Read Blob | ✅ | `_handle_read_blob()` |
| 0x10/0x11 | Read By Group Type | ✅ | `_handle_read_by_group_type()` |
| 0x12/0x13 | Write Request | ✅ | `_handle_write()` |
| 0x1B | Handle Value Notification | ✅ | `send_notification()` |
| 0x1D/0x1E | Handle Value Indication | ❌ | Not implemented |
| 0x52 | Write Command | ✅ | `_handle_write_cmd()` |

## GATT Database Structure

### Handle Layout (74 attributes, 6 services)

| Handle | UUID | Description |
|--------|------|-------------|
| 0x0001 | 0x2800 | GAP Service Declaration |
| 0x0002 | 0x2803 | Device Name Characteristic |
| 0x0003 | 0x2A00 | Device Name Value |
| 0x0004 | 0x2803 | Appearance Characteristic |
| 0x0005 | 0x2A01 | Appearance Value |
| 0x0006 | 0x2800 | GATT Service Declaration |
| 0x0007 | 0x2803 | Service Changed Characteristic |
| 0x0008 | 0x2A05 | Service Changed Value |
| 0x0009 | 0x2902 | Service Changed CCCD |
| 0x000A | 0x2800 | HID Service Declaration |
| 0x000B | 0x2803 | HID Information Characteristic |
| 0x000C | 0x2A4A | HID Information Value |
| 0x000D | 0x2803 | Report Map Characteristic |
| 0x000E | 0x2A4B | Report Map Value (77 bytes / standard 186 bytes layout) |
| 0x000F | 0x2803 | HID Control Point Characteristic |
| 0x0010 | 0x2A4C | HID Control Point Value |
| 0x0011 | 0x2803 | Report (Gamepad Input) Characteristic |
| 0x0012 | 0x2A4D | Report (Gamepad Input) Value (12 bytes) |
| 0x0013 | 0x2908 | Report Reference (Gamepad Input, ID=1) |
| 0x0014 | 0x2902 | Report (Gamepad Input) CCCD |
| 0x0015 | 0x2803 | Report (Output) Characteristic |
| 0x0016 | 0x2A4D | Report (Output) Value (1 byte) |
| 0x0017 | 0x2908 | Report Reference (Output, ID=2) |
| 0x0018 | 0x2803 | Report (Mouse Input) Characteristic |
| 0x0019 | 0x2A4D | Report (Mouse Input) Value (4 bytes) |
| 0x001A | 0x2908 | Report Reference (Mouse Input, ID=3) |
| 0x001B | 0x2902 | Report (Mouse Input) CCCD |
| 0x001C | 0x2803 | Report (Keyboard Input) Characteristic |
| 0x001D | 0x2A4D | Report (Keyboard Input) Value (8 bytes) |
| 0x001E | 0x2908 | Report Reference (Keyboard Input, ID=4) |
| 0x001F | 0x2902 | Report (Keyboard Input) CCCD |
| 0x0020 | 0x2803 | Feature Report 0x00 Characteristic |
| 0x0021 | 0x2A4D | Feature Report 0x00 Value (64 bytes) |
| 0x0022 | 0x2908 | Report Reference (Feature, ID=0x00) |
| 0x0023 | 0x2803 | Feature Report 0x01 Characteristic |
| 0x0024 | 0x2A4D | Feature Report 0x01 Value (64 bytes) |
| 0x0025 | 0x2908 | Report Reference (Feature, ID=0x01) |
| 0x0026 | 0x2803 | Feature Report 0x85 Characteristic |
| 0x0027 | 0x2A4D | Feature Report 0x85 Value (64 bytes) |
| 0x0028 | 0x2908 | Report Reference (Feature, ID=0x85) |
| 0x0029 | 0x2803 | Feature Report 0x86 Characteristic |
| 0x002A | 0x2A4D | Feature Report 0x86 Value (64 bytes) |
| 0x002B | 0x2908 | Report Reference (Feature, ID=0x86) |
| 0x002C | 0x2803 | Feature Report 0x87 Characteristic |
| 0x002D | 0x2A4D | Feature Report 0x87 Value (64 bytes) |
| 0x002E | 0x2908 | Report Reference (Feature, ID=0x87) |
| 0x002F | 0x2800 | Valve Custom SC2 HID Service Declaration |
| 0x0030 | 0x2803 | SC2 Input CH1 Characteristic (Notify) |
| 0x0031 | 0x2A4D | SC2 Input CH1 Value (45 bytes) |
| 0x0032 | 0x2902 | SC2 Input CH1 CCCD |
| 0x0033 | 0x2803 | SC2 Input CH2 Characteristic (Notify) |
| 0x0034 | 0x2A4D | SC2 Input CH2 Value (47 bytes) |
| 0x0035 | 0x2902 | SC2 Input CH2 CCCD |
| 0x0036 | 0x2803 | SC2 Report CH Characteristic (Write) |
| 0x0037 | 0x2A4D | SC2 Report CH Value (64 bytes) |
| 0x0038 | 0x2800 | Battery Service Declaration |
| 0x0039 | 0x2803 | Battery Level Characteristic |
| 0x003A | 0x2A19 | Battery Level Value (1 byte) |
| 0x003B | 0x2902 | Battery Level CCCD |
| 0x003C | 0x2800 | Device Info Service Declaration |
| 0x003D | 0x2803 | Manufacturer Name Characteristic |
| 0x003E | 0x2A29 | Manufacturer Name Value |
| 0x003F | 0x2803 | Model Number Characteristic |
| 0x0040 | 0x2A24 | Model Number Value |
| 0x0041 | 0x2803 | Serial Number Characteristic |
| 0x0042 | 0x2A25 | Serial Number Value |
| 0x0043 | 0x2803 | Firmware Revision Characteristic |
| 0x0044 | 0x2A26 | Firmware Revision Value |
| 0x0045 | 0x2803 | Hardware Revision Characteristic |
| 0x0046 | 0x2A27 | Hardware Revision Value |
| 0x0047 | 0x2803 | Software Revision Characteristic |
| 0x0048 | 0x2A28 | Software Revision Value |
| 0x0049 | 0x2803 | PnP ID Characteristic |
| 0x004A | 0x2A50 | PnP ID Value (7 bytes, Source=0x02, VID=0x28DE, PID=0x1303) |

### Host Discovery Sequence

1. `Exchange MTU Request` → `Exchange MTU Response`
2. `Read By Group Type` (UUID 0x2800) → 5 services found
3. `Read By Type` (UUID 0x2803) → characteristics in each service
4. `Find Information` → descriptors (especially CCCD 0x2902)
5. `Write` to CCCD → enable notifications
6. `Read` HID Information, Report Map, PnP ID, Battery Level
7. Start receiving notifications

### CCCD (Client Characteristic Configuration Descriptor)

UUID: `0x2902`

- `0x0000` = Notifications disabled
- `0x0001` = Notifications enabled
- `0x0002` = Indications enabled

When the host writes `[0x01, 0x00]` to a CCCD, the server adds that handle's parent characteristic to `_notification_handles`. Subsequent `send_notification()` calls will send ATT Handle Value Notifications.

### Report Map

The HID Report Map descriptor defines the input report format. For a gamepad:
- Report ID 1 (Input): 16 buttons (2 bytes), 4 axes X/Y/Rx/Ry (4 × 16-bit signed), 2 triggers Z/Rz (2 × 8-bit unsigned) = 12 bytes
- Report ID 2 (Output): 1 byte vendor data

The Report ID 2 (Output) exists solely to make BlueZ's hog-ll driver set `num_reports > 1`, which causes it to expect the Report ID as the first byte of ATT notifications.

### Input Report Format (12 bytes notification)

ATT notifications send raw HID report data **without** Report ID prefix. BlueZ's hog-ll driver prepends the Report ID via `bt_uhid_input()` using the `id` from the Report Reference descriptor.
```
Bytes 0-1:   16 buttons (1 bit each, LE)
Bytes 2-3:   X axis (signed 16-bit LE)
Bytes 4-5:   Y axis (signed 16-bit LE)
Bytes 6-7:   Rx axis (signed 16-bit LE)
Bytes 8-9:   Ry axis (signed 16-bit LE)
Byte 10:     Z trigger (unsigned 8-bit)
Byte 11:     Rz trigger (unsigned 8-bit)
```

## Neptune HID Input Source

### Why hidraw, Not evdev

The `hid-steam` kernel driver only generates evdev events when `gamepad_mode` is true (requires Steam button long-press or Steam running). Without Steam, the controller is in **lizard mode** where buttons map to keyboard scancodes — evdev events exist but contain no real gamepad data. Solution: read directly from `/dev/hidraw3`.

### Finding the Gamepad hidraw

The Neptune controller (VID=0x28DE, PID=0x1205) exposes 3 hidraw interfaces. The gamepad one is identified by `HID_PHYS` containing `input2`:
- `/dev/hidraw3` — USB interface 2 (gamepad: sticks, buttons, triggers)
- Other interfaces — trackpads, IMU, etc.

### Neptune HID Report Format (type 0x09, 64 bytes)

The controller sends 64-byte reports with NO Report ID prefix (HID descriptor has no Report ID). Report type 0x09 = `ID_CONTROLLER_DECK_STATE`.

| Offset | Field |
|--------|-------|
| 0-3 | Header: `01 00 09 40` |
| 4-7 | Frame counter (u32 LE) |
| 8 | Buttons: A/X/B/Y/L1/R1/L2/R2 |
| 9 | Buttons: L5/Menu/Steam/Options/Down/Left/Right/Up |
| 10 | Buttons: L3/RPadTouch/LPadTouch/RPadPress/LPadPress/R5 |
| 11 | Buttons: R3 |
| 13 | Buttons: RStickTouch/LStickTouch/R4/L4 |
| 14 | Buttons: QuickAccess |
| 16-23 | Trackpads: LPadXY, RPadXY (i16 LE) |
| 24-35 | IMU: accelXYZ, gyroXYZ (i16 LE) |
| 44-47 | Triggers: L/R (u16 LE, 0..32767) |
| 48-55 | Sticks: LX/LY/RX/RY (i16 LE, -32767..32767) |
| 56-63 | Force: pad/stick capacitive touch |

### Button Mapping (Neptune → SC2)

| Neptune | SC2 bitmask |
|---------|-------------|
| byte8 bit0 (A) | 0x0001 (BTN_SOUTH) |
| byte8 bit2 (B) | 0x0002 (BTN_EAST) |
| byte8 bit1 (X) | 0x0004 (BTN_NORTH) |
| byte8 bit3 (Y) | 0x0008 (BTN_WEST) |
| byte8 bit4 (L1) | 0x0010 (BTN_TL) |
| byte8 bit5 (R1) | 0x0020 (BTN_TR) |
| byte9 bit1 (Menu) | 0x0040 (BTN_SELECT) |
| byte9 bit3 (Options) | 0x0080 (BTN_START) |
| byte9 bit2 (Steam) | 0x0100 (BTN_MODE) |
| byte10 bit1 (L3) | 0x0200 (BTN_THUMBL) |
| byte11 bit5 (R3) | 0x0400 (BTN_THUMBR) |
| byte9 bit7 (Up) | 0x0800 (DPAD_UP) |
| byte9 bit4 (Down) | 0x1000 (DPAD_DOWN) |
| byte9 bit5 (Left) | 0x2000 (DPAD_LEFT) |
| byte9 bit6 (Right) | 0x4000 (DPAD_RIGHT) |

Sticks: direct copy (same format). Triggers: `>> 7` to scale from 16-bit to 8-bit.

### Lizard Mode Control

Lizard mode re-enables every ~2 seconds. Must periodically re-send disable commands via `os.write()`:
1. `[0x01, 0x00, 0x81] + [0]*61` — ClearDigitalMappings
2. `[0x01, 0x00, 0x87, 0x03, 0x08, 0x07, 0x00] + [0]*57` — disable left trackpad mouse
3. `[0x01, 0x00, 0x87, 0x03, 0x15, 0x00, 0x00] + [0]*57` — disable smooth mouse

**Note**: `ioctl(fd, HIDIOCSFEATURE, ...)` returns EINVAL on hidraw. Use `os.write()` for output reports.

### Reference

[InputPlumber](https://github.com/ShadowBlip/InputPlumber) — Neptune protocol documentation

### Long Read (Read Blob)

Report Map is 77 bytes, exceeding the default MTU of 23. The host sends:
1. `Read Blob Request` with offset 0
2. Server responds with data starting at offset 0
3. Host sends `Read Blob Request` with offset = previous response length
4. Repeat until all data is read

## Socket Setup

```python
import socket, struct, ctypes, ctypes.util

AF_BLUETOOTH = 31
BTPROTO_L2CAP = 0
BT_ATT_CID = 4
BDADDR_LE_RANDOM = 0x02

sk = socket.socket(AF_BLUETOOTH, socket.SOCK_SEQPACKET, BTPROTO_L2CAP)
addr_bytes = bytes.fromhex('C2123456789A')[::-1]
sockaddr = struct.pack('<HH6sHB', AF_BLUETOOTH, 0, addr_bytes, BT_ATT_CID, BDADDR_LE_RANDOM)
libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
libc.bind(sk.fileno(), ctypes.create_string_buffer(sockaddr), len(sockaddr))
sk.listen(1)
conn, addr = sk.accept()
```

## Sending Notifications

```python
def send_notification(self, handle, value):
    """Send ATT Handle Value Notification."""
    if handle not in self._notification_handles:
        return  # Notifications not enabled
    pdu = struct.pack('<BH', 0x1B, handle) + value
    self.conn.send(pdu)
```
