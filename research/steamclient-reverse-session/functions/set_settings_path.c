/*
 * SET_SETTINGS Path Analysis — Does It Go Through the State Machine?
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
 * YES, SET_SETTINGS goes through the state machine at 0x010d466b [32-bit: NEEDS RE-ANALYSIS].
 * But the verification step (vtable[0x130]) is SKIPPED because:
 *   - The verify object (r13) is NULL for SET_SETTINGS
 *   - The state machine checks `test r13, r13` at 0x010d4e6c [32-bit: NEEDS RE-ANALYSIS]
 *   - If r13==0, it jumps to 0x10d4ff1 (timing calc, no verify)
 *
 * The command byte (0x87) is stored at [esi+0xe0], not hardcoded.
 * The state machine is command-agnostic — it processes whatever
 * command is in [esi+0xe0].
 */

/*
 * === CORRECTED: 0x010d544c [32-bit: NEEDS RE-ANALYSIS] IS NOT mov al, 0x87 ===
 *
 * Previous sessions identified 0x010d544c [32-bit: NEEDS RE-ANALYSIS] as `mov al, 0x87`.
 * This is WRONG. The bytes at 0x010d544c [32-bit: NEEDS RE-ANALYSIS] are:
 *
 *   0x010d544b [32-bit: NEEDS RE-ANALYSIS]: e8 b0 87 5f 01    call 0x26cdc00    ; assertion()
 *   0x010d5450 [32-bit: NEEDS RE-ANALYSIS]: 84 c0             test al, al
 *   0x010d5452 [32-bit: NEEDS RE-ANALYSIS]: 0f 85 67 ff ff ff jne 0x10d53bf
 *
 * The 0x87 is part of the displacement bytes of `call 0x26cdc00`,
 * NOT an opcode being loaded. The `mov al, 0x87` is a disassembly
 * artifact from misaligned decoding.
 */

/*
 * === SET_SETTINGS QUEUE FUNCTION (0x010d5488 [32-bit: NEEDS RE-ANALYSIS]) ===
 *
 * This function queues a setting entry to the settings array:
 *
 *   void QueueSetting(ControllerSettings* this, int count, double timestamp) {
 *       // Compute timestamp from this->frame_rate (this+0x118)
 *       float delay = this->frame_rate / CONSTANT;
 *       double computed_time = timestamp + delay;
 *
 *       // Push 16-byte entry to settings array
 *       int index = this->count;  // [this+0xd0]
 *       int new_count = index + 1;
 *
 *       if (new_count > this->capacity) {  // [this+0xc8]
 *           GrowArray(this);  // call 0x10d3080
 *       }
 *
 *       this->count = new_count;  // [this+0xd0] = new_count
 *
 *       // Store 16-byte entry: {flag=1, padding, timestamp}
 *       xmmword entry = { 1, 0, computed_time_lo, computed_time_hi };
 *       this->buffer[index * 16] = entry;  // [this+0xc0]
 *   }
 *
 * KEY: This function does NOT set [esi+0x17c]. It only adds entries
 * to the settings array. The state machine processes these entries.
 */

/*
 * === STATE MACHINE FLOW (0x010d466b [32-bit: NEEDS RE-ANALYSIS]) ===
 *
 * The state machine processes settings at [esi+0xc0]:
 *
 *   void ProcessSettings(ControllerSettings* esi, callback r13, ...) {
 *       if (esi->init_flag [0xf0] == 0) {
 *           // First-time initialization
 *           if (esi->count [0xd0] <= 0) return;
 *           // Process settings...
 *       }
 *
 *       // Main loop
 *       for (int i = 0; i < esi->count; i++) {
 *           entry = &esi->buffer[i * 16];
 *           if (entry->flag == 0) continue;  // skip disabled
 *
 *           // Threshold checks...
 *
 *           // SEND (vtable[0x10])
 *           esi->send_state [0xe1] = send_result;
 *
 *           // VERIFY (vtable[0x130]) — ONLY if r13 != NULL
 *           if (r13 == NULL) {
 *               // Skip verify, go to timing calc
 *               goto timing_calc;
 *           }
 *           result = r13->vtable[0x130](r13, esi->report_id [0x198]);
 *           // Process result...
 *       }
 *   }
 */

/*
 * === THE CRITICAL BRANCH: test r13, r13 at 0x010d4e6c [32-bit: NEEDS RE-ANALYSIS] ===
 *
 *   0x010d4e6c [32-bit: NEEDS RE-ANALYSIS]: test r13, r13          ; check if verify object exists
 *   0x010d4e6f [32-bit: NEEDS RE-ANALYSIS]: je 0x10d4ff1           ; if NULL → SKIP VERIFY
 *
 *   0x010d4e75 [32-bit: NEEDS RE-ANALYSIS]: mov rax, [r13]         ; (only reached if r13 != NULL)
 *   0x010d4e79 [32-bit: NEEDS RE-ANALYSIS]: mov rdi, r13
 *   0x010d4e7c [32-bit: NEEDS RE-ANALYSIS]: mov esi, [esi+0x198]   ; report ID
 *   0x010d4e83 [32-bit: NEEDS RE-ANALYSIS]: call [rax+0x130]        ; VERIFY (get_feature_report)
 *
 * For SET_SETTINGS: r13 is NULL → verify is SKIPPED
 * For GET_ATTRIBUTES: r13 is non-NULL → verify happens
 */

/*
 * === WHERE [esi+0x17c] FITS IN ===
 *
 * The flag [esi+0x17c] is a separate gatekeeper:
 *
 *   0x0123e5fb: cmp byte [esi+0x17c], 0
 *   0x010d4db0 [32-bit: NEEDS RE-ANALYSIS]: je 0x10d4fd0           ; if flag==0, go to comparison path
 *
 * When [esi+0x17c]==0 (normal operation):
 *   - Goes to comparison path at 0x10d4fd0
 *   - Reads byte from settings buffer, compares with [esi+0xe1]
 *   - If mismatch → sends (0x10d4dc6)
 *   - If match → skips to verify (0x10d4e75)
 *
 * When [esi+0x17c]!=0 (test initialization only):
 *   - Always sends (the xor/cmp at 0x010d4db9 [32-bit: NEEDS RE-ANALYSIS]-0x010d4dc0 [32-bit: NEEDS RE-ANALYSIS] is dead code)
 *
 * KEY: [esi+0x17c] is only set to 1 during YieldingRunTestProgram
 * (0x0178a140). In normal operation, it's always 0.
 */

/*
 * === CExitLizardModeWorkItem ===
 *
 * RTTI string at 0x00aa19e0: "23CExitLizardModeWorkItem"
 * No LEA references found — the work item is likely created through
 * a vtable or factory pattern, not direct string reference.
 *
 * The work item is part of the work item queue system:
 *   CWriteFeatureReportWorkItem (0x00aa1880) — sends feature reports
 *   CExitLizardModeWorkItem (0x00aa19e0) — exits lizard mode
 *   CPulseHapticWorkItem (0x00aa18e0) — haptic pulses
 *   CVibrationWorkItem (0x00aa1900) — vibration
 *   CImpulseTriggerWorkItem (0x00aa1920) — impulse triggers
 */

/*
 * === COMPLETE FLOW FOR SET_SETTINGS 0x09 ===
 *
 * 1. CExitLizardModeWorkItem is queued
 * 2. It calls QueueSetting (0x010d5488 [32-bit: NEEDS RE-ANALYSIS]) with command=0x87, register=0x09, value=0
 * 3. Entry is added to settings array at [esi+0xc0]
 * 4. State machine (0x010d466b [32-bit: NEEDS RE-ANALYSIS]) processes the entry
 * 5. SEND: call vtable[0x10] — sends feature report to controller
 * 6. VERIFY: r13 is NULL → SKIPPED
 * 7. If send failed, entry remains in array → retried on next iteration
 * 8. The 3-second retry is the state machine's polling period
 *
 * The verification (vtable[0x130] = get_feature_report) is NOT called
 * because r13 (the verify object) is NULL for SET_SETTINGS.
 */

/*
 * === BINARY REFERENCES ===
 *
 * SET_SETTINGS queue: 0x010d5488 [32-bit: NEEDS RE-ANALYSIS]
 * State machine: 0x010d466b [32-bit: NEEDS RE-ANALYSIS]
 * SEND (vtable[0x10]): 0x010d4e14 [32-bit: NEEDS RE-ANALYSIS]
 * VERIFY (vtable[0x130]): 0x010d4e83 [32-bit: NEEDS RE-ANALYSIS]
 * Critical branch (test r13): 0x010d4e6c [32-bit: NEEDS RE-ANALYSIS]
 * Pending flag check: 0x0123e5fb
 * Comparison path: 0x010d4fd0 [32-bit: NEEDS RE-ANALYSIS]
 * Timing calc: 0x010d4ff1 [32-bit: NEEDS RE-ANALYSIS]
 * Settings array: [esi+0xc0]
 * Settings count: [esi+0xd0]
 * Command byte: [esi+0xe0]
 * Report ID: [esi+0x198]
 * Init flag: [esi+0xf0]
 * Pending flag: [esi+0x17c]
 */
