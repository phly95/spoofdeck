#!/usr/bin/env python3
"""
Main entrypoint for Steam Controller 2026 BLE Spoof.

Captures Deck controller inputs and forwards them as SC2-format
BLE GATT notifications to the host PC.

Startup order:
  1. Create D-Bus objects (GATT app, advertisement) — no BlueZ calls
  2. Own bus name
  3. Start GLib main loop
  4. Register GATT app + advertisement via GLib.idle_add()
"""

import argparse
import signal
import sys

import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib

from gatt_app import build_sc2_gatt_application, REPORT_UUID
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
GATT_MANAGER_IFACE = "org.bluez.GattManager1"
LE_ADVERTISING_MANAGER_IFACE = "org.bluez.LEAdvertisingManager1"
ADAPTER_IFACE = "org.bluez.Adapter1"
DBUS_PROPERTIES_IFACE = "org.freedesktop.DBus.Properties"


class HoGPeripheral:
    """
    HID over GATT Peripheral for Steam Controller 2026 BLE Spoof.
    Captures Deck controller inputs and sends them as SC2 BLE reports.
    """

    def __init__(self, bus, adapter_name="hci0"):
        self.bus = bus
        self.adapter_name = adapter_name
        self.adapter_path = get_adapter_path(bus, adapter_name)
        self.app = None
        self.adv = None
        self.agent = None
        self.input_handler = None
        self.mainloop = None
        self._input_ch = None

    def create_objects(self, local_name="Steam Controller 2026"):
        """Create D-Bus objects (no BlueZ calls yet)."""
        self.app = build_sc2_gatt_application(self.bus)
        print(f"[+] GATT application created at {self.app.path}")

        # Find the HOGP input report characteristic (for notifications)
        for svc in self.app._services:
            for ch in svc.get_characteristics():
                if ch.uuid == REPORT_UUID:
                    self._input_ch = ch
                    print(f"[+] HOGP Report characteristic at {ch.path}")
                    break

        # Create advertisement object (not registered yet)
        adv_path = f"{self.app.path}/advertisement0"
        self.adv = LEAdvertisement(
            self.bus, adv_path, local_name,
            service_uuids=["1812"],
            appearance=0x03C4,
        )
        print(f"[+] Advertisement object created at {adv_path}")

    def _register_with_bluez(self):
        """Called via GLib.idle_add() after main loop starts."""
        # Register pairing agent BEFORE adv/gatt so BlueZ has an agent ready
        # for any incoming pairing attempt.
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

        # Register GATT application with BlueZ
        try:
            obj = self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path)
            gatt_manager = dbus.Interface(obj, GATT_MANAGER_IFACE)
            gatt_manager.RegisterApplication(
                self.app.path, {},
                reply_handler=self._on_gatt_registered,
                error_handler=self._on_gatt_error,
            )
            print("[*] RegisterApplication dispatched...")
        except dbus.exceptions.DBusException as e:
            print(f"[-] Failed to register GATT application: {e}")

        # Set adapter properties for discoverable advertising
        setup_adapter_properties(self.bus, self.adapter_name)

        return False  # Remove from idle handler (run once)

    def _on_adv_registered(self):
        print("[+] Advertisement registered successfully")

    def _on_adv_error(self, error):
        print(f"[-] Advertisement registration failed: {error}")

    def _on_gatt_registered(self):
        print("[+] GATT application registered successfully")

    def _on_gatt_error(self, error):
        print(f"[-] GATT registration failed: {error}")

    def start_input_capture(self, device_path=None):
        """Start capturing controller inputs from the Deck."""
        self.input_handler = InputHandler(
            on_report=self._on_input_report,
            device_path=device_path,
        )
        self.input_handler.start()

    def _on_input_report(self, report_bytes):
        """Called when a new SC2 input report is ready."""
        if self._input_ch and self._input_ch.notifying:
            self._input_ch.update_value(list(report_bytes))

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
        if self.agent:
            unregister_agent(self.bus, self.agent)

        if self.input_handler:
            self.input_handler.stop()

        if self.mainloop:
            self.mainloop.quit()

        if self.app:
            try:
                obj = self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path)
                gatt_manager = dbus.Interface(obj, GATT_MANAGER_IFACE)
                gatt_manager.UnregisterApplication(self.app.path)
                print("[+] GATT application unregistered")
            except dbus.exceptions.DBusException:
                pass

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
        description="Steam Controller 2026 BLE Spoof"
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

    # Initialize D-Bus
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

    # Own bus name (required for BlueZ to access our D-Bus objects)
    try:
        bus_name = dbus.service.BusName("com.steamdeck.hogp", bus)
        print("[+] D-Bus bus name com.steamdeck.hogp owned")
    except dbus.exceptions.DBusException as e:
        print(f"[-] Failed to own bus name: {e}")
        sys.exit(1)

    # Create D-Bus objects (no BlueZ calls yet)
    peripheral = HoGPeripheral(bus, args.adapter)
    peripheral.create_objects(args.name)

    # Start input capture
    peripheral.start_input_capture(args.device)

    # Run main loop (registration happens via GLib.idle_add)
    peripheral.run()


if __name__ == "__main__":
    main()
