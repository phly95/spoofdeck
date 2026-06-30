/*
 * HID Write Failure Analysis — Why vtable[0x10] Fails
 *
 * Binary: ~/.steam/debian-installation/ubuntu12_32/steamclient.so (32-bit, 49MB)
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
 * The vtable[0x10] call at 0x010d4e14 [32-bit: NEEDS RE-ANALYSIS] does NOT actually fail in the
 * traditional sense. The issue is that [esi+0x17c] == 0, which causes
 * the entire vtable dispatch to be SKIPPED. The feature report is
 * never sent. The "retry" is the state machine trying again later,
 * but the root cause is that the HID device connection was never
 * fully established for feature report writes.
 */

/*
 * === THE vtable[0x10] DISPATCH ===
 *
 * At 0x010d4e14 [32-bit: NEEDS RE-ANALYSIS]:
 *
 *   0x010d4dfc [32-bit: NEEDS RE-ANALYSIS]: mov rax, [esi+0xa8]     ; load HID device array
 *   0x010d4e08 [32-bit: NEEDS RE-ANALYSIS]: mov rax, [rax+rdx*8]    ; index into array
 *   0x010d4e0e [32-bit: NEEDS RE-ANALYSIS]: mov rdi, [rax]          ; load object pointer
 *   0x010d4e11 [32-bit: NEEDS RE-ANALYSIS]: mov rax, [rdi]          ; load vtable
 *   0x010d4e14 [32-bit: NEEDS RE-ANALYSIS]: call [rax+0x10]         ; dispatch vtable[0x10]
 *
 * The vtable method at 0x017605b0 [32-bit: NEEDS RE-ANALYSIS] is:
 *   mov [rdi+0x20], rsi    ; store context pointer
 *   ret
 *
 * This is a TRIVIAL SETTER — it cannot "fail" in isolation.
 * It stores a context pointer and returns void.
 */

/*
 * === THE REAL PROBLEM: [esi+0x17c] == 0 ===
 *
 * Before reaching 0x010d4e14 [32-bit: NEEDS RE-ANALYSIS], the code checks [esi+0x17c]:
 *
 *   0x0123e5fb: cmp byte [esi+0x17c], 0
 *   0x010d4db0 [32-bit: NEEDS RE-ANALYSIS]: je 0x10d4fd0            ; if flag==0, SKIP vtable dispatch
 *
 * When [esi+0x17c] == 0:
 *   - The vtable dispatch at 0x010d4e14 [32-bit: NEEDS RE-ANALYSIS] is SKIPPED
 *   - Code jumps to 0x10d4fd0 (comparison path)
 *   - No feature report is sent
 *   - The setting remains in the array → retried later
 *
 * [esi+0x17c] is only set to 1 at 0x0178a140 (YieldingRunTestProgram).
 * In normal operation, it's always 0.
 */

/*
 * === THE FEATURE REPORT PATH ===
 *
 * The actual HID write goes through:
 *
 * 1. CWriteFeatureReportWorkItem (RTTI at 0x00aa1880)
 * 2. CHIDMessageToRemote.DeviceSendFeatureReport (protobuf at 0x00c9503d)
 * 3. IPC pipe (hiddevicepipesteam.cpp at 0x00c8ce9a)
 * 4. CHIDIOThread processes the write (0x00b9994a)
 * 5. SDL_hid_send_feature_report (resolved via dlsym at 0x00dfb22b)
 *
 * The vtable at 0x02c69a10 [32-bit: NEEDS RE-ANALYSIS] has send_feature_report at offset 0x18.
 * The function is resolved dynamically at startup.
 */

/*
 * === WHY [esi+0x17c] IS 0 ===
 *
 * The flag [esi+0x17c] is set at 0x0178a140:
 *
 *   0x0178a140: mov byte [esi+0x17c], 1
 *   0x0156782a [32-bit: NEEDS RE-ANALYSIS]: call 0x2844a00          ; StartRetryTimer
 *   0x01567847 [32-bit: NEEDS RE-ANALYSIS]: lea rsi, "YieldingRunTestProgram"
 *
 * This is in a TEST/INITIALIZATION path. In normal controller
 * operation, this path is NOT taken. The flag stays 0.
 *
 * The flag is cleared at 0x0119f3b1 [32-bit: NEEDS RE-ANALYSIS]:
 *   0x0119f3b1 [32-bit: NEEDS RE-ANALYSIS]: mov byte [rdi+0x17c], 0
 *
 * This is in a cleanup function that calls vtable[0x228].
 *
 * CONCLUSION: [esi+0x17c] is a "test mode" flag. When it's 0,
 * the state machine skips the actual HID write and falls through
 * to a comparison path that either no-ops or calls an alternate
 * dispatch at 0x010d5260 [32-bit: NEEDS RE-ANALYSIS].
 */

/*
 * === THE BUFFER SIZE CHECK ===
 *
 * After the vtable call (if it happens), there's a buffer check:
 *
 *   0x010d4e49 [32-bit: NEEDS RE-ANALYSIS]: mov edi, [esi+0xe4]    ; current buffer index
 *   0x010d4e50 [32-bit: NEEDS RE-ANALYSIS]: lea edx, [rdi+1]       ; index + 1
 *   0x010d4e53 [32-bit: NEEDS RE-ANALYSIS]: cmp edx, eax           ; eax = [esi+0xb8] (max)
 *   0x010d4e55 [32-bit: NEEDS RE-ANALYSIS]: jl 0x10d50f8           ; if fits, continue
 *   0x010d4e5b [32-bit: NEEDS RE-ANALYSIS]: mov dword [esi+0xe4], 0 ; OVERFLOW: reset
 *   0x010d4e66 [32-bit: NEEDS RE-ANALYSIS]: mov r14d, 1             ; set error flag
 *
 * This checks if the feature report data fits in the IPC pipe buffer.
 * If it doesn't, the buffer is reset and an error is flagged.
 *
 * However, this check is ONLY reached if the vtable dispatch at
 * 0x010d4e14 [32-bit: NEEDS RE-ANALYSIS] actually executes. When [esi+0x17c]==0, the dispatch
 * is skipped, so this check is also skipped.
 */

/*
 * === IPC PATH DETAILS ===
 *
 * The feature report goes through:
 *
 * 1. CHIDMessageToRemote.DeviceSendFeatureReport (protobuf)
 *    - Field 1: device (uint32)
 *    - Field 2: data (bytes) — the 64-byte feature report
 *
 * 2. IPC pipe via hiddevicepipesteam.cpp
 *    - Source: /data/src/common/hiddevicepipesteam.cpp
 *    - The pipe connects steamclient.so to the HID I/O thread
 *
 * 3. CHIDIOThread processes the message
 *    - "CSteamController::CHIDIOThread" at 0x00b9994a
 *    - "CSteamController::CHIDIOThread::CWorkItemThread" at 0x00d73b6a
 *
 * 4. SDL_hid_send_feature_report is called
 *    - Resolved via dlsym at startup (0x00dfb22b)
 *    - Stored at 0x02c69a28 [32-bit: NEEDS RE-ANALYSIS] (vtable + 0x18)
 *    - The actual SDL function pointer
 *
 * 5. BlueZ/bluetoothd receives the write
 *    - For BLE: ATT Write Request (0x12) or Write Command (0x52)
 *    - For USB: hidraw write
 *    - For Dongle: ESB protocol
 */

/*
 * === ERROR STRINGS ===
 *
 * 0x00d23fac: "Error uploading firmware. Failed to write feature report"
 * 0x00ce027a: "FWU Send complete feature report failed"
 * 0x00d02f59: "Update start cmd write feature report failed"
 * 0x00d40ec2: "Erase all write feature report failed"
 * 0x00ba4c48: "Erase page write feature report failed"
 *
 * All error strings are in FIRMWARE UPDATE paths, not SET_SETTINGS.
 * There is no error string for SET_SETTINGS write failure.
 */

/*
 * === BINARY REFERENCES ===
 *
 * vtable[0x10] dispatch: 0x010d4e14 [32-bit: NEEDS RE-ANALYSIS]
 * vtable method: 0x017605b0 [32-bit: NEEDS RE-ANALYSIS] (trivial setter)
 * [esi+0x17c] check: 0x0123e5fb
 * [esi+0x17c] set: 0x0178a140
 * [esi+0x17c] cleared: 0x0119f3b1 [32-bit: NEEDS RE-ANALYSIS]
 * SDL_hid_send_feature_report string: 0x00cbb561
 * dlsym resolution: 0x00dfb22b
 * vtable storage: 0x02c69a28 [32-bit: NEEDS RE-ANALYSIS]
 * CHIDMessageToRemote: 0x00c9503d
 * IPC pipe source: 0x00c8ce9a (hiddevicepipesteam.cpp)
 * CHIDIOThread: 0x00b9994a
 * CWriteFeatureReportWorkItem RTTI: 0x00aa1880
 */
