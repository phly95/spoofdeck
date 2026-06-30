/*
 * Bypass Handshake Analysis — Can We Populate Slot Data Without Feature Reports?
 *
 * Binary: ~/.steam/debian-installation/ubuntu12_32/steamclient.so (32-bit, 49MB)
 * Status: PARTIALLY DETERMINED
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
 * === THE RACE CONDITION ===
 *
 * Timeline:
 * T+0s:    BLE connection established
 * T+0s:    BlueZ hog-ll opens /dev/hidrawN
 * T+0-1s:  Feature report handshake begins
 * T+1-2s:  All responses parsed, identity slot populated
 * T+6s:    Zombie timer fires → checks slot+0x200
 *
 * The zombie timer fires at ~6 seconds. The feature report handshake
 * must complete AND populate the identity slot before then.
 *
 * Current problem: our ATT server responds to feature reports, but
 * the processing code doesn't parse our responses correctly, so the
 * identity slot stays empty.
 */

/*
 * === OPTION 1: FIX THE FEATURE REPORT RESPONSE FORMAT ===
 *
 * The most direct approach: make our ATT server return responses in the
 * exact format that the processing code expects.
 *
 * This requires knowing:
 * 1. The exact byte format for GET_ATTRIBUTES (0x83) response
 * 2. The exact byte format for GET_SERIAL response
 * 3. The exact byte format for 0xf2 capability responses
 *
 * If we get the format right, the processing code will parse the response
 * and populate the identity slot automatically.
 *
 * Pros: Works with the existing code flow
 * Cons: Need to reverse-engineer the exact response formats
 */

/*
 * === OPTION 2: POPULATE THE IDENTITY SLOT DIRECTLY ===
 *
 * If we know what code writes to controller+slot*0xe8+0x200, we could
 * potentially call that code directly with pre-populated data.
 *
 * However, this requires:
 * 1. Finding the writer function
 * 2. Understanding its parameters
 * 3. Calling it at the right time
 *
 * This is more invasive and risky.
 */

/*
 * === OPTION 3: BYPASS THE ZOMBIE CHECK ===
 *
 * The zombie check at 0x1070620 has multiple conditions:
 * 1. Bounds check (slot <= 15)
 * 2. Vtable validation
 * 3. Connection object exists
 * 4. Connection state == 1 or 4
 * 5. Slot ready flag at +0x200 != 0
 *
 * If we can satisfy conditions 1-4 but not 5, the function returns 0.
 * The zombie timer then disconnects the controller.
 *
 * Is there a way to skip the zombie check entirely?
 * - The zombie check is called from the slot iterator at 0x1072106
 * - The iterator checks slot state == 3 AND per-slot flag == 0
 * - If we can set the per-slot flag to non-zero, the zombie check is skipped
 *
 * Per-slot flag location: [controller+slot*0x54+0x10b4]
 * If this flag is non-zero, the zombie check is SKIPPED entirely.
 *
 * This might be the easiest bypass: populate the per-slot flag at
 * offset 0x10b4 to bypass the zombie check.
 */

/*
 * === OPTION 4: TRIGGER QueueFetchingControllerDetails DIRECTLY ===
 *
 * QueueFetchingControllerDetails sets controller+0x3c = 1.
 * But GetControllerInfo checks controller+slot*0xe8+0x200.
 * These are DIFFERENT locations. So calling QueueFetchingControllerDetails
 * directly won't help with the zombie check.
 */

/*
 * === RECOMMENDED APPROACH ===
 *
 * The most promising approach is Option 3: bypass the zombie check by
 * setting the per-slot flag at offset 0x10b4.
 *
 * From the zombie check code at 0x1072013:
 *   cmp byte [rcx+rax+0x10b4], 0  ; check per-slot flag
 *   je 0x1072100                    ; if 0 → do zombie check
 *
 * If the flag is non-zero, the zombie check is skipped entirely.
 * This means the controller won't be disconnected even if the identity
 * slot is empty.
 *
 * But this only delays the problem — registration will still fail because
 * GetControllerInfo returns 0 (identity slot empty).
 *
 * The REAL fix is Option 1: make our ATT server return correct responses
 * so the processing code populates the identity slot.
 */

/*
 * === ANSWER: CAN WE BYPASS? ===
 *
 * Short answer: We can BYPASS the zombie check (Option 3), but we CANNOT
 * bypass the need for populated identity data (Option 1).
 *
 * The zombie check and the identity check are the SAME function (0x1070620).
 * If we bypass the zombie check, registration still fails because
 * GetControllerInfo returns 0.
 *
 * The only way to make registration succeed is to populate the identity
 * slot at controller+slot*0xe8+0x200 with non-zero data.
 *
 * This requires the feature report handshake to complete successfully,
 * which means our ATT server must return responses in the correct format.
 */
