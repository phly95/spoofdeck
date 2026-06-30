/*
 * QueueFetchingControllerDetails Trigger Analysis
 *
 * Binary: ~/.steam/debian-installation/ubuntu12_32/steamclient.so (32-bit, 49MB)
 * Status: DETERMINED
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
 * === WHAT TRIGGERS QueueFetchingControllerDetails? ===
 *
 * QueueFetchingControllerDetails (0x1092820) is called by exactly ONE function:
 *   CallerOfQueueFetchingControllerDetails (0x10b2ca0)
 *
 * This caller is invoked as part of the controller registration flow:
 *
 * 1. Controller connects via BLE
 * 2. BlueZ hog-ll creates /dev/hidrawN
 * 3. Steam opens /dev/hidrawN
 * 4. Feature report handshake begins (GET_ATTRIBUTES, GET_SERIAL, 0xf2)
 * 5. Each response is parsed and stored in controller+0x84..0xd4
 * 6. After all responses are processed:
 *    a. CallerOfQueueFetchingControllerDetails is called
 *    b. It reads controller+0x84..0xd4 (the "ControllerDetails source")
 *    c. It builds a ControllerDetails struct (0x54 bytes) on the stack
 *    d. It calls QueueFetchingControllerDetails
 *    e. QueueFetchingControllerDetails stores to controller+0x1070+id*0x54
 *    f. QueueFetchingControllerDetails sets controller+0x3c = 1 (ready_flag)
 * 7. EYldWaitForControllerDetails unblocks (ready_flag set)
 * 8. BYieldingCompleteSteamControllerRegistration completes
 *
 * NOTE: QueueFetchingControllerDetails sets controller+0x3c = 1, NOT
 * controller+slot*0xe8+0x200. These are different data structures.
 */

/*
 * === CALLER DETAILS (0x10b2ca0) ===
 *
 * Pseudocode:
 *
 * void CallerOfQueueFetchingControllerDetails(CSteamController* controller) {
 *     // Read ControllerDetails source fields from controller object
 *     ControllerDetails details = {0};
 *     details.field_00 = controller->field_84;  // qword
 *     details.field_08 = controller->field_8c;  // qword
 *     details.field_10 = controller->field_94;  // qword
 *     details.field_18 = controller->field_9c;  // qword
 *     details.field_20 = controller->field_a4;  // qword
 *     details.field_28 = controller->field_ac;  // qword
 *     details.field_30 = controller->field_b4;  // qword
 *     details.field_38 = controller->field_bc;  // qword
 *     details.field_40 = controller->field_c4;  // qword
 *     details.field_48 = controller->field_cc;  // qword
 *     details.field_50 = controller->field_d4;  // dword
 *
 *     // Overwrite first dword with controller index
 *     details.field_00 = controller->field_18;  // dword
 *
 *     // Log the operation
 *     LogMessage("GetControllerInfo failed - executed %d, success %d\n", ...);
 *
 *     // Check controller product ID
 *     uint16_t product_id = controller->field_8a;  // word
 *     bool is_known = false;
 *     if (product_id == 0x1142) is_known = true;
 *     if (product_id == 0x1220) is_known = true;
 *     if (product_id >= 0x1201 && product_id <= 0x1206) is_known = true;
 *     if (product_id >= 0x1302 && product_id <= 0x1305) is_known = true;  // SC2 range!
 *
 *     // Determine force_update flag
 *     bool force_update = false;
 *     if (controller->field_28) {  // is_active
 *         if (controller->field_80) {  // flag_80
 *             force_update = true;
 *         }
 *     }
 *
 *     // Call QueueFetchingControllerDetails
 *     QueueFetchingControllerDetails(
 *         controller->field_08,     // sub-controller object
 *         &details,                  // ControllerDetails struct
 *         force_update               // bool
 *     );
 *
 *     // Call tracking function
 *     function_15a6880(global_ptr, 0x102ca7, &details, 0x54, 0);
 * }
 */

/*
 * === WHAT POPULATES controller+0x84..0xd4? ===
 *
 * These fields are populated by the feature report handshake processing.
 * When Steam reads Feature Report 0x00 and gets a response, the response
 * is parsed and stored in the controller object.
 *
 * The feature report processing code at 0x10d4e6c handles the parsing.
 * For each command type (GET_ATTRIBUTES, GET_SERIAL, 0xf2), the response
 * data is stored at specific offsets in the controller object.
 *
 * The fields at controller+0x84..0xd4 are the "ControllerDetails source"
 * that contains the parsed feature report responses. These include:
 * - Product ID (from GET_ATTRIBUTES or PnP ID)
 * - Firmware version (from GET_ATTRIBUTES)
 * - Serial number (from GET_SERIAL)
 * - Capability data (from 0xf2 responses)
 * - Transport type (from connection handler)
 *
 * After all feature report responses are processed, these fields are
 * populated and CallerOfQueueFetchingControllerDetails is called.
 */

/*
 * === TIMING ===
 *
 * The trigger timing is:
 * T+0s:    BLE connection established
 * T+0s:    BlueZ hog-ll opens /dev/hidrawN
 * T+0-1s:  Feature report handshake begins
 *          - GET_ATTRIBUTES (0x83) sent and response received
 *          - GET_SERIAL sent and response received
 *          - 0xf2 sent multiple times for capabilities
 * T+1-2s:  All responses parsed, controller+0x84..0xd4 populated
 * T+1-2s:  CallerOfQueueFetchingControllerDetails called
 *          QueueFetchingControllerDetails called
 *          controller+0x3c = 1 (ControllerDetails ready_flag)
 * T+2s:    EYldWaitForControllerDetails unblocks
 *          BYieldingCompleteSteamControllerRegistration completes
 * T+6s:    Zombie timer fires
 *          GetControllerInfo checks controller+slot*0xe8+0x200
 *          If still 0 → disconnect zombie
 *
 * The race: feature report handshake must complete AND populate the
 * identity slot (controller+slot*0xe8+0x200) before the zombie timer.
 */

/*
 * === KEY INSIGHT ===
 *
 * The CallerOfQueueFetchingControllerDetails is called AFTER the feature
 * report handshake completes. It reads from controller+0x84..0xd4 and
 * stores to controller+0x1070+id*0x54 (ControllerDetails).
 *
 * BUT: the identity slot at controller+slot*0xe8+0x200 is what the zombie
 * check reads. This is a DIFFERENT data structure.
 *
 * The identity slot must be populated by a DIFFERENT code path, likely
 * the feature report response processing itself. When each response is
 * parsed, the data is stored directly in the identity slot.
 *
 * The key question is: what code writes to controller+slot*0xe8+0x200?
 * This is the code that sets the unique_id (and thus the ready flag).
 */
