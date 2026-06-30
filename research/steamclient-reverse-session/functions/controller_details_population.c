/*
 * Controller Details Population Analysis — What Writes to Identity Slot
 *
 * Binary: ~/.steam/debian-installation/ubuntu12_32/steamclient.so (32-bit, 49MB)
 * Status: PARTIALLY DETERMINED
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
 * === TWO SEPARATE WRITE PATHS ===
 *
 * Path 1: ControllerDetails (ControllerDetails_tE)
 *   Writer: QueueFetchingControllerDetails (0x1092820)
 *   Destination: controller+0x1070+id*0x54
 *   Source: controller+0x84..0xd4 (read by CallerOfQueueFetchingControllerDetails)
 *   Ready flag: controller+0x3c = 1
 *   Used by: EYldWaitForControllerDetails
 *
 * Path 2: Identity Slot (slot identity data)
 *   Writer: UNKNOWN (feature report response processing code)
 *   Destination: controller+slot*0xe8+0x1f8
 *   Source: Feature Report 0x00 responses (GET_ATTRIBUTES, GET_SERIAL, 0xf2)
 *   Ready flag: controller+slot*0xe8+0x200 (first byte of unique_id)
 *   Used by: GetControllerInfo (0x1070620) — zombie check
 */

/*
 * === FEATURE REPORT RESPONSE PROCESSING (0x10d4e6c) ===
 *
 * The feature report processing state machine at 0x10d4e6c handles
 * responses to Feature Report 0x00 commands.
 *
 * Flow:
 * 1. Steam sends command via SDL_hid_send_feature_report()
 * 2. BlueZ hog-ll sends ATT Write Command (0x52) to our server
 * 3. Our server stores response in _pending_fr_response
 * 4. Steam reads Feature Report 0x00 via SDL_hid_get_feature_report()
 * 5. BlueZ hog-ll sends ATT Read Request (0x0A) to our server
 * 6. We return the stored response
 * 7. Steam receives the response
 * 8. State machine at 0x10d4e6c processes the response
 * 9. Response data is stored in identity slot
 *
 * The state machine dispatches based on the command byte:
 * - 0x83 (GET_ATTRIBUTES): Parse and store controller attributes
 * - 0x84 (GET_SERIAL): Parse and store serial number
 * - 0xf2 (CAPABILITIES): Parse and store capability data
 * - 0x87 (SET_SETTINGS): Fire-and-forget, no response expected
 *
 * After each response is processed, the data is stored in the identity
 * slot at controller+slot*0xe8+0x1f8. The unique_id at +0x200 becomes
 * non-zero when the serial number is received.
 */

/*
 * === WHAT POPULATES EACH FIELD ===
 *
 * Product ID (+0x1f8):
 *   Source: GET_ATTRIBUTES (0x83) response
 *   Value: 0x1303 for SC2 BLE
 *   Format: uint32 LE in the response payload
 *
 * Secondary ID (+0x1fc):
 *   Source: GET_ATTRIBUTES (0x83) response
 *   Value: Firmware version or board revision
 *   Format: uint32 LE in the response payload
 *
 * Unique ID (+0x200, 17 bytes):
 *   Source: GET_SERIAL response
 *   Value: Serial number (e.g., MAC address or firmware string)
 *   Format: 17 bytes, first byte MUST be non-zero (this IS the ready flag)
 *   For real SC2: likely "PV000..." or MAC address bytes
 *
 * Identity Data (+0x214, 32 bytes):
 *   Source: 0xf2 capability responses (multiple queries)
 *   Value: Capability bitmask and hardware features
 *   Format: Multiple 0xf2 responses are concatenated
 *
 * Capability Flags (+0x234):
 *   Source: GET_ATTRIBUTES (0x83) response
 *   Value: Capability bitmask (e.g., 0x4169bfff)
 *   Format: uint8
 *
 * Transport Type (+0x235):
 *   Source: Connection handler
 *   Value: 3 for BLE, 2 for USB, 4 for Dongle
 *   Format: uint8
 */

/*
 * === THE SERIAL NUMBER FORMAT ===
 *
 * The unique_id at +0x200 is 17 bytes. For a real SC2:
 * - Byte 0: Non-zero (this is the ready flag check)
 * - Bytes 1-16: Serial number data
 *
 * The serial number is likely:
 * - Option A: MAC address (6 bytes) + padding
 * - Option B: Firmware-derived string (e.g., "PV000000000000")
 * - Option C: UUID or hash
 *
 * The critical requirement: byte 0 must be non-zero.
 * Any non-zero value should satisfy the ready_flag check.
 *
 * For our spoofed controller, we can use:
 * - A fixed serial string like "SC2SPOOF000000000" (17 bytes)
 * - The first byte 'S' (0x53) is non-zero → ready flag satisfied
 */

/*
 * === IMPLICATION FOR OUR ATT SERVER ===
 *
 * Our ATT server must return responses that the feature report processing
 * code can parse correctly. The processing code expects specific formats
 * for each command.
 *
 * If the response format is wrong:
 * - The processing code may skip the response
 * - The identity slot fields stay at their initial values (zeros)
 * - The unique_id stays zero → ready_flag not set
 * - GetControllerInfo returns 0 → zombie disconnect
 *
 * The key is that our ATT server must return responses in the EXACT format
 * that the processing code expects. This means:
 * 1. Correct command byte in the response
 * 2. Correct payload format for each command
 * 3. Correct lengths for each field
 * 4. Non-zero serial number
 */
