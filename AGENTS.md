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
  │  │  gatt_db.py               │  │  att_server.py            │  │
  │  │  (85 attributes,           │  │  (Raw L2CAP socket        │  │
  │  │   6 services)              │  │   on CID 4)               │  │
│  └─────────────────────┘  └──────────────────────────┘  │
│                                                          │
│  BlueZ handles:                                          │
│  ├─ SMP pairing (kernel, CID 6)                          │
│  ├─ LE advertising (LEAdvertisingManager1)               │
│  └─ Agent registration (AgentManager1)                   │
│                                                          │
│  Input: /dev/hidraw3 (Neptune controller, USB iface 2)   │
│  ├─ input_handler.py reads 64-byte HID reports           │
│  ├─ Maps Neptune buttons → SC2 12-byte report            │
│  └─ Sends as ATT notifications (no Report ID prefix)     │
│                                                          │
│  Lizard mode: periodically re-sends 0x81 cmd to disable  │
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

**Working (End-to-End):**
- Raw L2CAP ATT server accepts connections on CID 4.
- MTU exchange succeeds (negotiated 517).
- Service discovery succeeds (6 services, 85 attributes).
- Characteristic/Descriptor discovery succeeds.
- Host reads HID Information, Report Map, PnP ID, Battery Level.
- PnP ID format corrected: Vendor ID Source set to USB-IF (0x02) with Valve's VID (0x28DE) and PID (0x1303).
- Host writes CCCD to enable notifications on Report/Input (0x0012), Mouse (0x001c), Keyboard (0x0020), SC2 Custom CHR_REPORT (0x0033), and Battery (0x003c).
- `/dev/hidrawN` created on host.
- Host creates `/dev/input/eventN` for Mouse and Keyboard.
- SMP pairing works (auto-confirm via Agent1 D-Bus interface).
- **Physical Deck controller input works** — reads from `/dev/hidraw3` (Neptune HID, 64-byte reports).
- Input handler maps Neptune buttons → SC2 12-byte report format (Y axis inverted correctly).
- **Standard HID gamepad reports flow** — Host detects generic gamepad via KDE Game Controller and Steam Controller Settings.
- **45-byte SC2 Custom reports flow** — Host receives Report ID 0x45 reports via `/dev/hidrawN`, verified via hexdump.
- **Trackpads work** — Left/right trackpad X/Y data flows in 45-byte reports.
- **Gyro works** — IMU accelerometer and gyroscope data flows in 45-byte reports.
- **Back buttons work** — L4/L5/R4/R5 paddle data flows in button bitmask.
- Connection stable for 5+ minutes (use `connect` not `pair`). Clear stale bonding keys after Deck BT restart.
- **Synthetic SC2 Command Handler** — Feature Report 0x00 (SC2 command channel) intercepted locally. Handles GET_ATTRIBUTES, GET_SERIAL, CLEAR_MAPPINGS, SET_ATTRIBUTES, SET_MODE with synthetic SC2 device info responses matching real device byte layout.
- **Neptune Auto-Recovery** — Input handler retries opening hidraw device on crash (2s delay, 10 retries).
- **CHR_REPORT SC2 Custom in HID Service** — Report IDs 0x45 (45-byte) and 0x47 (47-byte) in HID Service for hog-ll subscription. Dual notification targets: Valve Custom Service + HID Service CHR_REPORT.
- **In-game rumble works** — Full haptic pipeline confirmed end-to-end with Celeste hazard impacts. Host game calls `SDL_RumbleJoystick()` → SDL writes output report to `/dev/hidrawN` → kernel `UHID_OUTPUT` → BlueZ hog-ll `forward_report()` → ATT Write Request (0x12) to handle 0x0019 → `_on_haptic_write()` → `_forward_haptic_to_neptune()` → writes PackedRumbleReport to `/dev/hidraw3` → Neptune dual ERM motors vibrate. Rumble format matches InputPlumber's PackedRumbleReport: `[0xeb, 0x09, 0x00, 0x00, 0x00, left_lo, left_hi, right_lo, right_hi]` padded to 64 bytes.
- **Lizard mode properly disabled** — NEPTUNE_LIZARD_OFF_CMDS uses direct 0x81 command (no Report ID prefix). EVIOCGRAB grabs event4/event5 at startup to prevent lizard mode evdev events from reaching KDE desktop.

**Not Working:**
- **Steam-generated haptics** — Trackpad clicks, UI feedback haptics, and other Steam-internal haptic events do NOT produce rumble. These come from Steam's own haptic system, not from `SDL_RumbleJoystick()`. The Steam haptic path uses a different code path that does not reach the Neptune motors. Only games that call `SDL_RumbleJoystick()` produce rumble.

**~~❌ Not Working (Both PRE-EXISTING)~~ — RESOLVED (2026-06-26):**
- **~~Zombie disconnect~~** — Caused by stale BlueZ state, not code. After host PC reboot or clearing bond data + restarting BlueZ daemon, registration completes and input flows.
- **~~Encryption error~~** — Same root cause. Cleared after host reboot.
- **~~Input not reaching Steam~~** — Resolved after clearing stale BlueZ state.

**NOTE (2026-06-26 evening)**: After host PC reboot, input IS flowing. The stale BlueZ state from previous sessions was blocking SET_REPORT. A reboot cleared it. This explains why the issues appeared pre-existing — the cached state persisted across code deploys.

### What Needs to Happen Next

1. **LD_PRELOAD patch for 0x8F gate (RECOMMENDED)** — The verified root cause of missing Steam haptics is that `[r15+0x208]` at `0x10d4da0` stays 0 on BLE, so the 0x8F dispatch is skipped. The only setter is `YieldingRunTestProgram` at `0x0156781c` (`mov byte [r15+0x208], 1`), which is reached through a controller message dispatcher at `0x015675a8` that branches on `[rdi+0x1d8]` (controller state/type). On BLE, the state is 3-4 instead of 1-2, so the path is never taken. **Recommended next step**: Write a C library loaded via `LD_PRELOAD` that patches the conditional jump `je 0x10d4fd0` at `0x10d4da6` to `nop nop`, forcing 0x8F dispatch regardless of the gate. 55-65% probability of working. If it crashes, GDB watchpoint reveals what gate controls. If it works, Steam haptics (trackpad clicks, UI feedback) will flow to Neptune motors.
2. **ATT Server Spec Compliance** — Implement one at a time, test each:
   - Read Blob error code (0x01 → 0x07)
   - MTU caps on Read/Notify PDUs
   - PDU length validation
   - ATT permission checking (Read + Write Request only, NOT Write Command)
   - Fix diagnostic handle labels

### Files You Must Read Before Making Changes

#### MUST READ IN ENTIRETY (Start Here)

| File | Lines | Why |
|------|-------|-----|
| **AGENTS.md** (this file) | 615 | Full project context, architecture, how to run, gotchas, working principles |
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

## Working Principles — How to Investigate Efficiently

> **The main thread's context window is finite and precious.** This project involves SSH debugging, BLE protocol analysis, BlueZ source code reading, and iterative deploy/test cycles. If you do all of this in the main thread, you'll fill the context before reaching a solution. Follow these principles.

### Principle 1: Actors for Research, Main Thread for Decisions

| Phase | Who Does It | Why |
|-------|-------------|-----|
| Reading BlueZ source code | `actor(explore)` | 500+ lines of hog-lib.c / uhid.c analysis fills context fast |
| Analyzing btmon / host logs | `actor(explore)` | Log parsing is mechanical, conclusions are what matter |
| Checking Deck SSH logs | `actor(explore)` | Repeated `sshpass ssh deck@...` calls add up |
| SSH restart/test cycles | `actor(general)` | Deploy → restart → pair → check can run autonomously |
| Writing code changes | **Main thread** | Needs full context of architecture + findings |
| Making decisions | **Main thread** | Needs synthesized results from actors, not raw data |

**The pattern**: Spawn an actor with a specific question, get a concise answer back, act on it. Don't do the investigation yourself.

> **📖 See `docs/actor-prompt-guide.md`** for templates and examples of how to formulate actor prompts. Read it before spawning any actor. It covers RE/binary analysis, deploy/test, and source code analysis prompts with correct structure, stop conditions, and parallelism rules.

### Principle 2: Batch SSH Operations

**Bad** (fills context with 10+ SSH round-trips):
```
sshpass ssh deck@... "check service status"
sshpass ssh deck@... "restart service"
sshpass ssh deck@... "check logs"
sshpass ssh deck@... "check logs again"
sshpass ssh deck@... "check if device exists"
```

**Good** (one script, one deployment):
```bash
# Write a diagnostic script once
cat > /tmp/diagnose.sh << 'EOF'
#!/bin/bash
echo "=== Service Status ==="
systemctl status sc2-hogp --no-pager | head -5
echo "=== Last 20 Logs ==="
journalctl -u sc2-hogp -n 20 --no-pager
echo "=== Connection State ==="
bluetoothctl info C2:12:34:56:78:9A 2>/dev/null | head -10
echo "=== Input Devices ==="
ls /sys/class/input/ | while read d; do
  name=$(cat /sys/class/input/$d/device/name 2>/dev/null)
  echo "$d: $name"
done
EOF
# Deploy and run once
sshpass scp /tmp/diagnose.sh deck@<DECK_IP>:/tmp/
sshpass ssh deck@<DECK_IP> 'bash /tmp/diagnose.sh'
```

### Principle 3: Actors for Iterative Testing

The deploy → restart → pair → check cycle is the biggest context consumer. Delegate it:

```
actor(general, prompt="""
  Deploy the updated src/ files to the Deck at /tmp/sc2-spoof/src/
  via sshpass -p '<DECK_PASSWORD>' scp.
  Then:
  1. Restart sc2-hogp on Deck
  2. Run the pexpect auto-pair script
  3. Check Deck logs for notifications sent
  4. Check host for events on /dev/input/eventN
  5. Report: did notifications arrive? did events appear?
""")
```

The actor handles the entire cycle. You get back: "Notifications arrived at HCI. No events on eventN. Connection dropped after 1s." You decide the next move.

### Principle 4: Research BlueZ Internals via Explore Actors

When you need to understand how hog-ll processes notifications, don't read 500 lines of hog-lib.c yourself:

```
actor(explore, prompt="""
  Read /tmp/bluez-src/profiles/input/hog-lib.c and
  /tmp/bluez-src/src/shared/uhid.c.
  Answer these specific questions:
  1. What happens in report_value_cb() when a notification arrives?
  2. How does bt_uhid_input() handle the 'number' parameter?
  3. When is report->numbered set to true?
  4. How does the uhid input queue work (uhid->input)?
  5. When is the queue flushed?
  Return only the answers, not the full source code.
""")
```

### Principle 5: Separate Investigation from Implementation

**Investigation phase** (use actors):
- "Why does the host drop the connection after pairing?"
- "What does BlueZ's hog-ll do when it receives an ATT notification?"
- "Is the uhid device created before or after the Report Map is read?"

**Implementation phase** (main thread):
- Make the code change based on findings
- Deploy and verify

Don't mix these. If you're reading source code while also trying to edit files, you'll fill context with both.

### Principle 6: Capture Only What You Need from SSH

**Bad** — Dumping entire journal logs:
```
sshpass ssh deck@... "journalctl -u sc2-hogp --no-pager"
# Returns 200 lines of ATT PDU traffic
```

**Good** — Filtering to what matters:
```
sshpass ssh deck@... "journalctl -u sc2-hogp --since '1 min ago' --no-pager | grep -i 'error\|notif\|disconnect\|test'"
```

**Better** — Actor handles it and returns summary:
```
actor(explore, prompt="SSH to deck@<DECK_IP> (password: <DECK_PASSWORD>) and check the last 2 minutes of sc2-hogp logs. Filter for errors, notifications, disconnections. Report only the key findings in 5 lines.")
```

### Principle 7: Host-Side Debugging Pattern

For host BT debugging, the typical flow is:
1. `bluetoothctl info C2:12:34:56:78:9A` — check connection state
2. `journalctl | grep hog` — check BlueZ logs
3. `btmon -t -w /tmp/capture.log &` — capture HCI traffic
4. `evtest /dev/input/eventN` — check for input events

Do steps 1-2 via actor. Step 3 requires root (use `printf '<HOST_SUDO_PASSWORD>\n' | sudo -S`). Step 4 needs the connection to be active — run it in parallel with the test, not after.

### Principle 8: SSH Password Handling

The Deck uses `sshpass -p '<DECK_PASSWORD>'`. The host uses sudo with password `<HOST_SUDO_PASSWORD>`. For repeated Deck operations, create a wrapper:

```bash
# On the host, create a helper function
deck() {
  sshpass -p '<DECK_PASSWORD>' ssh -o StrictHostKeyChecking=no deck@<DECK_IP> "$@"
}
deck_sudo() {
  sshpass -p '<DECK_PASSWORD>' ssh -o StrictHostKeyChecking=no deck@<DECK_IP> "echo <DECK_PASSWORD> | sudo -S $*"
}
```

### Principle 9: When You Must Do It in Main Thread

Sometimes you can't delegate (e.g., making code changes, analyzing complex protocol interactions). In those cases:

1. **Use `grep` over `read`** for finding specific patterns in large files
2. **Read targeted sections** (use offset/limit) not full files
3. **Summarize findings immediately** — don't leave large code blocks in context
4. **Make the edit, deploy, then move on** — don't re-read the file you just edited

### Principle 10: The Anti-Pattern Checklist

Before starting work, check if you're about to:
- [ ] Read 200+ lines of source code → **Spawn an explore actor**
- [ ] Run 5+ SSH commands in sequence → **Write a script or use an actor**
- [ ] Do an iterative deploy/test cycle → **Use an actor**
- [ ] Analyze log output line-by-line → **Use an actor with grep filters**
- [ ] Read the same file you read last session → **Check AGENTS.md first**

If any box is checked, redirect to an actor.

### Principle 11: Parallelism Without Stepping on Toes

When spawning multiple background actors, you must prevent them from competing for shared resources. This project has several exclusive resources that can only be used by one agent at a time.

#### Resource Classification

| Resource | Type | Conflicts With | Safe to Parallel? |
|----------|------|----------------|-------------------|
| **Local files (read)** | Read-only | Nothing | ✅ Yes — multiple explore actors |
| **Local files (write)** | Exclusive | Other writes to same file | ⚠️ Only if different files |
| **Deck SSH session** | Exclusive | Other SSH to Deck | ❌ Serialize — one SSH at a time |
| **Deck sc2-hogp service** | Exclusive | Restart/stop by another agent | ❌ Serialize — one lifecycle op at a time |
| **Deck BT adapter config** | Exclusive | Other config_bt.py calls | ❌ Serialize — adapter state is global |
| **Host bluetoothctl** | Exclusive | Other bluetoothctl instances | ❌ Serialize — one pairing at a time |
| **Host btmon** | Exclusive | Other btmon instances | ❌ Serialize — one capture at a time |
| **BLE connection** | Exclusive | Other connection attempts | ❌ Serialize — one connection at a time |
| **Host /dev/hidrawN** | Exclusive | Other hidraw readers | ⚠️ Usually one reader |
| **Host /dev/input/eventN** | Shared read | evtest while connection active | ✅ Read-only is fine |
| **Already-captured logs** | Read-only | Nothing | ✅ Yes — multiple readers |

#### The Rule: Check Before You Act

Before spawning a parallel actor, ask:

1. **Does it SSH to the Deck?** → Must not overlap with another Deck-SSH actor
2. **Does it restart a service?** → Must be the only one doing lifecycle operations
3. **Does it run bluetoothctl?** → Must be the only one pairing/connecting
4. **Does it run btmon?** → Must be the only one capturing
5. **Does it write to a file?** → Must not overlap with another writer to the same file

#### Safe Parallel Patterns

**✅ Safe — Multiple explore actors reading local files:**
```
actor(explore, prompt="Read /tmp/bluez-src/hog-lib.c and explain report_value_cb")
actor(explore, prompt="Read /tmp/bluez-src/uhid.c and explain bt_uhid_input")
# Both read local files, no conflict
```

**✅ Safe — One SSH actor + one local-file actor:**
```
actor(general, prompt="SSH to Deck, restart sc2-hogp, check logs")
actor(explore, prompt="Read src/input_handler.py and explain the button mapping")
# One touches Deck, other touches local files — no conflict
```

**❌ Unsafe — Two SSH actors in parallel:**
```
actor(general, prompt="SSH to Deck, restart sc2-hogp")
actor(general, prompt="SSH to Deck, check logs")
# Both try to SSH simultaneously — undefined behavior
```

**❌ Unsafe — btmon + pairing in parallel:**
```
actor(general, prompt="Run btmon to capture traffic")
actor(general, prompt="Pair with the Deck via bluetoothctl")
# btmon needs exclusive adapter access; pairing changes adapter state
```

#### Serialization Protocol

When multiple actors need the same resource, serialize them:

```
# Step 1: Deploy code (exclusive Deck access)
actor(general, prompt="Deploy updated src/ to Deck via scp")

# Step 2: After Step 1 completes, restart service (exclusive Deck access)
actor(general, prompt="Restart sc2-hogp on Deck, report logs")

# Step 3: After Step 2 completes, pair (exclusive host BT access)
actor(general, prompt="Pair with Deck via bluetoothctl, check result")

# Step 4: After Step 3 completes, capture traffic (exclusive btmon access)
actor(general, prompt="Run btmon, wait for notifications, report findings")
```

Use `actor(operation="wait", actor_id=...)` to block until the previous actor finishes before spawning the next one.

#### The Quick Heuristic

> **If two actors would both run `sshpass ssh deck@...` or both run `bluetoothctl`, they MUST NOT run in parallel.** Run them sequentially with `wait` between them.

---

## Connection Details

All connection details are in `pii.env` (not tracked by git). Source it before running scripts:

```bash
source pii.env
```

| Item | Env Variable |
|------|-------------|
| Deck IP | `$DECK_IP` |
| SSH user | `$DECK_USER` |
| SSH password | `$DECK_PASSWORD` |
| sudo password | `$DECK_SUDO_PASSWORD` |
| BT adapter address | `$DECK_BT_MAC_PUBLIC` (public) |
| Static BLE address | `C2:12:34:56:78:9A` (fixed) |
| Host PC BT adapter | `$HOST_BT_MAC` |
| Host sudo password | `$HOST_SUDO_PASSWORD` |

### SSH Tips
```bash
source pii.env
sshpass -p "$DECK_PASSWORD" ssh -o StrictHostKeyChecking=no "$DECK_USER@$DECK_IP"
# sudo wrapper:
echo "$DECK_PASSWORD" | sudo -S "$@"
```

---

## How to Run (Step by Step)

### On the Deck:
```bash
source pii.env

# 1. Stop old services
echo $DECK_PASSWORD | sudo -S systemctl stop sc2-hogp bluetooth
echo $DECK_PASSWORD | sudo -S systemctl reset-failed sc2-hogp

# 2. Remove debug override (if exists)
echo $DECK_PASSWORD | sudo -S rm -rf /etc/systemd/system/bluetooth.service.d
echo $DECK_PASSWORD | sudo -S systemctl daemon-reload

# 3. Restart bluetooth
echo $DECK_PASSWORD | sudo -S systemctl start bluetooth
sleep 2

# 4. Apply BT config (bredr off + static addr)
echo $DECK_PASSWORD | sudo -S python3 /tmp/config_bt.py

# 5. Start the raw L2CAP ATT server
echo $DECK_PASSWORD | sudo -S systemd-run --remain-after-exit \
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

### Controller Input (Neptune HID)
- **Neptune controller**: VID=0x28DE, PID=0x1205, 3 hidraw interfaces
- **Gamepad hidraw**: `/dev/hidraw3` (USB interface 2, input2 — identified by HID_PHYS containing 'input2')
- **HID descriptor**: NO Report ID — raw 64 bytes per report
- **Report type**: 0x09 (`ID_CONTROLLER_DECK_STATE`) — contains sticks, triggers, buttons, trackpads, IMU, force sensors
- **Input handler** reads 64-byte Neptune reports → maps to 12-byte SC2 format → sends as ATT notifications
- **Lizard mode**: `hid-steam` driver only generates evdev events when `gamepad_mode` is true (requires Steam running). Without Steam, controller is in lizard mode (buttons map to keyboard scancodes). Solution: read directly from hidraw.
- **Lizard mode re-enables** every ~2 seconds; must re-send 0x81 (`ClearDigitalMappings`) command periodically via `os.write()`
- **Feature report ioctl** `HIDIOCSFEATURE` returns EINVAL on hidraw — use `os.write()` for output reports instead
- **Reference**: [InputPlumber](https://github.com/ShadowBlip/InputPlumber) — Neptune protocol documentation

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
9. **Stale BlueZ state causes zombie disconnects / CCCD failures** — The host's BlueZ daemon caches pairing keys, CCCD states, and HOG profile state per-device. When the Deck's BT stack restarts (or code changes break the connection mid-session), this cached state becomes stale. Symptoms: zombie disconnects, CCCDs never enabled (notifications dropped), `CGetControllerInfoWorkItem::RunFunc: Read failure`, or `Encryption Key Size is insufficient` errors. **Fix (in order of escalation):**
   - `bluetoothctl remove C2:12:34:56:78:9A` + reconnect (clears in-memory state only)
   - Clear bond data + restart BlueZ daemon (clears persistent state):
     ```
     sudo rm -rf /var/lib/bluetooth/<HOST_BT_MAC>/C2:12:34:56:78:9A
     sudo rm -rf /var/lib/bluetooth/cache
     sudo systemctl restart bluetooth
     ```
     Then restart the Deck's sc2-hogp service to re-register the advertisement.
   - Full host reboot (nuclear option — clears everything including kernel-level BLE state)
   - **IMPORTANT**: `btusb` kernel module reset (`sudo rmmod btusb && sudo modprobe btusb`) does NOT fix this — the stale state is in BlueZ user-space, not the kernel driver.
10. **hog-ll strips Report ID from output reports** — When the host writes an output report (e.g., haptic 0x80) to `/dev/hidrawN`, hog-ll strips the Report ID byte before sending the ATT Write Request (0x12). The `_on_haptic_write()` handler must parse the 9-byte payload without the 0x80 prefix (type at [0], left speed at [3], right speed at [6]). Note: `forward_report()` uses ATT Write Request (0x12), NOT Write Command (0x52), because our CHR_REPORT has `GATT_CHR_PROP_WRITE`.
11. **Cumulative BlueZ state corruption** — Repeated connection failures (e.g., from code bugs sending bad ATT responses) can poison BlueZ's HOG driver state. The driver may stop re-enabling CCCDs on subsequent connections, even after `bluetoothctl remove`. The only fix is clearing bond data + restarting the daemon, or a full reboot. This is why testing with a broken code version can break ALL subsequent tests until the state is cleared.
12. **In-game rumble works, Steam haptics do not** — Games that call `SDL_RumbleJoystick()` produce rumble that flows through the full pipeline (SDL → hidraw → UHID → hog-ll → ATT 0x12 → Neptune motors). Steam-generated haptics (trackpad clicks, UI feedback) use a different code path that does not reach the Neptune motors. See `docs/findings-backlog.md` for details.

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
/home/philip/spoofdeck-modified/
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
│   ├── gatt_db.py               # ★ GATT database (85 attributes, 6 services)
│   ├── agent.py                 # BlueZ Agent1 (auto-confirm)
│   ├── adv.py                   # BLE advertisement
│   ├── bluez.py                 # BlueZ D-Bus helpers
│   ├── input_handler.py         # Xbox 360 → SC2 input mapping
│   ├── main.py                  # DEPRECATED — uses BlueZ GATT (broken)
│   └── gatt_app.py              # DEPRECATED — D-Bus GATT objects
├── scripts/
│   ├── setup.sh                 # Deck setup script (first-time only)
│   ├── deploy.sh                # Deploy source files + restart service
│   ├── pair.py                  # Pexpect auto-pair (handles KDE dialog)
│   ├── diagnose.sh              # Full Deck status diagnostic
│   ├── connect_deck.py          # BLE connection (subprocess-based)
│   ├── bt_agent_pty.py          # PTY-based bluetoothctl agent
│   ├── bt_agent.py              # D-Bus agent
│   ├── bt_remove.py             # Remove BT device
│   └── config_bt.py             # Configure BT adapter
└── tests/                       # Test scripts
```
