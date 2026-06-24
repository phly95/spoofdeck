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

### Handle Layout (34 attributes)

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
| 0x000E | 0x2A4B | Report Map Value (210 bytes) |
| 0x000F | 0x2803 | HID Control Point Characteristic |
| 0x0010 | 0x2A4C | HID Control Point Value |
| 0x0011 | 0x2803 | Report (Input) Characteristic |
| 0x0012 | 0x2A4D | Report (Input) Value |
| 0x0013 | 0x2908 | Report Reference (Input) |
| 0x0014 | 0x2902 | Report (Input) CCCD |
| 0x0015 | 0x2803 | Report (Output) Characteristic |
| 0x0016 | 0x2A4D | Report (Output) Value |
| 0x0017 | 0x2908 | Report Reference (Output) |
| 0x0018 | 0x2800 | Battery Service Declaration |
| 0x0019 | 0x2803 | Battery Level Characteristic |
| 0x001A | 0x2A19 | Battery Level Value |
| 0x001B | 0x2902 | Battery Level CCCD |
| 0x001C | 0x2800 | Device Info Service Declaration |
| 0x001D | 0x2803 | Manufacturer Name Characteristic |
| 0x001E | 0x2A29 | Manufacturer Name Value |
| 0x001F | 0x2803 | Model Number Characteristic |
| 0x0020 | 0x2A24 | Model Number Value |
| 0x0021 | 0x2803 | PnP ID Characteristic |
| 0x0022 | 0x2A50 | PnP ID Value |

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
- 16 buttons (2 bytes)
- 4 axes X/Y/Rx/Ry (4 × 16-bit signed)
- 2 triggers Z/Rz (2 × 8-bit unsigned)
- Total: 12 bytes per report

### Long Read (Read Blob)

Report Map is >200 bytes, exceeding the default MTU of 23. The host sends:
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
