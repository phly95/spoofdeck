/*
 * Slot Data Population Analysis — What Populates controller+slot*0xe8+0x200
 *
 * Binary: ~/.steam/debian-installation/ubuntu12_32/steamclient.so (32-bit, 49MB)
 * Status: DETERMINED
 *
 * CRITICAL FINDING: There are TWO DIFFERENT data structures that are often confused:
 *
 * 1. ControllerDetails_tE (stride 0x54, at controller+0x1070+id*0x54)
 *    - Written by QueueFetchingControllerDetails (0x1092820)
 *    - Used by EYldWaitForControllerDetails (blocks registration)
 *    - ready_flag at ControllerDetails+0x3c
 *
 * 2. Identity Slot Data (stride 0xe8, at controller+slot*0xe8+0x1f8)
 *    - Read by GetControllerInfo (0x1070620) — the zombie check
 *    - ready_flag at slot+0x200 (first byte of unique_id)
 *    - This is what the zombie timer checks
 *
 * THE BLOCKER: GetControllerInfo checks [controller+slot*0xe8+0x200] != 0.
 * This is the identity slot's unique_id field, NOT the ControllerDetails ready_flag.
 * QueueFetchingControllerDetails writes to ControllerDetails (different struct).
 * The identity slot is populated by a DIFFERENT code path.
 */

⚠️ DISCLAIMER: 64-BIT ADDRESSES — NEEDS RE-ANALYSIS

All function addresses and offsets in this file are from the 64-bit binary:
  ~/.steam/debian-installation/linux64/steamclient.so (46MB, 64-bit x86_64)

Steam actually loads the 32-bit binary:
  ~/.steam/debian-installation/ubuntu12_32/steamclient.so (49MB, 32-bit i386)

These 64-bit addresses are WRONG for the running process. Every address must be
re-derived from the 32-bit binary or verified via GDB on the running process.
The conceptual findings (gate mechanism, YieldingRunTestProgram, job system) likely
apply to both binaries, but all specific addresses are invalid.

Verified: 2026-06-30
- Steam process: ELF 32-bit LSB pie executable (i386)
- steamclient.so loaded: ubuntu12_32/steamclient.so
- YieldingRunTestProgram string: 0x00bfc7e3 (32-bit) vs 0x00d6d17b (64-bit)


/*
 * === THE TWO DATA STRUCTURES ===
 *
 * Controller Details (stride 0x54):
 *   controller+0x1070 + id*0x54 + 0x00..0x54
 *   Written by: QueueFetchingControllerDetails (0x1092820)
 *   Read by: EYldWaitForControllerDetails
 *   ready_flag at: controller+0x1070+id*0x54+0x3c
 *
 * Identity Slot (stride 0xe8):
 *   controller+slot*0xe8 + 0x1f8..0x235
 *   Read by: GetControllerInfo (0x1070620) — zombie check
 *   ready_flag at: controller+slot*0xe8+0x200 (first byte of unique_id)
 *   Written by: ???
 */

/*
 * === IDENTITY SLOT LAYOUT ===
 *
 * Base: controller_obj + slot_index * 0xe8
 *
 * Offset  Size  Field              Description
 * ------  ----  -----              -----------
 * +0x1f8  4     product_id         Controller product ID (e.g., 0x1303)
 * +0x1fc  4     secondary_id       Firmware/board version
 * +0x200  17    unique_id          Serial number — FIRST BYTE IS READY FLAG
 * +0x214  32    identity_data      Capability data from 0xf2 responses
 * +0x234  1     capability_flags   Capability bitmask
 * +0x235  1     transport_type     3=BLE, 2=USB, 4=Dongle
 * +0x238  8     name_array_ptr     Pointer to name array
 * +0x240  4     name_array_count   Number of names
 * +0x244  4     name_array_cap     Name array capacity
 * +0x248  4     field_50           Unknown
 * +0x250  4     mode               Controller mode
 * +0x254  8     name_ptr           Controller name string
 * +0x25c  26    settings_string    "#SettingsController_SteamController"
 * +0x274+ various calibration      Calibration data
 *
 * Total per slot: 0xe8 (232 bytes)
 *
 * For slot 0: identity data starts at controller+0x1f8
 * For slot 1: identity data starts at controller+0x2e0
 * For slot N: identity data starts at controller+0x1f8 + N*0xe8
 */

/*
 * === GETCONTROLLERINFO READS (0x107086e-0x1070a54) ===
 *
 * ; r12 = controller_obj, rbp = slot_index
 * 0x107086e: imul r13, rbp, 0xe8        ; r13 = slot * 0xe8
 * 0x1070888: lea rax, [r12+r13]          ; rax = controller + slot*0xe8
 * 0x107088c: cmp byte [rax+0x200], 0     ; CHECK: ready_flag at slot+0x200
 * 0x1070893: jne 0x10708a0               ; if non-zero → copy data
 * 0x1070895: ... unlock mutex, return 0   ; if zero → "not ready"
 *
 * ; SUCCESS PATH (0x10708a0):
 * 0x10708a0: mov edx, [rax+0x1f8]        ; product_id from slot+0x1f8
 * 0x10708b2: mov [ebx], edx              ; output[0x00] = product_id
 * 0x10708b4: mov eax, [rax+0x1fc]        ; secondary_id from slot+0x1fc
 * 0x10708c2: mov [ebx+4], eax            ; output[0x04] = secondary_id
 * 0x10708ba: lea rdx, [r12+r13+0x200]    ; rdx = slot+0x200 (unique_id)
 * 0x10708df: movdqu xmm3, [rdx]          ; copy 16 bytes from slot+0x200
 * 0x10708e3: movups [ebx+8], xmm3        ; output+0x08 = first 16 bytes
 * 0x10708e7: movzx eax, byte [rdx+0x10]  ; 17th byte from slot+0x210
 * 0x10708eb: mov [ebx+0x18], al          ; output+0x18 = 17th byte
 * 0x1070907: lea rax, [r12+r13+0x224]    ; end of identity (slot+0x224)
 * 0x107090f: lea rdx, [r12+r13+0x214]    ; start of identity (slot+0x214)
 * 0x1070929: movdqu xmm1, [rdx]          ; 16 bytes from slot+0x214
 * 0x107092d: movups [ebx+0x1c], xmm1     ; output+0x1c = identity part 1
 * 0x1070931: movdqu xmm2, [rdx+0x10]     ; 16 bytes from slot+0x224
 * 0x1070936: movups [ebx+0x2c], xmm2     ; output+0x2c = identity part 2
 * 0x107093a: movzx eax, byte [rdx+0x20]  ; slot+0x234 (capability_flags)
 * 0x107093e: mov [ebx+0x3c], al          ; output+0x3c = capability_flags
 * 0x1070941: imul rax, rbp, 0xe8
 * 0x1070948: movzx eax, byte [r12+rax+0x235] ; slot+0x235 (transport_type)
 * 0x1070951: mov [ebx+0x3d], al          ; output+0x3d = transport_type
 *
 * ; After data copy, set r14d = 1 (success)
 * 0x1070a54: mov r14d, 1
 */

/*
 * === QUEUEFETCHINGCONTROLLERDETAILS WRITES (0x1092820-0x10929e8) ===
 *
 * This function writes to a COMPLETELY DIFFERENT location:
 *   controller + 0x1070 + id * 0x54  (ControllerDetails slot)
 *
 * NOT to: controller + slot * 0xe8 + 0x200  (identity slot)
 *
 * 0x109284b: imul rax, rax, 0x54        ; id * 0x54 (ControllerDetails stride)
 * 0x1092851: lea rax, [rdi + rax + 0x1070]  ; controller + 0x1070 + id*0x54
 *
 * Copies qwords from details_input (ebx) to ControllerDetails slot (rax):
 *   [rax+0x08] = [rsi+0x00]  (qword)
 *   [rax+0x10] = [rsi+0x08]  (qword)
 *   [rax+0x18] = [rsi+0x10]  (qword)
 *   ... up to ...
 *   [rax+0x58] = [rsi+0x50]  (dword)
 *
 * Then sets ready_flag:
 * 0x10929bf: mov dword [esi + 0x3c], 1  ; controller+0x3c = 1
 *            (NOT controller+slot*0xe8+0x200!)
 */

/*
 * === CALLER OF QUEUEFETCHINGCONTROLLERDETAILS (0x10b2ca0) ===
 *
 * Reads from controller object at FIXED offsets (not slot-indexed):
 *   controller+0x84 → stack[0x30]
 *   controller+0x8c → stack[0x38]
 *   controller+0x94 → stack[0x40]
 *   controller+0x9c → stack[0x48]
 *   controller+0xa4 → stack[0x50]
 *   controller+0xac → stack[0x58]
 *   controller+0xb4 → stack[0x60]
 *   controller+0xbc → stack[0x68]
 *   controller+0xc4 → stack[0x70]
 *   controller+0xcc → stack[0x78]
 *   controller+0xd4 → stack[0x80] (dword)
 *
 * Then overwrites first dword:
 *   stack[0x30] = controller+0x18 (controller index)
 *
 * Calls QueueFetchingControllerDetails:
 *   rdi = controller+0x08 (sub-controller object)
 *   rsi = stack (ControllerDetails struct, 0x54 bytes)
 *   edx = force_update flag (0 or 1)
 *
 * These controller+0x84..0xd4 fields are populated by the feature report
 * handshake processing code at 0x10d4e6c.
 */

/*
 * === THE CRITICAL QUESTION: WHO WRITES TO IDENTITY SLOT? ===
 *
 * The identity slot at controller+slot*0xe8+0x1f8 is populated by a code path
 * that is NOT QueueFetchingControllerDetails. The key evidence:
 *
 * 1. GetControllerInfo (0x1070620) reads from controller+slot*0xe8+0x200
 * 2. QueueFetchingControllerDetails writes to controller+0x1070+id*0x54
 * 3. These are at DIFFERENT addresses
 *
 * The identity slot must be populated by the feature report response processing
 * code. When Steam reads Feature Report 0x00 and gets a response, the response
 * is parsed and stored in the identity slot.
 *
 * The feature report processing state machine at 0x10d4e6c handles the
 * command dispatch. For each command (GET_ATTRIBUTES, GET_SERIAL, 0xf2, etc.),
 * the response is parsed and stored.
 *
 * The key function that writes to the identity slot is likely called from
 * the feature report processing code. It receives the parsed response data
 * and stores it at controller+slot*0xe8+0x1f8.
 */

/*
 * === WHAT WE KNOW ABOUT THE IDENTITY SLOT WRITER ===
 *
 * The identity slot is populated during the feature report handshake.
 * The handshake flow is:
 *
 * 1. Steam opens /dev/hidrawN
 * 2. BlueZ hog-ll sends ATT Read Request for HID Report Value
 * 3. Our ATT server responds with our stored response
 * 4. Steam parses the response (GET_ATTRIBUTES, GET_SERIAL, etc.)
 * 5. Steam stores parsed data in identity slot at controller+slot*0xe8+0x1f8
 * 6. After all responses are processed, unique_id at +0x200 becomes non-zero
 * 7. GetControllerInfo succeeds → controller is registered
 *
 * The critical point: our ATT server must return responses that the processing
 * code can parse correctly. If the response format is wrong, the processing
 * code either skips it or stores garbage, and the unique_id stays zero.
 *
 * The unique_id (17 bytes at +0x200) is likely populated by the serial number
 * characteristic response. The first byte being non-zero IS the ready flag.
 *
 * For a real SC2, the serial number is the MAC address or a firmware-derived
 * string. The first byte would be non-zero (e.g., 0x50 for 'P' in "PV000...")
 * or the first byte of the MAC address.
 */

/*
 * === IMPLICATION FOR OUR ATT SERVER ===
 *
 * Our ATT server must provide responses that:
 * 1. Have the correct format for each command
 * 2. Include a non-zero serial number (unique_id)
 * 3. Are returned at the right time (before the 6s zombie timer)
 *
 * The serial number response must contain at least one non-zero byte.
 * Any non-zero value in the first byte should satisfy the ready_flag check.
 *
 * The identity data (32 bytes at +0x214) must contain valid capability data
 * from the 0xf2 responses.
 *
 * The product_id (4 bytes at +0x1f8) must be 0x1303 for SC2 BLE.
 * The transport_type (1 byte at +0x235) must be 3 for BLE.
 */
