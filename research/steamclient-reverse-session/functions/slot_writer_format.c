/*
 * Slot Writer Response Format — What Format Does the Processing Code Expect?
 *
 * Binary: ~/.steam/debian-installation/ubuntu12_32/steamclient.so (32-bit, 49MB)
 * Status: DETERMINED (from binary analysis + SDL3 source)
 *
 * THE RESPONSE FORMAT
 * ===================
 *
 * The feature report processing code at 0x10d4e6c receives responses
 * from Feature Report 0x00 reads. The response format is:
 *
 * Byte 0:    Command identifier (0x83=GET_ATTRIBUTES, 0x84=GET_SERIAL, 0xf2=CAPABILITIES)
 * Byte 1+:   Command-specific payload
 *
 * The processing code dispatches based on the command byte and stores
 * the parsed data in the identity slot.
 *
 * COMMAND FORMATS
 * ===============
 *
 * 1. GET_ATTRIBUTES (0x83) Response
 *    Byte 0:    0x83 (command ID)
 *    Byte 1-4:  Product ID (uint32 LE, e.g., 0x1303 for SC2 BLE)
 *    Byte 5-8:  Secondary ID (uint32 LE, firmware version)
 *    Byte 9-12: Capability flags (uint32 LE)
 *    Byte 13+:  Additional attribute data
 *
 *    Stored in identity slot:
 *    - slot+0x1f8: product_id (from bytes 1-4)
 *    - slot+0x1fc: secondary_id (from bytes 5-8)
 *    - slot+0x234: capability_flags (from bytes 9-12, low byte)
 *
 * 2. GET_SERIAL (0x84) Response
 *    Byte 0:    0x84 (command ID)
 *    Byte 1+:   Serial number string (null-terminated or fixed length)
 *
 *    Stored in identity slot:
 *    - slot+0x200: unique_id (17 bytes, the serial number)
 *    - FIRST BYTE MUST BE NON-ZERO (this IS the ready flag)
 *
 *    For a real SC2 BLE controller, the serial number is derived from
 *    the MAC address or firmware. Format example:
 *    "PV000000000000000" (17 bytes, 'P'=0x50)
 *
 * 3. 0xf2 CAPABILITIES Response (multiple queries)
 *    Byte 0:    0xf2 (command ID)
 *    Byte 1:    Category/sub-command index (0x01, 0x02, etc.)
 *    Byte 2-N:  Capability data (varies by category)
 *
 *    Multiple 0xf2 queries return different categories of data.
 *    The combined responses fill the identity_data buffer:
 *    - slot+0x214: identity_data (32 bytes, concatenated from multiple 0xf2 responses)
 *
 * MINIMAL REQUIREMENTS FOR SLOT POPULATION
 * ==========================================
 *
 * To pass the zombie check at 0x107088c, the identity slot must have:
 *
 * 1. slot+0x200 (unique_id, first byte) MUST be non-zero
 *    - This is the ONLY byte that matters for the zombie check
 *    - Any non-zero value works (e.g., 0x53 for 'S' in "SC2SPOOF...")
 *
 * 2. slot+0x1f8 (product_id) SHOULD be 0x1303 for SC2 BLE
 *    - If wrong, the controller may not be recognized correctly
 *    - But the zombie check doesn't check this field
 *
 * 3. slot+0x1fc (secondary_id) SHOULD be a valid firmware version
 *    - If wrong, the version check at 0x10b3bbf may fail
 *    - But the zombie check doesn't check this field
 *
 * 4. slot+0x214 (identity_data, 32 bytes) SHOULD contain valid capability data
 *    - If wrong, the controller may not function correctly
 *    - But the zombie check doesn't check this field
 *
 * 5. slot+0x234 (capability_flags) SHOULD be a valid bitmask
 *    - If wrong, some features may not work
 *    - But the zombie check doesn't check this field
 *
 * 6. slot+0x235 (transport_type) SHOULD be 3 for BLE
 *    - If wrong, transport-specific code paths may not work
 *    - But the zombie check doesn't check this field
 *
 * THE CRITICAL INSIGHT
 * ====================
 *
 * The zombie check at 0x107088c ONLY checks:
 *   cmp byte [rax+0x200], 0
 *
 * It does NOT check any other field in the identity slot.
 * So to pass the zombie check, we only need:
 *   - slot+0x200 != 0
 *
 * The serial number (unique_id) at slot+0x200 is the ONLY field
 * that matters for the zombie check.
 *
 * HOWEVER: After passing the zombie check, the controller must
 * also pass registration (BYieldingRegisterSteamController), which
 * checks more fields. But that's a separate issue.
 *
 * WHAT OUR ATT SERVER MUST RESPOND
 * =================================
 *
 * When Steam reads Feature Report 0x00, our ATT server must return
 * a response that the processing code can parse correctly.
 *
 * The response must start with the command byte (0x83, 0x84, or 0xf2)
 * followed by the appropriate payload.
 *
 * For the serial number specifically:
 *   Response: [0x84] [serial_number_bytes...]
 *   Where serial_number_bytes is at least 1 byte and the first byte is non-zero.
 *
 * For capabilities:
 *   Response: [0xf2] [category] [capability_data...]
 *   Multiple responses for different categories.
 *
 * FOR OUR SPOOFED CONTROLLER
 * ===========================
 *
 * We can use any valid serial number format. The first byte must be non-zero.
 * Example: "SC2SPOOF000000000" (17 bytes, 'S'=0x53)
 *
 * The product_id should be 0x1303 (SC2 BLE).
 * The transport_type should be 3 (BLE).
 *
 * The capability data should match what a real SC2 returns.
 * We can use the capability bitmask 0x4169bfff as observed in logs.
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

