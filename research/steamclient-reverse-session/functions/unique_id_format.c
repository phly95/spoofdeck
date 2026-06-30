/*
 * Unique ID Format Analysis — What Goes in controller+slot*0xe8+0x200
 *
 * Binary: ~/.steam/debian-installation/ubuntu12_32/steamclient.so (32-bit, 49MB)
 * Status: DETERMINED (constraints known, exact format TBD)
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
 * === THE READY FLAG ===
 *
 * The ready flag is the FIRST BYTE of the unique_id field:
 *   Location: controller + slot*0xe8 + 0x200
 *   Size: 1 byte (but the field is 17 bytes total)
 *   Check: cmp byte [rax+0x200], 0
 *   Pass condition: non-zero
 *   Fail condition: zero
 *
 * This is the ONLY byte that matters for the zombie check.
 * The rest of the 17-byte unique_id can be anything.
 */

/*
 * === UNIQUE ID FIELD LAYOUT ===
 *
 * Offset  Size  Description
 * ------  ----  -----------
 * +0x200  1     READY FLAG (first byte of unique_id)
 * +0x201  1     byte 1
 * +0x202  1     byte 2
 * +0x203  1     byte 3
 * +0x204  1     byte 4
 * +0x205  1     byte 5
 * +0x206  1     byte 6
 * +0x207  1     byte 7
 * +0x17c  1     byte 8
 * +0x209  1     byte 9
 * +0x20a  1     byte 10
 * +0x20b  1     byte 11
 * +0x20c  1     byte 12
 * +0x20d  1     byte 13
 * +0x20e  1     byte 14
 * +0x20f  1     byte 15
 * +0x210  1     byte 16 (17th byte)
 *
 * Total: 17 bytes (0x11 bytes)
 */

/*
 * === WHAT A REAL SC2 RETURNS ===
 *
 * The unique_id is likely the controller's serial number.
 * For a real SC2 BLE controller, the serial number is:
 * - Derived from the MAC address or firmware
 * - Typically 12-17 characters
 * - First byte is non-zero (part of the serial string)
 *
 * The serial number is read from the Serial Number characteristic
 * in the Device Information Service (UUID 0x2A25).
 *
 * For our spoofed controller, we can use any non-zero value.
 */

/*
 * === WHAT FORMAT DOES THE PROCESSING CODE EXPECT? ===
 *
 * The feature report processing code parses the GET_SERIAL response
 * and stores it in the identity slot. The processing code expects:
 *
 * 1. A response to the GET_SERIAL command
 * 2. The response contains a serial number string
 * 3. The serial number is stored as-is in the identity slot
 * 4. The first byte becomes the ready flag
 *
 * The processing code doesn't validate the serial number format.
 * It just stores whatever bytes the response contains.
 *
 * So any non-zero byte in the first position should work.
 */

/*
 * === MINIMAL REQUIREMENT ===
 *
 * To satisfy the ready flag check:
 *   controller+slot*0xe8+0x200 must be non-zero
 *
 * This means:
 *   The first byte of the unique_id must be non-zero
 *
 * The simplest approach:
 *   Return a serial number response where byte 0 is non-zero
 *   Example: "SC2SPOOF000000000" (17 bytes, 'S' = 0x53)
 *
 * The response must come from the GET_SERIAL command processing.
 * If the processing code doesn't parse our response correctly,
 * the slot stays empty.
 */

/*
 * === CONSTRAINTS ===
 *
 * 1. The serial number must be returned via the GET_SERIAL command
 * 2. The processing code must parse the response correctly
 * 3. The first byte must be non-zero
 * 4. The response must arrive before the 6s zombie timer
 *
 * The critical question is: what format does the GET_SERIAL response
 * processing code expect? If we get the format wrong, the slot stays empty.
 */

/*
 * === RECOMMENDATION ===
 *
 * Use a simple serial string like:
 *   "SC2DECK0000000000" (17 bytes)
 *
 * First byte 'S' = 0x53 (non-zero) → ready flag satisfied
 *
 * The exact format depends on what the processing code expects.
 * We need to trace the GET_SERIAL response handler to confirm.
 */
