/*
 * Registration Data Flow — What Data Registration Needs
 *
 * Binary: ~/.steam/debian-installation/ubuntu12_32/steamclient.so (32-bit, 49MB)
 * Status: DETERMINED
 */

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


/*
 * === REGISTRATION STEP 1: GetControllerInfo (0x1070620) ===
 *
 * BYieldingRegisterSteamController calls 0x1070620 to fill ControllerInfo.
 * The output buffer is at [rbp-0x240] (128+ bytes).
 *
 * Call setup (0x10b3b94-0x10b3bac):
 * 0x10b3b94: mov rdi, r12          ; r12 = [rbp-0x240] (output buffer)
 * 0x10b3b97: call 0x10a4cf0        ; init/prepare output buffer
 * 0x10b3b9c: mov esi, [ebx+0x1d8]  ; slot_index from controller obj
 * 0x10b3ba2: mov rdx, r12          ; output buffer
 * 0x10b3ba5: mov rdi, [ebx+0x1e0]  ; controller sub-object
 * 0x10b3bac: call 0x1070620        ; GetControllerInfo()
 *
 * If successful, the output buffer contains:
 *   [rbp-0x240]: product_id (e.g., 0x1303 for SC2 BLE)
 *   [rbp-0x23c]: secondary_id
 *   [rbp-0x238..0x228]: unique_id (17 bytes)
 *   [rbp-0x224..0x1f4]: identity_data (32+ bytes)
 *   [rbp-0x204..0x1f0]: more identity fields
 *
 * Version check (0x10b3bb9-0x10b3bc5):
 * 0x10b3bb9: mov eax, [ebx+0x1dc]     ; current version from controller
 * 0x10b3bbf: cmp [rbp-0x23c], eax      ; compare with identity secondary_id
 * 0x10b3bc5: jne 0x10b3de0             ; if changed → "controller changed"
 *
 * ; This secondary_id acts as a version/fingerprint.
 * ; If it changes mid-registration, the controller is considered
 * ; to have been replaced (hot-swap, reconnect, etc.)
 */

/*
 * === REGISTRATION STEP 2: Build RPC Request ===
 *
 * After GetControllerInfo succeeds:
 *
 * 0x10b3bcb: lea r13, [rbp-0x2a0]     ; request buffer 1
 * 0x10b3bd2: xor esi, esi
 * 0x10b3bd4: mov rdi, r13
 * 0x10b3bd7: call 0x17f9160           ; Init request object
 *
 * 0x10b3bdc: lea r14, [rbp-0x2c0]     ; request buffer 2
 * 0x10b3be3: xor esi, esi
 * 0x10b3be5: mov rdi, r14
 * 0x10b3be8: call 0x17f91a0           ; Init request object
 *
 * The request objects are built from the identity data:
 * - Controller name string (from output[0x5c])
 * - Product ID (from output[0x00])
 * - Serial/unique ID (from output[0x08])
 * - Transport type (from output[0x3d])
 *
 * Additional data from the controller object:
 * 0x10b3bed: mov rax, [rbp-0x298]     ; read from controller
 * 0x10b3bf4: or dword [rbp-0x290], 1  ; set flags
 * 0x10b3bfb: test al, 3               ; check specific bits
 */

/*
 * === REGISTRATION STEP 3: RPC Call ===
 *
 * AccountHardware.RegisterSteamController#1:
 *
 * 0x10b3d30: add rdi, 0xd60           ; offset to RPC interface
 * 0x10b3d37: mov rax, [rdi]           ; vtable
 * 0x10b3d3a: lea rsi, "AccountHardware.RegisterSteamController#1"
 * 0x10b3d41: mov rcx, r14             ; request data 2
 * 0x10b3d44: mov rdx, r13             ; request data 1
 * 0x10b3d47: mov r8, [rbp-0x2d8]     ; additional context
 * 0x10b3d4e: call [rax+0x28]          ; RPC call
 * 0x10b3d51: test al, al              ; success?
 * 0x10b3d53: mov r12d, eax            ; save result
 * 0x10b3d56: jne 0x10b3f80           ; if success → check version, commit
 *
 * The RPC sends the controller identity to Valve's servers.
 * The server creates/updates the controller record.
 */

/*
 * === REGISTRATION STEP 4: CompleteSteamControllerRegistration ===
 *
 * After RegisterSteamController#1 succeeds:
 *
 * 0x10b3d30: add rdi, 0xd60           ; RPC interface
 * 0x10b3d3a: lea rsi, "AccountHardware.CompleteSteamControllerRegistration#1"
 * 0x10b3d41: mov rcx, r14
 * 0x10b3d44: mov rdx, r13
 * 0x10b3d47: mov r8, [rbp-0x2d8]
 * 0x10b3d4e: call [rax+0x28]          ; RPC call
 * 0x10b3d51: test al, al
 * 0x10b3d56: jne 0x10b3f80           ; if success → commit
 *
 * This finalizes the registration on the server side.
 */

/*
 * === DATA FROM ATT SERVER RESPONSES ===
 *
 * The identity data in the slot comes from the feature report handshake.
 * The ATT server must provide responses that populate the slot fields:
 *
 * 1. Product ID (slot+0x1f8):
 *    - SC2 BLE = 0x1303
 *    - From PnP ID characteristic (Vendor ID Source = 0x02, VID = 0x28DE, PID = 0x1303)
 *
 * 2. Secondary ID (slot+0x1fc):
 *    - Likely a firmware version or board revision
 *    - From Feature Report 0x00 responses
 *
 * 3. Unique ID (slot+0x200, 17 bytes):
 *    - MAC address or serial number
 *    - From serial number characteristic or Feature Report 0x00
 *    - THE READY FLAG: first byte must be non-zero
 *
 * 4. Identity Data (slot+0x214, 32 bytes):
 *    - From 0xf2 capability responses
 *    - Multiple 0xf2 queries return different categories
 *    - The combined responses fill this buffer
 *
 * 5. Transport Type (slot+0x235):
 *    - BLE = 3, USB = 2, Dongle = 4
 *    - Set by the connection handler based on product ID
 *
 * 6. Name String (slot+0x25c):
 *    - Controller name, e.g., "Steam Controller"
 *    - From Device Info Service or hardcoded
 *
 * 7. Calibration Data (slot+0x264+):
 *    - Float values for stick/trigger calibration
 *    - From Feature Report 0x00 responses or hardcoded defaults
 *
 * THE CRITICAL FIELD: Unique ID at slot+0x200
 * The first byte of this field IS the ready flag.
 * If our ATT server doesn't provide a serial number response,
 * this field stays 0, and the zombie check fails.
 */

/*
 * === WHAT OUR ATT SERVER MUST PROVIDE ===
 *
 * For 0x1070620 to return 1, the following must be populated:
 *
 * 1. ✅ Connection state = 1 or 4
 *    - Our raw L2CAP server accepts connections
 *    - Connection is alive (BLE link established)
 *
 * 2. ❌ Slot ready flag (offset 0x200 != 0)
 *    - This is populated by the feature report handshake
 *    - Our synthetic handler responds to GET_ATTRIBUTES and GET_SERIAL
 *    - But the data must reach the slot's internal storage
 *
 * The question: WHAT CODE POPULATES THE SLOT DATA?
 *
 * This happens in the feature report processing code (0x10d4e6c area).
 * When Steam reads Feature Report 0x00, it gets responses that populate
 * the slot fields. Our synthetic handler must provide the RIGHT responses
 * in the RIGHT format.
 *
 * Specifically:
 * - GET_ATTRIBUTES (0x83) → fills identity data
 * - GET_SERIAL → fills unique_id (slot+0x200)
 * - 0xf2 responses → fill capability data
 * - The serial number is the key: it must be non-zero
 */

/*
 * === SYNTHETIC HANDLER vs REAL DATA ===
 *
 * Our current synthetic handler returns:
 * - GET_ATTRIBUTES: hardcoded responses
 * - GET_SERIAL: some serial number
 * - 0xf2: capability responses
 *
 * The issue may be:
 * 1. The serial number format is wrong
 * 2. The 0xf2 responses don't match expected format
 * 3. The slot data isn't being populated because the response
 *    doesn't match what the processing code expects
 *
 * We need to trace WHAT function populates slot+0x200 and
 * WHAT response format it expects.
 */

/*
 * === BINARY REFERENCES ===
 *
 * GetControllerInfo call:     0x10b3bac → 0x1070620
 * Request init:               0x10b3bd7 → 0x17f9160
 * Request init 2:             0x10b3be8 → 0x17f91a0
 * RPC interface:              0x10b3d30 (add rdi, 0xd60)
 * RPC vtable call:            0x10b3d4e (call [rax+0x28])
 * Register method:            0x00b9ba50 ("AccountHardware.RegisterSteamController#1")
 * Complete method:            0x00ce2dc8 ("AccountHardware.CompleteSteamControllerRegistration#1")
 * Controller version field:   [ebx+0x1dc]
 * Controller sub-object:      [ebx+0x1e0]
 * Slot index field:           [ebx+0x1d8]
 */
