#!/usr/bin/env python3
"""
Main entrypoint for Steam Controller 2026 BLE Spoof.

Uses a raw L2CAP ATT server to bypass BlueZ's GATT server bug.
BlueZ is still used for:
  - LE advertising (LEAdvertisingManager1)
  - SMP pairing (kernel handles on CID 6)
  - Agent registration (auto-confirm pairing)

The ATT server handles:
  - ATT PDU exchange on CID 4 (raw L2CAP socket)
  - GATT service/characteristic/discovery
  - Input report notifications
"""

import argparse
import json
import os
import signal
import struct
import sys
import threading

import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib

# Structured protocol logging (enabled via SPOOFDECK_PROTO_LOG=1)
_PROTO_LOG = os.environ.get('SPOOFDECK_PROTO_LOG', '') == '1'

def _proto_log(event, **kwargs):
    """Emit a structured JSON log line to stderr when SPOOFDECK_PROTO_LOG=1."""
    if not _PROTO_LOG:
        return
    import time as _time
    entry = {"ts": round(_time.monotonic(), 3), "event": event}
    entry.update(kwargs)
    try:
        print(json.dumps(entry), flush=True)
    except Exception:
        pass

from gatt_db import build_sc2_database
from att_server import AttServer
from adv import LEAdvertisement, setup_adapter_properties
from input_handler import InputHandler
from agent import register_agent, unregister_agent, AGENT_PATH
from bluez import (
    get_adapter_path,
    is_adapter_powered,
    power_on_adapter,
    print_adapter_info,
)


BLUEZ_SERVICE_NAME = "org.bluez"
LE_ADVERTISING_MANAGER_IFACE = "org.bluez.LEAdvertisingManager1"
ADAPTER_IFACE = "org.bluez.Adapter1"
DBUS_PROPERTIES_IFACE = "org.freedesktop.DBus.Properties"

# Handle for the Report characteristic (input reports)
# This must match the handle assigned by build_sc2_database()
REPORT_CH_HANDLE = None  # Computed after database is built


class HoGPeripheral:
    """
    HID over GATT Peripheral for Steam Controller 2026 BLE Spoof.

    Architecture:
      - BlueZ handles advertising + SMP pairing
      - Raw L2CAP ATT server handles GATT data exchange
      - Input handler reads Deck controller → sends as BLE notifications
    """

    def __init__(self, bus, adapter_name="hci0"):
        self.bus = bus
        self.adapter_name = adapter_name
        self.adapter_path = get_adapter_path(bus, adapter_name)
        self.adv = None
        self.agent = None
        self.input_handler = None
        self.mainloop = None
        self.att_server = None
        self.gatt_db = None
        self._report_handle = None
        self._mouse_report_handle = None
        self._keyboard_report_handle = None
        self._sc2_report_handle = None
        # Not reset on disconnect — matches real SC2 behavior where mode persists across connections.
        self.steam_input_mode = False
        # Settings persist across connections (matches real SC2 behavior — settings stored in flash).
        # Intentionally NOT cleared on disconnect.
        self._settings_store = {}  # register_index -> value (for GET_SETTINGS_VALUES)

    def setup(self, local_name="Steam Controller 2026"):
        """Set up GATT database and advertisement."""
        # Build the GATT database (no D-Bus dependency)
        self.gatt_db = build_sc2_database(local_name)
        print(f"[+] GATT database built: {len(self.gatt_db.attributes)} attributes, "
              f"{len(self.gatt_db.services)} services")

        # Find the Report characteristic handles for input notifications
        self._report_handle = self._find_report_char_handle(0x01, 0x01)
        self._mouse_report_handle = self._find_report_char_handle(0x03, 0x01)
        self._keyboard_report_handle = self._find_report_char_handle(0x04, 0x01)
        print(f"[+] Gamepad Report handle: 0x{self._report_handle:04x}" if self._report_handle else "[-] WARNING: Gamepad Report characteristic not found")
        print(f"[+] Mouse Report handle: 0x{self._mouse_report_handle:04x}" if self._mouse_report_handle else "[-] WARNING: Mouse Report characteristic not found")
        print(f"[+] Keyboard Report handle: 0x{self._keyboard_report_handle:04x}" if self._keyboard_report_handle else "[-] WARNING: Keyboard Report characteristic not found")

        # Find the SC2 custom characteristic handle (Valve Custom Service)
        self._find_sc2_report_handle()
        print(f"[+] SC2 Custom Report characteristic handle: 0x{self._sc2_report_handle:04x}" if self._sc2_report_handle
              else "[-] WARNING: SC2 Custom Report characteristic not found")

        # Find CHR_REPORT handles in HID Service for hog-ll subscription
        self._sc2_hid_handle = self._find_report_char_handle(0x45, 0x01)
        print(f"[+] SC2 CHR_REPORT (HID Service) handle: 0x{self._sc2_hid_handle:04x}" if self._sc2_hid_handle
              else "[-] WARNING: SC2 CHR_REPORT not found in HID Service")

        # Create advertisement object
        adv_path = "/com/steamdeck/sc2/adv0"
        from gatt_db import SC2_HID_SERVICE_UUID
        self.adv = LEAdvertisement(
            self.bus, adv_path, local_name,
            service_uuids=["1812", "180f"],  # HID + Battery (matches real SC2 firmware)
            appearance=0x03C4,
        )

        # Set up Feature Report callbacks
        self._neptune_feature_fd = None
        self._setup_feature_report_callbacks()
        self._setup_haptic_callback()
        print(f"[+] Advertisement object created at {adv_path}")

        # Create raw ATT server
        self.att_server = AttServer(self.gatt_db, mtu=517)
        self.att_server._on_connection = self._on_att_connection
        self.att_server._on_disconnection = self._on_att_disconnection
        self.att_server._on_cccd_enabled = self._on_cccd_enabled

    def _find_sc2_report_handle(self):
        """Find the handle of the SC2 custom characteristic for input notifications."""
        from gatt_db import SC2_INPUT_CH1_UUID, uuid_to_bytes
        sc2_uuid_bytes = uuid_to_bytes(SC2_INPUT_CH1_UUID)
        for handle, attr in self.gatt_db.attributes.items():
            if attr.uuid == sc2_uuid_bytes:
                if attr.properties & 0x10:
                    self._sc2_report_handle = handle
                    return
        # Fallback: look for the characteristic declaration
        for handle, attr in self.gatt_db.attributes.items():
            if attr.uuid == b'\x03\x28':  # Characteristic declaration UUID
                if len(attr.value) >= 19:
                    char_uuid = attr.value[3:]
                    props = attr.value[0]
                    if char_uuid == sc2_uuid_bytes and props & 0x10:
                        val_handle = attr.value[1] | (attr.value[2] << 8)
                        self._sc2_report_handle = val_handle
                        return

    def _find_report_char_handle(self, report_id, report_type):
        """Find the value handle of a CHR_REPORT with specific Report ID and Report Type."""
        for handle, attr in self.gatt_db.attributes.items():
            # Report characteristic UUID is 0x2A4D
            if attr.uuid == b'\x4d\x2a':
                # Find its descriptors (scan forward until next characteristic or service)
                desc_handle = handle + 1
                while True:
                    desc = self.gatt_db.lookup(desc_handle)
                    if not desc:
                        break
                    # Stop if we hit a service or characteristic declaration
                    if desc.uuid in (b'\x00\x28', b'\x01\x28', b'\x03\x28'):
                        break
                    if desc.uuid == b'\x08\x29':  # Report Reference UUID
                        if len(desc.value) >= 2 and desc.value[0] == report_id and desc.value[1] == report_type:
                            return handle
                    desc_handle += 1
        return None

    # SC2 command IDs (sent via Feature Report 0x00)
    SC2_CMD_CLEAR_MAPPINGS         = 0x81
    SC2_CMD_GET_ATTRIBUTES         = 0x83
    # NOTE: 0x85 is BOTH a Feature Report ID (Mode Switch, handled by _on_feature_report_write)
    # AND a command byte (SET_DEFAULT_DIGITAL_MAPPINGS, handled by _handle_sc2_command).
    # These are different namespaces — FR IDs are in the HID descriptor, command bytes are
    # in the Feature Report payload. The handler dispatches based on context (FR write vs command).
    SC2_CMD_SET_DEFAULT_MAPPINGS   = 0x85
    SC2_CMD_SET_ATTRIBUTES         = 0x87
    SC2_CMD_GET_SETTINGS_VALUES    = 0x89
    SC2_CMD_GET_SETTINGS_DEFAULTS  = 0x8C
    SC2_CMD_SET_CONTROLLER_MODE    = 0x8D
    SC2_CMD_GET_CHIP_ID            = 0xBA
    SC2_CMD_GET_SERIAL             = 0xAE

    def _setup_feature_report_callbacks(self):
        """Register callbacks for Feature Reports (Report IDs 0x01, 0x02, 0x85, 0x86, 0x87)."""
        self._pending_fr_response = {}  # report_id -> response bytes (for command/response pattern)
        feature_report_ids = [0x01, 0x02, 0x85, 0x86, 0x87]
        for report_id in feature_report_ids:
            handle = self._find_report_char_handle(report_id, 0x03)  # 0x03 = Feature Report
            if handle:
                print(f"[+] Registering Feature Report ID 0x{report_id:02x} callback on handle 0x{handle:04x}")
                self.gatt_db.read_callbacks[handle] = lambda r_id=report_id: self._on_feature_report_read(r_id)
                self.gatt_db.write_callbacks[handle] = lambda value, r_id=report_id: self._on_feature_report_write(r_id, value)

    def _setup_haptic_callback(self):
        """Register write callbacks on SC2 output report handles for haptic forwarding.

        When the host writes a haptic rumble command (report ID 0x80) to the
        SC2 report characteristic or CHR_REPORT, forward it to the Neptune
        controller via os.write() on the hidraw device.
        """
        # Find and register on the actual Output Report ID 0x80 characteristic handle
        haptic_handle = self._find_report_char_handle(0x80, 0x02)
        if haptic_handle:
            print(f"[+] Registering haptic callback on HID Haptic (0x80 Output) handle 0x{haptic_handle:04x}")
            self.gatt_db.write_callbacks[haptic_handle] = lambda value, h=haptic_handle: self._on_haptic_write(h, value)
        else:
            print("[-] WARNING: HID Haptic (0x80 Output) characteristic handle not found")

        # Keep registrations on custom and standard input reports just in case
        for label, handle in [("Valve Custom", self._sc2_report_handle), ("HID Service", self._sc2_hid_handle)]:
            if handle:
                print(f"[+] Registering haptic callback on {label} handle 0x{handle:04x}")
                self.gatt_db.write_callbacks[handle] = lambda value, h=handle: self._on_haptic_write(h, value)

    def _prepopulate_responses(self):
        """Pre-populate FR 0x01 responses for GATT discovery reads.
        
        BlueZ's hog-lib.c sends ATT Read Requests for Feature Report 0x01
        during GATT discovery, BEFORE Steam sends any SET_REPORT commands.
        
        We return zeros — Steam's feature report processing will handle the
        actual handshake when it opens the controller. Returning synthetic
        data during GATT discovery may confuse the UHID device setup.
        """
        self._fr_response_queue = []
        print(f"[+] Pre-populated FR 0x01 responses (zeros) for GATT discovery")

    def _on_haptic_write(self, handle, value):
        """Handle writes to the SC2 output report characteristic.

        Parses the report ID and forwards haptic commands to Neptune.
        """
        print(f"[haptic] Write callback triggered on handle 0x{handle:04x} len={len(value)} data={value.hex()}")
        _proto_log("haptic_write", handle=f"0x{handle:04x}", len=len(value), data=value.hex())
        if len(value) < 1:
            return
        report_id = value[0]
        # Haptic rumble: report ID 0x80, payload 9 bytes (type, intensity, left.speed, left.gain, right.speed, right.gain)
        if report_id == 0x80 and len(value) >= 10:
            # Parse haptic rumble from SDL3 MsgHapticRumble format
            # value[0] = report_id (0x80)
            # value[1] = type (uint8)
            # value[2-3] = intensity (uint16 LE)
            # value[4-5] = left.speed (uint16 LE)
            # value[6] = left.gain (int8)
            # value[7-8] = right.speed (uint16 LE)
            # value[9] = right.gain (int8)
            left_speed = struct.unpack_from('<H', value, 4)[0]
            right_speed = struct.unpack_from('<H', value, 7)[0]
            print(f"[haptic] Rumble (Report ID 0x80): left={left_speed} right={right_speed}")
            self._forward_haptic_to_neptune(left_speed, right_speed)
        elif len(value) == 9:
            # Report ID 0x80 was stripped by hog-ll, value is just the payload:
            # value[0] = type (uint8)
            # value[1-2] = intensity (uint16 LE)
            # value[3-4] = left.speed (uint16 LE)
            # value[5] = left.gain (int8)
            # value[6-7] = right.speed (uint16 LE)
            # value[8] = right.gain (int8)
            left_speed = struct.unpack_from('<H', value, 3)[0]
            right_speed = struct.unpack_from('<H', value, 6)[0]
            print(f"[haptic] Rumble (Stripped Report ID): left={left_speed} right={right_speed}")
            self._forward_haptic_to_neptune(left_speed, right_speed)
        else:
            # Forward unknown output reports to Neptune verbatim.
            # This is a catch-all — could forward unintended calibration/LED commands.
            print(f"[haptic] Unknown output report ID=0x{report_id:02x} len={len(value)}, forwarding raw")
            self._forward_raw_to_neptune(value)

    def _forward_haptic_to_neptune(self, left_speed, right_speed):
        """Forward haptic rumble to the Neptune controller via hidraw output report."""
        try:
            # Neptune rumble format per InputPlumber's PackedRumbleReport:
            # 64-byte struct: [0xeb, 0x09, 0x00, 0x00, 0x00, left_lo, left_hi, right_lo, right_hi, ...]
            left_i = min(0xFFFF, left_speed)
            right_i = min(0xFFFF, right_speed)
            report = bytearray(64)
            report[0] = 0xeb  # TriggerRumbleCommand
            report[1] = 0x09  # report_size
            report[2] = 0x00  # unk_2
            report[3] = 0x00  # event_type
            report[4] = 0x00  # intensity
            report[5] = left_i & 0xFF
            report[6] = (left_i >> 8) & 0xFF
            report[7] = right_i & 0xFF
            report[8] = (right_i >> 8) & 0xFF
            self._write_neptune_output(bytes(report))
        except Exception as e:
            print(f"[-] Haptic forward error: {e}")

    def _forward_raw_to_neptune(self, data):
        """Forward raw output report to Neptune controller."""
        self._write_neptune_output(data)

    def _write_neptune_output(self, data):
        """Write an output report to the Neptune hidraw device."""
        self._ensure_neptune_feature_fd()
        if self._neptune_feature_fd:
            try:
                written = os.write(self._neptune_feature_fd, data)
                print(f"[haptic] ✅ Neptune output written: {written} bytes data={data.hex()}")
            except Exception as e:
                print(f"[haptic] ❌ Neptune output write error: {e}")
                self._close_neptune_feature_fd()
        else:
            print(f"[haptic] ❌ Neptune fd not available, dropping {len(data)} bytes")

    def _on_feature_report_read(self, report_id):
        """Called when the host reads a Feature Report from the GATT database.
        
        For FR 0x01 and 0x02 (SC2 command channels), return the pending
        synthetic response. For GATT discovery reads (before any writes),
        use the pre-populated response queue. For other FRs, proxy to Neptune.
        """
        import time, traceback
        ts = time.strftime('%H:%M:%S')
        print(f"[DIAG] [{ts}] 📤 FR 0x{report_id:02x} READ called — pending keys: {list(self._pending_fr_response.keys())}")

        # SC2 command channels — return synthetic response
        if report_id in (0x01, 0x02):
            # First check if there's a pending response from a write command
            response = self._pending_fr_response.pop(report_id, None)
            if response:
                print(f"[DIAG] [{ts}] 📤 FR 0x{report_id:02x} READ → returning write response: {response[:20].hex()}...")
                return response
            
            # If no pending write response, use the pre-populated queue
            # (for GATT discovery reads before any writes)
            if hasattr(self, '_fr_response_queue') and self._fr_response_queue:
                response = self._fr_response_queue.pop(0)
                print(f"[DIAG] [{ts}] 📤 FR 0x{report_id:02x} READ → returning queued response: {response[:20].hex()}...")
                return response
            
            print(f"[DIAG] [{ts}] 📤 FR 0x{report_id:02x} READ → no pending response, returning zeros")
            return b'\x00' * 64

        # Other Feature Reports — proxy to Neptune hardware
        return self._proxy_feature_read(report_id)

    def _on_feature_report_write(self, report_id, value):
        """Called when the host writes a Feature Report to the GATT database.
        
        For FR 0x01 and 0x02, parse the SC2 command and generate a synthetic
        response. For FR 0x85, handle the mode switch. For others, proxy to Neptune.
        """
        import time
        ts = time.strftime('%H:%M:%S')
        print(f"[DIAG] [{ts}] ⭐ FEATURE REPORT WRITE: ID=0x{report_id:02x} len={len(value)} data={value[:20].hex()}{'...' if len(value) > 20 else ''}")

        if report_id == 0x85:
            self._handle_mode_switch(value)
            return

        # SC2 command channels — handle synthetically
        if report_id in (0x01, 0x02):
            self._handle_sc2_command(report_id, value)
            return

        # Other Feature Reports — proxy to Neptune
        self._proxy_feature_write(report_id, value)

    def _handle_mode_switch(self, value, from_command=False):
        """Handle mode switch between Lizard and Steam Input.

        Called from Feature Report 0x85 write and SC2 command 0x8D (SET_CONTROLLER_MODE).

        Args:
            value: Raw ATT write data (includes Report ID prefix from hog-ll)
            from_command: True if called from SC2 command 0x8D (format: [ReportID, cmd, len, mode, ...])
                         False if called from FR 0x85 write (format: [0x85, mode, ...])
        """
        if len(value) > 0:
            if from_command:
                # SC2 command 0x8D format: [ReportID, 0x8D, length, mode, ...]
                # Mode byte is at index 3
                mode = value[3] if len(value) > 3 else 0x00
            elif value[0] == 0x85:
                # FR 0x85 write format: [0x85, mode, ...]
                # Mode byte is at index 1
                mode = value[1] if len(value) > 1 else 0x00
            else:
                mode = value[0]
            if mode == 0x01:
                self.steam_input_mode = True
                print("[DIAG] ⭐ MODE SWITCH: Lizard → Steam Input Mode")
                print(f"[DIAG]    Gamepad handle=0x{self._report_handle:04x}" if self._report_handle else "[DIAG]    Gamepad handle=NONE")
                print(f"[DIAG]    SC2 Custom handle=0x{self._sc2_report_handle:04x}" if self._sc2_report_handle else "[DIAG]    SC2 Custom handle=NONE")
                if self.att_server:
                    self.att_server.print_active_subscriptions()
            elif mode == 0x00:
                self.steam_input_mode = False
                print("[DIAG] ⭐ MODE SWITCH: Steam Input → Lizard Mode")
                if self.att_server:
                    self.att_server.print_active_subscriptions()
            else:
                print(f"[DIAG] ❓ Unknown mode value written to Feature Report 0x85: {value.hex()}")

    def _handle_sc2_command(self, report_id, value):
        """Parse and respond to SC2 commands written to Feature Report 0x01 or 0x02.
        
        Steam Client communicates with the controller via a command/response protocol:
          1. Host writes a command to FR 0x01 (e.g., GET_ATTRIBUTES = 0x83)
          2. Host reads FR 0x01 to retrieve the response
         
        We intercept these and return synthetic SC2-appropriate responses.
        """
        if len(value) < 2:
            print(f"[DIAG] ⚠️  SC2 command too short: {value.hex()}")
            _proto_log("sc2_cmd", fr_id=f"0x{report_id:02x}", data=value.hex(),
                       error="TOO_SHORT")
            return

        # Parse command — first byte is the command ID.
        # hog-ll strips the Report ID prefix, so value[0] = cmd_id.
        cmd = value[0]
        
        print(f"[DIAG] 🎮 SC2 Command on FR 0x{report_id:02x}: cmd=0x{cmd:02x} data={value[:10].hex()}")

        response = bytearray(64)

        if cmd == self.SC2_CMD_GET_ATTRIBUTES:
            # GET_ATTRIBUTES (0x83) — Real device response from InputPlumber capture.
            # Format: [cmd_echo, length, attributes[]]
            # Each attribute: 1-byte tag + 4-byte LE uint32 value.
            # Total: 2 + 45 (9 attrs x 5) + 17 padding = 64 bytes
            response = bytearray([
                0x83,       # header.type = ID_GET_ATTRIBUTES_VALUES
                0x2d,       # header.length = 45 (9 attributes x 5 bytes)
                # Attribute: ATTRIB_PRODUCT_ID (tag=1) = 0x1303 (SC2 BLE PID)
                0x01, 0x03, 0x13, 0x00, 0x00,
                # Attribute: ATTRIB_CAPABILITIES (tag=2) = 0x4169bfff (from SC2 protocol analysis)
                # Bits: buttons(0-9), triggers(10-19), joysticks(20-25), trackpads(26-29),
                #       IMU(30-31), haptics(37), dual trackpads(39)
                0x02, 0xff, 0xbf, 0x69, 0x41,
                # Attribute: ATTRIB_BOOTLOADER_BUILD_TIME (tag=10)
                0x0a, 0x2b, 0x12, 0xa9, 0x62,
                # Attribute: ATTRIB_FIRMWARE_BUILD_TIME (tag=4)
                0x04, 0xad, 0xf1, 0xe4, 0x65,
                # Attribute: ATTRIB_BOARD_REVISION (tag=9) = 46
                0x09, 0x2e, 0x00, 0x00, 0x00,
                # Attribute: ATTRIB_CONNECTION_INTERVAL_IN_US (tag=11) = 4000
                0x0b, 0xa0, 0x0f, 0x00, 0x00,
                # Extended attributes (tags 13, 12, 14) = 0
                0x0d, 0x00, 0x00, 0x00, 0x00,
                0x0c, 0x00, 0x00, 0x00, 0x00,
                0x0e, 0x00, 0x00, 0x00, 0x00,
                # Zero padding to 64 bytes (17 zeros)
                0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
                0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
                0x00,
            ])
            print(f"[DIAG] 🎮 → Responding to GET_ATTRIBUTES with synthetic SC2 device info")

        elif cmd == self.SC2_CMD_GET_SERIAL:
            # GET_SERIAL (0xAE) — Response format (23 bytes total):
            #   byte[0] = 0xAE (command echo)
            #   byte[1] = 0x15 (payload length — MUST match write command's byte[1])
            #   byte[2] = 0x01 (success status — required by V_strncmp validation path)
            #   bytes[3-22] = serial number (20 bytes, first byte must be 'F')
            #
            # Validation: V_strncmp(serial[0], 'F', count=1) at 0x10c29b3
            # If serial[0] != 'F' → "Controller Serial# invalid" → identity slot not populated → zombie
            # The BLE PCB Serial# check (FUN_0122e4c0) logs "PCB Serial# invalid" but is cosmetic
            serial = b'F0000-0000-00000000'  # Must start with 'F' to pass V_strncmp validation
            response = bytearray([
                0xAE,       # command echo
                0x15,       # payload length (0x15 = 21, matches write command byte[1])
                0x01,       # success status (required — 0x00 or 0x04 triggers "Controller Serial# invalid")
            ])
            response += serial[:20].ljust(20, b'\x00')  # pad serial to 20 bytes
            response += bytearray(64 - len(response))  # pad to 64 bytes
            print(f"[DIAG] 🎮 → Responding to GET_SERIAL with '{serial.decode()}'")

        elif cmd == self.SC2_CMD_GET_CHIP_ID:
            # GET_CHIP_ID (0xBA) — Return chip ID (15-byte identifier)
            # Format from InputPlumber: [0xBA, 0x11, 0x00, chip_id_15_bytes, padding]
            # Fabricated chip ID. Real SC2 uses Nordic nRF52840, not NXP.
            # Steam may validate this against known values — needs testing.
            chip_id = bytes([
                0x4e, 0x58, 0x50, 0x35, 0x33, 0x37, 0x30, 0x30,
                0x30, 0x31, 0x32, 0x33, 0x34, 0x35, 0x36,
            ])  # "NXP5370000123456"
            response = bytearray([
                0xBA,       # header.type = GetChipId
                0x11,       # header.length = 17
                0x00,       # status
            ])
            response += chip_id
            response += bytearray(64 - len(response))  # pad to 64
            print(f"[DIAG] 🎮 → Responding to GET_CHIP_ID with chip ID")

        elif cmd == self.SC2_CMD_CLEAR_MAPPINGS:
            # CLEAR_MAPPINGS (0x81) — Echo back with proper header
            response = bytearray([
                0x81,       # header.type = ClearDigitalMappings
                0x00,       # header.length = 0
            ])
            response += bytearray(64 - len(response))
            print(f"[DIAG] 🎮 → Acknowledging CLEAR_MAPPINGS")

        elif cmd == self.SC2_CMD_SET_ATTRIBUTES:
            # SET_ATTRIBUTES (0x87) — Write-only command, but Steam may read FR 0x01
            # to verify the write succeeded. Store a success response.
            register = value[3] if len(value) > 3 else 0
            payload_len = value[2] if len(value) > 2 else 0
            
            # The value data starts at offset 4, and its length is payload_len - 1
            # (since payload_len includes the 1-byte register).
            val_len = max(0, payload_len - 1)
            data_val = value[4:4+val_len] if len(value) >= 4 + val_len else value[4:6]
            print(f"[DIAG] 🎮 → SET_SETTINGS register=0x{register:02x} payload_len={payload_len} data={data_val.hex()}")
            
            # Store the setting so GET_SETTINGS_VALUES can return it
            if len(data_val) >= 2:
                self._settings_store[register] = struct.unpack_from('<H', data_val)[0]
            elif len(data_val) == 1:
                self._settings_store[register] = data_val[0]
            else:
                self._settings_store[register] = 0
                
            # Respond with command echo + register echo + value echo
            response = bytearray([
                0x87,       # header.type = ID_SET_SETTINGS_VALUES
                payload_len,  # header.length = register(1) + value
                register,
            ])
            response += data_val
            response += bytearray(64 - len(response))
            # NOTE: Do NOT send ack notification on CHR_REPORT handles.
            # Sending non-zero data on input report handles causes phantom button presses
            # because the host interprets the ack bytes [0x87, 0x01, register] as a
            # 45-byte SC2 input report with non-zero button bitmask.

        elif cmd == self.SC2_CMD_GET_SETTINGS_VALUES:
            # GET_SETTINGS_VALUES (0x89) — Return current settings for requested registers.
            # Format: [cmd, num_registers, reg1, reg2, ...]
            # Response: [cmd, num_registers, reg1, val1_lo, val1_hi, reg2, val2_lo, val2_hi, ...]
            num_regs = value[2] if len(value) > 2 else 0
            response = bytearray([0x89, num_regs])
            for i in range(num_regs):
                reg_idx = 3 + i if len(value) > 3 + i else 0
                reg = value[reg_idx] if reg_idx < len(value) else 0
                val = self._settings_store.get(reg, 0)
                response += bytes([reg, val & 0xFF, (val >> 8) & 0xFF])
            response += bytearray(64 - len(response))
            print(f"[DIAG] 🎮 → GET_SETTINGS_VALUES: returning {num_regs} registers")

        elif cmd == 0xf2:
            # 0xf2 is a MAPPING ACK — minimal 6-byte response per firmware FUN_00042132.
            # Not a capability query. Sent by firmware after 0xe7 (mapping) commands.
            # Format: [0x01, 0x00, 0x00, 0x00, 0x00, 0xf2] (6 bytes, no payload)
            response = bytearray([0x01, 0x00, 0x00, 0x00, 0x00, 0xf2])
            response += bytearray(64 - len(response))
            print(f"[DIAG] 🎮 → Command 0xf2 (MAPPING_ACK): {response[:6].hex()}")

        elif cmd == self.SC2_CMD_SET_DEFAULT_MAPPINGS:
            # SET_DEFAULT_DIGITAL_MAPPINGS (0x85) — Acknowledge only, no mode switch
            response = bytearray([
                0x85,       # header.type = SetDefaultDigitalMappings
                0x00,       # header.length = 0
            ])
            response += bytearray(64 - len(response))
            print(f"[DIAG] 🎮 → Acknowledging SET_DEFAULT_DIGITAL_MAPPINGS")

        elif cmd == self.SC2_CMD_SET_CONTROLLER_MODE:
            # SET_CONTROLLER_MODE (0x8D) — Handle mode switch, echo back
            self._handle_mode_switch(value, from_command=True)
            response = bytearray([
                0x8D,       # header.type = SetControllerMode
                0x00,       # header.length = 0
            ])
            response += bytearray(64 - len(response))
            print(f"[DIAG] 🎮 → Acknowledging SET_CONTROLLER_MODE")

        elif cmd == 0xB4:
            # Protocol Version Query — blocking on native Deck, echo ack
            response = bytearray([0xB4, 0x00, 0x01])
            response += bytearray(64 - len(response))
            print(f"[DIAG] 🎮 → Protocol Version Query (0xB4)")

        elif cmd == 0xB5:
            # Protocol Command — echo ack
            response = bytearray([0xB5, 0x00])
            response += bytearray(64 - len(response))
            print(f"[DIAG] 🎮 → Protocol Command (0xB5)")

        elif cmd == 0xEE:
            # Feature Report Message (write) — echo ack
            response = bytearray([0xEE, 0x00])
            response += bytearray(64 - len(response))
            print(f"[DIAG] 🎮 → Feature Report Message (0xEE)")

        elif cmd == 0xEF:
            # Feature Report Message (read/key) — echo ack
            response = bytearray([0xEF, 0x00])
            response += bytearray(64 - len(response))
            print(f"[DIAG] 🎮 → Feature Report Message Read (0xEF)")

        elif cmd == 0x95:
            # Enter Bootloader — acknowledge but don't actually reboot
            response = bytearray([0x95, 0x00])
            response += bytearray(64 - len(response))
            print(f"[DIAG] 🎮 → Enter Bootloader (0x95) — ignored on spoof")

        elif cmd == 0x8C:
            # GET_SETTINGS_DEFAULTS — return zero defaults
            response = bytearray([0x8C, 0x00])
            response += bytearray(64 - len(response))
            print(f"[DIAG] 🎮 → GET_SETTINGS_DEFAULTS (0x8C)")

        elif cmd == 0x82:
            # GET_DIGITAL_MAPPINGS — firmware returns error (0xff, 0x02)
            response = bytearray([0x82, 0xFF, 0x02])
            response += bytearray(64 - len(response))
            print(f"[DIAG] 🎮 → GET_DIGITAL_MAPPINGS (0x82) — error response")

        else:
            # Unknown command — echo back with proper header format
            response = bytearray([
                cmd,        # header.type = command echo
                0x00,       # header.length = 0
            ])
            response += bytearray(64 - len(response))
            print(f"[DIAG] 🎮 → Unknown SC2 command 0x{cmd:02x}, echoing with zero payload")

        self._pending_fr_response[report_id] = bytes(response)
        print(f"[DIAG] 📥 FR 0x{report_id:02x} STORED: len={len(response)} first10={response[:10].hex()} pending_keys={list(self._pending_fr_response.keys())}")

        # Map cmd byte to human name
        _SC2_CMD_NAMES = {
            0x81: "CLEAR_DIGITAL_MAPPINGS", 0x82: "GET_DIGITAL_MAPPINGS",
            0x83: "GET_ATTRIBUTES", 0x85: "SET_DEFAULT_DIGITAL_MAPPINGS",
            0x87: "SET_SETTINGS_VALUES", 0x89: "GET_SETTINGS_VALUES",
            0x8C: "GET_SETTINGS_DEFAULTS", 0x8D: "SET_CONTROLLER_MODE",
            0xAE: "GET_SERIAL", 0xB4: "PROTOCOL_VERSION",
            0xB5: "PROTOCOL_COMMAND", 0xBA: "GET_CHIP_ID",
            0xEE: "FEATURE_REPORT_WRITE", 0xEF: "FEATURE_REPORT_READ",
            0x95: "ENTER_BOOTLOADER", 0xF2: "MAPPING_ACK",
        }
        _proto_log("sc2_cmd", fr_id=f"0x{report_id:02x}", cmd=f"0x{cmd:02x}",
                   cmd_name=_SC2_CMD_NAMES.get(cmd, f"UNKNOWN_0x{cmd:02x}"),
                   data=value[:20].hex(),
                   response=response[:64].hex(), response_len=len(response))

    def _proxy_feature_read(self, report_id):
        """Proxy a Feature Report read to Neptune hardware (for non-SC2 reports)."""
        self._ensure_neptune_feature_fd()
        if self._neptune_feature_fd:
            import fcntl, array
            length = 65
            # HIDIOCGFEATURE ioctl encoding:
            # bits 31-30: direction = _IOC_READ (3)
            # bits 29-16: size = length
            # bits 15-8:  type = 'H' (72, from linux/hidraw.h HID_MAX_USAGES)
            # bits 7-0:   number = 7 (HIDIOCGFEATURE) or 6 (HIDIOCSFEATURE)
            ioctl_num = (3 << 30) | (length << 16) | (72 << 8) | 7
            buf = array.array('B', [0] * length)
            buf[0] = report_id
            try:
                fcntl.ioctl(self._neptune_feature_fd, ioctl_num, buf, True)
                print(f"[att] Proxy Feature Report 0x{report_id:02x} read success, payload: {buf[1:10].tolist()}")
                return bytes(buf[1:])
            except Exception as e:
                print(f"[-] Proxy Feature Report 0x{report_id:02x} read error: {e}")
                self._close_neptune_feature_fd()
        return b'\x00' * 64

    def _proxy_feature_write(self, report_id, value):
        """Proxy a Feature Report write to Neptune hardware (for non-SC2 reports)."""
        self._ensure_neptune_feature_fd()
        if self._neptune_feature_fd:
            try:
                import fcntl, array
                length = len(value) + 1
                ioctl_num = (3 << 30) | (length << 16) | (72 << 8) | 6
                buf = array.array('B', [report_id] + list(value))
                fcntl.ioctl(self._neptune_feature_fd, ioctl_num, buf, True)
                print(f"[att] Proxy Feature Report 0x{report_id:02x} write success, len={len(value)}")
            except Exception as e:
                print(f"[-] Proxy Feature Report 0x{report_id:02x} write error: {e}")
                self._close_neptune_feature_fd()

    def _ensure_neptune_feature_fd(self):
        """Open the Neptune feature report fd if not already open."""
        if self._neptune_feature_fd:
            return
        dev_path = None
        if self.input_handler and self.input_handler._is_neptune:
            dev_path = self.input_handler.device_path
        if not dev_path:
            from input_handler import find_neptune_hidraw
            dev_path = find_neptune_hidraw()
        if dev_path:
            try:
                import os
                self._neptune_feature_fd = os.open(dev_path, os.O_RDWR)
                print(f"[+] Neptune feature report proxy fd opened: {dev_path}")
            except Exception as e:
                print(f"[-] Failed to open Neptune feature report proxy: {e}")

    def _close_neptune_feature_fd(self):
        """Close the Neptune feature report fd on error (will be reopened on next attempt)."""
        if self._neptune_feature_fd:
            try:
                import os
                os.close(self._neptune_feature_fd)
            except OSError:
                pass
            self._neptune_feature_fd = None
            print(f"[DIAG] Neptune feature fd closed (will reopen on next use)")

    def _on_att_connection(self, addr):
        print(f"[+] ATT connection established from {addr}")
        self._pending_fr_response.clear()
        self._prepopulate_responses()

    def _on_cccd_enabled(self, handle):
        """Called when a CCCD is enabled for an input report."""
        print(f"[DIAG] CCCD callback: handle=0x{handle:04x} _report_handle=0x{self._report_handle:04x} _sc2_hid_handle=0x{self._sc2_hid_handle:04x} att_server={'yes' if self.att_server else 'no'}")
        # Build a map of known handles for diagnostic output
        handle_names = {}
        if self._report_handle:
            handle_names[self._report_handle] = f"Gamepad (0x{self._report_handle:04x})"
        if self._mouse_report_handle:
            handle_names[self._mouse_report_handle] = f"Mouse (0x{self._mouse_report_handle:04x})"
        if self._keyboard_report_handle:
            handle_names[self._keyboard_report_handle] = f"Keyboard (0x{self._keyboard_report_handle:04x})"
        if self._sc2_report_handle:
            handle_names[self._sc2_report_handle] = f"SC2 Custom (0x{self._sc2_report_handle:04x})"
        if self._sc2_hid_handle:
            handle_names[self._sc2_hid_handle] = f"SC2 CHR_REPORT (0x{self._sc2_hid_handle:04x})"

        name = handle_names.get(handle, f"Unknown (0x{handle:04x})")
        print(f"[DIAG] 📡 CCCD ENABLED: {name}")

        # Print all active subscriptions
        if self.att_server:
            active = sorted(self.att_server._notification_handles)
            names = [handle_names.get(h, f"0x{h:04x}") for h in active]
            print(f"[DIAG] 📡 Active subscriptions: {names}")

        # Auto-switch to Steam Input mode. The real SC2 starts in lizard mode and switches
        # when Steam sends an explicit command. We skip that and go directly to Steam Input
        # because the Deck doesn't need lizard mode (it has its own input devices).
        if handle in (self._report_handle, self._sc2_report_handle):
            if not self.steam_input_mode:
                self.steam_input_mode = True
                print(f"[DIAG] ⭐ AUTO MODE SWITCH: Host subscribed to {name} → Steam Input Mode")

        # CCCD TIMING FIX: Send multiple zero notifications to pre-fill the UHID queue.
        # The first notification is consumed by UHID device creation (UHID_CREATE2),
        # not forwarded to the application. Subsequent notifications become UHID_INPUT2
        # and reach /dev/hidrawN. CGetControllerInfoWorkItem::RunFunc calls
        # SDL_hid_read_timeout 51x at 100ms — we must have data ready.
        import threading as _threading
        import time as _time
        if handle == self._report_handle and self.att_server:
            def _send_gamepad_prefill():
                for i in range(5):
                    _time.sleep(0.01 * (i + 1))
                    try:
                        self.att_server.send_notification(self._report_handle, b'\x00' * 12)
                    except Exception:
                        pass
                print(f"[DIAG] Pre-filled UHID queue: 5x 12-byte zero gamepad on handle 0x{self._report_handle:04x}")
            _threading.Thread(target=_send_gamepad_prefill, daemon=True).start()
        if handle == self._sc2_hid_handle and self.att_server:
            def _send_sc2_prefill():
                for i in range(5):
                    _time.sleep(0.01 * (i + 1))
                    try:
                        self.att_server.send_notification(self._sc2_hid_handle, b'\x00' * 45)
                    except Exception:
                        pass
                print(f"[DIAG] Pre-filled UHID queue: 5x 45-byte zero SC2 on handle 0x{self._sc2_hid_handle:04x}")
            _threading.Thread(target=_send_sc2_prefill, daemon=True).start()

    def _on_att_disconnection(self, addr):
        print(f"[+] ATT connection lost from {addr}")
        self._schedule_adv_refresh()

    def _schedule_adv_refresh(self):
        """Re-register advertisement after a disconnect using GLib.idle_add to ensure
        it runs on the main loop. No retry if registration fails — if BlueZ is
        restarting, the device stops advertising until manually restarted."""

        def _refresh():
            try:
                obj = self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path)
                adv_manager = dbus.Interface(obj, LE_ADVERTISING_MANAGER_IFACE)
                adv_manager.RegisterAdvertisement(
                    self.adv.path, {},
                    reply_handler=lambda: print("[+] Advertisement re-registered"),
                    error_handler=lambda e: print(f"[-] Re-register failed: {e}"),
                )
            except Exception as e:
                print(f"[-] Adv refresh error: {e}")
            return False
        GLib.idle_add(_refresh)

    def _register_with_bluez(self):
        """Called via GLib.idle_add() after main loop starts."""
        # Register pairing agent
        try:
            self.agent = register_agent(self.bus)
        except dbus.exceptions.DBusException as e:
            print(f"[-] Agent registration failed: {e}")

        # Register advertisement with BlueZ
        try:
            obj = self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path)
            adv_manager = dbus.Interface(obj, LE_ADVERTISING_MANAGER_IFACE)
            adv_manager.RegisterAdvertisement(
                self.adv.path, {},
                reply_handler=self._on_adv_registered,
                error_handler=self._on_adv_error,
            )
            print("[*] RegisterAdvertisement dispatched...")
        except dbus.exceptions.DBusException as e:
            print(f"[-] Failed to register advertisement: {e}")

        # Set adapter properties for discoverable advertising
        setup_adapter_properties(self.bus, self.adapter_name)

        # Start the raw ATT server in a background thread
        print("[*] Starting raw L2CAP ATT server...")
        self.att_server.start_async()

        return False  # Remove from idle handler (run once)

    def _on_adv_registered(self):
        print("[+] Advertisement registered successfully")

    def _on_adv_error(self, error):
        print(f"[-] Advertisement registration failed: {error}")

    def start_input_capture(self, device_path=None):
        """Start capturing controller inputs from the Deck."""
        self.input_handler = InputHandler(
            on_report=self._on_input_report,
            device_path=device_path,
        )
        self.input_handler.start()

    def _on_input_report(self, report_dict):
        """Called when a new input report is ready. Send appropriate BLE notifications based on mode."""
        if not self.att_server or not self.att_server.connected:
            return

        if self.steam_input_mode:
            # Gamepad mode
            gamepad_12b = report_dict.get('gamepad_12b')
            gamepad_45b = report_dict.get('gamepad_45b')
            if gamepad_12b and self._report_handle:
                self.att_server.send_notification(self._report_handle, gamepad_12b)
            if gamepad_45b:
                # Send on both Valve Custom (for Steam's direct read) and CHR_REPORT (for hog-ll)
                if self._sc2_report_handle:
                    self.att_server.send_notification(self._sc2_report_handle, gamepad_45b)
                if self._sc2_hid_handle:
                    self.att_server.send_notification(self._sc2_hid_handle, gamepad_45b)
        # Lizard mode suppressed — SC2 protocol uses Feature Reports + CHR_REPORT for input.
        # Steam's SC2 driver handles everything via Feature Reports + CHR_REPORT.

    def run(self):
        """Run the main event loop."""
        self._grab_lizard_mode_devices()
        self.mainloop = GLib.MainLoop()

        def signal_handler(signum, frame):
            print("\n[*] Shutting down...")
            self.cleanup()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Schedule BlueZ registration after main loop starts
        GLib.idle_add(self._register_with_bluez)

        print("[*] Entering main loop. Press Ctrl+C to stop.")
        self.mainloop.run()

    _EVIOCGRAB = 0x40044590
    _lizard_grab_fds = {}

    def _grab_lizard_mode_devices(self):
        """Grab Steam Controller mouse/kbd evdev to prevent lizard mode on Deck desktop."""
        import fcntl, glob as _glob
        for evpath in sorted(_glob.glob('/dev/input/event*')):
            try:
                base = os.path.basename(evpath)
                name_path = f'/sys/class/input/{base}/device/name'
                phys_path = f'/sys/class/input/{base}/device/phys'
                if not os.path.exists(name_path):
                    continue
                with open(name_path) as f:
                    name = f.read().strip()
                with open(phys_path) as f:
                    phys = f.read().strip()
                # Only grab mouse (input0) and keyboard (input1) — NOT vendor HID (input2/hidraw3).
                # The vendor HID is read directly via hidraw for gamepad input.
                # If this filter changes, verify that hidraw3 read path still works.
                if 'Valve' in name and ('/input0' in phys or '/input1' in phys):
                    fd = os.open(evpath, os.O_RDONLY | os.O_NONBLOCK)
                    fcntl.ioctl(fd, self._EVIOCGRAB, 1)
                    self._lizard_grab_fds[evpath] = fd
                    print(f"[+] Grabbed {evpath} ({name}, {phys}) to disable lizard mode")
            except (OSError, FileNotFoundError):
                pass

    def _release_lizard_mode_devices(self):
        """Release grabbed evdev devices."""
        import fcntl
        for evpath, fd in self._lizard_grab_fds.items():
            try:
                fcntl.ioctl(fd, self._EVIOCGRAB, 0)
                os.close(fd)
                print(f"[+] Released {evpath}")
            except OSError:
                pass
        self._lizard_grab_fds.clear()

    def cleanup(self):
        """Clean up resources."""
        self._release_lizard_mode_devices()

        if hasattr(self, '_neptune_feature_fd') and self._neptune_feature_fd:
            try:
                import os
                os.close(self._neptune_feature_fd)
                print("[+] Neptune feature report proxy fd closed")
            except OSError:
                pass
            self._neptune_feature_fd = None

        if self.att_server:
            self.att_server.stop()

        if self.agent:
            unregister_agent(self.bus, self.agent)

        if self.input_handler:
            self.input_handler.stop()

        if self.mainloop:
            self.mainloop.quit()

        if self.adv:
            try:
                obj = self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path)
                adv_manager = dbus.Interface(obj, LE_ADVERTISING_MANAGER_IFACE)
                adv_manager.UnregisterAdvertisement(self.adv.path)
                print("[+] Advertisement unregistered")
            except dbus.exceptions.DBusException:
                pass

        try:
            obj = self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path)
            props = dbus.Interface(obj, DBUS_PROPERTIES_IFACE)
            props.Set(ADAPTER_IFACE, "Discoverable", dbus.Boolean(False))
            props.Set(ADAPTER_IFACE, "Alias", dbus.String("steamdeck"))
            print("[+] Adapter reset to default")
        except dbus.exceptions.DBusException:
            pass

        print("[+] Cleanup complete")


def main():
    parser = argparse.ArgumentParser(
        description="Steam Controller 2026 BLE Spoof (Raw L2CAP ATT)"
    )
    parser.add_argument(
        "--adapter",
        default="hci0",
        help="Bluetooth adapter name (default: hci0)",
    )
    parser.add_argument(
        "--name",
        default="Steam Controller 2026",
        help="BLE local name (default: Steam Controller 2026)",
    )
    parser.add_argument(
        "--device",
        default=None,
        help="Input device path (/dev/hidrawN for Neptune, /dev/input/eventN for evdev). Auto-detect if not specified.",
    )
    parser.add_argument(
        "--info",
        action="store_true",
        help="Print adapter info and exit",
    )

    args = parser.parse_args()

    # Initialize D-Bus (for advertising only)
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()

    # Check if BlueZ is running
    try:
        bus.get_object(BLUEZ_SERVICE_NAME, "/")
    except dbus.exceptions.DBusException:
        print("[-] BlueZ is not running on the system D-Bus")
        sys.exit(1)

    # Print adapter info if requested
    if args.info:
        print_adapter_info(bus, args.adapter)
        sys.exit(0)

    # Check adapter
    if not is_adapter_powered(bus, args.adapter):
        print(f"[*] Adapter {args.adapter} is not powered, powering on...")
        power_on_adapter(bus, args.adapter)

    # Print adapter info
    print_adapter_info(bus, args.adapter)

    # Set up the peripheral (GATT database + advertisement)
    peripheral = HoGPeripheral(bus, args.adapter)
    peripheral.setup(args.name)

    # Start input capture
    peripheral.start_input_capture(args.device)

    # Run main loop (advertising + ATT server via GLib idle)
    peripheral.run()


if __name__ == "__main__":
    main()
