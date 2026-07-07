#!/usr/bin/env python3
"""
Virtual USB Steam Controller 2 using vhci_hcd + USB/IP protocol.

Creates a full virtual USB composite device (mouse, keyboard, controller)
via the vhci-hcd kernel module, exactly as InputPlumber's steam_deck.rs does.
Steam sees it as a real USB device with proper bInterfaceNumber — unlike UHID.

Usage:
    sudo python3 src/main_virtual_usb.py [--name "Steam Controller 2026"]
"""

import argparse
import ctypes
import ctypes.util
import fcntl
import json
import os
import signal
import socket
import struct
import sys
import threading
import time

# ---------------------------------------------------------------------------
# USB/IP constants (from linux/usbip.h)
# ---------------------------------------------------------------------------
USBIP_CMD_SUBMIT  = 1
USBIP_CMD_UNLINK  = 2
USBIP_RET_SUBMIT  = 3
USBIP_RET_UNLINK  = 4

USBIP_DIR_OUT = 0
USBIP_DIR_IN  = 1

USB_SPEED_FULL  = 2
USB_SPEED_HIGH  = 3

# USB standard requests
USB_REQ_GET_STATUS        = 0
USB_REQ_CLEAR_FEATURE     = 1
USB_REQ_SET_FEATURE       = 3
USB_REQ_SET_ADDRESS       = 5
USB_REQ_GET_DESCRIPTOR    = 6
USB_REQ_SET_DESCRIPTOR    = 7
USB_REQ_GET_CONFIGURATION = 8
USB_REQ_SET_CONFIGURATION = 9

# USB descriptor types
USB_DESC_DEVICE            = 1
USB_DESC_CONFIGURATION     = 2
USB_DESC_STRING            = 3
USB_DESC_INTERFACE         = 4
USB_DESC_ENDPOINT          = 5
USB_DESC_HID               = 0x21
USB_DESC_HID_REPORT        = 0x22

# HID class codes
HID_GET_REPORT  = 0x01
HID_SET_IDLE    = 0x0A
HID_SET_REPORT  = 0x09

# HID report types
HID_REPORT_TYPE_INPUT   = 1
HID_REPORT_TYPE_OUTPUT  = 2
HID_REPORT_TYPE_FEATURE = 3

# SC2 VID/PID (same as InputPlumber uses for Steam Deck)
SC2_VID = 0x28DE
SC2_PID = 0x1205

# Structured protocol logging
_PROTO_LOG = os.environ.get('SPOOFDECK_PROTO_LOG', '') == '1'

def _proto_log(event, **kwargs):
    if not _PROTO_LOG:
        return
    entry = {"ts": round(time.monotonic(), 3), "event": event}
    entry.update(kwargs)
    try:
        print(json.dumps(entry), flush=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# HID Report Descriptors (same as InputPlumber's report_descriptor.rs)
# ---------------------------------------------------------------------------

MOUSE_DESCRIPTOR = bytes([
    0x05, 0x01,        # Usage Page (Generic Desktop)
    0x09, 0x02,        # Usage (Mouse)
    0xa1, 0x01,        # Collection (Application)
    0x09, 0x01,        #  Usage (Pointer)
    0xa1, 0x00,        #  Collection (Physical)
    0x05, 0x09,        #   Usage Page (Button)
    0x19, 0x01,        #   Usage Minimum (1)
    0x29, 0x02,        #   Usage Maximum (2)
    0x15, 0x00,        #   Logical Minimum (0)
    0x25, 0x01,        #   Logical Maximum (1)
    0x75, 0x01,        #   Report Size (1)
    0x95, 0x02,        #   Report Count (2)
    0x81, 0x02,        #   Input (Data,Var,Abs)
    0x75, 0x06,        #   Report Size (6)
    0x95, 0x01,        #   Report Count (1)
    0x81, 0x01,        #   Input (Cnst,Arr,Abs)
    0x05, 0x01,        #   Usage Page (Generic Desktop)
    0x09, 0x30,        #   Usage (X)
    0x09, 0x31,        #   Usage (Y)
    0x15, 0x81,        #   Logical Minimum (-127)
    0x25, 0x7f,        #   Logical Maximum (127)
    0x75, 0x08,        #   Report Size (8)
    0x95, 0x02,        #   Report Count (2)
    0x81, 0x06,        #   Input (Data,Var,Rel)
    0x95, 0x01,        #   Report Count (1)
    0x09, 0x38,        #   Usage (Wheel)
    0x81, 0x06,        #   Input (Data,Var,Rel)
    0x05, 0x0c,        #   Usage Page (Consumer Devices)
    0x0a, 0x38, 0x02,  #   Usage (AC Pan)
    0x95, 0x01,        #   Report Count (1)
    0x81, 0x06,        #   Input (Data,Var,Rel)
    0xc0,              #  End Collection
    0xc0,              # End Collection
])

KEYBOARD_DESCRIPTOR = bytes([
    0x05, 0x01,        # Usage Page (Generic Desktop)
    0x09, 0x06,        # Usage (Keyboard)
    0xa1, 0x01,        # Collection (Application)
    0x05, 0x07,        #  Usage Page (Keyboard)
    0x19, 0xe0,        #  Usage Minimum (224)
    0x29, 0xe7,        #  Usage Maximum (231)
    0x15, 0x00,        #  Logical Minimum (0)
    0x25, 0x01,        #  Logical Maximum (1)
    0x75, 0x01,        #  Report Size (1)
    0x95, 0x08,        #  Report Count (8)
    0x81, 0x02,        #  Input (Data,Var,Abs)
    0x81, 0x01,        #  Input (Cnst,Arr,Abs)
    0x19, 0x00,        #  Usage Minimum (0)
    0x29, 0x65,        #  Usage Maximum (101)
    0x15, 0x00,        #  Logical Minimum (0)
    0x25, 0x65,        #  Logical Maximum (101)
    0x75, 0x08,        #  Report Size (8)
    0x95, 0x06,        #  Report Count (6)
    0x81, 0x00,        #  Input (Data,Arr,Abs)
    0xc0,              # End Collection
])

CONTROLLER_DESCRIPTOR = bytes([
    0x06, 0xff, 0xff,  # Usage Page (Vendor Usage Page 0xffff)
    0x09, 0x01,        # Usage (Vendor Usage 0x01)
    0xa1, 0x01,        # Collection (Application)
    0x09, 0x02,        #  Usage (Vendor Usage 0x02)
    0x09, 0x03,        #  Usage (Vendor Usage 0x03)
    0x15, 0x00,        #  Logical Minimum (0)
    0x26, 0xff, 0x00,  #  Logical Maximum (255)
    0x75, 0x08,        #  Report Size (8)
    0x95, 0x40,        #  Report Count (64)
    0x81, 0x02,        #  Input (Data,Var,Abs)
    0x09, 0x06,        #  Usage (Vendor Usage 0x06)
    0x09, 0x07,        #  Usage (Vendor Usage 0x07)
    0x15, 0x00,        #  Logical Minimum (0)
    0x26, 0xff, 0x00,  #  Logical Maximum (255)
    0x75, 0x08,        #  Report Size (8)
    0x95, 0x40,        #  Report Count (64)
    0xb1, 0x02,        #  Feature (Data,Var,Abs)
    0xc0,              # End Collection
])


# ---------------------------------------------------------------------------
# USB Descriptors — build the full descriptor tree
# ---------------------------------------------------------------------------

def build_string_descriptor(s):
    """Build a USB string descriptor (2 bytes header + UCS-2 characters)."""
    encoded = s.encode('utf-16-le')
    return bytes([len(encoded) + 2, USB_DESC_STRING]) + encoded

# Pre-built string descriptors:
#   0 = Language ID (English US)
#   1 = Manufacturer
#   2 = Product
#   3 = Serial
STRING_DESCS = [
    bytes([4, USB_DESC_STRING, 0x09, 0x04]),          # English US
    build_string_descriptor("Valve Corporation"),       # Manufacturer
    build_string_descriptor("Steam Controller"),        # Product
    build_string_descriptor("F0000-0000-00000000"),     # Serial
]


def build_device_descriptor():
    """18-byte USB Device Descriptor."""
    desc = bytearray(18)
    desc[0]  = 18          # bLength
    desc[1]  = USB_DESC_DEVICE
    desc[2:4] = struct.pack('<H', 0x0200)  # bcdUSB = 2.00
    desc[4]  = 0x00        # bDeviceClass (UseInterface)
    desc[5]  = 0x00        # bDeviceSubClass
    desc[6]  = 0x00        # bDeviceProtocol
    desc[7]  = 64          # bMaxPacketSize0
    desc[8:10]  = struct.pack('<H', SC2_VID)   # idVendor
    desc[10:12] = struct.pack('<H', SC2_PID)   # idProduct
    desc[12:14] = struct.pack('<H', 0x0100)    # bcdDevice
    desc[14] = 1           # iManufacturer
    desc[15] = 2           # iProduct
    desc[16] = 3           # iSerialNumber
    desc[17] = 1           # bNumConfigurations
    return bytes(desc)


def build_hid_descriptor(report_desc_len):
    """9-byte HID class descriptor."""
    desc = bytearray(9)
    desc[0] = 9            # bLength
    desc[1] = USB_DESC_HID
    desc[2:4] = struct.pack('<H', 0x0111)  # bcdHID = 1.11
    desc[4] = 0            # bCountryCode
    desc[5] = 1            # bNumDescriptors
    desc[6] = USB_DESC_HID_REPORT  # bDescriptorType (Report)
    desc[7:9] = struct.pack('<H', report_desc_len)
    return bytes(desc)


def build_endpoint_descriptor(addr, max_packet_size):
    """7-byte Endpoint Descriptor."""
    desc = bytearray(7)
    desc[0] = 7            # bLength
    desc[1] = USB_DESC_ENDPOINT
    desc[2] = addr         # bEndpointAddress (bit 7 = direction: 1=IN)
    desc[3] = 0x03         # bmAttributes (Interrupt)
    desc[4:6] = struct.pack('<H', max_packet_size)
    desc[6] = 10           # bInterval (10ms)
    return bytes(desc)


def build_configuration_descriptor():
    """Build the full Configuration Descriptor with 3 HID interfaces.

    Layout (same as InputPlumber's steam_deck.rs):
      Interface 0: Mouse   (ep 0x81, 8 bytes)
      Interface 1: Keyboard (ep 0x82, 8 bytes)
      Interface 2: Controller (ep 0x83, 64 bytes)
    """
    parts = []

    # Configuration Descriptor (9 bytes)
    conf = bytearray(9)
    conf[0] = 9            # bLength
    conf[1] = USB_DESC_CONFIGURATION
    # wTotalLength will be patched at the end
    conf[4] = 3            # bNumInterfaces
    conf[5] = 1            # bConfigurationValue
    conf[6] = 0            # iConfiguration
    conf[7] = 0x80         # bmAttributes (bus-powered)
    conf[8] = 50           # bMaxPower (100mA)
    parts.append(conf)

    # --- Interface 0: Mouse ---
    iface0 = bytearray(9)
    iface0[0] = 9; iface0[1] = USB_DESC_INTERFACE
    iface0[2] = 0          # bInterfaceNumber
    iface0[3] = 0          # bAlternateSetting
    iface0[4] = 1          # bNumEndpoints
    iface0[5] = 0x03       # bInterfaceClass (HID)
    iface0[6] = 0x01       # bInterfaceSubClass (Boot)
    iface0[7] = 0x02       # bInterfaceProtocol (Mouse)
    iface0[8] = 0          # iInterface
    parts.append(iface0)
    parts.append(build_hid_descriptor(len(MOUSE_DESCRIPTOR)))
    parts.append(build_endpoint_descriptor(0x81, 8))

    # --- Interface 1: Keyboard ---
    iface1 = bytearray(9)
    iface1[0] = 9; iface1[1] = USB_DESC_INTERFACE
    iface1[2] = 1          # bInterfaceNumber
    iface1[3] = 0          # bAlternateSetting
    iface1[4] = 1          # bNumEndpoints
    iface1[5] = 0x03       # bInterfaceClass (HID)
    iface1[6] = 0x01       # bInterfaceSubClass (Boot)
    iface1[7] = 0x01       # bInterfaceProtocol (Keyboard)
    iface1[8] = 0          # iInterface
    parts.append(iface1)
    parts.append(build_hid_descriptor(len(KEYBOARD_DESCRIPTOR)))
    parts.append(build_endpoint_descriptor(0x82, 8))

    # --- Interface 2: Controller ---
    iface2 = bytearray(9)
    iface2[0] = 9; iface2[1] = USB_DESC_INTERFACE
    iface2[2] = 2          # bInterfaceNumber
    iface2[3] = 0          # bAlternateSetting
    iface2[4] = 1          # bNumEndpoints
    iface2[5] = 0x03       # bInterfaceClass (HID)
    iface2[6] = 0x00       # bInterfaceSubClass (None)
    iface2[7] = 0x00       # bInterfaceProtocol (None)
    iface2[8] = 0          # iInterface
    parts.append(iface2)
    parts.append(build_hid_descriptor(len(CONTROLLER_DESCRIPTOR)))
    parts.append(build_endpoint_descriptor(0x83, 64))

    # Flatten and patch wTotalLength
    data = bytearray()
    for p in parts:
        data.extend(p)
    struct.pack_into('<H', data, 2, len(data))

    return bytes(data)


# Build the config descriptor and its sub-descriptors for lookup
CONFIG_DESC = build_configuration_descriptor()

# Map interface number -> HID report descriptor
IFACE_REPORT_DESCS = {
    0: MOUSE_DESCRIPTOR,
    1: KEYBOARD_DESCRIPTOR,
    2: CONTROLLER_DESCRIPTOR,
}


# ---------------------------------------------------------------------------
# SC2 Command Handler (reused from main_uhid.py)
# ---------------------------------------------------------------------------

class SC2CommandHandler:
    """Handles SC2 Feature Report commands (synthetic responses)."""

    def __init__(self):
        self.steam_input_mode = False
        self._settings_store = {}
        self._pending_response = {}

    def handle_set_report(self, report_type, report_id, data):
        """Handle a HID SET_REPORT request.
        
        For Feature reports: process the command, store the response so a
        subsequent GET_REPORT returns it to Steam.
        """
        if report_type == HID_REPORT_TYPE_FEATURE:
            response = self._handle_feature_report(report_id, data)
            if response:
                self._pending_response[report_id] = response
            return response
        if report_type == HID_REPORT_TYPE_OUTPUT:
            self._handle_output_report(report_id, data)
            return None
        return None

    def handle_get_report(self, report_type, report_id):
        """Handle a HID GET_REPORT request."""
        if report_type == HID_REPORT_TYPE_FEATURE:
            return self._handle_feature_read(report_id)
        return b'\x00' * 64

    def _handle_feature_report(self, report_id, data):
        # The CONTROLLER_DESCRIPTOR has no Report ID field, so report_id is
        # always 0x00. The command byte is data[0]. We route on data[0].
        cmd = data[0] if len(data) > 0 else 0
        if cmd == 0x85:
            return self._handle_mode_switch(data)
        if cmd in (0x81, 0x83, 0x87, 0x89, 0x8C, 0x8D, 0xAE, 0xBA,
                    0xB4, 0xB5, 0xEE, 0xEF, 0xF2, 0x95, 0x82):
            return self._handle_sc2_command(report_id, data)
        if cmd == 0x8F:
            return self._handle_haptic_command(data)
        # Fallback: try SC2 command handler with whatever we got
        if len(data) > 0:
            return self._handle_sc2_command(report_id, data)
        return b'\x00' * 64

    def _handle_feature_read(self, report_id):
        # Try report_id first (for descriptors with Report IDs)
        response = self._pending_response.pop(report_id, None)
        if response:
            return response
        # Try 0x00 (for CONTROLLER_DESCRIPTOR which has no Report ID)
        response = self._pending_response.pop(0x00, None)
        if response:
            return response
        return b'\x00' * 64

    def _handle_mode_switch(self, data):
        if len(data) > 0:
            mode = data[1] if len(data) > 1 and data[0] == 0x85 else data[0]
            if mode == 0x01:
                self.steam_input_mode = True
                print("[SC2] MODE SWITCH: Lizard -> Steam Input Mode")
            elif mode == 0x00:
                self.steam_input_mode = False
                print("[SC2] MODE SWITCH: Steam Input -> Lizard Mode")
        return b'\x00' * 64

    def _handle_haptic_command(self, data):
        print(f"[SC2] Haptic command: {data[:20].hex()}")
        return b'\x00' * 64

    def _handle_output_report(self, report_id, data):
        if report_id == 0x80 and len(data) >= 9:
            left_speed = struct.unpack_from('<H', data, 3)[0] if len(data) >= 5 else 0
            right_speed = struct.unpack_from('<H', data, 6)[0] if len(data) >= 8 else 0
            if left_speed or right_speed:
                print(f"[haptic] Rumble: left={left_speed} right={right_speed}")

    def _handle_sc2_command(self, report_id, value):
        if len(value) < 1:
            return b'\x00' * 64
        cmd = value[0]
        response = bytearray(64)

        if cmd == 0x83:  # GET_ATTRIBUTES
            response = bytearray([
                0x83, 0x2d,
                0x01, 0x03, 0x13, 0x00, 0x00,
                0x02, 0xff, 0xbf, 0x69, 0x41,
                0x0a, 0x2b, 0x12, 0xa9, 0x62,
                0x04, 0xad, 0xf1, 0xe4, 0x65,
                0x09, 0x2e, 0x00, 0x00, 0x00,
                0x0b, 0xa0, 0x0f, 0x00, 0x00,
                0x0d, 0x00, 0x00, 0x00, 0x00,
                0x0c, 0x00, 0x00, 0x00, 0x00,
                0x0e, 0x00, 0x00, 0x00, 0x00,
                0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
                0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            ])
            print("[SC2] GET_ATTRIBUTES")
        elif cmd == 0xAE:  # GET_SERIAL
            serial = b'F0000-0000-00000000'
            response = bytearray([0xAE, 0x15, 0x01])
            response += serial[:20].ljust(20, b'\x00')
            response += bytearray(64 - len(response))
            print(f"[SC2] GET_SERIAL -> '{serial.decode()}'")
        elif cmd == 0xBA:  # GET_CHIP_ID
            chip_id = bytes([0x4e,0x58,0x50,0x35,0x33,0x37,0x30,0x30,
                             0x30,0x31,0x32,0x33,0x34,0x35,0x36])
            response = bytearray([0xBA, 0x11, 0x00]) + chip_id
            response += bytearray(64 - len(response))
            print("[SC2] GET_CHIP_ID")
        elif cmd == 0x81:  # CLEAR_MAPPINGS
            response = bytearray([0x81, 0x00])
            response += bytearray(64 - len(response))
            print("[SC2] CLEAR_MAPPINGS")
        elif cmd == 0x87:  # SET_ATTRIBUTES
            register = value[3] if len(value) > 3 else 0
            payload_len = value[2] if len(value) > 2 else 0
            val_len = max(0, payload_len - 1)
            data_val = value[4:4+val_len] if len(value) >= 4 + val_len else value[4:6]
            if len(data_val) >= 2:
                self._settings_store[register] = struct.unpack_from('<H', data_val)[0]
            elif len(data_val) == 1:
                self._settings_store[register] = data_val[0]
            response = bytearray([0x87, payload_len, register]) + data_val
            response += bytearray(64 - len(response))
            print(f"[SC2] SET_ATTRIBUTES reg=0x{register:02x}")
        elif cmd == 0x89:  # GET_SETTINGS_VALUES
            num_regs = value[2] if len(value) > 2 else 0
            response = bytearray([0x89, num_regs])
            for i in range(num_regs):
                reg_idx = 3 + i if len(value) > 3 + i else 0
                reg = value[reg_idx] if reg_idx < len(value) else 0
                val = self._settings_store.get(reg, 0)
                response += bytes([reg, val & 0xFF, (val >> 8) & 0xFF])
            response += bytearray(64 - len(response))
            print(f"[SC2] GET_SETTINGS_VALUES: {num_regs} registers")
        elif cmd == 0xf2:
            response = bytearray([0x01, 0x00, 0x00, 0x00, 0x00, 0xf2])
            response += bytearray(64 - len(response))
            print("[SC2] MAPPING_ACK (0xf2)")
        elif cmd == 0x85:
            response = bytearray([0x85, 0x00])
            response += bytearray(64 - len(response))
            print("[SC2] SET_DEFAULT_DIGITAL_MAPPINGS")
        elif cmd == 0x8D:
            self._handle_mode_switch(value)
            response = bytearray([0x8D, 0x00])
            response += bytearray(64 - len(response))
            print("[SC2] SET_CONTROLLER_MODE")
        elif cmd == 0xB4:
            response = bytearray([0xB4, 0x00, 0x01])
            response += bytearray(64 - len(response))
            print("[SC2] Protocol Version Query (0xB4)")
        elif cmd == 0xB5:
            response = bytearray([0xB5, 0x00])
            response += bytearray(64 - len(response))
            print("[SC2] Protocol Command (0xB5)")
        elif cmd == 0xEE:
            response = bytearray([0xEE, 0x00])
            response += bytearray(64 - len(response))
            print("[SC2] Feature Report Message Write (0xEE)")
        elif cmd == 0xEF:
            response = bytearray([0xEF, 0x00])
            response += bytearray(64 - len(response))
            print("[SC2] Feature Report Message Read (0xEF)")
        elif cmd == 0x95:
            response = bytearray([0x95, 0x00])
            response += bytearray(64 - len(response))
            print("[SC2] Enter Bootloader (0x95) - ignored")
        elif cmd == 0x8C:
            response = bytearray([0x8C, 0x00])
            response += bytearray(64 - len(response))
            print("[SC2] GET_SETTINGS_DEFAULTS (0x8C)")
        elif cmd == 0x82:
            response = bytearray([0x82, 0xFF, 0x02])
            response += bytearray(64 - len(response))
            print("[SC2] GET_DIGITAL_MAPPINGS (0x82) - error response")
        else:
            response = bytearray([cmd, 0x00])
            response += bytearray(64 - len(response))
            print(f"[SC2] Unknown command 0x{cmd:02x}")

        return bytes(response)


# ---------------------------------------------------------------------------
# USB/IP Protocol Handler
# ---------------------------------------------------------------------------

class VirtualUSBDevice:
    """Virtual USB device using vhci_hcd + USB/IP protocol.

    Mirrors the approach in InputPlumber's steam_deck.rs / virtual-usb-rs:
      1. socketpair() → one end to vhci_hcd, one end for our I/O
      2. Write to /sys/devices/platform/vhci_hcd.0/attach to connect
      3. Handle USB/IP CMD_SUBMIT / RET_SUBMIT on the userspace socket
    """

    def __init__(self, name="Steam Controller"):
        self.name = name
        self.sock = None
        self.port = None
        self.sc2 = SC2CommandHandler()
        self._running = False
        self._pending_in = {}   # seqnum -> (ep, expected_length)
        self._seqnum = 0
        self.start_time = time.monotonic()
        self._lock = threading.Lock()

    # -- vhci_hcd setup -----------------------------------------------------

    def open(self):
        """Load vhci-hcd, create socketpair, attach to a virtual port."""
        # 1. Ensure vhci-hcd is loaded
        os.system("modprobe vhci-hcd")
        time.sleep(0.2)

        # 2. Create socketpair
        self.sock, vhci_sock = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)

        # 3. Find an available port (status == 4 means VDEV_ST_NULL)
        port = self._find_available_port()
        if port is None:
            raise RuntimeError("No available vhci_hcd ports")
        self.port = port

        # 4. Attach via sysfs: "{port} {fd} {devid} {speed}"
        vhci_fd = vhci_sock.fileno()
        attach_path = "/sys/devices/platform/vhci_hcd.0/attach"
        devid = 1  # virtual device ID
        speed = USB_SPEED_HIGH
        try:
            with open(attach_path, 'w') as f:
                f.write(f"{port} {vhci_fd} {devid} {speed}")
        except PermissionError:
            raise RuntimeError("Need root to write to vhci_hcd sysfs")
        vhci_sock.close()

        # 5. Wait for kernel to enumerate
        time.sleep(1.0)

        print(f"[+] Attached to vhci_hcd port {port} (USB_SPEED_HIGH)")
        print(f"[+] Device should appear as /dev/hidraw* and /dev/input/event*")

    def _find_available_port(self):
        """Parse /sys/devices/platform/vhci_hcd.0/status for available ports."""
        try:
            with open("/sys/devices/platform/vhci_hcd.0/status") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 5 and parts[0] != "hub":
                        port_num = int(parts[1], 10)
                        status = int(parts[2], 10)
                        if status == 4:  # VDEV_ST_NULL = available
                            return port_num
        except Exception as e:
            print(f"[-] Error reading vhci status: {e}")
        return None

    def close(self):
        """Detach from vhci_hcd and close the socket."""
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        # Detach from vhci
        if self.port is not None:
            try:
                with open("/sys/devices/platform/vhci_hcd.0/detach", 'w') as f:
                    f.write(str(self.port))
                print(f"[+] Detached from vhci_hcd port {self.port}")
            except Exception:
                pass
            self.port = None

    # -- USB/IP protocol handling --------------------------------------------

    def _read_exact(self, n):
        """Read exactly n bytes from the socket."""
        data = b''
        while len(data) < n:
            chunk = self.sock.recv(n - len(data))
            if not chunk:
                raise ConnectionError("Socket closed")
            data += chunk
        return data

    def _write_exact(self, data):
        """Write all data to the socket."""
        total = 0
        while total < len(data):
            sent = self.sock.send(data[total:])
            if sent == 0:
                raise ConnectionError("Socket closed")
            total += sent

    def _build_ret_submit(self, seqnum, devid, direction, ep, status, payload=b''):
        """Build a 48-byte RET_SUBMIT header + payload."""
        header = struct.pack('>IIII', USBIP_RET_SUBMIT, seqnum, devid, direction)
        header += struct.pack('>IIIII', ep, status, len(payload), 0, 0)
        # Pad header to 48 bytes (base is 20 + 4*5 = 40, need 8 more)
        # Actually: basic(20) + status(4) + actual_length(4) + start_frame(4) +
        #           number_of_packets(4) + error_count(4) = 40 bytes
        # Wait — the CMD_SUBMIT is 48 bytes (basic 20 + 28). RET_SUBMIT should also be 48.
        # basic(20) + status(4) + actual_length(4) + start_frame(4) + nopackets(4) + errorcount(4) = 40
        # Need 8 more bytes padding? No — let me check the struct sizes again.
        #
        # From usbip.rs:
        #   USBIPHeaderRetSubmit: base(20) + status(4) + actual_length(4) + start_frame(4)
        #                         + number_of_packets(4) + error_count(4) = 40 bytes
        #   USBIPHeaderCmdSubmit: base(20) + transfer_flags(4) + transfer_buffer_length(4)
        #                         + start_frame(4) + number_of_packets(4) + interval(4)
        #                         + setup(8) = 48 bytes
        #
        # So RET_SUBMIT is 40 bytes, not 48. But the kernel reads USBIP_CMD_SIZE (48) bytes.
        # Let me check the actual sizes.
        #
        # Actually from the packed_struct definitions:
        #   USBIPHeaderCmdSubmit: size_bytes = "48"
        #   USBIPHeaderRetSubmit: size_bytes = "48"
        #   USBIPHeaderCmdUnlink: size_bytes = "48"
        #   USBIPHeaderRetUnlink: size_bytes = "48"
        #
        # But the struct fields only add up to 40 for RetSubmit... The packed_struct
        # macro pads to the declared size. So RetSubmit has 8 bytes of implicit padding.
        #
        # Let me just pad to 48 bytes total.

        # Rebuild properly: 48 bytes total for RET_SUBMIT
        header = bytearray(48)
        struct.pack_into('>I', header, 0, USBIP_RET_SUBMIT)   # command
        struct.pack_into('>I', header, 4, seqnum)              # seqnum
        struct.pack_into('>I', header, 8, devid)               # devid
        struct.pack_into('>I', header, 12, direction)          # direction
        struct.pack_into('>I', header, 16, ep)                 # ep
        struct.pack_into('>i', header, 20, status)             # status
        struct.pack_into('>i', header, 24, len(payload))       # actual_length
        struct.pack_into('>i', header, 28, 0)                  # start_frame
        struct.pack_into('>i', header, 32, 0)                  # number_of_packets
        struct.pack_into('>i', header, 36, 0)                  # error_count
        # bytes 40-47: implicit padding (zeros)

        return bytes(header) + payload

    def _build_ret_unlink(self, seqnum, devid, status=-104):
        """Build a 48-byte RET_UNLINK response."""
        header = bytearray(48)
        struct.pack_into('>I', header, 0, USBIP_RET_UNLINK)   # command
        struct.pack_into('>I', header, 4, seqnum)              # seqnum
        struct.pack_into('>I', header, 8, devid)               # devid
        struct.pack_into('>I', header, 12, 0)                  # direction
        struct.pack_into('>I', header, 16, 0)                  # ep
        struct.pack_into('>i', header, 20, status)             # status
        return bytes(header)

    def _parse_setup(self, data):
        """Parse an 8-byte USB setup packet."""
        if len(data) < 8:
            return None
        bmRequestType = data[0]
        bRequest = data[1]
        wValue = struct.unpack_from('<H', data, 2)[0]
        wIndex = struct.unpack_from('<H', data, 4)[0]
        wLength = struct.unpack_from('<H', data, 6)[0]
        direction = (bmRequestType >> 7) & 1
        kind = (bmRequestType >> 5) & 3
        recipient = bmRequestType & 0x1f
        return {
            'bmRequestType': bmRequestType,
            'bRequest': bRequest,
            'wValue': wValue,
            'wIndex': wIndex,
            'wLength': wLength,
            'direction': direction,
            'kind': kind,
            'recipient': recipient,
        }

    def _handle_ep0_setup(self, seqnum, devid, setup_data, payload):
        """Handle a USB control transfer on EP0."""
        req = self._parse_setup(setup_data)
        if not req:
            return self._build_ret_submit(seqnum, devid, USBIP_DIR_IN, 0, -32)

        direction = req['direction']
        kind = req['kind']
        recipient = req['recipient']
        bRequest = req['bRequest']
        wValue = req['wValue']
        wIndex = req['wIndex']
        wLength = req['wLength']

        # Standard device requests (kind == 0)
        if kind == 0 and recipient == 0:  # Standard, Device
            if bRequest == USB_REQ_GET_DESCRIPTOR:
                return self._handle_get_descriptor(seqnum, devid, wValue, wIndex, wLength, direction)
            elif bRequest == USB_REQ_SET_CONFIGURATION:
                print(f"[USB] SET_CONFIGURATION wValue={wValue}")
                return self._build_ret_submit(seqnum, devid, USBIP_DIR_OUT, 0, 0)
            elif bRequest == USB_REQ_GET_STATUS:
                return self._build_ret_submit(seqnum, devid, USBIP_DIR_IN, 0, 0, b'\x00\x00')
            elif bRequest == USB_REQ_SET_ADDRESS:
                # Kernel handles this, but we still get the request
                print(f"[USB] SET_ADDRESS wValue={wValue}")
                return self._build_ret_submit(seqnum, devid, USBIP_DIR_OUT, 0, 0)
            else:
                print(f"[USB] Unknown standard device request 0x{bRequest:02x}")
                return self._build_ret_submit(seqnum, devid, direction, 0, 0)

        # Standard interface requests
        if kind == 0 and recipient == 1:  # Standard, Interface
            if bRequest == USB_REQ_GET_DESCRIPTOR:
                return self._handle_get_descriptor(seqnum, devid, wValue, wIndex, wLength, direction)
            elif bRequest == USB_REQ_GET_STATUS:
                return self._build_ret_submit(seqnum, devid, USBIP_DIR_IN, 0, 0, b'\x00\x00')
            else:
                print(f"[USB] Unknown standard iface request 0x{bRequest:02x} iface={wIndex}")
                return self._build_ret_submit(seqnum, devid, direction, 0, 0)

        # Class interface requests (HID)
        if kind == 1 and recipient == 1:  # Class, Interface
            return self._handle_hid_class_request(seqnum, devid, bRequest, wValue, wIndex, wLength, direction, payload)

        # Class endpoint requests
        if kind == 1 and recipient == 2:  # Class, Endpoint
            return self._build_ret_submit(seqnum, devid, direction, 0, 0)

        print(f"[USB] Unhandled EP0: type={kind} recip={recipient} req=0x{bRequest:02x}")
        return self._build_ret_submit(seqnum, devid, direction, 0, -32)

    def _handle_get_descriptor(self, seqnum, devid, wValue, wIndex, wLength, direction):
        """Handle GET_DESCRIPTOR standard request."""
        desc_type = (wValue >> 8) & 0xFF
        desc_index = wValue & 0xFF

        if desc_type == USB_DESC_DEVICE:
            data = build_device_descriptor()
            print(f"[USB] GET_DESCRIPTOR Device")
        elif desc_type == USB_DESC_CONFIGURATION:
            data = CONFIG_DESC
            print(f"[USB] GET_DESCRIPTOR Configuration (len={len(data)})")
        elif desc_type == USB_DESC_STRING:
            if desc_index < len(STRING_DESCS):
                data = STRING_DESCS[desc_index]
            else:
                data = bytes([2, USB_DESC_STRING])
            print(f"[USB] GET_DESCRIPTOR String[{desc_index}]")
        elif desc_type == USB_DESC_HID_REPORT:
            # HID Report descriptor — wIndex tells us which interface
            iface_num = wIndex & 0xFF
            if iface_num in IFACE_REPORT_DESCS:
                data = IFACE_REPORT_DESCS[iface_num]
            else:
                data = b''
            print(f"[USB] GET_DESCRIPTOR HID Report iface={iface_num} (len={len(data)})")
        elif desc_type == USB_DESC_HID:
            # HID class descriptor (9 bytes) — extract from config desc
            iface_num = wIndex & 0xFF
            # Find the HID descriptor for this interface in CONFIG_DESC
            data = self._find_hid_class_desc(iface_num)
            print(f"[USB] GET_DESCRIPTOR HID iface={iface_num}")
        else:
            data = b''
            print(f"[USB] GET_DESCRIPTOR unknown type=0x{desc_type:02x} idx={desc_index}")

        # Truncate to wLength
        if len(data) > wLength:
            data = data[:wLength]

        return self._build_ret_submit(seqnum, devid, USBIP_DIR_IN, 0, 0, data)

    def _find_hid_class_desc(self, iface_num):
        """Find the 9-byte HID class descriptor for the given interface from CONFIG_DESC."""
        # Walk through the config descriptor to find the matching interface
        offset = 9  # skip configuration descriptor itself
        current_iface = -1
        while offset < len(CONFIG_DESC):
            if offset + 1 > len(CONFIG_DESC):
                break
            bLength = CONFIG_DESC[offset]
            if bLength == 0:
                break
            bDescType = CONFIG_DESC[offset + 1]
            if bDescType == USB_DESC_INTERFACE:
                bInterfaceNumber = CONFIG_DESC[offset + 2]
                current_iface = bInterfaceNumber
            elif bDescType == USB_DESC_HID and current_iface == iface_num:
                return CONFIG_DESC[offset:offset + bLength]
            offset += bLength
        return b''

    def _handle_hid_class_request(self, seqnum, devid, bRequest, wValue, wIndex, wLength, direction, payload):
        """Handle HID class-specific requests."""
        iface_num = wIndex & 0xFF
        report_type = (wValue >> 8) & 0xFF
        report_id = wValue & 0xFF

        if bRequest == HID_GET_REPORT:
            # Host reads a report from the device
            data = self.sc2.handle_get_report(report_type, report_id)
            if len(data) > wLength:
                data = data[:wLength]
            print(f"[HID] GET_REPORT type={report_type} id=0x{report_id:02x} iface={iface_num}")
            return self._build_ret_submit(seqnum, devid, USBIP_DIR_IN, 0, 0, data)

        elif bRequest == HID_SET_REPORT:
            # Host writes a report to the device
            # payload contains the report data (after the setup stage)
            report_data = payload
            # Strip report ID prefix if present and matches
            if len(report_data) > 0 and report_id != 0 and report_data[0] == report_id:
                report_data = report_data[1:]
            self.sc2.handle_set_report(report_type, report_id, report_data)
            print(f"[HID] SET_REPORT type={report_type} id=0x{report_id:02x} iface={iface_num} len={len(report_data)}")
            return self._build_ret_submit(seqnum, devid, USBIP_DIR_OUT, 0, 0)

        elif bRequest == HID_SET_IDLE:
            print(f"[HID] SET_IDLE iface={iface_num}")
            return self._build_ret_submit(seqnum, devid, USBIP_DIR_OUT, 0, 0)

        else:
            print(f"[HID] Unknown class request 0x{bRequest:02x} iface={iface_num}")
            return self._build_ret_submit(seqnum, devid, direction, 0, 0)

    def _handle_cmd_submit(self, header_data, payload):
        """Handle a USBIP_CMD_SUBMIT from the kernel."""
        # Parse the 48-byte header
        seqnum = struct.unpack_from('>I', header_data, 4)[0]
        devid = struct.unpack_from('>I', header_data, 8)[0]
        direction = struct.unpack_from('>I', header_data, 12)[0]
        ep = struct.unpack_from('>I', header_data, 16)[0]
        transfer_flags = struct.unpack_from('>I', header_data, 20)[0]
        transfer_buf_len = struct.unpack_from('>i', header_data, 24)[0]
        start_frame = struct.unpack_from('>i', header_data, 28)[0]
        num_packets = struct.unpack_from('>i', header_data, 32)[0]
        interval = struct.unpack_from('>i', header_data, 36)[0]
        setup = header_data[40:48]

        # EP0 control transfer
        if ep == 0:
            has_setup = any(b != 0 for b in setup)
            if has_setup:
                return self._handle_ep0_setup(seqnum, devid, setup, payload)
            elif direction == USBIP_DIR_IN:
                # Status stage IN — no data
                return self._build_ret_submit(seqnum, devid, USBIP_DIR_IN, 0, 0)
            else:
                return self._build_ret_submit(seqnum, devid, USBIP_DIR_OUT, 0, 0)

        # Interrupt IN (host waiting for input report)
        if direction == USBIP_DIR_IN:
            _proto_log("interrupt_in", ep=ep, seqnum=seqnum, buf_len=transfer_buf_len)
            # Queue this — will be answered when we have input data
            with self._lock:
                self._pending_in[seqnum] = (ep, transfer_buf_len)
            return None  # Don't reply yet

        # Interrupt OUT (e.g., haptic output)
        if direction == USBIP_DIR_OUT:
            _proto_log("interrupt_out", ep=ep, seqnum=seqnum, data=payload[:20].hex() if payload else "")
            if ep == 0x03:
                # Controller endpoint OUT — handle output reports
                if len(payload) > 0:
                    report_id = payload[0] if payload else 0
                    self.sc2.handle_set_report(HID_REPORT_TYPE_OUTPUT, report_id, payload[1:] if len(payload) > 1 else b'')
            return self._build_ret_submit(seqnum, devid, USBIP_DIR_OUT, 0, 0, payload or b'')

        return self._build_ret_submit(seqnum, devid, direction, ep, 0)

    def _handle_cmd_unlink(self, header_data):
        """Handle a USBIP_CMD_UNLINK from the kernel."""
        seqnum = struct.unpack_from('>I', header_data, 4)[0]
        devid = struct.unpack_from('>I', header_data, 8)[0]
        unlink_seqnum = struct.unpack_from('>I', header_data, 20)[0]
        print(f"[USBIP] UNLINK seqnum={seqnum} unlinking={unlink_seqnum}")
        # Remove from pending
        with self._lock:
            self._pending_in.pop(unlink_seqnum, None)
        return self._build_ret_unlink(seqnum, devid, -104)

    def _read_thread(self):
        """Read USB/IP commands from the kernel socket and handle them."""
        print("[+] USB/IP read thread started")
        while self._running:
            try:
                # Read the 48-byte header
                header_data = self._read_exact(48)
                command = struct.unpack_from('>I', header_data, 0)[0]

                if command == USBIP_CMD_SUBMIT:
                    # Determine payload length (OUT direction only)
                    direction = struct.unpack_from('>I', header_data, 12)[0]
                    transfer_buf_len = struct.unpack_from('>i', header_data, 24)[0]
                    payload = b''
                    if direction == USBIP_DIR_OUT and transfer_buf_len > 0:
                        payload = self._read_exact(transfer_buf_len)

                    reply = self._handle_cmd_submit(header_data, payload)
                    if reply:
                        self._write_exact(reply)

                elif command == USBIP_CMD_UNLINK:
                    reply = self._handle_cmd_unlink(header_data)
                    if reply:
                        self._write_exact(reply)
                else:
                    print(f"[USBIP] Unknown command: {command}")

            except ConnectionError:
                if self._running:
                    print("[-] USB/IP socket closed")
                break
            except Exception as e:
                if self._running:
                    print(f"[-] USB/IP read error: {e}")
                break

    # -- Input report sending ------------------------------------------------

    def reply_pending_input(self, ep, data):
        """Reply to a pending interrupt IN request with input data."""
        with self._lock:
            for seqnum, (pending_ep, buf_len) in list(self._pending_in.items()):
                if pending_ep == ep:
                    del self._pending_in[seqnum]
                    reply = self._build_ret_submit(
                        seqnum, 1, USBIP_DIR_IN, ep, 0, data[:buf_len]
                    )
                    try:
                        self._write_exact(reply)
                    except Exception as e:
                        print(f"[-] Failed to send input reply: {e}")
                    return
        # No pending request — drop the report
        _proto_log("input_dropped", ep=ep)

    def _input_loop(self):
        """Send synthetic idle input reports at 10Hz on the controller endpoint."""
        print("[+] Input loop started (10Hz idle reports)")
        seq_num = 0
        while self._running:
            seq_num = (seq_num + 1) & 0xFF
            timestamp_us = int((time.monotonic() - self.start_time) * 1000000) & 0xFFFFFFFF

            # 64-byte controller input report (matching CONTROLLER_DESCRIPTOR)
            report = bytearray(64)
            report[0] = seq_num  # frame counter
            struct.pack_into("<I", report, 4, timestamp_us)

            self.reply_pending_input(0x83, bytes(report))
            time.sleep(0.1)

    # -- Main loop -----------------------------------------------------------

    def start(self):
        """Start the USB/IP read thread and input loop."""
        self._running = True
        self._read_thread_obj = threading.Thread(target=self._read_thread, daemon=True)
        self._read_thread_obj.start()
        self._input_thread = threading.Thread(target=self._input_loop, daemon=True)
        self._input_thread.start()
        print("[+] Virtual USB SC2 device started")

    def stop(self):
        self._running = False
        self.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Virtual USB Steam Controller 2 (vhci_hcd + USB/IP)"
    )
    parser.add_argument(
        "--name",
        default="Steam Controller",
        help="Device name (default: 'Steam Controller')",
    )
    args = parser.parse_args()

    device = VirtualUSBDevice(name=args.name)

    def signal_handler(signum, frame):
        print("\n[*] Shutting down...")
        device.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    device.open()
    device.start()

    print("[*] Virtual USB SC2 device created.")
    print("[*] Check: lsusb | grep 28de, ls -la /dev/hidraw*, evtest /dev/input/event*")
    print("[*] Press Ctrl+C to stop.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        device.stop()


if __name__ == "__main__":
    main()
