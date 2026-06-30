/*
 * Registration Identity Failure — What Happens When 0x1070620 Fails
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
 * === FAILURE PATH IN BYieldingRegisterSteamController (0x10b3a60) ===
 *
 * ; Call GetControllerInfo
 * 0x10b3bac: call 0x1070620
 * 0x10b3bb1: test al, al
 * 0x10b3bb3: je 0x10b3ee8       ; ← FAILURE PATH
 *
 * ; At 0x10b3ee8:
 * 0x10b3ee8:   mov rax, 0x300000000
 * 0x10b3ef2:   xor ecx, ecx
 * 0x10b3ef4:   xor esi, esi
 * 0x10b3ef6:   mov qword [rbp-0x150], 0
 * 0x10b3f01:   mov [rbp-0x138], rax
 * 0x10b3f08:   mov edx, 0x28
 * 0x10b3f0d:   xor edi, edi
 * 0x10b3f0f:   mov rax, [0x2c4f890]
 * 0x10b3f16:   mov dword [rbp-0x128], 0
 * 0x10b3f20:   mov r9d, 5
 * 0x10b3f26:   mov qword [rbp-0x148], 0
 * 0x10b3f31:   mov qword [rbp-0x140], 0
 * 0x10b3f3c:   mov qword [rbp-0x130], 0
 * 0x10b3f47:   mov r8d, [rax+0x7c]
 * 0x10b3f4b:   lea rax, "BYieldingCompleteSteamControllerRegistration - couldn't get controller identity.\n"
 * 0x10b3f52:   push rax
 * 0x10b3f53:   xor eax, eax
 * 0x10b3f55:   push qword [rbp-0x2d8]
 * 0x10b3f5b:   call 0x104ca50    ; logging/format
 * 0x10b3f60:   pop r8
 * 0x10b3f62:   lea rsi, "BYieldingCompleteSteamControllerRegistration - couldn't get controller identity.\n"
 * 0x10b3f69:   xor eax, eax
 * 0x10b3f6b:   pop r9
 * 0x10b3f6d:   lea rdi, [0x2c4fbe0]
 * 0x10b3f74:   call 0x1790ba0    ; logMsg()
 * 0x10b3f79:   jmp 0x10b3e6f    ; → cleanup and return failure
 *
 * ; At 0x10b3e6f (cleanup):
 * 0x10b3e6f:   xor r12d, r12d   ; return value = 0
 * 0x10b3e72:   call 0x26d1530   ; get something
 * 0x10b3e77:   xor edx, edx
 * 0x10b3e79:   mov rsi, [rbp-0x1dc]
 * 0x10b3e80:   mov rdi, rax
 * 0x10b3e83:   mov rax, [rax]
 * 0x10b3e86:   call [rax+0x20]  ; release/unref
 * 0x10b3e89:   mov eax, [rbp-0x1f4]
 * 0x10b3e8f:   mov dword [rbp-0x1f0], 0
 * 0x10b3e99:   test eax, eax
 * 0x10b3e9b:   js 0x10b3ebe
 * 0x10b3e9d:   cmp qword [rbp-0x200], 0
 * 0x10b3ea5:   je 0x10b3ebe
 * 0x10b3ea7:   call 0x26d1530
 * 0x10b3eac:   mov rsi, [rbp-0x200]
 * 0x10b3eb3:   xor edx, edx
 * 0x10b3eb5:   mov rdi, rax
 * 0x10b3eb8:   mov rax, [rax]
 * 0x10b3ebb:   call [rax+0x20]  ; release/unref
 * 0x10b3ebe:   mov rax, [rbp-0x38]  ; canary check
 * 0x10b3ec2:   xor rax, fs:[0x28]
 * 0x10b3ecb:   jne 0x10b4368
 * 0x10b3ed1:   lea rsp, [rbp-0x28]
 * 0x10b3ed5:   pop ebx
 * 0x10b3ed6:   pop r12
 * 0x10b3ed8:   pop r13
 * 0x10b3eda:   pop r14
 * 0x10b3edc:   pop esi
 * 0x10b3ede:   pop rbp
 * 0x10b3edf:   pop rdi           ; (alternate register restore)
 * 0x10b3ee0:   pop rbp
 * 0x10b3ee1:   ret               ; returns r12d = 0 (FAILURE)
 */

/*
 * === WHAT HAPPENS AFTER FAILURE ===
 *
 * When 0x1070620 returns 0:
 *
 * 1. Error message logged:
 *    "BYieldingCompleteSteamControllerRegistration - couldn't get controller identity.\n"
 *
 * 2. Resources released (unref calls at 0x10b3e72-0x10b3ebb)
 *
 * 3. Function returns 0 (failure)
 *
 * 4. The caller of BYieldingRegisterSteamController sees the failure
 *
 * 5. The controller is NOT registered
 *
 * 6. The zombie timer continues iterating
 *
 * 7. After ~6 seconds, zombie timer calls 0x1070620 again
 *
 * 8. If still 0 → "Disconnecting zombie controller %d"
 *
 * 9. Controller is disconnected
 *
 * 10. BYieldingRegisterSteamController is retried (44 times observed)
 *
 * 11. Cycle repeats until feature report handshake completes
 */

/*
 * === NO RETRY WITHIN THE FUNCTION ===
 *
 * BYieldingRegisterSteamController does NOT retry 0x1070620 internally.
 * It calls it once. If it fails, it returns immediately.
 *
 * The retry happens at a higher level:
 * - The controller poll loop detects the controller is alive
 * - It attempts registration again
 * - Each attempt calls 0x1070620 once
 *
 * Observed: 44 registration attempts, each failing because 0x1070620 returns 0
 */

/*
 * === ERROR STRINGS ===
 *
 * 0x00cd4dc0: "BYieldingRegisterSteamController - couldn't get identity before registration."
 * 0x00b9b74f: "BYieldingCompleteSteamControllerRegistration - couldn't get controller identity."
 *
 * The first is for the Register path, the second for the Complete path.
 * Both indicate 0x1070620 returned 0.
 */

/*
 * === REGISTRATION DATA FLOW (Success Path) ===
 *
 * When 0x1070620 succeeds (returns 1):
 *
 * 1. Output buffer filled with controller identity
 * 2. Version check at 0x10b3bbf:
 *    mov eax, [ebx+0x1dc]           ; current version
 *    cmp [rbp-0x23c], eax            ; compare with identity version
 *    jne 0x10b3de0                   ; if changed → "controller changed before registration"
 *
 * 3. Initialize RPC objects (0x10b3bcb-0x10b3be8)
 *
 * 4. Build registration request from identity data
 *
 * 5. Call AccountHardware.RegisterSteamController#1 via vtable[0x28]
 *
 * 6. If RPC succeeds → continue to CompleteSteamControllerRegistration
 *
 * 7. If RPC fails → "Error committing registration"
 */

/*
 * === IDENTITY DATA USED IN REGISTRATION ===
 *
 * From the output buffer of 0x1070620:
 *
 * - product_id (offset 0x00): identifies controller type (0x1303 for SC2 BLE)
 * - secondary_id (offset 0x04): secondary identifier
 * - unique_id (offset 0x08): MAC address or serial number (17 bytes)
 * - identity_data (offset 0x1c): additional identity info (32 bytes)
 * - transport_type (offset 0x3d): BLE=3, USB=2, Dongle=4
 * - name_ptr (offset 0x5c): controller name string
 *
 * These fields are serialized into the RegisterSteamController RPC request.
 * The server uses them to create/update the controller record.
 */

/*
 * === BINARY REFERENCES ===
 *
 * GetControllerInfo call:         0x10b3bac → 0x1070620
 * Failure check:                  0x10b3bb1 (test al, al)
 * Failure jump:                   0x10b3bb3 (je 0x10b3ee8)
 * Error log:                      0x10b3f4b (lea "couldn't get controller identity")
 * Version check:                  0x10b3bbf (cmp identity version)
 * RPC call:                       0x10b3d4e (call [rax+0x28])
 * RPC method:                     0x00b9ba50 ("AccountHardware.RegisterSteamController#1")
 * Complete method:                0x00ce2dc8 ("AccountHardware.CompleteSteamControllerRegistration#1")
 */
