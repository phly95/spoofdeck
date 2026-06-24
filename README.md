# Steam Deck → Steam Controller 2026 BLE Spoof

Make a Steam Deck present itself as a Steam Controller 2026 over Bluetooth Low Energy, enabling Steam Input integration without USB wired mode.

## Current Status

**Working (Raw L2CAP ATT Server)** — The Deck runs a raw L2CAP ATT server on CID 4, bypassing BlueZ's buggy GATT server. MTU exchange and service discovery succeed. The host sees `ServicesResolved: yes` with all 5 GATT services. Pairing works via auto-confirm Agent1. Next step: complete the full HOGP connection lifecycle (characteristic reads + CCCD enable → `/dev/hidraw`).

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    Steam Deck (Peripheral)                 │
│                                                          │
│  main_l2cap.py                                           │
│  ├─ GLib main loop (BlueZ D-Bus advertising)             │
│  ├─ Agent1 (auto-confirm pairing)                        │
│  └─ Raw L2CAP ATT server (CID 4, BDADDR_LE_RANDOM)      │
│     └─ Serves GATT database: HID + Battery + DIS         │
│     └─ Sends input reports as BLE notifications           │
│                                                          │
│  BlueZ handles: SMP (CID 6) + Advertising                │
│  Input: /dev/input/event10 (Xbox 360 pad)                │
└──────────────────────────────────────────────────────────┘
              │
              │ BLE (static random addr C2:12:34:56:78:9A)
              ▼
┌──────────────────────────────────────────────────────────┐
│                    Host PC (Central)                      │
│  BlueZ hog-ll driver → /dev/hidrawN → Steam Client       │
└──────────────────────────────────────────────────────────┘
```

## Key Findings

- **BLE PID**: 0x1303 (SC2 wireless), USB PID: 0x1302 (wired), Puck PID: 0x1304
- **GATT Service UUID**: `100F6C32-1735-4313-B402-38567131E5F3` (SC2 HID Service)
- **Input Report 0x45**: 45 bytes — buttons, triggers, sticks, trackpads, IMU
- **BT Adapter**: Qualcomm QCA, Bluetooth 5.3, supports central+peripheral
- **BlueZ Bug**: GATT listener bound to public addr, BLE on static random → raw L2CAP bypass needed
- **Raw L2CAP Viability**: Confirmed via ctypes bind() test on Deck

## Quick Start

### On the Deck:

```bash
# Stop old services
echo <DECK_PASSWORD> | sudo -S systemctl stop sc2-hogp bluetooth

# Apply BT config (bredr off + static addr)
echo <DECK_PASSWORD> | sudo -S python3 /tmp/config_bt.py

# Start the raw L2CAP ATT server
echo <DECK_PASSWORD> | sudo -S systemd-run --remain-after-exit \
  --unit=sc2-hogp \
  --property=WorkingDirectory=/tmp/sc2-spoof \
  python3 -u /tmp/sc2-spoof/src/main_l2cap.py \
  --name "Steam Controller 2026"

# Check logs
journalctl -u sc2-hogp -f
```

### On the Host:

```bash
# Scan and pair
bluetoothctl --timeout 10 scan on
bluetoothctl pair C2:12:34:56:78:9A

# Check hidraw
ls -la /dev/hidraw*
```

## Project Structure

```
steamdeck-sc2-spoof/
├── AGENTS.md                    # MUST READ for new agents
├── README.md                    # This file
├── docs/
│   ├── sc2-protocol.md          # SC2 BLE protocol details
│   ├── hardware-findings.md     # Deck hardware findings
│   ├── challenges.md            # Known challenges and solutions
│   ├── steam-client-analysis.md # Steam client analysis
│   └── att-server-implementation.md  # ATT protocol details
├── research/
│   ├── raw-l2cap-viability.md   # Why raw L2CAP works
│   ├── debug-bluetoothd-analysis.md  # BlueZ bug analysis
│   ├── att-mtu-failure-analysis.md   # ATT MTU root cause
│   ├── smp-pairing-bypass-bluez.md   # SMP/ATT separation
│   ├── smp-pairing-summary.md        # Quick reference
│   └── implementation-roadmap.md     # Step-by-step plan
├── dbus-config/
│   └── com.steamdeck.hogp.conf  # D-Bus system policy
├── src/
│   ├── main_l2cap.py            # ★ ENTRYPOINT — raw L2CAP ATT server
│   ├── att_server.py            # ★ Raw L2CAP ATT server (CID 4)
│   ├── gatt_db.py               # ★ GATT database (34 attributes, 5 services)
│   ├── agent.py                 # BlueZ Agent1 (auto-confirm)
│   ├── adv.py                   # BLE advertisement
│   ├── bluez.py                 # BlueZ D-Bus helpers
│   ├── input_handler.py         # Xbox 360 → SC2 input mapping
│   ├── main.py                  # DEPRECATED — BlueZ GATT (broken)
│   └── gatt_app.py              # DEPRECATED — D-Bus GATT objects
├── scripts/
│   └── setup.sh                 # Deck setup script
└── tests/                       # Test scripts
```

## Connection Details

| Item | Value |
|------|-------|
| Deck IP | `<DECK_IP>` |
| SSH user | `deck` / <DECK_PASSWORD> |
| Static BLE address | `C2:12:34:56:78:9A` |
| Host BT adapter | `<HOST_BT_MAC>` |
| Host sudo password | `\` (backslash) |

## Known Issues

1. Connection drops after service discovery (~26s timeout) — SMP pairing timing
2. No `/dev/hidraw` yet — full HOGP lifecycle not completed
3. Host shows KDE pairing dialog — auto-confirm works but user must click "yes"

## Acknowledgments

- SDL3 source for SC2 HID report format documentation
- Valve's steamdeck-bt-controller-emulator project
- BlueZ source code (peripheral/gatt.c reference implementation)
- SteamOS community research
