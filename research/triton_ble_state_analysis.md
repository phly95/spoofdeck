# SC2/Triton BLE Controller Firmware Analysis

**Firmware**: `ibex_firmware.bin` (350,528 bytes)  
**Platform**: Nordic nRF52840 (ARM Cortex-M4F)  
**RTOS**: Zephyr OS v3.7.99-af30fca7cecd  
**SDK**: nRF Connect SDK v2.9.0-d93dcad627bd  
**BLE Stack**: Nordic SoftDevice Controller (not Zephyr HCI)  
**Decompiler**: Ghidra 11.3.1 — 2,027 functions, 73,705 lines of pseudocode  

> **Note**: All function names are mangled (`FUN_XXXXXXXX`) since this is a raw firmware binary without debug symbols. Analysis is based on string cross-references, UUID values, and code pattern matching.

---

## 1. State Machine (`controller_state_machine_thread`)

The firmware uses **Zephyr's SMF (State Machine Framework)** (`smf_set_state` string found at runtime). The main thread is named `controller_state_machine_thread` (string at `0x48d9f`).

### Complete State Diagram

```
                            ┌──────────────┐
                            │ ST_INITIAL   │
                            └──────┬───────┘
                                   │
                    ┌──────────────┼──────────────┐
                    ▼              ▼               ▼
            ┌──────────┐  ┌──────────┐  ┌──────────────────┐
            │ST_USB_*  │  │ST_PUCK_* │  │ST_BATTERY_*      │
            └────┬─────┘  └────┬─────┘  └────┬─────────────┘
                 │              │              │
                 ▼              ▼              ▼
            ┌──────────┐  ┌──────────┐  ┌──────────────────┐
            │ST_SHUTDOWN│  │ST_REBOOT │  │(battery keychord)│
            └──────────┘  └──────────┘  └──────────────────┘
```

### All States (25 total)

| State | String Address | Entry Action |
|-------|---------------|--------------|
| **ST_INITIAL** | `0x48b19` | Boot initialization, BLE stack init |
| **ST_USB_WAIT_FOR_ENUMERATION** | `0x48b2a` | Wait for USB host enumeration |
| **ST_USB_DATA** | `0x48b4c` | USB HID data streaming active |
| **ST_USB_SUSPENDED** | `0x48b5e` | USB suspended (host sleep) |
| **ST_USB_WAIT_FOR_WAKEUP** | `0x48b75` | USB waiting for wakeup signal |
| **ST_USB_WIRELESS_ON** | `0x48b92` | USB connected + wireless enabled |
| **ST_USB_WIRELESS_OFF** | `0x48bab` | USB connected + wireless disabled |
| **ST_PUCK_OFF** | `0x48bc5` | Puck (wireless dongle) disconnected |
| **ST_PUCK_OFF_DEBOUNCE_DETACHMENT** | `0x48bd7` | Debouncing puck detach event |
| **ST_PUCK_KEYCHORD_CURRENT** | `0x48bfd` | Puck keychord (current mode) |
| **ST_PUCK_KEYCHORD_BT** | `0x48c1c` | Puck keychord (BT pairing) |
| **ST_PUCK_KEYCHORD_ESB** | `0x48c36` | Puck keychord (ESB mode) |
| **ST_PUCK_KEYCHORD_ESB_ALT** | `0x48c51` | Puck keychord (ESB alt mode) |
| **ST_PUCK_ON** | `0x48c70` | Puck connected, wireless active |
| **ST_BATTERY** | `0x48d00` | Battery monitoring state |
| **ST_BATTERY_KEYCHORD_CURRENT** | `0x48c81` | Battery keychord (current mode) |
| **ST_BATTERY_KEYCHORD_BT** | `0x48ca3` | Battery keychord (BT pairing) |
| **ST_BATTERY_KEYCHORD_ESB** | `0x48cc0` | Battery keychord (ESB mode) |
| **ST_BATTERY_KEYCHORD_ESB_ALT** | `0x48cde` | Battery keychord (ESB alt mode) |
| **ST_SHUTDOWN** | `0x48d11` | Normal shutdown |
| **ST_SHUTDOWN_SILENT** | `0x48d23` | Silent shutdown (no LED) |
| **ST_SHUTDOWN_LOW_BATT** | `0x48d3c` | Low battery forced shutdown |
| **ST_SHUTDOWN_KEYLOCK_ACTIVE** | `0x48d57` | Shutdown with keylock override |
| **ST_REBOOT** | `0x48d78` | Normal reboot |
| **ST_REBOOT_SILENT** | `0x48d88` | Silent reboot |

### State Transitions (Inferred from Strings and Code)

```
ST_INITIAL
  ├─→ ST_USB_WAIT_FOR_ENUMERATION   (USB cable inserted)
  ├─→ ST_PUCK_OFF                   (No USB, start wireless)
  └─→ ST_BATTERY                    (Battery check at boot)

ST_PUCK_OFF
  ├─→ ST_PUCK_ON                    (Puck/dongle detected)
  ├─→ ST_PUCK_OFF_DEBOUNCE_DETACHMENT → ST_PUCK_OFF  (puck removed)
  ├─→ ST_PUCK_KEYCHORD_BT           (BT pairing keychord)
  ├─→ ST_PUCK_KEYCHORD_ESB          (ESB pairing keychord)
  └─→ ST_SHUTDOWN_LOW_BATT          (low battery)

ST_PUCK_ON
  ├─→ ST_PUCK_OFF                   (puck disconnected)
  └─→ ST_SHUTDOWN                   (power off)

ST_USB_WAIT_FOR_ENUMERATION
  ├─→ ST_USB_DATA                   (enumerated successfully)
  ├─→ ST_USB_WIRELESS_ON            (USB + wireless)
  └─→ ST_USB_WIRELESS_OFF           (USB only)

ST_USB_DATA
  ├─→ ST_USB_SUSPENDED              (host suspend)
  ├─→ ST_USB_WAIT_FOR_WAKEUP        (host sleep)
  └─→ ST_SHUTDOWN                   (power off while USB)

ST_BATTERY
  ├─→ ST_BATTERY_KEYCHORD_BT        (BT pairing from battery)
  ├─→ ST_BATTERY_KEYCHORD_ESB       (ESB pairing from battery)
  └─→ ST_SHUTDOWN_LOW_BATT          (critical battery)

ST_SHUTDOWN / ST_SHUTDOWN_LOW_BATT / ST_SHUTDOWN_SILENT / ST_SHUTDOWN_KEYLOCK_ACTIVE
  └─→ (power off / MCU reset)

ST_REBOOT / ST_REBOOT_SILENT
  └─→ (MCU reset → ST_INITIAL)
```

### State Machine Mechanism
- Uses `smf_set_state()` for transitions (string at runtime)
- Each state has an `_entry` function (logged when entering state)
- State table is located at approximately `0x53e4c` in firmware data section
- State entry functions are Thumb-mode code at addresses like `0x2b8ac` (ST_PUCK_OFF), `0x2c180` (ST_BATTERY_KEYCHORD_BT)
- States are logged via `failed to process state machine (%d)` on error

---

## 2. BLE Initialization Sequence

### Stack Architecture
```
┌─────────────────────────────────────────────────────┐
│ Application Layer (controller_state_machine_thread) │
├─────────────────────────────────────────────────────┤
│ Zephyr BLE Host (bt_gatt, bt_hids, bt_smp, bt_att) │
│   - bt_hids (HID Service)                           │
│   - bt_gatt_pool (attribute pool)                   │
│   - bt_gatt (GATT server)                           │
│   - bt_att (ATT protocol)                           │
│   - bt_smp (Security Manager)                       │
├─────────────────────────────────────────────────────┤
│ Nordic SoftDevice Controller                        │
│   - HCI driver (bt_hci)                             │
│   - Link layer                                      │
│   - Physical layer (2.4 GHz)                        │
└─────────────────────────────────────────────────────┘
```

### Initialization Strings (Order of Operations)

From firmware strings, the init sequence:
1. `*** Booting My Application v0.0.0-none ***`
2. `*** Using nRF Connect SDK v2.9.0-d93dcad627bd ***`
3. `*** Using Zephyr OS v3.7.99-af30fca7cecd ***`
4. `SoftDevice Controller build revision:` — SDC initialized
5. `HCI driver open failed` / `HCI driver close failed` — HCI transport to SDC
6. `Failed to set Bluetooth device name: %s` — Set device name
7. `HID report descriptor size: %zu` — HID descriptor loaded
8. `HIDS initialization failed (err %d)` — HIDS service registered
9. `controller_state_machine_thread` — Main thread starts
10. `Enable slot 0` / `Enable slot 1` — Advertising slots enabled

### Key Initialization Functions
| Function | Size | Evidence | Role |
|----------|------|----------|------|
| `FUN_0001d8d0` | 1520 | Contains 0x1812, 0x2a4d, 0x2a4e, 0x1800, 0x1801, 0x2a33, 0x2a4a, 0x2a4b, 0x2a4c | **GATT service registration** — registers HID service + GAP + GATT |
| `FUN_0001ce7c` | 306 | Called by FUN_0001d8d0, creates entries with type 0x10000 | **Register primary service** (bt_gatt_pool) |
| `FUN_0001cef4` | — | Called by FUN_0001d8d0 with UUID values | **Register characteristics** |
| `FUN_0001cff0` | — | Called by FUN_0001d8d0 after characteristics | **Register descriptors** (CCCD etc.) |
| `FUN_000246b0` | 344 | Contains PrimaryService + SecondaryService UUIDs | **Service discovery helpers** |
| `FUN_00024eb0` | 234 | Contains PrimaryService + SecondaryService UUIDs | **Service discovery helpers** |
| `FUN_00025260` | 188 | Contains PrimaryService UUID | **Service discovery** |

---

## 3. GATT Services and Characteristics

### Service Registration in FUN_0001d8d0

The function `FUN_0001d8d0` (size 1520) is the master GATT service registration function. It constructs the complete GATT database by calling helper functions with specific BLE UUIDs:

#### GAP Service (0x1800)
```c
// FUN_0001d8d0 creates:
local_30 = param_1 + 0x81;           // Device Name attribute
local_2c = 0x40000;                   // Properties (Read)
// UUID 0x2a4a = HID Information
// UUID 0x2a4c = HID Control Point
```

#### HID Service (0x1812)
The HID service registration at `FUN_0001d8d0` line ~50:
```c
local_3c = (undefined1 *)((uint)local_3c & 0xffffff00);  // UUID = 0x1812
FUN_0001ce7c(param_1, &local_3c);  // Register primary service
```

**HID Report Characteristics (up to 6 input reports):**
```c
// Loop: uVar11 = min(*(byte*)(param_1 + 0x46), 6)  — max 6 reports
for (uVar16 = 0; uVar16 < uVar11; uVar16++) {
    local_3e = 0x2a4d;    // UUID: HID Report Characteristic
    local_2c = uVar17 << 0x10;  // Properties from config
    FUN_0001cef4(param_1, 0x12, &local_3c);  // Register characteristic
    // Register CCCD for each report
    FUN_0001d09c(param_1, piVar8, uVar17 | uVar17 << 1);  // CCCD descriptor
    // Register Report Reference descriptor
    local_3e = 0x2908;    // UUID: Report Reference Descriptor
    FUN_0001cff0(param_1, &local_3c);  // Register descriptor
}
```

**HID Report Map (0x2a4b):**
```c
local_3e = 0x2a4b;       // UUID: Report Map
local_2c = 0x40000;      // Properties: Read
local_30 = param_1 + 0x7c;  // Report map data pointer
FUN_0001cef4(param_1, 2, &local_3c);
```

**HID Information (0x2a4a):**
```c
local_3e = 0x2a4a;       // UUID: HID Information
local_30 = param_1 + 0x81;  // bcdHID, bCountryCode, Flags
local_2c = 0x40000;      // Properties: Read
FUN_0001cef4(param_1, 2, &local_3c);
```

**Protocol Mode (0x2a4e):**
```c
local_3e = 0x2a4e;       // UUID: Protocol Mode
local_2c = 0x80000;      // Properties: Read + Write Without Response
FUN_0001cef4(param_1, 4);  // Register with Write
```

**Boot Keyboard Input Report (0x2a33) — optional:**
```c
if (*(char *)(param_2 + 0xdc) != '\0') {
    local_3e = 0x2a33;   // UUID: Boot Keyboard Input Report
    local_2c = 0x40000;  // Properties: Read (+ Notify via CCCD)
    FUN_0001cef4(param_1, 0x12, &local_3c);  // Register with CCCD
    FUN_0001d09c(param_1, piVar8, 0xc);      // CCCD descriptor
}
```

**Consumer Control (0x2a22) — optional:**
```c
if (*(char *)((int)param_2 + 0x1b9) != '\0') {
    local_3e = 0x2a22;   // UUID: Consumer Control
    local_2c = 0x40000;  // Properties: Read
    FUN_0001cef4(param_1, 0x12, &local_3c);  // Register with CCCD
    FUN_0001d09c(param_1, piVar8, 0xc);      // CCCD descriptor
    // Also register Report Reference (0x2a32)
    local_3e = 0x2a32;   // UUID: Report Reference
    FUN_0001cef4(param_1, 0xe, &local_3c);  // Read descriptor
}
```

#### Battery Service (0x180F) — separate characteristic
```c
// Battery Level Characteristic (0x2a19)
// Referenced via "BAS Notifications %s" string
// Config: CONFIG_BT_SETTINGS_CCC_STORE_MAX
```

#### Device Information Service (0x180A) — stored in settings
From strings: `Failed to read device name from storage`, `Failed to read firmware revision from storage`, `Failed to read manufacturer from storage`, `Failed to read model from storage`, `Failed to read serial number from storage`, `Failed to read software revision from storage`

### Service Registration Order
1. **Primary Service Declaration** (0x2800) for each service
2. **Characteristics** with their declarations (0x2803)
3. **Descriptors** (CCCD 0x2902, Report Reference 0x2908, etc.)
4. Each attribute registered via `bt_gatt_pool` functions

---

## 4. CCCD / Notification Logic

### CCCD Write Handling

Three CCCD handler functions identified:

#### `FUN_00026894` (size 226) — CCCD Write Handler 1
```c
// Checks: FUN_0003f76c (verify connection state)
// Checks: param_1 + 0xd == 0x07 (ATT opcode check: Write Request = 0x12, but 0x07 = Handle Value Confirmation?)
// Looks up characteristic via FUN_000261ec
// If CCCD write (param_1 != 0): sets *(param_3 + 0x16) = 1 (notifications enabled)
// Calls FUN_000267b0 to process CCCD value
// If CCCD clear (param_1 == 0): sets *(param_3 + 0x16) = 0 (notifications disabled)
// UUID 0x2902 confirmed as CCCD
```

#### `FUN_00026bb0` (size 218) — CCCD Write Handler 2
```c
// Similar to FUN_00026894 but for a different characteristic set
// Checks param_1 + 0xd == 0x07
// Calls FUN_00026b00 for CCCD processing
// UUID 0x2902 confirmed as CCCD
```

#### `FUN_0003fc3e` (size 264) — CCCD Value Check / Notification Gate
```c
// This is the notification subscription check function
// Walks the GATT database looking for CCCD (0x2902) descriptors
// For each characteristic: checks if CCCD value is non-zero
// Returns: (param_3 & *(ushort*)(puVar3 + 8)) != 0
// This means: "Is this notification enabled for the given subscription type?"
// UUID chain: 0x2803 (CharDecl) → 0x2902 (CCCD) → 0x2800/0x2801 (Service)
```

### Notification Trigger Mechanism

Based on firmware strings:
- **`No buffer available to send notification`** — Flow control exists, notifications can be dropped
- **`Unable to send hid report, %u`** — Report sending can fail (returns error code)
- **`Failed to send full HID report %d`** — Large reports can fail to send completely
- **`Device is not subscribed to characteristic`** — Checks CCCD before sending
- **`BAS Notifications %s`** — Battery service uses notifications (enable/disable logged)

From code analysis:
- `FUN_0003fc3e` acts as a **notification gate** — before sending any notification, the firmware checks if the host has subscribed (CCCD value != 0)
- Notifications are triggered by events (button presses, IMU data, etc.), NOT by a fixed timer
- The notification path: Event → Check CCCD (FUN_0003fc3e) → Allocate buffer → Send ATT Notification

### Notification Flow
```
1. Input event occurs (button, stick, trackpad, IMU)
2. Firmware checks: FUN_0003fc3e(conn, char, subscription_type)
   → Walks GATT DB to find CCCD for this characteristic
   → Checks if CCCD value & subscription_mask != 0
3. If subscribed:
   a. Allocate buffer: "Failed to allocate report" (on failure)
   b. Build ATT Handle Value Notification (0x1B)
   c. Send: "Unable to send hid report, %u" (on failure)
   d. Flow control: "No buffer available to send notification" (on backpressure)
4. If NOT subscribed:
   → "Device is not subscribed to characteristic" → skip
```

---

## 5. MTU and Data Length

### MTU
- **`ATT MTU exceeded, max %u, wanted %zu`** — The controller enforces an MTU limit
- **`No ATT channel for MTU %zu`** — ATT channel allocation depends on negotiated MTU
- **`Report map size exceeds max ATT attribute length`** — Report Map is limited by MTU
- **`Too small ATT PDU received`** — Minimum PDU validation
- The controller uses Zephyr's default ATT MTU handling (no custom MTU override found in strings)
- **Expected MTU**: 23 (default) or negotiated up to 517 (Zephyr default max)

### Data Length Extension (DLE)
- **`DLE support: %s`** — DLE is logged during connection setup
- **`Failed to read DLE max data len`** — DLE negotiation attempted
- **`Failed to set data len (%d)`** — DLE configuration
- **`ACL data length mismatch (%u != %u)`** — DLE enforcement
- DLE is supported and actively used

### PHY
- **`2M PHY support: %s`** — Controller checks for 2M PHY support
- **`BLE PHY update`** / **`Tx PHY: %s`** / **`Rx PHY: %s`** — PHY negotiation logged
- **`Failed LE Set PHY (%d)`** — PHY switching attempted
- Controller supports 1M and 2M PHY (likely negotiates 2M for throughput)

---

## 6. Advertising Configuration

### Advertising Slots
- **`Enable slot 0`** / **`Enable slot 1`** — Two advertising slots used
- **`Advertising (%s): id %d`** — Named advertising sets with IDs
- **`Advertising: %d`** — Advertising state logged (probably start/stop status)

### Advertising Types
- **`adv-connectable`** — Connectable undirected advertising (primary)
- **`adv-dir-connectable`** — Connectable directed advertising (reconnection)
- **`Advertising timeout`** — Advertising has a timeout (likely for directed ads)

### Advertising Data
From the strings and GATT registration:
- **Device Name**: `"Steam Deck Controller"` (string at `0x48b28`) — stored in settings, can be read from storage
- **Short Name**: `"Steam Ctrl (BT) %s"` (string at `0x492d6`) — `%s` filled with MAC suffix
- **Appearance**: Likely 0x03C4 (Gamepad) based on HID usage
- **Flags**: LE General Discoverable + BR/EDR Not Supported
- **Service UUIDs**: HID Service (0x1812), Battery Service (0x180F)

### Advertising Lifecycle
```
1. ST_INITIAL → Enable slot 0 + slot 1
2. Bond updated - start advertising (new bond created)
3. Bond updated - restart advertising (bond changed)
4. Advertising timeout (directed ad timeout → switch to undirected)
5. Connected → Stop advertising
6. Disconnected → Restart advertising
7. "Controller cannot resume connectable advertising (%d)" — Error recovery
```

### Scan Response
- **`Cannot get scan response data: %s`** — Scan response data is used
- Likely contains full device name + additional service UUIDs

---

## 7. Connection Management

### Connection Events
- **`Connected %s`** — Connection established (logged with address)
- **`Disconnected from %s (reason %u)`** — Disconnection with HCI reason code
- **`Lost connection`** — Unexpected disconnection (link supervision timeout)
- **`Connection event trigger failed`** — BLE event processing failure

### Connection Parameters
- **`BLE connection parameter update`** — Parameters logged:
  ```
  connection interval: %u
  connection latency: %u
  connection timeout: %u
  ```
- **`Suboptimal connection interval`** — Firmware detects non-ideal intervals
- **`BLE connection parameter update request`** — Firmware requests parameter update
- **`Suboptimal connection interval requested`** — Requested interval is suboptimal
- **`Send auto LE param update failed (err %d)`** — Auto-update after connection
- **`Send LE param update failed (err %d)`** — Manual parameter update

### Connection Lifecycle
```
1. Advertising → Host scans → Connects
2. "Connected %s" → Notify HIDS about connection: "Failed to notify HIDS about connection %d"
3. SMP Pairing: "Pairing" → "Pairing timeout" (if no response)
4. Connection parameter negotiation (auto LE param update)
5. PHY negotiation: "BLE PHY update" → "Tx PHY: %s" / "Rx PHY: %s"
6. DLE negotiation: "DLE support: %s" → "Failed to set data len (%d)"
7. HID notifications start flowing
8. Disconnection: "Disconnected from %s (reason %u)" or "Lost connection"
9. "Failed to notify HIDS about disconnection %d" → Restart advertising
```

### Pairing and Bonding
- **`Pairing`** / **`Pairing timeout`** — Standard pairing with timeout
- **`Bond info for id %d was deleted. Resetting id %d`** — Bond management
- **`Bond updated - ignoring event`** — Duplicate bond events filtered
- **`Bond updated - start advertising`** / **`Bond updated - restart advertising`** — Bond triggers re-advertising
- **`Failed to save keys (err %d)`** — Key storage errors
- **`SMP does not allow a pairing failure at this point. Known issue. Disconnecting instead.`** — Known SMP limitation
- **`SC Pair Only Mode selected but LE SC not supported`** — Secure Connections fallback
- **`Refusing new pairing. The old bond has more trust.`** — Trust level enforcement
- **`bt/ccc`** — CCC values stored in settings
- **`esb/bond`** / **`esb/bond_2`** — ESB (Enhanced ShockBurst) bond storage for wireless dongle

### Security
- **`Failed to set required security level`** — Security level enforcement
- **`Failed to set security for bonded peer (%d)`** — Bonded peer security setup
- **`No change to encryption state (encrypt 0x%02x)`** — Encryption monitoring
- **`Calculate LTK failed`** / **`Calculate local DHKey check failed`** / **`Calculate remote DHKey check failed`** — LE Secure Connections crypto

---

## 8. HID Report System

### Report Types
From `FUN_0001d8d0`, the HID service supports:
- **Input Reports** (up to 6): Registered with UUID 0x2a4d, each with CCCD + Report Reference
- **Output Reports**: Via HID Control Point (0x2a4c) and separate output characteristics
- **Feature Reports**: Via special handling — `Discarding feature report with unexpected length %d`

### Report Flow
```
1. Input event (button/stick/trackpad/IMU)
2. Format into HID report (matched to Report Map descriptor)
3. Check subscription: FUN_0003fc3e
4. Send ATT notification
5. "Unable to send hid report, %u" — on failure
6. "Failed to send full HID report %d" — on partial failure
```

### HID Report Descriptor
- **`HID report descriptor size: %zu`** — Descriptor size logged at registration
- **`Report map size exceeds max ATT attribute length`** — Descriptor must fit in ATT MTU
- Report Map stored at `param_1 + 0x7c` in the GATT context structure
- The Report Map is read by the host during characteristic discovery

### Custom HID Reports
- **`hid_custom`** — Custom HID report channel (separate from standard HID)
- **`hid_stream`** — Streaming HID data (possibly for high-rate input like gyro/trackpad)

---

## 9. Input System

### Neptune Controller Interface
- **`ibex_input`** — Input processing thread/module name
- **`HID_0`** — USB HID device name (Neptune controller via USB)
- **`Cannot get USB HID 0 Device`** — USB HID device access
- **`neptune_usb`** — Neptune USB interface

### Input Processing
- Input comes from Neptune controller via USB HID (`/dev/hidraw3` on host)
- The firmware reads 64-byte Neptune HID reports
- Reports are mapped to SC2 BLE HID format
- **`Discarded report`** — Invalid/malformed reports dropped
- **`Discarding feature report with unexpected length %d`** — Feature report validation

---

## 10. Haptic System

### Haptic Architecture
- **`haptic_script`** — Named haptic script sequences
- **`haptics_sequencer`** — Haptic sequencer module
- **`haptics-sequencer-gri-v3`** — Grip haptic sequencer
- **`haptics-sequencer-touchpad`** — Touchpad haptic sequencer
- **`user/haptic_boot_level`** — Boot-time haptic level setting
- **`settings/haptics/haptic_master_gain_db`** — Master gain control
- **`settings/haptics/enabled`** — Haptic enable/disable
- **`settings/haptics/amplifier_mode`** — Amplifier configuration

### Haptic Settings (stored in flash)
```
settings/haptics/haptic_master_gain_db  — Gain in dB
settings/haptics/enabled               — Enable/disable
settings/haptics/amplifier_mode        — Amplifier mode
user/haptic_boot_level                 — Boot level
```

### Grip Haptics
- **`Left lower grip`** / **`Left upper grip`** — Grip motor control
- **`R_LOWER_GRIP`** / **`R_UPPER_GRIP`** — Right grip motor references
- **`grip de-touch threshold`** / **`grip touch threshold`** — Touch detection thresholds

### Haptic Trigger
- **`Haptic script ID: %d gain %d`** — Script selection with gain
- **`Haptics script already active - ignoring new script`** — Only one script at a time
- **`sequence init: %d`** — Sequence initialization
- **`Inappropriate trigger (%d/%d), active stream(s): %d`** — Trigger validation

---

## 11. ESB (Enhanced ShockBurst) — Wireless Dongle Protocol

The SC2 has a secondary wireless protocol for the Steam Wireless Receiver (dongle):

- **`esb_thread`** — Dedicated ESB processing thread
- **`esb/bond`** / **`esb/bond_2`** — ESB bond storage
- **`puck-interface`** — Puck (dongle) communication interface
- **`puck-pilot-gpio`** — Puck GPIO control
- **`Connecting to: Proteus %s, (0x%08X, 0x%08X)`** — ESB connection to dongle
- **`Connected: private pipe (%u/%u, addr 0x%08X, prefix %u`** — ESB pipe setup
- **`No message on private channel`** — ESB channel monitoring

The ESB protocol runs alongside BLE — the controller can simultaneously:
1. Act as BLE peripheral (connected to host PC)
2. Communicate with Steam Wireless Receiver via ESB (2.4 GHz proprietary)

---

## 12. USB Mode

When connected via USB:
- **`USB connected operation`** — USB mode active
- **`USB device support already enabled`** — Single USB initialization
- **`Failed to enable USB`** — USB initialization error
- **`Cannot get USB HID 0 Device`** — USB HID device access
- **`neptune_usb`** — Neptune USB interface access

USB states:
- `ST_USB_WAIT_FOR_ENUMERATION` → `ST_USB_DATA` (enumerated)
- `ST_USB_SUSPENDED` ↔ `ST_USB_WAIT_FOR_WAKEUP` (power management)
- `ST_USB_WIRELESS_ON` / `ST_USB_WIRELESS_OFF` (USB + wireless combo)

---

## 13. RGB LED System

- **`rgbled`** — RGB LED module
- **`rgbled_test_thread`** — LED test thread
- **`pwmrgbleds`** — PWM-controlled RGB LEDs
- **`pwm_nrfx`** — nRF PWM driver for LEDs

---

## 14. Key Findings vs Expectations

### Matches Expectations
1. **GATT services**: HID (0x1812) + Battery (0x180F) + Device Info (0x180A) — matches SC2 protocol spec
2. **CCCD handling**: Standard Zephyr bt_hids CCCD management
3. **Report format**: Up to 6 input reports with Report Reference descriptors
4. **BLE advertising**: Connectable + directed advertising with timeout
5. **SMP pairing**: Standard BLE pairing with bond storage

### Surprising Findings
1. **ESB (Enhanced ShockBurst)**: The controller has a complete secondary wireless protocol for the Steam Wireless Receiver. This is a proprietary 2.4 GHz protocol separate from BLE.
2. **State machine complexity**: 25 states covering USB/Puck/ESB/Battery/Shutdown scenarios — far more complex than expected for a simple HID gamepad.
3. **Two advertising slots**: The controller uses two advertising slots — one for BLE, one likely for directed reconnection.
4. **Grip haptics**: The controller has dedicated grip motors (left upper/lower, right upper/lower) with touch detection.
5. **Haptic scripts**: The haptic system uses named script sequences with gain control, not just simple rumble commands.
6. **2M PHY support**: The controller supports and likely negotiates 2M PHY for higher throughput.
7. **`smf_set_state`**: Uses Zephyr's State Machine Framework (SMF), not a hand-rolled state machine.
8. **`controller_state_machine_thread`**: The state machine runs in its own dedicated thread, not the main thread.
9. **Consumer Control (0x2a22)**: Optional consumer control characteristic for media keys.
10. **Boot Keyboard Input (0x2a33)**: Optional boot protocol support.

---

## 15. Function Address Summary

### Core BLE Functions
| Address | Size | Function |
|---------|------|----------|
| `0x0001d8d0` | 1520 | GATT service registration (HID+GAP+GATT+BAS+DIS) |
| `0x0001ce7c` | 306 | Register primary service (bt_gatt_pool) |
| `0x0001cef4` | — | Register characteristic |
| `0x0001cff0` | — | Register descriptor |
| `0x0001d09c` | — | Register CCCD descriptor |
| `0x00026894` | 226 | CCCD write handler 1 |
| `0x00026bb0` | 218 | CCCD write handler 2 |
| `0x0003fc3e` | 264 | Notification subscription check |
| `0x0001d8d0` | 1520 | GATT database builder |

### State Machine Functions
| Address | Size | Function |
|---------|------|----------|
| `0x00028ce4` | 754 | State event processor (0-4 cases) |
| `0x00023304` | 598 | BLE connection state handler (0-8 cases) |
| `0x0001bc50` | 784 | BLE command processor (1-9 cases) |
| `0x00009ff0` | 1176 | BLE connection event handler |

### Advertising Functions
| Address | Size | Function |
|---------|------|----------|
| `0x00022298` | 338 | Advertising management |
| `0x000235e8` | 544 | Advertising configuration |

### Service Helper Functions
| Address | Size | Function |
|---------|------|----------|
| `0x000246b0` | 344 | Primary/Secondary service helper |
| `0x00024eb0` | 234 | Primary/Secondary service helper |
| `0x00025260` | 188 | Primary service helper |
| `0x0003fac6` | 58 | Characteristic declaration helper |

---

## 16. Implications for SC2 Spoofing

### What This Means for Our Project

1. **Report format**: The SC2 BLE HID report format is defined by the HID Report Descriptor in the firmware. Our spoofed GATT database must match this exactly.

2. **MTU and report size**: The firmware handles reports up to the negotiated MTU. Our ATT server must handle MTU exchange correctly.

3. **CCCD behavior**: The firmware checks CCCD before every notification send. Our host-side driver (hog-ll) must write CCCD to enable notifications — which it already does.

4. **Notification gating**: The `FUN_0003fc3e` function is the notification gate. If our spoofed controller doesn't implement this correctly, notifications won't flow.

5. **Multiple report types**: Up to 6 input reports, plus optional Boot Keyboard and Consumer Control. The Report Map must list all of these.

6. **Connection parameters**: The firmware requests specific connection parameters. Our ATT server should handle LE Connection Parameter Update requests.

7. **ESB is irrelevant for BLE spoofing**: The ESB protocol is for the wireless dongle, not BLE. We can ignore it.

8. **State machine is firmware-internal**: The state machine handles mode switching (USB/Puck/BLE/Battery). For BLE spoofing, we only care about the BLE path (which is the PUCK_ON or equivalent state).
