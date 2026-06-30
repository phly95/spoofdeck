/*
 * Analysis of V_strncmp at 0x26b1ac0 in steamclient.so
 * 
 * This is Valve's V_strncmp from /data/src/vstdlib/strtools.cpp
 * It's a bounded string comparison function.
 *
 * Prototype:
 *   int V_strncmp(const char* s1, const char* s2, size_t count)
 *
 * Parameters (System V AMD64 ABI):
 *   rdi = s1   (first string — serial data from response)
 *   rsi = s2   (second string — pattern at 0xd69c60)
 *   rdx = count (max bytes to compare)
 *
 * Return values:
 *   0  — strings match (up to count bytes, or null terminator hit)
 *   -1 — s1 < s2 at first mismatch
 *   +1 — s1 > s2 at first mismatch
 *
 * Assembly breakdown:
 *
 * 0x26b1ac0: push r13, r12, rbp, ebx, sub rsp, 8
 *   Save callee-saved registers.
 *
 * 0x26b1ac4: mov r12, rdx    ; r12 = count (preserved in register)
 * 0x26b1ac8: mov rbp, rdi    ; rbp = s1
 * 0x26b1acc: mov ebx, rsi    ; ebx = s2
 *
 * Null-pointer assertions:
 *   "count == 0 || s1 != NULL"  (strtools.cpp line 0xe8)
 *   "count == 0 || s2 != NULL"  (strtools.cpp line 0xe9)
 *
 * 0x26b1af2: test r12, r12  ; count == 0?
 * 0x26b1af5: je 0x26b1b78   ; return 0 (equal) if count is 0
 *
 * Main comparison loop:
 *   0x26b1afb: xor eax, eax      ; i = 0
 *   0x26b1b0d: movzx edx, byte [rbp + rax]  ; edx = s1[i]
 *   0x26b1b12: cmp dl, byte [ebx + rax]     ; compare s1[i] vs s2[i]
 *   0x26b1b15: je 0x26b1b00                  ; if equal, continue
 *
 *   Mismatch path:
 *     0x26b1b17: setge al           ; al = (s1[i] >= s2[i]) ? 1 : 0
 *     0x26b1b27: lea eax, [rax+rax-1]  ; return -1 or +1
 *
 *   Equal path (loop back):
 *     0x26b1b00: test dl, dl        ; s1[i] == '\0'? (null terminator)
 *     0x26b1b02: je return_0        ; yes → strings equal
 *     0x26b1b04: add rax, 1         ; i++
 *     0x26b1b08: cmp r12, rax       ; i == count?
 *     0x26b1b0b: je return_0        ; all count bytes matched
 *
 * CALL SITE at 0x10c29b3:
 *   rdi = r12 = [rbp-0x17d]   — pointer to first byte of serial string
 *   rsi = 0xd69c60            — str.FH_cz (pattern string)
 *   rdx = 1                   — count = 1 byte
 *
 * The serial data layout:
 *   Response buffer at [rbp-0x140]:
 *     [rbp-0x140+0] = 0xAE  (command marker)
 *     [rbp-0x140+1] = 0x15  (command type)
 *     [rbp-0x140+2] = 0x01  (status: success)
 *     [rbp-0x140+3..22] = serial string (20 bytes)
 *
 *   Copied to [rbp-0x180]:
 *     [rbp-0x180+0] = 0xAE
 *     [rbp-0x180+3] = serial[0]  ← r12 points here
 *
 *   Pattern at 0xd69c60:
 *     [0xd69c60] = 0x46 = 'F'   ← first byte of pattern
 *
 * RESULT: V_strncmp(serial[0], "FH_cz...", 1)
 *   Compares ONLY the first byte of the serial against 'F' (0x46).
 *
 * CONCLUSION:
 *   The validation checks if serial[0] == 'F' (0x46).
 *   Our serial "28de-1303-2efea7d" has serial[0] = '2' (0x32).
 *   0x32 != 0x46 → validation FAILS.
 *
 *   When validation FAILS (0x10c20a3):
 *     Serial is replaced with "DOCKED_SLOT" (20 bytes via V_memcpy).
 *
 *   When validation PASSES (0x10c29c4):
 *     20 bytes of serial data are copied to controller info struct
 *     at offset 0x3d: V_memcpy(controller_info+0x3d, serial_data, 0x14).
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

