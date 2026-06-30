/*
 * ATT Notification Trigger Analysis — Can We Trigger Slot Population via Notification?
 *
 * Binary: ~/.steam/debian-installation/ubuntu12_32/steamclient.so (32-bit, 49MB)
 * Status: DETERMINED (NO — ATT notifications won't work)
 *
 * EXECUTIVE SUMMARY
 * =================
 * ATT Notifications (0x1B) on the Feature Report characteristic handle
 * will NOT trigger the feature report response processing code in Steam.
 *
 * The reason: hog-lib.c's notification handler only processes Input Reports,
 * not Feature Reports. Feature Reports are accessed via the GET_REPORT
 * path (ATT Read Request 0x0A), not via notifications.
 *
 * THE NOTIFICATION PATH IN HOG-LIB.C
 * ====================================
 *
 * When BlueZ hog-lib.c receives an ATT Notification (0x1B):
 *
 * 1. The notification arrives on a subscribed characteristic handle
 * 2. hog-lib.c's report_value_cb() is called
 * 3. report_value_cb() checks the Report Reference descriptor:
 *    - Report Type = 0x01 (Input) → process as input report
 *    - Report Type = 0x02 (Output) → ignore (output reports are sent, not received)
 *    - Report Type = 0x03 (Feature) → NOT HANDLED by notification path
 * 4. For Input Reports:
 *    a. The Report ID is extracted from the Report Reference descriptor
 *    b. The report data is formatted as a HID report
 *    c. bt_uhid_input() is called to send the data to the kernel
 *    d. The kernel creates /dev/input/eventN events
 *
 * CRITICAL: Feature Reports are NOT processed through the notification path.
 * They are processed through the GET_REPORT/SET_REPORT path, which is
 * triggered by SDL_hid_get_feature_report() / SDL_hid_send_feature_report().
 *
 * THE GET_REPORT PATH
 * ===================
 *
 * When Steam calls SDL_hid_get_feature_report():
 *
 * 1. SDL calls ioctl(fd, HIDIOCGFEATURE(len), buf) on /dev/hidrawN
 * 2. The kernel's hidraw driver sends UHID_GET_REPORT to BlueZ
 * 3. BlueZ hog-lib.c's get_report_cb() is called
 * 4. get_report_cb() sends ATT Read Request (0x0A) to the peripheral
 * 5. The peripheral responds with ATT Read Response (0x0B)
 * 6. get_report_cb() returns the data to the kernel
 * 7. The kernel returns the data to SDL
 * 8. SDL returns the data to Steam
 * 9. Steam's state machine at 0x10d4e6c processes the response
 *
 * THE BLOCKER
 * ===========
 *
 * Step 3-4 is the blocker. hog-lib.c's get_report_cb() should send
 * ATT Read Request (0x0A) for the Feature Report characteristic.
 * But it doesn't, because:
 *
 * a) The Feature Report characteristic may not have the correct
 *    Report Reference descriptor (Report Type = 0x03)
 * b) hog-lib.c may not have registered a GET_REPORT handler for
 *    this characteristic
 * c) The UHID_GET_REPORT request may not reach hog-lib.c
 *
 * WHY NOTIFICATIONS WON'T WORK
 * ============================
 *
 * If we send an ATT Notification (0x1B) on handle 0x0024 (Feature Report):
 *
 * 1. BlueZ receives the notification
 * 2. hog-lib.c checks if the handle is subscribed (CCCD written)
 * 3. If subscribed, report_value_cb() is called
 * 4. report_value_cb() checks the Report Reference descriptor
 * 5. If Report Type = 0x03 (Feature), the notification is IGNORED
 *    because hog-lib.c doesn't process Feature Report notifications
 *
 * Even if hog-lib.c DID process the notification, it would call
 * bt_uhid_input() which sends the data as an Input Report to the kernel.
 * This is NOT the same as a Feature Report read response.
 *
 * Steam's state machine at 0x10d4e6c processes Feature Report responses
 * that come through the GET_REPORT path, NOT through input events.
 *
 * ALTERNATIVE: CAN WE TRIGGER GET_REPORT?
 * ========================================
 *
 * The GET_REPORT path is triggered by:
 *   SDL_hid_get_feature_report() → ioctl(HIDIOCGFEATURE) → UHID_GET_REPORT
 *
 * This is called by Steam's feature report processing code at 0x10d4e6c:
 *   0x10d4e83: call qword [rax + 0x130]  ; vtable[0x130] = get_feature_report
 *
 * The vtable[0x130] function reads the feature report from the HID device.
 * For BLE controllers, this goes through the kernel's uhid driver, which
 * sends UHID_GET_REPORT to BlueZ, which should send ATT Read Request.
 *
 * If we can make BlueZ send the ATT Read Request, our ATT server can
 * respond with the stored data, and Steam will process it.
 *
 * THE REAL FIX
 * ============
 *
 * The real fix is to make BlueZ's hog-lib.c send ATT Read Requests
 * for Feature Reports. This requires:
 *
 * 1. Ensuring the Feature Report characteristic has a Report Reference
 *    descriptor with Report Type = 0x03 (Feature)
 * 2. Ensuring hog-lib.c registers a GET_REPORT handler for this characteristic
 * 3. Ensuring the UHID_GET_REPORT request reaches hog-lib.c
 *
 * Alternatively, we could modify BlueZ's source code to send ATT Read
 * Requests proactively, without waiting for a host request.
 *
 * WHAT TO TRY FIRST
 * =================
 *
 * 1. Check if our GATT database has the correct Report Reference descriptor
 *    for the Feature Report characteristic (handle 0x0024)
 * 2. Check if BlueZ's hog-lib.c sends any ATT requests for this handle
 * 3. If not, try modifying hog-lib.c to send ATT Read Request on connection
 * 4. As a workaround, try sending ATT Notification and see if hog-lib.c
 *    processes it (unlikely, but worth testing)
 *
 * BTMON CAPTURE
 * ==============
 *
 * To verify whether BlueZ sends ATT Read Requests, capture HCI traffic:
 *   btmon -t -w /tmp/capture.log &
 *   # Then connect and wait for feature report processing
 *   grep "Read Request" /tmp/capture.log
 *   grep "Read Response" /tmp/capture.log
 *
 * If there are NO Read Request/Response pairs for handle 0x0024,
 * then hog-lib.c is not sending the requests.
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

