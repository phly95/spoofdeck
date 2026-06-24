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
        self.notification_count = 0
        self._on_connection = None
        self._on_disconnection = None
        self._on_cccd_enabled = None

    def start(self):
        """Create socket, bind, listen. Blocks until a client connects."""
        self._create_socket()
        self._running = True
        print(f"[att] Listening on {self.address} CID {BT_ATT_CID}")
        self.conn, self.conn_addr = self.sock.accept()
        print(f"[att] Client connected: {self.conn_addr}")

        # Note: BT_SECURITY setsockopt is not supported on fixed-CID L2CAP
        # sockets (CID 4). SMP pairing is handled by the kernel on CID 6.
        if self._on_connection:
            self._on_connection(self.conn_addr)

        self._pdu_loop()

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
        if self._on_disconnection:
            self._on_disconnection(self.conn_addr)
        self._notification_handles.clear()

    def _handle_pdu(self, data):
        """Parse ATT opcode and dispatch to handler."""
        opcode = data[0]
        print(f"[att] PDU recv: opcode=0x{opcode:02x} len={len(data)} data={data[:20].hex()}")

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
        opcode = data[0]
        handle = struct.unpack('<H', data[1:3])[0]

        value = self.db.read_attribute(handle)
        if value is None:
            print(f"[att] Read FAILED: handle=0x{handle:04x} -> ERR_INVALID_HANDLE")
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
            self._send_error(opcode, handle, ATT_ERR_INVALID_HANDLE)
            return

        print(f"[att] Write: handle=0x{handle:04x} uuid={attr.uuid.hex()} len={len(value)} data={value.hex()}")
        cccd_uuid = uuid16_to_bytes(0x2902)
        enable_handle = None
        if attr.uuid == cccd_uuid:
            ccc_value = struct.unpack('<H', value[:2])[0] if len(value) >= 2 else 0
            value_handle = self._find_cccd_value_handle(handle)
            if value_handle is not None:
                if ccc_value & 0x0001:
                    self._notification_handles.add(value_handle)
                    print(f"[att] Notifications enabled for handle 0x{value_handle:04x}")
                    enable_handle = value_handle
                else:
                    self._notification_handles.discard(value_handle)
                    print(f"[att] Notifications disabled for handle 0x{value_handle:04x}")
            else:
                print(f"[att] Warning: could not find value handle for CCCD 0x{handle:04x}")

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
            print(f"[att] Write Cmd: handle=0x{handle:04x} uuid={attr.uuid.hex()} len={len(value)} data={value.hex()}")
            self.db.write_attribute(handle, value)

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
            return  # Notifications not enabled for this handle

        pdu = struct.pack('<BH', ATT_OP_HANDLE_NFY, handle) + value
        sent = self._send(pdu)
        self.notification_count += 1
        if self.notification_count % 100 == 0:
            print(f"[att] Notification sent (throttled): handle=0x{handle:04x} len={len(value)} count={self.notification_count}")

    @property
    def connected(self):
        return self.conn is not None
