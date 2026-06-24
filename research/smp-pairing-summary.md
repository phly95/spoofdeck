# SMP Pairing Research Summary — Key Findings

## Quick Answers to Your Questions

### 1. Can we keep BlueZ for SMP but handle ATT ourselves?
**YES.** This is the recommended approach. SMP (CID 6) and ATT (CID 4) are separate L2CAP channels. The kernel handles SMP independently at `net/bluetooth/smp.c`, while you can implement your own ATT server on raw L2CAP CID 4.

### 2. Can SMP and ATT be on different sockets?
**YES.** They're completely separate:
- SMP: L2CAP CID 6 (handled by kernel)
- ATT: L2CAP CID 4 (handled by userspace)
Both operate independently on the same BLE connection.

### 3. Does BlueZ's SMP work independently of its GATT server?
**YES.** BlueZ's SMP implementation (`src/shared/smp.c`) is separate from its GATT server (`src/shared/gatt-server.c`). You can disable the GATT server while keeping SMP active.

### 4. What L2CAP channels do SMP and ATT use?
- **SMP**: CID 6 (Security Manager Protocol)
- **ATT**: CID 4 (Attribute Protocol)
- Both are fixed L2CAP channels defined in the Bluetooth Core Specification

### 5. Can they coexist on the same connection?
**YES.** BLE connections support multiple L2CAP channels simultaneously. SMP and ATT operate independently.

### 6. What pairing methods are available?
1. **Just Works** - No user interaction (recommended for HOGP)
2. **Passkey Entry** - User enters 6-digit code
3. **Numeric Comparison** - Both devices display code
4. **OOB** - Out-of-band pairing (NFC, etc.)

### 7. Does Just Works require SMP implementation?
**NO.** The kernel handles SMP automatically. Just Works pairing can work without any SMP implementation on the peripheral if you let the kernel handle it.

### 8. Can the peripheral just accept whatever the central proposes?
**YES.** With Just Works pairing, the peripheral accepts the central's pairing parameters without user interaction.

### 9. What happens if the peripheral doesn't respond to SMP?
- Central times out (typically 30 seconds)
- Connection may still be established but unencrypted
- Some characteristics may be inaccessible if they require encryption
- HOGP requires encryption, so pairing must succeed

### 10. Does the kernel handle SMP independently of bluetoothd?
**YES.** The kernel's Bluetooth stack includes a complete SMP implementation at `net/bluetooth/smp.c`. It handles:
- SMP PDU reception/transmission
- Pairing state machine
- Key generation and storage
- Encryption setup

### 11. Can we start bluetoothd just for SMP, then use our own ATT server?
**YES.** This is the recommended approach:
1. Start `bluetoothd` (handles SMP, bonding, device management)
2. Create raw L2CAP socket on CID 4 (your custom ATT server)
3. Both operate independently

### 12. What happens if both BlueZ and our code try to handle the same connection?
**RACE CONDITION.** If both try to accept the ATT connection on CID 4:
- Only one will succeed
- The other will fail silently
- **Solution**: Either disable BlueZ's GATT database or use BlueZ's D-Bus API instead

### 13. Is there a way to tell BlueZ to handle SMP but not ATT?
**Not directly.** BlueZ doesn't have a configuration option to disable ATT while keeping SMP. However:
- You can implement your own ATT server on CID 4
- BlueZ's GATT server may fail to bind (address mismatch issue)
- This effectively gives you what you want

### 14. Are there standalone SMP implementations?
**YES**, but not recommended:
- **TinyCrypt**: Minimal crypto library
- **mbedTLS**: Full crypto library
- **BlueZ `src/shared/smp.c`**: BlueZ's SMP implementation

### 15. Can we use the kernel's SMP directly?
**Not directly from userspace.** The kernel handles SMP internally. Userspace can only:
- Set IO capabilities via `MGMT_OP_SET_IO_CAPABILITY`
- Register agent via `MGMT_OP_REGISTER_AGENT`
- Receive pairing events via `MGMT_EV_*`

### 16. What happens if the peripheral doesn't respond to SMP?
- Central times out (30 seconds typical)
- Connection may be established unencrypted
- Some characteristics may be inaccessible
- HOGP requires encryption, so pairing must succeed

### 17. Can we use no encryption (Just Works without bonding)?
**YES**, but:
- Just Works can work without bonding (temporary pairing)
- HOGP may require encryption for security
- Some characteristics may require encryption
- Bonding is recommended for persistent pairing

### 18. Does HOGP require encryption?
**YES.** The HID over GATT Profile requires encryption for security. Pairing must complete before HID reports can be exchanged.

---

## Recommended Implementation Strategy

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    BLE Connection                           │
├─────────────────────────────────────────────────────────────┤
│  L2CAP Channel 6 (SMP)     │  L2CAP Channel 4 (ATT)       │
│  ┌─────────────────────┐   │  ┌─────────────────────────┐  │
│  │  Kernel SMP Handler │   │  │  Your Custom ATT Server │  │
│  │  (net/bluetooth/    │   │  │  (raw L2CAP socket)     │  │
│  │   smp.c)            │   │  │                         │  │
│  └─────────────────────┘   │  └─────────────────────────┘  │
├─────────────────────────────────────────────────────────────┤
│  HCI Layer (Kernel)                                         │
├─────────────────────────────────────────────────────────────┤
│  Bluetooth Hardware (Qualcomm QCA)                          │
└─────────────────────────────────────────────────────────────┘
```

### Implementation Steps

1. **Keep bluetoothd running** for SMP handling
2. **Create raw L2CAP socket** on CID 4
3. **Bind to static random address** `C2:12:34:56:78:9A`
4. **Implement ATT PDU handler** for GATT operations
5. **Serve SC2 GATT database** (custom service + characteristics)
6. **Test pairing** with Just Works
7. **Add input forwarding** from Deck controller

### Code Example

```python
import socket
import struct

class ATTServer:
    def __init__(self, address: str):
        # Create raw L2CAP socket
        self.sock = socket.socket(socket.AF_BLUETOOTH, 
                                  socket.SOCK_RAW, 
                                  socket.BTPROTO_L2CAP)
        # Bind to static random address on CID 4 (ATT)
        self.sock.bind((address, 4))
        
    def listen(self):
        self.sock.listen(1)
        conn, addr = self.sock.accept()
        return conn, addr
        
    def handle_pdu(self, pdu: bytes) -> bytes:
        opcode = pdu[0]
        if opcode == 0x02:  # ATT Exchange MTU Request
            mtu = struct.unpack('<H', pdu[1:3])[0]
            return struct.pack('<BBH', 0x03, 23, mtu)  # MTU Response
        # Handle other ATT PDUs...
        return b'\x01'  # Error Response

# Usage
server = ATTServer("C2:12:34:56:78:9A")
conn, addr = server.listen()
while True:
    data = conn.recv(1024)
    response = server.handle_pdu(data)
    conn.send(response)
```

---

## Key Technical Details

### L2CAP CID Definitions (from kernel headers)

```c
#define L2CAP_CID_ATT        0x0004  // ATT Protocol
#define L2CAP_CID_LE_SIGNALING 0x0005  // LE Signaling
#define L2CAP_CID_SMP        0x0006  // SMP Protocol
#define L2CAP_CID_SMP_BREDR  0x0007  // SMP over BR/EDR
```

### BT Security Levels

```c
#define BT_SECURITY_LOW      1   // No encryption
#define BT_SECURITY_MEDIUM   2   // Unauthenticated pairing
#define BT_SECURITY_HIGH     3   // Authenticated pairing
#define BT_SECURITY_FIPS     4   // FIPS-compliant pairing
```

### SMP Pairing Methods

From Bluetooth Core Specification:
- **Just Works**: No user interaction, no MITM protection
- **Passkey Entry**: User enters 6-digit code
- **Numeric Comparison**: Both devices display 6-digit number
- **OOB**: Out-of-band pairing (NFC, etc.)

---

## Testing Strategy

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

### Test 3: Steam Client Recognition

1. Advertise SC2 service UUID (`100F6C32-...`)
2. Connect from Steam Client
3. Verify Steam Input recognizes device
4. Send test input report

---

## Known Issues and Mitigations

### Issue 1: Address Binding Problem
**Problem**: BlueZ's GATT listener binds to public address, not static random address.
**Mitigation**: Use raw L2CAP socket bound to static random address.

### Issue 2: SMP/ATT Race Condition
**Problem**: Both BlueZ and custom code may try to handle ATT.
**Mitigation**: Either disable BlueZ's GATT database or use BlueZ's D-Bus API.

### Issue 3: Key Storage
**Problem**: Need to store bonding keys for re-pairing.
**Mitigation**: Let bluetoothd handle key storage (default behavior).

### Issue 4: Agent Registration
**Problem**: Need to register SMP agent for pairing interaction.
**Mitigation**: Register agent via MGMT_OP_REGISTER_AGENT or use NoInputNoOutput agent.

---

## Conclusion

**The approach is feasible.** You can:
1. Keep BlueZ for SMP handling (kernel-level)
2. Implement your own ATT server on raw L2CAP CID 4
3. Use Just Works pairing (no user interaction required)
4. Serve SC2 GATT database from your custom ATT server
5. Forward input from Deck controller to host PC

The key insight is that SMP and ATT are separate L2CAP channels that operate independently. The kernel handles SMP automatically, while you can implement your own ATT server.

---

## References

- Bluetooth Core Specification 5.4
- Linux kernel `net/bluetooth/smp.c`
- Linux kernel `net/bluetooth/l2cap.h`
- BlueZ `src/shared/smp.c`
- BlueZ `src/shared/att.c`
- BlueZ `peripheral/gatt.c` (reference implementation)
- Our project documentation (`docs/`, `research/`)
