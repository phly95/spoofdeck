/*
 * 0xf2 Response Format — Analysis
 *
 * Binary: ~/.steam/debian-installation/ubuntu12_32/steamclient.so (32-bit, 49MB)
 * Status: PARTIALLY DETERMINED
 *
 * ============================================================
 * WHERE 0xf2 IS SENT
 * ============================================================
 *
 * The 0xf2 command is NOT in the initial setup function at 0x10c1f5f.
 * It's in the ongoing feature report state machine at 0x10d4e6c or
 * in a different code path.
 *
 * The initial setup function (0x10c1f5f) only sends:
 * - 0xAE (GET_SERIAL) — multiple retries
 * - 0x83 (GET_ATTRIBUTES) — one round
 * - 0xA1 (command at 0x10c4118) — appears to be a different command
 *
 * The 0xf2 is likely sent in the post-registration phase or in the
 * ongoing state machine. The state machine at 0x10d4e6c processes
 * feature report responses from an ongoing read loop.
 *
 * ============================================================
 * 0xf2 IN THE INITIAL SETUP
 * ============================================================
 *
 * The function at 0x10c1f5f has an outer loop that sends different
 * commands based on the PID. For SC2 BLE (PID 0x1303):
 *
 * 1. First: Send 0xAE (GET_SERIAL) with size 23, read with size 23
 * 2. Then: Send 0x83 (GET_ATTRIBUTES) with size 2, read with size 62
 * 3. After GET_ATTRIBUTES: process attributes → set PID/VID/capabilities
 * 4. Return to caller with populated output struct
 *
 * The 0xf2 is NOT sent in this initial setup. It must be sent
 * elsewhere — likely in the state machine at 0x10d4e6c.
 *
 * ============================================================
 * 0xf2 IN THE STATE MACHINE (0x10d4e6c)
 * ============================================================
 *
 * The state machine at 0x10d4e6c is called periodically to process
 * ongoing feature report reads. It iterates through settings entries
 * at [esi+0xc0] (16-byte entries), each with a command byte and
 * response data.
 *
 * The state machine structure (esi = controller object):
 *   [esi+0xb8]: total number of settings entries
 *   [esi+0xc0]: settings array (16 bytes per entry)
 *   [esi+0xd0]: pending entry count
 *   [esi+0xe0]: command byte (e.g., 0x87 for SET_SETTINGS)
 *   [esi+0xe1]: response flag
 *   [esi+0xe4]: current entry index
 *   [esi+0x198]: report ID for feature report
 *   [esi+0x1f8]: flag byte
 *   [esi+0x17c]: HID connection established flag
 *
 * The 0xf2 command is likely one of the settings entries that
 * gets dispatched through the vtable call at 0x10d509d:
 *   call qword [rax + 0x10]  ; vtable[2] handler
 *
 * ============================================================
 * WHAT WE KNOW ABOUT 0xf2 FROM PROTOCOL ANALYSIS
 * ============================================================
 *
 * From the SC2 protocol documentation:
 * - 0xf2 is a per-category capability query
 * - The host sends 0xf2 with a category byte
 * - The controller responds with category-specific capability data
 * - Real SC2 sends 8+ categories
 *
 * Expected categories (0x01-0x08 or similar):
 * - Category 0x01: Basic gamepad capabilities
 * - Category 0x02: Trackpad capabilities
 * - Category 0x03: IMU/gyroscope capabilities
 * - Category 0x04: Trigger capabilities
 * - Category 0x05-0x08: Additional features
 *
 * Expected response format for each category:
 *   Byte 0:    0xf2 (command echo)
 *   Byte 1:    Category ID (0x01-0x08)
 *   Byte 2:    Capability data length
 *   Bytes 3-N: Category-specific capability data
 *
 * ============================================================
 * WHY ONLY 1 CATEGORY MATTERS
 * ============================================================
 *
 * The identity slot at controller+slot*0xe8+0x214 has 32 bytes
 * of identity_data. This is populated by concatenating the
 * capability data from all 0xf2 responses.
 *
 * If we only return 1 category, the identity_data is incomplete.
 * This might cause the controller to be rejected during
 * registration or lose functionality later.
 *
 * HOWEVER: The zombie check at 0x107088c ONLY checks:
 *   cmp byte [rax+0x200], 0  ; serial[0] must be non-zero
 *
 * It does NOT check identity_data. So incomplete 0xf2 responses
 * won't cause zombie disconnects — they'll cause functional issues
 * later (missing trackpads, gyro, etc.).
 *
 * ============================================================
 * WHAT NEEDS TO BE DONE
 * ============================================================
 *
 * To fully support 0xf2, we need to:
 * 1. Determine how many categories the real SC2 responds with
 * 2. Determine the exact capability data for each category
 * 3. Return all categories in sequence
 *
 * For now, the minimum viable approach is to:
 * - Return at least category 0x01 with basic gamepad capabilities
 * - Include the capabilities bitmask (0x4169bfff or similar)
 * - Don't worry about additional categories until basic registration works
 *
 * The 0xf2 responses are likely NOT the blocker for registration.
 * The serial number validation is the more likely blocker.
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

