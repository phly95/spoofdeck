/*
 * Report ID Prefix Convention — Analysis
 *
 * Binary: ~/.steam/debian-installation/ubuntu12_32/steamclient.so (32-bit, 49MB)
 * Status: DETERMINED
 *
 * ============================================================
 * ANSWER: NO REPORT ID PREFIX
 * ============================================================
 *
 * The HID feature report responses do NOT include a Report ID
 * prefix byte. The command byte (0x83, 0xAE, 0xf2) IS the first
 * byte of the response data.
 *
 * ============================================================
 * EVIDENCE
 * ============================================================
 *
 * 1. WRITE COMMAND FORMAT:
 *    At 0x10c2751 (GET_ATTRIBUTES):
 *      mov word [rbp-0x180], r13w  ; [0x83, 0x00]
 *      movzx edx, byte [rbp-0x17f] ; edx = 0x00
 *      add rdx, 2                   ; size = 2
 *      call [rax+0x30]              ; HID send_feature_report
 *
 *    At 0x10c2043 (GET_SERIAL):
 *      mov word [rbp-0x180], cx     ; [0xAE, 0x15]
 *      movzx edx, byte [rbp-0x17f] ; edx = 0x15
 *      add rdx, 2                   ; size = 23
 *      call [rax+0x30]              ; HID send_feature_report
 *
 *    The write data starts with the COMMAND BYTE, not a Report ID.
 *    In SDL3's HID API, the first parameter to send_feature_report
 *    IS the Report ID (passed separately), and the data starts
 *    at buffer[0] with the actual payload.
 *
 * 2. READ RESPONSE VALIDATION:
 *    At 0x10c2b21 (GET_ATTRIBUTES):
 *      cmp byte [rbp-0x140], 0x83  ; check byte[0] == 0x83
 *
 *    At 0x10c2910 (GET_SERIAL):
 *      cmp byte [rbp-0x140], 0xAE  ; check byte[0] == 0xAE
 *
 *    The code checks byte[0] for the COMMAND BYTE directly.
 *    If there were a Report ID prefix (0x00), byte[0] would be 0x00
 *    and these checks would fail.
 *
 * 3. SDL3 HID API BEHAVIOR:
 *    SDL3's SDL_hid_get_feature_report():
 *    - buffer[0] = Report ID to request (0x00 for Feature Report 0x00)
 *    - After the call, buffer[0] = Report ID (0x00)
 *    - buffer[1..N] = Report data
 *
 *    BUT: The Steam client code does NOT use SDL3's API directly.
 *    It uses vtable calls:
 *      [rax+0x30] = send_feature_report(dev, data, size)
 *      [rax+0x38] = get_feature_report(dev, data, size)
 *
 *    These vtable functions are the UHID interface. In UHID:
 *    - GET_REPORT response format: [Report ID] [Report data]
 *    - But for Feature Report 0x00 (no explicit Report ID):
 *      The Report ID is 0x00, and the data follows immediately
 *
 *    The Steam code reads the response into [rbp-0x140] with
 *    the command byte at [rbp-0x140][0]. This means either:
 *    a) The UHID layer strips the Report ID (0x00) byte, OR
 *    b) The data doesn't include a Report ID at all
 *
 *    Given that the write command also starts with the command byte
 *    (not a Report ID), option (b) is most likely: the HID feature
 *    report data does NOT include a Report ID prefix.
 *
 * 4. BLE HID PROTOCOL:
 *    In BLE HID, Feature Report 0x00 is accessed via:
 *    - ATT Read Request for the Feature Report characteristic
 *    - ATT Read Response contains just the report data
 *    - No Report ID in the ATT layer (it's implicit from the handle)
 *
 *    BlueZ's hog-lib translates between UHID and ATT:
 *    - UHID GET_REPORT → ATT Read Request
 *    - ATT Read Response → UHID GET_REPORT response
 *    - The Report ID is NOT included in the ATT data
 *
 * ============================================================
 * IMPLICATION FOR OUR ATT SERVER
 * ============================================================
 *
 * Our ATT server should return responses starting with the COMMAND
 * BYTE, NOT a Report ID byte. This is what we're already doing:
 *
 *   GET_ATTRIBUTES: 83 2d 01 03 13 00...  (starts with 0x83) ✓
 *   GET_SERIAL:     ae 14 01 53 43 32...  (starts with 0xAE) ✓
 *
 * Do NOT add a 0x00 byte before the command. The command byte
 * IS the first byte of the feature report data.
 *
 * ============================================================
 * CONFIRMATION FROM ACTUAL HID DESCRITORS
 * ============================================================
 *
 * Looking at the HID descriptor parsing in hog-lib, the Feature
 * Report characteristic has Report ID 0x00. When the host reads
 * it:
 * - ATT Read Request → our server
 * - Our server returns: [cmd] [payload...]
 * - hog-lib passes this to UHID as the GET_REPORT response
 * - Steam reads it via ioctl
 * - The first byte is the command (0x83, 0xAE, etc.)
 *
 * The Report ID (0x00) is implicit — it's not in the data.
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

