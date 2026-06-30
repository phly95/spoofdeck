/*
 * 0x1070620 — Controller Identity Check (GetControllerInfo)
 *
 * Binary: ~/.steam/debian-installation/ubuntu12_32/steamclient.so (32-bit, 49MB)
 * Function VA: 0x1070620
 * Status: DETERMINED
 *
 * This function is BOTH:
 *   1. The identity gate for BYieldingRegisterSteamController (called at 0x10b3bac)
 *   2. The zombie check function (called at 0x1072106 from slot iterator)
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
 * === FUNCTION SIGNATURE ===
 *
 * bool GetControllerInfo(
 *     void* controller_obj,     // rdi → saved as r12
 *     int   slot_index,         // esi → saved as ebp (0-15, max 0xf)
 *     ControllerInfo* output    // rdx → saved as ebx
 * );
 *
 * Returns: 1 = success (slot has valid controller identity)
 *          0 = failure (no controller, not ready, or invalid state)
 */

/*
 * === DISASSEMBLY WALKTHROUGH ===
 *
 * ; === PROLOGUE ===
 * 0x1070620: push esi
 * 0x1070622: push r14          ; will hold return value (0 or 1)
 * 0x1070624: push r13
 * 0x1070626: push r12          ; r12 = controller_obj
 * 0x1070628: push rbp
 * 0x1070629: mov ebp, esi      ; ebp = slot_index
 * 0x107062b: push ebx
 * 0x107062c: mov ebx, rdx      ; ebx = output buffer
 * 0x107062f: sub rsp, 0x58
 *
 * ; === CHECK 1: Bounds check (slot_index <= 15) ===
 * 0x1070641: xor eax, eax      ; eax = 0 (default return)
 * 0x1070643: cmp ebp, 0xf      ; slot > 15?
 * 0x1070646: ja 0x10706b4      ; → FAILURE (clear output, return 0)
 *
 * ; === CHECK 2: Vtable validation ===
 * 0x1070648: mov rax, [rdi]    ; rax = controller_obj->vtable
 * 0x107064b: lea rdx, [0x104e5e0]  ; expected vtable function at offset 0x60
 * 0x1070652: mov r12, rdi      ; r12 = controller_obj
 * 0x1070655: mov rax, [rax+0x60]  ; rax = vtable[0x60]
 * 0x1070659: cmp rax, rdx      ; must match 0x104e5e0
 * 0x107065c: jne 0x1070860     ; → alternate path (calls through vtable)
 *
 * ; === CHECK 3: Flag byte (alternate connection path) ===
 * 0x1070662: cmp byte [rdi+0x1091fd], 0
 * 0x1070669: jne 0x1070850     ; if flag set, use [rdi+0x180] as connection
 *
 * ; === CHECK 4: Connection object exists ===
 * 0x107066f: mov r8, [rdi+0x190]  ; r8 = connection object
 * 0x1070676: test r8, r8
 * 0x1070679: je 0x10706b4      ; → FAILURE if NULL
 *
 * ; === CHECK 5: Query connection state via vtable ===
 * 0x107067b: xor eax, eax
 * 0x107067d: mov ecx, 6
 * 0x1070682: xor r9d, r9d
 * 0x1070685: lea rdi, [rsp+0x10]  ; stack buffer for state query
 * 0x107068a: rep stosq          ; zero-fill 48 bytes (6 qwords)
 * 0x107068d: lea rsi, [rsp+0x10]
 * 0x1070692: mov word [rdi], r9w ; first word = 0
 * 0x1070696: mov rax, [r8]       ; rax = connection->vtable
 * 0x1070699: mov rdi, r8         ; rdi = connection object
 * 0x107069c: call [rax+0x18]     ; CONNECTION_VTABLE[0x18](connection, state_buf)
 *                                 ; → fills state_buf with per-slot connection states
 *
 * ; === CHECK 6: Read state for our slot ===
 * 0x107069f: movzx eax, byte [rsp + rbp + 0x10]  ; state_buf[slot_index]
 * 0x10706a4: cmp al, 1          ; state == 1? (connected)
 * 0x10706a6: je 0x107086e       ; → SUCCESS path
 * 0x10706ac: cmp al, 4          ; state == 4? (also valid)
 * 0x10706ae: je 0x107086e       ; → SUCCESS path
 *
 * ; Fall through to FAILURE
 *
 * ; === FAILURE PATH (0x10706b4) ===
 * ; Zeroes the entire output buffer with default values:
 * ;   [ebx+0x00..0x18] = 0
 * ;   [ebx+0x1c..0x3c] = 0
 * ;   [ebx+0x50] = 0
 * ;   [ebx+0x58] = 0
 * ;   [ebx+0x64] = "#SettingsController_SteamController" (string init)
 * ;   [ebx+0x6c] = 0x3f8000003f800000 (1.0f, 1.0f)
 * ;   [ebx+0x74] = -1 (all bits set)
 * ;   [ebx+0x80] = 0x7f7fffff7f7fffff (max floats)
 * ;   [ebx+0xa4] = 0x5ffffffff (max values)
 * ;   etc.
 * ; Returns 0 (r14d was NOT set to 1)
 *
 * ; === ALTERNATE VTABLE PATH (0x1070860) ===
 * ; When vtable[0x60] != 0x104e5e0:
 * 0x1070860: xor edx, edx
 * 0x1070862: mov esi, ebp       ; slot_index
 * 0x1070864: call rax           ; call vtable[0x60](controller, slot, 0)
 * 0x1070866: test al, al
 * 0x1070868: je 0x10706b4      ; → FAILURE if returned false
 * ; Falls through to SUCCESS path
 *
 * ; === ALTERNATE CONNECTION PATH (0x1070850) ===
 * 0x1070850: mov r8, [rdi+0x180]  ; use offset 0x180 instead of 0x190
 * 0x1070857: jmp 0x1070676        ; continue with connection check
 *
 * ; === SUCCESS PATH (0x107086e) ===
 * 0x107086e: imul r13, rbp, 0xe8  ; r13 = slot_index * 0xe8 (slot stride)
 * 0x1070875: xor r14d, r14d       ; r14d = 0 (will be set to 1 if slot ready)
 * 0x1070878: lea esi, [r12+0x198] ; esi = mutex (at controller+0x198)
 * 0x1070880: mov rdi, esi
 * 0x1070883: call 0xd8ae80        ; LOCK mutex
 *
 * ; === CHECK 7: Slot ready flag ===
 * 0x1070888: lea rax, [r12+r13]  ; rax = controller + slot*0xe8
 * 0x107088c: cmp byte [rax+0x200], 0  ; READY FLAG at slot+0x200
 * 0x1070893: jne 0x10708a0       ; if non-zero → slot is READY, copy data
 * 0x1070895: mov rdi, esi
 * 0x1070898: call 0xd8b090       ; UNLOCK mutex
 * 0x107089d: jmp 0x1070820      ; → return 0 (slot NOT ready yet)
 *
 * ; === DATA COPY (0x10708a0) ===
 * ; Copies controller identity from internal slot data to output buffer:
 * ;   output[0x00] = slot_data[0x1f8]  (dword - product_id)
 * ;   output[0x04] = slot_data[0x1fc]  (dword - secondary_id)
 * ;   output[0x08..0x18] = slot_data[0x200..0x210] (17 bytes - unique_id/serial)
 * ;   output[0x1c..0x3c] = slot_data[0x214..0x234] (32+ bytes - identity data)
 * ;   output[0x3c] = slot_data[0x234] (byte - capability flags)
 * ;   output[0x3d] = slot_data[0x235] (byte - transport type)
 * ;   output[0x40..0x50] = slot_data[0x238..0x248] (pointer + count)
 * ;   output[0x58] = slot_data[0x250] (dword - mode)
 * ;   output[0x5c] = slot_data[0x254] (qword - name_ptr)
 * ;   output[0x64..] = slot_data[0x25c+] (string + calibration data)
 *
 * ; After copy, unlock mutex and set success:
 * 0x1070a54: mov r14d, 1         ; ← RETURN VALUE = 1 (SUCCESS)
 * 0x1070a51: mov rdi, esi
 * ; ... more data copy ...
 * ; Eventually: unlock mutex, return r14d (which is 1)
 */

/*
 * === OUTPUT BUFFER LAYOUT (ControllerInfo) ===
 *
 * Offset  Size  Field              Source
 * ------  ----  -----              ------
 * 0x00    4     product_id         slot_data[0x1f8] (dword)
 * 0x04    4     secondary_id       slot_data[0x1fc] (dword)
 * 0x08    17    unique_id          slot_data[0x200..0x210] (bytes)
 * 0x19    3     padding            slot_data[0x211..0x213]
 * 0x1c    32    identity_data      slot_data[0x214..0x234] (bytes)
 * 0x3c    1     capability_flags   slot_data[0x234] (byte)
 * 0x3d    1     transport_type     slot_data[0x235] (byte)
 * 0x40    8     name_array_ptr     slot_data[0x238] (qword)
 * 0x48    4     name_array_count   slot_data[0x240] (dword)
 * 0x4c    4     name_array_cap     slot_data[0x244] (dword)
 * 0x50    4     field_50           slot_data[0x248] (dword)
 * 0x54    4     padding
 * 0x58    4     mode               slot_data[0x250] (dword)
 * 0x5c    8     name_ptr           slot_data[0x254] (qword, string)
 * 0x64    26    settings_string    "#SettingsController_SteamController"
 * 0x7c    2     field_7c           slot_data[0x274] (word)
 * 0x7e    1     field_7e           slot_data[0x276] (byte)
 * 0x80    4     float_field_1      slot_data[0x278] (float)
 * 0x84    4     float_field_2      slot_data[0x27c] (float)
 * 0x88    1     field_88           slot_data[0x280] (byte)
 * 0x8c    4     float_field_3      slot_data[0x284] (float)
 * 0x90    4     float_field_4      slot_data[0x288] (float)
 * 0x94    12    vector_field       slot_data[0x28c..0x298] (3x int32)
 * 0xa0    4     field_a0           slot_data[0x298] (dword)
 * 0xa4    4     field_a4           slot_data[0x29c] (dword)
 * 0xa8    4     field_a8           slot_data[0x2a0] (dword)
 * 0xac    4     field_ac           slot_data[0x2a4] (dword)
 * 0xb0    4     float_field_5      slot_data[0x2a8] (float)
 * 0xb4    4     float_field_6      slot_data[0x2ac] (float)
 * ... (more fields)
 */

/*
 * === CONTROLLER SLOT STRUCTURE ===
 *
 * Controller object has 16 slots (indices 0-15).
 * Each slot occupies 0xe8 bytes.
 * Slot N base address = controller_obj + N * 0xe8
 *
 * Within each slot, the useful data starts at offset 0x1f8:
 *   +0x1f8: product_id (dword)
 *   +0x1fc: secondary_id (dword)
 *   +0x200: unique_id (17 bytes) — THIS IS THE READY FLAG BYTE
 *   +0x214: identity data (32+ bytes)
 *   +0x235: transport type
 *   +0x250..0x2ac: calibration/config floats and integers
 *
 * Ready flag: byte at [controller + slot*0xe8 + 0x200]
 *   0 = slot NOT ready (feature report handshake incomplete)
 *   non-zero = slot READY (controller identity populated)
 *
 * The ready flag byte IS the first byte of the unique_id field.
 * When the feature report handshake completes, the first byte of
 * the unique_id is written (non-zero), making the slot "ready".
 */

/*
 * === CRITICAL IMPLICATION ===
 *
 * For 0x1070620 to return 1 (success), TWO conditions must be met:
 *
 * 1. CONNECTION STATE must be 1 or 4
 *    - The connection object at [controller+0x190] must exist
 *    - Its vtable[0x18] must report state 1 or 4 for our slot
 *    - This checks if the BLE/USB connection is alive
 *
 * 2. SLOT READY FLAG must be non-zero
 *    - Byte at [controller + slot*0xe8 + 0x200] must be non-zero
 *    - This checks if the feature report handshake completed
 *    - The handshake includes GET_ATTRIBUTES, serial read, 0xf2 responses
 *
 * If EITHER condition fails, the function returns 0 (failure).
 *
 * THE ZOMBIE TIMER calls this function periodically.
 * If the feature report handshake doesn't complete within ~6 seconds,
 * the zombie timer fires, calls 0x1070620, gets 0, and disconnects.
 *
 * THIS IS THE REAL REGISTRATION BLOCKER.
 * The feature report handshake must complete BEFORE the zombie timer fires.
 */

/*
 * === XREFS ===
 *
 * Called from:
 *   0x10b3bac (BYieldingRegisterSteamController) — registration identity check
 *   0x1072106 (slot iterator / zombie check) — zombie disconnect decision
 *
 * The same function serves both purposes:
 *   - Registration: "can I register this controller?"
 *   - Zombie check: "is this controller still alive?"
 */
