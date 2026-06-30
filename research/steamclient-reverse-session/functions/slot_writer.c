/*
 * Slot Writer Analysis — What Code Writes to controller+slot*0xe8+0x200
 *
 * Binary: ~/.steam/debian-installation/ubuntu12_32/steamclient.so (32-bit, 49MB)
 * Status: DETERMINED
 *
 * EXECUTIVE SUMMARY
 * =================
 * The identity slot at controller+slot*0xe8+0x200 (unique_id/serial number)
 * is populated through a TWO-PHASE process:
 *
 * Phase 1: Initialization (function at 0x105c7f0)
 *   - Clears the entire identity slot to 0
 *   - Sets default calibration values
 *   - Writes slot+0x1f8 = slot_index, slot+0x1fc = flags
 *   - Sets controller+0x3c = 1 (ControllerDetails ready_flag)
 *   - Does NOT write slot+0x200 (unique_id stays 0)
 *
 * Phase 2: Feature Report Response Processing
 *   - The state machine at 0x10d4e6c processes GET_ATTRIBUTES/GET_SERIAL/0xf2 responses
 *   - Responses are stored in the state machine object (esi+0xc0 settings array)
 *   - A separate function reads from the state machine and writes to the identity slot
 *   - The unique_id at slot+0x200 is written when the serial number response is processed
 *
 * CRITICAL FINDING: The write to slot+0x200 is NOT a direct instruction.
 * It happens through a memcpy/memmove from a parsed response buffer to the identity slot.
 *
 * THE WRITE PATH
 * ==============
 *
 * 1. Feature Report Processing State Machine (0x10d4e6c)
 *    - Receives response data from ATT layer
 *    - Dispatches based on command byte (0x83=GET_ATTRIBUTES, 0x84=GET_SERIAL, 0xf2=CAPABILITIES)
 *    - For each command, calls vtable handlers to process the response
 *    - Stores parsed data in internal structures (esi+0xc0 settings array)
 *
 * 2. Identity Slot Population (function at 0x105cb50, within controller.cpp)
 *    - Large function (~500 instructions) that processes controller data
 *    - Reads from the state machine's internal data structures
 *    - Writes to identity slot at controller+slot*0xe8+0x1f8
 *    - Specifically, the unique_id at slot+0x200 is written from the parsed serial number
 *
 * 3. Identity Data Copy (function at 0x105ca80)
 *    - Checks: cmp byte [rbp + rax + 0x200], 0 (slot+0x200 must be non-zero)
 *    - If non-zero: copies 0x21 bytes from source buffer to slot+0x214 (identity_data)
 *    - This is the capability data copy, NOT the serial number write
 *
 * WHAT WE KNOW ABOUT THE WRITE
 * =============================
 *
 * The function at 0x105c7f0 (InitializeSlotDefaults) clears the identity slot:
 *   0x105c859: mov qword [rdx + 0x1f8], 0    ; product_id = 0
 *   0x105c864: mov qword [rax], 0             ; unique_id[0:8] = 0
 *   0x105c86b: mov qword [rax + 8], 0         ; unique_id[8:16] = 0
 *   0x105c873: mov dword [rax + 0x10], 0      ; unique_id[16:20] = 0
 *   0x105c87a: ... (clears identity_data, capability_flags, transport_type)
 *
 * Then at the end, writes defaults:
 *   0x105ca02: mov dword [rax + 0x1f8], ebp   ; slot+0x1f8 = slot_index
 *   0x105ca0f: mov dword [rax + 0x1fc], edx   ; slot+0x1fc = flags
 *   0x105ca15: mov dword [ebx + 0x3c], 1      ; ControllerDetails ready_flag = 1
 *
 * The unique_id at slot+0x200 remains 0 after initialization.
 * It must be populated by the feature report response processing code.
 *
 * The function at 0x105ca80 (CopyIdentityData) REQUIRES slot+0x200 to be non-zero:
 *   0x105cabb: cmp byte [rbp + rax + 0x200], 0
 *   0x105cac3: jne 0x105caf0                    ; if non-zero → copy identity data
 *   0x105cac5: lea rdx, "m_rgControllerIDs[unControllerIndex].rgchSerialNumber[0]"
 *   0x105cad8: call 0x26cdc00                    ; ASSERTION if zero
 *
 * This means the serial number MUST be written BEFORE CopyIdentityData is called.
 *
 * IMPLICATION FOR OUR ATT SERVER
 * ===============================
 *
 * The identity slot is populated by the feature report response processing code,
 * which is triggered by SDL_hid_get_feature_report() calls from Steam.
 *
 * The flow is:
 *   1. Steam calls SDL_hid_get_feature_report() for FR 0x00
 *   2. SDL calls ioctl(fd, HIDIOCGFEATURE(len), buf) on /dev/hidrawN
 *   3. Kernel sends UHID_GET_REPORT to BlueZ hog-lib.c
 *   4. hog-lib.c sends ATT Read Request (0x0A) to our ATT server
 *   5. Our ATT server responds with the stored response
 *   6. BlueZ returns the data to SDL
 *   7. Steam parses the response
 *   8. Steam stores parsed data in the identity slot
 *
 * THE BLOCKER: Step 4 never happens because hog-lib.c doesn't send
 * ATT Read Requests for Feature Reports. This is the root cause of
 * the zombie disconnect.
 *
 * SOLUTION OPTIONS
 * ================
 *
 * Option A: Fix hog-lib.c to send ATT Read Requests
 *   - Modify BlueZ source to handle GET_REPORT for Feature Reports
 *   - This would make the normal flow work
 *   - Requires BlueZ source modification
 *
 * Option B: Send ATT Notification with response data
 *   - Send ATT Notification (0x1B) on Feature Report handle (0x0024)
 *   - hog-lib.c might process unsolicited notifications
 *   - UNLIKELY to work: hog-lib.c's report_value_cb only handles Input Reports
 *
 * Option C: Write to the IPC pipe
 *   - CGetControllerInfoWorkItem reads from "hiddevicepipesteam"
   - If we write the correct protobuf response, Steam would process it
 *   - BUT: this populates ControllerDetails, NOT the identity slot
 *   - The zombie check reads from the identity slot, not ControllerDetails
 *   - So this would NOT fix the zombie disconnect
 *
 * Option D: Direct memory write (binary patch)
 *   - Find the exact address of the identity slot in memory
 *   - Write the serial number directly via ptrace or shared memory
 *   - Fragile and complex
 *
 * RECOMMENDED: Option A (fix hog-lib.c) is the correct long-term fix.
 * Option B is worth trying as a quick test.
 *
 * FUNCTION ADDRESSES
 * ==================
 * 0x105c7f0: InitializeSlotDefaults (clears identity slot, sets defaults)
 * 0x105c80f: InitializeSlotDefaults continued (within 0x105c7f0)
 * 0x105ca80: CopyIdentityData (requires slot+0x200 != 0)
 * 0x105caf0: CopyIdentityData success path (memcpy 0x21 bytes to slot+0x214)
 * 0x105cb50: MainControllerSetup (large function, reads/writes identity slot)
 * 0x1070620: GetControllerInfo (zombie check, reads slot+0x200)
 * 0x10d4e6c: FeatureReportStateMachine (processes FR 0x00 responses)
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

