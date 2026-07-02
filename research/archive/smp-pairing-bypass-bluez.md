# Research: BLE SMP Pairing When Bypassing BlueZ's GATT Server

## Executive Summary

**Can we keep BlueZ for SMP but handle ATT ourselves?** Yes, this is the recommended approach. The Linux kernel handles SMP independently at the L2CAP layer (CID 6), while ATT runs on a separate L2CAP channel (CID 4). You can implement your own ATT server on raw L2CAP CID 4 while letting the kernel/BlueZ handle SMP on CID 6.

**Key finding**: SMP and ATT are completely separate L2CAP channels that operate independently. The kernel's Bluetooth stack (`net/bluetooth/smp.c`) handles SMP pairing automatically at the kernel level, regardless of whether BlueZ's GATT server is running.

---

## 1. BlueZ Architecture: SMP vs ATT Separation

### L2CAP Channel Layout

From kernel header `include/net/bluetooth/l2cap.h`:
```c
#define L2CAP_CID_ATT        0x0004  // ATT (Attribute Protocol)
#define L2CAP_CID_LE_SIGNALING 0x0005  // LE L2CAP signaling
#define L2CAP_CID_SMP        0x0006  // SMP (Security Manager Protocol)
#define L2CAP_CID_SMP_BREDR  0x0007  // SMP over BR/EDR
```

**Critical insight**: SMP (CID 6) and ATT (CID 4) are separate fixed L2CAP channels. They coexist on the same BLE connection but operate independently.

### BlueZ's Internal Architecture

From `include/net/bluetooth/hci_core.h`:
```c
struct hci_dev {
    void *smp_data;      // SMP channel data
    void *smp_bredr_data; // SMP over BR/EDR data
    // ...
};
```

BlueZ maintains SMP as a separate subsystem from GATT/ATT. The SMP channel is managed at the kernel level via `net/bluetooth/smp.c`, while the ATT channel is handled by `bluetoothd` (userspace) via `src/shared/att.c` and `src/shared/gatt-server.c`.

### How BlueZ Handles Incoming Connections

From our debug analysis (`debug-bluetoothd-analysis.md`):
1. **Kernel level**: LE connection accepted → MGMT `Device Connected` event
2. **L2CAP level**: SMP channel (CID 6) automatically handled by kernel
3. **ATT level**: `bt_io_listen` socket on CID 4 tries to accept connection
4. **Failure point**: Socket bound to wrong address → ATT channel not accepted

The key insight: **SMP works even when ATT fails**. The kernel handles SMP independently.

---

## 2. SMP Protocol Basics

### L2CAP Channels for SMP and ATT

| Channel | CID | Purpose | Handler |
|---------|-----|---------|---------|
| ATT | 0x0004 | Attribute Protocol (GATT) | BlueZ userspace (`att.c`) |
| LE Signaling | 0x0005 | LE L2CAP signaling | Kernel (`l2cap_core.c`) |
| SMP | 0x0006 | Security Manager Protocol | Kernel (`smp.c`) |

### SMP Pairing Methods

From Bluetooth Core Specification:
1. **Just Works** - No user interaction, no MITM protection
2. **Passkey Entry** - User enters 6-digit passkey
3. **Numeric Comparison** - Both devices display 6-digit number, user confirms
4. **OOB (Out of Band)** - Pairing data exchanged via NFC or other means

### Pairing Phases

1. **Phase 1: Feature Exchange** - IO capabilities, authentication requirements
2. **Phase 2: Key Generation** - Pairing keys generated (STK or LTK)
3. **Phase 3: Key Distribution** - Encrypted keys distributed (IRK, CSRK, LTK)

---

## 3. Just Works Pairing Analysis

### Does Just Works Require SMP Implementation?

**No, Just Works can work without any SMP implementation on the peripheral** if:
- The kernel handles SMP automatically (which it does in Linux)
- The peripheral accepts whatever the central proposes
- No encryption is required (bonding optional)

### What Happens If Peripheral Doesn't Respond to SMP?

From kernel SMP behavior:
1. **Central sends pairing request** → SMP PDU on CID 6
2. **If peripheral doesn't respond** → Central times out after 30s
3. **Connection may still be established** but unencrypted
4. **Some characteristics may be inaccessible** if they require encryption

### HOGP (HID over GATT Profile) Requirements

From Bluetooth HID Profile specification:
- **HOGP requires encryption** for security
- The HID service characteristics must be encrypted
- Pairing must complete before HID reports can be exchanged
- **Just Works is sufficient** for HOGP (no MITM protection needed)

### BlueZ's JustWorksRepairing Setting

From `/etc/bluetooth/main.conf`:
```ini
# Specify the policy to the JUST-WORKS repairing initiated by peer
# Possible values: "never", "confirm", "always"
# Defaults to "never"
#JustWorksRepairing = never
```

This controls whether BlueZ accepts Just Works re-pairing from a peer.

---

## 4. Kernel-Level SMP Implementation

### Does Linux Kernel Handle SMP Independently?

**Yes.** The kernel's Bluetooth stack includes a complete SMP implementation:
- Location: `net/bluetooth/smp.c`
- Handles all SMP PDUs on CID 6
- Manages pairing state machines
- Generates encryption keys
- Stores bonded device information

### SMP Data Structures (from kernel headers)

```c
struct smp_csrk {
    // Connection Signature Resolving Key
};

struct smp_ltk {
    // Long Term Key (used for encryption)
};

struct smp_irk {
    // Identity Resolving Key (used for privacy)
};
```

### Key Management Functions

```c
struct smp_ltk *hci_add_ltk(struct hci_dev *hdev, bdaddr_t *bdaddr, ...);
struct smp_ltk *hci_find_ltk(struct hci_dev *hdev, bdaddr_t *bdaddr, ...);
void hci_smp_ltks_clear(struct hci_dev *hdev);
struct smp_irk *hci_find_irk_by_rpa(struct hci_dev *hdev, bdaddr_t *rpa);
void mgmt_smp_complete(struct hci_conn *conn, bool complete);
```

### Does SMP Work Without bluetoothd?

**Yes, at the kernel level.** The kernel handles:
- SMP PDU reception and transmission
- Pairing state machine
- Key generation and storage
- Encryption setup

However, **bluetoothd is needed for**:
- Agent registration (user interaction for pairing)
- Bonding persistence (storing keys to disk)
- Device management (tracking paired devices)
- GATT services (if using BlueZ's GATT server)

---

## 5. Testing SMP Without BlueZ's GATT Server

### Approach: Keep bluetoothd for SMP, Custom ATT Server

**Recommended architecture**:
1. **bluetoothd running** → Handles SMP, bonding, device management
2. **Custom ATT server** → Raw L2CAP socket on CID 4
3. **Coexistence** → SMP and ATT operate on different channels

### Implementation Strategy

```python
import socket
import struct

# Create raw L2CAP socket for ATT
att_sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_RAW, socket.BTPROTO_L2CAP)

# Bind to static random address on CID 4 (ATT)
addr = "C2:12:34:56:78:9A"
att_sock.bind((addr, 4))  # CID 4 = ATT

# Listen for connections
att_sock.listen(1)
conn, addr = att_sock.accept()

# Handle ATT PDUs
while True:
    data = conn.recv(1024)
    # Process ATT requests (MTU exchange, Read By Group Type, etc.)
    # Send ATT responses
```

### What Happens if Both BlueZ and Our Code Handle Same Connection?

**Problem**: If BlueZ's GATT server is also listening on CID 4, there's a race condition:
- Both sockets receive the ATT connection request
- Only one will successfully accept
- The other will fail silently

**Solution**: Either:
1. Disable BlueZ's GATT database (not easily possible)
2. Use a different approach (see Option 2 below)
3. Accept that BlueZ handles ATT and use D-Bus API instead

### Option 2: Let BlueZ Handle Everything, Use D-Bus API

Instead of raw L2CAP, use BlueZ's D-Bus API:
1. Register GATT application via `GattManager1.RegisterApplication`
2. Handle `ReadValue`/`WriteValue` calls via D-Bus method handlers
3. Send notifications via `PropertiesChanged` signals

This is what our current `gatt_app.py` does, but it has the address binding issue.

---

## 6. Standalone SMP Implementations

### Can We Implement SMP Ourselves?

**Yes, but not recommended** for several reasons:
1. **Complexity**: SMP is cryptographically complex (ECDH, AES-CCM, etc.)
2. **Key storage**: Need secure storage for bonding keys
3. **Compliance**: Must implement all SMP features for interoperability
4. **Kernel conflicts**: Kernel may interfere with SMP if bluetoothd is running

### Standalone SMP Libraries

- **TinyCrypt**: Minimal crypto library, can implement SMP
- **mbedTLS**: Full crypto library, can implement SMP
- **BlueZ `src/shared/smp.c`**: BlueZ's SMP implementation (userspace)

### Using Kernel's SMP Directly

**Not directly possible** from userspace. The kernel handles SMP internally via:
- HCI commands (LE Enable Encryption, LE Start Encryption)
- L2CAP fixed channel (CID 6)
- Internal state machine

Userspace can only:
- Set IO capabilities via `MGMT_OP_SET_IO_CAPABILITY`
- Register agent via `MGMT_OP_REGISTER_AGENT`
- Receive pairing events via `MGMT_EV_*`

---

## 7. What Happens If Peripheral Doesn't Respond to SMP

### Scenario Analysis

| Central Action | Peripheral Response | Result |
|---------------|---------------------|--------|
| Send Pairing Request | No response | Central times out, no encryption |
| Send Pairing Request | Reject | Connection may fail or proceed unencrypted |
| Send Pairing Request | Accept | Pairing proceeds |
| Request Encryption | No response | Encryption fails, connection may drop |

### Connection Failure Modes

1. **Immediate failure**: Some centrals reject unencrypted HID connections
2. **Delayed failure**: Connection established but HID reports rejected
3. **Partial functionality**: Some characteristics work, others require encryption

### HOGP-Specific Behavior

From Bluetooth HID Profile:
- **MUST support encryption** for security
- **Just Works pairing** is sufficient (no MITM protection)
- **Bonding recommended** for persistent pairing
- **If no encryption**: Central may reject the HID service

---

## 8. Recommended Implementation Strategy

### Phase 1: Minimal SMP Test

1. **Keep bluetoothd running** for SMP handling
2. **Create raw L2CAP socket** on CID 4 (ATT)
3. **Bind to static random address** `C2:12:34:56:78:9A`
4. **Handle basic ATT requests**: MTU Exchange, Read By Group Type
5. **Test pairing** from host PC

### Phase 2: Full ATT Server

1. **Implement ATT PDU handler** for all GATT operations
2. **Serve SC2 GATT database** (custom service + characteristics)
3. **Handle notifications** for input reports
4. **Test Steam Client recognition**

### Phase 3: Input Forwarding

1. **Read Deck controller input** (USB HID or evdev)
2. **Format as SC2 input reports** (45-byte or 47-byte format)
3. **Send via ATT notifications** to host PC
4. **Test Steam Input functionality**

### Phase 4: Integration

1. **Add Valve custom service** (UUID: `100F6C32-...`)
2. **Implement mode switching** (lizard mode ↔ Steam Input)
3. **Add haptics and gyro support**
4. **Polish and debugging**

---

## 9. Code Architecture

### Module Structure

```
src/
├── att_server.py      # Raw L2CAP ATT server (CID 4)
├── smp_handler.py     # SMP handler (if needed, or rely on kernel)
├── gatt_database.py   # GATT database (services, characteristics)
├── advertisement.py   # BLE advertisement (LEAdvertisement1)
├── input_handler.py   # Deck controller input reading
├── sc2_protocol.py    # SC2 report format handling
└── main.py            # Main entry point
```

### Key Classes

```python
class ATTServer:
    """Raw L2CAP ATT server on CID 4"""
    def __init__(self, address: str):
        self.sock = socket.socket(AF_BLUETOOTH, SOCK_RAW, BTPROTO_L2CAP)
        self.sock.bind((address, 4))  # CID 4 = ATT
        
    def listen(self):
        """Listen for ATT connections"""
        
    def handle_pdu(self, pdu: bytes) -> bytes:
        """Process ATT PDU and return response"""

class GATTDatabase:
    """GATT database with services and characteristics"""
    def __init__(self):
        self.services = []
        self.characteristics = []
        
    def add_service(self, uuid: str, primary: bool = True):
        """Add GATT service"""
        
    def add_characteristic(self, service_uuid: str, uuid: str, 
                          properties: int, value: bytes = b''):
        """Add GATT characteristic"""

class SC2InputHandler:
    """Read Deck controller and format as SC2 reports"""
    def __init__(self):
        self.controller = None  # USB HID or evdev device
        
    def read_input(self) -> bytes:
        """Read controller input and return SC2 report"""
```

---

## 10. Testing Strategy

### Test 1: SMP Pairing

1. Start `bluetoothd` (for SMP handling)
2. Start custom ATT server on CID 4
3. Connect from host PC
4. Verify pairing completes (Just Works)
5. Check if encryption is established

### Test 2: ATT Server

1. Send ATT Exchange MTU request
2. Verify ATT MTU response
3. Send ATT Read By Group Type request
4. Verify GATT services discovered
5. Send ATT Find Information request
6. Verify characteristics discovered

### Test 3: Steam Client Recognition

1. Advertise SC2 service UUID (`100F6C32-...`)
2. Connect from Steam Client
3. Verify Steam Input recognizes device
4. Send test input report
5. Verify input appears in Steam

### Test 4: Input Forwarding

1. Read Deck controller input (USB HID)
2. Format as SC2 input report (45 bytes)
3. Send via ATT notification
4. Verify input appears in Steam

---

## 11. Known Issues and Mitigations

### Issue 1: Address Binding Problem

**Problem**: BlueZ's GATT listener binds to public address, not static random address.

**Mitigation**: Use raw L2CAP socket bound to static random address.

### Issue 2: SMP/ATT Race Condition

**Problem**: Both BlueZ and custom code may try to handle ATT.

**Mitigation**: 
- Option A: Disable BlueZ's GATT database (not easily possible)
- Option B: Use BlueZ's D-Bus API instead of raw L2CAP
- Option C: Accept that BlueZ handles ATT, use D-Bus for everything

### Issue 3: Key Storage

**Problem**: Need to store bonding keys for re-pairing.

**Mitigation**: 
- Let bluetoothd handle key storage (default behavior)
- Or implement custom key storage if bypassing bluetoothd

### Issue 4: Agent Registration

**Problem**: Need to register SMP agent for pairing interaction.

**Mitigation**:
- Register agent via MGMT_OP_REGISTER_AGENT
- Or use NoInputNoOutput agent for Just Works

---

## 12. Conclusion

### Feasibility Assessment

| Approach | Feasibility | Complexity | Recommendation |
|----------|-------------|------------|----------------|
| Keep BlueZ for SMP, custom ATT | **High** | Medium | **Recommended** |
| Implement SMP ourselves | Low | Very High | Not recommended |
| Just Works without SMP | Medium | Low | Test first |
| Use BlueZ D-Bus API only | High | Low | Alternative |

### Recommended Path Forward

1. **Start with raw L2CAP ATT server** (CID 4)
2. **Keep bluetoothd for SMP handling**
3. **Test pairing** with Just Works
4. **Implement GATT database** for SC2 service
5. **Add input forwarding** from Deck controller
6. **Test Steam Client recognition**

### Key Takeaways

1. **SMP and ATT are separate** - Can be handled independently
2. **Kernel handles SMP** - No need for userspace SMP implementation
3. **Just Works is sufficient** - For HOGP (HID over GATT)
4. **Raw L2CAP works** - For custom ATT server
5. **Address binding is critical** - Must bind to static random address

---

## References

- Bluetooth Core Specification 5.4
- Bluetooth HID Profile Specification
- Linux kernel `net/bluetooth/smp.c`
- Linux kernel `net/bluetooth/l2cap.h`
- BlueZ `src/shared/smp.c`
- BlueZ `src/shared/att.c`
- BlueZ `peripheral/gatt.c` (reference implementation)
- Our project documentation (`docs/`, `research/`)
