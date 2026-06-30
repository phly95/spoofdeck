/*
 * GET_SERIAL (0xAE) Response Format — Exact Analysis
 *
 * Binary: ~/.steam/debian-installation/ubuntu12_32/steamclient.so (32-bit, 49MB)
 * Function: 0x10c1f5f (initial controller setup)
 * Status: DETERMINED
 *
 * ============================================================
 * HOW THE RESPONSE IS READ
 * ============================================================
 *
 * STEP 1: SEND GET_SERIAL COMMAND (SET_REPORT)
 * ------------------------------------------------
 * At 0x10c2038-0x10c2043:
 *   mov ecx, 0x15ae
 *   mov word [rbp-0x180], cx   ; buffer[0] = 0xAE, buffer[1] = 0x15
 *   mov byte [rbp-0x17e], 1    ; buffer[2] = 0x01 (set earlier at 0x10c2020)
 *
 * At 0x10c205c:
 *   movzx edx, byte [rbp-0x17f]  ; edx = buffer[1] = 0x15
 *   add rdx, 2                    ; size = 0x15 + 2 = 0x17 = 23
 *   call [rax+0x30]               ; HID send_feature_report(dev, buf, 23)
 *
 * Write command: [0xAE, 0x15, 0x01, 0x00 × 20] (23 bytes)
 *
 * STEP 2: READ RESPONSE (GET_REPORT)
 * -----------------------------------
 * At 0x10c28be:
 *   mov r13d, 9                   ; retry count = 9
 *   mov edx, 0x17                 ; read size = 23 bytes
 *   mov rsi, esi                  ; buffer = [rbp-0x140]
 *   call [rax+0x38]               ; HID get_feature_report(dev, buf, 23)
 *
 * STEP 3: VALIDATE RESPONSE
 * --------------------------
 * At 0x10c2910 (success path):
 *   cmp byte [rbp-0x140], 0xAE   ; byte[0] must be 0xAE (command echo)
 *   jne retry
 *   cmp byte [rbp-0x13e], 1      ; byte[2] must be 0x01 (success flag)
 *   jne error                     ; if not 1 → "Controller Serial# invalid"
 *
 * The retry loop (up to 9 internal + 8 outer iterations) sends the SAME
 * 0xAE command repeatedly until a valid 0xAE response with status=1 is received.
 *
 * ============================================================
 * RESPONSE FORMAT (23 bytes)
 * ============================================================
 *
 * Offset  Size  Description
 * ------  ----  -----------
 * 0       1     Command echo: 0xAE
 * 1       1     Payload length / info byte (0x15 = 21 for our case)
 * 2       1     Status: 0x01 = valid serial, 0x00 = invalid/pending
 * 3       20    Serial number (ASCII string, null-padded)
 *
 * Total: 23 bytes (matching the read size of 0x17)
 *
 * ============================================================
 * SERIAL NUMBER VALIDATION
 * ============================================================
 *
 * After byte[2] == 0x01 check passes:
 *
 * At 0x10c2926-0x10c2943:
 *   rax = first 8 bytes of response
 *   r12 = [rbp-0x17d] = response + 3 (serial data pointer)
 *   r14 = [rbp-0x1c8] = output struct
 *   rdx = 1
 *   rdi = r12 (serial data)
 *   rsi = "FH_cz..." (format/pattern string at 0xd69c60)
 *
 * At 0x10c29b3:
 *   call 0x26b1ac0               ; validation function
 *   test eax, eax
 *   jne error                     ; if validation FAILS, serial is rejected
 *
 * If validation passes:
 *   lea rdi, [r14+0x3d]          ; destination = output_struct + 0x3d
 *   mov edx, 0x14                ; 20 bytes
 *   mov rsi, r12                 ; source = serial data
 *   call 0x26b2800               ; memcpy(output+0x3d, serial, 20)
 *
 * The validation function at 0x26b1ac0 likely checks:
 * - The first byte(s) of the serial match an expected pattern
 * - OR the serial has minimum length
 * - OR the serial matches a specific format
 *
 * "FH_cz" at 0xd69c60 is an ENCRYPTED/SCRAMBLED string (the binary
 * shows it as garbage unicode). This is likely a key for decrypting
 * or validating the serial number. The function probably does a
 * byte comparison or HMAC check.
 *
 * ============================================================
 * FAILURE PATH
 * ============================================================
 *
 * If ALL 8 outer iterations fail (no valid 0xAE response):
 *
 * At 0x10c209c:
 *   call [rax+0x38]              ; one final read
 *   lea rdi, [r14+0x3d]          ; output + 0x3d
 *   lea rsi, str.DOCKED_SLOT     ; "DOCKED_SLOT"
 *   mov edx, 0x14                ; 20 bytes
 *   call 0x26b2800               ; memcpy(output+0x3d, "DOCKED_SLOT", 20)
 *
 * Then sets default values:
 *   output[4] = 0x130228de       ; VID=0x28de, PID=0x1302 (USB default!)
 *   output[8] = 0x4161bfff       ; capabilities bitmask
 *   output[0x30] = 0xa           ; mode = 10
 *   output[0x38] = 1             ; flag
 *
 * NOTE: Even in the failure path, the function continues and returns
 * a "default" output struct with PID 0x1302 (USB) instead of 0x1303 (BLE).
 *
 * ============================================================
 * THE "INVALID OR MISSING" ERROR
 * ============================================================
 *
 * The Steam log message:
 *   "Controller has an Invalid or missing unit serial number SC2DECK001,
 *    setting to '28de-1303-2efea7d'"
 *
 * This message is from string at 0xcaedd8, which is a DIFFERENT code path
 * from the Feature Report processing at 0x10c1f5f. It's called from the
 * identity slot validation code (likely at 0x105cb50 or similar).
 *
 * The flow is:
 * 1. Feature Report processing reads serial → writes to output struct
 * 2. Caller copies output struct to identity slot (controller+slot*0xe8+0x1f8)
 * 3. Identity slot validation at 0x105ca80 checks slot+0x200 (serial[0])
 * 4. If serial[0] != 0 → passes basic check
 * 5. But later validation rejects the format → "Invalid or missing" message
 *
 * The serial "SC2DECK001" IS being written to the identity slot (first byte
 * 'S' = 0x53 ≠ 0, so slot+0x200 check passes). But the format validation
 * rejects it because it expects a MAC-derived or firmware-derived serial.
 *
 * The replacement serial "28de-1303-2efea7d" follows the format:
 *   XX XX - XXXX - XXXXXXX
 *   VID   PID    hash
 *
 * ============================================================
 * WHAT OUR ATT SERVER MUST RETURN
 * ============================================================
 *
 * Minimum viable response (23 bytes):
 *
 * Byte 0:    0xAE (command echo)
 * Byte 1:    0x15 (payload length, matching the write command's byte[1])
 * Byte 2:    0x01 (success status — MUST be 0x01)
 * Bytes 3-22: Serial number (20 bytes)
 *
 * The serial number format that Steam accepts:
 *   Option A: "XX-XXXX-XXXXXXXX" (MAC-like format)
 *   Option B: Raw MAC address bytes
 *   Option C: Any non-zero, non-trivial string
 *
 * Since Steam replaces invalid serials with "28de-1303-XXXXXXXX",
 * the hash part might be a CRC32 or other hash of the MAC address.
 *
 * For our spoof, any 20-byte string should work IF the validation
 * at 0x26b1ac0 passes. The issue is that this validation function
 * checks the serial against an encrypted pattern.
 *
 * ALTERNATIVE APPROACH: Instead of trying to match the exact serial
 * format, we can try to bypass the validation entirely by returning
 * a serial that makes the validation function return 0.
 *
 * ============================================================
 * WHAT'S WRONG WITH OUR CURRENT RESPONSE
 * ============================================================
 *
 * Our current: ae 14 01 53 43 32 44 45 43 4b 30 30 31...
 *
 * Analysis:
 *   byte[0] = 0xAE ✓ (command echo)
 *   byte[1] = 0x14 = 20 (but the write command has 0x15 in byte[1])
 *   byte[2] = 0x01 ✓ (success flag)
 *   bytes[3-22] = "SC2DECK001\0..." (10 chars + null padding)
 *
 * ISSUE: byte[1] = 0x14 but write command byte[1] = 0x15.
 * The write command is [0xAE, 0x15, 0x01, ...] and read response
 * has byte[1] = 0x14. These should match!
 *
 * The write command byte[1] = 0x15 = 21 (payload size).
 * The response byte[1] should echo this value or be consistent.
 *
 * FIX: Change response byte[1] from 0x14 to 0x15.
 * Current: ae 14 01 ... → ae 15 01 ...
 *
 * SECOND ISSUE: The serial "SC2DECK001" doesn't pass the validation
 * at 0x26b1ac0. The validation function likely checks:
 * - First byte matches a pattern (the "FH_cz" string)
 * - OR the serial is all hex characters
 * - OR the serial matches MAC address format
 *
 * The Steam replacement "28de-1303-2efea7d" suggests the expected
 * format is: VID-PID-hash where hash is 7 hex chars.
 *
 * ============================================================
 * CORRECTED RESPONSE
 * ============================================================
 *
 * 23-byte response:
 *   ae 15 01 32 38 64 65 2d 31 33 30 33 2d 32 65 66 65 61 37 64 00 00 00
 *   ^  ^  ^  ^-- serial "28de-1303-2efea7d" (padded to 20 bytes)
 *   |  |  |
 *   |  |  success flag
 *   |  payload length (0x15 = 21, matching write command)
 *   command echo
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

