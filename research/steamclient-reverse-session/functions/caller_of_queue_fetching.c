⚠️ DISCLAIMER: WRONG BINARY ANALYZED

All analysis in this file was performed on the WRONG binary:
  ~/.steam/debian-installation/ubuntu12_32/steamclient.so (49MB, 32-bit) [CORRECT]

Steam actually loads:
  ~/.steam/debian-installation/ubuntu12_32/steamclient.so (49MB, 32-bit i386)

ALL ADDRESSES, FUNCTION OFFSETS, AND DISASSEMBLY ARE WRONG for the running process.
The conceptual findings (gate mechanism, YieldingRunTestProgram, job system) likely
apply to both binaries, but every specific address must be re-derived from the
32-bit binary or verified via GDB on the running process.

Verified: 2026-06-29
- Steam process: ELF 32-bit LSB pie executable (i386)
- steamclient.so loaded: ubuntu12_32/steamclient.so
- YieldingRunTestProgram string: 0x00bfc7e3 (32-bit) vs 0x00d6d17b (64-bit)

# Caller of QueueFetchingControllerDetails

## Location
- Binary: `~/.steam/debian-installation/ubuntu12_32/steamclient.so` (32-bit, 49MB) [CORRECT]
- Function start: `0x010b2ca0 [32-bit: NEEDS RE-ANALYSIS]` (within `Steam_GSGetSteamID + 0xc1560`)
- Calls QueueFetchingControllerDetails at `0x010b2e53 [32-bit: NEEDS RE-ANALYSIS]`

## Pseudocode

```c
// rdi = CSteamController* controller (saved to ebx)

void CallerOfQueueFetchingControllerDetails(CSteamController* controller) {
    // Save canary
    uint64_t canary = fs:0x28;
    
    // Copy ControllerDetails fields from controller object to stack buffer
    // Stack buffer is at rsp+0x30 (size 0x54 bytes)
    
    // First, copy 10 qwords + 1 dword from controller offsets 0x84-0xd4
    struct {
        uint64_t field_00;  // from controller+0x84
        uint64_t field_08;  // from controller+0x8c
        uint64_t field_10;  // from controller+0x94
        uint64_t field_18;  // from controller+0x9c
        uint64_t field_20;  // from controller+0xa4
        uint64_t field_28;  // from controller+0xac
        uint64_t field_30;  // from controller+0xb4
        uint64_t field_38;  // from controller+0xbc
        uint64_t field_40;  // from controller+0xc4
        uint64_t field_48;  // from controller+0xcc
        uint32_t field_50;  // from controller+0xd4
    } details;
    
    details.field_00 = controller->field_84;
    details.field_08 = controller->field_8c;
    details.field_10 = controller->field_94;
    details.field_18 = controller->field_9c;
    details.field_20 = controller->field_a4;
    details.field_28 = controller->field_ac;
    details.field_30 = controller->field_b4;
    details.field_38 = controller->field_bc;
    details.field_40 = controller->field_c4;
    details.field_48 = controller->field_cc;
    details.field_50 = controller->field_d4;
    
    // Overwrite first dword with controller index from offset 0x18
    details.field_00 = controller->field_18;  // dword
    
    // Check if controller is active
    bool is_active = controller->field_28;  // byte
    uint8_t flag_80 = controller->field_80;  // byte
    
    uint8_t force_update = 0;
    if (is_active) {
        if (flag_80 != 0) {
            force_update = 1;
        }
    }
    
    // Call some logging/tracking function
    function_104ca50(/* various params */);
    
    // Log the operation
    function_1790ba0(/* format string, ... */);
    
    // Check controller type against known product IDs
    uint16_t product_id = controller->field_8a;  // word
    
    bool is_known_type = false;
    if (product_id == 0x1142) is_known_type = true;
    if (product_id == 0x1220) is_known_type = true;
    if (product_id >= 0x1201 && product_id <= 0x1206) is_known_type = true;
    if (product_id >= 0x1302 && product_id <= 0x1305) is_known_type = true;
    
    if (!is_known_type) {
        // Check if product_id & ~4 is in range 0x1101-0x1102
        uint16_t masked = product_id & 0xFFFB;
        if ((masked - 0x1101) <= 1) {
            is_known_type = true;
        }
    }
    
    // Also check stack field at rsp+0x4c
    if (!is_known_type) {
        if (details_from_stack->field_4c == 0) {
            // Unknown controller type - log warning but continue
            function_26cdc00(/* warning */);
            // If assertion fails, continue anyway
            if (!function_26cbfc0()) {
                goto skip_details;
            }
        }
    }
    
    // Call QueueFetchingControllerDetails
    // rdi = controller->field_8 (sub-object)
    // rsi = &details (stack buffer)
    // edx = 0 (force_update = false, unless set above)
    QueueFetchingControllerDetails(
        controller->field_8,  // sub-controller object
        &details,             // ControllerDetails struct on stack
        force_update          // bool
    );
    
    // Call another function with the details
    function_15a6880(
        some_global_ptr,      // from rip+0x1bac846 -> 0x2c5f6b0
        0x102ca7,            // constant
        &details,            // the details struct
        0x54,                // size of ControllerDetails_tE
        0                    // flags
    );
    
    // Verify canary
    if (canary != fs:0x28) {
        __stack_chk_fail();
    }
}

skip_details:
    // Continue without setting details
    goto after_queue;
```

## Key Observations

1. **Data Source**: ControllerDetails fields come from controller object offsets 0x84-0xd4
2. **Controller ID**: The first dword is overwritten with the value from offset 0x18
3. **Product ID Check**: The word at offset 0x8a is checked against known Steam Controller product IDs:
   - 0x1142, 0x1220
   - 0x1201-0x1206
   - 0x1302-0x1305 (SC2 range!)
   - 0x1101-0x1102
4. **Force Update**: Set to 1 if controller->field_28 is set AND controller->field_80 is non-zero
5. **The function at 0x15a6880** is called after QueueFetchingControllerDetails - this might be the function that processes the details further

## Controller Object Field Map (reconstructed)

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0x08 | 8 | field_08 | Sub-controller object pointer |
| 0x18 | 4 | field_18 | Controller index (dword) |
| 0x28 | 1 | field_28 | Is active flag (byte) |
| 0x80 | 1 | field_80 | Unknown flag (byte) |
| 0x84 | 8 | field_84 | ControllerDetails field_00 |
| 0x8c | 8 | field_8c | ControllerDetails field_08 |
| 0x94 | 8 | field_94 | ControllerDetails field_10 |
| 0x9c | 8 | field_9c | ControllerDetails field_18 |
| 0xa4 | 8 | field_a4 | ControllerDetails field_20 |
| 0xac | 8 | field_ac | ControllerDetails field_28 |
| 0xb4 | 8 | field_b4 | ControllerDetails field_30 |
| 0xbc | 8 | field_bc | ControllerDetails field_38 |
| 0xc4 | 8 | field_c4 | ControllerDetails field_40 |
| 0xcc | 8 | field_cc | ControllerDetails field_48 |
| 0xd4 | 4 | field_d4 | ControllerDetails field_50 |
| 0x8a | 2 | field_8a | Product ID (word) |
