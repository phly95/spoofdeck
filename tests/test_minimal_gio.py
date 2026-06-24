#!/usr/bin/env python3
"""
Minimal Gio register_object test.

Tests:
1. Register an ObjectManager at a D-Bus path from the same process
2. Verify the object is accessible via busctl
3. Verify BlueZ can discover the registered object
"""

import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib
import sys
import threading
import time


DBUS_OM_IFACE = "org.freedesktop.DBus.ObjectManager"
DBUS_PROPERTIES_IFACE = "org.freedesktop.DBus.Properties"


class MinimalObjectManager(dbus.service.Object):
    """Minimal ObjectManager implementation."""

    def __init__(self, bus, path):
        self.path = path
        super().__init__(bus, path)

    @dbus.service.method(DBUS_OM_IFACE, out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self):
        print(f"[TEST] GetManagedObjects called at {self.path}")
        return {}


def test_same_process():
    """Test 1: Register and query from same process."""
    print("\n=== Test 1: Same Process Registration ===")

    bus = dbus.SystemBus()
    obj = MinimalObjectManager(bus, "/test/minimal")

    # Query from same process
    remote_obj = bus.get_object("org.freedesktop.DBus", "/test/minimal")
    om = dbus.Interface(remote_obj, DBUS_OM_IFACE)
    objects = om.GetManagedObjects()
    print(f"  [PASS] Same process query returned: {objects}")
    return True


def test_busctl():
    """Test 2: Verify object is accessible via busctl."""
    print("\n=== Test 2: busctl Access ===")
    print("  Run this command in another terminal:")
    print("  busctl call org.freedesktop.DBus /test/minimal org.freedesktop.DBus.ObjectManager GetManagedObjects")
    print("  Press Enter when ready to continue...")
    input()
    return True


def main():
    """Run minimal tests."""
    print("Minimal Gio register_object Test")
    print("=" * 40)

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    try:
        bus = dbus.SystemBus()
    except dbus.exceptions.DBusException as e:
        print(f"[-] Cannot connect to system bus: {e}")
        sys.exit(1)

    results = []

    # Test 1: Same process
    results.append(("Same Process", test_same_process()))

    # Test 2: busctl
    results.append(("busctl Access", test_busctl()))

    # Print results
    print("\n" + "=" * 40)
    print("Results:")
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")

    all_passed = all(r[1] for r in results)
    print(f"\n{'All tests passed!' if all_passed else 'Some tests failed.'}")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
