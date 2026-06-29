#!/usr/bin/env python3
"""
Raw L2CAP ATT Server for BLE Peripheral.

Bypasses BlueZ's GATT server by using a raw L2CAP socket on CID 4
bound directly to the static random BLE address.

Handles ATT PDU exchange: MTU, service discovery, reads, writes, notifications.
SMP pairing is handled separately by the kernel on CID 6.
"""

import socket
import struct
import ctypes
import ctypes.util
import threading
import time
import select
from collections import defaultdict

from gatt_db import (
    GattDatabase, Attribute,
    ATT_OP_ERROR, ATT_OP_MTU_REQ, ATT_OP_MTU_RSP,
    ATT_OP_FIND_INFO_REQ, ATT_OP_FIND_INFO_RSP,
    ATT_OP_READ_BY_TYPE_REQ, ATT_OP_READ_BY_TYPE_RSP,
    ATT_OP_READ_REQ, ATT_OP_READ_RSP,
    ATT_OP_READ_BLOB_REQ, ATT_OP_READ_BLOB_RSP,
    ATT_OP_READ_BY_GROUP_TYPE_REQ, ATT_OP_READ_BY_GROUP_TYPE_RSP,
    ATT_OP_WRITE_REQ, ATT_OP_WRITE_RSP,
    ATT_OP_HANDLE_NFY, ATT_OP_HANDLE_IND, ATT_OP_HANDLE_CNF,
    ATT_OP_WRITE_CMD,
    ATT_ERR_INVALID_HANDLE, ATT_ERR_READ_NOT_PERM, ATT_ERR_WRITE_NOT_PERM,
    ATT_ERR_ATTR_NOT_FOUND, ATT_ERR_REQ_NOT_SUPP,
    GATT_PRIM_SVC_UUID, GATT_CHARAC_UUID, uuid16_to_bytes,
)

AF_BLUETOOTH = 31
BTPROTO_L2CAP = 0
BT_ATT_CID = 4
BDADDR_LE_RANDOM = 0x02
SOL_BLUETOOTH = 274
BT_SECURITY = 4
BT_SECURITY_LOW = 1
BT_SECURITY_MEDIUM = 2

# Load libc for ctypes bind
_libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)


class AttServer:
    """
    Raw L2CAP ATT server for BLE peripheral.

    Binds to a static random BLE address on CID 4 (ATT fixed channel).
    Handles incoming ATT connections and PDU exchange.
    """

    def __init__(self, db, address="C2:12:34:56:78:9A", mtu=517):
        """
        Args:
            db: GattDatabase instance
            address: BLE static random address
            mtu: Server MTU (max attribute value length)
        """
        self.db = db
        self.address = address
        self.server_mtu = mtu
        self.mtu = 23  # Negotiated MTU (starts at default)
        self.sock = None
        self.conn = None
        self.conn_addr = None
        self._running = False
        self._thread = None
        self._notification_handles = set()  # CCCD-enabled handles
        self._client_cccds = {}            # Client address -> CCCD-enabled handles (persisted for bonding)
        self.notification_count = 0
        self._on_connection = None
        self._on_disconnection = None
        # Diagnostic counters
        self._diag_notif_sent = defaultdict(int)     # handle -> count of sent notifications
        self._diag_notif_dropped = defaultdict(int)  # handle -> count of dropped (no CCCD) notifications
        self._diag_writes = []                        # list of (timestamp, handle, uuid_hex, value_hex)
        self._diag_cccd_events = []                   # list of (timestamp, cccd_handle, value_handle, enabled)
        self._on_cccd_enabled = None

    def start(self):
        """Create socket, bind, listen. Loops to accept connections."""
        self._create_socket()
        self._running = True
        
        while self._running:
            print(f"[att] Listening for connection on {self.address} CID {BT_ATT_CID}...")
            try:
                self.conn, self.conn_addr = self.sock.accept()
                print(f"[att] Client connected: {self.conn_addr}")


                
                # Reset MTU to default for new connection
                self.mtu = 23
                
                # Reset diagnostic counters for new connection
                self._diag_notif_sent.clear()
                self._diag_notif_dropped.clear()
                self._diag_writes.clear()
                self._diag_cccd_events.clear()
                
                # Restore CCCD states for this client if they are bonded/known
                client_ip = self.conn_addr[0] if self.conn_addr else "unknown"
                self._notification_handles = self._client_cccds.setdefault(client_ip, set())
                if self._notification_handles:
                    print(f"[att] Restored CCCD handles for {client_ip}: {[f'0x{h:04x}' for h in self._notification_handles]}")
                    # Notify application that CCCDs are already enabled
                    if self._on_cccd_enabled:
                        for handle in self._notification_handles:
                            self._on_cccd_enabled(handle)
                
                if self._on_connection:
                    self._on_connection(self.conn_addr)

                self._pdu_loop()
                
                # Clean up connection
                try:
                    self.conn.close()
                except Exception:
                    pass
                self.conn = None
                
            except Exception as e:
                if self._running:
                    print(f"[att] Accept/Connection error: {e}")
                    time.sleep(1)

    def start_async(self):
        """Start in a background thread."""
        self._thread = threading.Thread(target=self.start, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the server."""
        self._running = False
        if self.conn:
            try:
                self.conn.close()
            except Exception:
                pass
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass

    def _create_socket(self):
        """Create and bind the raw L2CAP ATT socket."""
        self.sock = socket.socket(AF_BLUETOOTH, socket.SOCK_SEQPACKET, BTPROTO_L2CAP)

        # NOTE: Do NOT set BT_SECURITY_MEDIUM — it causes BlueZ HOG profile
        # to require encryption for SET_REPORT, resulting in
        # "Encryption Key Size is insufficient" errors. BT_SECURITY_LOW
        # allows unencrypted ATT operations which is what we need.

        # Build sockaddr_l2: family(2) + psm(2) + bdaddr(6) + cid(2) + addr_type(1)
        addr_bytes = bytes.fromhex(self.address.replace(':', ''))[::-1]
        sockaddr = struct.pack('<HH6sHB',
            AF_BLUETOOTH,
            0,                  # psm (0 for fixed CID)
            addr_bytes,         # bdaddr
            BT_ATT_CID,         # cid = 4 (ATT)
            BDADDR_LE_RANDOM    # addr_type
        )

        # Use ctypes bind() because Python 3.13 doesn't support BLE addr types
        result = _libc.bind(
            self.sock.fileno(),
            ctypes.create_string_buffer(sockaddr),
            len(sockaddr)
        )
        if result != 0:
            err = ctypes.get_errno()
            raise OSError(err, f"bind failed: {err}")

        self.sock.listen(1)

    def _pdu_loop(self):
        """Main loop: read ATT PDUs and send responses."""
        while self._running:
            try:
                data = self.conn.recv(self.mtu + 3)
                if not data:
                    break
                self._handle_pdu(data)
            except Exception as e:
                if self._running:
                    print(f"[att] PDU error: {e}")
                break

        print("[att] Client disconnected")
        self._print_diag_summary()
        if self._on_disconnection:
            self._on_disconnection(self.conn_addr)
        # Reset local active notification handles to empty set, but do not clear
        # the client's persisted configuration in self._client_cccds.
        self._notification_handles = set()

    def _handle_pdu(self, data):
        """Parse ATT opcode and dispatch to handler."""
        opcode = data[0]
        print(f"[att] PDU recv: opcode=0x{opcode:02x} len={len(data)} data={data.hex()}")

        if opcode == ATT_OP_MTU_REQ:
            self._handle_mtu_req(data)
        elif opcode == ATT_OP_READ_BY_GROUP_TYPE_REQ:
            self._handle_read_by_group_type(data)
        elif opcode == ATT_OP_READ_BY_TYPE_REQ:
            self._handle_read_by_type(data)
        elif opcode == ATT_OP_FIND_INFO_REQ:
            self._handle_find_info(data)
        elif opcode == ATT_OP_READ_REQ:
            self._handle_read(data)
        elif opcode == ATT_OP_READ_BLOB_REQ:
            self._handle_read_blob(data)
        elif opcode == ATT_OP_WRITE_REQ:
            self._handle_write(data)
        elif opcode == ATT_OP_WRITE_CMD:
            self._handle_write_cmd(data)
        elif opcode == ATT_OP_HANDLE_CNF:
            pass  # Confirmation of our indication — no action needed
        else:
            self._send_error(opcode, 0x0000, ATT_ERR_REQ_NOT_SUPP)

    def _handle_mtu_req(self, data):
        """Handle Exchange MTU Request (0x02)."""
        client_mtu = struct.unpack('<H', data[1:3])[0]
        self.mtu = min(client_mtu, self.server_mtu)
        self.mtu = max(self.mtu, 23)  # Minimum MTU is 23
        print(f"[att] MTU exchange: client={client_mtu}, server={self.server_mtu}, negotiated={self.mtu}")
        resp = struct.pack('<BH', ATT_OP_MTU_RSP, self.server_mtu)
        self._send(resp)

    def _handle_read_by_group_type(self, data):
        """Handle Read By Group Type Request (0x10) — service discovery."""
        # Format: opcode(1) + start_handle(2) + end_handle(2) + [uuid(2 or 16)]
        opcode = data[0]
        start_handle = struct.unpack('<H', data[1:3])[0]
        end_handle = struct.unpack('<H', data[3:5])[0]

        uuid_filter = None
        if len(data) >= 7:
            uuid_bytes = data[5:]
            if len(uuid_bytes) == 2:
                uuid_filter = uuid_bytes

        print(f"[att] ReadByGroupType: start=0x{start_handle:04x} end=0x{end_handle:04x} uuid_filter={uuid_filter.hex() if uuid_filter else None}")

        # Find matching services
        services = self.db.find_services(start_handle, end_handle, uuid_filter)

        if not services:
            print(f"[att] No services found, sending error")
            self._send_error(opcode, start_handle, ATT_ERR_ATTR_NOT_FOUND)
            return

        print(f"[att] Found {len(services)} services")
        # Build response: each service is handle(2) + end_handle(2) + uuid(2)
        # Build response: each service is handle(2) + end_handle(2) + uuid
        # Note: all returned services in a single RSP must be of the same length.
        first_svc_uuid_len = len(services[0][2])
        attr_list = b''
        for svc_start, svc_end, svc_uuid in services:
            if len(svc_uuid) != first_svc_uuid_len:
                break
            entry = struct.pack('<HH', svc_start, svc_end) + svc_uuid
            print(f"  Service: start=0x{svc_start:04x} end=0x{svc_end:04x} uuid={svc_uuid.hex()}")
            attr_list += entry

        # Response format: opcode(1) + length(1) + data
        length = 4 + first_svc_uuid_len  # 4 bytes handles + UUID length
        resp = struct.pack('<BB', ATT_OP_READ_BY_GROUP_TYPE_RSP, length) + attr_list
        print(f"[att] Sending ReadByGroupType response: {resp.hex()}")
        self._send(resp)

    def _handle_read_by_type(self, data):
        """Handle Read By Type Request (0x08) — characteristic discovery."""
        opcode = data[0]
        start_handle = struct.unpack('<H', data[1:3])[0]
        end_handle = struct.unpack('<H', data[3:5])[0]

        uuid_filter = None
        if len(data) >= 7:
            uuid_bytes = data[5:]
            if len(uuid_bytes) == 2:
                uuid_filter = uuid_bytes

        print(f"[att] ReadByType: start=0x{start_handle:04x} end=0x{end_handle:04x} uuid_filter={uuid_filter.hex() if uuid_filter else None}")

        # Find matching characteristics
        chars = self.db.find_characteristics(start_handle, end_handle, uuid_filter)

        if not chars:
            print(f"[att] No characteristics found, sending error")
            self._send_error(opcode, start_handle, ATT_ERR_ATTR_NOT_FOUND)
            return

        print(f"[att] Found {len(chars)} characteristics")
        # Build response: each char is decl_handle(2) + properties(1) + value_handle(2) + uuid
        # Note: all returned characteristics in a single RSP must be of the same length.
        first_char_uuid_len = len(chars[0][3])
        attr_list = b''
        for decl_handle, val_handle, props, char_uuid in chars:
            if len(char_uuid) != first_char_uuid_len:
                break
            entry = struct.pack('<H', decl_handle) + struct.pack('B', props) + struct.pack('<H', val_handle) + char_uuid
            print(f"  Char: decl=0x{decl_handle:04x} val=0x{val_handle:04x} props=0x{props:02x} uuid={char_uuid.hex()}")
            attr_list += entry

        # Response format: opcode(1) + length(1) + data
        length = 5 + first_char_uuid_len  # 2+1+2 + UUID length
        resp = struct.pack('<BB', ATT_OP_READ_BY_TYPE_RSP, length) + attr_list
        print(f"[att] Sending ReadByType response: {resp.hex()}")
        self._send(resp)

    def _handle_find_info(self, data):
        """Handle Find Information Request (0x04) — descriptor discovery."""
        opcode = data[0]
        start_handle = struct.unpack('<H', data[1:3])[0]
        end_handle = struct.unpack('<H', data[3:5])[0]

        descriptors = self.db.find_descriptors(start_handle, end_handle)

        if not descriptors:
            self._send_error(opcode, start_handle, ATT_ERR_ATTR_NOT_FOUND)
            return

        # Build response: must only contain UUIDs of the same length in a single response
        first_uuid_len = len(descriptors[0][1])
        attr_list = b''
        for handle, uuid in descriptors:
            if len(uuid) != first_uuid_len:
                break
            attr_list += struct.pack('<H', handle) + uuid

        # Response format: opcode(1) + format(1) + data
        # format: 0x01 for 16-bit UUIDs, 0x02 for 128-bit UUIDs
        fmt = 0x01 if first_uuid_len == 2 else 0x02
        resp = struct.pack('<BB', ATT_OP_FIND_INFO_RSP, fmt) + attr_list
        print(f"[att] FindInfo: sending response fmt={fmt} len={len(resp)}")
        self._send(resp)

    def _handle_read(self, data):
        """Handle Read Request (0x0A)."""
        import time
        ts = time.strftime('%H:%M:%S')
        opcode = data[0]
        handle = struct.unpack('<H', data[1:3])[0]

        print(f"[att] [{ts}] Read Request: handle=0x{handle:04x}")
        value = self.db.read_attribute(handle)
        if value is None:
            print(f"[att] [{ts}] Read FAILED: handle=0x{handle:04x} -> ERR_INVALID_HANDLE")
            self._send_error(opcode, handle, ATT_ERR_INVALID_HANDLE)
            return

        print(f"[att] Read: handle=0x{handle:04x} len={len(value)} data={value.hex()}")
        resp = struct.pack('B', ATT_OP_READ_RSP) + value
        self._send(resp)

    def _handle_read_blob(self, data):
        """Handle Read Blob Request (0x0C) — for values > MTU."""
        opcode = data[0]
        handle = struct.unpack('<H', data[1:3])[0]
        offset = struct.unpack('<H', data[3:5])[0]

        value = self.db.read_attribute(handle)
        if value is None:
            self._send_error(opcode, handle, ATT_ERR_INVALID_HANDLE)
            return

        if offset >= len(value):
            self._send_error(opcode, handle, ATT_ERR_INVALID_HANDLE)
            return

        resp = struct.pack('B', ATT_OP_READ_BLOB_RSP) + value[offset:]
        self._send(resp)

    def _find_cccd_value_handle(self, cccd_handle):
        """Find the value handle of the characteristic that owns this CCCD.

        Searches backwards from the CCCD handle to find the Characteristic
        Declaration (UUID 0x2803), then extracts the value handle from it.
        """
        for h in range(cccd_handle - 1, 0, -1):
            attr = self.db.lookup(h)
            if attr and attr.uuid == uuid16_to_bytes(GATT_CHARAC_UUID):
                if len(attr.value) >= 5:
                    return attr.value[1] | (attr.value[2] << 8)
        return None

    def _handle_write(self, data):
        """Handle Write Request (0x12)."""
        opcode = data[0]
        handle = struct.unpack('<H', data[1:3])[0]
        value = data[3:]

        attr = self.db.lookup(handle)
        if attr is None:
            print(f"[att] ❌ Write Request FAILED: handle=0x{handle:04x} ERR_INVALID_HANDLE (attr not found)")
            self._send_error(opcode, handle, ATT_ERR_INVALID_HANDLE)
            return

        print(f"[att] ✅ Write Request: handle=0x{handle:04x} uuid={attr.uuid.hex()} len={len(value)} data={value.hex()}")
        
        # Record all writes for diagnostics
        ts = time.strftime('%H:%M:%S')
        self._diag_writes.append((ts, handle, attr.uuid.hex(), value.hex()))
        
        cccd_uuid = uuid16_to_bytes(0x2902)
        enable_handle = None
        if attr.uuid == cccd_uuid:
            ccc_value = struct.unpack('<H', value[:2])[0] if len(value) >= 2 else 0
            value_handle = self._find_cccd_value_handle(handle)
            if value_handle is not None:
                enabled = bool(ccc_value & 0x0001)
                if enabled:
                    self._notification_handles.add(value_handle)
                    print(f"[DIAG] ✅ CCCD ENABLED: cccd=0x{handle:04x} → value_handle=0x{value_handle:04x} (ccc=0x{ccc_value:04x})")
                    enable_handle = value_handle
                else:
                    self._notification_handles.discard(value_handle)
                    print(f"[DIAG] ❌ CCCD DISABLED: cccd=0x{handle:04x} → value_handle=0x{value_handle:04x} (ccc=0x{ccc_value:04x})")
                self._diag_cccd_events.append((ts, handle, value_handle, enabled))
                self._print_active_subscriptions()
            else:
                print(f"[att] Warning: could not find value handle for CCCD 0x{handle:04x}")
        else:
            # Non-CCCD write — log prominently for feature reports
            print(f"[DIAG] 📝 WRITE to handle=0x{handle:04x} uuid={attr.uuid.hex()} data={value.hex()}")

        self.db.write_attribute(handle, value)
        resp = struct.pack('B', ATT_OP_WRITE_RSP)
        self._send(resp)

        if enable_handle is not None and self._on_cccd_enabled:
            self._on_cccd_enabled(enable_handle)

    def _handle_write_cmd(self, data):
        """Handle Write Command (0x52) — no response."""
        opcode = data[0]
        handle = struct.unpack('<H', data[1:3])[0]
        value = data[3:]

        attr = self.db.lookup(handle)
        if attr:
            print(f"[att] ✅ Write Command: handle=0x{handle:04x} uuid={attr.uuid.hex()} len={len(value)} data={value.hex()}")
            self.db.write_attribute(handle, value)
        else:
            print(f"[att] ❌ Write Command FAILED: handle=0x{handle:04x} ERR_INVALID_HANDLE (attr not found)")

    def _send_error(self, request_opcode, handle, error_code):
        """Send ATT Error Response."""
        resp = struct.pack('<BBHB', ATT_OP_ERROR, request_opcode, handle, error_code)
        self._send(resp)

    def _send(self, data):
        """Send raw bytes to the connected client."""
        if self.conn:
            try:
                sent = self.conn.send(data)
                return sent
            except Exception as e:
                print(f"[att] Send error: {e}")
                return 0
        return 0

    def send_notification(self, handle, value):
        """
        Send ATT Handle Value Notification.

        Args:
            handle: Attribute handle
            value: Notification value bytes
        """
        if handle not in self._notification_handles:
            self._diag_notif_dropped[handle] += 1
            # Log first drop and then every 200th drop per handle
            count = self._diag_notif_dropped[handle]
            if count == 1 or count % 200 == 0:
                print(f"[DIAG] 🚫 NOTIFICATION DROPPED (no CCCD): handle=0x{handle:04x} len={len(value)} (dropped {count}x total)")
                print(f"[DIAG]    Active subscriptions: {[f'0x{h:04x}' for h in sorted(self._notification_handles)]}")
            return

        pdu = struct.pack('<BH', ATT_OP_HANDLE_NFY, handle) + value
        sent = self._send(pdu)
        self.notification_count += 1
        self._diag_notif_sent[handle] += 1
        
        # Log mouse/keyboard (len <= 8) immediately, and gamepad (len > 8) throttled
        if len(value) <= 8 or (self.notification_count % 100 == 0):
            print(f"[att] Notification sent: handle=0x{handle:04x} len={len(value)} value={value.hex()}")

    def print_active_subscriptions(self):
        """Public method to print current CCCD subscription state."""
        self._print_active_subscriptions()

    def _print_active_subscriptions(self):
        """Print which handles currently have active CCCD subscriptions."""
        handle_names = {
            0x0012: 'Gamepad(ID1)',
            0x0019: 'Mouse(ID3)',
            0x001D: 'Keyboard(ID4)',
            0x0031: 'SC2_Custom_CH1',
            0x0034: 'SC2_Custom_CH2',
        }
        if self._notification_handles:
            labels = [f'0x{h:04x}({handle_names.get(h, "?")})'for h in sorted(self._notification_handles)]
            print(f"[DIAG] 📋 Active CCCD subscriptions: {labels}")
        else:
            print(f"[DIAG] 📋 Active CCCD subscriptions: (none)")

    def _print_diag_summary(self):
        """Print diagnostic summary at disconnect."""
        print("\n" + "=" * 70)
        print("[DIAG] === DIAGNOSTIC SUMMARY (connection ended) ===")
        print("=" * 70)
        
        # CCCD events
        print(f"\n[DIAG] CCCD Events ({len(self._diag_cccd_events)} total):")
        handle_names = {
            0x0012: 'Gamepad(ID1)', 0x0014: 'Gamepad_CCCD',
            0x0019: 'Mouse(ID3)', 0x001B: 'Mouse_CCCD',
            0x001D: 'Keyboard(ID4)', 0x001F: 'Keyboard_CCCD',
            0x0027: 'Feature_0x85',
            0x0031: 'SC2_Custom_CH1', 0x0032: 'SC2_CH1_CCCD',
            0x0034: 'SC2_Custom_CH2', 0x0035: 'SC2_CH2_CCCD',
        }
        for ts, cccd_h, val_h, enabled in self._diag_cccd_events:
            status = '✅ ENABLED' if enabled else '❌ DISABLED'
            name = handle_names.get(val_h, '?')
            print(f"  {ts}  CCCD 0x{cccd_h:04x} → 0x{val_h:04x} ({name}) {status}")
        
        # Non-CCCD writes (feature reports etc)
        non_cccd_writes = [(ts, h, u, v) for ts, h, u, v in self._diag_writes 
                           if h not in {e[1] for e in self._diag_cccd_events}]
        if non_cccd_writes:
            print(f"\n[DIAG] Non-CCCD Writes ({len(non_cccd_writes)} total):")
            for ts, h, uuid_hex, val_hex in non_cccd_writes:
                name = handle_names.get(h, '?')
                print(f"  {ts}  handle=0x{h:04x} ({name}) data={val_hex}")
        
        # Notification stats
        print(f"\n[DIAG] Notifications Sent:")
        for h in sorted(self._diag_notif_sent.keys()):
            name = handle_names.get(h, '?')
            print(f"  0x{h:04x} ({name}): {self._diag_notif_sent[h]}")
        if not self._diag_notif_sent:
            print("  (none)")
        
        print(f"\n[DIAG] Notifications DROPPED (no CCCD):")
        for h in sorted(self._diag_notif_dropped.keys()):
            name = handle_names.get(h, '?')
            print(f"  0x{h:04x} ({name}): {self._diag_notif_dropped[h]}")
        if not self._diag_notif_dropped:
            print("  (none)")
        
        print("=" * 70 + "\n")

    @property
    def connected(self):
        return self.conn is not None
