#!/usr/bin/env python3
"""Debug GATT + Adv registration with verbose logging."""
import dbus
import dbus.mainloop.glib
import dbus.service
import signal
from gi.repository import GLib

dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
bus = dbus.SystemBus()

GATT_CHRC_IFACE = "org.bluez.GattCharacteristic1"
GATT_SVC_IFACE = "org.bluez.GattService1"
DBUS_OM_IFACE = "org.freedesktop.DBus.ObjectManager"
DBUS_PROPS_IFACE = "org.freedesktop.DBus.Properties"
LE_ADV_IFACE = "org.bluez.LEAdvertisement1"
APP_BASE = "/com/steamdeck/sc2test"


class Char(dbus.service.Object):
    def __init__(self, bus, idx, uuid, flags, svc):
        self.path = f"{svc.path}/char{idx:04d}"
        self.uuid = uuid
        self.flags = flags
        self.svc_path = svc.path
        super().__init__(bus, self.path)

    def _get_props(self):
        return {
            "Service": dbus.ObjectPath(self.svc_path, variant_level=1),
            "UUID": dbus.String(self.uuid, variant_level=1),
            "Flags": dbus.Array(self.flags, signature="s", variant_level=1),
        }

    @dbus.service.method(DBUS_PROPS_IFACE, out_signature="v", in_signature="ss")
    def Get(self, interface, prop):
        if interface == GATT_CHRC_IFACE:
            props = self._get_props()
            if prop in props:
                return props[prop]
        raise dbus.exceptions.DBusException("org.freedesktop.DBus.Error.InvalidArgs",
                                             f"No such property")

    @dbus.service.method(DBUS_PROPS_IFACE, out_signature="a{sv}", in_signature="s")
    def GetAll(self, interface):
        if interface == GATT_CHRC_IFACE:
            return self._get_props()
        raise dbus.exceptions.DBusException("org.freedesktop.DBus.Error.InvalidArgs")

    @dbus.service.method(GATT_CHRC_IFACE, out_signature="ay", in_signature="a{sv}")
    def ReadValue(self, options=None):
        return dbus.Array([], signature="y", variant_level=1)

    @dbus.service.method(GATT_CHRC_IFACE, in_signature="aya{sv}")
    def WriteValue(self, value, options=None):
        pass

    @dbus.service.method(GATT_CHRC_IFACE)
    def StartNotify(self): pass
    @dbus.service.method(GATT_CHRC_IFACE)
    def StopNotify(self): pass


class Svc(dbus.service.Object):
    def __init__(self, bus, idx, uuid):
        self.path = f"{APP_BASE}/svc{idx:04d}"
        self.uuid = uuid
        self._chars = []
        super().__init__(bus, self.path)

    def _get_props(self):
        return {
            "UUID": dbus.String(self.uuid, variant_level=1),
            "Primary": dbus.Boolean(True, variant_level=1),
        }

    @dbus.service.method(DBUS_PROPS_IFACE, out_signature="v", in_signature="ss")
    def Get(self, interface, prop):
        if interface == GATT_SVC_IFACE:
            props = self._get_props()
            if prop in props:
                return props[prop]
        raise dbus.exceptions.DBusException("org.freedesktop.DBus.Error.InvalidArgs")

    @dbus.service.method(DBUS_PROPS_IFACE, out_signature="a{sv}", in_signature="s")
    def GetAll(self, interface):
        if interface == GATT_SVC_IFACE:
            return self._get_props()
        raise dbus.exceptions.DBusException("org.freedesktop.DBus.Error.InvalidArgs")


class App(dbus.service.Object):
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
            svc_props["Primary"] = dbus.Boolean(True, variant_level=1)
            svc_ifaces = dbus.Dictionary(signature="sv")
            svc_ifaces[GATT_SVC_IFACE] = svc_props
            result[dbus.ObjectPath(svc.path)] = svc_ifaces

            for ch in svc._chars:
                ch_props = dbus.Dictionary(signature="sv")
                ch_props["Service"] = dbus.ObjectPath(svc.path, variant_level=1)
                ch_props["UUID"] = dbus.String(ch.uuid, variant_level=1)
                ch_props["Flags"] = dbus.Array(ch.flags, signature="s", variant_level=1)
                ch_ifaces = dbus.Dictionary(signature="sv")
                ch_ifaces[GATT_CHRC_IFACE] = ch_props
                result[dbus.ObjectPath(ch.path)] = ch_ifaces

        print(f"GetManagedObjects: {len(result)} objects", flush=True)
        return result


class Adv(dbus.service.Object):
    def __init__(self, bus, path, name, uuids):
        self.path = path
        self._name = name
        self._uuids = uuids
        super().__init__(bus, path)

    def _get_props(self):
        return {
            "Type": dbus.String("peripheral", variant_level=1),
            "ServiceUUIDs": dbus.Array([], signature="s", variant_level=1),
            "LocalName": dbus.String(self._name, variant_level=1),
            "IncludeTxPower": dbus.Boolean(True, variant_level=1),
            "ManufacturerData": dbus.Dictionary({}, signature="qv", variant_level=1),
            "SolicitUUIDs": dbus.Array([], signature="s", variant_level=1),
            "ServiceData": dbus.Dictionary({}, signature="sv", variant_level=1),
        }

    @dbus.service.method(DBUS_PROPS_IFACE, out_signature="v", in_signature="ss")
    def Get(self, interface, prop):
        if interface == LE_ADV_IFACE:
            props = self._get_props()
            if prop in props:
                return props[prop]
        raise dbus.exceptions.DBusException("org.freedesktop.DBus.Error.InvalidArgs")

    @dbus.service.method(DBUS_PROPS_IFACE, out_signature="a{sv}", in_signature="s")
    def GetAll(self, interface):
        if interface == LE_ADV_IFACE:
            return self._get_props()
        raise dbus.exceptions.DBusException("org.freedesktop.DBus.Error.InvalidArgs")

    @dbus.service.method(LE_ADV_IFACE)
    def Release(self):
        print("[*] Adv released", flush=True)


# Build
app = App(bus)
sc2_svc = Svc(bus, 0, "100f6c32-1735-4313-b402-38567131e5f3")
for i, (uuid, flags) in enumerate([
    ("100f6c7a-1735-4313-b402-38567131e5f3", ["notify", "read"]),
    ("100f6c7c-1735-4313-b402-38567131e5f3", ["notify", "read"]),
    ("100f6c34-1735-4313-b402-38567131e5f3", ["read", "write", "write-without-response"]),
]):
    ch = Char(bus, i, uuid, flags, sc2_svc)
    sc2_svc._chars.append(ch)
app.add_service(sc2_svc)

adv = Adv(bus, f"{APP_BASE}/adv0", "SC2",
          ["100f6c32-1735-4313-b402-38567131e5f3"])
print("[+] Created", flush=True)

# Register GATT
bluez_obj = bus.get_object("org.bluez", "/org/bluez/hci0")
gatt_mgr = dbus.Interface(bluez_obj, "org.bluez.GattManager1")
gatt_mgr.RegisterApplication(
    app.path, {},
    reply_handler=lambda: print("[+] GATT REGISTERED", flush=True),
    error_handler=lambda e: print(f"[-] GATT FAIL: {e}", flush=True),
)

# Register Adv
adv_mgr = dbus.Interface(bluez_obj, "org.bluez.LEAdvertisingManager1")
adv_mgr.RegisterAdvertisement(
    adv.path, {},
    reply_handler=lambda: print("[+] ADV REGISTERED", flush=True),
    error_handler=lambda e: print(f"[-] ADV FAIL: {e}", flush=True),
)


def check():
    props = dbus.Interface(bluez_obj, DBUS_PROPS_IFACE)
    p = props.GetAll("org.bluez.LEAdvertisingManager1")
    ai = p.get("ActiveInstances", "N/A")
    print(f"  ActiveInstances={ai}", flush=True)
    if ai and ai != "N/A":
        print(f"  Advertising is {'ACTIVE' if int(ai) > 0 else 'INACTIVE'}", flush=True)
    return True


GLib.timeout_add(2000, check)

loop = GLib.MainLoop()
signal.signal(signal.SIGINT, lambda s, f: loop.quit())
signal.signal(signal.SIGTERM, lambda s, f: loop.quit())
print("[*] Running...", flush=True)
loop.run()
print("[*] Done", flush=True)
