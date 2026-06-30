/*
 * Verify Branch Analysis — What Prevents VERIFY for SET_SETTINGS?
 *
 * Binary: ~/.steam/debian-installation/ubuntu12_32/steamclient.so (32-bit, 49MB)
 * Status: DETERMINED
 */

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


/*
 * === EXECUTIVE SUMMARY ===
 *
 * The VERIFY step (vtable[0x130] = get_feature_report) is prevented
 * by the NULL check at 0x010d4e6c [32-bit: NEEDS RE-ANALYSIS]:
 *
 *   0x010d4e6c [32-bit: NEEDS RE-ANALYSIS]: test r13, r13
 *   0x010d4e6f [32-bit: NEEDS RE-ANALYSIS]: je 0x10d4ff1       ; skip verify if r13==NULL
 *
 * For SET_SETTINGS: r13 is NULL → verify SKIPPED
 * For GET_ATTRIBUTES: r13 is non-NULL → verify HAPPENS
 *
 * The state machine is command-agnostic. The difference is not in
 * the state machine itself, but in what the CALLER passes as r13.
 */

/*
 * === THE TWO PATHS ===
 *
 * PATH A: With verify object (r13 != NULL) — used by GET_ATTRIBUTES
 *
 *   0x010d4e6c [32-bit: NEEDS RE-ANALYSIS]: test r13, r13          ; r13 != NULL
 *   0x010d4e6f [32-bit: NEEDS RE-ANALYSIS]: je 0x10d4ff1           ; NOT taken
 *   0x010d4e75 [32-bit: NEEDS RE-ANALYSIS]: mov rax, [r13]         ; load vtable
 *   0x010d4e79 [32-bit: NEEDS RE-ANALYSIS]: mov rdi, r13           ; this = r13
 *   0x010d4e7c [32-bit: NEEDS RE-ANALYSIS]: mov esi, [esi+0x198]   ; report ID
 *   0x010d4e83 [32-bit: NEEDS RE-ANALYSIS]: call [rax+0x130]        ; VERIFY (get_feature_report)
 *   0x010d4e89 [32-bit: NEEDS RE-ANALYSIS]: ...                     ; process result
 *
 * PATH B: Without verify object (r13 == NULL) — used by SET_SETTINGS
 *
 *   0x010d4e6c [32-bit: NEEDS RE-ANALYSIS]: test r13, r13          ; r13 == NULL
 *   0x010d4e6f [32-bit: NEEDS RE-ANALYSIS]: je 0x10d4ff1           ; TAKEN → skip verify
 *   ...
 *   0x010d4ff1 [32-bit: NEEDS RE-ANALYSIS]: pxor xmm0, xmm0       ; timing calc
 *   0x010d4ff5 [32-bit: NEEDS RE-ANALYSIS]: cvtsi2ss xmm0, [esi+0x198]
 *   0x010d4ffe [32-bit: NEEDS RE-ANALYSIS]: jmp 0x10d4e91          ; go to timing calc
 */

/*
 * === WHY r13 IS NULL FOR SET_SETTINGS ===
 *
 * The state machine function signature:
 *
 *   void ProcessSettings(
 *       ControllerSettings* esi,     // settings state
 *       void* r13,                   // verify object (NULL for SET_SETTINGS)
 *       ...
 *   );
 *
 * The caller passes NULL as r13 when:
 *   - The command doesn't require verification (SET_SETTINGS)
 *   - The verify object hasn't been created yet
 *   - The caller explicitly wants to skip verification
 *
 * For GET_ATTRIBUTES:
 *   - A verify object is created to hold the response data
 *   - r13 points to this object
 *   - After vtable[0x130] returns, the response is in the object
 *
 * For SET_SETTINGS:
 *   - No verify object is needed (fire-and-forget)
 *   - r13 is NULL
 *   - The verify step is skipped
 */

/*
 * === THE COMPARISON PATH (0x010d4fd0 [32-bit: NEEDS RE-ANALYSIS]) ===
 *
 * When [esi+0x17c]==0 (normal operation):
 *
 *   0x010d4fd0 [32-bit: NEEDS RE-ANALYSIS]: mov rdx, [esi+0xc0]       ; settings buffer
 *   0x010d4fd7 [32-bit: NEEDS RE-ANALYSIS]: movzx r12d, byte [rdx+ebx] ; read setting byte
 *   0x010d4fdc [32-bit: NEEDS RE-ANALYSIS]: cmp r12b, al               ; compare with [esi+0xe1]
 *   0x010d4fdf [32-bit: NEEDS RE-ANALYSIS]: jne 0x10d4dc6              ; mismatch → send
 *   0x010d4fe5 [32-bit: NEEDS RE-ANALYSIS]: xor r12d, r12d             ; match → r12=0
 *   0x010d4feb [32-bit: NEEDS RE-ANALYSIS]: jne 0x10d4e75              ; if callback, call verify
 *
 * This path compares a byte from the settings buffer with the
 * current state byte. If they match, it means the setting was
 * already applied, so no send is needed. If they differ, a send
 * is triggered.
 *
 * But this comparison is NOT the SET_SETTINGS verification.
 * It's a "does this setting need to be sent?" check.
 */

/*
 * === THE [esi+0x17c] FLAG ===
 *
 * Set to 1 at: 0x0178a140 (YieldingRunTestProgram initialization)
 * Cleared at: 0x0119f3b1 [32-bit: NEEDS RE-ANALYSIS] (after calling vtable[0x228])
 *
 * In normal operation, [esi+0x17c] is ALWAYS 0.
 * The flag is only set during test/initialization sequences.
 *
 * When [esi+0x17c]==0:
 *   - The comparison path (0x10d4fd0) is used
 *   - Settings are compared with current state before sending
 *   - Verify happens only if r13 != NULL
 *
 * When [esi+0x17c]!=0:
 *   - The always-send path is used (dead code path)
 *   - All settings are sent regardless of current state
 */

/*
 * === WHY SET_SETTINGS RETRIES EVERY 3 SECONDS ===
 *
 * The retry is NOT because verification fails.
 * The retry is because:
 *
 * 1. SET_SETTINGS is fire-and-forget (no verification)
 * 2. If the HID write fails (vtable[0x10] returns error), the
 *    setting entry remains in the settings array
 * 3. The state machine re-processes the array periodically
 * 4. The 3-second interval is the state machine's polling period
 * 5. Each iteration, the failed setting is retried
 *
 * The "retry" is actually the state machine's normal operation:
 * it keeps trying to send until the HID write succeeds.
 */

/*
 * === KEY DIFFERENCE: SET_SETTINGS vs GET_ATTRIBUTES ===
 *
 *                    SET_SETTINGS (0x87)    GET_ATTRIBUTES (0x83)
 * Command byte       [esi+0xe0] = 0x87      [esi+0xe0] = 0x83
 * Verify object      r13 = NULL             r13 = non-NULL
 * VERIFY step        SKIPPED                HAPPENS
 * Response handling  None                   Data in verify object
 * Retry on failure   Yes (periodic)         Yes (periodic)
 * Protocol           Fire-and-forget        Request-response
 */

/*
 * === BINARY REFERENCES ===
 *
 * Critical branch (test r13): 0x010d4e6c [32-bit: NEEDS RE-ANALYSIS]
 * Skip verify target: 0x010d4ff1 [32-bit: NEEDS RE-ANALYSIS]
 * Verify call: 0x010d4e83 [32-bit: NEEDS RE-ANALYSIS] (vtable[0x130])
 * Send call: 0x010d4e14 [32-bit: NEEDS RE-ANALYSIS] (vtable[0x10])
 * Comparison path: 0x010d4fd0 [32-bit: NEEDS RE-ANALYSIS]
 * Pending flag check: 0x0123e5fb
 * [esi+0x17c] set: 0x0178a140
 * [esi+0x17c] cleared: 0x0119f3b1 [32-bit: NEEDS RE-ANALYSIS]
 */
