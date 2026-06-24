# Research: Raw L2CAP ATT Server Viability — CONFIRMED

## Date: 2026-06-24

## Viability Test Results

| Test | Result |
|------|--------|
| Python 3.13 `socket.bind()` with `sockaddr_l2` | FAIL — Python 3.13 doesn't support BLE address types |
| `ctypes.bind()` with raw `sockaddr_l2` | **PASS** — Kernel accepts CID 4 + BDADDR_LE_RANDOM |
| `listen()` on raw L2CAP socket | **PASS** |
| Python `BDADDR_LE_RANDOM` constant | NOT AVAILABLE — must hardcode `0x02` |

## Socket Setup (Confirmed Working)

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
```

## Architecture

```
┌──────────────────────────────────────────────────────┐
│                   BLE Connection                      │
├──────────────────────┬───────────────────────────────┤
│  L2CAP CID 6 (SMP)  │  L2CAP CID 4 (ATT)           │
│  ┌────────────────┐  │  ┌──────────────────────────┐ │
│  │ Kernel SMP     │  │  │ Our Custom ATT Server    │ │
│  │ (automatic)    │  │  │ (raw L2CAP socket)       │ │
│  │ Just Works     │  │  │ GATT DB: HID+Battery+DIS │ │
│  └────────────────┘  │  └──────────────────────────┘ │
├──────────────────────┴───────────────────────────────┤
│  BlueZ advertising (LEAdvertisingManager1)           │
└──────────────────────────────────────────────────────┘
```

## ATT Opcodes to Implement (13 total)

| Opcode | Name | Purpose |
|--------|------|---------|
| 0x01 | Error Response | Error handling |
| 0x02/0x03 | Exchange MTU | MTU negotiation |
| 0x04/0x05 | Find Information | Descriptor discovery |
| 0x08/0x09 | Read By Type | Characteristic discovery |
| 0x0A/0x0B | Read Request | Read attribute |
| 0x0C/0x0D | Read Blob | Long read (Report Map) |
| 0x10/0x11 | Read By Group Type | Service discovery |
| 0x12/0x13 | Write Request | CCCD enable, etc. |
| 0x1B | Handle Value Notification | Input reports to host |
| 0x52 | Write Command | HID Control Point |

## GATT Database (~34 attributes)

- GAP Service (0x1800): Device Name, Appearance
- GATT Service (0x1801): Service Changed
- HID Service (0x1812): HID Info, Report Map, Control Point, Report (in+out)
- Battery Service (0x180F): Battery Level
- Device Info Service (0x180A): PnP ID, Manufacturer, Model

## Dependencies

- `bluetoothd` running (for SMP pairing on CID 6)
- Root or `CAP_NET_RAW` (for raw L2CAP socket)
- `config_bt.py` applied (bredr off + static-addr)
