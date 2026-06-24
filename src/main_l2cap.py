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

    def setup(self, local_name="Steam Controller 2026"):
        """Set up GATT database and advertisement."""
        # Build the GATT database (no D-Bus dependency)
        self.gatt_db = build_sc2_database(local_name)
        print(f"[+] GATT database built: {len(self.gatt_db.attributes)} attributes, "
              f"{len(self.gatt_db.services)} services")

        # Find the Report characteristic handle for input notifications
        self._find_report_handle()
        print(f"[+] Report characteristic handle: 0x{self._report_handle:04x}" if self._report_handle
              else "[-] WARNING: Report characteristic not found")

        # Create advertisement object
        adv_path = "/com/steamdeck/sc2/adv0"
        self.adv = LEAdvertisement(
            self.bus, adv_path, local_name,
            service_uuids=["1812"],
            appearance=0x03C4,
        )
        print(f"[+] Advertisement object created at {adv_path}")

        # Create raw ATT server
        self.att_server = AttServer(self.gatt_db, mtu=517)
        self.att_server._on_connection = self._on_att_connection
        self.att_server._on_disconnection = self._on_att_disconnection

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

    def _on_att_connection(self, addr):
        print(f"[+] ATT connection established from {addr}")

    def _on_att_disconnection(self, addr):
        print(f"[+] ATT connection lost from {addr}")
        # Restart advertising after disconnect
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

    def _on_input_report(self, report_bytes):
        """Called when a new SC2 input report is ready. Send as BLE notification."""
        if self.att_server and self.att_server.connected and self._report_handle:
            notification = bytes([0x01]) + report_bytes
            self.att_server.send_notification(self._report_handle, notification)
        else:
            print(f"[input] Skipped: connected={self.att_server.connected if self.att_server else None} handle={self._report_handle}")

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
        help="Input device path (e.g., /dev/input/event10). Auto-detect if not specified.",
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
