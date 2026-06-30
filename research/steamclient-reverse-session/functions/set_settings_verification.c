/*
 * SET_SETTINGS 0x09 Verification Path — COMPLETE ANALYSIS
 *
 * Binary: ~/.steam/debian-installation/ubuntu12_32/steamclient.so (32-bit, 49MB)
 * Status: DETERMINED
 *
 * Addresses corrected from previous sessions:
 * - 0x014fd614 [32-bit: NEEDS RE-ANALYSIS] is NOT `mov al, 0x87` — it's `movzx esi, byte [rax+0x87]`
 *   (reads command byte from struct, not loads immediate)
 * - 0x014fd620 [32-bit: NEEDS RE-ANALYSIS] is the same pattern (re-read after conditional store)
 * - The actual verification is in the state manager at 0x010d466b [32-bit: NEEDS RE-ANALYSIS]
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
 * === EXECUTIVE SUMMARY ===
 *
 * The SET_SETTINGS 0x09 verification works as follows:
 *
 * 1. Settings are queued as 16-byte entries in an array at [esi+0xc0]
 * 2. The state manager iterates through pending settings
 * 3. For each setting, it SENDS the feature report via vtable[0x10]
 * 4. Then READS BACK via vtable[0x130] (get_feature_report)
 * 5. The response bytes are compared against expected values
 * 6. On mismatch, the setting is retried after a 3-second timeout
 * 7. On success, the pending flag is cleared
 *
 * The verification does NOT check the full 64-byte FR 0x00 response.
 * It checks specific bytes at specific offsets in the response buffer.
 */

/*
 * === CORRECTED ADDRESSES ===
 *
 * Previous sessions identified these as `mov al, 0x87`:
 *   0x014fd614 [32-bit: NEEDS RE-ANALYSIS]  →  Actually: movzx esi, byte [rax+0x87]  (READ from struct)
 *   0x014fd620 [32-bit: NEEDS RE-ANALYSIS]  →  Actually: movzx esi, byte [rax+0x87]  (RE-READ after conditional)
 *   0x014fdf44 [32-bit: NEEDS RE-ANALYSIS]  →  Actually: movzx esi, byte [rax+0x87]  (READ from struct)
 *   0x014fdf50 [32-bit: NEEDS RE-ANALYSIS]  →  Actually: movzx esi, byte [rax+0x87]  (RE-READ after conditional)
 *
 * These are in a device enumeration/string lookup function, NOT the SET_SETTINGS
 * send path. The 0x87 is a STRUCT FIELD OFFSET, not an immediate value.
 *
 * The actual SET_SETTINGS send and verification are in the state manager at:
 *   0x010d466b [32-bit: NEEDS RE-ANALYSIS]  — main state manager entry
 *   0x010d4e14 [32-bit: NEEDS RE-ANALYSIS]  — send feature report (vtable[0x10])
 *   0x010d4e83 [32-bit: NEEDS RE-ANALYSIS]  — read back FR 0x00 (vtable[0x130])
 *   0x010d4dc6 [32-bit: NEEDS RE-ANALYSIS]  — byte comparison loop
 */

/*
 * === STATE MANAGER STRUCTURE (at esi) ===
 *
 * Offset   Size   Description
 * +0xc0    8      Settings array pointer (16-byte entries)
 * +0xd0    4      Settings count
 * +0xdc    4      Expected byte count / size
 * +0xe0    1      State flag byte (toggle)
 * +0xe1    1      VERIFY STATE BYTE (0 or 1)
 * +0xe4    4      Current index / error code
 * +0xe8    8      State pointer (cleared to 0 on retry)
 * +0xa8    8      Timing data pointer
 * +0xb8    4      Array count for iteration
 * +0x128   8      Vtable pointer 1 (compared to 0x010cdde0 [32-bit: NEEDS RE-ANALYSIS])
 * +0x150   8      Vtable pointer 2 (compared to 0x010cea50 [32-bit: NEEDS RE-ANALYSIS])
 * +0x178   4      State field
 * +0x198   4      Feature report ID for get_feature_report
 * +0x1f8   1      Flag byte
 * +0x17c   1      PENDING SETTINGS FLAG (controls verify path)
 *
 * The verify state byte at +0xe1 toggles between 0 and 1:
 *   0 = "read back" mode (verify previous send)
 *   1 = "send" mode (send next setting)
 */

/*
 * === SETTINGS ARRAY ENTRIES (16 bytes each at [esi+0xc0]) ===
 *
 * Offset  Size  Description
 * +0x00   1     Active flag (1=active, 0=inactive)
 * +0x01   7     Padding
 * +0x08   8     Timeout/timestamp (double)
 *
 * The register ID and value are NOT stored in the 16-byte entry.
 * They are derived from the verify state and passed to the vtable calls.
 */

/*
 * === COMPLETE VERIFICATION FLOW ===
 *
 * STEP 1: Check if settings are pending
 *   0x0123e5fb: cmp byte [esi+0x17c], 0    ; any pending settings?
 *   0x010d4da8 [32-bit: NEEDS RE-ANALYSIS]: movzx eax, byte [esi+0xe1]  ; load verify state
 *   0x010d4db0 [32-bit: NEEDS RE-ANALYSIS]: je 0x10d4fd0                ; if no pending, go to byte check
 *
 * STEP 2: Toggle verify state
 *   0x010d4db6 [32-bit: NEEDS RE-ANALYSIS]: mov r12d, eax               ; save current state
 *   0x010d4db9 [32-bit: NEEDS RE-ANALYSIS]: xor r12d, 1                 ; toggle: 0→1, 1→0
 *   0x010d4dbd [32-bit: NEEDS RE-ANALYSIS]: cmp r12b, al                ; compare toggled vs current
 *   0x010d4dc0 [32-bit: NEEDS RE-ANALYSIS]: je 0x10d4fe5                ; if same (impossible), skip
 *
 * STEP 3: SEND (when state toggles to 1)
 *   0x010d4e11 [32-bit: NEEDS RE-ANALYSIS]: mov rdi, [rax]              ; load HID device
 *   0x010d4e14 [32-bit: NEEDS RE-ANALYSIS]: call qword [rax+0x10]       ; SEND FEATURE REPORT
 *   0x010d4e17 [32-bit: NEEDS RE-ANALYSIS]: test r12b, r12b             ; check which state
 *   0x010d4e1a [32-bit: NEEDS RE-ANALYSIS]: mov byte [esi+0xe1], r12b   ; store new state
 *   0x010d4e24 [32-bit: NEEDS RE-ANALYSIS]: jne 0x10d4e6c               ; if state=1, go to verify
 *
 * STEP 4: READ BACK (when state toggles to 0)
 *   0x010d4e75 [32-bit: NEEDS RE-ANALYSIS]: mov rax, [r13]              ; load protocol vtable
 *   0x010d4e7c [32-bit: NEEDS RE-ANALYSIS]: mov esi, [esi+0x198]        ; feature report ID
 *   0x010d4e83 [32-bit: NEEDS RE-ANALYSIS]: call qword [rax+0x130]      ; GET FEATURE REPORT (FR 0x00)
 *
 * STEP 5: Compute retry count from return value
 *   0x010d4e89 [32-bit: NEEDS RE-ANALYSIS]: pxor xmm0, xmm0
 *   0x010d4e8d [32-bit: NEEDS RE-ANALYSIS]: cvtsi2ss xmm0, eax          ; convert return value to float
 *   0x010d4e91 [32-bit: NEEDS RE-ANALYSIS]: divss xmm0, [0x00c84180]    ; divide by constant A
 *   0x010d4e99 [32-bit: NEEDS RE-ANALYSIS]: mulss xmm0, [0x00c820bc]    ; multiply by constant B
 *   0x010d4ea1 [32-bit: NEEDS RE-ANALYSIS]: cvttss2si edx, xmm0         ; truncate to int
 *   0x010d4ea5 [32-bit: NEEDS RE-ANALYSIS]: test edx, edx               ; retry count > 0?
 *   0x010d4ea7 [32-bit: NEEDS RE-ANALYSIS]: jle 0x10d4f01               ; if ≤ 0, skip retry
 *
 * STEP 6: Byte comparison loop
 *   0x010d4fd0 [32-bit: NEEDS RE-ANALYSIS]: mov rdx, [esi+0xc0]         ; load settings array
 *   0x010d4fd7 [32-bit: NEEDS RE-ANALYSIS]: movzx r12d, byte [rdx+ebx]  ; read response byte
 *   0x010d4fdc [32-bit: NEEDS RE-ANALYSIS]: cmp r12b, al                ; compare with expected
 *   0x010d4fdf [32-bit: NEEDS RE-ANALYSIS]: jne 0x10d4dc6               ; MISMATCH → retry
 *
 * STEP 7: Success
 *   0x010d4fe5 [32-bit: NEEDS RE-ANALYSIS]: xor r12d, r12d              ; r12d = 0 (success)
 *   0x010d4feb [32-bit: NEEDS RE-ANALYSIS]: jne 0x10d4e75               ; if more data, loop
 *
 * STEP 8: Clear pending flag
 *   0x010d50ba [32-bit: NEEDS RE-ANALYSIS]: test r12b, r12b
 *   0x010d50bd [32-bit: NEEDS RE-ANALYSIS]: mov byte [esi+0xe1], r12b    ; store verify result
 *   0x010d50c4 [32-bit: NEEDS RE-ANALYSIS]: je 0x10d4e2d                ; if 0, loop back
 *
 * STEP 9: Failure/timeout
 *   0x010d5100 [32-bit: NEEDS RE-ANALYSIS]: mov esi, 1                   ; return error
 *   0x010d5105 [32-bit: NEEDS RE-ANALYSIS]: jmp 0x10d4e6c                ; exit
 *   0x010d5174 [32-bit: NEEDS RE-ANALYSIS]: mov qword [esi+0xe8], 0      ; clear state
 *   0x010d517f [32-bit: NEEDS RE-ANALYSIS]: jmp 0x10d4c96                ; restart
 */

/*
 * === WHAT THE VERIFICATION CHECKS ===
 *
 * The FR 0x00 response format (from SDL3 source):
 *
 *   Byte 0:   Report ID (0x01 for host->device commands)
 *   Byte 1:   FeatureReportHeader.type (command byte, 0x87 for SET_SETTINGS)
 *   Byte 2:   FeatureReportHeader.length (payload length)
 *   Byte 3:   settingNum (register ID, e.g., 0x09 for lizard mode)
 *   Byte 4-5: settingValue (uint16 LE, e.g., 0x0000 for OFF)
 *   Bytes 6-63: padding
 *
 * The verification at 0x010d4dc6 [32-bit: NEEDS RE-ANALYSIS]-0x010d4fdf [32-bit: NEEDS RE-ANALYSIS] checks:
 *
 *   1. The RESPONSE BYTE at [rdx+ebx] matches the EXPECTED VALUE in al
 *   2. This is a byte-by-byte comparison loop
 *   3. The expected values are loaded from the settings state
 *   4. On mismatch (jne 0x10d4dc6), the setting is retried
 *
 * The expected response for SET_SETTINGS 0x09 (lizard mode OFF):
 *
 *   Byte 1: 0x87 (command echo — SET_SETTINGS)
 *   Byte 2: 0x03 (length echo — 3 bytes per setting)
 *   Byte 3: 0x09 (register echo — lizard mode)
 *   Byte 4: 0x00 (value low byte — OFF)
 *   Byte 5: 0x00 (value high byte)
 *
 * However, the verification does NOT check all bytes. It checks
 * specific bytes at specific offsets, determined by the iteration
 * index (ebx) and the expected value (al).
 */

/*
 * === KEY INSIGHT: THE VERIFICATION IS NOT A FULL BUFFER COMPARISON ===
 *
 * The code at 0x010d4dc6 [32-bit: NEEDS RE-ANALYSIS]-0x010d4fdf [32-bit: NEEDS RE-ANALYSIS] is a LOOP that checks individual
 * bytes, not a memcmp of the entire 64-byte buffer. The loop:
 *
 *   1. Loads a response byte from [rdx+ebx]
 *   2. Compares it with an expected value in al
 *   3. On mismatch, retries the setting
 *   4. On match, advances to the next byte
 *
 * The expected values are NOT hardcoded in .rodata. They are computed
 * from the settings state and passed through registers. This means:
 *
 * - The verification checks that the controller ECHOED the command
 * - It does NOT check a fixed "golden pattern"
 * - The expected values are the same bytes that were SENT
 * - The verification is: "did the controller accept and echo back
 *   the setting we just sent?"
 */

/*
 * === TIMEOUT AND RETRY ===
 *
 * The 3-second timeout (0x2DC6C0 = 3,000,000 µs) is used in:
 *   0x01f84306 [32-bit: NEEDS RE-ANALYSIS]: cmp rax, 0x2dc6c0    ; compare elapsed time with 3s
 *   0x01f8430c [32-bit: NEEDS RE-ANALYSIS]: cmovg rax, rdx       ; clamp to max
 *
 * The retry count is computed from the get_feature_report return value:
 *   return_value / constant_A * constant_B = retry_count
 *
 * If retry_count > 0 AND we're in send state, the loop continues.
 * If retry_count ≤ 0, the loop exits (timeout or success).
 *
 * The timer at 0x02a04238 [32-bit: NEEDS RE-ANALYSIS] also uses 0x2DC6C0 for a 3-second timeout.
 */

/*
 * === VTABLE TYPE CHECKS ===
 *
 * The state manager verifies vtable pointers before proceeding:
 *
 *   0x010d4c50 [32-bit: NEEDS RE-ANALYSIS]: lea rcx, [0x010cdde0 [32-bit: NEEDS RE-ANALYSIS]]    ; expected vtable type 1
 *   0x010d4c60 [32-bit: NEEDS RE-ANALYSIS]: cmp rdx, rcx              ; verify
 *   0x010d4c63 [32-bit: NEEDS RE-ANALYSIS]: jne 0x10d52b4             ; mismatch → error
 *
 *   0x010d4c70 [32-bit: NEEDS RE-ANALYSIS]: lea rdx, [0x010cdd90 [32-bit: NEEDS RE-ANALYSIS]]    ; expected vtable type 2
 *   0x010d4c7a [32-bit: NEEDS RE-ANALYSIS]: cmp rax, rdx              ; verify
 *   0x010d4c7d [32-bit: NEEDS RE-ANALYSIS]: jne 0x10d52c3             ; mismatch → error
 *
 *   0x010d4eb3 [32-bit: NEEDS RE-ANALYSIS]: lea rdi, [0x010cde90 [32-bit: NEEDS RE-ANALYSIS]]    ; expected protocol handler
 *   0x010d4ece [32-bit: NEEDS RE-ANALYSIS]: cmp rax, rdi              ; verify
 *   0x010d4ed1 [32-bit: NEEDS RE-ANALYSIS]: jne 0x10d5238             ; mismatch → error
 *
 *   0x010d500b [32-bit: NEEDS RE-ANALYSIS]: lea rdx, [0x010cea50 [32-bit: NEEDS RE-ANALYSIS]]    ; expected vtable type 3
 *   0x010d5019 [32-bit: NEEDS RE-ANALYSIS]: cmp rax, rdx              ; verify
 *   0x010d501c [32-bit: NEEDS RE-ANALYSIS]: jne 0x10d5260             ; mismatch → error
 *
 * These checks ensure the HID device and protocol handler are valid
 * before sending/receiving feature reports.
 */

/*
 * === PROTOCOL HANDLER CHAIN ===
 *
 * From the string table at 0x02ae1ac8 [32-bit: NEEDS RE-ANALYSIS]:
 *
 *   0x02ae1ae0 [32-bit: NEEDS RE-ANALYSIS]: "IControllerVirtualSocket"           (base interface)
 *   0x02ae1af0 [32-bit: NEEDS RE-ANALYSIS]: "CControllerHidVirtualSocket"        (HID transport)
 *   0x02ae1b08 [32-bit: NEEDS RE-ANALYSIS]: "CSteamControllerProtocolHandlerV1"  (V1 protocol)
 *   0x02ae1b20 [32-bit: NEEDS RE-ANALYSIS]: "CSteamControllerProtocolHandlerV2"  (V2 protocol)
 *   0x02ae1b38 [32-bit: NEEDS RE-ANALYSIS]: "CGenericControllerProtocolHandler"  (generic fallback)
 *
 * The V1 protocol handler at 0x02ae1b08 [32-bit: NEEDS RE-ANALYSIS] has vtable at 0x02c06aa8 [32-bit: NEEDS RE-ANALYSIS].
 * The state manager verifies the handler against 0x010cde90 [32-bit: NEEDS RE-ANALYSIS] and 0x010cdce0 [32-bit: NEEDS RE-ANALYSIS].
 */

/*
 * === BINARY REFERENCES ===
 *
 * State manager: 0x010d466b [32-bit: NEEDS RE-ANALYSIS]
 * Send feature report: 0x010d4e14 [32-bit: NEEDS RE-ANALYSIS] (vtable[0x10])
 * Get feature report: 0x010d4e83 [32-bit: NEEDS RE-ANALYSIS] (vtable[0x130])
 * Byte comparison loop: 0x010d4dc6 [32-bit: NEEDS RE-ANALYSIS]-0x010d4fdf [32-bit: NEEDS RE-ANALYSIS]
 * Timeout comparison: 0x01f84306 [32-bit: NEEDS RE-ANALYSIS] (0x2DC6C0 = 3s)
 * Timer start: 0x02a04238 [32-bit: NEEDS RE-ANALYSIS] (0x2DC6C0 = 3s)
 * Settings init: 0x0112daf0 [32-bit: NEEDS RE-ANALYSIS]
 * Settings queue: 0x010d5488 [32-bit: NEEDS RE-ANALYSIS]
 * Vtable type checks: 0x010cdde0 [32-bit: NEEDS RE-ANALYSIS], 0x010cdd90 [32-bit: NEEDS RE-ANALYSIS], 0x010cde90 [32-bit: NEEDS RE-ANALYSIS], 0x010cea50 [32-bit: NEEDS RE-ANALYSIS]
 * Protocol handler vtable: 0x02c06aa8 [32-bit: NEEDS RE-ANALYSIS]
 *
 * String references:
 * "toggle_lizard" at 0x00ca6b5d (in URI string)
 * "CSteamControllerProtocolHandlerV1" at 0x02ae1b08 [32-bit: NEEDS RE-ANALYSIS]
 * "CWriteFeatureReportWorkItem" RTTI at 0x00aa1880
 */

/*
 * === FR 0x00 RESPONSE FORMAT (from SDL3 source) ===
 *
 * For SET_SETTINGS, the FR 0x00 response echoes the command:
 *
 *   Byte 0:   0x01 (report ID)
 *   Byte 1:   0x87 (ID_SET_SETTINGS_VALUES)
 *   Byte 2:   0x03 (length = 1 × sizeof(ControllerSetting) = 3)
 *   Byte 3:   settingNum (e.g., 0x09 for lizard mode)
 *   Byte 4:   settingValue low byte (e.g., 0x00 for OFF)
 *   Byte 5:   settingValue high byte (e.g., 0x00)
 *   Bytes 6-63: 0x00 (padding)
 *
 * For SET_SETTINGS 0x09 (lizard mode OFF), the expected response:
 *
 *   01 87 03 09 00 00 00 00 00 00 00 00 00 00 00 00
 *   00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
 *   00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
 *   00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
 *
 * The verification checks that bytes 1-5 match the sent command.
 * If any byte doesn't match, the setting is retried after 3 seconds.
 */

/*
 * === SUCCESS CONDITION ===
 *
 * Verification SUCCEEDS when:
 *   1. The FR 0x00 response bytes match the expected values
 *   2. The byte comparison loop completes without mismatch
 *   3. r12d is set to 0 (success) at 0x010d4fe5 [32-bit: NEEDS RE-ANALYSIS]
 *   4. The verify state byte [esi+0xe1] is cleared
 *   5. The pending flag [esi+0x17c] is cleared
 *   6. The state machine moves to the next setting
 *
 * Verification FAILS when:
 *   1. A response byte doesn't match (jne at 0x010d4fdf [32-bit: NEEDS RE-ANALYSIS])
 *   2. The retry count exceeds the limit
 *   3. The timeout expires (3 seconds)
 *   4. A vtable type check fails
 *   5. The HID device returns an error
 *
 * On failure:
 *   - The setting remains pending
 *   - The retry timer is started (3 seconds)
 *   - After timeout, the setting is retried
 *   - No explicit retry count limit (retries indefinitely)
 */
