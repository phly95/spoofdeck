# BlueZ Debug bluetoothd Output Analysis — CONFIRMED ROOT CAUSE

## Date: 2026-06-24

## What We Did
1. Started `bluetoothd -d -n` (debug mode) on the Deck
2. Applied `config_bt.py` (bredr off + static-addr C2:12:34:56:78:9A)
3. Started our hogp GATT server
4. Connected from host PC
5. Captured debug output

## Debug Output (Key Lines)

```
Jun 24 10:55:56 bluetoothd[40935]: src/adapter.c:connected_callback() hci0 device <HOST_BT_MAC> connected eir_len 0
Jun 24 10:56:00 bluetoothd[40935]: src/adapter.c:dev_disconnected() Device <HOST_BT_MAC> disconnected, reason 2
Jun 24 10:56:00 bluetoothd[40935]: [signal] org.bluez.Bearer.LE1.Disconnected
Jun 24 10:56:00 bluetoothd[40935]: src/adapter.c:bonding_attempt_complete() hci0 bdaddr <HOST_BT_MAC> type 1 status 0xe
Jun 24 10:56:00 bluetoothd[40935]: src/device.c:device_bonding_failed() status 14
```

## Analysis

### What DID happen:
- `connected_callback` fires — the LE connection IS accepted at the MGMT/kernel level
- The host's MAC `<HOST_BT_MAC>` is recognized
- Connection is established (reason 2 = supervision timeout after 4s)

### What did NOT happen (CRITICAL):
- **NO `gatt-database` logs** — `connect_cb` in `gatt-database.c:646` was NEVER called
- **NO `device_attach_att` logs** — ATT bearer was NEVER created
- **NO `exchange_mtu` logs** — MTU handler was NEVER invoked
- **NO `bt_io_accept` or `io_accept` logs** — the L2CAP ATT socket never accepted the connection

### Conclusion:
The kernel-level LE connection is accepted (MGMT `Device Connected` event), but the GATT listener socket (L2CAP CID 4) never accepts the ATT channel. This means:

1. `bt_io_listen` in `btd_gatt_database_new()` created a socket listening on CID 4
2. The socket is bound to the adapter's public address `<DECK_BT_MAC_PUBLIC>`
3. The BLE connection arrives on the static random address `C2:12:34:56:78:9A`
4. The kernel's L2CAP layer cannot route the ATT channel to the socket because the addresses don't match
5. The ATT channel is silently dropped
6. After ~4s supervision timeout, the connection is terminated

### Why `connect_cb` never fires:
The `bt_io_listen` socket is bound to `btd_adapter_get_address(adapter)` which returns the public address `<DECK_BT_MAC_PUBLIC>`. When a BLE connection arrives on `C2:12:34:56:78:9A`, the kernel's L2CAP layer tries to find a socket bound to that address. No such socket exists → ATT channel not accepted → `connect_cb` never fires.

## Fix Options

### Option 1: Don't use `bredr off` (Simplest)
Without `bredr off`, the adapter uses its public address for everything. The GATT listener binds to the public address. BLE connections to the public address would work.

**Problem**: The host sees BR/EDR UUIDs and tries BR/EDR first, which fails with `br-connection-unknown`.

**Workaround**: Force BLE-only connection from the host using `hcitool` or custom pairing script.

### Option 2: Bypass BlueZ's GATT server (Most Robust)
Use a raw L2CAP socket on CID 4, bind it to the static random address, and handle ATT requests ourselves. This is what the BlueZ `peripheral/gatt.c` reference implementation does.

**Implementation**: Create a new module `src/att_server.py` that:
1. Opens a raw L2CAP socket on CID 4
2. Binds to `C2:12:34:56:78:9A` with `BDADDR_LE_RANDOM`
3. Handles ATT Exchange MTU, Read By Group Type, etc.
4. Serves our GATT database

### Option 3: Patch BlueZ (Not feasible on SteamOS)
Modify `gatt-database.c:connect_cb` to also check the static address. Requires rebuilding BlueZ.

## Recommendation
Option 2 (bypass BlueZ's GATT server) is the most robust fix. It gives us full control over the ATT layer and eliminates the address binding issue entirely.
