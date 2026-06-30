⚠️ DISCLAIMER: PARTIALLY CONVERTED — MIXED 32/64-BIT ADDRESSES

Some addresses in this file have been converted to 32-bit equivalents.
Others are still from the 64-bit binary and are INVALID for the running process.

  64-bit binary: ~/.steam/debian-installation/linux64/steamclient.so (46MB, x86_64)
  32-bit binary: ~/.steam/debian-installation/ubuntu12_32/steamclient.so (49MB, i386)

Addresses tagged [32-bit: NEEDS RE-ANALYSIS] are converted but unverified.
Addresses without this tag are still 64-bit and WRONG.
All addresses should be verified via GDB on the running process.

Verified: 2026-06-30
- Steam process: ELF 32-bit LSB pie executable (i386)
- steamclient.so loaded: ubuntu12_32/steamclient.so
- YieldingRunTestProgram string: 0x00bfc7e3 (32-bit) vs 0x00d6d17b (64-bit)

# Controller Identification Function

## Location
- Binary: `~/.steam/debian-installation/ubuntu12_32/steamclient.so` (32-bit, 49MB) [CORRECT]
- Function: `0x010c4a00 [32-bit: NEEDS RE-ANALYSIS]` (within `Steam_GSGetSteamID + 0xd32c0`)
- Contains references to "Controller uses V1 HID protocol" strings

## Pseudocode

```c
// This function identifies the controller type and creates the appropriate handler
// rdx = controller info struct (contains product ID at offset 0x7c)

void IdentifyControllerType(void* controller_info) {
    int product_id = controller_info->field_7c;  // Product ID at offset 0x7c
    
    // Check for specific product IDs
    if (product_id == 0x1303) {
        // SC2 (Neptune/SC2) - Steam Controller 2026
        // Create SC2-specific handler
        goto create_sc2_handler;
    }
    
    if (product_id == 0x1302 || product_id == 0x1304) {
        // USB SC2 or Puck (dongle)
        goto create_usb_or_puck_handler;
    }
    
    // Check for older product IDs
    if (product_id == 0x1101 || product_id == 0x1102 || product_id == 0x1104) {
        // Original Steam Controller or variants
        goto create_original_sc_handler;
    }
    
    if (product_id == 0x1042) {
        // Another variant
        goto create_variant_handler;
    }
    
    // Default: unknown controller
    // Log "Unrecognized controller using V1 HID protocol"
    LogMessage("Unrecognized controller using V1 HID protocol");
    
    // Create generic handler
    goto create_generic_handler;

create_sc2_handler:
    // Log "Controller uses V1 HID protocol via BLE"
    LogMessage("Controller uses V1 HID protocol via BLE");
    
    // Allocate 0x30 bytes for controller handler
    void* handler = malloc(0x30);
    
    // Set up vtable
    handler->vtable = &SC2HandlerVtable;  // at 0x2ae1b58
    
    // Initialize handler fields
    handler->field_08 = 0;  // not connected yet
    handler->field_10 = controller_info;  // store controller info
    handler->field_18 = 0;  // no data yet
    handler->field_20 = 0;  // no data yet
    handler->field_28 = 1;  // is_ble = true
    
    // Set vtable to connected state
    handler->vtable = &SC2HandlerConnectedVtable;  // at 0x2ae1c10
    
    return handler;
}
```

## Key Observations

1. **Product ID 0x1303 = SC2 (Neptune/SC2)** - This is the main target
2. **Product ID 0x1302 = USB SC2** (wired mode)
3. **Product ID 0x1304 = Puck** (dongle)
4. **The handler is 0x30 bytes** and has a vtable pointer
5. **BLE connection** is identified by the "via BLE" string
6. **The handler stores controller info** at offset 0x10

## Product ID Table

| Product ID | Controller | Connection |
|-----------|------------|------------|
| 0x1302 | SC2 (USB) | Wired USB |
| 0x1303 | SC2 (BLE) | Bluetooth LE |
| 0x1304 | Puck | Dongle |
| 0x1101-0x1104 | Original SC | Various |
| 0x1042 | Variant | Unknown |
