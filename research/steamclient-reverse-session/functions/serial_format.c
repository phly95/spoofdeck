/*
 * Serial Format Analysis — What Steam Accepts
 *
 * ============================================================
 * FUNCTION AT 0x26b1ac0: V_strncmp (strtools.cpp)
 * ============================================================
 *
 * Prototype: int V_strncmp(const char* s1, const char* s2, size_t count)
 * 
 * ABI: rdi=s1, rsi=s2, rdx=count
 * Returns: 0 if equal (up to count bytes), -1 if s1<s2, +1 if s1>s2
 *
 * ============================================================
 * CALL SITE AT 0x10c29b3
 * ============================================================
 *
 * Arguments:
 *   rdi = [rbp-0x17d]   → serial string (first byte after 0xAE/0x15/0x01 header)
 *   rsi = 0xd69c60       → pattern string (UTF-16LE "FH_cz~...")
 *   rdx = 1              → count = 1 BYTE
 *
 * With count=1, V_strncmp compares exactly ONE byte:
 *   serial[0] vs pattern[0]
 *
 * pattern[0] = 0x46 = 'F'
 *
 * Result:
 *   serial[0] == 'F' → return 0 → PASSES validation
 *   serial[0] != 'F' → return non-zero → FAILS validation
 *
 * ============================================================
 * WHY OUR SERIAL FAILS
 * ============================================================
 *
 * Our serial: "28de-1303-2efea7d"
 * serial[0] = '2' = 0x32
 * Expected:  'F' = 0x46
 * 0x32 != 0x46 → FAILS
 *
 * ============================================================
 * WHAT HAPPENS ON FAILURE
 * ============================================================
 *
 * When V_strncmp fails (jne at 0x10c29be → 0x10c20a3):
 *
 *   lea rdi, [r14+0x3d]      ; dest = controller_info + offset 0x3d
 *   lea rsi, "DOCKED_SLOT"   ; source = fallback string
 *   mov edx, 0x14             ; 20 bytes
 *   call V_strncpy            ; copies "DOCKED_SLOT" as the serial
 *
 * The serial in the controller info struct becomes "DOCKED_SLOT".
 *
 * ============================================================
 * WHAT HAPPENS ON SUCCESS
 * ============================================================
 *
 * When V_strncmp passes (0x10c29c4):
 *
 *   mov edx, 0x14             ; 20 bytes
 *   mov rsi, r12              ; source = serial data from response
 *   call V_strncpy            ; copies the actual serial to controller_info+0x3d
 *
 * The actual serial from the GET_SERIAL response is preserved.
 *
 * ============================================================
 * FUNCTION AT 0x26b2800: V_strncpy (strtools.cpp)
 * ============================================================
 *
 * Prototype: char* V_strncpy(char* dest, const char* src, size_t maxLen)
 *
 * Copies src to dest byte-by-byte, stopping at:
 *   - Null terminator in src
 *   - maxLen reached
 * Then null-terminates dest.
 *
 * At call site 0x10c29cc: maxLen = 0x14 (20 bytes)
 * At call site 0x10c20af: maxLen = 0x14 (20 bytes)
 *
 * ============================================================
 * SERIAL FORMAT TO USE
 * ============================================================
 *
 * REQUIREMENT: Serial must start with 'F' (0x46).
 * LENGTH: 20 bytes (from V_memcpy size 0x14).
 *
 * Recommended format: First byte 'F', remaining 19 bytes unknown.
 * No real SC2 serials available for reference.
 *
 * Breakdown:
 *   'F'        = Valve hardware serial prefix (passes V_strncmp)
 *   Rest       = Unknown without real device capture
 *
 * ============================================================
 * THE "Invalid or missing" LOG MESSAGE
 * ============================================================
 *
 * The log "Invalid or missing unit serial number SC2DECK001,
 * setting to '28de-1303-2efea7d'" comes from a SEPARATE
 * validation in CGetControllerInfoWorkItem::RunFunc.
 *
 * This runs AFTER the GET_SERIAL handler. It checks the
 * serial stored in the controller info struct (at offset 0x3d).
 *
 * Flow:
 *   1. GET_SERIAL handler validates serial[0] == 'F' via V_strncmp
 *   2. If fails → serial = "DOCKED_SLOT"  
 *   3. If passes → serial = actual serial from device
 *   4. Controller info registered with Steam
 *   5. CGetControllerInfoWorkItem reads controller details
 *   6. If serial is invalid (empty, "DOCKED_SLOT", etc.)
 *      → generates fallback "28de-1303-XXXXXXXX"
 *
 * The fallback format "28de-1303-XXXXXXXX":
 *   28de = VID 0x28DE (Valve) in little-endian
 *   1303 = PID 0x1303 (SC2 BLE) in little-endian  
 *   XXXXXXXX = hash of controller Bluetooth address
 *
 * ============================================================
 * SUMMARY
 * ============================================================
 *
 * The validation function at 0x26b1ac0 (V_strncmp) compares
 * only the FIRST BYTE of the serial against 'F'.
 *
 * Our serial fails because serial[0] = '2', not 'F'.
 *
 * Fix: Change serial to start with 'F' (20 bytes total).
 *
 * The V_strncmp check is the first gate. After passing it,
 * the serial is copied to the controller info struct. Then
 * CGetControllerInfoWorkItem performs a second validation.
 * A well-formatted serial starting with 'F' should pass both.
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

