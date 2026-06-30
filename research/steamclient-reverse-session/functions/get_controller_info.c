/*
 * CGetControllerInfoWorkItem::RunFunc — Complete Analysis
 *
 * Binary: ~/.steam/debian-installation/ubuntu12_32/steamclient.so (32-bit, 49MB)
 * Function VA: 0x010a3800 [32-bit: NEEDS RE-ANALYSIS]
 * Source: /data/src/clientdll/controller.cpp
 * Status: DETERMINED
 */

⚠️ DISCLAIMER: PARTIALLY CONVERTED — MIXED 32/64-BIT ADDRESSES

Some addresses in this file have been converted to 32-bit equivalents.
Others are still from the 64-bit binary and are INVALID for the running process.

  64-bit binary: ~/.steam/debian-installation/linux64/steamclient.so (46MB, x86_64)
  32-bit binary: ~/.steam/debian-installation/ubuntu12_32/steamclient.so (49MB, i386)

Addresses tagged [32-bit: NEEDS RE-ANALYSIS] are converted but unverified.
Addresses without this tag are still 64-bit and WRONG.
All addresses should be verified via GDB on the running process.

Verified: 2026-06-30
- Steam process: ELF 32-bit LSB pie executable (i386)
- steamclient.so loaded: ubuntu12_32/steamclient.so
- YieldingRunTestProgram string: 0x00bfc7e3 (32-bit) vs 0x00d6d17b (64-bit)


/*
 * === EXECUTIVE SUMMARY ===
 *
 * CGetControllerInfoWorkItem::RunFunc reads a FEATURE REPORT RESPONSE
 * from the controller via IPC pipe (CHIDMessageToRemote.DeviceRead).
 *
 * It sends a DeviceRead request over the named pipe "hiddevicepipesteam",
 * then waits for a CHIDMessageFromRemote.RequestResponse containing the
 * HID data. The read uses vtable+0x28 on the controller object.
 *
 * "Read failure" occurs when:
 *   1. The pipe read returns 0 bytes (pipe closed/broken)
 *   2. The response never arrives (timeout ~20 seconds)
 *   3. The response has wrong request_id or error result
 *
 * The function retries up to 51 times with 100ms sleeps between attempts.
 */

/*
 * === PROTOBUF MESSAGE FORMAT ===
 *
 * REQUEST (CHIDMessageToRemote):
 *   field 1: request_id (uint32)
 *   field 5: device_read = {
 *     field 1: device (uint32)     — device handle
 *     field 2: length (uint32)     — bytes to read (40)
 *     field 3: timeout_ms (int32)  — read timeout
 *   }
 *
 * RESPONSE (CHIDMessageFromRemote):
 *   field 2: response = {
 *     field 1: request_id (uint32) — must match request
 *     field 2: result (int32)      — 0 = success
 *     field 3: data (bytes)        — HID report data (40 bytes)
 *   }
 *
 * The response is deserialized from the pipe and validated:
 *   - request_id must match
 *   - result must be 0
 *   - data must contain valid HID report
 */

/*
 * === DISASSEMBLY (0x010a3800 [32-bit: NEEDS RE-ANALYSIS]) ===
 *
 * rdi = this (CGetControllerInfoWorkItem*)
 * rsi = controller (IController* with vtable)
 *
 * 0x010a3800 [32-bit: NEEDS RE-ANALYSIS]: push ebx/rbp/r12-esi
 * 0x010a380e [32-bit: NEEDS RE-ANALYSIS]: test rsi, rsi           ; if (controller == NULL) return
 * 0x010a3811 [32-bit: NEEDS RE-ANALYSIS]: je 0x10a38b3
 *
 * 0x010a3817 [32-bit: NEEDS RE-ANALYSIS]: lea rax, [0x02c396f0 [32-bit: NEEDS RE-ANALYSIS]]  ; timeout config value
 * 0x010a3824 [32-bit: NEEDS RE-ANALYSIS]: xor r12d, r12d         ; retry_count = 0
 * 0x010a3834 [32-bit: NEEDS RE-ANALYSIS]: lea r14, [ebx+0x84]    ; read buffer at this+0x84
 * 0x010a383b [32-bit: NEEDS RE-ANALYSIS]: imul r13, [rax], 0x989680  ; timeout_value * 10,000,000
 * 0x010a384b [32-bit: NEEDS RE-ANALYSIS]: call fcn.026d7e80      ; get current time
 * 0x010a3850 [32-bit: NEEDS RE-ANALYSIS]: shr r13, 0x12          ; convert to seconds
 * 0x010a3854 [32-bit: NEEDS RE-ANALYSIS]: add r13, rax           ; deadline = current + timeout
 *
 * ; === READ LOOP ===
 * 0x010a3860 [32-bit: NEEDS RE-ANALYSIS]: mov rax, [rbp]         ; load vtable
 * 0x010a3864 [32-bit: NEEDS RE-ANALYSIS]: mov rsi, r14           ; buffer = this+0x84
 * 0x010a3867 [32-bit: NEEDS RE-ANALYSIS]: mov rdi, rbp           ; this = controller
 * 0x010a386a [32-bit: NEEDS RE-ANALYSIS]: call [rax+0x28]        ; *** VTABLE CALL: DeviceRead() ***
 * 0x010a386d [32-bit: NEEDS RE-ANALYSIS]: test eax, eax
 * 0x010a386f [32-bit: NEEDS RE-ANALYSIS]: setg [ebx+0x80]       ; success_flag = (return > 0)
 * 0x010a3876 [32-bit: NEEDS RE-ANALYSIS]: cmp eax, -1
 * 0x010a3879 [32-bit: NEEDS RE-ANALYSIS]: je 0x10a38b3          ; if return == -1, exit (hard error)
 * 0x010a387b [32-bit: NEEDS RE-ANALYSIS]: test eax, eax
 * 0x010a387d [32-bit: NEEDS RE-ANALYSIS]: jle 0x10a38e0         ; if return <= 0, goto SLEEP/RETRY
 *
 * ; === SUCCESS PATH (return > 0) ===
 * 0x010a387f [32-bit: NEEDS RE-ANALYSIS]: cmp r12d, 0x32        ; if retry_count == 50
 * 0x010a3883 [32-bit: NEEDS RE-ANALYSIS]: jne 0x10a38a5         ;   goto deadline check
 * 0x010a3885 [32-bit: NEEDS RE-ANALYSIS]: lea rdx, "too many read failures"
 * 0x010a3898 [32-bit: NEEDS RE-ANALYSIS]: call fcn.026cdc00     ; warning/assertion
 *
 * ; === DEADLINE CHECK ===
 * 0x010a38a5 [32-bit: NEEDS RE-ANALYSIS]: call fcn.026d7e80     ; get current time
 * 0x010a38aa [32-bit: NEEDS RE-ANALYSIS]: cmp r13, rax          ; deadline <= current?
 * 0x010a38ad [32-bit: NEEDS RE-ANALYSIS]: jle 0x10a39b6        ; if expired, goto TIMEOUT
 * 0x010a38b3 [32-bit: NEEDS RE-ANALYSIS]: ...                   ; NORMAL EXIT
 *
 * ; === SLEEP / RETRY PATH ===
 * 0x010a38e0 [32-bit: NEEDS RE-ANALYSIS]: mov edi, 0x64         ; sleep = 100ms
 * 0x010a38e5 [32-bit: NEEDS RE-ANALYSIS]: add r12d, 1          ; retry_count++
 * 0x010a38e9 [32-bit: NEEDS RE-ANALYSIS]: call Sleep(100ms)
 * 0x010a3944 [32-bit: NEEDS RE-ANALYSIS]: lea rax, "Read failure.\n"
 * 0x010a3967 [32-bit: NEEDS RE-ANALYSIS]: call LogMsg
 * 0x010a396c [32-bit: NEEDS RE-ANALYSIS]: cmp r12d, 0x33       ; if retry_count == 51
 * 0x010a3970 [32-bit: NEEDS RE-ANALYSIS]: je 0x10a3885        ;   goto "too many failures"
 * 0x010a3976 [32-bit: NEEDS RE-ANALYSIS]: cmp [ebx+0x80], 0   ; was previous read successful?
 * 0x010a397d [32-bit: NEEDS RE-ANALYSIS]: jne 0x10a38a5       ; if yes, exit (keep result)
 * 0x010a399a [32-bit: NEEDS RE-ANALYSIS]: call fcn.026d7e80   ; get current time
 * 0x010a399f [32-bit: NEEDS RE-ANALYSIS]: cmp r13, rax        ; deadline expired?
 * 0x010a39a2 [32-bit: NEEDS RE-ANALYSIS]: jg 0x10a3860        ; no → RETRY LOOP
 *                                 ; yes → fall through to TIMEOUT
 *
 * ; === TIMEOUT PATH ===
 * 0x010a39b6 [32-bit: NEEDS RE-ANALYSIS]: lea rax, "timeout"
 * 0x010a3a32 [32-bit: NEEDS RE-ANALYSIS]: jmp 0x10a38b3       ; exit
 */

/*
 * === KEY CONSTANTS ===
 *
 * Vtable offset for Read:     0x28 (slot 5)
 * Retry count limit:          51 (0x33)
 * Warning threshold:          50 (0x32)
 * Sleep between retries:      100ms (0x64)
 * Read buffer offset:         this+0x84
 * Success flag offset:        this+0x80
 * Timeout config address:     0x02c396f0 [32-bit: NEEDS RE-ANALYSIS]
 * Timeout value:              ~20 seconds (computed via magic number division)
 */

/*
 * === SUCCESS VS FAILURE ===
 *
 * On SUCCESS (read returns > 0):
 *   - byte [this+0x80] = 1 (success flag)
 *   - Data read into buffer at this+0x84
 *   - Function returns normally
 *
 * On FAILURE (read returns 0 or negative, not -1):
 *   - Increment retry counter
 *   - Sleep 100ms
 *   - Log "Read failure.\n"
 *   - If previous read was successful (this+0x80 == 1), exit early
 *   - Otherwise retry up to 51 times or until deadline
 *
 * On HARD ERROR (read returns -1):
 *   - Immediate exit via je 0x10a38b3
 *   - No retry
 *
 * On TIMEOUT (deadline exceeded):
 *   - Log "timeout"
 *   - Exit
 *
 * On TOO MANY FAILURES (51 retries):
 *   - Log "too many read failures" via assertion
 *   - Exit
 */

/*
 * === WHAT CAUSES "READ FAILURE" ===
 *
 * The vtable+0x28 call sends a CHIDMessageToRemote.DeviceRead request
 * over the IPC pipe and waits for a CHIDMessageFromRemote.RequestResponse.
 *
 * "Read failure" occurs when:
 *
 * 1. PIPE BROKEN: The named pipe "hiddevicepipesteam" is closed or broken.
 *    The read syscall returns 0 bytes or error.
 *
 * 2. NO RESPONSE: The remote side (SDL HID daemon) never sends a response.
 *    This happens if:
 *    - The controller is not connected
 *    - The SDL HID daemon is not running
 *    - The controller doesn't support the requested read
 *
 * 3. WRONG RESPONSE: The response has wrong request_id or error result.
 *    The code checks request_id matching and result == 0.
 *
 * 4. TIMEOUT: No response within ~20 seconds. The deadline is computed
 *    from the timeout config value at 0x02c396f0 [32-bit: NEEDS RE-ANALYSIS].
 *
 * In the user's case (SC2 BLE), the likely cause is:
 *   - The BLE controller doesn't respond to DeviceRead requests
 *   - The IPC pipe to the SDL HID daemon is not established
 *   - The controller firmware doesn't support the feature report query
 */

/*
 * === IPC PIPE MECHANISM ===
 *
 * Source: /data/src/common/hiddevicepipesteam.cpp (string at 0x00c8ce80)
 *
 * The IPC uses named pipe "hiddevicepipesteam" with protobuf messages:
 *
 * REQUEST (CHIDMessageToRemote):
 *   field 1: request_id (uint32)
 *   field 5: device_read = {
 *     field 1: device (uint32)
 *     field 2: length (uint32)
 *     field 3: timeout_ms (int32)
 *   }
 *
 * RESPONSE (CHIDMessageFromRemote):
 *   field 2: response = {
 *     field 1: request_id (uint32)
 *     field 2: result (int32)
 *     field 3: data (bytes)
 *   }
 *
 * The read loop:
 *   1. Serialize CHIDMessageToRemote with DeviceRead command
 *   2. Write to named pipe
 *   3. Wait for response (with timeout)
 *   4. Deserialize CHIDMessageFromRemote
 *   5. Validate request_id and result
 *   6. Copy data to buffer at this+0x84
 */

/*
 * === BINARY REFERENCES ===
 *
 * Function VA:               0x010a3800 [32-bit: NEEDS RE-ANALYSIS]
 * RTTI type name:            0x00aa1a60 ("26CGetControllerInfoWorkItem")
 * RTTI type info:            0x0008dac0
 * "Read failure" string:     0x00b991d5
 * "too many read failures":  0x00b99209
 * "timeout" string:          0x00d12f48
 * "GetControllerInfo failed": 0x00c8f560
 * Timeout config:            0x02c396f0 [32-bit: NEEDS RE-ANALYSIS]
 * IPC pipe source:           0x00c8ce80 (hiddevicepipesteam.cpp)
 * CHIDMessageToRemote:       0x00c94ef7
 * DeviceRead tag:            0x00c94ff6
 * RequestResponse tag:       0x00c95090
 */
