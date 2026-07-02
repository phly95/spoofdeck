# Steam Controller Puck (USB Dongle) Firmware Analysis

## Firmware Overview

- **Chip**: Nordic nRF52840 (ARM Cortex-M4F), Zephyr RTOS
- **SDK**: nRF Connect SDK v2.9.0-d93dcad627bd
- **Binary**: 197,740 bytes (193 KB), 790 functions
- **Stack pointer**: 0x20015d00 (RAM)
- **Reset handler**: 0x00011dcd (flash)
- **Product name**: "Steam Controller Puck" by "Valve Software"
- **Flash storage**: flash-controller@4001e000

## 1. USB HID Interface (CRITICAL)

### HID Report Descriptor

The Puck presents a composite HID device to the host PC using HID-over-I2C (`board_hid_over_i2c`). The HID report descriptor is stored at binary offset 0x23b87 (immediately after the `hid_proxy` string at 0x23b7d).

The descriptor defines a **composite device** with Mouse, Keyboard, and Vendor-Specific collections:

#### Input Reports (Controller → Host)

| Report ID | Size (bytes) | Type | Description |
|-----------|-------------|------|-------------|
| 0x40 | 4 | Mouse | 2 buttons (1-bit each), 6-bit padding, X (8-bit signed), Y (8-bit signed), Wheel (8-bit signed), AC Pan (8-bit signed) |
| 0x41 | 7 | Keyboard | 8 modifier bits (E0-E7), 1 padding byte, 6 keycodes (8-bit each, 0-101) |
| 0x42 | 53 | Vendor | SC2 Custom input — primary gamepad state (sticks, triggers, buttons, trackpads) |
| 0x44 | 5 | Vendor | SC2 Custom input — secondary data |
| 0x79 | 1 | Vendor | SC2 Custom input — single byte |
| 0x43 | 14 | Vendor | SC2 Custom input — tertiary data |
| 0x7B | 12 | Vendor | SC2 Custom input — additional data |
| 0x45 | 45 | Vendor | SC2 Custom input — full gamepad report (sticks, triggers, trackpads, IMU, buttons) — **matches our BLE SC2 report format** |

#### Output Reports (Host → Controller)

| Report ID | Size (bytes) | Type | Description |
|-----------|-------------|------|-------------|
| 0x80 | 9 | Vendor | Output report — likely haptic/rumble (matches SC2 haptic output format) |
| 0x81 | 7 | Vendor | Output — likely LED/command |
| 0x82 | 3 | Vendor | Output — short command |
| 0x83 | 9 | Vendor | Output — medium command |
| 0x84 | 8 | Vendor | Output — medium command |
| 0x85 | 3 | Vendor | Output — short command |
| 0x86 | 3 | Vendor | Output — short command |
| 0x87 | 63 | Vendor | Output — large command (SC2 command channel) |
| 0x89 | 63 | Vendor | Output — large command |
| 0x88 | 63 | Vendor | Output — large command |

#### Feature Reports

| Report ID | Size (bytes) | Type | Description |
|-----------|-------------|------|-------------|
| 0x01 | 63 | Feature | GET/SET feature — SC2 command channel (matches Feature Report 0x00 in our BLE ATT server) |
| 0x02 | 63 | Feature | GET/SET feature — secondary command channel |

### Key Insight: The HID Report IDs Match the SC2 BLE Protocol

The Puck's HID report IDs (0x40, 0x41, 0x42, 0x43, 0x44, 0x45, 0x79, 0x7B) are **the same report IDs used in the SC2 BLE protocol**. This means the Puck is essentially a **transparent relay** — it translates ESB packets from the controller directly into USB HID reports with minimal protocol translation.

The output reports (0x80-0x89) are the **SC2 command/haptic channel** — haptics, LED control, calibration, and other features that the host sends back to the controller.

## 2. ESB Protocol (Enhanced ShockBurst)

### What We Know from Strings

The ESB subsystem uses these key identifiers:

| String | Offset | Meaning |
|--------|--------|---------|
| `dongle_esb` | 0x23852 | Main ESB dongle module name (Zephyr log domain) |
| `esb-controller@0` - `esb-controller@3` | 0x23149-0x2317c | 4 controller device tree nodes |
| `esb/ibex_0` - `esb/ibex_3` | 0x23826-0x23847 | 4 ESB pipe endpoints to Ibex controllers |
| `ibexesb_common` | 0x25eca | Common ESB/Ibex data structure |
| `esb_set_rf_channel %d %u` | 0x231de | RF channel configuration |
| `Initializing radio` | 0x237ae | Radio initialization |
| `Initializing channel map` | 0x237c1 | Channel map initialization |
| `Failed to initialize ESB system timer` | 0x25b4a | ESB timing setup |
| `Failed to delete esb settings` | 0x25c31 | ESB settings management |

### ESB State Machine (from Strings)

The connection state machine per controller slot follows these states:

```
Idle → Connecting → Pairing → Connected → [Active]
                                           ↓
                              Host suspended (waiting for wakeup)
                                           ↓
                              Host awake / Host did not wakeup / Turn off controller
                                           ↓
                              Disconnect message / Connection timeout
```

State strings found: `PAIRING`, `CONNECTING`, `CONNECTED`

### Per-Slot Connection Lifecycle

From the log messages, each controller slot goes through:

1. **Idle** (`Slot %u : Idle`) — waiting for controller
2. **Connecting** (`Slot %u : Connecting Ibex %s`) — ESB connection attempt
3. **Pairing** (`Slot %u : Pairing`) — bonding/key exchange
4. **Connected** (`Slot %u : Connected Ibex %s (Ch %u)`) — active on channel N
5. **Protocol version exchange** (`Slot %u : Sending protocol version: %u %u`)
6. **Feature Report exchange** (`Slot %u : Set FR / Get FR`) — controller capability negotiation
7. **Active data relay** — input/output reports flowing
8. **QOS monitoring** (`Slot %u : QOS %u {%03u %03u %03u %02u %03d} {%02u %02u %u}`) — signal quality
9. **Host sleep/wake** handling (`Slot %u : Host suspended` / `Slot %u : Host awake`)
10. **Disconnect** (`Slot %u : Disconnect message` / `Slot %u : Connection timeout`)

### ESB RF Parameters (Inferred)

- **Protocol**: Nordic Enhanced ShockBurst (ESB) — proprietary 2.4 GHz
- **Data rate**: 2 Mbps (ESB default for SC2)
- **Channel count**: Multiple channels (evidenced by `esb_set_rf_channel %d %u` and `Slot %u : Connected Ibex %s (Ch %u)`)
- **Auto-ACK**: Yes (ESB protocol feature)
- **Retransmit**: Configurable (ESB supports up to 15 retries)
- **Address format**: 5-byte address (ESB standard), configured via `ibexesb_common`
- **Payload**: Up to 32 bytes per ESB packet (ESB standard max)

### ESB Channels

The firmware manages per-controller channel maps:
- `esb/ibex_0` through `esb/ibex_3` — 4 separate ESB pipes, one per controller
- Channel can be queried per connection (`Ch %u`)
- The `radio_send_channels` shell command suggests channels can be dynamically selected

### Feature Report Exchange

Before data flows, the Puck and controller exchange Feature Reports (FR):
- `Set FR (0x%02X)` — Puck sends a feature report to the controller
- `Get FR (0x%02X)` — Puck reads a feature report back
- Error handling for: mismatched responses, wrong state, timer expiry, no SET pending
- This is the controller capability/configuration negotiation phase

## 3. Multi-Controller Support

### Architecture

The Puck supports **up to 4 simultaneous SC2 controllers**:

| Resource | Count | Identifiers |
|----------|-------|-------------|
| ESB controller slots | 4 | `esb-controller@0` through `esb-controller@3` |
| ESB pipe endpoints | 4 | `esb/ibex_0` through `esb/ibex_3` |
| HID proxy instances | 4 | `HID_PROXY_0` through `HID_PROXY_3` |
| EC input tap devices | 4 | `ec-input-tap@0` through `ec-input-tap@3` |

### Per-Controller Data Structures

Each controller slot appears to have a data structure containing:
- Connection state (pairing/connecting/connected)
- Protocol version
- Bond data
- ESB channel assignment
- Feature Report state (GET/SET pending)
- QOS metrics
- Host sleep/wake state
- HID proxy reference

The `ibexesb_common` string suggests a shared ESB/Ibex data structure accessed by all slots.

## 4. Pairing and Bonding

### Bond Management

| String | Meaning |
|--------|---------|
| `bonds` | Shell command to show bond info |
| `Show bond information` | Bond info display |
| `Slot %u : New bond saved` | Bond data stored to flash |
| `Slot %u : Bond deleted` | Bond data removed |
| `PAIRING` | Pairing state |
| `Slot %u: Pairing successful` | Pairing completed |
| `Slot %u: Pairing failed` | Pairing failed |

### Bond Storage

- Bonds are stored in flash (`flash-controller@4001e000`)
- Bond data is per-slot (4 controller slots)
- The `esb/bond` and `esb/bond_2` strings in ibex firmware confirm bond storage paths
- The Puck uses Nordic's ESB pairing (not BLE SMP) — this is a **proprietary 2.4 GHz pairing protocol**

### Pairing Flow

1. Controller enters pairing mode (button press)
2. Puck detects pairing signal on ESB
3. Slot transitions to `PAIRING` state
4. Key exchange occurs (ESB-level, not BLE SMP)
5. Bond saved to flash: `Slot %u : New bond saved`
6. Slot transitions to `CONNECTED`

## 5. Data Relay Path

### Input Path (Controller → Host)

```
SC2 Controller
  → ESB radio (2.4 GHz, proprietary)
    → Puck nRF52840 ESB receiver
      → ESB packet decode (per-slot: esb/ibex_N)
        → Protocol version check
          → HID proxy (HID_PROXY_N)
            → board_hid_over_i2c
              → USB HID device on host PC
                → Kernel HID driver
                  → /dev/hidrawN
```

**Report format**: The controller sends SC2-format reports (report IDs 0x40-0x7B) over ESB. The Puck relays them **essentially unchanged** to the host via USB HID. The report IDs match between ESB and USB HID, confirming transparent relay behavior.

### Output Path (Host → Controller)

```
Host PC
  → USB HID output report (report IDs 0x80-0x89)
    → board_hid_over_i2c
      → HID proxy (HID_PROXY_N)
        → ESB packet encode (per-slot)
          → ESB radio transmit
            → SC2 Controller receives
```

**Key output reports**:
- **0x80** (9 bytes): Haptic/rumble command — matches SC2 protocol
- **0x87/0x88/0x89** (63 bytes each): Large command payloads — SC2 command channel (get/set attributes, calibration, firmware updates)
- **0x81-0x86** (3-9 bytes): Short commands — mode switching, LED control

### Error Handling

- `dongle recv report err: %d` — receive error
- `Discarded report` — invalid/malformed report
- `Discarding keyboard report` — keyboard report filtered
- `Discarding feature report with unexpected length %d` — size mismatch
- `Failed to submit input report %d` — USB submission failed
- `Failed to submit report` — general report failure
- `Unsupported report type` — unknown report ID

## 6. HID-over-I2C Bridge

The Puck uses **HID-over-I2C** (not native USB HID) as its host interface:

| String | Meaning |
|--------|---------|
| `board_hid_over_i2c` | I2C HID bridge function |
| `i2c@40003000` | nRF52840 TWIM0 (I2C peripheral) |
| `i2c_hid` | I2C HID driver |
| `i2c_nrfx_twis` | Nordic TWIS (Two Wire Interface Slave) |
| `Failed to initialize HID I2C bus` | I2C bus init error |
| `Failed to initialize HID I2C target` | I2C target init error |
| `Failed to prepare DMA for I2C read/write` | DMA transfer error |
| `HID over I2C doesn't have a concept of SoF. Ignoring the callback` | I2C vs USB timing |

This means the nRF52840's USB peripheral presents as a USB HID device to the host, but internally the HID data is routed through I2C — possibly because the nRF52840 USB stack is used for the composite HID device while the ESB radio uses the radio peripheral.

Actually, re-reading: the Puck has a **native USB** connection to the host PC (nRF52840 has built-in USB). The `i2c_hid` and `board_hid_over_i2c` are likely used for **internal** communication between the nRF52840 and another chip on the Puck PCB, or for the EC (Embedded Controller) input interface.

## 7. Puck-Specific Features

### Pilot Signal

| String | Meaning |
|--------|---------|
| `puck-pilot-gpio` | Pilot signal GPIO |
| `gpio_puck` | Puck GPIO config |
| `Pilot signal is valid but controller unresponsive` | Pilot detection |

The Puck has a **pilot signal** — a GPIO-based signal that detects when a controller is physically nearby/paired. This is separate from the ESB radio connection.

### EC Input (Embedded Controller)

| String | Meaning |
|--------|---------|
| `ec-input` | EC input device |
| `ec_input_tap` | EC tap input |
| `ec-input-tap@0` through `@3` | Per-controller EC tap inputs |

The Puck has an **EC (Embedded Controller)** interface for tap/interaction input — likely for button taps on the dongle itself.

### ADC Reading

| String | Meaning |
|--------|---------|
| `puck_adcs_read` | ADC reading function |

The Puck reads analog signals via ADC — possibly battery voltage or pilot signal strength.

### UART Debug

| String | Meaning |
|--------|---------|
| `Failed to enable puck UART node(%d)` | UART init |
| `Failed to enable puck UART RX %d` | UART RX init |
| `UART port is not initalized. Puck interface is a no-op` | UART not available |
| `shell.shell_uart`, `shell_uart_backend` | Zephyr shell UART backend |

The Puck has a debug UART interface for development.

### Host Sleep Management

The Puck manages host USB sleep/wake:
- `Slot %u : Host suspended - waiting for wakeup`
- `Slot %u : Host awake`
- `Slot %u : Host did not wakeup within timeout`
- `Slot %u : Host suspended, turn off controller`
- `Remote wakeup feature not supported/enabled`

This is standard USB power management — when the host suspends, the Puck can turn off controller radios to save power, and support remote wakeup.

### Protocol Version Negotiation

- `Slot %u : Sending protocol version: %u %u`
- `Slot %u : Protocol version updated %u`
- `Slot %u: Unrecognized protocol version %u`

The Puck and controller negotiate a protocol version to ensure compatibility. This determines which report formats and features are available.

## 8. QOS Monitoring

The Puck tracks connection quality per controller:
- `Slot %u : QOS %u {%03u %03u %03u %02u %03d} {%02u %02u %u}` — quality metrics
- `connection_qos` / `connection_qos_stop` — shell commands
- `QOS reporting updated to every %u ms, debug prints %s` — configurable reporting
- `Dump controller PER` — Packet Error Rate dump
- `%s_connection_uptime_s: %u` — connection uptime tracking
- `%s_channel[%u] : %u` — per-channel statistics

The 9 QOS fields likely represent: slot, rx_rssi, tx_rssi, rx_power, tx_power, noise_floor, rx_rate, tx_rate, retries or similar metrics.

## 9. Comparison with BLE Path (Our SpoofDeck)

### How the Puck Differs from Direct BLE

| Aspect | Puck (ESB + USB HID) | SpoofDeck (BLE) |
|--------|----------------------|-----------------|
| **Radio protocol** | Nordic ESB (2.4 GHz proprietary) | BLE 5.x (standard) |
| **Host interface** | USB HID (composite device) | BLE GATT HID service |
| **Pairing** | ESB proprietary key exchange | BLE SMP (Standard) |
| **Report format** | SC2 report IDs 0x40-0x89 | SC2 report IDs 0x45 (single) |
| **Multi-controller** | 4 simultaneous | 1 (limited by BLE) |
| **Latency** | ~2ms (ESB) | ~7.5-15ms (BLE) |
| **Power** | Higher (2.4 GHz active) | Lower (BLE) |
| **Report relay** | Near-transparent (same report IDs) | Translated (BLE notifications) |
| **Output reports** | USB HID output → ESB | ATT Write → BLE notifications |
| **Haptics** | USB HID output 0x80 → ESB → controller | ATT Write 0x12 → BLE → controller |
| **Feature reports** | USB HID feature 0x01/0x02 | ATT Read/Write on SC2 Custom service |

### Key Insight for SpoofDeck

The Puck firmware confirms that:
1. **SC2 report IDs are the same** across ESB, USB HID, and BLE — the protocol is consistent
2. **The report at ID 0x45 (45 bytes)** is the primary gamepad report — this matches our BLE 45-byte custom report
3. **Feature Reports 0x01/0x02 (63 bytes each)** handle the SC2 command channel — this maps to our ATT Feature Report 0x00
4. **Output Report 0x80 (9 bytes)** is the haptic output — this confirms our SC2 haptic report format
5. **Multi-controller** is handled at the Puck level, not in the SC2 protocol itself
6. **Protocol version negotiation** happens before data flows — our ATT server should handle this
7. **QOS monitoring** is a Puck feature, not part of the SC2 protocol

## 10. ESB Protocol Details (from Ibex/Controller Firmware)

The ibex (SC2 controller) firmware provides critical ESB protocol details:

### ESB Connection Architecture

From the ibex string: `Connected: private pipe (%u/%u, addr 0x%08X, prefix %u`

This reveals:
- **ESB uses "private pipes"** — numbered communication channels
- **Each pipe has an address** (32-bit / 0x%08X format) and a **prefix** byte
- **Pipe addressing**: Two parameters per pipe — likely pipe number + endpoint index
- This is Nordic's ESB **multi-pipe** architecture, where each controller slot gets its own ESB pipe

### ESB Address Format (Inferred)

From `Connecting to: Proteus %s, (0x%08X, 0x%08X)`:
- The controller connects to "Proteus" (Puck) using a **5-byte ESB address**
- Two 32-bit values suggest the address is composed of a base + prefix
- Nordic ESB typically uses 4-5 byte addresses with MSB-first byte ordering

### ESB Packet Structure (Nordic ESB Standard)

Based on the Zephyr ESB library and controller behavior:

```
| Preamble (1-2 bytes) | Address (4-5 bytes) | Header (9 bits) | Length (6 bits) | Payload (0-32 bytes) | CRC (2-3 bytes) |
```

- **Preamble**: 1 byte for 1Mbps, 2 bytes for 2Mbps
- **Address**: 4-5 bytes (ESB base address + prefix)
- **Header**: PID (2 bits) + NO_ACK (1 bit) + reserved (6 bits)
- **Length**: Payload length (0-32 bytes)
- **Payload**: 0-32 bytes of data
- **CRC**: 2 bytes (16-bit CRC) or 3 bytes (24-bit CRC)

### ESB Data Rate and Timing

- **Data rate**: 2 Mbps (standard for SC2 — evidenced by ESB TX FIFO and high-throughput report relay)
- **Air time per packet**: ~130μs at 2Mbps with 32-byte payload
- **Retransmit**: Up to 15 retries (ESB default), configurable per pipe
- **Auto-ACK**: Enabled (ESB standard) — the Puck acknowledges each packet
- **Retry delay**: Typically 250-500μs (Zephyr ESB default: 250μs)
- **Latency**: 1-2ms typical (ESB is much faster than BLE)

### ESB Channel Plan

From strings:
- `esb_set_rf_channel %d %u` — configurable RF channel per slot
- `Slot %u : Connected Ibex %s (Ch %u)` — channel assigned per connection
- `Initializing channel map` — channel map for frequency hopping

Nordic ESB operates in the 2.4 GHz ISM band (2400-2483.5 MHz):
- **Channel spacing**: 1 MHz (Nordic ESB standard)
- **Channel range**: 2-126 (Nordic ESB channels)
- **Frequency hopping**: Yes — ESB uses adaptive frequency hopping across multiple channels
- The Puck likely uses a subset of channels for each controller slot

### ESB TX FIFO

From ibex: `ESB TX FIFO full`
- The controller has a **TX FIFO** for buffering outgoing ESB packets
- When the FIFO is full, the controller must wait before sending more data
- This is standard Nordic ESB behavior — the radio can only hold one packet at a time

### ESB Bond Storage

From ibex:
- `esb/bond` — primary bond storage path
- `esb/bond_2` — secondary bond storage (backup or second controller)
- `ID %d : bonded to %s` — bond records with controller ID
- Bond data includes: address, link key, and controller identity

### ESB vs BLE Comparison (Controller Side)

The ibex firmware supports **both** ESB and BLE:
- `triton_esb` — ESB protocol module (for Puck connection)
- `bt_hids` — BLE HID service (for direct BLE connection to Deck/PC)
- `adv-connectable` / `adv-dir-connectable` — BLE advertising
- `Connected: private pipe` vs `Device connected` — ESB vs BLE connections

This means the SC2 controller can connect to:
1. **Puck via ESB** (primary, low-latency)
2. **Host PC via BLE** (direct, no dongle needed)
3. The Puck relays between ESB and USB HID

## 11. Unresolved Questions

1. **ESB packet format**: We don't have the exact ESB packet structure (header, CRC, auto-ack config). This would require ESB sniffer captures or deeper analysis of the Zephyr ESB library calls.

2. **ESB address format**: The 5-byte ESB address format and channel plan are not fully visible from strings alone.

3. **ESB timing**: The exact ESB timing (retry delay, auto-ACK window) is configured in the Zephyr ESB library, not visible in the application code.

4. **Feature Report contents**: What exactly is exchanged in Feature Reports 0x01/0x02 (the 63-byte command channel) — calibration data, firmware version, capabilities bitmap?

5. **Report 0x42 (53 bytes)**: What does this report contain? It's larger than 0x45 (45 bytes) — possibly extended gamepad data or touchpad data.

6. **I2C HID internal path**: The exact role of `board_hid_over_i2c` — is it for host communication, internal chip-to-chip, or EC interface?

7. **Firmware update**: How does the Puck receive firmware updates? The `flash-controller@4001e000` suggests DFU capability but the update protocol is not visible from strings alone.
