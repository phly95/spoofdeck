# AGENTS.md — Project Continuation Guide

> **Purpose**: This file gives a new agent session everything it needs to continue this project without re-discovering anything. **You MUST read this entire file before writing any code or making any changes.** Then read the `docs/` folder for protocol details and `research/` for technical analysis.

---

## ⚠️ MUST READ — Critical Context for New Agents

### What This Project Does
Make a **Steam Deck** present itself as a **Steam Controller 2026 (SC2)** over **Bluetooth Low Energy**, so that Steam Client on a host PC recognizes it as an SC2 with full Steam Input support (trackpads, gyro, haptics, back buttons).

### How It Works (Current Architecture)
```
┌──────────────────────────────────────────────────────────┐
│                    Steam Deck (Peripheral)                 │
│                                                          │
│  ┌─────────────────────────────────────────────────────┐ │
│  │  main_l2cap.py                                      │ │
│  │  ├─ GLib main loop (for BlueZ D-Bus advertising)   │ │
│  │  ├─ Agent1 (auto-confirm pairing via dbus-python)   │ │
│  │  └─ Raw L2CAP ATT server thread                     │ │
│  │     └─ Binds to C2:12:34:56:78:9A CID 4            │ │
│  │     └─ Handles all ATT PDU exchange                 │ │
│  │     └─ Serves GATT database (HID + Battery + DIS)   │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                          │
│  ┌─────────────────────┐  ┌──────────────────────────┐  │
│  │  gatt_db.py          │  │  att_server.py            │  │
│  │  (34 attributes,     │  │  (Raw L2CAP socket        │  │
│  │   5 services)        │  │   on CID 4)               │  │
│  └─────────────────────┘  └──────────────────────────┘  │
│                                                          │
│  BlueZ handles:                                          │
│  ├─ SMP pairing (kernel, CID 6)                          │
│  ├─ LE advertising (LEAdvertisingManager1)               │
│  └─ Agent registration (AgentManager1)                   │
│                                                          │
│  Input: /dev/input/event10 (Xbox 360 pad)                │
│  └─ input_handler.py reads → sends as BLE notifications  │
└──────────────────────────────────────────────────────────┘
              │
              │ BLE (static random addr C2:12:34:56:78:9A)
              ▼
┌──────────────────────────────────────────────────────────┐
│                    Host PC (Central)                      │
│                                                          │
│  BlueZ hog-ll driver → /dev/hidrawN → Steam Client       │
└──────────────────────────────────────────────────────────┘
```

### Why Raw L2CAP (Not BlueZ's Built-in GATT Server)?

**BlueZ 5.86 on SteamOS has a critical bug**: its GATT listener socket is bound to the adapter's **public address** (`<DECK_BT_MAC_PUBLIC>`), but BLE connections arrive on the **static random address** (`C2:12:34:56:78:9A`). The kernel's L2CAP layer can't route the ATT channel to the socket → `connect_cb` in `gatt-database.c:646` never fires → no ATT bearer is created → MTU exchange fails → connection drops after ~4 seconds.

**Debug proof** (from `bluetoothd -d -n`):
```
11:31:04 adapter.c:connected_callback() hci0 device <HOST_BT_MAC> connected  # ← kernel accepts
# No GATT/ATT/MTU logs between connect and disconnect        # ← GATT listener never fires
11:31:08 adapter.c:dev_disconnected() reason 2               # ← supervision timeout
```

**The fix**: Use a raw L2CAP socket on CID 4 bound directly to `C2:12:34:56:78:9A` with `BDADDR_LE_RANDOM`. This bypasses BlueZ's buggy GATT server entirely. Confirmed working: MTU exchange and service discovery both succeed.

### Current Status

**✅ Working:**
- Raw L2CAP ATT server accepts connections on CID 4
- MTU exchange succeeds (negotiated 517)
- Service discovery succeeds (5 services, 34 attributes)
- Characteristic discovery succeeds (12 characteristics found)
- Descriptor discovery succeeds (CCCDs, Report References)
- Host reads HID Information, Report Map, PnP ID, Battery Level
- Host writes CCCD to enable notifications on Report/Input (0x0012)
- `/dev/hidrawN` created on host
- Host creates `/dev/input/eventN` with correct gamepad capabilities
- SMP pairing works (auto-confirm via Agent1 D-Bus interface)
- Input handler reads Deck Xbox 360 pad and produces 12-byte HID reports
- ATT notifications (13 bytes: Report ID + report) sent and arrive at host HCI (confirmed via btmon)

**❌ Not Yet Working:**
- Host's BlueZ hog-ll driver drops notifications — doesn't forward to uhid/input
- Zero events arrive at `/dev/input/eventN` on host

### What Needs to Happen Next

1. **Fix hog-ll notification forwarding** — BlueZ 5.72 on the host receives ATT notifications at HCI level but silently drops them. Investigate with `bluetoothd --debug` on host, try fresh pairing, check if BlueZ's ATT client properly routes notifications from our raw L2CAP socket.

### Files You Must Read Before Making Changes

#### MUST READ IN ENTIRETY (Start Here)

| File | Lines | Why |
|------|-------|-----|
| **AGENTS.md** (this file) | 287 | Full project context, architecture, how to run, gotchas |
| `docs/sc2-protocol.md` | 172 | SC2 BLE protocol — PIDs, UUIDs, report formats, button bitmask, mode switching |
| `docs/att-server-implementation.md` | 134 | ATT opcode table, handle layout, host discovery sequence, CCCD handling |
| `research/raw-l2cap-viability.md` | 76 | Confirmed working socket setup code, architecture diagram, ATT opcodes |
| `research/debug-bluetoothd-analysis.md` | 70 | Debug proof of BlueZ bug — why `connect_cb` never fires |

#### MUST READ SECTIONS (Skim These)

| File | Read This Section | Why |
|------|-------------------|-----|
| `research/smp-pairing-summary.md` | Lines 1-50 | Quick answers: SMP and ATT are separate (CID 6 vs CID 4), kernel handles SMP |
| `research/implementation-roadmap.md` | Lines 1-50 | Architecture decision: keep BlueZ for SMP, custom ATT on CID 4 |
| `docs/challenges.md` | Challenges #26-31 | Current bugs and fixes: UUID comparison, handle allocation, MTU format |

#### REFERENCE DOCUMENTS (Read As Needed)

| File | Content |
|------|---------|
| `research/smp-pairing-bypass-bluez.md` | Deep dive into SMP/ATT separation (15KB) |
| `research/att-mtu-failure-analysis.md` | ATT MTU root cause analysis |
| `docs/hardware-findings.md` | Deck hardware: USB, BT, HID descriptors |
| `docs/steam-client-analysis.md` | steamclient.so analysis, firmware files |
| `research/att-mtu-failure-analysis.md` | BlueZ source code analysis for ATT handler |

### Files That Are DEPRECATED (Do Not Use)

| File | Why Deprecated |
|------|---------------|
| `src/main.py` | Uses BlueZ's GATT server (broken on SteamOS). Use `main_l2cap.py` instead |
| `src/gatt_app.py` | D-Bus GATT objects (not needed with raw L2CAP). Use `gatt_db.py` instead |

---

## Connection Details

| Item | Value |
|------|-------|
| Deck IP | `<DECK_IP>` |
| SSH user | `deck` |
| SSH password | <DECK_PASSWORD> |
| sudo password | <DECK_PASSWORD> |
| BT adapter address | `<DECK_BT_MAC_PUBLIC>` (public) |
| Static BLE address | `C2:12:34:56:78:9A` |
| Host PC BT adapter | `<HOST_BT_MAC>` (Qualcomm 4.2) |
| Host sudo password | `\` (backslash) — for btmon |

### SSH Tips
```bash
sshpass -p '<DECK_PASSWORD>' ssh -o StrictHostKeyChecking=no deck@<DECK_IP>
# sudo wrapper:
echo '<DECK_PASSWORD>' | sudo -S "$@"
```

---

## How to Run (Step by Step)

### On the Deck:
```bash
# 1. Stop old services
echo <DECK_PASSWORD> | sudo -S systemctl stop sc2-hogp bluetooth
echo <DECK_PASSWORD> | sudo -S systemctl reset-failed sc2-hogp

# 2. Remove debug override (if exists)
echo <DECK_PASSWORD> | sudo -S rm -rf /etc/systemd/system/bluetooth.service.d
echo <DECK_PASSWORD> | sudo -S systemctl daemon-reload

# 3. Restart bluetooth
echo <DECK_PASSWORD> | sudo -S systemctl start bluetooth
sleep 2

# 4. Apply BT config (bredr off + static addr)
echo <DECK_PASSWORD> | sudo -S python3 /tmp/config_bt.py

# 5. Start the raw L2CAP ATT server
echo <DECK_PASSWORD> | sudo -S systemd-run --remain-after-exit \
  --unit=sc2-hogp \
  --property=WorkingDirectory=/tmp/sc2-spoof \
  python3 -u /tmp/sc2-spoof/src/main_l2cap.py \
  --name "Steam Controller 2026"

# 6. Check logs
journalctl -u sc2-hogp -f
```

### On the Host:
```bash
# Scan and pair
bluetoothctl --timeout 10 scan on
bluetoothctl pair C2:12:34:56:78:9A

# Check hidraw
ls -la /dev/hidraw*

# Check connection stability
bluetoothctl info C2:12:34:56:78:9A
```

---

## Deck Hardware Details

### Bluetooth Adapter
- Qualcomm QCA, Bluetooth 5.3
- Roles: **central + peripheral** (critical — supports advertising)
- 16 advertising instances
- Python 3.13.5, BlueZ 5.86, GLib 2.84.3

### Controller Input
- `event10` / `js0`: Virtual Xbox 360 pad (created by `hid-steam` driver)
- Input handler reads from `/dev/input/event10`
- Maps Xbox buttons → SC2 button bitmask

---

## SC2 BLE Protocol

### Device IDs
| Mode | VID | PID |
|------|-----|-----|
| BLE | 0x28DE | 0x1303 |
| USB wired | 0x28DE | 0x1302 |

### GATT Services (5 total)
| Service | UUID | Handles |
|---------|------|---------|
| GAP | 0x1800 | 0x0001-0x0005 |
| GATT | 0x1801 | 0x0006-0x0009 |
| HID | 0x1812 | 0x000A-0x0017 |
| Battery | 0x180F | 0x0018-0x001B |
| Device Info | 0x180A | 0x001C-0x0022 |

### Input Report 0x45 (45 bytes)
Sticks, triggers, trackpads, IMU — see `docs/sc2-protocol.md` for full format.

---

## Known Gotchas

1. **Never use `ControllerMode=le` in main.conf** — causes "Not Supported" error
2. **btmgmt power-cycles kill hogp** — always start hogp AFTER config_bt.py
3. **Static BLE address lost on reboot** — must re-apply after every bluetooth restart
4. **Python 3.13 doesn't support BLE socket tuple syntax** — use `ctypes.bind()` for raw L2CAP
5. **`SOL_BLUETOOTH` not in Python 3.13** — must use numeric constant (10)
6. **`btmgmt info` output is empty** — known SteamOS issue, ignore it
7. **`steamos-readonly`** — must disable before modifying `/etc/`
8. **KDE pairing dialog** — host shows dialog during pairing, user must click "yes"

---

## Research & Analysis Documents

| Document | Content |
|----------|---------|
| `research/raw-l2cap-viability.md` | Why raw L2CAP approach is confirmed viable |
| `research/debug-bluetoothd-analysis.md` | Debug proof of BlueZ GATT listener bug |
| `research/att-mtu-failure-analysis.md` | ATT MTU exchange failure root cause |
| `research/smp-pairing-bypass-bluez.md` | SMP pairing works separately from ATT |
| `research/smp-pairing-summary.md` | Quick reference for SMP/ATT separation |
| `research/implementation-roadmap.md` | Step-by-step implementation plan |
| `docs/att-server-implementation.md` | ATT protocol implementation details |

---

## Project File Structure

```
/home/philip/steamdeck-sc2-spoof/
├── AGENTS.md                    ← YOU ARE HERE (read this first!)
├── README.md                    # Project overview
├── docs/
│   ├── sc2-protocol.md          # SC2 BLE protocol details
│   ├── hardware-findings.md     # Deck hardware findings
│   ├── challenges.md            # Known challenges and solutions
│   ├── steam-client-analysis.md # Steam client analysis
│   └── att-server-implementation.md  # ATT protocol details
├── research/                    # Technical research documents
│   ├── raw-l2cap-viability.md
│   ├── debug-bluetoothd-analysis.md
│   ├── att-mtu-failure-analysis.md
│   ├── smp-pairing-bypass-bluez.md
│   ├── smp-pairing-summary.md
│   └── implementation-roadmap.md
├── dbus-config/
│   └── com.steamdeck.hogp.conf  # D-Bus system policy
├── src/
│   ├── main_l2cap.py            # ★ ENTRYPOINT — raw L2CAP ATT server
│   ├── att_server.py            # ★ Raw L2CAP ATT server
│   ├── gatt_db.py               # ★ GATT database (34 attributes)
│   ├── agent.py                 # BlueZ Agent1 (auto-confirm)
│   ├── adv.py                   # BLE advertisement
│   ├── bluez.py                 # BlueZ D-Bus helpers
│   ├── input_handler.py         # Xbox 360 → SC2 input mapping
│   ├── main.py                  # DEPRECATED — uses BlueZ GATT (broken)
│   └── gatt_app.py              # DEPRECATED — D-Bus GATT objects
├── scripts/
│   └── setup.sh                 # Deck setup script
└── tests/                       # Test scripts
```
