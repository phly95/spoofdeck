#!/usr/bin/env python3
"""
GATT Application for Steam Controller 2026 BLE Spoof.

Uses dbus-python's dbus.service.Object to export GATT services,
characteristics, and descriptors with proper BlueZ interfaces.

Key insight: GetManagedObjects must return dbus.Dictionary with explicit
signatures and variant_level=1 for BlueZ to accept the objects.
"""

import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib


BLUEZ_SERVICE_NAME = "org.bluez"
GATT_MANAGER_IFACE = "org.bluez.GattManager1"
LE_ADVERTISING_MANAGER_IFACE = "org.bluez.LEAdvertisingManager1"
GATT_SERVICE_IFACE = "org.bluez.GattService1"
GATT_CHARACTERISTIC_IFACE = "org.bluez.GattCharacteristic1"
GATT_DESCRIPTOR_IFACE = "org.bluez.GattDescriptor1"
DBUS_OM_IFACE = "org.freedesktop.DBus.ObjectManager"
DBUS_PROPERTIES_IFACE = "org.freedesktop.DBus.Properties"

HOGP_SERVICE_UUID = "00001812-0000-1000-8000-00805f9b34fb"
HID_INFORMATION_UUID = "00002a4c-0000-1000-8000-00805f9b34fb"
REPORT_MAP_UUID = "00002a4b-0000-1000-8000-00805f9b34fb"
HID_CONTROL_POINT_UUID = "00002a4c-0000-1000-8000-00805f9b34fb"
REPORT_UUID = "00002a4d-0000-1000-8000-00805f9b34fb"
REPORT_REFERENCE_UUID = "00002908-0000-1000-8000-00805f9b34fb"

SC2_HID_SERVICE_UUID = "100f6c32-1735-4313-b402-38567131e5f3"
SC2_INPUT_CH1_UUID = "100f6c7a-1735-4313-b402-38567131e5f3"
SC2_INPUT_CH2_UUID = "100f6c7c-1735-4313-b402-38567131e5f3"
SC2_REPORT_CH_UUID = "100f6c34-1735-4313-b402-38567131e5f3"

BATTERY_SERVICE_UUID = "0000180f-0000-1000-8000-00805f9b34fb"
BATTERY_LEVEL_UUID = "00002a19-0000-1000-8000-00805f9b34fb"

DEVICE_INFO_SERVICE_UUID = "0000180a-0000-1000-8000-00805f9b34fb"
DEVICE_INFO_PNP_ID_UUID = "00002a50-0000-1000-8000-00805f9b34fb"
DEVICE_INFO_MANUFACTURER_UUID = "00002a29-0000-1000-8000-00805f9b34fb"
DEVICE_INFO_MODEL_UUID = "00002a24-0000-1000-8000-00805f9b34fb"
DEVICE_INFO_SERIAL_UUID = "00002a25-0000-1000-8000-00805f9b34fb"
DEVICE_INFO_FW_REV_UUID = "00002a26-0000-1000-8000-00805f9b34fb"
DEVICE_INFO_HW_REV_UUID = "00002a27-0000-1000-8000-00805f9b34fb"

VALVE_SERVICE_UUID = "0000fe95-0000-1000-8000-00805f9b34fb"
VALVE_DATA_CH_UUID = "00001524-0000-1000-8000-00805f9b34fb"

SC2_BLE_PID = 0x1303
SC2_USB_PID = 0x1302
SC2_PUCK_PID = 0x1304
VALVE_VID = 0x28DE

APP_BASE_PATH = "/com/steamdeck/sc2"


class GattCharacteristic(dbus.service.Object):
    """GATT Characteristic with proper BlueZ interface export."""

    def __init__(self, bus, index, uuid, flags, service):
        self.path = f"{service.path}/char{index:04d}"
        self.uuid = uuid
        self.flags = flags
        self.service = service
        self.value = []
        self.notifying = False
        self._descriptors = []
        super().__init__(bus, self.path)

    def _get_props(self):
        return {
            "Service": dbus.ObjectPath(self.service.path, variant_level=1),
            "UUID": dbus.String(self.uuid, variant_level=1),
            "Flags": dbus.Array(self.flags, signature="s", variant_level=1),
            "Value": dbus.Array(self.value, signature="y", variant_level=1),
        }

    @dbus.service.method(DBUS_PROPERTIES_IFACE, out_signature="v", in_signature="ss")
    def Get(self, interface, prop):
        if interface != GATT_CHARACTERISTIC_IFACE:
            raise dbus.exceptions.DBusException(
                "org.freedesktop.DBus.Error.InvalidArgs",
                f"No such interface: {interface}",
            )
        props = self._get_props()
        if prop in props:
            return props[prop]
        raise dbus.exceptions.DBusException(
            "org.freedesktop.DBus.Error.InvalidArgs",
            f"No such property: {prop}",
        )

    @dbus.service.method(DBUS_PROPERTIES_IFACE, out_signature="a{sv}", in_signature="s")
    def GetAll(self, interface):
        if interface != GATT_CHARACTERISTIC_IFACE:
            raise dbus.exceptions.DBusException(
                "org.freedesktop.DBus.Error.InvalidArgs",
                f"No such interface: {interface}",
            )
        return self._get_props()

    @dbus.service.method(GATT_CHARACTERISTIC_IFACE, out_signature="ay", in_signature="a{sv}")
    def ReadValue(self, options=None):
        return dbus.Array(self.value, signature="y", variant_level=1)

    @dbus.service.method(GATT_CHARACTERISTIC_IFACE, in_signature="aya{sv}")
    def WriteValue(self, value, options=None):
        self.value = list(value)

    @dbus.service.method(GATT_CHARACTERISTIC_IFACE)
    def StartNotify(self):
        self.notifying = True

    @dbus.service.method(GATT_CHARACTERISTIC_IFACE)
    def StopNotify(self):
        self.notifying = False

    @dbus.service.signal(DBUS_PROPERTIES_IFACE, signature="sa{sv}as")
    def PropertiesChanged(self, interface, changed, invalidated):
        pass

    def update_value(self, value):
        self.value = list(value)
        if self.notifying:
            self.PropertiesChanged(
                GATT_CHARACTERISTIC_IFACE,
                {"Value": dbus.Array(self.value, variant_level=2)},
                [],
            )

    def add_descriptor(self, descriptor):
        self._descriptors.append(descriptor)

    def get_descriptors(self):
        return self._descriptors


class GattDescriptor(dbus.service.Object):
    """GATT Descriptor with proper BlueZ interface export."""

    def __init__(self, bus, index, uuid, flags, characteristic):
        self.path = f"{characteristic.path}/desc{index:04d}"
        self.uuid = uuid
        self.flags = flags
        self.characteristic = characteristic
        self.value = []
        super().__init__(bus, self.path)

    def _get_props(self):
        return {
            "Characteristic": dbus.ObjectPath(self.characteristic.path, variant_level=1),
            "UUID": dbus.String(self.uuid, variant_level=1),
            "Flags": dbus.Array(self.flags, signature="s", variant_level=1),
            "Value": dbus.Array(self.value, signature="y", variant_level=1),
        }

    @dbus.service.method(DBUS_PROPERTIES_IFACE, out_signature="v", in_signature="ss")
    def Get(self, interface, prop):
        if interface != GATT_DESCRIPTOR_IFACE:
            raise dbus.exceptions.DBusException(
                "org.freedesktop.DBus.Error.InvalidArgs",
                f"No such interface: {interface}",
            )
        props = self._get_props()
        if prop in props:
            return props[prop]
        raise dbus.exceptions.DBusException(
            "org.freedesktop.DBus.Error.InvalidArgs",
            f"No such property: {prop}",
        )

    @dbus.service.method(DBUS_PROPERTIES_IFACE, out_signature="a{sv}", in_signature="s")
    def GetAll(self, interface):
        if interface != GATT_DESCRIPTOR_IFACE:
            raise dbus.exceptions.DBusException(
                "org.freedesktop.DBus.Error.InvalidArgs",
                f"No such interface: {interface}",
            )
        return self._get_props()

    @dbus.service.method(GATT_DESCRIPTOR_IFACE, out_signature="ay", in_signature="a{sv}")
    def ReadValue(self, options=None):
        return dbus.Array(self.value, signature="y", variant_level=1)

    @dbus.service.method(GATT_DESCRIPTOR_IFACE, in_signature="aya{sv}")
    def WriteValue(self, value, options=None):
        self.value = list(value)


class GattService(dbus.service.Object):
    """GATT Service with proper BlueZ interface export."""

    def __init__(self, bus, index, uuid, primary=True):
        self.path = f"{APP_BASE_PATH}/service{index:04d}"
        self.uuid = uuid
        self.primary = primary
        self._characteristics = []
        super().__init__(bus, self.path)

    def _get_props(self):
        return {
            "UUID": dbus.String(self.uuid, variant_level=1),
            "Primary": dbus.Boolean(self.primary, variant_level=1),
        }

    @dbus.service.method(DBUS_PROPERTIES_IFACE, out_signature="v", in_signature="ss")
    def Get(self, interface, prop):
        if interface != GATT_SERVICE_IFACE:
            raise dbus.exceptions.DBusException(
                "org.freedesktop.DBus.Error.InvalidArgs",
                f"No such interface: {interface}",
            )
        props = self._get_props()
        if prop in props:
            return props[prop]
        raise dbus.exceptions.DBusException(
            "org.freedesktop.DBus.Error.InvalidArgs",
            f"No such property: {prop}",
        )

    @dbus.service.method(DBUS_PROPERTIES_IFACE, out_signature="a{sv}", in_signature="s")
    def GetAll(self, interface):
        if interface != GATT_SERVICE_IFACE:
            raise dbus.exceptions.DBusException(
                "org.freedesktop.DBus.Error.InvalidArgs",
                f"No such interface: {interface}",
            )
        return self._get_props()

    def add_characteristic(self, characteristic):
        self._characteristics.append(characteristic)

    def get_characteristics(self):
        return self._characteristics


class GattApplication(dbus.service.Object):
    """GATT Application — returns all objects via GetManagedObjects."""

    def __init__(self, bus):
        self.path = APP_BASE_PATH
        self._services = []
        super().__init__(bus, self.path)

    def add_service(self, service):
        self._services.append(service)

    @dbus.service.method(DBUS_OM_IFACE, out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self):
        result = dbus.Dictionary(signature="oa{sa{sv}}")

        for service in self._services:
            svc_props = dbus.Dictionary(signature="sv")
            svc_props["UUID"] = dbus.String(service.uuid, variant_level=1)
            svc_props["Primary"] = dbus.Boolean(service.primary, variant_level=1)

            svc_ifaces = dbus.Dictionary(signature="sv")
            svc_ifaces[GATT_SERVICE_IFACE] = svc_props

            result[dbus.ObjectPath(service.path)] = svc_ifaces

            for char in service.get_characteristics():
                ch_props = dbus.Dictionary(signature="sv")
                ch_props["Service"] = dbus.ObjectPath(service.path, variant_level=1)
                ch_props["UUID"] = dbus.String(char.uuid, variant_level=1)
                ch_props["Flags"] = dbus.Array(char.flags, signature="s", variant_level=1)
                ch_props["Value"] = dbus.Array(char.value, signature="y", variant_level=1)

                ch_ifaces = dbus.Dictionary(signature="sv")
                ch_ifaces[GATT_CHARACTERISTIC_IFACE] = ch_props

                result[dbus.ObjectPath(char.path)] = ch_ifaces

                for desc in char.get_descriptors():
                    desc_props = dbus.Dictionary(signature="sv")
                    desc_props["Characteristic"] = dbus.ObjectPath(char.path, variant_level=1)
                    desc_props["UUID"] = dbus.String(desc.uuid, variant_level=1)
                    desc_props["Flags"] = dbus.Array(desc.flags, signature="s", variant_level=1)
                    desc_props["Value"] = dbus.Array(desc.value, signature="y", variant_level=1)

                    desc_ifaces = dbus.Dictionary(signature="sv")
                    desc_ifaces[GATT_DESCRIPTOR_IFACE] = desc_props

                    result[dbus.ObjectPath(desc.path)] = desc_ifaces

        return result


# Minimal gamepad HID Report Descriptor (Report ID 1):
#   16 buttons (2 bytes) + 4 axes X/Y/Rx/Ry (8 bytes) + 2 triggers Z/Rz (2 bytes) = 12 bytes
HID_REPORT_DESCRIPTOR = bytes([
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
    0xC0,              # End Collection
])


def build_sc2_gatt_application(bus):
    """Build the complete SC2 GATT application with all services."""
    app = GattApplication(bus)

    # --- Standard HOGP HID Service (0x1812) ---
    hogp_service = GattService(bus, 0, HOGP_SERVICE_UUID, primary=True)

    hid_info = GattCharacteristic(
        bus, 0, HID_INFORMATION_UUID, ["read"], hogp_service,
    )
    # HID Information: bcdHID=1.11, bCountryCode=0, Flags=0x02 (normally connectable)
    hid_info.update_value([0x11, 0x01, 0x00, 0x02])

    report_map = GattCharacteristic(
        bus, 1, REPORT_MAP_UUID, ["read"], hogp_service,
    )
    report_map.update_value(list(HID_REPORT_DESCRIPTOR))

    hid_control = GattCharacteristic(
        bus, 2, HID_CONTROL_POINT_UUID, ["write-without-response"], hogp_service,
    )

    report_in = GattCharacteristic(
        bus, 3, REPORT_UUID, ["read", "notify"], hogp_service,
    )
    report_in.update_value([0] * 13)

    report_ref_in = GattDescriptor(
        bus, 0, REPORT_REFERENCE_UUID, ["read", "write"], report_in,
    )
    report_ref_in.value = [0x01, 0x01]
    report_in.add_descriptor(report_ref_in)

    report_out = GattCharacteristic(
        bus, 4, REPORT_UUID, ["write", "write-without-response", "read", "notify"], hogp_service,
    )
    report_ref_out = GattDescriptor(
        bus, 1, REPORT_REFERENCE_UUID, ["read", "write"], report_out,
    )
    report_ref_out.value = [0x00, 0x02]
    report_out.add_descriptor(report_ref_out)

    hogp_service.add_characteristic(hid_info)
    hogp_service.add_characteristic(report_map)
    hogp_service.add_characteristic(hid_control)
    hogp_service.add_characteristic(report_in)
    hogp_service.add_characteristic(report_out)
    app.add_service(hogp_service)

    # --- SC2 HID Service (custom Valve UUID) ---
    hid_service = GattService(bus, 1, SC2_HID_SERVICE_UUID, primary=True)

    input_ch1 = GattCharacteristic(
        bus, 0, SC2_INPUT_CH1_UUID,
        ["notify", "read"],
        hid_service,
    )
    input_ch2 = GattCharacteristic(
        bus, 1, SC2_INPUT_CH2_UUID,
        ["notify", "read"],
        hid_service,
    )
    report_ch = GattCharacteristic(
        bus, 2, SC2_REPORT_CH_UUID,
        ["read", "write", "write-without-response"],
        hid_service,
    )

    hid_service.add_characteristic(input_ch1)
    hid_service.add_characteristic(input_ch2)
    hid_service.add_characteristic(report_ch)
    app.add_service(hid_service)

    # --- Battery Service ---
    battery_service = GattService(bus, 2, BATTERY_SERVICE_UUID, primary=True)
    battery_level = GattCharacteristic(
        bus, 0, BATTERY_LEVEL_UUID,
        ["read", "notify"],
        battery_service,
    )
    battery_level.update_value([100])
    battery_service.add_characteristic(battery_level)
    app.add_service(battery_service)

    # --- Device Information Service ---
    devinfo_service = GattService(bus, 3, DEVICE_INFO_SERVICE_UUID, primary=True)

    pnp_id = GattCharacteristic(bus, 0, DEVICE_INFO_PNP_ID_UUID, ["read"], devinfo_service)
    pnp_id.update_value([0x01, 0xDE, 0x28, 0x03, 0x03, 0x13, 0x00, 0x01])

    manufacturer = GattCharacteristic(bus, 1, DEVICE_INFO_MANUFACTURER_UUID, ["read"], devinfo_service)
    manufacturer.update_value(list(b"Valve Software"))

    model = GattCharacteristic(bus, 2, DEVICE_INFO_MODEL_UUID, ["read"], devinfo_service)
    model.update_value(list(b"Steam Controller 2026"))

    serial = GattCharacteristic(bus, 3, DEVICE_INFO_SERIAL_UUID, ["read"], devinfo_service)
    serial.update_value(list(b"123456789ABCDEF"))

    fw_rev = GattCharacteristic(bus, 4, DEVICE_INFO_FW_REV_UUID, ["read"], devinfo_service)
    fw_rev.update_value(list(b"1.0.0"))

    hw_rev = GattCharacteristic(bus, 5, DEVICE_INFO_HW_REV_UUID, ["read"], devinfo_service)
    hw_rev.update_value(list(b"1.0.0"))

    devinfo_service.add_characteristic(pnp_id)
    devinfo_service.add_characteristic(manufacturer)
    devinfo_service.add_characteristic(model)
    devinfo_service.add_characteristic(serial)
    devinfo_service.add_characteristic(fw_rev)
    devinfo_service.add_characteristic(hw_rev)
    app.add_service(devinfo_service)

    # --- Valve Custom Service ---
    valve_service = GattService(bus, 4, VALVE_SERVICE_UUID, primary=False)
    valve_data = GattCharacteristic(
        bus, 0, VALVE_DATA_CH_UUID,
        ["read", "write", "write-without-response", "notify"],
        valve_service,
    )
    valve_service.add_characteristic(valve_data)
    app.add_service(valve_service)

    return app
