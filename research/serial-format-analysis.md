/*
 * Serial Format Analysis for Steam Client SC2 Controller Validation
 *
 * ============================================================
 * THE VALIDATION FUNCTION (0x26b1ac0)
 * ============================================================
 *
 * The function at 0x26b1ac0 is V_strncmp from Valve's vstdlib/strtools.cpp.
 * It's a standard bounded string comparison: compares up to `count` bytes.
 *
 * CALL SITE at 0x10c29b3:
 *   V_strncmp(serial_data, pattern, count)
 *   
 *   rdi (s1)  = [rbp-0x17d]  → first byte of serial string in GET_SERIAL response
 *   rsi (s2)  = 0xd69c60      → "FH_cz..." pattern (UTF-16LE string)
 *   rdx (cnt) = 1             → count = 1 BYTE
 *
 * CRITICAL FINDING: count=1 means only the FIRST BYTE is compared.
 *
 * The pattern at 0xd69c60:
 *   First byte = 0x46 = ASCII 'F'
 *   Full UTF-16LE string: "FH_cz~..." (wide chars, but compared byte-by-byte)
 *
 * The serial data layout in the response buffer:
 *   [rbp-0x180] = 0xAE (response marker)
 *   [rbp-0x17f] = 0x15 (response type) 
 *   [rbp-0x17e] = 0x01 (status byte)
 *   [rbp-0x17d] = serial[0] ← THIS is what r12/rdi points to
 *   [rbp-0x17c] = serial[1]
 *   ...
 *
 * V_strncmp with count=1 does:
 *   Compare serial[0] vs pattern[0]
 *   If serial[0] == pattern[0]: return 0 (PASS)
 *   If serial[0] != pattern[0]: return -1 or +1 (FAIL)
 *
 * pattern[0] = 0x46 = 'F'
 * Our serial[0] = '2' (from "28de-1303-2efea7d")
 * Result: FAIL (0x32 != 0x46)
 *
 * ============================================================
 * WHAT HAPPENS AFTER VALIDATION
 * ============================================================
 *
 * Call site flow (0x10c29b3):
 *   call V_strncmp
 *   test eax, eax
 *   jne 0x10c20a3    ; if FAILED, jump to fallback
 *
 * IF VALIDATION PASSES (V_strncmp returns 0):
 *   0x10c29c4: mov edx, 0x14             ; 20 bytes
 *   0x10c29c9: mov rsi, r12              ; serial data source
 *   0x10c29cc: call 0x26b2800            ; V_memcpy → copy serial to controller_info+0x3d
 *   0x10c29d1: jmp 0x10c20b4             ; continue to controller info setup
 *
 * IF VALIDATION FAILS (V_strncmp returns non-zero):
 *   0x10c20a3: lea rdi, [r14 + 0x3d]    ; dest = controller_info+0x3d
 *   0x10c20a3: lea rsi, str.DOCKED_SLOT  ; "DOCKED_SLOT"
 *   0x10c20aa: mov edx, 0x14             ; 20 bytes
 *   0x10c20af: call 0x26b2800            ; V_memcpy → copies "DOCKED_SLOT" as serial
 *   0x10c20b4: ...                        ; continue to controller info setup
 *
 * ============================================================
 * SERIAL FORMAT REQUIRED
 * ============================================================
 *
 * The validation checks: does the FIRST BYTE of the serial equal 'F' (0x46)?
 * 
 * That's it. Only 1 byte is compared. The full pattern at 0xd69c60
 * doesn't matter — only the first byte matters because count=1.
 *
 * OUR SERIAL "28de-1303-2efea7d" FAILS because:
 *   serial[0] = '2' (0x32) ≠ 'F' (0x46)
 *
 * TO PASS VALIDATION:
 *   The serial MUST start with 'F' (0x46).
 *   Any 20-byte string starting with 'F' will pass V_strncmp.
 *
 * Real SC2 controller serial format: UNKNOWN.
 * Only requirement verified: First byte must be 'F' (0x46).
 * No real SC2 device was available to capture serials.
 *
 * ============================================================
 * THE "Invalid or missing" LOG MESSAGE
 * ============================================================
 *
 * String at 0xcc4860: "Controller has an Invalid or missing unit serial number %s, setting to '%s'\n"
 *
 * This is a SEPARATE validation that happens AFTER the GET_SERIAL handler.
 * It runs during CGetControllerInfoWorkItem::RunFunc.
 *
 * Flow:
 *   1. GET_SERIAL handler reads serial from device
 *   2. V_strncmp checks first byte == 'F'
 *   3. If fails → serial becomes "DOCKED_SLOT"  
 *   4. Controller info is registered with Steam
 *   5. Steam's registration function validates the serial
 *   6. If serial is "DOCKED_SLOT" or "SC2DECK001" → "Invalid or missing" error
 *   7. Steam generates fallback: "28de-1303-XXXXXXXX" (VID-PID-hash format)
 *
 * The fallback "28de-1303-XXXXXXXX" format:
 *   - VID: 0x28DE (Valve, little-endian: DE 28)
 *   - PID: 0x1303 (SC2 BLE, little-endian: 03 13)
 *   - XXXXXXXX: hash derived from controller address or other data
 *
 * ============================================================
 * ROOT CAUSE & FIX
 * ============================================================
 *
 * ROOT CAUSE: Our serial "28de-1303-2efea7d" starts with '2', not 'F'.
 * The V_strncmp check at 0x10c29b3 fails, serial becomes "DOCKED_SLOT",
 * and Steam's registration function rejects "DOCKED_SLOT" as invalid.
 *
 * FIX: Change the serial in the GET_SERIAL response to start with 'F'.
 * 
 * Required: First byte must be 'F' (0x46) to pass V_strncmp validation.
 * Length: 20 bytes (from V_memcpy size 0x14).
 * Internal format: Unknown without a real SC2 device to capture.
 *
 * Recommendation: Use "F" + any 19 bytes. Test against Steam to see if
 * secondary validation rejects it.
 *
 * Note: The full serial also needs to survive Steam's secondary validation
 * in CGetControllerInfoWorkItem::RunFunc. If Steam also checks the format
 * beyond just the first byte, we may need the exact Valve serial format.
 * But the V_strncmp check is the first gate, and it only checks byte 0.
 */
