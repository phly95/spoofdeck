#!/usr/bin/env python3
"""
UHID-based Virtual Steam Controller 2026.

Creates a virtual SC2 device via /dev/uhid on the host PC.
Steam sees it as a USB HID device — no BLE, no Deck, no peripheral needed.

Usage:
    sudo python3 src/main_uhid.py
    # Steam should see "Steam Controller 2026" in controller settings
"""

import argparse
import fcntl
import os
import struct
import signal
import sys
import time
import threading

# UHID event types (from linux/uhid.h)
UHID_DESTROY = 1
UHID_START = 2
UHID_STOP = 3
UHID_OPEN = 4
UHID_CLOSE = 5
UHID_OUTPUT = 6
UHID_GET_REPORT = 9
UHID_GET_REPORT_REPLY = 10
UHID_CREATE2 = 11
UHID_INPUT2 = 12
UHID_SET_REPORT = 13
UHID_SET_REPORT_REPLY = 14

# UHID report types
UHID_FEATURE_REPORT = 0
UHID_OUTPUT_REPORT = 1

# HID descriptor size limit
HID_MAX_DESCRIPTOR_SIZE = 4096
UHID_DATA_MAX = 4096

# SC2 BLE VID/PID
SC2_VID = 0x28DE
SC2_PID = 0x1303  # BLE mode

# Structured protocol logging (enabled via SPOOFDECK_PROTO_LOG=1)
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


def build_sc2_hid_descriptor():
    """Build the HID Report Descriptor matching the real SC2 BLE firmware.

    This is the same descriptor used in gatt_db.py build_report_map(),
    but formatted as a raw byte sequence for UHID.
    """
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

        # --- SC2 Custom Input (Report ID 0x45, 45 bytes) ---
        0x06, 0x00, 0xFF,  # Usage Page (Vendor Defined 0xFF00)
        0x09, 0x45,        # Usage (0x45)
        0xA1, 0x01,        # Collection (Application)
        0x85, 0x45,        #   Report ID (0x45)
        0x75, 0x08,        #   Report Size (8)
        0x95, 0x2D,        #   Report Count (45)
        0x81, 0x02,        #   Input (Data,Var,Abs)
        0xC0,              # End Collection

        # --- SC2 Custom Input (Report ID 0x47, 47 bytes) ---
        0x06, 0x00, 0xFF,  # Usage Page (Vendor Defined 0xFF00)
        0x09, 0x47,        # Usage (0x47)
        0xA1, 0x01,        # Collection (Application)
        0x85, 0x47,        #   Report ID (0x47)
        0x75, 0x08,        #   Report Size (8)
        0x95, 0x2F,        #   Report Count (47)
        0x81, 0x02,        #   Input (Data,Var,Abs)
        0xC0,              # End Collection

        # --- SC2 Haptic Rumble Output (Report ID 0x80, 9 bytes) ---
        0x06, 0x00, 0xFF,  # Usage Page (Vendor Defined 0xFF00)
        0x09, 0x80,        # Usage (0x80)
        0xA1, 0x01,        # Collection (Application)
        0x85, 0x80,        #   Report ID (0x80)
        0x75, 0x08,        #   Report Size (8)
        0x95, 0x09,        #   Report Count (9)
        0x91, 0x02,        #   Output (Data,Var,Abs)
        0xC0,              # End Collection

        # --- Feature Report 0x01 (SC2 Capabilities, 64 bytes) ---
        0x06, 0x00, 0xFF,  # Usage Page (Vendor Defined 0xFF00)
        0x09, 0x01,        # Usage (0x01)
        0xA1, 0x02,        # Collection (Logical)
        0x85, 0x01,        #   Report ID (0x01)
        0x75, 0x08,        #   Report Size (8)
        0x95, 0x40,        #   Report Count (64)
        0xB1, 0x02,        #   Feature (Data,Var,Abs)
        0xC0,              # End Collection

        # --- Feature Report 0x02 (SC2 Command Channel, 64 bytes) ---
        0x06, 0x00, 0xFF,  # Usage Page (Vendor Defined 0xFF00)
        0x09, 0x02,        # Usage (0x02)
        0xA1, 0x02,        # Collection (Logical)
        0x85, 0x02,        #   Report ID (0x02)
        0x75, 0x08,        #   Report Size (8)
        0x95, 0x40,        #   Report Count (64)
        0xB1, 0x02,        #   Feature (Data,Var,Abs)
        0xC0,              # End Collection

        # --- Feature Report 0x85 (SC2 Mode Switch, 64 bytes) ---
        0x06, 0x00, 0xFF,  # Usage Page (Vendor Defined 0xFF00)
        0x09, 0x85,        # Usage (0x85)
        0xA1, 0x02,        # Collection (Logical)
        0x85, 0x85,        #   Report ID (0x85)
        0x75, 0x08,        #   Report Size (8)
        0x95, 0x40,        #   Report Count (64)
        0xB1, 0x02,        #   Feature (Data,Var,Abs)
        0xC0,              # End Collection

        # --- Feature Report 0x86 (64 bytes) ---
        0x06, 0x00, 0xFF,  # Usage Page (Vendor Defined 0xFF00)
        0x09, 0x86,        # Usage (0x86)
        0xA1, 0x02,        # Collection (Logical)
        0x85, 0x86,        #   Report ID (0x86)
        0x75, 0x08,        #   Report Size (8)
        0x95, 0x40,        #   Report Count (64)
        0xB1, 0x02,        #   Feature (Data,Var,Abs)
        0xC0,              # End Collection

        # --- Feature Report 0x87 (64 bytes) ---
        0x06, 0x00, 0xFF,  # Usage Page (Vendor Defined 0xFF00)
        0x09, 0x87,        # Usage (0x87)
        0xA1, 0x02,        # Collection (Logical)
        0x85, 0x87,        #   Report ID (0x87)
        0x75, 0x08,        #   Report Size (8)
        0x95, 0x40,        #   Report Count (64)
        0xB1, 0x02,        #   Feature (Data,Var,Abs)
        0xC0,              # End Collection

        # --- Feature Report 0x8F (SC2 Haptic Command, 64 bytes) ---
        0x06, 0x00, 0xFF,  # Usage Page (Vendor Defined 0xFF00)
        0x09, 0x8F,        # Usage (0x8F)
        0xA1, 0x02,        # Collection (Logical)
        0x85, 0x8F,        #   Report ID (0x8F)
        0x75, 0x08,        #   Report Size (8)
        0x95, 0x40,        #   Report Count (64)
        0xB1, 0x02,        #   Feature (Data,Var,Abs)
        0xC0,              # End Collection
    ])


class SC2CommandHandler:
    """Handles SC2 Feature Report commands (synthetic responses).

    Reuses the same logic from HoGPeripheral._handle_sc2_command() but
    adapted for UHID Feature Report I/O.
    """

    def __init__(self):
        self.steam_input_mode = False
        self._settings_store = {}
        self._pending_response = {}  # report_id -> response bytes

    def handle_feature_report(self, report_id, data):
        """Handle a Feature Report write from the host.

        Args:
            report_id: HID Report ID (0x01, 0x02, 0x85, 0x8F, etc.)
            data: Payload bytes (without Report ID prefix)

        Returns:
            Response bytes (64 bytes) or None if no response needed.
        """
        if report_id == 0x85:
            return self._handle_mode_switch(data)
        if report_id in (0x01, 0x02):
            return self._handle_sc2_command(report_id, data)
        if report_id == 0x8F:
            return self._handle_haptic_command(data)
        return b'\x00' * 64

    def handle_feature_read(self, report_id):
        """Handle a Feature Report read from the host.

        Returns the cached response from the last SET_REPORT for this report_id.
        """
        response = self._pending_response.pop(report_id, None)
        if response:
            return response
        return b'\x00' * 64

    def _handle_mode_switch(self, data):
        if len(data) > 0:
            mode = data[0] if len(data) > 1 else 0x00
            if data[0] == 0x85 and len(data) > 1:
                mode = data[1]
            if mode == 0x01:
                self.steam_input_mode = True
                print("[SC2] MODE SWITCH: Lizard -> Steam Input Mode")
            elif mode == 0x00:
                self.steam_input_mode = False
                print("[SC2] MODE SWITCH: Steam Input -> Lizard Mode")
        return b'\x00' * 64

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
            chip_id = bytes([
                0x4e, 0x58, 0x50, 0x35, 0x33, 0x37, 0x30, 0x30,
                0x30, 0x31, 0x32, 0x33, 0x34, 0x35, 0x36,
            ])
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
            else:
                self._settings_store[register] = 0
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

        elif cmd == 0x85:  # SET_DEFAULT_DIGITAL_MAPPINGS
            response = bytearray([0x85, 0x00])
            response += bytearray(64 - len(response))
            print("[SC2] SET_DEFAULT_DIGITAL_MAPPINGS")

        elif cmd == 0x8D:  # SET_CONTROLLER_MODE
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


class UhidSC2Device:
    """Virtual SC2 device using UHID."""

    def __init__(self, name="Steam Controller 2026"):
        self.name = name
        self.fd = None
        self._running = False
        self._thread = None
        self._input_thread = None
        self.sc2 = SC2CommandHandler()
        self.seq_num = 0
        self.start_time = time.monotonic()

    def open(self):
        """Open /dev/uhid and create the virtual device."""
        self.fd = os.open("/dev/uhid", os.O_RDWR | os.O_NONBLOCK)
        print(f"[+] Opened /dev/uhid (fd={self.fd})")
        self._create_device()

    def _create_device(self):
        """Send UHID_CREATE2 to create the virtual SC2."""
        rd = build_sc2_hid_descriptor()
        if len(rd) > HID_MAX_DESCRIPTOR_SIZE:
            raise ValueError(f"HID descriptor too large: {len(rd)} > {HID_MAX_DESCRIPTOR_SIZE}")

        # Build uhid_create2_req
        name_bytes = self.name.encode('utf-8')[:127]
        create2 = bytearray()
        create2 += name_bytes.ljust(128, b'\x00')   # name[128]
        create2 += b'\x00' * 64                       # phys[64]
        create2 += b'\x00' * 64                       # uniq[64]
        create2 += struct.pack('<H', len(rd))         # rd_size
        create2 += struct.pack('<H', 0x03)            # bus = BUS_USB
        create2 += struct.pack('<I', SC2_VID)         # vendor
        create2 += struct.pack('<I', SC2_PID)         # product
        create2 += struct.pack('<I', 0x0001)          # version
        create2 += struct.pack('<I', 0)               # country
        create2 += rd.ljust(HID_MAX_DESCRIPTOR_SIZE, b'\x00')  # rd_data

        # Build uhid_event: type(4) + create2 payload
        event = struct.pack('<I', UHID_CREATE2) + bytes(create2)
        os.write(self.fd, event)
        print(f"[+] UHID_CREATE2 sent: name='{self.name}' VID=0x{SC2_VID:04X} PID=0x{SC2_PID:04X} rd_size={len(rd)}")

    def start(self):
        """Start event listener and synthetic input threads."""
        self._running = True
        self._thread = threading.Thread(target=self._event_loop, daemon=True)
        self._thread.start()
        self._input_thread = threading.Thread(target=self._input_loop, daemon=True)
        self._input_thread.start()
        print("[+] UHID SC2 device started")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        if self._input_thread:
            self._input_thread.join(timeout=2)
        if self.fd is not None:
            # Send UHID_DESTROY
            try:
                event = struct.pack('<I', UHID_DESTROY)
                os.write(self.fd, event)
            except OSError:
                pass
            os.close(self.fd)
            self.fd = None
        print("[+] UHID SC2 device stopped")

    def _event_loop(self):
        """Read UHID events from the kernel."""
        while self._running:
            try:
                data = os.read(self.fd, 4380)
                if len(data) < 4:
                    continue
                event_type = struct.unpack('<I', data[:4])[0]
                self._handle_event(event_type, data[4:])
            except BlockingIOError:
                time.sleep(0.01)
            except OSError as e:
                if self._running:
                    print(f"[-] UHID read error: {e}")
                break

    def _handle_event(self, event_type, payload):
        """Dispatch UHID events."""
        if event_type == UHID_START:
            dev_flags = struct.unpack('<Q', payload[:8])[0]
            print(f"[UHID] START dev_flags=0x{dev_flags:x}")

        elif event_type == UHID_STOP:
            print("[UHID] STOP")

        elif event_type == UHID_OPEN:
            print("[UHID] OPEN — host opened the device")

        elif event_type == UHID_CLOSE:
            print("[UHID] CLOSE — host closed the device")

        elif event_type == UHID_DESTROY:
            print("[UHID] DESTROY")

        elif event_type == UHID_GET_REPORT:
            # Host reads a Feature Report
            req_id = struct.unpack('<I', payload[:4])[0]
            rnum = payload[4]
            rtype = payload[5]
            print(f"[UHID] GET_REPORT id={req_id} rnum=0x{rnum:02x} rtype={rtype}")
            response = self.sc2.handle_feature_read(rnum)
            self._send_get_report_reply(req_id, response)

        elif event_type == UHID_SET_REPORT:
            # Host writes a Feature/Output Report
            req_id = struct.unpack('<I', payload[:4])[0]
            rnum = payload[4]
            rtype = payload[5]
            size = struct.unpack('<H', payload[6:8])[0]
            data = payload[8:8+size]
            # UHID includes the Report ID as the first byte of data.
            # Strip it — the handler works with payload only.
            if len(data) > 0 and data[0] == rnum:
                data = data[1:]
            print(f"[UHID] SET_REPORT id={req_id} rnum=0x{rnum:02x} rtype={rtype} size={size}")
            if rtype == UHID_FEATURE_REPORT:
                response = self.sc2.handle_feature_report(rnum, data)
                # Store response for subsequent GET_REPORT; SET_REPORT_REPLY is just an ACK
                self.sc2._pending_response[rnum] = response if response else b'\x00' * 64
                self._send_set_report_reply(req_id, None)
            elif rtype == UHID_OUTPUT_REPORT:
                # Output report (e.g., haptic rumble)
                self._handle_output_report(rnum, data)
                self._send_set_report_reply(req_id, None)

        elif event_type == UHID_OUTPUT:
            # Legacy output report
            req_id = struct.unpack('<I', payload[:4])[0]
            data = payload[4:]
            print(f"[UHID] OUTPUT id={req_id} data={data[:20].hex()}")

        else:
            print(f"[UHID] Unknown event type={event_type}")

    def _send_get_report_reply(self, req_id, data):
        """Reply to UHID_GET_REPORT."""
        if data is None:
            data = b'\x00' * 64
        reply = bytearray()
        reply += struct.pack('<I', req_id)       # id
        reply += struct.pack('<H', 0)            # err = 0
        reply += struct.pack('<H', min(len(data), UHID_DATA_MAX))  # size
        reply += data[:UHID_DATA_MAX].ljust(UHID_DATA_MAX, b'\x00')
        event = struct.pack('<I', UHID_GET_REPORT_REPLY) + bytes(reply)
        try:
            os.write(self.fd, event)
        except OSError as e:
            print(f"[-] GET_REPORT_REPLY error: {e}")

    def _send_set_report_reply(self, req_id, data=None):
        """Reply to UHID_SET_REPORT (ACK only, no data)."""
        reply = bytearray()
        reply += struct.pack('<I', req_id)  # id
        reply += struct.pack('<H', 0)       # err = 0
        event = struct.pack('<I', UHID_SET_REPORT_REPLY) + bytes(reply)
        try:
            os.write(self.fd, event)
        except OSError as e:
            print(f"[-] SET_REPORT_REPLY error: {e}")

    def _handle_output_report(self, rnum, data):
        """Handle output report (e.g., haptic rumble 0x80)."""
        if rnum == 0x80 and len(data) >= 9:
            # Haptic rumble — log it, no hardware to forward to
            left_speed = struct.unpack_from('<H', data, 3)[0] if len(data) >= 5 else 0
            right_speed = struct.unpack_from('<H', data, 6)[0] if len(data) >= 8 else 0
            if left_speed or right_speed:
                print(f"[haptic] Rumble: left={left_speed} right={right_speed}")
        else:
            print(f"[output] Report ID 0x{rnum:02x} len={len(data)} data={data[:20].hex()}")

    def _input_loop(self):
        """Send synthetic idle gamepad reports at ~10Hz."""
        print("[+] Synthetic input loop started (10Hz idle reports)")
        while self._running:
            self.seq_num = (self.seq_num + 1) & 0xFF
            timestamp_us = int((time.monotonic() - self.start_time) * 1000000) & 0xFFFFFFFF

            # 12-byte gamepad report (Report ID 0x01)
            gamepad = bytearray(12)

            # 45-byte SC2 custom report (Report ID 0x45)
            sc2 = bytearray(45)
            sc2[0] = self.seq_num
            struct.pack_into("<I", sc2, 29, timestamp_us)

            self._send_input(0x01, bytes(gamepad))
            self._send_input(0x45, bytes(sc2))

            time.sleep(0.1)  # 10Hz

    def _send_input(self, report_id, data):
        """Send an input report via UHID_INPUT2."""
        # UHID_INPUT2 payload: size(2) + data
        payload = struct.pack('<H', len(data)) + data
        event = struct.pack('<I', UHID_INPUT2) + payload
        try:
            os.write(self.fd, event)
        except OSError:
            pass


def main():
    parser = argparse.ArgumentParser(
        description="UHID-based Virtual Steam Controller 2026 (host-side, no BLE)"
    )
    parser.add_argument(
        "--name",
        default="Steam Controller 2026",
        help="Device name shown in Steam (default: 'Steam Controller 2026')",
    )
    args = parser.parse_args()

    device = UhidSC2Device(name=args.name)

    def signal_handler(signum, frame):
        print("\n[*] Shutting down...")
        device.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    device.open()
    device.start()

    print("[*] Virtual SC2 device created. Steam should see it.")
    print("[*] Check: ls -la /dev/hidraw* and evtest /dev/input/event*")
    print("[*] Press Ctrl+C to stop.")

    # Keep main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        device.stop()


if __name__ == "__main__":
    main()
