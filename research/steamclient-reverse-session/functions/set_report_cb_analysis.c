/*
 * set_report_cb() Error Root Cause — COMPLETE ANALYSIS
 *
 * Binary: /usr/libexec/bluetooth/bluetoothd
 * Status: DETERMINED
 *
 * NOTE: This error is in BlueZ (bluetoothd), NOT in steamclient.so.
 * The Steam client binary has ZERO references to set_report_cb, hog-lib,
 * or the "unlikely error" string.
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
 * === EXECUTIVE SUMMARY ===
 *
 * The error "hog-lib.c:set_report_cb() Error setting Report value:
 * Request attribute has encountered an unlikely error" occurs in the
 * BlueZ HOG (HID over GATT) profile when:
 *
 * 1. BlueZ sends an ATT Write Request to write a HID Report value
 * 2. The remote BLE HID device responds with ATT Error Response (code 0x0E)
 * 3. The set_report_cb() callback formats and logs the error
 *
 * This is a REMOTE DEVICE ERROR — the SC2 controller rejected the write.
 * The error does NOT crash bluetoothd but DOES prevent the report from
 * being delivered to the device.
 */

/*
 * === ERROR STRING ASSEMBLY ===
 *
 * The log message is assembled from 4 parts:
 *
 * 1. Source file: "profiles/input/hog-lib.c" at VA 0x00115f13
 * 2. Function:    "set_report_cb" at VA 0x00139a10
 * 3. Format:      "%s:%s() Error setting Report value: %s" at VA 0x00123278
 * 4. ATT error:   "Request attribute has encountered an unlikely error"
 *                 at VA 0x00125a80
 *
 * Full log output:
 *   hog-lib.c:set_report_cb() Error setting Report value:
 *   Request attribute has encountered an unlikely error
 */

/*
 * === ATT ERROR CODE ===
 *
 * "Request attribute has encountered an unlikely error" is ATT error code 0x0E
 * (ATT_ERROR_UNLIKELY = 0x0E).
 *
 * From the ATT specification:
 *   0x0E = Unlikely Error
 *   "If an error response is received, the error code will be listed in the
 *   ATT ERROR PDU. If the error code is Unlikely Error, the request could
 *   not be completed due to an unlikely error on the remote device."
 *
 * This means the SC2 BLE controller itself returned error 0x0E when BlueZ
 * tried to write a HID Report value via ATT Write Request.
 */

/*
 * === ATT OPERATIONS IN HOG PROFILE ===
 *
 * The HOG profile uses these ATT operations:
 *
 * Write Request (0x12):
 *   - Used for SET_REPORT (setting HID report values on the device)
 *   - Requires acknowledgment from the remote device
 *   - If the device rejects it, an ATT Error Response is returned
 *
 * Write Command (0x52):
 *   - Used for OUTPUT reports (no acknowledgment required)
 *   - Does NOT trigger set_report_cb() on failure
 *   - Used for haptic rumble commands (Report ID 0x80)
 *
 * The set_report_cb() error is triggered by Write Request (0x12), NOT
 * Write Command (0x52). This means BlueZ was trying to SET a report
 * value (e.g., LED state, feature configuration), not send an output
 * report (haptic rumble).
 */

/*
 * === ERROR FLOW (from BlueZ source profiles/input/hog-lib.c) ===
 *
 * hog_send_report()
 *   → att_send(device->att, ATT_OP_WRITE_REQ, ... ,
 *              set_report_cb, ...)   ← ATT Write Request
 *   → [remote device responds with ATT Error 0x0E]
 *   → set_report_cb()
 *     → error("%s:%s() Error setting Report value: %s",
 *             "profiles/input/hog-lib.c",
 *             "set_report_cb",
 *             "Request attribute has encountered an unlikely error")
 *     → [clears pending SET_REPORT state]
 *     → [does NOT crash - continues operation]
 */

/*
 * === RELATED ERROR STRINGS IN BLUETOOTHD ===
 *
 * VA        String
 * 0x00139a00  "set_report"
 * 0x00139a10  "set_report_cb"
 * 0x00122b10  "%s:%s() SET_REPORT failed (%u)"
 * 0x00122b30  "%s:%s() Spurious HIDP_HSHK_ERR"
 * 0x00122920  "%s:%s() Old GET_REPORT or SET_REPORT still pending"
 * 0x00123258  "%s:%s() Write output report failed: %s"
 * 0x00123278  "%s:%s() Error setting Report value: %s"
 * 0x00116058  "%s:%s() bt_uhid_send: %s (%d)"
 * 0x001160ab  "%s:%s() SET_REPORT successful"
 * 0x00139e3a  "hidp_send_set_report"
 * 0x00139e50  "hidp_send_output"
 *
 * ATT error strings (0x00125a80 region):
 * 0x00125a80  "Request attribute has encountered an unlikely error"
 * 0x00125ab8  "Encryption required before read/write"
 * 0x00125ae0  "Attribute type is not a supported grouping attribute"
 * 0x00125b18  "Insufficient Resources to complete the request"
 * 0x00125b48  "Internal application error: I/O"
 */

/*
 * === IMPACT ON OUTPUT REPORTS ===
 *
 * Q: Does this error block haptic output reports (0x80)?
 * A: NO — but it indicates a deeper problem.
 *
 * The error is for SET_REPORT (Write Request 0x12), which is used for
 * feature/config reports, NOT output reports (Write Command 0x52).
 *
 * Haptic rumble uses output reports (Write Command 0x52, Report ID 0x80),
 * which do NOT go through set_report_cb(). They use a different path.
 *
 * However, if the SC2 rejects SET_REPORT with error 0x0E, it may also
 * reject output reports. The root cause is likely:
 * 1. The SC2 is not properly initialized (missing feature report setup)
 * 2. The BLE connection is not fully established
 * 3. The SC2 is in lizard mode and ignoring host commands
 * 4. The SC2 requires specific initialization sequence before accepting reports
 */

/*
 * === FALLBACK PATH ===
 *
 * From the "Old GET_REPORT or SET_REPORT still pending" string at
 * 0x00122920, there IS a state machine that handles pending requests.
 * When set_report_cb() fails:
 * 1. The pending state is cleared
 * 2. The HOG profile continues operating
 * 3. No explicit retry is attempted for the failed request
 *
 * There is NO automatic fallback to a different transport or protocol.
 * The error is logged and operation continues.
 */

/*
 * === steamclient.so vs bluetoothd ===
 *
 * steamclient.so:
 *   - Has ZERO references to set_report_cb, hog-lib, "unlikely error"
 *   - Uses feature reports via protobuf IPC (CWriteFeatureReportWorkItem)
 *   - Does NOT directly communicate with BLE HID devices
 *   - Communicates with bluetoothd via IPC
 *
 * bluetoothd (/usr/libexec/bluetooth/bluetoothd):
 *   - Contains the HOG profile (hog-lib.c)
 *   - Handles ATT Write Request/Command for HID reports
 *   - Manages the BLE HID connection
 *   - Contains set_report_cb() and the error handling
 *
 * The flow is:
 *   steamclient.so → protobuf IPC → bluetoothd → ATT → SC2 BLE controller
 */
