#!/usr/bin/env python3
"""
GATT Database for raw L2CAP ATT server.

Flat handle-based attribute store for BLE GATT services.
No D-Bus dependency — pure Python attribute database.
"""

import struct
from typing import Optional


# ATT constants
ATT_OP_ERROR = 0x01
ATT_OP_MTU_REQ = 0x02
ATT_OP_MTU_RSP = 0x03
ATT_OP_FIND_INFO_REQ = 0x04
ATT_OP_FIND_INFO_RSP = 0x05
ATT_OP_READ_BY_TYPE_REQ = 0x08
ATT_OP_READ_BY_TYPE_RSP = 0x09
ATT_OP_READ_REQ = 0x0A
ATT_OP_READ_RSP = 0x0B
ATT_OP_READ_BLOB_REQ = 0x0C
ATT_OP_READ_BLOB_RSP = 0x0D
ATT_OP_READ_BY_GROUP_TYPE_REQ = 0x10
ATT_OP_READ_BY_GROUP_TYPE_RSP = 0x11
ATT_OP_WRITE_REQ = 0x12
ATT_OP_WRITE_RSP = 0x13
ATT_OP_HANDLE_NFY = 0x1B
ATT_OP_HANDLE_IND = 0x1D
ATT_OP_HANDLE_CNF = 0x1E
ATT_OP_WRITE_CMD = 0x52

# ATT error codes
ATT_ERR_INVALID_HANDLE = 0x01
ATT_ERR_READ_NOT_PERM = 0x02
ATT_ERR_WRITE_NOT_PERM = 0x03
ATT_ERR_INVALID_PDU = 0x04
ATT_ERR_ATTR_NOT_FOUND = 0x0A
ATT_ERR_UNLIKELY = 0x0E
ATT_ERR_REQ_NOT_SUPP = 0x06

# ATT properties (bitmask)
ATT_PROP_READ = 0x02
ATT_PROP_WRITE_NO_RSP = 0x04
ATT_PROP_WRITE = 0x08
ATT_PROP_NOTIFY = 0x10
ATT_PROP_INDICATE = 0x20

# GATT UUIDs (16-bit)
GATT_PRIM_SVC_UUID = 0x2800
GATT_CHARAC_UUID = 0x2803
GATT_CLIENT_CHARAC_CFG_UUID = 0x2902
GATT_CHARAC_USER_DESC_UUID = 0x2901

# Standard service UUIDs
SVC_GAP = 0x1800
SVC_GATT = 0x1801
SVC_HID = 0x1812
SVC_BATTERY = 0x180F
SVC_DEVICE_INFO = 0x180A

# Standard characteristic UUIDs
CHR_DEVICE_NAME = 0x2A00
CHR_APPEARANCE = 0x2A01
CHR_SERVICE_CHANGED = 0x2A05
CHR_HID_INFO = 0x2A4A
CHR_REPORT_MAP = 0x2A4B
CHR_HID_CONTROL_POINT = 0x2A4C
CHR_REPORT = 0x2A4D
CHR_BATTERY_LEVEL = 0x2A19
CHR_MANUFACTURER_NAME = 0x2A29
CHR_MODEL_NUMBER = 0x2A24
CHR_PNP_ID = 0x2A50

# Descriptor UUIDs
DESC_REPORT_REF = 0x2908
DESC_CCCD = 0x2902


def uuid16_to_bytes(uuid16):
    """Convert 16-bit UUID to 2-byte little-endian."""
    return struct.pack('<H', uuid16)


def uuid128_to_bytes(uuid128_str):
    """Convert UUID string to 16-byte little-endian."""
    import uuid
    u = uuid.UUID(uuid128_str)
    return u.bytes_le


class Attribute:
    """A single GATT attribute."""

    def __init__(self, handle, uuid, value, properties=0, descriptors=None):
        self.handle = handle
        self.uuid = uuid  # bytes (2 or 16)
        self.value = value  # bytes
        self.properties = properties  # bitmask
        self.descriptors = descriptors or []  # list of Attribute

    def __repr__(self):
        return f"Attr(0x{self.handle:04x}, uuid={self.uuid.hex()}, len={len(self.value)})"


class GattDatabase:
    """
    Flat handle-based GATT attribute database.

    Attributes are stored in a dict keyed by handle (int).
    Handle ranges define services.
    """

    def __init__(self):
        self.attributes = {}  # handle -> Attribute
        self.services = []  # list of (start_handle, end_handle, uuid)
        self._next_handle = 1

    def _alloc_handle(self):
        h = self._next_handle
        self._next_handle += 1
        return h

    def add_service(self, svc_uuid_16, char_defs):
        """
        Add a GATT service with characteristics.

        Args:
            svc_uuid_16: Service UUID (16-bit)
            char_defs: List of (uuid_16, properties, value, [desc_defs])
                where desc_defs is [(desc_uuid_16, desc_value)]
        """
        # Service declaration handle
        svc_handle = self._alloc_handle()
        svc_value = struct.pack('<H', svc_uuid_16)
        self.attributes[svc_handle] = Attribute(
            svc_handle, uuid16_to_bytes(GATT_PRIM_SVC_UUID), svc_value
        )

        start_handle = svc_handle

        for uuid_16, properties, value, *rest in char_defs:
            desc_defs = rest[0] if rest else []

            # Characteristic declaration handle
            decl_handle = self._alloc_handle()
            # Allocate the value handle too
            value_handle = self._alloc_handle()

            # Build characteristic declaration value:
            # properties(1) + value_handle(2) + uuid(2)
            decl_value = struct.pack('<BB', properties, value_handle & 0xFF)
            decl_value += struct.pack('<B', (value_handle >> 8) & 0xFF)
            decl_value += uuid16_to_bytes(uuid_16)

            self.attributes[decl_handle] = Attribute(
                decl_handle, uuid16_to_bytes(GATT_CHARAC_UUID), decl_value
            )

            # Characteristic value handle
            self.attributes[value_handle] = Attribute(
                value_handle, uuid16_to_bytes(uuid_16), value, properties
            )

            # Descriptors
            for desc_uuid, desc_value in desc_defs:
                desc_handle = self._alloc_handle()
                self.attributes[desc_handle] = Attribute(
                    desc_handle, uuid16_to_bytes(desc_uuid), desc_value,
                    properties=ATT_PROP_READ | ATT_PROP_WRITE
                )

        end_handle = self._next_handle - 1
        self.services.append((start_handle, end_handle, svc_uuid_16))

    def lookup(self, handle):
        """Look up attribute by handle."""
        return self.attributes.get(handle)

    def read_attribute(self, handle):
        """Read attribute value. Returns bytes or None."""
        attr = self.attributes.get(handle)
        if attr:
            return attr.value
        return None

    def write_attribute(self, handle, value):
        """Write attribute value. Returns True on success."""
        attr = self.attributes.get(handle)
        if attr:
            attr.value = value
            return True
        return False

    def find_services(self, start_handle, end_handle, uuid_filter=None):
        """Find all primary services in handle range.

        uuid_filter is the ATTRIBUTE TYPE UUID (e.g., 0x2800 for Primary Service).
        All services have a declaration with this UUID, so the filter always matches
        when querying for service declarations.
        """
        results = []
        # uuid_filter is the attribute type we're searching for (e.g., 0x2800)
        # All services are Primary Service declarations, so if the filter is
        # the Primary Service UUID, return all services in range
        if uuid_filter is not None and uuid_filter != uuid16_to_bytes(GATT_PRIM_SVC_UUID):
            return results  # Not searching for services

        for svc_start, svc_end, svc_uuid in self.services:
            if svc_start >= start_handle and svc_end <= end_handle:
                results.append((svc_start, svc_end, svc_uuid))
        return results

    def find_characteristics(self, start_handle, end_handle, uuid_filter=None):
        """Find all characteristics in handle range.

        uuid_filter is the ATTRIBUTE TYPE UUID (e.g., 0x2803 for Characteristic Declaration).
        All characteristics have a declaration with this UUID.
        """
        # If filtering by attribute type, only return if it's the Characteristic Declaration UUID
        if uuid_filter is not None and uuid_filter != uuid16_to_bytes(GATT_CHARAC_UUID):
            return []

        results = []
        for handle in sorted(self.attributes.keys()):
            if handle < start_handle or handle > end_handle:
                continue
            attr = self.attributes[handle]
            if attr.uuid == uuid16_to_bytes(GATT_CHARAC_UUID):
                # Parse declaration: properties(1) + value_handle(2) + uuid(2)
                if len(attr.value) >= 5:
                    props = attr.value[0]
                    val_handle = attr.value[1] | (attr.value[2] << 8)
                    char_uuid = attr.value[3:5]
                    results.append((handle, val_handle, props, char_uuid))
        return results

    def find_descriptors(self, start_handle, end_handle):
        """Find all descriptors in handle range."""
        results = []
        for handle in sorted(self.attributes.keys()):
            if handle < start_handle or handle > end_handle:
                continue
            attr = self.attributes[handle]
            # Descriptors are not service declarations or characteristic declarations
            if attr.uuid != uuid16_to_bytes(GATT_PRIM_SVC_UUID) and \
               attr.uuid != uuid16_to_bytes(GATT_CHARAC_UUID):
                results.append((handle, attr.uuid))
        return results

    def build_report_map(self):
        """Build the HID Report Map descriptor for a gamepad."""
        return bytes([
            0x05, 0x01,        # Usage Page (Generic Desktop)
            0x09, 0x05,        # Usage (Gamepad)
            0xA1, 0x01,        # Collection (Application)
            0x85, 0x01,        #   Report ID (1)
            0x05, 0x09,        #   Usage Page (Button)
            0x19, 0x01,        #   Usage Minimum (1)
            0x29, 0x10,        #   Usage Maximum (16)
            0x15, 0x00,        #   Logical Minimum (0)
            0x25, 0x01,        #   Logical Maximum (1)
            0x75, 0x01,        #   Report Size (1)
            0x95, 0x10,        #   Report Count (16)
            0x81, 0x02,        #   Input (Data,Var,Abs)
            0x05, 0x01,        #   Usage Page (Generic Desktop)
            0x09, 0x30,        #   Usage (X)
            0x09, 0x31,        #   Usage (Y)
            0x09, 0x33,        #   Usage (Rx)
            0x09, 0x34,        #   Usage (Ry)
            0x16, 0x00, 0x80,  #   Logical Minimum (-32768)
            0x26, 0xFF, 0x7F,  #   Logical Maximum (32767)
            0x75, 0x10,        #   Report Size (16)
            0x95, 0x04,        #   Report Count (4)
            0x81, 0x02,        #   Input (Data,Var,Abs)
            0x09, 0x32,        #   Usage (Z)
            0x09, 0x35,        #   Usage (Rz)
            0x15, 0x00,        #   Logical Minimum (0)
            0x26, 0xFF, 0x00,  #   Logical Maximum (255)
            0x75, 0x08,        #   Report Size (8)
            0x95, 0x02,        #   Report Count (2)
            0x81, 0x02,        #   Input (Data,Var,Abs)
            0x85, 0x02,        #   Report ID (2)
            0x09, 0x20,        #   Usage (Survey)
            0x15, 0x00,        #   Logical Minimum (0)
            0x26, 0xFF, 0x00,  #   Logical Maximum (255)
            0x75, 0x08,        #   Report Size (8)
            0x95, 0x01,        #   Report Count (1)
            0x91, 0x02,        #   Output (Data,Var,Abs)
            0xC0,              # End Collection
        ])


def build_sc2_database(device_name="Steam Controller 2026"):
    """Build the complete SC2 GATT database."""
    db = GattDatabase()

    report_map = db.build_report_map()

    # HID Information: bcdHID=1.11, bCountryCode=0, Flags=0x02 (normally connectable)
    hid_info = bytes([0x11, 0x01, 0x00, 0x02])

    # PnP ID: VID source=BT SIG, VID=0x28DE, PID=0x0003, version=1.0
    pnp_id = bytes([0x01, 0xDE, 0x28, 0x03, 0x03, 0x00, 0x01, 0x00])

    # GAP Service (0x1800)
    db.add_service(SVC_GAP, [
        (CHR_DEVICE_NAME, ATT_PROP_READ, device_name.encode('utf-8')),
        (CHR_APPEARANCE, ATT_PROP_READ, struct.pack('<H', 0x03C4)),  # Gamepad
    ])

    # GATT Service (0x1801)
    db.add_service(SVC_GATT, [
        (CHR_SERVICE_CHANGED, ATT_PROP_INDICATE, b'\x00\x00\xff\xff', [
            (DESC_CCCD, b'\x00\x00'),
        ]),
    ])

    # HID Service (0x1812)
    db.add_service(SVC_HID, [
        (CHR_HID_INFO, ATT_PROP_READ, hid_info),
        (CHR_REPORT_MAP, ATT_PROP_READ, report_map),
        (CHR_HID_CONTROL_POINT, ATT_PROP_WRITE_NO_RSP, b'\x00'),
        (CHR_REPORT, ATT_PROP_READ | ATT_PROP_NOTIFY, b'\x00' * 12, [
            (DESC_REPORT_REF, bytes([0x01, 0x01])),  # Report ID 1, Input
            (DESC_CCCD, b'\x00\x00'),
        ]),
        (CHR_REPORT, ATT_PROP_READ | ATT_PROP_WRITE_NO_RSP, b'\x00', [
            (DESC_REPORT_REF, bytes([0x02, 0x02])),  # Report ID 2, Output
        ]),
    ])

    # Battery Service (0x180F)
    db.add_service(SVC_BATTERY, [
        (CHR_BATTERY_LEVEL, ATT_PROP_READ | ATT_PROP_NOTIFY, bytes([100]), [
            (DESC_CCCD, b'\x00\x00'),
        ]),
    ])

    # Device Information Service (0x180A)
    db.add_service(SVC_DEVICE_INFO, [
        (CHR_MANUFACTURER_NAME, ATT_PROP_READ, b'Valve Software'),
        (CHR_MODEL_NUMBER, ATT_PROP_READ, b'Steam Controller 2026'),
        (CHR_PNP_ID, ATT_PROP_READ, pnp_id),
    ])

    return db
