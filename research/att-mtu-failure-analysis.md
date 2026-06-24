# Research: BlueZ ATT Server MTU Exchange Failure

## Root Cause Summary

BlueZ's GATT listener socket on the Deck is bound to the adapter's **public address** (`<DECK_BT_MAC_PUBLIC>`), but the BLE connection arrives on the **static random address** (`C2:12:34:56:78:9A`). 

The `connect_cb` in `gatt-database.c:646` has two **silent return paths**:
```c
adapter = adapter_find(&src);
if (!adapter) return;    // SILENT — no error logged!
```

When `adapter_find` can't match the source address to any adapter, the connection is accepted at HCI level but no ATT bearer is created, so no ATT responses are sent.

## Evidence

| Check | Result |
|-------|--------|
| Host btmon | MTU Request sent, no response, 3.5s timeout |
| Deck btmon | MTU Request received (ACL Data RX), no ACL TX, disconnect initiated |
| Adapter Address | `<DECK_BT_MAC_PUBLIC>` (public) |
| Adapter AddressType | `public` (even after `btmgmt static-addr`) |
| BLE connection address | `C2:12:34:56:78:9A` (static random) |

## BlueZ Source Code Path

1. `gatt-database.c:connect_cb` — accepts incoming LE ATT connection
2. `device.c:device_attach_att` — creates bt_att + bt_gatt_server
3. `shared/gatt-server.c:exchange_mtu_cb` — handles MTU exchange
4. `shared/att.c:handle_notify` — dispatches ATT PDUs to registered handlers

The MTU handler IS properly implemented and registered. The problem is upstream: `connect_cb` never fires or returns early.

## Key Files

- `src/gatt-database.c:646` — `connect_cb` (connection acceptance)
- `src/device.c:6429` — `device_attach_att` (ATT bearer creation)
- `src/shared/gatt-server.c:1495` — `exchange_mtu_cb` (MTU handler)
- `src/shared/att.c:1077` — `can_read_data` (ATT PDU dispatch)

## BlueZ Issues

- [#1717](https://github.com/bluez/bluez/issues/1717) — Services not discovered after first-time pairing
- [#1125](https://github.com/bluez/bluez/issues/1125) — BLE pairing fails if GATT info not cached

## Upstream Project Analysis

The `xXJSONDeruloXx/steamdeck-bt-controller-emulator` uses `Gio.DBusConnection.register_object()` (not dbus-python). It does NOT own a bus name. Its D-Bus policy uses `group="bluetooth"`.

## Fix Options

1. **Run `bluetoothd -d -n`** to get debug output confirming the exact failure point
2. **Use `main.conf` settings** to make BlueZ use the static address (may not work on SteamOS)
3. **Restart bluetoothd after btmgmt** to reinitialize with the correct address
4. **Bypass BlueZ's GATT server** entirely (use raw L2CAP socket like `peripheral/gatt.c`)
