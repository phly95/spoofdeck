#!/usr/bin/env python3
"""
dbus-python export test.

Demonstrates BusName ownership denial without the D-Bus policy file.
This test will fail with AccessDenied if the policy file is not installed.
"""

import dbus
import dbus.service
import dbus.mainloop.glib
import sys


class TestObject(dbus.service.Object):
    """Simple test object."""

    def __init__(self, bus, path):
        self.path = path
        super().__init__(bus, path)

    @dbus.service.method("org.test.Test", out_signature="s")
    def Hello(self):
        return "Hello from Steam Deck SC2 Spoof!"


def main():
    print("dbus-python BusName Ownership Test")
    print("=" * 40)

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    try:
        bus = dbus.SystemBus()
    except dbus.exceptions.DBusException as e:
        print(f"[-] Cannot connect to system bus: {e}")
        sys.exit(1)

    # Test 1: Try to own a bus name without policy
    print("\n=== Test 1: BusName Ownership (No Policy) ===")
    print("  Attempting to own 'com.steamdeck.hogp'...")
    print("  This will FAIL if D-Bus policy is not installed.\n")

    try:
        bus_name = dbus.service.BusName("com.steamdeck.hogp", bus)
        print("  [PASS] BusName ownership granted")
        print("  This means the D-Bus policy file IS installed.")

        # If we got here, try to export an object
        obj = TestObject(bus, "/com/steamdeck/hogp/test")
        print("  [PASS] Object exported successfully")

        # Try to query the object
        remote_obj = bus.get_object("com.steamdeck.hogp", "/com/steamdeck/hogp/test")
        iface = dbus.Interface(remote_obj, "org.test.Test")
        result = iface.Hello()
        print(f"  [PASS] Object query returned: {result}")

    except dbus.exceptions.DBusException as e:
        print(f"  [FAIL] BusName ownership denied: {e}")
        print("\n  This is expected if the D-Bus policy file is not installed.")
        print("  Install the policy file at:")
        print("  /etc/dbus-1/system.d/com.steamdeck.hogp.conf")
        print("\n  Then restart D-Bus:")
        print("  sudo systemctl restart dbus")

    # Test 2: Try to register with BlueZ
    print("\n=== Test 2: BlueZ GATT Registration ===")
    print("  Attempting to register GATT application...")
    print("  This requires the D-Bus policy file.\n")

    BLUEZ_SERVICE_NAME = "org.bluez"
    GATT_MANAGER_IFACE = "org.bluez.GattManager1"

    try:
        bluez_obj = bus.get_object(BLUEZ_SERVICE_NAME, "/org/bluez/hci0")
        gatt_manager = dbus.Interface(bluez_obj, GATT_MANAGER_IFACE)

        # Create a minimal GATT application
        app = TestObject(bus, "/test/gatt/app")

        def on_register_complete():
            print("  [PASS] GATT application registered with BlueZ")

        def on_register_error(error):
            print(f"  [FAIL] GATT registration failed: {error}")

        gatt_manager.RegisterApplication(
            app.path,
            {},
            reply_handler=on_register_complete,
            error_handler=on_register_error,
        )

    except dbus.exceptions.DBusException as e:
        print(f"  [FAIL] Cannot access BlueZ: {e}")

    print("\n" + "=" * 40)
    print("Test complete.")


if __name__ == "__main__":
    main()
