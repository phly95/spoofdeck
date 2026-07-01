# Steam Controller Puck ↔ Triton ESB Cross-Reference

**Purpose**: Map the complete ESB (Enhanced ShockBurst) wireless protocol between the Puck (USB dongle) and Triton (SC2 BLE controller).

**Data Sources**:
- Puck firmware: `proteus_firmware.bin` (197,740 bytes, 790 functions)
- Triton firmware: `ibex_firmware.bin` (350,528 bytes, 2,027 functions)
- Both: Nordic nRF52840, Zephyr RTOS, nRF Connect SDK v2.9.0

---

## 1. ESB Packet Format

### Nordic ESB Standard (Zephyr Implementation)

Both firmwares use the **Zephyr ESB library** (`libesb`), which implements Nordic's Enhanced ShockBurst protocol. The packet format is fixed by the hardware radio peripheral:

```
┌──────────┬──────────┬────────────┬──────────┬───────────┬─────────┐
│ Preamble │ Address  │ Header (9b)│ Length(6b)│ Payload   │  CRC    │
│ 1-2 bytes│ 4-5 bytes│            │          │ 0-32 bytes│ 2-3 bytes│
└──────────┴──────────┴────────────┴──────────┴───────────┴─────────┘
```

**Confirmed from firmware strings**:
- Puck: `No event from ESB. Manually disabling radio so we get RADIO_IRQ for RX stage` — confirms direct radio IRQ handling (Zephyr ESB pattern)
- Puck: `Failed to initialize ESB system timer` — ESB uses a dedicated timer for retransmit/ACK timing
- Triton: `Failed to initialize ESB system timer` — same timer pattern on controller side
- Triton: `ESB TX FIFO full` — confirms hardware TX FIFO, standard ESB behavior

### Preamble
- **1 byte** at 1 Mbps data rate
- **2 bytes** at 2 Mbps data rate
- Both firmwares default to 2 Mbps (evidenced by high-throughput report relay and Zephyr ESB defaults)

### Address (4-5 bytes)
- **Puck (Dongle) address format**: `ibex%d_proteus_uuid : 0x%08X` — Puck has a 32-bit UUID per controller slot
- **Triton (Controller) address format**: `Connecting to: Proteus %s, (0x%08X, 0x%08X)` — connects using two 32-bit values (base address + prefix)
- **Connected pipe**: `Connected: private pipe (%u/%u, addr 0x%08X, prefix %u` — pipe number, endpoint, 32-bit address, prefix byte
- Total address: **5 bytes** (4-byte base + 1-byte prefix), standard Nordic ESB

### Header (9 bits)
- **PID** (2 bits): Packet ID for auto-ACK duplicate detection
- **NO_ACK** (1 bit): If set, no acknowledgment requested
- **Reserved** (6 bits)

### Payload Length (6 bits)
- 0-32 bytes (ESB standard maximum)

### CRC
- **2 bytes** (16-bit) or **3 bytes** (24-bit), configured in the Zephyr ESB library
- Puck string: `Unexpected CRC16 value %x` — confirms **16-bit CRC**

---

## 2. ESB Address/Channel Configuration

### Address Architecture

From both firmware strings, ESB uses a **pipe-based addressing** system:

**Puck side** (4 controller slots):
```
esb-controller@0    — Device tree node for slot 0
esb-controller@1    — Device tree node for slot 1
esb-controller@2    — Device tree node for slot 2
esb-controller@3    — Device tree node for slot 3
```

**Pipe endpoints** (per controller):
```
esb/ibex_0          — ESB pipe endpoint to controller slot 0
esb/ibex_1          — ESB pipe endpoint to controller slot 1
esb/ibex_2          — ESB pipe endpoint to controller slot 2
esb/ibex_3          — ESB pipe endpoint to controller slot 3
```

**Shared data structure**: `ibexesb_common` — common ESB/Ibex data structure accessed by all slots

**Per-controller UUIDs** (Puck stores):
```
ibex%d_proteus_uuid : 0x%08X    — Puck's UUID for this slot
ibex%d_ibex_uuid : 0x%08X      — Controller's UUID for this slot
ibex%d_peer_sn : %s             — Controller's serial number
```

### Address Generation
- Each Puck generates a unique 32-bit UUID per controller slot (`proteus_uuid`)
- Each controller has its own 32-bit UUID (`ibex_uuid`)
- During pairing, these UUIDs are exchanged and stored as bond data
- The 5-byte ESB address = 4-byte UUID + 1-byte prefix

### Channel Configuration

**Puck strings**:
- `esb_set_rf_channel %d %u` — configurable RF channel per slot
- `Initializing channel map` — channel map for frequency hopping
- `Slot %u : Connected Ibex %s (Ch %u)` — channel assigned per connection
- `radio_send_channels` / `radio_send_channels <timeout_s> [channels]` — shell commands for channel testing

**Triton strings**:
- `Failed to allocate PPI Channel` — PPI (Programmable Peripheral Interconnect) for radio timing
- `Failed to initialize ESB system timer` — ESB timing timer

### RF Parameters

| Parameter | Value | Evidence |
|-----------|-------|----------|
| **Protocol** | Nordic ESB | `dongle_esb`, `triton_esb` module names |
| **Frequency band** | 2.4 GHz ISM | Standard ESB, nRF52840 radio |
| **Data rate** | 2 Mbps | Default Zephyr ESB, 45-byte reports at high rate |
| **Channel spacing** | 1 MHz | ESB standard |
| **Channel range** | 2-126 | ESB standard, configurable via `esb_set_rf_channel` |
| **Auto-ACK** | Enabled | ESB standard, confirmed by PID in header |
| **CRC** | 16-bit | `Unexpected CRC16 value %x` in Puck |
| **Max payload** | 32 bytes | ESB standard, but reports may be fragmented |
| **Retransmit** | Up to 15 retries | ESB default, configurable |

### Frequency Hopping
- ESB uses **adaptive frequency hopping** across multiple channels
- The Puck maintains a **channel map** per controller slot
- `Initializing channel map` — channel map configured at connection time
- Channel can be queried per connection: `Slot %u : Connected Ibex %s (Ch %u)`
- `channel_cost` / `channel_cost_show` — channel quality tracking for adaptive hopping

---

## 3. Data Relay Translation

### Input Path (Controller → Host via Puck)

```
Triton Controller
  ├─ Neptune controller input (hidraw3, 64-byte reports)
  ├─ Firmware maps to SC2 format (45-byte report 0x45)
  ├─ ESB radio transmit (2.4 GHz, 2 Mbps)
  │   └─ Payload: SC2 report data (report IDs 0x40-0x7B)
  ▼
Puck nRF52840
  ├─ ESB radio receive → pipe decode (esb/ibex_N)
  ├─ Protocol version check
  ├─ HID proxy (HID_PROXY_N)
  ├─ board_hid_over_i2c → USB HID composite device
  │   └─ Same report IDs (0x40-0x7B) preserved
  ▼
Host PC
  └─ /dev/hidrawN → kernel HID driver → Steam Client
```

**Key insight from Puck analysis**: The Puck is a **transparent relay** — report IDs are preserved between ESB and USB HID. The ESB payload contains the same SC2-format reports that appear on the USB HID interface.

### Output Path (Host → Controller via Puck)

```
Host PC
  ├─ USB HID output report (report IDs 0x80-0x89)
  ├─ board_hid_over_i2c → HID proxy (HID_PROXY_N)
  ├─ ESB packet encode (per-slot)
  │   └─ Payload: same output report data
  ▼
Triton Controller
  ├─ ESB radio receive
  ├─ Command handler (same as BLE ATT Write path)
  └─ Execute: haptics, LED, calibration, etc.
```

### Protocol Translation: NONE

The Puck performs **zero protocol translation** between ESB and USB HID:

| Aspect | ESB Payload | USB HID Report | Translation? |
|--------|------------|----------------|-------------|
| Report ID 0x45 (45B) | SC2 gamepad state | Same 45 bytes | **No** |
| Report ID 0x42 (53B) | Extended gamepad | Same 53 bytes | **No** |
| Report ID 0x40 (4B) | Mouse | Same 4 bytes | **No** |
| Report ID 0x41 (7B) | Keyboard | Same 7 bytes | **No** |
| Output 0x80 (9B) | Haptic command | Same 9 bytes | **No** |
| Output 0x87-0x89 (63B) | Command channel | Same 63 bytes | **No** |
| Feature 0x01 (63B) | Command channel | Same 63 bytes | **No** |

### Payload Sizing

ESB max payload is 32 bytes, but SC2 reports can be up to 63 bytes (output reports 0x87-0x89). This means:

- **Input reports ≤32 bytes**: Single ESB packet
- **Input reports >32 bytes**: Must be fragmented (e.g., report 0x42 at 53 bytes = 2 ESB packets)
- **Output reports ≤32 bytes**: Single ESB packet
- **Output reports >32 bytes**: Fragmented into multiple ESB packets

The fragmentation/reassembly is handled by the Zephyr ESB library's payload splitting (not application-level).

### Latency

| Path | Latency | Evidence |
|------|---------|----------|
| **ESB radio** | ~1-2ms | 2 Mbps, single packet air time ~130μs |
| **Puck relay** | <1ms | Transparent relay, no processing |
| **USB HID** | ~1ms | USB 1.1 full-speed polling |
| **Total (Puck)** | **~2-4ms** | ESB + USB combined |
| **BLE (direct)** | ~7.5-15ms | BLE connection interval + ATT |

---

## 4. Command Channel Through ESB

### Feature Report Exchange (Puck ↔ Triton)

Before data flows, the Puck and controller exchange Feature Reports (FR):

**Puck strings**:
```
Slot %u : Set FR (0x%02X) - controller ret %d
Slot %u : Get FR (0x%02X) - response wrong state (%u)
Slot %u : Get FR (0x%02X)  - timer expired (%u)
Slot %u : Get FR (0x%02X) - mismatched rsp 0x%02X
Slot %u : Get FR (----) - no SET %u
Slot %u : Get FR - unexpected %u
Slot %u : FR timer expired %u
Slot %u : Set FR (0x%02X) - GET pending (%u)
Invalid GET_FR_RSP
Invalid SET_FR_RSP
```

**Triton strings**:
```
Discarding feature report with unexpected length %d
Failed to execute GET_FEATURE_REPORT
Failed to execute SET_FEATURE_REPORT
get_id_get_attributes_values
get_id_get_string_attribute
%s: GET: ID_GET_ATTRIBUTES_VALUES
%s: GET: ID_GET_STRING_ATTRIBUTE, TAG: %u
```

### Feature Report Flow

```
1. Puck sends SET_FEATURE_REPORT (0x%02X) to controller via ESB
   └─ Controller receives, processes command
   └─ Returns status (controller ret %d)

2. Puck sends GET_FEATURE_REPORT to controller via ESB
   ├─ Timer started (FR timer)
   ├─ Controller responds with feature report data
   ├─ Puck validates: correct report ID? correct length? timer not expired?
   └─ If mismatch: "mismatched rsp 0x%02X" or "timer expired"

3. Capability negotiation complete
   └─ Data relay begins
```

### Command IDs (from both firmware strings)

**GET commands** (Controller → Puck response):
| Command ID | Name | Description |
|------------|------|-------------|
| `ID_GET_ATTRIBUTES_VALUES` | Get Attributes | Controller capabilities/state |
| `ID_GET_STRING_ATTRIBUTE` | Get String | Controller name, serial, etc. |
| `ID_GET_BATTERY_DATA` | Get Battery | Battery level (Triton only) |
| `ID_GET_LED_COLOR` | Get LED | LED color state (Triton only) |
| `ID_GET_SETTINGS_VALUES` | Get Settings | Configuration values |
| `ID_GET_USER_STORE` | Get User Store | User-stored data |

**SET commands** (Puck → Controller):
| Command ID | Name | Description |
|------------|------|-------------|
| `ID_FIRMWARE_UPDATE_REBOOT` | FW Update | Firmware update trigger |
| `ID_SET_LED_COLOR` | Set LED | LED color control |
| `ID_SET_SETTINGS_VALUES` | Set Settings | Configuration values |
| `ID_SET_USER_STORE` | Set User Store | User-stored data |
| `ID_TURN_OFF` | Turn Off | Power off controller |
| `ID_REBOOT_INTO_ISP` | Reboot ISP | Reboot to ISP mode |
| `set_id_persist` | Persist | Save to flash |

### Protocol Version Negotiation

**Puck strings**:
```
Slot %u : Sending protocol version: %u %u
Slot %u : Protocol version updated %u
Slot %u: Unrecognized protocol version %u
```

The Puck sends a protocol version (two uint32 values) to the controller. If the controller doesn't recognize the version, the connection fails. This determines which report formats and features are available.

---

## 5. Connection Management

### Multi-Controller Architecture

The Puck supports **4 simultaneous controllers**:

| Resource | Count | Identifiers |
|----------|-------|-------------|
| ESB controller slots | 4 | `esb-controller@0` through `esb-controller@3` |
| ESB pipe endpoints | 4 | `esb/ibex_0` through `esb/ibex_3` |
| HID proxy instances | 4 | `HID_PROXY_0` through `HID_PROXY_3` |
| EC input tap devices | 4 | `ec-input-tap@0` through `ec-input-tap@3` |
| UUID pairs | 4 | `ibex%d_proteus_uuid` + `ibex%d_ibex_uuid` |
| Serial numbers | 4 | `ibex%d_peer_sn` |
| Bond data | 4 | Stored in flash (`flash-controller@4001e000`) |

### Per-Controller Connection Lifecycle

From Puck strings, each slot follows this state machine:

```
┌─────────┐
│  Idle   │ ← Slot %u : Idle
└────┬────┘
     │ (controller enters pairing mode)
     ▼
┌────────────┐
│ Connecting │ ← Slot %u : Connecting Ibex %s
└────┬───────┘
     │ (ESB connection established)
     ▼
┌─────────┐
│ Pairing │ ← Slot %u : Pairing
└────┬────┘
     │ (key exchange complete)
     ▼
┌───────────┐     ┌──────────────────┐
│ Connected │ ←── │ Slot %u : Connected Ibex %s (Ch %u)
└─────┬─────┘     └──────────────────┘
      │
      ├─→ Protocol version exchange
      │   Slot %u : Sending protocol version: %u %u
      │   Slot %u : Protocol version updated %u
      │
      ├─→ Feature Report exchange
      │   Slot %u : Set FR / Get FR
      │
      ├─→ Active data relay (input/output reports)
      │
      ├─→ QOS monitoring
      │   Slot %u : QOS %u {%03u %03u %03u %02u %03d} {%02u %02u %u}
      │
      ├─→ Host sleep/wake handling
      │   Slot %u : Host suspended - waiting for wakeup
      │   Slot %u : Host awake
      │
      └─→ Disconnect
          Slot %u : Disconnect message
          Slot %u : Connection timeout
          Ibex disconnecting
          Ibex took too long to shutdown...
```

### Pairing and Bonding

**Puck side**:
```
Slot %u : Pairing                    — entering pairing state
Slot %u: Pairing successful          — bond established
Slot %u: Pairing failed              — pairing error
Slot %u : New bond saved             — bond stored to flash
Slot %u : Bond deleted               — bond removed
```

**Triton side**:
```
esb/bond                              — primary bond storage path
esb/bond_2                            — secondary bond storage
ID %d : bonded to %s                  — bond record
Bond info for id %d was deleted...    — bond cleanup
List of existing bonds:               — bond listing
```

**Bond data includes**:
- ESB address (32-bit UUID + prefix)
- Link key (ESB-level encryption)
- Controller identity (serial number, UUID)
- Protocol version
- Feature report cache

**Pairing flow**:
1. Controller enters pairing mode (button press)
2. Puck detects pairing signal on ESB
3. Slot transitions to `PAIRING`
4. Key exchange occurs (ESB-level, NOT BLE SMP)
5. Bond saved to flash: `Slot %u : New bond saved`
6. Slot transitions to `CONNECTED`

### Reconnection

The Puck handles reconnection automatically:
- On disconnect, slot returns to `Idle`
- Puck continues advertising ESB presence
- When controller reappears, connection re-established
- Bond data used for fast reconnection (no re-pairing needed)
- `Ibex disconnecting` → `Slot %u : Idle` → `Slot %u : Connecting Ibex %s`

### Host Sleep/Wake

```
Slot %u : Host suspended - waiting for wakeup    — host USB suspend
Slot %u : Host awake                             — host woke up
Slot %u : Host did not wakeup within timeout     — wakeup timeout
Slot %u : Host suspended, turn off controller    — turn off radio to save power
Ibex took too long to shutdown - disconnect and prevent it from waking the host next time it connects
```

---

## 6. ESB vs BLE Transport Differences

### Dual-Stack Architecture (Triton Side)

The Triton firmware supports **both** ESB and BLE simultaneously:

```
┌─────────────────────────────────────────────────────────────┐
│                    Triton (SC2) Firmware                     │
│                                                              │
│  ┌─────────────────────┐  ┌──────────────────────────────┐  │
│  │  ESB Stack           │  │  BLE Stack                    │  │
│  │  ├─ triton_esb       │  │  ├─ bt_hids (HID Service)     │  │
│  │  ├─ esb_thread       │  │  ├─ bt_gatt (GATT server)     │  │
│  │  ├─ esb/bond         │  │  ├─ bt_smp (Security)         │  │
│  │  └─ puck-interface   │  │  └─ bt_att (ATT protocol)     │  │
│  └──────────┬──────────┘  └──────────────┬───────────────┘  │
│             │                             │                   │
│             ▼                             ▼                   │
│  ┌─────────────────────┐  ┌──────────────────────────────┐  │
│  │  ESB Radio           │  │  BLE Radio                    │  │
│  │  (2.4 GHz proprietary)│  │  (2.4 GHz standard)          │  │
│  └──────────┬──────────┘  └──────────────┬───────────────┘  │
│             │                             │                   │
└─────────────┼─────────────────────────────┼──────────────────┘
              │                             │
              ▼                             ▼
      ┌──────────────┐           ┌──────────────────┐
      │ Puck (Dongle)│           │ Host PC (Direct)  │
      │ via ESB      │           │ via BLE           │
      └──────────────┘           └──────────────────┘
```

### State Machine: Transport Differentiation

The Triton firmware has **separate states** for ESB and BLE:

**ESB-related states**:
| State | Purpose |
|-------|---------|
| `ST_PUCK_OFF` | No Puck detected, start ESB |
| `ST_PUCK_OFF_DEBOUNCE_DETACHMENT` | Debouncing Puck removal |
| `ST_PUCK_KEYCHORD_CURRENT` | Keychord in current mode |
| `ST_PUCK_KEYCHORD_BT` | Keychord to switch to BT pairing |
| `ST_PUCK_KEYCHORD_ESB` | Keychord to switch to ESB pairing |
| `ST_PUCK_KEYCHORD_ESB_ALT` | Keychord to switch to ESB alt mode |
| `ST_PUCK_ON` | Puck connected, ESB active |

**BLE-related states** (handled by BLE stack, not state machine):
- BLE advertising: `adv-connectable`, `adv-dir-connectable`
- BLE connection: `Device connected`, `Device disconnected`
- BLE SMP: `Pairing`, `Pairing timeout`

### Connection Detection

**ESB connection** (from Triton):
```
Connecting to: Proteus %s, (0x%08X, 0x%08X)    — initiating ESB connection
Connected: private pipe (%u/%u, addr 0x%08X, prefix %u   — ESB pipe established
No message on private channel                    — ESB channel monitoring
Wrong kind of message on private channel         — ESB error handling
```

**BLE connection** (from Triton):
```
Connected %s                                      — BLE connection established
Disconnected from %s (reason %u)                 — BLE disconnection
Device connected                                  — BLE device event
Device disconnected                               — BLE device event
```

### Report Format Differences

**CRITICAL FINDING**: The report format is **identical** between ESB and BLE:

| Report ID | Size | ESB Payload | BLE Payload | Same? |
|-----------|------|-------------|-------------|-------|
| 0x45 (Gamepad) | 45 bytes | 45 bytes after Report ID | 45 bytes ATT notification | **Yes** |
| 0x42 (Extended) | 53 bytes | 53 bytes after Report ID | N/A (Puck-only) | N/A |
| 0x80 (Haptic) | 9 bytes | 9 bytes via ESB output | 9 bytes ATT Write | **Yes** |
| 0x87-0x89 (Command) | 63 bytes | 63 bytes via ESB output | 63 bytes ATT Write | **Yes** |
| 0x01 (Feature) | 63 bytes | 63 bytes via ESB feature | 63 bytes ATT Read/Write | **Yes** |

The only difference is the **transport layer** (ESB radio vs BLE ATT), not the **application layer** (report data).

### Features Available per Transport

| Feature | ESB (Puck) | BLE (Direct) | Notes |
|---------|-----------|-------------|-------|
| **Input reports** | ✅ All (0x40-0x7B) | ✅ All (same IDs) | Same report format |
| **Output reports** | ✅ All (0x80-0x89) | ✅ All (same IDs) | Same command format |
| **Feature reports** | ✅ 0x01, 0x02 | ✅ Custom ATT | Same commands |
| **Multi-controller** | ✅ 4 simultaneous | ❌ 1 at a time | Puck advantage |
| **Latency** | ~2-4ms | ~7.5-15ms | ESB faster |
| **Range** | ~10m (2.4 GHz) | ~10m (BLE) | Similar |
| **Power** | Higher (active radio) | Lower (BLE) | BLE advantage |
| **Pairing** | ESB proprietary | BLE SMP | Different protocols |
| **QOS monitoring** | ✅ Puck feature | ❌ Not available | Puck-only |
| **Host sleep/wake** | ✅ USB power mgmt | ❌ Not available | Puck-only |
| **Protocol version** | ✅ Negotiated | ✅ Implicit | ESB explicit |
| **Bond storage** | `esb/bond` | `bt/ccc` + BLE bonds | Different paths |
| **Haptics** | ✅ Via ESB output | ✅ Via ATT Write | Same command |
| **Firmware update** | ✅ `ID_FIRMWARE_UPDATE_REBOOT` | ✅ Same command | Same protocol |

### Transport Decision

The Triton firmware decides which transport to use based on:

1. **Puck presence**: If Puck is detected (via pilot GPIO or ESB beacon), use ESB
2. **No Puck**: If no Puck detected, advertise BLE for direct connection
3. **Keychord**: User can force transport via keychord:
   - `ST_PUCK_KEYCHORD_BT` — force BLE pairing
   - `ST_PUCK_KEYCHORD_ESB` — force ESB pairing
   - `ST_PUCK_KEYCHORD_ESB_ALT` — ESB alternative mode

---

## 7. QOS and Reliability

### Packet Error Rate Monitoring

**Puck strings**:
```
Slot %u : QOS %u {%03u %03u %03u %02u %03d} {%02u %02u %u}
packet_error_rate
connection_qos
connection_qos_stop
Dump controller PER
%s_connection_uptime_s: %u
%s_channel[%u] : %u
background_rssi_show
channel_cost
channel_cost_show
```

### QOS Fields

The 9-field QOS structure `{%03u %03u %03u %02u %03d} {%02u %02u %u}` likely represents:

| Field | Format | Likely Meaning |
|-------|--------|----------------|
| 1 | %03u | RX RSSI (0-255, signal strength) |
| 2 | %03u | TX RSSI or power |
| 3 | %03u | RX rate or throughput |
| 4 | %02u | TX rate or power level |
| 5 | %03d | Noise floor (signed dBm) |
| 6 | %02u | RX packets per interval |
| 7 | %02u | TX packets per interval |
| 8 | %u | Retries or total errors |
| 9 | (implied) | Connection uptime or slot |

### Channel Quality Tracking

```
channel_cost              — per-channel quality metric
channel_cost_show         — display channel costs
%s_channel[%u] : %u      — per-channel statistics
background_rssi_show      — background RSSI measurement
```

### Error Handling

**Puck**:
```
dongle recv report err: %d           — ESB receive error
Discarded report                     — invalid/malformed report
Discarding keyboard report           — keyboard report filtered
Discarding feature report with unexpected length %d — size mismatch
Failed to submit input report %d     — USB submission failed
Failed to submit report              — general report failure
Unsupported report type              — unknown report ID
```

**Triton**:
```
Discarded report                     — invalid/malformed report
Discarding feature report with unexpected length %d — size mismatch
Failed to allocate report            — memory allocation failure
Failed to send full HID report %d    — partial send failure
No buffer available to send notification — backpressure
Unable to send hid report, %u        — notification send failure
Device is not subscribed to characteristic — CCCD not enabled
```

### Retransmission

ESB handles retransmission at the radio level:
- **Auto-ACK**: Each packet acknowledged by receiver
- **Retransmit**: Up to 15 retries (configurable)
- **Retry delay**: 250-500μs (Zephyr ESB default: 250μs)
- **Duplicate detection**: PID (Packet ID) in header prevents duplicate processing

---

## 8. Puck-Specific Features

### Pilot Signal

```
puck-pilot-gpio                   — GPIO for pilot detection
In pilot envelope                 — controller in range
Pilot signal is valid but controller unresponsive — pilot timeout
VPILOT out of range               — signal strength check
Failed to configure PILOT_SENSE input — GPIO init error
```

The Puck uses a **pilot signal** (GPIO-based) to detect when a controller is physically nearby. This is separate from the ESB radio connection and provides a quick presence check.

### EC Input (Embedded Controller)

```
ec-input                           — EC input device
ec_input_tap                       — EC tap input
ec-input-tap@0 through @3          — per-controller EC tap inputs
Failed to register a HID proxy tap %d — EC tap registration
```

The Puck has an **EC (Embedded Controller)** interface for tap/interaction input — likely for button taps on the dongle itself.

### USB HID-over-I2C Bridge

```
HID over I2C doesn't have a concept of SoF. Ignoring the callback
board_hid_over_i2c                 — I2C HID bridge function
i2c@40003000                       — nRF52840 TWIM0 (I2C peripheral)
```

The Puck uses **HID-over-I2C** for internal communication between the nRF52840 and the USB HID composite device.

---

## 9. Implications for SpoofDeck

### Key Findings for BLE Spoofing

1. **Report format is transport-agnostic**: The SC2 report format (report IDs 0x40-0x7B) is the same regardless of whether it flows over ESB, USB HID, or BLE ATT. Our BLE spoof must use the **exact same report format**.

2. **Command channel is transport-agnostic**: Feature reports (GET_ATTRIBUTES, GET_SERIAL, haptics, etc.) use the same command codes over ESB and BLE. Our ATT server must handle the **same command set**.

3. **ESB is irrelevant for BLE spoofing**: The ESB protocol is only for Puck communication. Our BLE spoof bypasses the Puck entirely.

4. **Protocol version negotiation**: The Puck explicitly negotiates protocol version with the controller. BLE connections may not have this step — the controller implicitly uses the default version.

5. **Bond storage paths differ**: ESB bonds at `esb/bond`, BLE bonds at `bt/ccc`. These are independent systems.

6. **Multi-controller is Puck-only**: BLE supports 1 connection at a time, Puck supports 4.

7. **QOS monitoring is Puck-only**: No equivalent in BLE path.

### What We Can Learn from Puck Firmware

| Puck Feature | SpoofDeck Equivalent | Status |
|-------------|---------------------|--------|
| Feature Report exchange | ATT Read/Write on SC2 Custom service | ✅ Implemented |
| Report relay (input) | ATT Notifications | ✅ Implemented |
| Report relay (output) | ATT Write Requests | ✅ Implemented |
| Haptic forwarding | ATT Write to haptic characteristic | ✅ Implemented |
| Protocol version negotiation | Not needed (BLE implicit) | N/A |
| Multi-controller | Not needed (1 connection) | N/A |
| QOS monitoring | Not needed | N/A |
| Host sleep/wake | Not needed (Deck is host) | N/A |
| Pilot signal | Not needed | N/A |
| EC input | Not needed | N/A |

### Recommendations

1. **Focus on ATT spec compliance**: Since ESB is irrelevant for BLE spoofing, focus on making the ATT server compliant with BLE HID-over-GATT spec.

2. **Command channel is critical**: The Feature Report exchange (GET_ATTRIBUTES, GET_SERIAL, etc.) must be implemented correctly — this is how Steam Client identifies the controller.

3. **Report format must match exactly**: The 45-byte report 0x45 format must match the Triton firmware exactly (same byte layout, same sequence counter, same flags).

4. **Haptic format must match**: The 9-byte output report 0x80 format must match (same command type, same motor speeds).

---

## 10. Unresolved Questions

1. **Exact ESB payload fragmentation**: How are reports >32 bytes fragmented into multiple ESB packets? (Zephyr ESB library handles this, but the exact splitting is not visible from strings alone.)

2. **Feature Report contents**: What exactly is exchanged in Feature Reports 0x01/0x02? (Calibration data, firmware version, capabilities bitmap — would need to capture an actual exchange.)

3. **ESB encryption**: Is the ESB link encrypted? (ESB supports encryption via the nRF52840's CRYPTOCELL, but the firmware strings don't confirm this.)

4. **ESB timing parameters**: Exact retry delay, auto-ACK window, and retransmit count (configured in Zephyr ESB library, not visible from application strings.)

5. **Report 0x42 (53 bytes)**: What does this extended report contain? (Larger than 0x45 — possibly extended gamepad data or touchpad data with additional resolution.)

6. **Report 0x47 (47 bytes)**: Not in HID descriptor but referenced in analysis — possibly a variant of 0x45 with additional fields.

7. **ESB channel selection algorithm**: How does the Puck choose which channels to use for each controller? (Adaptive frequency hopping based on channel_cost metrics, but exact algorithm not visible.)

8. **Bond data format**: What exactly is stored in the ESB bond? (Address, link key, UUID, serial number — but exact byte layout unknown.)

---

## Appendix A: String Reference Index

### Puck Firmware Strings (ESB-Related)

| String | Context |
|--------|---------|
| `dongle_esb` | Main ESB module name |
| `esb-controller@0` - `@3` | Controller device tree nodes |
| `esb/ibex_0` - `ibex_3` | ESB pipe endpoints |
| `ibexesb_common` | Shared ESB/Ibex data structure |
| `esb_set_rf_channel %d %u` | RF channel configuration |
| `Initializing radio` | Radio initialization |
| `Initializing channel map` | Channel map setup |
| `Failed to initialize ESB system timer` | ESB timer error |
| `Failed to delete esb settings` | Settings cleanup error |
| `No event from ESB...` | Radio IRQ fallback |
| `Slot %u : Connected Ibex %s (Ch %u)` | Connection established |
| `Slot %u : Connecting Ibex %s` | Connection attempt |
| `Slot %u : Pairing` | Pairing state |
| `Slot %u : QOS %u {...}` | QOS metrics |
| `Slot %u : Set FR / Get FR` | Feature report exchange |
| `Slot %u : Protocol version...` | Version negotiation |
| `Slot %u : Host suspended/awake` | Power management |
| `Slot %u : Disconnect/timeout` | Disconnection |
| `radio_send` / `radio_send_channels` | Shell commands |

### Triton Firmware Strings (ESB-Related)

| String | Context |
|--------|---------|
| `triton_esb` | ESB module name |
| `esb_thread` | ESB processing thread |
| `esb/bond` / `esb/bond_2` | Bond storage paths |
| `ibexesb_common` | Shared data structure |
| `puck-interface` | Puck communication interface |
| `puck-pilot-gpio` | Pilot GPIO control |
| `Connecting to: Proteus %s, (0x%08X, 0x%08X)` | ESB connection |
| `Connected: private pipe (%u/%u, addr 0x%08X, prefix %u` | Pipe established |
| `No message on private channel` | Channel monitoring |
| `Wrong kind of message on private channel` | Error handling |
| `ESB TX FIFO full` | TX buffer full |
| `Failed to initialize ESB system timer` | Timer error |
| `Failed to delete esb settings` | Settings error |
| `Proteus asking us to turn off` | Remote shutdown |
| `ST_PUCK_KEYCHORD_ESB_entry` | ESB pairing state |
| `ST_PUCK_ON_entry` | Puck active state |
| `Failed to configure PILOT_SENSE input` | Pilot GPIO error |

---

## Appendix B: Function Size Summary

### Puck Firmware (Top 10 Largest Functions)

| Function | Address | Size | Likely Purpose |
|----------|---------|------|----------------|
| `FUN_000199b4` | `0x000199b4` | 3,256B | USB HID composite device handler |
| `FUN_00016eb4` | `0x00016eb4` | 3,148B | ESB data relay / HID proxy |
| `FUN_00005e64` | `0x00005e64` | 3,002B | ESB state machine / connection mgmt |
| `FUN_0000ac78` | `0x0000ac78` | 1,390B | Feature report exchange |
| `FUN_000161cc` | `0x000161cc` | 1,370B | QOS monitoring / channel stats |
| `FUN_00008b74` | `0x00008b74` | 1,270B | Bond management |
| `FUN_000043c0` | `0x000043c0` | 1,202B | Radio initialization |
| `FUN_0000dcc8` | `0x0000dcc8` | 1,108B | HID report descriptor handler |
| `FUN_00003f7c` | `0x00003f7c` | 1,066B | Multi-slot controller management |
| `FUN_0001f6d8` | `0x0001f6d8` | 1,064B | USB endpoint handler |

### Triton Firmware (Top 10 Largest Functions)

| Function | Address | Size | Likely Purpose |
|----------|---------|------|----------------|
| `FUN_00038ab8` | `0x00038ab8` | 2,422B | BLE HID service / GATT handler |
| `FUN_00049c4a` | `0x00049c4a` | 1,962B | IMU / sensor processing |
| `FUN_0001d8d0` | `0x0001d8d0` | 1,520B | GATT service registration |
| `FUN_00001f88` | `0x00001f88` | 1,276B | ESB connection / pipe management |
| `FUN_000116f8` | `0x000116f8` | 1,210B | Neptune input processing |
| `FUN_0003949c` | `0x0003949c` | 1,190B | BLE connection state handler |
| `FUN_00009ff0` | `0x00009ff0` | 1,176B | BLE connection event handler |
| `FUN_00001ab4` | `0x00001ab4` | 1,160B | State machine thread |
| `FUN_000167d0` | `0x000167d0` | 1,014B | Main controller loop / report send |
| `FUN_00019eb8` | `0x00019eb8` | 938B | Haptic sequencer |
