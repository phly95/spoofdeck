# Known Challenges and Solutions

## 1. D-Bus Policy Restriction (SOLVED)

**Problem**: SteamOS restricts D-Bus object registration to root only. Applications running as the `deck` user cannot register GATT services or advertisements with BlueZ via the system D-Bus.

**Error**:
```
dbus.exceptions.DBusException: org.freedesktop.DBus.Error.AccessDenied:
  Activation of org.bluez declined by apparmor
```

**Solution**: Install a D-Bus policy file at `/etc/dbus-1/system.d/com.steamdeck.hogp.conf` that allows the `deck` user to:
- Own the `com.steamdeck.hogp` bus name
- Send messages to `org.bluez`
- Use all required BlueZ interfaces (GattManager1, LEAdvertisingManager1, GattService1, etc.)

See `dbus-config/com.steamdeck.hogp.conf` for the full policy.

---

## 2. Filesystem Read-Only (SOLVED)

**Problem**: SteamOS root filesystem is btrfs with `steamos-readonly` enabled. Cannot write files to `/etc/dbus-1/system.d/`.

**Error**:
```
btrfs: unable to pin object path /etc/dbus-1/system.d/
```

**Solution**:
```bash
sudo steamos-readonly disable
# Make changes
sudo steamos-readonly enable
```

Note: The filesystem will be remounted read-only after reboot if not explicitly disabled.

---

## 3. sudo Requires TTY (SOLVED)

**Problem**: SSH sessions don't allocate a TTY, so `sudo` prompts fail or don't work correctly.

**Error**:
```
sudo: no tty present and no askpass program specified
```

**Solution**: Use the `-S` flag to read password from stdin:
```bash
echo '<password>' | sudo -S <command>
```

Or create wrapper scripts that pipe the password:
```bash
#!/bin/bash
echo '<password>' | sudo -S "$@"
```

---

## 4. Static BLE Address (SOLVED)

**Problem**: To spoof the SC2, we need a static BLE address. This requires `btmgmt` commands which need root privileges.

**Solution**:
```bash
sudo btmgmt
# In btmgmt shell:
power off
static-addr <DECK_BT_MAC_PUBLIC>
power on
le on
quit
```

**Note**: The address must be set before starting the GATT server. The address is lost on reboot and must be re-set.

---

## 5. Gio.DBusConnection.register_object() Deprecated Warning (SOLVED)

**Problem**: `Gio.DBusConnection.register_object()` returns a deprecation warning:
```
/tmp/gatt_app.py:123: PyGIDeprecationWarning: Gio.DBusConnection.register_object
  is deprecated, use Gio.DBusConnection.register_object_with_closures.
```

**Reality**: The function still works and returns a successful registration ID. The warning is about the API change in GLib 2.84+, not a functional issue. The real blocker was the D-Bus policy, not the registration method.

---

## 6. dbus-python BusName Ownership Denied (SOLVED)

**Problem**: Using `dbus.service.BusName('com.steamdeck.hogp', bus)` raises:
```
dbus.exceptions.DBusException: org.freedesktop.DBus.Error.AccessDenied:
  Connection ":1.42" is not allowed to own the service
  "com.steamdeck.hogp" due to security policies
```

**Solution**: The D-Bus policy file must be installed before running the application. The policy grants the `deck` user permission to own the bus name.

---

## 7. steamdeck-bt-controller-emulator Bug (SOLVED)

**Problem**: The `check_static_address_set()` function in steamdeck-bt-controller-emulator calls `btmgmt` via sudo, which fails when run from a wrapper script.

**Error**:
```
subprocess.CalledProcessError: Command 'sudo btmgmt info' returned non-zero exit status 1
```

**Solution**: Patch the function to always return `True`:
```python
def check_static_address_set():
    return True
```

See `patches/check_static_addr.patch` for the full patch.

---

## 8. BLE Advertising Not Starting (SOLVED)

**Problem**: After registering an advertisement, `ActiveInstances` stays at 0x00 and no advertising occurs.

**Root Cause**: D-Bus policy was not in place. BlueZ silently ignored the registration attempt.

**Solution**: Install the D-Bus policy file and restart the D-Bus service:
```bash
sudo cp com.steamdeck.hogp.conf /etc/dbus-1/system.d/
sudo systemctl restart dbus
```

---

## 9. Original Emulator Uses Wrong D-Bus Registration (IDENTIFIED)

**Problem**: The steamdeck-bt-controller-emulator project only registers the Properties interface on D-Bus objects, not the full GattService1/GattCharacteristic1 interfaces.

**Impact**: BlueZ cannot discover the GATT service because it expects the standard interfaces to be exported.

**Solution**: Our implementation in `src/gatt_app.py` exports all required interfaces:
- `org.bluez.GattService1`
- `org.bluez.GattCharacteristic1`
- `org.bluez.GattDescriptor1`
- `org.freedesktop.DBus.Properties`
- `org.freedesktop.DBus.ObjectManager`

---

## 10. GLib / BlueZ / Python Versions

| Component | Version | Notes |
|-----------|---------|-------|
| GLib | 2.84.3 | Latest on SteamOS |
| BlueZ | 5.86 | Supports peripheral role |
| Python | 3.13 | Current stable |
| dbus-python | Latest | Included with SteamOS |

The versions are recent enough that all required features are available. No version-specific workarounds needed.

---

## 11. Steam Client BT Manager (IDENTIFIED)

**Problem**: The Steam Client's BT manager runs as a stub on Linux. Full HID parsing and Steam Input processing is handled client-side by `steamclient.so`.

**Impact**: The SC2 spoof must provide the exact BLE GATT profile that Steam Client expects, or it will not recognize the device.

**Solution**: Match the SC2 BLE profile exactly:
- Correct service UUID
- Correct characteristic UUIDs
- Correct input report format (0x45)
- Correct mode switching protocol

---

## 12. Custom LEAdvertisement1 Not Visible Over Air (SOLVED)

**Problem**: `LEAdvertisingManager1.RegisterAdvertisement()` succeeds (ActiveInstances=1), but the advertisement is never transmitted as BLE advertising PDUs. Host PC cannot see the device.

**Root Cause**: On BT 5.x adapters, BlueZ sends custom LEAdvertisement1 advertisements via **extended advertising HCI commands** (BLE 5.0+). Hosts with HCI 4.2 or older **cannot receive extended advertising PDUs**. The host sees the adapter's built-in "Discoverable" advertising (which uses legacy BLE) but NOT custom advertisement objects.

**Evidence**:
- Deck (BT 5.3) → ActiveInstances=1 but invisible to host (HCI 4.2)
- When `Discoverable=True`, host sees "SteamDeckHoG" (adapter alias via legacy advertising)
- Custom "SC2" advertisement never appears in host scans
- BlueZ strings confirm: `"kernel supports ext adv commands"`, `"Add Extended Advertisement Parameters"`

**Solution**: Do NOT use custom LEAdvertisement1 objects for advertising. Instead, use BlueZ's built-in discoverable advertising via adapter properties:
```python
props.Set("org.bluez.Adapter1", "Alias", "Steam Controller 2026")
props.Set("org.bluez.Adapter1", "Discoverable", True)
props.Set("org.bluez.Adapter1", "Connectable", True)
```
This uses legacy BLE advertising that all hosts (HCI 4.2+) can see.

---

## 13. GetManagedObjects Variant Level (SOLVED)

**Problem**: BlueZ rejects GATT objects with "No valid service object found" even though GetManagedObjects returns the correct structure.

**Root Cause**: `dbus-python` needs explicit `dbus.Dictionary(signature="sv")` and `variant_level=1` in GetManagedObjects. Plain Python dicts don't marshal correctly for BlueZ's parser.

**Solution**: In GetManagedObjects, construct return values with explicit signatures:
```python
result = dbus.Dictionary(signature="oa{sa{sv}}")
# For each service:
svc_props = dbus.Dictionary(signature="sv")
svc_props["UUID"] = dbus.String(svc.uuid, variant_level=1)
svc_props["Primary"] = dbus.Boolean(svc.primary, variant_level=1)
svc_ifaces = dbus.Dictionary(signature="sv")
svc_ifaces[GATT_SERVICE_IFACE] = svc_props
result[dbus.ObjectPath(svc.path)] = svc_ifaces
```

---

## 14. Properties.Get Missing (SOLVED)

**Problem**: BlueZ's `gatt-database.c:chrc_create()` fails with "Failed to parse characteristic properties" even though GetAll returns correct data.

**Root Cause**: BlueZ's internal GDBus proxy calls `org.freedesktop.DBus.Properties.Get` (singular) to read individual properties, not `GetAll`. Without `Get` implemented, the proxy cache is empty and parsing fails.

**Solution**: Implement both `Get` and `GetAll` on every D-Bus object:
```python
@dbus.service.method(DBUS_PROPERTIES_IFACE, out_signature="v", in_signature="ss")
def Get(self, interface, prop):
    if interface == GATT_CHARACTERISTIC_IFACE:
        props = self._get_props()
        if prop in props:
            return props[prop]
    raise dbus.exceptions.DBusException("org.freedesktop.DBus.Error.InvalidArgs")
```

---

---

## 15. Headless Bluetooth Pairing (SOLVED)

**Problem**: When pairing over SSH headlessly, BlueZ agent prompts for passkey confirmation or authorization, which times out since there is no TTY/interactive session.

**Solution**: A custom PTY-based agent wrapper (`scripts/bt_agent_pty.py`) spawns `bluetoothctl` in a pseudo-terminal (PTY) and intercepts text prompts to automatically reply `yes` to passkey confirmation and service authorization.

---

## 16. Wrong Link Type (-22) (SOLVED)

**Problem**: Dual-mode controllers advertise over both BR/EDR (Classic) and LE. When the host pairs using the public address, it defaults to BR/EDR classic. The host kernel's HOGP driver refuses to connect HID-over-GATT over BR/EDR, resulting in `Bluetooth: Wrong link type (-22)` errors.

**Solution**: Disable classic Bluetooth on the Deck's controller using `btmgmt bredr off`. This forces the Deck to advertise strictly as an LE peripheral, enabling the host to discover and pair with it purely over LE (`C2:12:34:56:78:9A (random)`).

---

## 17. GATT Service Connection Stability (SOLVED)

**Problem**: The host PC successfully pairs and connects over LE, but the connection drops immediately (`Connected: no`), preventing the host from resolving GATT services (`ServicesResolved: no`) and creating the virtual gamepad `/dev/hidraw` node. BlueZ daemon on the Deck logs `Failed to set mode: Invalid Parameters` and `Failed to add advertisement: Rejected (0x0b)`.

**Status**: Under investigation. Possible issues include advertising channel conflicts or GATT database validation failures in the python-dbus implementation.

---

## Summary of Blockers

| # | Blocker | Status |
|---|---------|--------|
| 1 | D-Bus policy | SOLVED |
| 2 | Filesystem read-only | SOLVED |
| 3 | sudo requires TTY | SOLVED |
| 4 | Static BLE address | SOLVED |
| 5 | Gio deprecation warning | SOLVED |
| 6 | BusName ownership | SOLVED |
| 7 | bt-mgmt bug | SOLVED |
| 8 | BLE advertising not starting | SOLVED |
| 9 | Wrong D-Bus registration | SOLVED |
| 10 | Version compatibility | OK |
| 11 | Steam Client expectations | IDENTIFIED |
| 12 | Custom LEAdvertisement1 invisible | SOLVED |
| 13 | GetManagedObjects variant level | SOLVED |
| 14 | Properties.Get missing | SOLVED |
| 15 | Headless pairing prompt | SOLVED |
| 16 | Wrong Link Type (-22) | SOLVED |
| 17 | GATT Connection Drops | SOLVED |
| 18 | Gio.DBusConnection GATT Registration Fails | SOLVED |
| 19 | ControllerMode=le Not Supported | SOLVED |
| 20 | Discoverable Property No Advertising in LE-only | SOLVED |
| 21 | btmgmt Power Cycle Kills hogp | SOLVED |
| 22 | Missing Standard HOGP Service (0x1812) | SOLVED |
| 23 | Properties.Get Missing (in_signature="ss") | SOLVED |
| 24 | Async D-Bus Registration Blocks | SOLVED |
| 25 | Pairing AuthenticationFailed | SOLVED |
| 26 | BlueZ GATT Listener Address Mismatch | SOLVED |
| 27 | Python 3.13 BLE Socket Limitation | SOLVED |
| 28 | GATT Database UUID Comparison Bug | SOLVED |
| 29 | GATT Handle Allocation Bug | SOLVED |
| 30 | MTU Exchange Response Format Bug | SOLVED |
| 31 | Connection Drops After Service Discovery | SOLVED |
| 32 | Host hog-ll Drops Notifications | SOLVED |
| 33 | Connection Drops After Pairing | SOLVED |
| 34 | Physical Deck Input Not Working via evdev | SOLVED |
| 35 | Feature Report ioctl EINVAL on hidraw | SOLVED |

---

## 18. Gio.DBusConnection GATT Registration Fails (ROOT CAUSE IDENTIFIED)

**Problem**: The upstream `steamdeck-bt-controller-emulator` uses `Gio.DBusConnection.register_object()` to register GATT objects. On SteamOS, BlueZ calls `RegisterApplication` which succeeds (callback fires), but the GATT objects are never actually registered with BlueZ's GATT server.

**Evidence**:
- `GattManager1.ActiveInstances` stays at 0 after registration
- BlueZ calls `GetManagedObjects` on the application path
- BlueZ gets `AccessDenied: Sender is not authorized` when trying to access the objects
- The GATT objects are visible via `busctl` under the hogp process's unique bus name
- But BlueZ can't access them via D-Bus (returns "No object received")

**Root Cause**: `Gio.DBusConnection.register_object()` registers objects on a private D-Bus connection. BlueZ tries to access these objects via the system bus, but the D-Bus policy blocks the access.

**Solution**: Use `dbus-python` (`dbus.service.Object`) instead of `Gio.DBusConnection`. The `dbus-python` library registers objects on the shared system bus, which is accessible to BlueZ. Our local `src/gatt_app.py` using `dbus-python` registers successfully and BlueZ accepts the GATT database.

**Key code difference**:
```python
# FAILS on SteamOS:
from gi.repository import Gio
bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
bus.register_object(path, interface, handler, None, None)

# WORKS on SteamOS:
import dbus
import dbus.service
class GattService(dbus.service.Object):
    def __init__(self, bus, path):
        super().__init__(bus, path)
```

---

## 19. ControllerMode=le Not Supported (SOLVED)

**Problem**: Setting `ControllerMode = le` in `/etc/bluetooth/main.conf` causes BlueZ to fail with `Failed to set mode: Not Supported (0x0c)`.

**Solution**: Do NOT set `ControllerMode = le`. Instead, use `btmgmt bredr off` to disable BR/EDR at runtime. The adapter stays in dual mode at the BlueZ level but BR/EDR is disabled at the kernel level.

---

## 20. Discoverable Property No Advertising in LE-only Mode (SOLVED)

**Problem**: When the adapter is in LE-only mode (`bredr off`), setting the `Discoverable` property to `true` does NOT trigger BLE advertising. The adapter does not send any advertising PDUs.

**Evidence**: btmon shows zero advertising reports from the Deck when using BlueZ's built-in discoverable advertising. The upstream hogp emulator's custom `LEAdvertisement1` objects DO work and produce advertisements visible to the host.

**Solution**: Register a proper `LEAdvertisement1` D-Bus object (using `dbus-python`, not `Gio.DBusConnection`) with:
- `Type: "peripheral"`
- `ServiceUUIDs: ["1812"]` (HID service)
- `Appearance: 0x03C4` (Gamepad)
- `LocalName: "SteamDeckHoG"`
- `Discoverable: true`

The custom advertisement must use legacy advertising (BLE 4.2 compatible) for the host's BT 4.2 adapter.

---

## 21. btmgmt Power Cycle Kills hogp (SOLVED)

**Problem**: The `config_bt.py` script runs `btmgmt` commands that power-cycle the adapter (`power off` → `bredr off` → `static-addr` → `power on`). This kills any running hogp process.

**Solution**: Always start hogp AFTER configuring btmgmt. Use `systemd-run --remain-after-exit` for persistent processes. The workflow is:
1. Stop hogp
2. Restart bluetooth service
3. Run config_bt.py
4. Start hogp with `--no-static-addr` (since static addr was already set by config_bt.py)

---

## 22. Missing Standard HOGP Service (SOLVED)

**Problem**: The GATT application only had the SC2 custom service and Device Information. BlueZ's HOGP driver requires a standard HID Service (UUID 0x1812) with HID Information, Report Map, HID Control Point, and Report characteristics to create a `/dev/hidraw` node on the host.

**Solution**: Added a complete HOGP service to `gatt_app.py`:
- HID Information (0x2A4C): bcdHID=1.11, Flags=0x02 (normally connectable)
- Report Map (0x2A4B): Minimal gamepad descriptor (16 buttons, 4 axes, 2 triggers)
- HID Control Point (0x2A4C): write-without-response
- Report Input (0x2A4D): notify + read, with Report Reference descriptor (ReportID=1, Type=Input)
- Report Output (0x2A4D): write + read, with Report Reference descriptor (ReportID=2, Type=Output)

---

## 23. Properties.Get Missing (in_signature="ss") (SOLVED)

**Problem**: BlueZ's `gatt-database.c:chrc_create()` calls `Properties.Get` (singular) with signature `ss` (interface name + property name), not `GetAll` with signature `s`. Without `Get` implemented, the proxy cache is empty and parsing fails silently.

**Solution**: Added `Get(in_signature="ss")` to all GATT objects (GattCharacteristic, GattService, GattDescriptor). Refactored to use `_get_props()` pattern so both `Get` and `GetAll` share the same property dictionary.

---

## 24. Async D-Bus Registration Blocks (SOLVED)

**Problem**: `RegisterAdvertisement` and `RegisterApplication` are async D-Bus method calls. When called synchronously (without `reply_handler`), they block waiting for a reply. The reply is delivered via the GLib main loop, which isn't running yet during setup. The call blocks forever.

**Solution**: Restructured `main.py` startup sequence:
1. Create all D-Bus objects (GATT app, advertisement, services) — no BlueZ calls
2. Own `dbus.service.BusName("com.steamdeck.hogp", bus)` — required for BlueZ access
3. Start `GLib.MainLoop`
4. Schedule registration via `GLib.idle_add()` after the loop starts
5. Registration uses async calls with `reply_handler`/`error_handler`

---

## 25. Pairing AuthenticationFailed (SOLVED — root cause was #26)

**Problem**: The host PC can see and connect to the Deck (`C2:12:34:56:78:9A Steam Controller 2026`), but pairing fails with `org.bluez.Error.AuthenticationFailed`.

**Root cause**: The underlying issue was #26 (BlueZ GATT Listener Address Mismatch). Once the raw L2CAP ATT server was implemented, SMP pairing works correctly via the Deck's Agent1 D-Bus interface (auto-confirms passkey).

**Resolution**: Implemented Agent1 in `src/agent.py` with `DisplayYesNo` capability that auto-confirms all pairing requests. Combined with the raw L2CAP ATT server, pairing now succeeds.

---

## 26. BlueZ GATT Listener Address Mismatch (SOLVED — root cause of #25)

**Problem**: BlueZ 5.86 on SteamOS binds its GATT listener socket to the adapter's **public address** (`<DECK_BT_MAC_PUBLIC>`), but BLE connections arrive on the **static random address** (`C2:12:34:56:78:9A`). The kernel's L2CAP layer can't route the ATT channel to the socket → `connect_cb` never fires → no ATT bearer → MTU exchange fails → connection drops.

**Debug proof** (`bluetoothd -d -n`):
```
adapter.c:connected_callback() hci0 device <HOST_BT_MAC> connected  # kernel accepts
# No GATT/ATT/MTU logs between connect and disconnect                    # GATT listener never fires
adapter.c:dev_disconnected() reason 2                                     # supervision timeout
```

**Solution**: Bypass BlueZ's GATT server entirely. Use a raw L2CAP socket on CID 4 bound to the static random address with `BDADDR_LE_RANDOM`. This is what BlueZ's own `peripheral/gatt.c` reference implementation does.

**Key code** (from `peripheral/gatt.c`):
```c
addr.l2_bdaddr_type = BDADDR_LE_RANDOM;  // Binds to static random address
addr.l2_cid = htobs(BT_ATT_CID);         // CID 4 = ATT fixed channel
bind(att_fd, (struct sockaddr *)&addr, sizeof(addr));
```

**Python equivalent** (confirmed working on Deck):
```python
import socket, struct, ctypes
sk = socket.socket(AF_BLUETOOTH, SOCK_SEQPACKET, BTPROTO_L2CAP)
addr_bytes = bytes.fromhex('C2123456789A')[::-1]
sockaddr = struct.pack('<HH6sHB', AF_BLUETOOTH, 0, addr_bytes, 4, 0x02)
libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
libc.bind(sk.fileno(), ctypes.create_string_buffer(sockaddr), len(sockaddr))
sk.listen(1)
conn, addr = sk.accept()
```

---

## 27. Python 3.13 BLE Socket Limitation (SOLVED)

**Problem**: Python 3.13 doesn't support the BLE address type tuple syntax for `BTPROTO_L2CAP`. `socket.bind((addr, psm, cid, bdaddr_type))` fails with "wrong format".

**Solution**: Use `ctypes` to call `bind()` directly with a manually constructed `sockaddr_l2` struct:
```python
sockaddr = struct.pack('<HH6sHB', AF_BLUETOOTH, 0, addr_bytes, CID, BDADDR_LE_RANDOM)
libc.bind(sk.fileno(), ctypes.create_string_buffer(sockaddr), len(sockaddr))
```

---

## 28. GATT Database UUID Comparison Bug (SOLVED)

**Problem**: The `find_services` method compared the service's **value UUID** (e.g., `0x1800`) against the filter UUID from the ATT request (`0x2800`). These don't match because `0x2800` is the **attribute type** (Primary Service Declaration), not the service's value.

**Fix**: The filter UUID in `Read By Group Type` requests is the attribute type UUID. All services have declaration UUID `0x2800`, so the filter should always match when querying for service declarations.

---

## 29. GATT Handle Allocation Bug (SOLVED)

**Problem**: The `add_service` method used `decl_handle + 1` for the characteristic value handle but didn't allocate it via `_alloc_handle()`. This caused the next characteristic's declaration to use the same handle as the previous characteristic's value.

**Fix**: Call `_alloc_handle()` for BOTH the declaration handle AND the value handle:
```python
decl_handle = self._alloc_handle()
value_handle = self._alloc_handle()  # Must allocate separately
```

---

## 30. MTU Exchange Response Format Bug (SOLVED)

**Problem**: The MTU response was packed as `struct.pack('<BBH', ...)` (4 bytes) instead of `struct.pack('<BH', ...)` (3 bytes). The extra byte caused the host to reject the response.

**Fix**: MTU Response is exactly 3 bytes: opcode(1) + Server RX MTU(2):
```python
resp = struct.pack('<BH', ATT_OP_MTU_RSP, self.server_mtu)
```

---

## 31. Connection Drops After Service Discovery (SOLVED)

**Problem**: The raw L2CAP ATT server successfully handles MTU exchange and service discovery (host sees `ServicesResolved: yes`), but the connection drops after ~26 seconds. The host's `bluetoothctl pair` doesn't complete pairing.

**Root causes** (three bugs working together):

1. **Malformed ATT Error Response (6 bytes instead of 5)**: The error response was packed as `struct.pack('BBBH', ...)` followed by `struct.pack('B', error_code)`, producing a 6-byte PDU. The ATT Error Response spec requires exactly 5 bytes: opcode(1) + request_opcode(1) + handle(2) + error_code(1). The extra byte corrupted the host's ATT state machine, causing it to stall after service discovery.

2. **Missing `SOL_BLUETOOTH` constant**: `socket.SOL_BLUETOOTH` doesn't exist in Python 3.13, so `setsockopt()` failed silently. The socket security level was never set, which could affect pairing behavior.

3. **Incorrect `BT_SECURITY` option number**: Used `10` instead of `4` for the socket option, and `struct.pack('ii', ...)` (8 bytes) instead of `struct.pack('BB', ...)` (2 bytes) for the `bt_security` struct.

4. **CCCD-to-value-handle mapping bug**: Used `handle - 1` to find the parent characteristic's value handle, which fails when descriptors (like Report Reference 0x2908) sit between the value and the CCCD. For the Report (Input) characteristic, CCCD at 0x0014 would map to 0x0013 (Report Reference) instead of 0x0012 (Report Value).

**Fix (in `att_server.py`)**:
```python
# Constants
SOL_BLUETOOTH = 274
BT_SECURITY = 4
BT_SECURITY_LOW = 1

# Error response (correct 5-byte format)
resp = struct.pack('<BBHB', ATT_OP_ERROR, request_opcode, handle, error_code)

# CCCD mapping (search backwards for characteristic declaration)
def _find_cccd_value_handle(self, cccd_handle):
    for h in range(cccd_handle - 1, 0, -1):
        attr = self.db.lookup(h)
        if attr and attr.uuid == uuid16_to_bytes(GATT_CHARAC_UUID):
            if len(attr.value) >= 5:
                return attr.value[1] | (attr.value[2] << 8)
    return None
```

Note: `BT_SECURITY` setsockopt is NOT supported on fixed-CID L2CAP sockets (returns EINVAL). SMP pairing is handled separately by the kernel on CID 6.

**Evidence of fix**:
- Host now sends ReadByType for 0x2803 (characteristic discovery) — 12 characteristics found
- Host discovers all descriptors via FindInformation
- Host reads HID Information, Report Map, PnP ID, Battery Level
- Host writes CCCD to enable notifications for Battery (0x001a) and Report/Input (0x0012)
- `/dev/hidraw16` created on host
- `ServicesResolved: yes`, `Paired: yes`, `Connected: yes`
- `Icon: input-gaming`, `Modalias: bluetooth:v28DEp0303d0100`

---

## 32. Host hog-ll Drops Notifications (SOLVED)

**Problem**: The Deck's ATT server sends Handle Value Notifications on handle 0x0012. The host's HCI layer receives them (confirmed via btmon), but BlueZ's hog-ll driver silently drops them instead of forwarding to uhid/input.

**Root cause**: Double Report ID prefix. Our code prepended Report ID (0x01) to notification data, making it 13 bytes. BlueZ's `report_value_cb()` strips the 3-byte ATT header, then calls `bt_uhid_input(uhid, report->numbered ? report->id : 0, pdu, len)`. When `numbered=true`, `bt_uhid_input` prepends the Report ID again (uhid.c:474), resulting in 14 bytes (double Report ID). The kernel's HID parser expects exactly 13 bytes (Report ID + 12-byte report), so the 14-byte event is silently dropped.

**Fix applied**: Removed Report ID prefix from notifications in `main_l2cap.py:_on_input_report()`. Notifications now send raw 12-byte report data. BlueZ's hog-ll handles the Report ID via `report->id` from the Report Reference descriptor.

**Verified**: Input events flow end-to-end from Deck to host `/dev/input/eventN`.

**What works end-to-end**:
```
Deck Xbox 360 pad (event10)
  → evdev → input_handler.py (12-byte report)
  → main_l2cap.py (NO Report ID prefix)
  → att_server.py send_notification(0x0012, 12 bytes)
  → raw L2CAP socket → BLE → host HCI
  → hog-ll report_value_cb → bt_uhid_input (prepends Report ID)
  → uhid → /dev/input/eventN ✅
```

---

## 33. Connection Drops After Pairing (SOLVED)

**Problem**: After pairing succeeds and services are resolved, the host resets the ATT connection within ~1 second. This prevents real controller input from being forwarded to uhid.

**Root cause**: `bluetoothctl pair` tries **BR/EDR classic bonding** first (`type 0`), which fails with status 4 (Page Timeout) because the Deck only supports BLE. After the BR/EDR failure, BlueZ cancels the bonding and tears down the entire LE connection — including the working HOGP session.

**Evidence** (from `bluetoothd -d -n` debug logs):
```
bonding_request_new() Requesting bonding for C2:12:34:56:78:9A
adapter_bonding_attempt() hci0 bdaddr C2:12:34:56:78:9A type 0 io_cap 0x01  # type 0 = BR/EDR!
connect_failed_callback() hci0 C2:12:34:56:78:9A status 4                    # Page Timeout
adapter_cancel_bonding() hci0 bdaddr C2:12:34:56:78:9A type 2                 # Cancels LE bonding
# → ALL profiles disconnect (batt, deviceinfo, gap, input-hog)
```

**Solution**: Use `bluetoothctl connect` instead of `bluetoothctl pair`. The LTK from previous pairing persists in BlueZ's storage, allowing re-connection without re-pairing. The `connect` command only establishes an LE connection and does not trigger BR/EDR bonding.

**What works end-to-end** (after fix):
```
1. sshpass -p '<DECK_PASSWORD>' ssh deck@<DECK_IP> 'systemctl restart sc2-hogp'
2. bluetoothctl scan on                    # Scans and discovers Deck
3. bluetoothctl connect C2:12:34:56:78:9A  # LE connect only, no BR/EDR
4. Host: /dev/hidrawN created, /dev/input/eventN with gamepad capabilities
5. Deck inputs → BLE notifications → host hog-ll → uhid → input events ✅
```

---

## 34. Physical Deck Input Not Working via evdev (SOLVED)

**Problem**: The input handler reads from `/dev/input/event10` (Xbox 360 pad created by `hid-steam` driver), but no real input events arrive. The evdev node exists with correct gamepad capabilities (buttons, axes) but stays silent.

**Root cause**: The `hid-steam` kernel driver only generates evdev events when `gamepad_mode` is true, which requires holding the Steam button. Without Steam running on the Deck, the controller is in **lizard mode** — buttons map to keyboard scancodes (A→Enter, B→Escape, etc.), not gamepad events. Lizard mode also re-enables every ~2 seconds, overriding any gamepad mode changes.

**Solution**: Read directly from `/dev/hidraw3` (USB interface 2, input2). The Neptune controller sends 64-byte HID reports (type 0x09 = `ID_CONTROLLER_DECK_STATE`) containing all input data: buttons, sticks, triggers, trackpads, IMU, and force sensors.

**Neptune HID Report Format** (type 0x09, 64 bytes):
| Offset | Field |
|--------|-------|
| 0-3 | Header: `01 00 09 40` |
| 4-7 | Frame counter (u32 LE) |
| 8 | Buttons: A/X/B/Y/L1/R1/L2/R2 |
| 9 | Buttons: L5/Menu/Steam/Options/Down/Left/Right/Up |
| 10 | Buttons: L3/RPadTouch/LPadTouch/RPadPress/LPadPress/R5 |
| 11 | Buttons: R3 |
| 13 | Buttons: RStickTouch/LStickTouch/R4/L4 |
| 14 | Buttons: QuickAccess |
| 16-23 | Trackpads: LPadXY, RPadXY (i16 LE) |
| 24-35 | IMU: accelXYZ, gyroXYZ (i16 LE) |
| 44-47 | Triggers: L/R (u16 LE, 0..32767) |
| 48-55 | Sticks: LX/LY/RX/RY (i16 LE, -32767..32767) |
| 56-63 | Force: pad/stick capacitive touch |

**Button mapping** (Neptune → SC2 12-byte report):
| Neptune | SC2 bitmask |
|---------|-------------|
| byte8 bit0 (A) | 0x0001 (BTN_SOUTH) |
| byte8 bit2 (B) | 0x0002 (BTN_EAST) |
| byte8 bit1 (X) | 0x0004 (BTN_NORTH) |
| byte8 bit3 (Y) | 0x0008 (BTN_WEST) |
| byte8 bit4 (L1) | 0x0010 (BTN_TL) |
| byte8 bit5 (R1) | 0x0020 (BTN_TR) |
| byte9 bit1 (Menu) | 0x0040 (BTN_SELECT) |
| byte9 bit3 (Options) | 0x0080 (BTN_START) |
| byte9 bit2 (Steam) | 0x0100 (BTN_MODE) |
| byte10 bit1 (L3) | 0x0200 (BTN_THUMBL) |
| byte11 bit5 (R3) | 0x0400 (BTN_THUMBR) |
| byte9 bit7 (Up) | 0x0800 (DPAD_UP) |
| byte9 bit4 (Down) | 0x1000 (DPAD_DOWN) |
| byte9 bit5 (Left) | 0x2000 (DPAD_LEFT) |
| byte9 bit6 (Right) | 0x4000 (DPAD_RIGHT) |

Sticks: direct copy (same format). Triggers: `>> 7` to scale from 16-bit to 8-bit.

**Lizard mode OFF commands** (output report via `os.write()`):
1. `[0x01, 0x00, 0x81] + [0]*61` — ClearDigitalMappings
2. `[0x01, 0x00, 0x87, 0x03, 0x08, 0x07, 0x00] + [0]*57` — disable left trackpad mouse
3. `[0x01, 0x00, 0x87, 0x03, 0x15, 0x00, 0x00] + [0]*57` — disable smooth mouse
4. Re-send 0x81 every ~2 seconds

**Reference**: [InputPlumber](https://github.com/ShadowBlip/InputPlumber) — Neptune protocol documentation

---

## 35. Feature Report ioctl EINVAL on hidraw (SOLVED)

**Problem**: `ioctl(fd, HIDIOCSFEATURE, ...)` returns `EINVAL` when writing output/feature reports to Neptune's hidraw device.

**Solution**: Use `os.write(fd, report_data)` to send output reports instead of ioctl. The hidraw device accepts raw output reports via the write syscall.

---

## Summary of Blockers
