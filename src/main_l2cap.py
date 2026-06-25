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
import signal
import sys
import threading

import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib

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
        self.steam_input_mode = False

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

        # Create advertisement object
        adv_path = "/com/steamdeck/sc2/adv0"
        from gatt_db import SC2_HID_SERVICE_UUID
        self.adv = LEAdvertisement(
            self.bus, adv_path, local_name,
            service_uuids=["1812", SC2_HID_SERVICE_UUID],  # HID + Valve Custom (for SC2 identification)
            appearance=0x03C4,
        )

        # Set up Feature Report callbacks
        self._neptune_feature_fd = None
        self._setup_feature_report_callbacks()
        print(f"[+] Advertisement object created at {adv_path}")

        # Create raw ATT server
        self.att_server = AttServer(self.gatt_db, mtu=517)
        self.att_server._on_connection = self._on_att_connection
        self.att_server._on_disconnection = self._on_att_disconnection
        self.att_server._on_cccd_enabled = self._on_cccd_enabled

    def _find_report_handle(self):
        """Find the handle of the Report characteristic for input notifications."""
        for handle, attr in self.gatt_db.attributes.items():
            # Report characteristic UUID is 0x2A4D
            if attr.uuid == b'\x4d\x2a':  # Little-endian UUID16
                # Check if it has NOTIFY property (0x10)
                if attr.properties & 0x10:
                    self._report_handle = handle
                    return
        # Fallback: look for the characteristic declaration
        for handle, attr in self.gatt_db.attributes.items():
            if attr.uuid == b'\x03\x28':  # Characteristic declaration UUID
                if len(attr.value) >= 5:
                    char_uuid = attr.value[3:5]
                    props = attr.value[0]
                    if char_uuid == b'\x4d\x2a' and props & 0x10:
                        val_handle = attr.value[1] | (attr.value[2] << 8)
                        self._report_handle = val_handle
                        return

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
    SC2_CMD_CLEAR_MAPPINGS     = 0x81
    SC2_CMD_GET_ATTRIBUTES     = 0x83
    SC2_CMD_SET_MODE           = 0x85
    SC2_CMD_SET_ATTRIBUTES     = 0x87
    SC2_CMD_GET_SERIAL         = 0xAE

    def _setup_feature_report_callbacks(self):
        """Register callbacks for Feature Reports (Report IDs 0x00, 0x01, 0x85, 0x86, 0x87)."""
        self._pending_fr_response = {}  # report_id -> response bytes (for command/response pattern)
        feature_report_ids = [0x00, 0x01, 0x85, 0x86, 0x87]
        for report_id in feature_report_ids:
            handle = self._find_report_char_handle(report_id, 0x03)  # 0x03 = Feature Report
            if handle:
                print(f"[+] Registering Feature Report ID 0x{report_id:02x} callback on handle 0x{handle:04x}")
                self.gatt_db.read_callbacks[handle] = lambda r_id=report_id: self._on_feature_report_read(r_id)
                self.gatt_db.write_callbacks[handle] = lambda value, r_id=report_id: self._on_feature_report_write(r_id, value)

    def _on_feature_report_read(self, report_id):
        """Called when the host reads a Feature Report from the GATT database.
        
        For FR 0x00 and 0x01 (SC2 command channels), return the pending
        synthetic response from the last command write. For other FRs,
        proxy to Neptune if available.
        """
        # SC2 command channels — return synthetic response
        if report_id in (0x00, 0x01):
            response = self._pending_fr_response.pop(report_id, None)
            if response:
                print(f"[DIAG] 📤 FR 0x{report_id:02x} READ → returning synthetic response: {response[:20].hex()}...")
                return response
            else:
                print(f"[DIAG] 📤 FR 0x{report_id:02x} READ → no pending response, returning zeros")
                return b'\x00' * 64

        # Other Feature Reports — proxy to Neptune hardware
        return self._proxy_feature_read(report_id)

    def _on_feature_report_write(self, report_id, value):
        """Called when the host writes a Feature Report to the GATT database.
        
        For FR 0x00 and 0x01, parse the SC2 command and generate a synthetic
        response. For FR 0x85, handle the mode switch. For others, proxy to Neptune.
        """
        print(f"[DIAG] ⭐ FEATURE REPORT WRITE: ID=0x{report_id:02x} len={len(value)} data={value[:20].hex()}{'...' if len(value) > 20 else ''}")

        if report_id == 0x85:
            self._handle_mode_switch(value)
            return

        # SC2 command channels — handle synthetically
        if report_id in (0x00, 0x01):
            self._handle_sc2_command(report_id, value)
            return

        # Other Feature Reports — proxy to Neptune
        self._proxy_feature_write(report_id, value)

    def _handle_mode_switch(self, value):
        """Handle Feature Report 0x85 (mode switch between Lizard and Steam Input)."""
        if len(value) > 0:
            mode = value[0]
            if len(value) >= 2 and value[0] == 0x85:
                mode = value[1]
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
        """Parse and respond to SC2 commands written to Feature Report 0x00 or 0x01.
        
        Steam Client communicates with the controller via a command/response protocol:
          1. Host writes a command to FR 0x00 (e.g., GET_ATTRIBUTES = 0x83)
          2. Host reads FR 0x00 to retrieve the response
        
        We intercept these and return synthetic SC2-appropriate responses.
        """
        if len(value) < 2:
            print(f"[DIAG] ⚠️  SC2 command too short: {value.hex()}")
            return

        # Parse command — format is typically: [msg_type, cmd_id, ...]
        # Data from Steam: 01 83 00 00 ... → msg_type=0x01, cmd=0x83
        cmd = value[1] if len(value) > 1 else value[0]
        
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
                # Attribute: ATTRIB_CAPABILITIES (tag=2) = 0
                0x02, 0x00, 0x00, 0x00, 0x00,
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
            # GET_SERIAL / GetStringAttribute (0xAE) — Real device response from InputPlumber.
            # Format: [cmd_echo, length, type, serial_ascii..., padding]
            serial = b'SC2DECK001'
            response = bytearray([
                0xAE,       # header.type = GetStringAttribute
                0x14,       # header.length = 20 (serial data length)
                0x01,       # string type
            ])
            response += serial
            response += bytearray(64 - len(response))  # pad to 64
            print(f"[DIAG] 🎮 → Responding to GET_SERIAL with '{serial.decode()}'")

        elif cmd == self.SC2_CMD_CLEAR_MAPPINGS:
            # CLEAR_MAPPINGS (0x81) — Echo back with proper header
            response = bytearray([
                0x81,       # header.type = ClearDigitalMappings
                0x00,       # header.length = 0
            ])
            response += bytearray(64 - len(response))
            print(f"[DIAG] 🎮 → Acknowledging CLEAR_MAPPINGS")

        elif cmd == self.SC2_CMD_SET_ATTRIBUTES:
            # SET_ATTRIBUTES (0x87) — Write-only command, no GET_REPORT response needed.
            # Just acknowledge the write is sufficient. Do NOT store a pending response.
            print(f"[DIAG] 🎮 → SET_SETTINGS write received (register=0x{value[3]:02x}, value=0x{value[4]:02x}{value[5]:02x})" if len(value) > 5 else f"[DIAG] 🎮 → SET_SETTINGS write received (len={len(value)})")
            return  # Don't store a response — this is write-only

        elif cmd == self.SC2_CMD_SET_MODE:
            # SET_MODE (0x85) — Handle mode switch, echo back with proper header
            self._handle_mode_switch(value)
            response = bytearray([
                0x85,       # header.type = SetDefaultDigitalMappings
                0x00,       # header.length = 0
            ])
            response += bytearray(64 - len(response))
            print(f"[DIAG] 🎮 → Acknowledging SET_MODE")

        else:
            # Unknown command — echo back with proper header format
            response = bytearray([
                cmd,        # header.type = command echo
                0x00,       # header.length = 0
            ])
            response += bytearray(64 - len(response))
            print(f"[DIAG] 🎮 → Unknown SC2 command 0x{cmd:02x}, echoing with zero payload")

        self._pending_fr_response[report_id] = bytes(response)

    def _proxy_feature_read(self, report_id):
        """Proxy a Feature Report read to Neptune hardware (for non-SC2 reports)."""
        self._ensure_neptune_feature_fd()
        if self._neptune_feature_fd:
            import fcntl, array
            length = 65
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

    def _on_cccd_enabled(self, handle):
        """Called when a CCCD is enabled for an input report."""
        # Build a map of known handles for diagnostic output
        handle_names = {}
        if self._report_handle:
            handle_names[self._report_handle] = "Gamepad (0x0012)"
        if self._mouse_report_handle:
            handle_names[self._mouse_report_handle] = "Mouse (0x0019)"
        if self._keyboard_report_handle:
            handle_names[self._keyboard_report_handle] = "Keyboard (0x001d)"
        if self._sc2_report_handle:
            handle_names[self._sc2_report_handle] = f"SC2 Custom (0x{self._sc2_report_handle:04x})"

        name = handle_names.get(handle, f"Unknown (0x{handle:04x})")
        print(f"[DIAG] 📡 CCCD ENABLED: {name}")

        # Print all active subscriptions
        if self.att_server:
            active = sorted(self.att_server._notification_handles)
            names = [handle_names.get(h, f"0x{h:04x}") for h in active]
            print(f"[DIAG] 📡 Active subscriptions: {names}")

        # Auto-switch to gamepad mode when host subscribes to gamepad or SC2 custom CCCDs
        if handle in (self._report_handle, self._sc2_report_handle):
            if not self.steam_input_mode:
                self.steam_input_mode = True
                print(f"[DIAG] ⭐ AUTO MODE SWITCH: Host subscribed to {name} → Steam Input Mode")

    def _on_att_disconnection(self, addr):
        print(f"[+] ATT connection lost from {addr}")
        self._schedule_adv_refresh()

    def _schedule_adv_refresh(self):
        """Re-register advertisement after a disconnect."""
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
            if gamepad_45b and self._sc2_report_handle:
                self.att_server.send_notification(self._sc2_report_handle, gamepad_45b)
        else:
            # Lizard mode: send mouse and keyboard reports when they change
            mouse_4b = report_dict.get('mouse_4b')
            kbd_8b = report_dict.get('kbd_8b')
            if mouse_4b and self._mouse_report_handle:
                self.att_server.send_notification(self._mouse_report_handle, mouse_4b)
            if kbd_8b and self._keyboard_report_handle:
                self.att_server.send_notification(self._keyboard_report_handle, kbd_8b)

    def run(self):
        """Run the main event loop."""
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

    def cleanup(self):
        """Clean up resources."""
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
