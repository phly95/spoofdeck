#!/usr/bin/env python3
"""
Full GATT registration test with advertisement.

Registers a complete GATT application + LE advertisement with BlueZ,
verifies registration, then runs until killed.
"""

import dbus
import dbus.mainloop.glib
import dbus.service
import sys
import time
from gi.repository import GLib


BLUEZ_SERVICE_NAME = "org.bluez"
GATT_MANAGER_IFACE = "org.bluez.GattManager1"
LE_ADV_MGR_IFACE = "org.bluez.LEAdvertisingManager1"
GATT_SERVICE_IFACE = "org.bluez.GattService1"
GATT_CHARACTERISTIC_IFACE = "org.bluez.GattCharacteristic1"
DBUS_OM_IFACE = "org.freedesktop.DBus.ObjectManager"
DBUS_PROPERTIES_IFACE = "org.freedesktop.DBus.Properties"
LE_ADV_IFACE = "org.bluez.LEAdvertisement1"

TEST_SVC_UUID = "100f6c32-1735-4313-b402-38567131e5f3"
TEST_CHAR_UUID = "100f6c7a-1735-4313-b402-38567131e5f3"
TEST_CHAR2_UUID = "100f6c7c-1735-4313-b402-38567131e5f3"
TEST_REPORT_UUID = "100f6c34-1735-4313-b402-38567131e5f3"
BATT_SVC_UUID = "0000180f-0000-1000-8000-00805f9b34fb"
BATT_LVL_UUID = "00002a19-0000-1000-8000-00805f9b34fb"
DEVINFO_SVC_UUID = "0000180a-0000-1000-8000-00805f9b34fb"
PNP_ID_UUID = "00002a50-0000-1000-8000-00805f9b34fb"
MFR_UUID = "00002a29-0000-1000-8000-00805f9b34fb"
MODEL_UUID = "00002a24-0000-1000-8000-00805f9b34fb"
SERIAL_UUID = "00002a25-0000-1000-8000-00805f9b34fb"
FW_UUID = "00002a26-0000-1000-8000-00805f9b34fb"
HW_UUID = "00002a27-0000-1000-8000-00805f9b34fb"

APP_BASE = "/com/steamdeck/sc2test"


class TestChar(dbus.service.Object):
    def __init__(self, bus, index, uuid, flags, svc):
        self.path = f"{svc.path}/char{index:04d}"
        self.uuid = uuid
        self.flags = flags
        self.svc_path = svc.path
        self.value = []
        super().__init__(bus, self.path)

    @dbus.service.method(DBUS_PROPERTIES_IFACE, out_signature="a{sv}", in_signature="s")
    def GetAll(self, interface):
        if interface != GATT_CHARACTERISTIC_IFACE:
            raise dbus.exceptions.DBusException("org.freedesktop.DBus.Error.InvalidArgs",
                                                 f"No such interface: {interface}")
        return {
            "Service": dbus.ObjectPath(self.svc_path, variant_level=1),
            "UUID": dbus.String(self.uuid, variant_level=1),
            "Flags": dbus.Array(self.flags, signature="s", variant_level=1),
            "Value": dbus.Array(self.value, signature="y", variant_level=1),
        }

    @dbus.service.method(GATT_CHARACTERISTIC_IFACE, out_signature="ay", in_signature="a{sv}")
    def ReadValue(self, options=None):
        return dbus.Array(self.value, signature="y", variant_level=1)

    @dbus.service.method(GATT_CHARACTERISTIC_IFACE, in_signature="aya{sv}")
    def WriteValue(self, value, options=None):
        self.value = list(value)

    @dbus.service.method(GATT_CHARACTERISTIC_IFACE)
    def StartNotify(self):
        pass

    @dbus.service.method(GATT_CHARACTERISTIC_IFACE)
    def StopNotify(self):
        pass


class TestSvc(dbus.service.Object):
    def __init__(self, bus, index, uuid, primary=True):
        self.path = f"{APP_BASE}/service{index:04d}"
        self.uuid = uuid
        self.primary = primary
        self._chars = []
        super().__init__(bus, self.path)

    @dbus.service.method(DBUS_PROPERTIES_IFACE, out_signature="a{sv}", in_signature="s")
    def GetAll(self, interface):
        if interface != GATT_SERVICE_IFACE:
            raise dbus.exceptions.DBusException("org.freedesktop.DBus.Error.InvalidArgs",
                                                 f"No such interface: {interface}")
        return {
            "UUID": dbus.String(self.uuid, variant_level=1),
            "Primary": dbus.Boolean(self.primary, variant_level=1),
        }


class TestApp(dbus.service.Object):
    def __init__(self, bus):
        self.path = APP_BASE
        self._svcs = []
        super().__init__(bus, self.path)

    def add_service(self, svc):
        self._svcs.append(svc)

    @dbus.service.method(DBUS_OM_IFACE, out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self):
        result = dbus.Dictionary(signature="oa{sa{sv}}")
        for svc in self._svcs:
            svc_props = dbus.Dictionary(signature="sv")
            svc_props["UUID"] = dbus.String(svc.uuid, variant_level=1)
            svc_props["Primary"] = dbus.Boolean(svc.primary, variant_level=1)
            svc_ifaces = dbus.Dictionary(signature="sv")
            svc_ifaces[GATT_SERVICE_IFACE] = svc_props
            result[dbus.ObjectPath(svc.path)] = svc_ifaces

            for ch in svc._chars:
                ch_props = dbus.Dictionary(signature="sv")
                ch_props["Service"] = dbus.ObjectPath(svc.path, variant_level=1)
                ch_props["UUID"] = dbus.String(ch.uuid, variant_level=1)
                ch_props["Flags"] = dbus.Array(ch.flags, signature="s", variant_level=1)
                ch_props["Value"] = dbus.Array(ch.value, signature="y", variant_level=1)
                ch_ifaces = dbus.Dictionary(signature="sv")
                ch_ifaces[GATT_CHARACTERISTIC_IFACE] = ch_props
                result[dbus.ObjectPath(ch.path)] = ch_ifaces

        print(f"  GetManagedObjects: {len(result)} objects", flush=True)
        return result


class TestAdvertisement(dbus.service.Object):
    def __init__(self, bus, path, local_name, service_uuids):
        self.path = path
        self.local_name = local_name
        self.service_uuids = service_uuids
        super().__init__(bus, path)

    @dbus.service.method(DBUS_PROPERTIES_IFACE, out_signature="a{sv}", in_signature="s")
    def GetAll(self, interface):
        if interface != LE_ADV_IFACE:
            raise dbus.exceptions.DBusException("org.freedesktop.DBus.Error.InvalidArgs",
                                                 f"No such interface: {interface}")
        return {
            "Type": dbus.String("peripheral", variant_level=1),
            "ServiceUUIDs": dbus.Array(self.service_uuids, signature="s", variant_level=1),
            "LocalName": dbus.String(self.local_name, variant_level=1),
            "IncludeTxPower": dbus.Boolean(True, variant_level=1),
            "ManufacturerData": dbus.Dictionary({}, signature="qv", variant_level=1),
            "SolicitUUIDs": dbus.Array([], signature="s", variant_level=1),
            "ServiceData": dbus.Dictionary({}, signature="sv", variant_level=1),
        }

    @dbus.service.method(LE_ADV_IFACE)
    def Release(self):
        print("[*] Advertisement released", flush=True)


def main():
    print("Full GATT + Advertisement Test")
    print("=" * 40)

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    try:
        bus = dbus.SystemBus()
    except dbus.exceptions.DBusException as e:
        print(f"[-] Cannot connect to system bus: {e}")
        sys.exit(1)

    # Build GATT app
    app = TestApp(bus)

    # SC2 HID service
    sc2_svc = TestSvc(bus, 0, TEST_SVC_UUID, primary=True)
    for i, uuid in enumerate([TEST_CHAR_UUID, TEST_CHAR2_UUID, TEST_REPORT_UUID]):
        flags = ["notify", "read"] if i < 2 else ["read", "write", "write-without-response"]
        ch = TestChar(bus, i, uuid, flags, sc2_svc)
        sc2_svc._chars.append(ch)
    app.add_service(sc2_svc)

    # Battery service
    batt_svc = TestSvc(bus, 1, BATT_SVC_UUID, primary=True)
    batt_ch = TestChar(bus, 0, BATT_LVL_UUID, ["read", "notify"], batt_svc)
    batt_ch.value = [100]
    batt_svc._chars.append(batt_ch)
    app.add_service(batt_svc)

    # Device info service
    di_svc = TestSvc(bus, 2, DEVINFO_SVC_UUID, primary=True)
    pnp = TestChar(bus, 0, PNP_ID_UUID, ["read"], di_svc)
    pnp.value = [0x01, 0xDE, 0x28, 0x03, 0x03, 0x13, 0x00, 0x01]
    mfr = TestChar(bus, 1, MFR_UUID, ["read"], di_svc)
    mfr.value = list(b"Valve Software")
    mdl = TestChar(bus, 2, MODEL_UUID, ["read"], di_svc)
    mdl.value = list(b"Steam Controller 2026")
    ser = TestChar(bus, 3, SERIAL_UUID, ["read"], di_svc)
    ser.value = list(b"123456789ABCDEF")
    fw = TestChar(bus, 4, FW_UUID, ["read"], di_svc)
    fw.value = list(b"1.0.0")
    hw = TestChar(bus, 5, HW_UUID, ["read"], di_svc)
    hw.value = list(b"1.0.0")
    for c in [pnp, mfr, mdl, ser, fw, hw]:
        di_svc._chars.append(c)
    app.add_service(di_svc)

    # Valve custom service
    valve_svc = TestSvc(bus, 3, "0000fe95-0000-1000-8000-00805f9b34fb", primary=False)
    valve_ch = TestChar(bus, 0, "00001524-0000-1000-8000-00805f9b34fb",
                        ["read", "write", "write-without-response", "notify"], valve_svc)
    valve_svc._chars.append(valve_ch)
    app.add_service(valve_svc)

    print("[+] GATT application created with 4 services")

    # Create advertisement
    adv = TestAdvertisement(
        bus,
        f"{APP_BASE}/advertisement0",
        "Steam Controller 2026",
        [TEST_SVC_UUID],
    )
    print("[+] Advertisement created")

    # Register GATT application
    try:
        bluez_obj = bus.get_object(BLUEZ_SERVICE_NAME, "/org/bluez/hci0")
        gatt_mgr = dbus.Interface(bluez_obj, GATT_MANAGER_IFACE)
    except dbus.exceptions.DBusException as e:
        print(f"[-] Cannot access BlueZ GattManager1: {e}")
        sys.exit(1)

    gatt_mgr.RegisterApplication(
        app.path, {},
        reply_handler=lambda: print("[+] GATT application registered successfully", flush=True),
        error_handler=lambda e: print(f"[-] GATT registration FAILED: {e}", flush=True),
    )

    # Register advertisement
    try:
        adv_mgr = dbus.Interface(bluez_obj, LE_ADV_MGR_IFACE)
        adv_mgr.RegisterAdvertisement(
            adv.path, {},
            reply_handler=lambda: print("[+] Advertisement registered successfully", flush=True),
            error_handler=lambda e: print(f"[-] Advertisement registration FAILED: {e}", flush=True),
        )
    except dbus.exceptions.DBusException as e:
        print(f"[-] Cannot register advertisement: {e}")

    # Check ActiveInstances after a short delay
    def check_instances():
        try:
            props = dbus.Interface(bluez_obj, DBUS_PROPERTIES_IFACE)
            adapter_props = props.GetAll("org.bluez.Adapter1")
            active = adapter_props.get("ActiveInstances", "N/A")
            print(f"  ActiveInstances: {active}", flush=True)
        except Exception as e:
            print(f"  Could not read ActiveInstances: {e}", flush=True)
        return False

    GLib.timeout_add(2000, check_instances)

    # Run main loop
    print("[*] Running... (Ctrl+C to stop)")
    loop = GLib.MainLoop()

    def signal_handler(sig, frame):
        print("\n[*] Shutting down...")
        loop.quit()

    import signal
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    loop.run()
    print("[*] Done")


if __name__ == "__main__":
    main()
