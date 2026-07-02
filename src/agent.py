#!/usr/bin/env python3
"""
BlueZ Agent1 D-Bus interface for CJohnson Controller 2026 BLE Spoof.

Implements org.bluez.Agent1 on the Deck (peripheral side) so that when the
host PC initiates pairing, BlueZ has an agent that auto-responds to all
pairing prompts (passkey confirmation, authorization, etc.).

This replaces the fragile PTY-based bluetoothctl wrapper (bt_agent_pty.py)
with an in-process agent that is robust and stateless.

Registered with org.bluez.AgentManager1.RegisterAgent(capability) +
RequestDefaultAgent(). Capability "DisplayYesNo" is used so we receive
RequestConfirmation / DisplayPasskey calls and auto-confirm them.

Reference: doc/org.bluez.Agent.rst in BlueZ source tree.
"""

import dbus
import dbus.service


BLUEZ_SERVICE_NAME = "org.bluez"
AGENT_MANAGER_IFACE = "org.bluez.AgentManager1"
AGENT_IFACE = "org.bluez.Agent1"
DBUS_PROPERTIES_IFACE = "org.freedesktop.DBus.Properties"

AGENT_PATH = "/com/steamdeck/sc2/agent"


class Agent(dbus.service.Object):
    """BlueZ Agent1 that auto-confirms all pairing requests."""

    def __init__(self, bus, path=AGENT_PATH, capability="DisplayYesNo"):
        self.path = path
        self.capability = capability
        self._events = []
        super().__init__(bus, path)

    # --- Agent1 methods (all auto-accept) ---

    @dbus.service.method(AGENT_IFACE, in_signature="", out_signature="")
    def Release(self):
        print("[agent] Release")

    @dbus.service.method(AGENT_IFACE, in_signature="o", out_signature="s")
    def RequestPinCode(self, device):
        print(f"[agent] RequestPinCode for {device} -> '000000'")
        return dbus.String("000000")

    @dbus.service.method(AGENT_IFACE, in_signature="os", out_signature="")
    def DisplayPinCode(self, device, pincode):
        print(f"[agent] DisplayPinCode for {device}: {pincode}")

    @dbus.service.method(AGENT_IFACE, in_signature="o", out_signature="u")
    def RequestPasskey(self, device):
        print(f"[agent] RequestPasskey for {device} -> 0")
        return dbus.UInt32(0)

    @dbus.service.method(AGENT_IFACE, in_signature="ouq", out_signature="")
    def DisplayPasskey(self, device, passkey, entered):
        print(f"[agent] DisplayPasskey for {device}: {passkey} (entered {entered})")

    @dbus.service.method(AGENT_IFACE, in_signature="ou", out_signature="")
    def RequestConfirmation(self, device, passkey):
        print(f"[agent] RequestConfirmation for {device} passkey={passkey} -> auto-confirm")
        return

    @dbus.service.method(AGENT_IFACE, in_signature="o", out_signature="")
    def RequestAuthorization(self, device):
        print(f"[agent] RequestAuthorization for {device} -> auto-authorize")
        return

    @dbus.service.method(AGENT_IFACE, in_signature="os", out_signature="")
    def AuthorizeService(self, device, uuid):
        print(f"[agent] AuthorizeService for {device} uuid={uuid} -> authorize")
        return

    @dbus.service.method(AGENT_IFACE, in_signature="", out_signature="")
    def Cancel(self):
        print("[agent] Cancel")


def register_agent(bus, capability="DisplayYesNo"):
    """Create, register, and request-default an Agent1 on the system bus.

    Returns the Agent instance (keep a reference so it stays alive).
    """
    agent = Agent(bus, AGENT_PATH, capability=capability)
    print(f"[+] Agent created at {agent.path} (capability={capability})")

    manager_obj = bus.get_object(BLUEZ_SERVICE_NAME, "/org/bluez")
    manager = dbus.Interface(manager_obj, AGENT_MANAGER_IFACE)

    # RegisterAgent is async-ish but actually a sync call that returns once
    # the agent is registered. Wrap in try/except to surface errors.
    manager.RegisterAgent(agent.path, capability)
    print(f"[+] Agent registered with AgentManager1")

    manager.RequestDefaultAgent(agent.path)
    print(f"[+] Agent requested as default")

    return agent


def unregister_agent(bus, agent):
    """Unregister and release an agent (best-effort)."""
    if agent is None:
        return
    try:
        manager_obj = bus.get_object(BLUEZ_SERVICE_NAME, "/org/bluez")
        manager = dbus.Interface(manager_obj, AGENT_MANAGER_IFACE)
        manager.UnregisterAgent(agent.path)
        print("[+] Agent unregistered")
    except dbus.exceptions.DBusException as e:
        print(f"[-] Agent unregister failed: {e}")