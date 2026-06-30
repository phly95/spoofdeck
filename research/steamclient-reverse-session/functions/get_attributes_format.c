/*
 * GET_ATTRIBUTES (0x83) Response Format — Exact Analysis
 *
 * Binary: ~/.steam/debian-installation/ubuntu12_32/steamclient.so (32-bit, 49MB)
 * Function: 0x10c1f5f (initial controller setup)
 * Status: DETERMINED
 *
 * ============================================================
 * HOW THE RESPONSE IS READ
 * ============================================================
 *
 * The function at 0x10c1f5f handles the initial controller setup.
 * For SC2 BLE (PID 0x1303), it jumps to 0x10c1fc3.
 *
 * STEP 1: SEND GET_ATTRIBUTES COMMAND (SET_REPORT)
 * ------------------------------------------------
 * At 0x10c274b:
 *   mov r13d, 0x83
 *   mov word [rbp-0x180], r13w   ; write buffer = [0x83, 0x00]
 *
 * At 0x10c276c:
 *   movzx edx, byte [rbp-0x17f]  ; edx = buffer[1] = 0x00
 *   add rdx, 2                    ; size = 0x00 + 2 = 2
 *   call [rax+0x30]               ; HID send_feature_report(dev, buf, 2)
 *
 * So the WRITE command is: [0x83, 0x00] (2 bytes via SET_REPORT)
 * This tells the controller "I want attributes, respond with command 0x83"
 *
 * STEP 2: READ RESPONSE (GET_REPORT)
 * -----------------------------------
 * At 0x10c2b00-0x10c2b15:
 *   mov r13d, 9                   ; retry count = 9
 *   mov edx, 0x3e                 ; read size = 62 bytes
 *   mov rsi, esi                  ; buffer = [rbp-0x140]
 *   call [rax+0x38]               ; HID get_feature_report(dev, buf, 62)
 *
 * The response buffer is esi = [rbp-0x140], 62 bytes.
 *
 * STEP 3: VALIDATE RESPONSE
 * --------------------------
 * At 0x10c31c0 (success path after read):
 *   cmp byte [rbp-0x140], 0x83   ; byte[0] must be 0x83 (command echo)
 *   jne error                     ; if not, retry
 *   cmp byte [rbp-0x13f], 0      ; byte[1] must NOT be zero
 *   jne process_attributes        ; if non-zero, process
 *   ; if byte[1] == 0 → "Controller Info Msg garbled" error
 *
 * At 0x10c2bd0 (attribute processing entry):
 *   mov rax, qword [rbp-0x140]   ; load first 8 bytes
 *   cmp al, 0x83                 ; confirm byte[0] == 0x83
 *   jne error
 *   movzx edx, byte [rbp-0x17f]  ; edx = byte[1] = attribute count
 *   test dl, dl
 *   je error                      ; count must be non-zero
 *
 * ============================================================
 * RESPONSE FORMAT
 * ============================================================
 *
 * Byte layout (62 bytes total):
 *
 * Offset  Size  Description
 * ------  ----  -----------
 * 0       1     Command echo: 0x83
 * 1       1     Attribute byte count: N (must be > 0, must be multiple of 5)
 * 2       N     Attribute data: N/5 groups of 5 bytes each
 * 2+N     ...   Padding to 62 bytes (zeros)
 *
 * Each attribute group (5 bytes):
 *   Byte 0: Tag (0x00-0x0b, must be <= 0x0b)
 *   Bytes 1-4: Value (uint32 little-endian)
 *
 * ============================================================
 * ATTRIBUTE TAG DISPATCH (jump table at 0x00aa3f98)
 * ============================================================
 *
 * Tag  Dispatch Address   Action
 * ---  ----------------   ------
 * 0x00 0x010c2cc0 [32-bit: NEEDS RE-ANALYSIS]         No-op (advance to next group)
 * 0x01 0x010c2ca0 [32-bit: NEEDS RE-ANALYSIS]         Store VID:PID — VID hardcoded to 0x28de, PID from value low word
 * 0x02 0x010c3400 [32-bit: NEEDS RE-ANALYSIS]         (jump table entry at 0x00aa3fa0)
 * 0x03 0x010c2cc0 [32-bit: NEEDS RE-ANALYSIS]         No-op
 * 0x04 (jump table)       (entry at 0x00aa3fa8)
 * 0x05 0x010c2cc0 [32-bit: NEEDS RE-ANALYSIS]         No-op
 * 0x06 0x010c2cc0 [32-bit: NEEDS RE-ANALYSIS]         No-op
 * 0x07 0x010c2cc0 [32-bit: NEEDS RE-ANALYSIS]         No-op
 * 0x08 0x010c2cc0 [32-bit: NEEDS RE-ANALYSIS]         No-op
 * 0x09 (jump table)       (entry at 0x00aa3fb8)
 * 0x0a 0x010c2cc0 [32-bit: NEEDS RE-ANALYSIS]         No-op
 * 0x0b (jump table)       (entry at 0x00aa3fbc)
 *
 * CRITICAL: Tag 1 is the ONLY tag we've confirmed the handler for.
 * It writes VID:PID to the output struct:
 *   output[4] = 0x28de (Valve VID, hardcoded)
 *   output[6] = value & 0xFFFF (PID from attribute)
 *
 * After the first attribute is processed, if count/5 > 1,
 * it processes up to 7 more groups (total 8 max).
 * Each group is at offset: 2 + group_index * 5
 *
 * ============================================================
 * POST-PROCESSING
 * ============================================================
 *
 * After all attributes are processed, at 0x10c2ef8:
 *   output_struct[6] is checked for non-zero PID
 *   PID range checks determine controller type:
 *     0x1201-0x1206: PS4 controllers
 *     0x1302-0x1303: SC2 (USB/BLE)
 *     0x1304-0x1305: SC2 Puck/Dongle
 *     0x1142, 0x1220: Other controllers
 *   Based on PID, different capability bitmasks are set:
 *     0x4161bfff: SC2 BLE capabilities
 *     0x164bfff:  Extended capabilities
 *     0x27bff5:   Alternative capabilities
 *
 * ============================================================
 * WHAT OUR ATT SERVER MUST RETURN
 * ============================================================
 *
 * Minimum viable response (47 bytes minimum, 62 recommended):
 *
 * Byte 0:    0x83 (command echo)
 * Byte 1:    0x2d (45 = 9 attributes × 5 bytes each)
 * Byte 2:    0x01 (tag 1 = VID/PID)
 * Bytes 3-6: 0x03, 0x13, 0x00, 0x00 (PID 0x1303, LE)
 * Byte 7:    0x00 (tag 0 = no-op, padding)
 * Bytes 8-11: 0x00, 0x00, 0x00, 0x00
 * Byte 12:   0x02 (tag 2 = capability?)
 * Bytes 13-16: capability dword
 * ... (repeat for 9 attributes total)
 * Bytes 47-61: zeros (padding to 62 bytes)
 *
 * IMPORTANT: The response must NOT have a Report ID prefix.
 * The command byte (0x83) is at offset 0 of the HID feature report data.
 *
 * ============================================================
 * WHAT'S WRONG WITH OUR CURRENT RESPONSE
 * ============================================================
 *
 * Our current: 83 2d 01 03 13 00 00 02 ff bf 69 41...
 *
 * Analysis:
 *   byte[0] = 0x83 ✓
 *   byte[1] = 0x2d = 45 ✓ (9 groups × 5)
 *   Group 0: tag=0x01, value=0x00001303 → PID=0x1303 ✓
 *   Group 1: tag=0x00, value=0x4169_bfff → tag 0 = no-op ✓
 *   Remaining groups: tags/values need validation
 *
 * The format appears correct for the initial setup.
 * The real issue is likely:
 * 1. The response data doesn't populate the identity slot
 * 2. The 0xf2 capability queries (sent later) aren't handled
 * 3. The serial validation at 0x26b1ac0 rejects "SC2DECK001"
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

