#!/usr/bin/env python3
"""
BlueZ D-Bus helpers for CJohnson Controller 2026 BLE Spoof.

Provides functions to interact with BlueZ via D-Bus for
adapter configuration, GATT registration, and advertisement management.
"""

import dbus


BLUEZ_SERVICE_NAME = "org.bluez"
GATT_MANAGER_IFACE = "org.bluez.GattManager1"
LE_ADVERTISING_MANAGER_IFACE = "org.bluez.LEAdvertisingManager1"
ADAPTER_IFACE = "org.bluez.Adapter1"
DBUS_PROPERTIES_IFACE = "org.freedesktop.DBus.Properties"


def get_adapter_path(bus, adapter_name="hci0"):
    """Get the D-Bus object path for a Bluetooth adapter."""
    return f"/org/bluez/{adapter_name}"


def get_adapter_properties(bus, adapter_name="hci0"):
    """Get all properties of a Bluetooth adapter."""
    adapter_path = get_adapter_path(bus, adapter_name)
    obj = bus.get_object(BLUEZ_SERVICE_NAME, adapter_path)
    props = dbus.Interface(obj, DBUS_PROPERTIES_IFACE)
    return props.GetAll(ADAPTER_IFACE)


def set_adapter_property(bus, adapter_name, property_name, value):
    """Set a property on a Bluetooth adapter."""
    adapter_path = get_adapter_path(bus, adapter_name)
    obj = bus.get_object(BLUEZ_SERVICE_NAME, adapter_path)
    props = dbus.Interface(obj, DBUS_PROPERTIES_IFACE)
    props.Set(ADAPTER_IFACE, property_name, value)


def is_adapter_powered(bus, adapter_name="hci0"):
    """Check if a Bluetooth adapter is powered on."""
    try:
        props = get_adapter_properties(bus, adapter_name)
        return props.get("Powered", False)
    except dbus.exceptions.DBusException:
        return False


def power_on_adapter(bus, adapter_name="hci0"):
    """Power on a Bluetooth adapter."""
    set_adapter_property(bus, adapter_name, "Powered", True)


def power_off_adapter(bus, adapter_name="hci0"):
    """Power off a Bluetooth adapter."""
    set_adapter_property(bus, adapter_name, "Powered", False)


def set_adapter_name(bus, adapter_name, name):
    """Set the local name of a Bluetooth adapter."""
    set_adapter_property(bus, adapter_name, "Alias", name)


def register_gatt_application(bus, app_path, adapter_name="hci0"):
    """
    Register a GATT application with BlueZ.

    Args:
        bus: D-Bus system bus connection
        app_path: D-Bus object path of the GATT application
        adapter_name: Bluetooth adapter name (default: hci0)

    Returns:
        True if registration was initiated successfully
    """
    adapter_path = get_adapter_path(bus, adapter_name)
    obj = bus.get_object(BLUEZ_SERVICE_NAME, adapter_path)
    gatt_manager = dbus.Interface(obj, GATT_MANAGER_IFACE)
    gatt_manager.RegisterApplication(app_path, {})
    return True


def unregister_gatt_application(bus, app_path, adapter_name="hci0"):
    """
    Unregister a GATT application from BlueZ.

    Args:
        bus: D-Bus system bus connection
        app_path: D-Bus object path of the GATT application
        adapter_name: Bluetooth adapter name (default: hci0)

    Returns:
        True if unregistration was initiated successfully
    """
    adapter_path = get_adapter_path(bus, adapter_name)
    obj = bus.get_object(BLUEZ_SERVICE_NAME, adapter_path)
    gatt_manager = dbus.Interface(obj, GATT_MANAGER_IFACE)
    gatt_manager.UnregisterApplication(app_path)
    return True


def register_advertisement(bus, adv_path, adapter_name="hci0"):
    """
    Register an LE advertisement with BlueZ.

    Args:
        bus: D-Bus system bus connection
        adv_path: D-Bus object path of the advertisement
        adapter_name: Bluetooth adapter name (default: hci0)

    Returns:
        True if registration was initiated successfully
    """
    adapter_path = get_adapter_path(bus, adapter_name)
    obj = bus.get_object(BLUEZ_SERVICE_NAME, adapter_path)
    adv_manager = dbus.Interface(obj, LE_ADVERTISING_MANAGER_IFACE)
    adv_manager.RegisterAdvertisement(adv_path, {})
    return True


def unregister_advertisement(bus, adv_path, adapter_name="hci0"):
    """
    Unregister an LE advertisement from BlueZ.

    Args:
        bus: D-Bus system bus connection
        adv_path: D-Bus object path of the advertisement
        adapter_name: Bluetooth adapter name (default: hci0)

    Returns:
        True if unregistration was initiated successfully
    """
    adapter_path = get_adapter_path(bus, adapter_name)
    obj = bus.get_object(BLUEZ_SERVICE_NAME, adapter_path)
    adv_manager = dbus.Interface(obj, LE_ADVERTISING_MANAGER_IFACE)
    adv_manager.UnregisterAdvertisement(adv_path)
    return True


def get_connected_devices(bus, adapter_name="hci0"):
    """Get list of connected device paths."""
    adapter_path = get_adapter_path(bus, adapter_name)
    obj = bus.get_object(BLUEZ_SERVICE_NAME, adapter_path)
    props = dbus.Interface(obj, DBUS_PROPERTIES_IFACE)
    return props.GetAll(ADAPTER_IFACE).get("Devices", [])


def get_advertising_instances(bus, adapter_name="hci0"):
    """Get the number of active advertising instances."""
    try:
        adapter_path = get_adapter_path(bus, adapter_name)
        obj = bus.get_object(BLUEZ_SERVICE_NAME, adapter_path)
        props = dbus.Interface(obj, DBUS_PROPERTIES_IFACE)
        props_dict = props.GetAll(ADAPTER_IFACE)
        # ActiveInstances is not always available
        return props_dict.get("ActiveInstances", 0)
    except dbus.exceptions.DBusException:
        return 0


def print_adapter_info(bus, adapter_name="hci0"):
    """Print detailed adapter information."""
    try:
        props = get_adapter_properties(bus, adapter_name)
        print(f"=== Adapter: {adapter_name} ===")
        print(f"  Name: {props.get('Alias', 'N/A')}")
        print(f"  Address: {props.get('Address', 'N/A')}")
        print(f"  Address Type: {props.get('AddressType', 'N/A')}")
        print(f"  Powered: {props.get('Powered', False)}")
        print(f"  Discoverable: {props.get('Discoverable', False)}")
        print(f"  Pairable: {props.get('Pairable', False)}")
        print(f"  UUIDs: {list(props.get('UUIDs', []))}")
        print(f"  Modalias: {props.get('Modalias', 'N/A')}")
        print(f"  Supported Settings: {list(props.get('SupportedSettings', []))}")
    except dbus.exceptions.DBusException as e:
        print(f"Error reading adapter {adapter_name}: {e}")
