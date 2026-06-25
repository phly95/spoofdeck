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
CHR_SERIAL_NUMBER = 0x2A25
CHR_FIRMWARE_REVISION = 0x2A26
CHR_HARDWARE_REVISION = 0x2A27
CHR_SOFTWARE_REVISION = 0x2A28

# Descriptor UUIDs
DESC_REPORT_REF = 0x2908
DESC_CCCD = 0x2902

# Custom Valve SC2 UUIDs
SC2_HID_SERVICE_UUID = "100f6c32-1735-4313-b402-38567131e5f3"
SC2_INPUT_CH1_UUID = "100f6c7a-1735-4313-b402-38567131e5f3"
SC2_INPUT_CH2_UUID = "100f6c7c-1735-4313-b402-38567131e5f3"
SC2_REPORT_CH_UUID = "100f6c34-1735-4313-b402-38567131e5f3"


def uuid16_to_bytes(uuid16):
    """Convert 16-bit UUID to 2-byte little-endian."""
    return struct.pack('<H', uuid16)


def uuid128_to_bytes(uuid128_str):
    """Convert UUID string to 16-byte little-endian."""
    import uuid
    u = uuid.UUID(uuid128_str)
    return u.bytes_le


def uuid_to_bytes(uuid_val):
    """Convert UUID (int, str, or bytes) to bytes (2 or 16)."""
    if isinstance(uuid_val, int):
        return struct.pack('<H', uuid_val)
    elif isinstance(uuid_val, str):
        return uuid128_to_bytes(uuid_val)
    elif isinstance(uuid_val, bytes):
        return uuid_val
    raise ValueError(f"Invalid UUID: {uuid_val}")


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
        self.read_callbacks = {}   # handle -> callable returning bytes
        self.write_callbacks = {}  # handle -> callable accepting bytes

    def _alloc_handle(self):
        h = self._next_handle
        self._next_handle += 1
        return h

    def add_service(self, svc_uuid, char_defs):
        """
        Add a GATT service with characteristics.

        Args:
            svc_uuid: Service UUID (16-bit int or 128-bit str/bytes)
            char_defs: List of (uuid, properties, value, [desc_defs])
                where desc_defs is [(desc_uuid, desc_value)]
        """
        svc_uuid_bytes = uuid_to_bytes(svc_uuid)
        
        # Service declaration handle
        svc_handle = self._alloc_handle()
        self.attributes[svc_handle] = Attribute(
            svc_handle, uuid16_to_bytes(GATT_PRIM_SVC_UUID), svc_uuid_bytes
        )

        start_handle = svc_handle

        for char_uuid, properties, value, *rest in char_defs:
            desc_defs = rest[0] if rest else []
            char_uuid_bytes = uuid_to_bytes(char_uuid)

            # Characteristic declaration handle
            decl_handle = self._alloc_handle()
            # Allocate the value handle too
            value_handle = self._alloc_handle()

            # Build characteristic declaration value:
            # properties(1) + value_handle(2) + uuid (2 or 16)
            decl_value = struct.pack('<BB', properties, value_handle & 0xFF)
            decl_value += struct.pack('<B', (value_handle >> 8) & 0xFF)
            decl_value += char_uuid_bytes

            self.attributes[decl_handle] = Attribute(
                decl_handle, uuid16_to_bytes(GATT_CHARAC_UUID), decl_value
            )

            # Characteristic value handle
            self.attributes[value_handle] = Attribute(
                value_handle, char_uuid_bytes, value, properties
            )

            # Descriptors
            for desc_uuid, desc_value in desc_defs:
                desc_handle = self._alloc_handle()
                desc_uuid_bytes = uuid_to_bytes(desc_uuid)
                self.attributes[desc_handle] = Attribute(
                    desc_handle, desc_uuid_bytes, desc_value,
                    properties=ATT_PROP_READ | ATT_PROP_WRITE
                )

        end_handle = self._next_handle - 1
        self.services.append((start_handle, end_handle, svc_uuid_bytes))

    def lookup(self, handle):
        """Look up attribute by handle."""
        return self.attributes.get(handle)

    def read_attribute(self, handle):
        """Read attribute value. Returns bytes or None."""
        if handle in self.read_callbacks:
            try:
                return self.read_callbacks[handle]()
            except Exception as e:
                print(f"[-] Read callback error for handle 0x{handle:04x}: {e}")
        attr = self.attributes.get(handle)
        if attr:
            return attr.value
        return None

    def write_attribute(self, handle, value):
        """Write attribute value. Returns True on success."""
        if handle in self.write_callbacks:
            try:
                self.write_callbacks[handle](value)
            except Exception as e:
                print(f"[-] Write callback error for handle 0x{handle:04x}: {e}")
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
                # Parse declaration: properties(1) + value_handle(2) + uuid
                if len(attr.value) >= 5:
                    props = attr.value[0]
                    val_handle = attr.value[1] | (attr.value[2] << 8)
                    char_uuid = attr.value[3:]
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
        """Build the HID Report Map descriptor for gamepad, mouse, and keyboard."""
        return bytes([
            # --- Gamepad (Report ID 1) & Output (Report ID 2) ---
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
            0xC0,              # End Collection (Gamepad)

            # --- Mouse (Report ID 3) ---
            0x05, 0x01,        # Usage Page (Generic Desktop)
            0x09, 0x02,        # Usage (Mouse)
            0xA1, 0x01,        # Collection (Application)
            0x09, 0x01,        #   Usage (Pointer)
            0xA1, 0x00,        #   Collection (Physical)
            0x85, 0x03,        #     Report ID (3)
            0x05, 0x09,        #     Usage Page (Button)
            0x19, 0x01,        #     Usage Minimum (1)
            0x29, 0x05,        #     Usage Maximum (5)
            0x15, 0x00,        #     Logical Minimum (0)
            0x25, 0x01,        #     Logical Maximum (1)
            0x95, 0x05,        #     Report Count (5)
            0x75, 0x01,        #     Report Size (1)
            0x81, 0x02,        #     Input (Data,Var,Abs)
            0x95, 0x01,        #     Report Count (1)
            0x75, 0x03,        #     Report Size (3)
            0x81, 0x01,        #     Input (Cnst,Var,Abs)
            0x05, 0x01,        #     Usage Page (Generic Desktop)
            0x09, 0x30,        #     Usage (X)
            0x09, 0x31,        #     Usage (Y)
            0x15, 0x81,        #     Logical Minimum (-127)
            0x25, 0x7F,        #     Logical Maximum (127)
            0x75, 0x08,        #     Report Size (8)
            0x95, 0x02,        #     Report Count (2)
            0x81, 0x06,        #     Input (Data,Var,Rel)
            0x09, 0x38,        #     Usage (Wheel)
            0x15, 0x81,        #     Logical Minimum (-127)
            0x25, 0x7F,        #     Logical Maximum (127)
            0x75, 0x08,        #     Report Size (8)
            0x95, 0x01,        #     Report Count (1)
            0x81, 0x06,        #     Input (Data,Var,Rel)
            0xC0,              #   End Collection
            0xC0,              # End Collection

            # --- Keyboard (Report ID 4) ---
            0x05, 0x01,        # Usage Page (Generic Desktop)
            0x09, 0x06,        # Usage (Keyboard)
            0xA1, 0x01,        # Collection (Application)
            0x85, 0x04,        #   Report ID (4)
            0x05, 0x07,        #   Usage Page (Key Codes)
            0x19, 0xE0,        #   Usage Minimum (224)
            0x29, 0xE7,        #   Usage Maximum (231)
            0x15, 0x00,        #   Logical Minimum (0)
            0x25, 0x01,        #   Logical Maximum (1)
            0x75, 0x01,        #   Report Size (1)
            0x95, 0x08,        #   Report Count (8)
            0x81, 0x02,        #   Input (Data,Var,Abs)  ; Modifier byte
            0x95, 0x01,        #   Report Count (1)
            0x75, 0x08,        #   Report Size (8)
            0x81, 0x01,        #   Input (Cnst,Var,Abs)  ; Reserved byte
            0x19, 0x00,        #   Usage Minimum (0)
            0x29, 0x65,        #   Usage Maximum (101)
            0x15, 0x00,        #   Logical Minimum (0)
            0x25, 0x65,        #   Logical Maximum (101)
            0x75, 0x08,        #   Report Size (8)
            0x95, 0x06,        #   Report Count (6)
            0x81, 0x00,        #   Input (Data,Ary,Abs)  ; Key array (6 bytes)
            0xC0,              # End Collection

            # --- SC2 Custom Input Report (Report ID 0x45, 45 bytes) ---
            0x06, 0x01, 0xFF,  # Usage Page (Vendor Defined 0xFF01)
            0x09, 0x45,        # Usage (0x45)
            0xA1, 0x01,        # Collection (Application)
            0x85, 0x45,        #   Report ID (0x45)
            0x75, 0x08,        #   Report Size (8)
            0x95, 0x2D,        #   Report Count (45)
            0x81, 0x02,        #   Input (Data,Var,Abs)
            0xC0,              # End Collection

            # --- SC2 Custom Input Report 2 (Report ID 0x47, 47 bytes) ---
            0x06, 0x01, 0xFF,  # Usage Page (Vendor Defined 0xFF01)
            0x09, 0x47,        # Usage (0x47)
            0xA1, 0x01,        # Collection (Application)
            0x85, 0x47,        #   Report ID (0x47)
            0x75, 0x08,        #   Report Size (8)
            0x95, 0x2F,        #   Report Count (47)
            0x81, 0x02,        #   Input (Data,Var,Abs)
            0xC0,              # End Collection
            0xC0,              # End Collection
        ])


def build_sc2_database(device_name="Steam Controller 2026"):
    """Build the complete SC2 GATT database."""
    db = GattDatabase()

    report_map = db.build_report_map()

    # HID Information: bcdHID=1.11, bCountryCode=0, Flags=0x02 (normally connectable)
    hid_info = bytes([0x11, 0x01, 0x00, 0x02])

    # PnP ID: VID source=USB Forum (0x02), VID=0x28DE, PID=0x1303, version=1.0
    pnp_id = bytes([0x02, 0xDE, 0x28, 0x03, 0x13, 0x00, 0x01])

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
        (CHR_REPORT, ATT_PROP_READ | ATT_PROP_NOTIFY, b'\x00' * 4, [
            (DESC_REPORT_REF, bytes([0x03, 0x01])),  # Report ID 3, Input (Mouse)
            (DESC_CCCD, b'\x00\x00'),
        ]),
        (CHR_REPORT, ATT_PROP_READ | ATT_PROP_NOTIFY, b'\x00' * 8, [
            (DESC_REPORT_REF, bytes([0x04, 0x01])),  # Report ID 4, Input (Keyboard)
            (DESC_CCCD, b'\x00\x00'),
        ]),
        # Feature Reports (Report IDs 0x00, 0x01, 0x85, 0x86, 0x87)
        (CHR_REPORT, ATT_PROP_READ | ATT_PROP_WRITE, b'\x00' * 64, [
            (DESC_REPORT_REF, bytes([0x00, 0x03])),  # Report ID 0x00, Feature
        ]),
        (CHR_REPORT, ATT_PROP_READ | ATT_PROP_WRITE, b'\x00' * 64, [
            (DESC_REPORT_REF, bytes([0x01, 0x03])),  # Report ID 0x01, Feature
        ]),
        (CHR_REPORT, ATT_PROP_READ | ATT_PROP_WRITE, b'\x00' * 64, [
            (DESC_REPORT_REF, bytes([0x85, 0x03])),  # Report ID 0x85, Feature
        ]),
        (CHR_REPORT, ATT_PROP_READ | ATT_PROP_WRITE, b'\x00' * 64, [
            (DESC_REPORT_REF, bytes([0x86, 0x03])),  # Report ID 0x86, Feature
        ]),
        (CHR_REPORT, ATT_PROP_READ | ATT_PROP_WRITE, b'\x00' * 64, [
            (DESC_REPORT_REF, bytes([0x87, 0x03])),  # Report ID 0x87, Feature
        ]),
        # --- SC2 Custom Input Reports (moved from Valve Custom HID Service) ---
        # These MUST be in the HID Service for hog-ll to subscribe to them.
        (CHR_REPORT, ATT_PROP_READ | ATT_PROP_NOTIFY, b'\x00' * 45, [
            (DESC_REPORT_REF, bytes([0x45, 0x01])),  # Report ID 0x45, Input
            (DESC_CCCD, b'\x00\x00'),
        ]),
        (CHR_REPORT, ATT_PROP_READ | ATT_PROP_NOTIFY, b'\x00' * 47, [
            (DESC_REPORT_REF, bytes([0x47, 0x01])),  # Report ID 0x47, Input
            (DESC_CCCD, b'\x00\x00'),
        ]),
    ])

    # Valve Custom HID Service — needed for Steam to identify this as an SC2 device.
    # SC2 Custom CHR_REPORT inputs are also in the HID Service above (for hog-ll subscription).
    # Steam reads from these Valve UUID characteristics directly.
    db.add_service(SC2_HID_SERVICE_UUID, [
        (SC2_INPUT_CH1_UUID, ATT_PROP_READ | ATT_PROP_NOTIFY, b'\x00' * 45, [
            (DESC_CCCD, b'\x00\x00'),
        ]),
        (SC2_INPUT_CH2_UUID, ATT_PROP_READ | ATT_PROP_NOTIFY, b'\x00' * 47, [
            (DESC_CCCD, b'\x00\x00'),
        ]),
        (SC2_REPORT_CH_UUID, ATT_PROP_READ | ATT_PROP_WRITE | ATT_PROP_WRITE_NO_RSP, b'\x00' * 64),
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
        (CHR_SERIAL_NUMBER, ATT_PROP_READ, b'123456789ABCDEF'),
        (CHR_FIRMWARE_REVISION, ATT_PROP_READ, b'1.0.0'),
        (CHR_HARDWARE_REVISION, ATT_PROP_READ, b'1.0.0'),
        (CHR_SOFTWARE_REVISION, ATT_PROP_READ, b'1.0.0'),
        (CHR_PNP_ID, ATT_PROP_READ, pnp_id),
    ])

    return db
