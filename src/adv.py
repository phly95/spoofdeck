#!/usr/bin/env python3
"""
BLE Advertisement for CJohnson Controller 2026 Spoof.

LEAdvertisement1 D-Bus object for BlueZ registration.
Adapter property setup for discoverable advertising fallback.
"""

import dbus
import dbus.service
import dbus.mainloop.glib


BLUEZ_SERVICE_NAME = "org.bluez"
LE_ADVERTISEMENT_IFACE = "org.bluez.LEAdvertisement1"
ADAPTER_IFACE = "org.bluez.Adapter1"
DBUS_PROPERTIES_IFACE = "org.freedesktop.DBus.Properties"


class LEAdvertisement(dbus.service.Object):
    """LE Advertisement D-Bus object for SC2 BLE Spoof."""

    def __init__(self, bus, path, local_name, service_uuids=None, appearance=0x03C4):
        self.path = path
        self.local_name = local_name
        self.service_uuids = service_uuids or []
        self.appearance = appearance
        self.include_tx_power = True
        self.type = "peripheral"
        self.manufacturer_data = {}
        self.solicit_uuids = []
        self.service_data = {}
        super().__init__(bus, path)

    def _get_props(self):
        return {
            "Type": dbus.String(self.type, variant_level=1),
            "ServiceUUIDs": dbus.Array(self.service_uuids, signature="s", variant_level=1),
            "LocalName": dbus.String(self.local_name, variant_level=1),
            "Appearance": dbus.UInt16(self.appearance, variant_level=1),
            "IncludeTxPower": dbus.Boolean(self.include_tx_power, variant_level=1),
            "ManufacturerData": dbus.Dictionary(self.manufacturer_data, signature="qv", variant_level=1),
            "SolicitUUIDs": dbus.Array(self.solicit_uuids, signature="s", variant_level=1),
            "ServiceData": dbus.Dictionary(self.service_data, signature="sv", variant_level=1),
        }

    @dbus.service.method(DBUS_PROPERTIES_IFACE, out_signature="v", in_signature="ss")
    def Get(self, interface, prop):
        if interface == LE_ADVERTISEMENT_IFACE:
            props = self._get_props()
            if prop in props:
                return props[prop]
        raise dbus.exceptions.DBusException("org.freedesktop.DBus.Error.InvalidArgs")

    @dbus.service.method(DBUS_PROPERTIES_IFACE, out_signature="a{sv}", in_signature="s")
    def GetAll(self, interface):
        if interface == LE_ADVERTISEMENT_IFACE:
            return self._get_props()
        raise dbus.exceptions.DBusException("org.freedesktop.DBus.Error.InvalidArgs")

    @dbus.service.method(LE_ADVERTISEMENT_IFACE)
    def Release(self):
        print("[*] Advertisement released")


def setup_adapter_properties(bus, adapter_name="hci0"):
    """Set adapter Alias, Discoverable, Connectable for legacy advertising."""
    adapter_path = f"/org/bluez/{adapter_name}"
    try:
        obj = bus.get_object(BLUEZ_SERVICE_NAME, adapter_path)
        props = dbus.Interface(obj, DBUS_PROPERTIES_IFACE)

        props.Set(ADAPTER_IFACE, "Alias", dbus.String("CJohnson Controller 2026", variant_level=1))
        props.Set(ADAPTER_IFACE, "Discoverable", dbus.Boolean(True, variant_level=1))
        props.Set(ADAPTER_IFACE, "Connectable", dbus.Boolean(True, variant_level=1))
        print("[+] Adapter configured: Alias, Discoverable, Connectable")

        p = props.GetAll(ADAPTER_IFACE)
        print(f"[+] Address: {p.get('Address')}")
        print(f"[+] ActiveInstances: {p.get('ActiveInstances', 'N/A')}")
    except dbus.exceptions.DBusException as e:
        print(f"[-] Failed to set adapter properties: {e}")
