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

# EYldWaitForControllerDetails Function

## Location
- Binary: `~/.steam/debian-installation/ubuntu12_32/steamclient.so` (32-bit, 49MB) [CORRECT]
- Function start: `0x01071c70 [32-bit: NEEDS RE-ANALYSIS]` (within `Steam_GSGetSteamID + 0x8a530`)
- String reference: `EYldWaitForControllerDetails` at vaddr `0x00b9979f`
- Timeout: `0x1e8480` (2,000,000 microseconds = 2 seconds)

## Pseudocode

```c
// rdi = CSteamController* controller
// esi = controller_index
// rdx = ControllerDetails_tE* output_buffer

int BYieldingWaitForControllerDetails(CSteamController* controller, 
                                        int controller_index,
                                        ControllerDetails_tE* output_buffer) {
    // Access per-controller data array at controller + controller_index*8 + 0x119e10
    void* per_controller_data = controller->field_119e10[controller_index];
    
    if (per_controller_data == NULL) {
        // Initialize empty ControllerDetails_tE on stack
        ControllerDetails_tE empty = {0};
        // ... copy empty to output ...
        return 0x10;  // Error: no controller data
    }
    
    void* first_field = per_controller_data->field_0;
    if (first_field == NULL) {
        ControllerDetails_tE empty = {0};
        // ... copy empty to output ...
        return 0x10;
    }
    
    // Set up stack buffer (0x10 bytes at rsp+0x10)
    void* stack_buffer = rsp + 0x10;
    void* data_ptr = first_field + 8;  // Skip first qword
    
    // Call function to copy/wait for data
    function_27aabe0(stack_buffer, data_ptr);
    
    // Set up vtable/function pointer table
    void* vtable_entry = GOT_SLOT;  // rip + 0x1a59263 -> 0x2ad7498
    
    // Call virtual function on controller: [controller+0x2c8]
    // This is likely BYieldingWaitForControllerDetails or similar
    int controller_idx = controller_index;
    controller->vtable->field_2c8(controller, controller_idx);
    
    // Wait with timeout
    // edx = 0x1e8480 (2,000,000 us = 2 second timeout)
    // rdi = stack_buffer
    // rsi = "EYldWaitForControllerDetails" (string at 0xd4da02)
    // ecx = 0
    int result = WaitForSomething(stack_buffer, "EYldWaitForControllerDetails", 
                                   0x1e8480, 0);
    
    // Check result
    if (result == 1) {
        // SUCCESS: Copy ControllerDetails_tE from stack to output
        // Stack buffer contains the details at offset 0x20 from stack_buffer base
        
        output_buffer->field_00 = stack_buffer[0x20];  // qword
        output_buffer->field_08 = stack_buffer[0x28];  // qword
        output_buffer->field_10 = stack_buffer[0x30];  // qword
        output_buffer->field_18 = stack_buffer[0x38];  // qword
        output_buffer->field_20 = stack_buffer[0x40];  // qword
        output_buffer->field_28 = stack_buffer[0x48];  // qword
        output_buffer->field_30 = stack_buffer[0x50];  // qword
        output_buffer->field_38 = stack_buffer[0x58];  // qword
        output_buffer->field_40 = stack_buffer[0x60];  // qword
        output_buffer->field_48 = stack_buffer[0x68];  // qword
        output_buffer->field_50 = stack_buffer[0x70];  // dword
        
        return 1;  // Success
    } else if (result == 2) {
        return 2;  // Timeout or other error
    } else {
        // Clean up stack buffer
        stack_buffer->field_08 -= 1;
        if (stack_buffer->field_08 == 0) {
            // Call destructor
            void* destructor = stack_buffer->field_0;
            if (destructor->field_10 ==特定値) {
                destructor->vtable->field_08(stack_buffer);
            }
        }
        return 0x10;  // Error
    }
}
```

## Key Observations

1. **ControllerDetails_tE is 0x54 bytes (84 bytes)** - the copy loop transfers exactly 0x54 bytes
2. **The struct has 10 qword fields and 1 dword field** at the end
3. **The blocking condition**: The function calls `WaitForSomething()` with a 2-second timeout. It blocks until either:
   - Result == 1: Controller details are ready (success)
   - Result == 2: Some other state
   - Result == other: Error, returns 0x10
4. **The per-controller data is at offset 0x119e10** from the CSteamController base, indexed by controller ID * 8
