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
| 0x02/0x03 | Exchange MTU | ✅ | `_handle_mtu_req()` — server MTU=517, negotiated=min(client, 517) |
| 0x04/0x05 | Find Information | ✅ | `_handle_find_info()` |
| 0x08/0x09 | Read By Type | ✅ | `_handle_read_by_type()` |
| 0x0A/0x0B | Read Request | ✅ | `_handle_read()` |
| 0x0C/0x0D | Read Blob | ✅ | `_handle_read_blob()` |
| 0x10/0x11 | Read By Group Type | ✅ | `_handle_read_by_group_type()` |
| 0x12/0x13 | Write Request | ✅ | `_handle_write()` |
| 0x1B | Handle Value Notification | ✅ | `send_notification()` |
| 0x1D | Handle Value Indication | — | Not sent (but could be added) |
| 0x1E | Handle Value Confirmation | ✅ | `_handle_pdu()` — no-op (client confirms our indication) |
| 0x52 | Write Command | ✅ | `_handle_write_cmd()` |

## GATT Database Structure

### Handle Layout (87 attributes, 6 services)

| Handle | UUID | Description |
|--------|------|-------------|
| 0x0001 | 0x2800 (Primary Service) | GAP Service Declaration |
| 0x0002 | 0x2803 (Characteristic) | Characteristic Decl (val=0x0003) |
| 0x0003 | 0x2A00 (Device Name) | Device Name Value |
| 0x0004 | 0x2803 (Characteristic) | Characteristic Decl (val=0x0005) |
| 0x0005 | 0x2A01 (Appearance) | Appearance Value |
| 0x0006 | 0x2800 (Primary Service) | GATT Service Declaration |
| 0x0007 | 0x2803 (Characteristic) | Characteristic Decl (val=0x0008) |
| 0x0008 | 0x2A05 (Service Changed) | Service Changed Value |
| 0x0009 | 0x2902 (CCCD) | CCCD |
| 0x000A | 0x2800 (Primary Service) | HID Service Declaration |
| 0x000B | 0x2803 (Characteristic) | Characteristic Decl (val=0x000C) |
| 0x000C | 0x2A4A (HID Information) | HID Information Value |
| 0x000D | 0x2803 (Characteristic) | Characteristic Decl (val=0x000E) |
| 0x000E | 0x2A4E (Protocol Mode) | Protocol Mode Value |
| 0x000F | 0x2803 (Characteristic) | Characteristic Decl (val=0x0010) |
| 0x0010 | 0x2A4B (Report Map) | Report Map Value (282 bytes) |
| 0x0011 | 0x2803 (Characteristic) | Characteristic Decl (val=0x0012) |
| 0x0012 | 0x2A4C (HID Control Point) | HID Control Point Value |
| 0x0013 | 0x2803 (Characteristic) | Characteristic Decl (val=0x0014) |
| 0x0014 | 0x2A4D (Report) | Report Value (0x01, Input, 12 bytes) |
| 0x0015 | 0x2908 (Report Reference) | Report Reference (ID=0x01, Input) |
| 0x0016 | 0x2902 (CCCD) | CCCD |
| 0x0017 | 0x2803 (Characteristic) | Characteristic Decl (val=0x0018) |
| 0x0018 | 0x2A4D (Report) | Report Value (0x02, Output, 1 bytes) |
| 0x0019 | 0x2908 (Report Reference) | Report Reference (ID=0x02, Output) |
| 0x001A | 0x2803 (Characteristic) | Characteristic Decl (val=0x001B) |
| 0x001B | 0x2A4D (Report) | Report Value (0x80, Output, 10 bytes) |
| 0x001C | 0x2908 (Report Reference) | Report Reference (ID=0x80, Output) |
| 0x001D | 0x2803 (Characteristic) | Characteristic Decl (val=0x001E) |
| 0x001E | 0x2A4D (Report) | Report Value (0x03, Input, 4 bytes) |
| 0x001F | 0x2908 (Report Reference) | Report Reference (ID=0x03, Input) |
| 0x0020 | 0x2902 (CCCD) | CCCD |
| 0x0021 | 0x2803 (Characteristic) | Characteristic Decl (val=0x0022) |
| 0x0022 | 0x2A4D (Report) | Report Value (0x04, Input, 8 bytes) |
| 0x0023 | 0x2908 (Report Reference) | Report Reference (ID=0x04, Input) |
| 0x0024 | 0x2902 (CCCD) | CCCD |
| 0x0025 | 0x2803 (Characteristic) | Characteristic Decl (val=0x0026) |
| 0x0026 | 0x2A4D (Report) | Report Value (0x00, Feature, 64 bytes) |
| 0x0027 | 0x2908 (Report Reference) | Report Reference (ID=0x00, Feature) |
| 0x0028 | 0x2803 (Characteristic) | Characteristic Decl (val=0x0029) |
| 0x0029 | 0x2A4D (Report) | Report Value (0x01, Feature, 64 bytes) |
| 0x002A | 0x2908 (Report Reference) | Report Reference (ID=0x01, Feature) |
| 0x002B | 0x2803 (Characteristic) | Characteristic Decl (val=0x002C) |
| 0x002C | 0x2A4D (Report) | Report Value (0x85, Feature, 64 bytes) |
| 0x002D | 0x2908 (Report Reference) | Report Reference (ID=0x85, Feature) |
| 0x002E | 0x2803 (Characteristic) | Characteristic Decl (val=0x002F) |
| 0x002F | 0x2A4D (Report) | Report Value (0x86, Feature, 64 bytes) |
| 0x0030 | 0x2908 (Report Reference) | Report Reference (ID=0x86, Feature) |
| 0x0031 | 0x2803 (Characteristic) | Characteristic Decl (val=0x0032) |
| 0x0032 | 0x2A4D (Report) | Report Value (0x87, Feature, 64 bytes) |
| 0x0033 | 0x2908 (Report Reference) | Report Reference (ID=0x87, Feature) |
| 0x0034 | 0x2803 (Characteristic) | Characteristic Decl (val=0x0035) |
| 0x0035 | 0x2A4D (Report) | Report Value (0x45, Input, 45 bytes) |
| 0x0036 | 0x2908 (Report Reference) | Report Reference (ID=0x45, Input) |
| 0x0037 | 0x2902 (CCCD) | CCCD |
| 0x0038 | 0x2803 (Characteristic) | Characteristic Decl (val=0x0039) |
| 0x0039 | 0x2A4D (Report) | Report Value (0x47, Input, 47 bytes) |
| 0x003A | 0x2908 (Report Reference) | Report Reference (ID=0x47, Input) |
| 0x003B | 0x2902 (CCCD) | CCCD |
| 0x003C | 0x2800 (Primary Service) | Valve Custom SC2 HID Service Declaration |
| 0x003D | 0x2803 (Characteristic) | Characteristic Decl (val=0x003E) |
| 0x003E | 100f6c7a-1735-4313-b402-38567131e5f3 | SC2 Input CH1 Value (45 bytes) |
| 0x003F | 0x2902 (CCCD) | CCCD |
| 0x0040 | 0x2803 (Characteristic) | Characteristic Decl (val=0x0041) |
| 0x0041 | 100f6c7c-1735-4313-b402-38567131e5f3 | SC2 Input CH2 Value (47 bytes) |
| 0x0042 | 0x2902 (CCCD) | CCCD |
| 0x0043 | 0x2803 (Characteristic) | Characteristic Decl (val=0x0044) |
| 0x0044 | 100f6c34-1735-4313-b402-38567131e5f3 | SC2 Report CH Value (64 bytes) |
| 0x0045 | 0x2800 (Primary Service) | Battery Service Declaration |
| 0x0046 | 0x2803 (Characteristic) | Characteristic Decl (val=0x0047) |
| 0x0047 | 0x2A19 (Battery Level) | Battery Level Value |
| 0x0048 | 0x2902 (CCCD) | CCCD |
| 0x0049 | 0x2800 (Primary Service) | Device Info Service Declaration |
| 0x004A | 0x2803 (Characteristic) | Characteristic Decl (val=0x004B) |
| 0x004B | 0x2A29 (Manufacturer Name) | Manufacturer Name Value |
| 0x004C | 0x2803 (Characteristic) | Characteristic Decl (val=0x004D) |
| 0x004D | 0x2A24 (Model Number) | Model Number Value |
| 0x004E | 0x2803 (Characteristic) | Characteristic Decl (val=0x004F) |
| 0x004F | 0x2A25 (Serial Number) | Serial Number Value |
| 0x0050 | 0x2803 (Characteristic) | Characteristic Decl (val=0x0051) |
| 0x0051 | 0x2A26 (Firmware Revision) | Firmware Revision Value |
| 0x0052 | 0x2803 (Characteristic) | Characteristic Decl (val=0x0053) |
| 0x0053 | 0x2A27 (Hardware Revision) | Hardware Revision Value |
| 0x0054 | 0x2803 (Characteristic) | Characteristic Decl (val=0x0055) |
| 0x0055 | 0x2A28 (Software Revision) | Software Revision Value |
| 0x0056 | 0x2803 (Characteristic) | Characteristic Decl (val=0x0057) |
| 0x0057 | 0x2A50 (PnP ID) | PnP ID Value (7 bytes: Source=0x02, VID=0x28DE, PID=0x1303) |

### Host Discovery Sequence

1. `Exchange MTU Request` → `Exchange MTU Response`
2. `Read By Group Type` (UUID 0x2800) → 6 services found (GAP, GATT, HID, Valve Custom, Battery, Device Info)
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

#### CCCD Write Processing

When a Write Request (0x12) arrives on a CCCD handle (`att_server.py:501-549`):

1. Server checks if the attribute UUID is `0x2902`
2. Calls `_find_cccd_value_handle(cccd_handle)` — walks backwards from the CCCD handle searching for a Characteristic Declaration (UUID `0x2803`), then extracts the value handle from its value field (`att_server.py:464-475`)
3. If the CCCD value has bit 0 set (`ccc_value & 0x0001`), adds the value handle to `_notification_handles`
4. If bit 0 is clear, removes the value handle from `_notification_handles`
5. Calls `_on_cccd_enabled(value_handle)` callback so the application layer can react (e.g., send pre-fill notifications)

**Known limitation**: Write Command (0x52) does not process CCCD writes. Only Write Request (0x12) triggers CCCD logic. This means a host that uses Write Command for CCCD writes will not enable notifications. In practice, BlueZ uses Write Request for CCCDs, so this is not a real-world issue.

#### CCCD Persistence Across Reconnections

CCCD state is persisted per-client in `_client_cccds` (keyed by client address). On reconnection (`att_server.py:140-148`):

1. Server looks up the client address in `_client_cccds`
2. Restores `_notification_handles` from the stored set
3. Calls `_on_cccd_enabled` for each restored handle, so the application can resume sending notifications immediately

This is important because BLE connections may use different addresses across sessions. The raw L2CAP socket uses IP-based `conn_addr`, which is stable for a given host.

#### CCCD Timing Fix

When `_on_cccd_enabled` fires for the gamepad handle (Report ID 1, 12 bytes) or the SC2 CHR_REPORT handle (Report ID 0x45, 45 bytes), `main_l2cap.py:767-779` immediately sends a zero-notification to pre-fill the UHID queue:

```python
# CCCD TIMING FIX: Send initial zero notifications to pre-fill the UHID queue.
# CGetControllerInfoWorkItem::RunFunc calls SDL_hid_read_timeout 51x at 100ms.
# If no data is available, it stalls the entire init chain (gate at [esi+0x17c]
# is never set, blocking haptics/commands). Sending zero reports immediately
# when the CCCD is enabled ensures data is available on the first read.
if handle == self._report_handle and self.att_server:
    zero_gamepad = b'\x00' * 12
    self.att_server.send_notification(self._report_handle, zero_gamepad)
if handle == self._sc2_hid_handle and self.att_server:
    zero_sc2 = b'\x00' * 45
    self.att_server.send_notification(self._sc2_hid_handle, zero_sc2)
```

Without this fix, Steam-generated haptics (trackpad clicks, UI feedback) don't work because `CGetControllerInfoWorkItem` stalls before the haptic gate is set. In-game rumble still works because `SDL_RumbleJoystick` uses `SDL_hid_write` (host → device) which doesn't depend on the init chain completing.

#### Notification Capping

Notifications are capped to MTU - 3 bytes per ATT spec (opcode `0x1B` = 1 byte + handle = 2 bytes overhead). With the default negotiated MTU of 517, the effective maximum notification payload is 514 bytes (`att_server.py:641-642`).

#### Notification Drops

If `send_notification()` is called for a handle not in `_notification_handles` (no CCCD enabled), the notification is silently dropped and counted in `_diag_notif_dropped`. The first drop and every 200th subsequent drop per handle are logged. This is useful for diagnosing subscription issues.

## Threading Model

The system runs two concurrent threads:

```
┌──────────────────────┐     ┌──────────────────────────┐
│   GLib Main Loop     │     │   ATT Server Thread       │
│   (D-Bus callbacks)  │     │   (att_server.py daemon)  │
│                      │     │                            │
│  _on_input_report()  │────▶│  send_notification()       │
│  _on_haptic_write()  │     │  _handle_write()           │
│  _on_cccd_enabled()  │◀────│  _handle_mtu_req()         │
└──────────────────────┘     └──────────────────────────┘
```

### Shared Mutable State

These fields are accessed from both threads without locks:

| Field | Write Thread | Read Thread | Risk |
|-------|-------------|-------------|------|
| `_notification_handles` | ATT (CCCD write) | GLib (send_notification) | Notification sent/dropped based on stale set |
| `mtu` | ATT (MTU exchange) | GLib (send_notification capping) | Notification may be capped to wrong MTU |
| `steam_input_mode` | ATT (mode switch) or GLib (CCCD auto-switch) | GLib (input report routing) | Report routed to wrong mode |
| `_pending_fr_response` | ATT (SC2 command handler) | GLib (FR read handler) | Response lost or stale |
| `conn` | ATT accept/cleanup | GLib (connected property) | Racy check, but safe due to exception handling |

**Why this works in practice**: CPython's GIL prevents memory corruption on shared objects. Set mutations (`add`/`discard`) and dict assignments are atomic at the bytecode level. The worst case is a logical race (stale read), not a crash. Exception handling in `_send()` (`att_server.py:612-621`) catches send errors on disconnected sockets.

**Why it could break**: Any refactoring that introduces multi-step operations on shared state (e.g., check-then-act on `_notification_handles`) will create TOCTOU races. If the project moves to a non-CPython runtime (PyPy, GraalPy), the GIL guarantees change.

### How CCCD Callbacks Bridge the Threads

When the ATT thread processes a CCCD write, it calls `_on_cccd_enabled(handle)` (`att_server.py:548-549`). This callback is defined in `main_l2cap.py:737-779` and runs on the ATT thread, but it accesses GLib state (`steam_input_mode`) and calls `send_notification()`. This is safe because:
1. The callback runs synchronously on the ATT thread before returning
2. `send_notification()` only reads shared state (`_notification_handles`, `mtu`) and sends on the socket
3. GLib main loop notifications are queued and processed on the next iteration

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

Report Map is 282 bytes, exceeding the default MTU of 23. The host sends:
1. `Read Blob Request` with offset 0
2. Server responds with data starting at offset 0
3. Host sends `Read Blob Request` with offset = previous response length
4. Repeat until all data is read

## Feature Report Protocol

The SC2 Feature Report system uses a **write-then-read** pattern that is not standard BLE HID. The host writes a command to a Feature Report, then reads the same Feature Report to get the response.

### The Flow

```
Host → Device:  ATT Write Request to FR 0x00 (command payload)
                Server stores response in _pending_fr_response[0x00]

Host ← Device:  ATT Write Response (ack)

Host → Device:  ATT Read Request to FR 0x00
                Server returns _pending_fr_response[0x00]

Host ← Device:  ATT Read Response (command response)
```

### Two Response Mechanisms

The server maintains two separate response sources for Feature Report reads:

1. **`_fr_response_queue`** (`main_l2cap.py:254`) — Pre-populated with zero-byte responses during `_prepopulate_responses()`. Used for the initial GATT discovery reads that BlueZ's hog-lib sends before any Steam commands arrive. These reads happen during connection setup and must return valid (but empty) data.

2. **`_pending_fr_response`** (`main_l2cap.py:214`) — Dict of actual command responses, keyed by report_id. Set by `_handle_sc2_command()` after processing a command. Checked first during `_on_feature_report_read()`; if empty, falls back to the queue.

The read handler priority: `_pending_fr_response` → `_fr_response_queue` → `b'\x00' * 64` (zero fallback).

### Lifecycle

```
Connection opens
  → _prepopulate_responses() fills _fr_response_queue with zeros
  → _pending_fr_response is cleared

Host discovers GATT (reads FR 0x00/0x01)
  → _on_feature_report_read() returns from queue (zeros)

Steam sends SC2 command (writes FR 0x00)
  → _handle_sc2_command() processes command
  → Stores response in _pending_fr_response[0x00]

Steam reads FR 0x00 for response
  → _on_feature_report_read() returns from _pending_fr_response
```

### Key Behavior Notes

- If Steam writes a new command before reading the previous response, the old response is overwritten
- If a read arrives before any write, the queue provides valid zeros (not an error)
- The `_pending_fr_response` dict is cleared on disconnect (`_on_att_connection`)
- Feature Report reads for report IDs other than 0x00/0x01 go through `_proxy_feature_read()` (Neptune proxy) if the hidraw fd is open

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
    # Cap to MTU - 3 per ATT spec (opcode + handle)
    capped = value[:self.mtu - 3] if len(value) > self.mtu - 3 else value
    pdu = struct.pack('<BH', 0x1B, handle) + capped
    self.conn.send(pdu)
```

**MTU constraints**: Read Responses are capped to MTU-1. Notifications are capped to MTU-3 (opcode + handle = 3 bytes overhead). With server MTU=517, the effective payload limits are 516 bytes for reads and 514 bytes for notifications.

---

## Firmware GATT Comparison (2026-06-30)

Detailed comparison with the real SC2 firmware's GATT registration (`FUN_0001d8d0`, extracted from Ghidra analysis of `IBEX_FW_6A3F2424.fw`).

### Firmware GATT Registration

The firmware uses Zephyr's `bt_gatt_pool` API to register GATT services:
- `bt_gatt_pool_init_service` — service declarations
- `bt_gatt_pool_register_chrc` — characteristics (UUID, properties, permissions)
- `bt_gatt_pool_register_descriptor` — descriptors (UUID, permissions)
- `bt_gatt_pool_register_ccc` — CCCD descriptors

Handle allocation is dynamic, using 20-byte attribute entries and 8-byte UUID pool entries.

### Service Comparison

| Service | Firmware | Our Server | Notes |
|---------|----------|------------|-------|
| GAP (0x1800) | Pre-registered by BLE stack | Explicitly registered | Redundant but harmless |
| GATT (0x1801) | Pre-registered by BLE stack | Explicitly registered | Redundant but harmless |
| HID (0x1812) | Explicitly registered | Registered | **Differences in characteristics** |
| Battery (0x180F) | **NOT in firmware** | Registered | Required by BlueZ HOGP |
| Device Info (0x180A) | **NOT in firmware** | Registered | Required by BlueZ HOGP |

### HID Characteristic Comparison

| Characteristic | Firmware | Our Server | Status |
|---------------|----------|------------|--------|
| Protocol Mode (0x2A4E) | Read+WriteNoResp (0x06) | Present at 0x000D/0x000E | OK |
| Report Input (0x2A4D) | Up to 6 instances, Read+Notify (0x12) | 3 instances (ID=1, 3, 4) | OK |
| Report Output (0x2A4D) | Up to 10 instances, Read+WriteNoResp+Write (0x0E) | ID=2 only | Partial |
| Feature Reports (0x2A4D) | In output group | IDs 0x00, 0x01, 0x85, 0x86, 0x87 (in Report Map) | OK |
| Custom CHR_REPORT (0x2A4D) | 0-1 instance, Read+WriteNoResp (0x0A) | IDs 0x45, 0x47 | OK |
| Boot KB Output (0x2A33) | Optional, Read+Notify (0x12) | MISSING | Skip (Valve-proprietary UUID) |
| Boot KB Input (0x2A22) | Optional, Read+Notify (0x12) | MISSING | Optional |
| Boot KB Output (0x2A32) | Optional, Read+WriteNoResp+Write (0x0E) | MISSING | Optional |
| Report Map (0x2A4B) | Read (0x02) | Read | OK |
| HID Information (0x2A4A) | Read (0x02) | Read | OK |
| HID Control Point (0x2A4C) | WriteNoResp (0x04) | WriteNoResp | OK |

### Key Differences

1. **Feature Reports in Report Map** — Feature Reports 0x00, 0x01, 0x85, 0x86, 0x87 are declared in the HID Report Map as Feature collections (Logical, Vendor Defined 0xFF00). This allows Steam's SC2 HIDAPI driver to discover them during Report Map parsing.

2. **Battery/Device Info** — The firmware does NOT register these in its GATT setup. However, BlueZ's HOGP driver requires them for `/dev/hidrawN` creation. These are extra in our server but necessary for BlueZ compatibility.

3. **Report Reference descriptor in Report characteristics** — The firmware registers 0x2908 (Report Reference) descriptors for each Report characteristic, matching our implementation.
