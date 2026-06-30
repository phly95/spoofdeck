/*
 * IPC Message Format — CGetControllerInfoWorkItem Protocol
 *
 * Binary: ~/.steam/debian-installation/ubuntu12_32/steamclient.so (32-bit, 49MB)
 * Status: DETERMINED
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


/*
 * === EXECUTIVE SUMMARY ===
 *
 * CGetControllerInfoWorkItem uses CHIDMessageToRemote.DeviceRead to read
 * HID feature reports from the controller via IPC pipe. The response is
 * CHIDMessageFromRemote.RequestResponse containing the HID data.
 *
 * The IPC pipe is "hiddevicepipesteam" (named pipe between steamclient.so
 * and the SDL HID daemon).
 */

/*
 * === PROTOBUF SCHEMA (Reconstructed from Binary) ===
 *
 * // Request: steamclient → SDL HID daemon
 * message CHIDMessageToRemote {
 *   uint32 request_id = 1;
 *   oneof command {
 *     DeviceOpen device_open = 2;
 *     DeviceClose device_close = 3;
 *     DeviceWrite device_write = 4;
 *     DeviceRead device_read = 5;           // ← Used by CGetControllerInfoWorkItem
 *     DeviceSendFeatureReport device_send_feature_report = 6;
 *     DeviceGetFeatureReport device_get_feature_report = 7;
 *     DeviceGetVendorString device_get_vendor_string = 8;
 *     DeviceGetProductString device_get_product_string = 9;
 *     DeviceGetSerialNumberString device_get_serial_number_string = 10;
 *     DeviceStartInputReports device_start_input_reports = 11;
 *     DeviceRequestFullReport device_request_full_report = 12;
 *     bool device_disconnect = 13;
 *   }
 * }
 *
 * // DeviceRead command
 * message DeviceRead {
 *   uint32 device = 1;        // device handle
 *   uint32 length = 2;        // bytes to read (40)
 *   int32 timeout_ms = 3;     // read timeout
 * }
 *
 * // Response: SDL HID daemon → steamclient
 * message CHIDMessageFromRemote {
 *   oneof command {
 *     UpdateDeviceList update_device_list = 1;
 *     RequestResponse response = 2;        // ← Response to DeviceRead
 *     DeviceInputReports reports = 3;      // async input reports
 *     CloseDevice close_device = 4;
 *     CloseAllDevices close_all_devices = 5;
 *   }
 * }
 *
 * // RequestResponse
 * message RequestResponse {
 *   uint32 request_id = 1;    // must match request
 *   int32 result = 2;         // 0 = success
 *   bytes data = 3;           // HID report data (40 bytes)
 * }
 *
 * // DeviceInputReports (async)
 * message DeviceInputReports {
 *   repeated DeviceInputReport device_reports = 1;
 * }
 *
 * message DeviceInputReport {
 *   uint32 device = 1;
 *   repeated CHIDDeviceInputReport reports = 2;
 * }
 *
 * message CHIDDeviceInputReport {
 *   bytes full_report = 1;
 *   bytes delta_report = 2;
 *   uint32 delta_report_size = 3;
 *   uint32 delta_report_crc = 4;
 * }
 */

/*
 * === PROTOBUF FIELD TAGS (from Binary) ===
 *
 * CHIDMessageToRemote:           0x00c94ef7
 * DeviceOpen tag:                0x00c94f4a
 * DeviceClose tag:               0x00c94f83
 * DeviceWrite tag:               0x00c94fbd
 * DeviceRead tag:                0x00c94ff6  ← Used by CGetControllerInfoWorkItem
 * DeviceSendFeatureReport tag:   0x00c9503d
 * DeviceGetFeatureReport tag:    0x00c95090
 * DeviceGetVendorString tag:     0x00c950e1
 * DeviceGetProductString tag:    0x00c95132
 * DeviceGetSerialNumberString:   0x00c9518a
 * DeviceStartInputReports:       0x00c951e2
 * DeviceRequestFullReport:       0x00c95236
 * DeviceDisconnect:              0x00c95281
 *
 * RequestResponse:               0x00c95090
 * UpdateDeviceList:              0x00c95583
 * DeviceInputReports:            0x00c955fb
 */

/*
 * === READ FLOW ===
 *
 * 1. CGetControllerInfoWorkItem constructs CHIDMessageToRemote:
 *    - request_id = unique ID
 *    - device_read.device = controller device handle
 *    - device_read.length = 40 (bytes)
 *    - device_read.timeout_ms = configured timeout
 *
 * 2. Message serialized with protobuf and written to named pipe
 *
 * 3. Waits for response from pipe (with timeout)
 *
 * 4. Deserializes CHIDMessageFromRemote
 *
 * 5. Validates response:
 *    - response field (field 2) must be present
 *    - request_id must match
 *    - result must be 0
 *    - data must contain valid HID report
 *
 * 6. Copies data to buffer at this+0x84
 */

/*
 * === WHY IT FAILS FOR SC2 BLE ===
 *
 * The "Read failure" occurs because:
 *
 * 1. The IPC pipe "hiddevicepipesteam" connects steamclient.so to the
 *    SDL HID daemon. For BLE controllers, the SDL HID daemon uses
 *    bluetoothd (BlueZ) to communicate with the controller.
 *
 * 2. CGetControllerInfoWorkItem sends a DeviceRead request, expecting
 *    the SDL HID daemon to read a feature report from the controller
 *    and return the data.
 *
 * 3. For SC2 BLE, the feature report read may fail because:
 *    - The SC2 doesn't support the requested feature report
 *    - The BLE connection is not fully established
 *    - The BlueZ HOG profile rejects the read request
 *    - The IPC pipe is not connected to the SDL HID daemon
 *
 * 4. The error "set_report_cb() Error setting Report value: Request
 *    attribute has encountered an unlikely error" in bluetoothd
 *    indicates the SC2 rejects ATT Write Requests, which may also
 *    affect feature report reads.
 *
 * 5. The 10+ "Read failure" messages indicate the function retries
 *    10+ times before giving up (up to 51 retries with 100ms sleep).
 */

/*
 * === KEY STRINGS ===
 *
 * 0x00c94ef7: "CHIDMessageToRemote"
 * 0x00c9503d: "CHIDMessageToRemote.DeviceSendFeatureReport"
 * 0x00c95090: "CHIDMessageToRemote.DeviceGetFeatureReport"
 * 0x00b3fbc0: "CHIDMessageToRemote_DeviceSendFeatureReport"
 * 0x00b3fbd6: "CHIDMessageToRemote_DeviceGetFeatureReport"
 * 0x00c8ce80: "hiddevicepipesteam.cpp"
 * 0x00c8ce9a: "hiddevicepipesteam.cpp" (second reference)
 */
