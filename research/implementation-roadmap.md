# Implementation Roadmap: Custom ATT Server with BlueZ SMP

## Overview

This document provides a step-by-step implementation plan for creating a custom ATT server on the Steam Deck while keeping BlueZ for SMP pairing handling.

## Architecture Decision

**Chosen Approach**: Keep BlueZ for SMP, implement custom ATT server on raw L2CAP CID 4.

**Rationale**:
1. SMP and ATT are separate L2CAP channels (CID 6 and CID 4)
2. Kernel handles SMP automatically at `net/bluetooth/smp.c`
3. Custom ATT server gives us full control over GATT database
4. Eliminates BlueZ's address binding issue (public vs static random address)

## Implementation Steps

### Phase 1: Basic ATT Server (1-2 days)

#### Step 1.1: Create Raw L2CAP Socket
```python
import socket
import struct

class RawL2CAPSocket:
    def __init__(self, address: str, cid: int):
        self.address = address
        self.cid = cid
        self.sock = None
        
    def create_socket(self):
        """Create and bind raw L2CAP socket"""
        self.sock = socket.socket(
            socket.AF_BLUETOOTH,
            socket.SOCK_RAW,
            socket.BTPROTO_L2CAP
        )
        # Bind to static random address on specific CID
        self.sock.bind((self.address, self.cid))
        print(f"[+] L2CAP socket bound to {self.address} CID {self.cid}")
        
    def listen(self, backlog=1):
        """Listen for incoming connections"""
        self.sock.listen(backlog)
        print(f"[+] Listening on CID {self.cid}")
        
    def accept(self):
        """Accept incoming connection"""
        conn, addr = self.sock.accept()
        print(f"[+] Connection from {addr}")
        return conn, addr
```

#### Step 1.2: Implement ATT PDU Handler
```python
class ATTPDUHandler:
    """Handle ATT Protocol Data Units"""
    
    # ATT Opcodes
    ATT_OP_MTU_REQ = 0x02
    ATT_OP_MTU_RESP = 0x03
    ATT_OP_FIND_INFO_REQ = 0x04
    ATT_OP_FIND_INFO_RESP = 0x05
    ATT_OP_READ_BY_GROUP_REQ = 0x10
    ATT_OP_READ_BY_GROUP_RESP = 0x11
    ATT_OP_READ_BY_TYPE_REQ = 0x08
    ATT_OP_READ_BY_TYPE_RESP = 0x09
    
    def __init__(self, mtu=23):
        self.mtu = mtu
        
    def handle_pdu(self, pdu: bytes) -> bytes:
        """Process ATT PDU and return response"""
        if len(pdu) < 1:
            return self.error_response(0x01, 0x0001)  # Invalid PDU
            
        opcode = pdu[0]
        
        if opcode == self.ATT_OP_MTU_REQ:
            return self.handle_mtu_request(pdu)
        elif opcode == self.ATT_OP_FIND_INFO_REQ:
            return self.handle_find_info_request(pdu)
        elif opcode == self.ATT_OP_READ_BY_GROUP_REQ:
            return self.handle_read_by_group_request(pdu)
        elif opcode == self.ATT_OP_READ_BY_TYPE_REQ:
            return self.handle_read_by_type_request(pdu)
        else:
            return self.error_response(opcode, 0x0006)  # Request Not Supported
            
    def handle_mtu_request(self, pdu: bytes) -> bytes:
        """Handle ATT Exchange MTU Request"""
        if len(pdu) < 3:
            return self.error_response(self.ATT_OP_MTU_REQ, 0x000D)
            
        client_mtu = struct.unpack('<H', pdu[1:3])[0]
        self.mtu = max(23, min(client_mtu, 517))  # Clamp MTU
        print(f"[+] MTU Exchange: client={client_mtu}, server={self.mtu}")
        
        return struct.pack('<BBH', 
            self.ATT_OP_MTU_RESP, 
            0,  # Reserved
            self.mtu
        )
        
    def error_response(self, request_opcode: int, error_code: int) -> bytes:
        """Generate ATT Error Response"""
        return struct.pack('<BBH', 
            0x01,  # Error Response opcode
            request_opcode,
            error_code
        )
```

#### Step 1.3: Test Basic ATT Server
```python
def test_basic_att_server():
    """Test basic ATT server functionality"""
    server = RawL2CAPSocket("C2:12:34:56:78:9A", 4)  # CID 4 = ATT
    server.create_socket()
    server.listen()
    
    handler = ATTPDUHandler()
    
    while True:
        conn, addr = server.accept()
        print(f"[+] Client connected: {addr}")
        
        while True:
            try:
                data = conn.recv(1024)
                if not data:
                    break
                    
                print(f"[+] Received: {data.hex()}")
                response = handler.handle_pdu(data)
                print(f"[+] Sending: {response.hex()}")
                conn.send(response)
                
            except Exception as e:
                print(f"[-] Error: {e}")
                break
                
        conn.close()
```

### Phase 2: GATT Database (2-3 days)

#### Step 2.1: Define GATT Structure
```python
class GATTService:
    def __init__(self, uuid: str, primary: bool = True):
        self.uuid = uuid
        self.primary = primary
        self.characteristics = []
        
class GATTCharacteristic:
    def __init__(self, uuid: str, properties: int, value: bytes = b''):
        self.uuid = uuid
        self.properties = properties
        self.value = value
        self.descriptors = []
        
class GATTDatabase:
    def __init__(self):
        self.services = []
        
    def add_service(self, service: GATTService):
        self.services.append(service)
        
    def add_characteristic(self, service: GATTService, 
                          characteristic: GATTCharacteristic):
        service.characteristics.append(characteristic)
```

#### Step 2.2: Implement SC2 GATT Database
```python
def create_sc2_gatt_database() -> GATTDatabase:
    """Create SC2 GATT database"""
    db = GATTDatabase()
    
    # Device Information Service (0x180A)
    device_info = GATTService("0000180a-0000-1000-8000-00805f9b34fb", primary=True)
    db.add_service(device_info)
    
    manufacturer = GATTCharacteristic(
        "00002a29-0000-1000-8000-00805f9b34fb",
        0x02,  # Read
        b"Valve Software"
    )
    db.add_characteristic(device_info, manufacturer)
    
    # SC2 Custom Service (100F6C32-...)
    sc2_service = GATTService(
        "100f6c32-1735-4313-b402-38567131e5f3",
        primary=True
    )
    db.add_service(sc2_service)
    
    # Input Report Characteristic (100F6C7A-...)
    input_report = GATTCharacteristic(
        "100f6c7a-1735-4313-b402-38567131e5f3",
        0x12,  # Read, Notify
        b'\x00' * 45  # 45-byte input report
    )
    db.add_characteristic(sc2_service, input_report)
    
    return db
```

#### Step 2.3: Handle GATT Operations
```python
class GATTHandler:
    def __init__(self, database: GATTDatabase):
        self.database = database
        self.att_handler = ATTPDUHandler()
        
    def handle_read_by_group_request(self, pdu: bytes) -> bytes:
        """Handle ATT Read By Group Type Request"""
        # Parse request
        start_handle = struct.unpack('<H', pdu[1:3])[0]
        end_handle = struct.unpack('<H', pdu[3:5])[0]
        uuid = pdu[5:]
        
        # Find matching services
        services = []
        for service in self.database.services:
            if service.primary and uuid == bytes.fromhex("2800"):
                services.append(service)
                
        # Build response
        if not services:
            return self.att_handler.error_response(
                self.att_handler.ATT_OP_READ_BY_GROUP_REQ,
                0x0A02  # Attribute Not Found
            )
            
        # Return services
        response = bytearray()
        response.append(self.att_handler.ATT_OP_READ_BY_GROUP_RESP)
        response.append(0)  # Length (to be filled)
        
        for service in services:
            # Service record
            response.extend(struct.pack('<HH', 0x0001, 0xFFFF))  # Handles
            response.extend(bytes.fromhex(service.uuid.replace('-', '')))
            
        response[1] = len(response) - 2  # Set length
        
        return bytes(response)
```

### Phase 3: Integration with BlueZ SMP (1-2 days)

#### Step 3.1: Verify SMP Handling
```python
def verify_smp_pairing():
    """Verify SMP pairing works with custom ATT server"""
    # 1. Start bluetoothd (handles SMP)
    # 2. Start custom ATT server
    # 3. Connect from host PC
    # 4. Verify pairing completes
    # 5. Check encryption is established
    
    print("[*] SMP pairing test:")
    print("1. Start bluetoothd")
    print("2. Start custom ATT server on CID 4")
    print("3. Connect from host PC")
    print("4. Verify pairing completes")
    print("5. Check encryption")
```

#### Step 3.2: Test with Host PC
```python
def test_with_host_pc():
    """Test custom ATT server with host PC"""
    # On Deck:
    # 1. Start bluetoothd
    # 2. Start custom ATT server
    # 3. Advertise SC2 service UUID
    
    # On Host PC:
    # 1. Scan for devices
    # 2. Connect to "Steam Controller 2026"
    # 3. Verify pairing completes
    # 4. Discover GATT services
    # 5. Read characteristics
    
    print("[*] Host PC test:")
    print("1. Start custom ATT server on Deck")
    print("2. Scan from host PC")
    print("3. Connect to Steam Controller 2026")
    print("4. Verify pairing")
    print("5. Discover services")
```

### Phase 4: Input Forwarding (2-3 days)

#### Step 4.1: Read Deck Controller Input
```python
class DeckControllerInput:
    def __init__(self):
        self.device = None
        
    def open_device(self, device_path: str = "/dev/hidraw3"):
        """Open Deck controller USB HID device"""
        import os
        self.fd = os.open(device_path, os.O_RDONLY)
        print(f"[+] Opened controller device: {device_path}")
        
    def read_input(self) -> bytes:
        """Read 64-byte vendor HID report"""
        import os
        data = os.read(self.fd, 64)
        return data
        
    def parse_input(self, data: bytes) -> dict:
        """Parse vendor HID report"""
        # Parse according to SC2 format
        buttons = struct.unpack('<I', data[2:6])[0]
        left_trigger = data[6]
        right_trigger = data[7]
        left_stick_x = struct.unpack('<h', data[8:10])[0]
        left_stick_y = struct.unpack('<h', data[10:12])[0]
        
        return {
            'buttons': buttons,
            'left_trigger': left_trigger,
            'right_trigger': right_trigger,
            'left_stick_x': left_stick_x,
            'left_stick_y': left_stick_y,
        }
```

#### Step 4.2: Format SC2 Input Report
```python
class SC2InputReport:
    def __init__(self):
        self.sequence = 0
        
    def create_report(self, input_data: dict) -> bytes:
        """Create 45-byte SC2 input report"""
        report = bytearray(45)
        
        # Report ID
        report[0] = 0x45
        
        # Sequence number
        self.sequence = (self.sequence + 1) & 0xFF
        report[1] = self.sequence
        
        # Buttons (32-bit)
        struct.pack_into('<I', report, 2, input_data['buttons'])
        
        # Triggers
        report[6] = input_data['left_trigger']
        report[7] = input_data['right_trigger']
        
        # Sticks (16-bit signed)
        struct.pack_into('<h', report, 8, input_data['left_stick_x'])
        struct.pack_into('<h', report, 10, input_data['left_stick_y'])
        struct.pack_into('<h', report, 12, input_data.get('right_stick_x', 0))
        struct.pack_into('<h', report, 14, input_data.get('right_stick_y', 0))
        
        # Trackpads
        struct.pack_into('<h', report, 16, input_data.get('left_trackpad_x', 0))
        struct.pack_into('<h', report, 18, input_data.get('left_trackpad_y', 0))
        struct.pack_into('<h', report, 20, input_data.get('right_trackpad_x', 0))
        struct.pack_into('<h', report, 22, input_data.get('right_trackpad_y', 0))
        
        # IMU (accelerometer + gyroscope)
        struct.pack_into('<h', report, 24, input_data.get('accel_x', 0))
        struct.pack_into('<h', report, 26, input_data.get('accel_y', 0))
        struct.pack_into('<h', report, 28, input_data.get('accel_z', 0))
        struct.pack_into('<h', report, 30, input_data.get('gyro_x', 0))
        struct.pack_into('<h', report, 32, input_data.get('gyro_y', 0))
        struct.pack_into('<h', report, 34, input_data.get('gyro_z', 0))
        
        # IMU timestamp
        struct.pack_into('<I', report, 36, input_data.get('imu_timestamp', 0))
        
        return bytes(report)
```

#### Step 4.3: Send Input via ATT Notifications
```python
class ATTNotificationSender:
    def __init__(self, connection):
        self.connection = connection
        self.enabled = False
        
    def enable_notifications(self):
        """Enable ATT notifications"""
        self.enabled = True
        print("[+] ATT notifications enabled")
        
    def send_notification(self, handle: int, value: bytes):
        """Send ATT notification"""
        if not self.enabled:
            return
            
        # ATT Notification PDU
        pdu = bytearray()
        pdu.append(0x1B)  # Notification opcode
        pdu.extend(struct.pack('<H', handle))
        pdu.extend(value)
        
        self.connection.send(bytes(pdu))
        print(f"[+] Sent notification: handle={handle}, value={value.hex()}")
```

## Testing Checklist

### Phase 1 Tests
- [ ] Raw L2CAP socket creation
- [ ] Socket binding to static random address
- [ ] Listening on CID 4
- [ ] Accepting connections
- [ ] ATT MTU exchange
- [ ] Basic ATT PDU handling

### Phase 2 Tests
- [ ] GATT database creation
- [ ] Service discovery (Read By Group Type)
- [ ] Characteristic discovery (Read By Type)
- [ ] Characteristic reading
- [ ] Notification support

### Phase 3 Tests
- [ ] SMP pairing with Just Works
- [ ] Encryption establishment
- [ ] Bonding (optional)
- [ ] Host PC connection
- [ ] Steam Client recognition

### Phase 4 Tests
- [ ] Deck controller input reading
- [ ] SC2 report formatting
- [ ] ATT notification sending
- [ ] Input forwarding to host
- [ ] Steam Input functionality

## Known Issues and Solutions

### Issue 1: Address Binding
**Problem**: BlueZ's GATT listener binds to public address.
**Solution**: Use raw L2CAP socket bound to static random address.

### Issue 2: SMP/ATT Race Condition
**Problem**: Both BlueZ and custom code may try to handle ATT.
**Solution**: Accept that BlueZ's GATT server may fail, or disable it.

### Issue 3: Key Storage
**Problem**: Need to store bonding keys for re-pairing.
**Solution**: Let bluetoothd handle key storage.

### Issue 4: Agent Registration
**Problem**: Need to register SMP agent for pairing interaction.
**Solution**: Use existing `agent.py` implementation.

## Next Steps

1. **Implement Phase 1**: Basic ATT server with raw L2CAP socket
2. **Test SMP pairing**: Verify pairing works with custom ATT server
3. **Implement Phase 2**: GATT database for SC2 service
4. **Test Steam Client recognition**: Verify Steam Input works
5. **Implement Phase 3**: Input forwarding from Deck controller
6. **Test full functionality**: End-to-end testing

## Resources

- Bluetooth Core Specification 5.4
- Linux kernel `net/bluetooth/smp.c`
- Linux kernel `net/bluetooth/l2cap.h`
- BlueZ `src/shared/smp.c`
- BlueZ `src/shared/att.c`
- BlueZ `peripheral/gatt.c` (reference implementation)
- Our project documentation (`docs/`, `research/`)
- `src/agent.py` (SMP agent implementation)
- `src/gatt_app.py` (current GATT implementation)
