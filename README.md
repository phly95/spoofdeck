# Steam Deck → Steam Controller 2026 BLE Spoof

Make a Steam Deck present itself as a Steam Controller 2026 over Bluetooth Low Energy, enabling Steam Input support (trackpads, gyro, back buttons) without USB wired mode.

## Current Status

**Working**: Gamepad, trackpads, gyro, back buttons, standard HID input. Steam Client recognizes the Deck as an SC2 controller with full Steam Input features.

**Not working**: Haptics. The haptic forwarding code is ready but Steam never sends haptic output reports. See `docs/findings-backlog.md` for details.

**Stable**: Registration completes reliably. No zombie disconnects after clearing stale BlueZ state.

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    Steam Deck (Peripheral)                 │
│                                                          │
│  main_l2cap.py                                           │
│  ├─ GLib main loop (BlueZ D-Bus advertising)             │
│  ├─ Agent1 (auto-confirm pairing)                        │
│  └─ Raw L2CAP ATT server (CID 4, BDADDR_LE_RANDOM)      │
│     └─ Serves GATT database (85 attributes, 6 services)  │
│     └─ Sends input reports as BLE notifications           │
│                                                          │
│  BlueZ handles: SMP (CID 6) + Advertising                │
│  Input: /dev/hidraw3 (Neptune controller HID)            │
│  └─ input_handler.py reads 64-byte reports               │
│  └─ Maps Neptune buttons → SC2 reports                   │
│  └─ Sends as ATT notifications                            │
└──────────────────────────────────────────────────────────┘
              │
              │ BLE (static random addr C2:12:34:56:78:9A)
              ▼
┌──────────────────────────────────────────────────────────┐
│                    Host PC (Central)                      │
│  BlueZ hog-ll driver → /dev/hidrawN → Steam Client       │
└──────────────────────────────────────────────────────────┘
```

## Why Raw L2CAP?

BlueZ 5.86 on SteamOS has a bug: its GATT listener socket is bound to the adapter's **public address**, but BLE connections arrive on the **static random address**. The kernel can't route the ATT channel → `connect_cb` never fires → connection drops after ~4 seconds.

The fix: use a raw L2CAP socket on CID 4 bound directly to the static random address, bypassing BlueZ's GATT server entirely.

## Quick Start

### Prerequisites

- Steam Deck with Bluetooth enabled
- Host PC with BlueZ and Steam Client
- Python 3.13+ on Deck

### Setup

1. Copy `pii.env.example` to `pii.env` and fill in your values
2. Run `scripts/setup.sh` on the Deck (first time only)
3. Deploy with `scripts/deploy.sh`
4. Connect from host: `bluetoothctl connect C2:12:34:56:78:9A`

### On the Host

```bash
# Connect (NOT pair — pair tries BR/EDR which tears down LE)
bluetoothctl connect C2:12:34:56:78:9A

# Check hidraw
ls -la /dev/hidraw*

# Check input device
evtest /dev/input/eventN
```

## What's Implemented

- **Raw L2CAP ATT server** on CID 4 (bypasses BlueZ GATT bug)
- **GATT database**: GAP, GATT, HID, Battery, Device Info, Valve Custom SC2
- **SMP pairing**: Auto-confirm via BlueZ Agent1 D-Bus interface
- **Input capture**: Reads Neptune controller from `/dev/hidraw3` (64-byte HID reports)
- **SC2 report mapping**: Neptune → 12-byte gamepad + 45-byte SC2 Custom (buttons, sticks, triggers, trackpads, gyro)
- **Synthetic SC2 command handler**: Responds to GET_ATTRIBUTES, GET_SERIAL, SET_SETTINGS, etc.
- **Lizard mode fix**: Periodically re-sends 0x81 command to prevent lizard mode re-enabling
- **Auto-recovery**: Retries Neptune hidraw device on crash (2s delay, 10 retries)
- **Haptic forwarding**: Code ready but host never sends haptic reports

## Project Structure

```
├── AGENTS.md                    # Project continuation guide
├── pii.env.example              # Configuration template (copy to pii.env)
├── docs/
│   ├── sc2-protocol.md          # SC2 BLE protocol details
│   ├── att-server-implementation.md  # ATT protocol details
│   ├── findings-backlog.md      # Known issues and technical findings
│   ├── hardware-findings.md     # Deck hardware findings
│   └── challenges.md            # Known challenges and solutions
├── research/                    # Technical research documents
├── src/
│   ├── main_l2cap.py            # ENTRYPOINT — raw L2CAP ATT server
│   ├── att_server.py            # Raw L2CAP ATT server (CID 4)
│   ├── gatt_db.py               # GATT database (85 attributes, 6 services)
│   ├── input_handler.py         # Neptune HID → SC2 input mapping
│   ├── agent.py                 # BlueZ Agent1 (auto-confirm)
│   ├── adv.py                   # BLE advertisement
│   └── bluez.py                 # BlueZ D-Bus helpers
└── scripts/
    ├── setup.sh                 # Deck setup (first time only)
    ├── deploy.sh                # Deploy source + restart service
    └── diagnose.sh              # Full Deck status diagnostic
```

## Known Issues

- **Haptics not working** — Steam never sends haptic output reports (0x52 packets). Likely a registration/state issue upstream in Steam/hog-ll. See `docs/findings-backlog.md`.
- **PnP ID warning** — BlueZ logs `Error reading PNP_ID: Protocol error` (non-fatal)
- **KDE pairing dialog** — Host shows dialog during pairing, user must click "yes"
- **Stale BlueZ state** — After code changes break a connection, clear bond data and restart BlueZ daemon. See `AGENTS.md` for the fix.

## Contributing

**I don't own a real Steam Controller 2026.** This project was built through reverse engineering `steamclient.so` and Bluetooth protocol analysis. A real SC2 device would unlock:

- **Haptics** — A btmon capture from a real SC2 would show exactly what haptic reports Steam sends, making translation straightforward
- **Protocol refinements** — Verifying our synthetic command responses match a real device
- **Edge cases** — Things only a real device would trigger

If you have a real SC2 and want to help, start with `docs/findings-backlog.md` for the full technical analysis.

## Acknowledgments

- SDL3 source for SC2 HID report format documentation
- BlueZ source code (HOG profile, L2CAP reference)
- SteamOS community research
- InputPlumber project for Neptune protocol documentation
