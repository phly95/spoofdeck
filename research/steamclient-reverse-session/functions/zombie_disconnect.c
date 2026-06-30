/*
 * Zombie Disconnect Analysis — Why Controller Dies After 6 Seconds
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
 * === EXECUTIVE SUMMARY ===
 *
 * The zombie disconnect is STATE-BASED, not TIME-BASED. There is no
 * explicit 6-second timer. The controller becomes "zombie" when:
 *
 * 1. Slot state byte == 3 (previously connected/active)
 * 2. Per-slot flag at offset 0x10b4 is 0 (active flag cleared)
 * 3. Connection state query returns neither 1 nor 4 (no valid data)
 *
 * The 6-second interval is the POLLING FREQUENCY of the caller that
 * iterates all 16 controller slots. The zombie check runs on each
 * poll cycle.
 */

/*
 * === ZOMBIE CHECK FUNCTION (0x1070620) ===
 *
 * This function checks if a controller slot is "zombie" (unresponsive).
 *
 * Input:
 *   rdi = controller manager context
 *   esi = slot index (0-15)
 *   rdx = output struct (controller state)
 *
 * Flow:
 *   1. Validate slot index (0-15)
 *   2. Load connection object at [ctx+0x190] (or [ctx+0x180] if alt mode)
 *   3. If connection is NULL → return 0 (zombie)
 *   4. Call vtable[0x18] to query connection state
 *   5. Check state byte:
 *      - State == 1 → alive (return 1)
 *      - State == 4 → alive (return 1)
 *      - Any other → zombie (return 0)
 *
 * Disassembly:
 *   0x1070620: push esi/r14/r13/r12/rbp/ebx
 *   0x1070629: mov ebp, esi           ; slot index
 *   0x107062c: mov ebx, rdx           ; output struct
 *   0x1070641: xor eax, eax           ; default return 0
 *   0x1070643: cmp ebp, 0xf           ; if slot > 15
 *   0x1070646: ja 0x10706b4           ;   → return 0
 *
 *   ; Load connection object
 *   0x1070662: cmp byte [rdi+0x1091fd], 0  ; alt mode flag
 *   0x1070669: jne 0x1070850               ; → use offset 0x180
 *   0x107066f: mov r8, [rdi+0x190]         ; connection at 0x190
 *   0x1070676: test r8, r8
 *   0x1070679: je 0x10706b4                ; NULL → return 0
 *
 *   ; Query connection state via vtable[0x18]
 *   0x1070696: mov rax, [r8]               ; load vtable
 *   0x107069c: call [rax+0x18]             ; get_state(connection, &buf)
 *
 *   ; Check state byte
 *   0x107069f: movzx eax, byte [rsp+rbp+0x10]  ; state = buf[slot]
 *   0x10706a4: cmp al, 1
 *   0x10706a6: je 0x107086e               ; state==1 → alive
 *   0x10706ac: cmp al, 4
 *   0x10706ae: je 0x107086e               ; state==4 → alive
 *                                           ; else → zombie (return 0)
 *
 *   0x10706b4: ... (clear output, return 0)
 *   0x107086e: ... (fill output, return 1)
 */

/*
 * === SLOT ITERATOR / ZOMBIE DISCONNECT LOOP (0x1071d00) ===
 *
 * This function iterates all 16 controller slots and disconnects zombies.
 *
 * Flow:
 *   1. Initialize slot index = 0
 *   2. For each slot (0-15):
 *      a. Load controller context
 *      b. Check vtable type at 0x1072095
 *      c. Check flag at offset 0x1091fd
 *      d. Load connection at [ctx+0x190]
 *      e. If connection exists, call vtable[0x28] to validate
 *      f. Check slot state byte at [rbp+ebx-0x160]
 *      g. If state == 3, check per-slot flag at [rcx+rax+0x10b4]
 *      h. If flag == 0, call 0x1070620 (zombie check)
 *      i. If zombie == true, disconnect controller
 *
 * Disassembly:
 *   0x1071d1d: xor ebx, ebx           ; slot = 0
 *   0x1071d1f: jmp 0x1072084          ; → loop condition
 *
 *   ; Loop condition
 *   0x1072084: mov rax, [rax+0x50]    ; vtable[0x50]
 *   0x1072095: cmp rax, rcx           ; expected vtable fn
 *   0x1072098: jne 0x10720e8          ; different type → alternate
 *
 *   ; Check connection
 *   0x1071d2f: test rdi, rdi
 *   0x1071d32: je 0x1072070           ; NULL → skip
 *
 *   ; Validate connection via vtable[0x28]
 *   0x1071d45: call [rax+0x28]        ; validate_connection
 *   0x1071d48: test al, al
 *   0x1071d4a: je 0x1072070           ; invalid → skip
 *
 *   ; Check slot state byte
 *   0x1071f47: cmp byte [rbp+ebx-0x160], 3  ; state == 3?
 *
 *   ; Check per-slot flag
 *   0x1072013: cmp byte [rcx+rax+0x10b4], 0  ; flag == 0?
 *   0x107201b: je 0x1072100            ; yes → do zombie check
 *
 *   ; Zombie check call
 *   0x1072106: call 0x1070620          ; → zombie check
 *   0x107210b: test al, al
 *   0x107210d: jne 0x1072021           ; alive → skip
 *
 *   ; Disconnect zombie
 *   0x107214b: lea rcx, "Disconnecting zombie controller %d\n"
 *   0x10721d6: call 0x106d8a0          ; perform disconnect
 *
 *   ; Loop increment
 *   0x1072070: add ebx, 1              ; next slot
 *   0x1072074: cmp ebx, 0x10          ; done? (16 slots)
 *   0x1072078: je 0x10720c0           ; → epilogue
 */

/*
 * === CONDITIONS FOR ZOMBIE STATE ===
 *
 * A controller is classified as zombie when ALL of these are true:
 *
 * 1. SLOT STATE BYTE == 3
 *    - Location: [rbp+ebx-0x160] where ebx = slot index
 *    - Value 3 indicates "previously connected/active"
 *    - Other values (0, 1, 2, 4) skip zombie check
 *
 * 2. PER-SLOT FLAG AT OFFSET 0x10B4 == 0
 *    - Location: [rcx+rax+0x10b4] where rax = slot * 0x54
 *    - Value 0 means "active flag cleared"
 *    - Non-zero bypasses zombie check entirely
 *
 * 3. CONNECTION STATE != 1 AND != 4
 *    - Queried via vtable[0x18] on connection object
 *    - State 1 = "has valid input data"
 *    - State 4 = "has valid input data"
 *    - Any other state = "no valid data" → zombie
 *
 * 4. CONNECTION OBJECT EXISTS
 *    - At [ctx+0x190] (or [ctx+0x180] if alt mode)
 *    - If NULL, already classified as zombie
 */

/*
 * === WHAT MUST HAPPEN TO PREVENT ZOMBIE ===
 *
 * To prevent zombie disconnect, the controller must:
 *
 * 1. MAINTAIN ACTIVE CONNECTION
 *    - Connection object at [ctx+0x190] must be non-NULL
 *    - Vtable must be valid
 *
 * 2. RESPOND TO STATE QUERIES
 *    - vtable[0x18] must return state 1 or 4
 *    - State 1 = "has valid input data"
 *    - State 4 = "has valid input data"
 *
 * 3. PROVIDE VALID INPUT DATA
 *    - The controller must continuously send input reports
 *    - The connection state must remain 1 or 4
 *    - If state drops to 0, 2, or 3, controller is zombie
 *
 * 4. KEEP PER-SLOT FLAG SET
 *    - Flag at offset 0x10b4 must be non-zero
 *    - This bypasses zombie check entirely
 *    - Set when controller is actively being used
 */

/*
 * === THE 6-SECOND INTERVAL ===
 *
 * The 6-second interval is NOT a timer in the zombie check function.
 * It's the POLLING FREQUENCY of the caller that invokes the slot
 * iterator loop at 0x1071d00.
 *
 * The polling is likely driven by:
 *   - "controller_idle_poll_interval" config key (0x00c89dad)
 *   - A periodic timer that calls the slot iterator
 *   - The default poll interval is ~6 seconds
 *
 * On each poll cycle:
 *   1. Iterate all 16 controller slots
 *   2. For each slot, check if zombie
 *   3. If zombie, disconnect immediately
 *
 * So the 6-second delay is:
 *   Time from controller becoming unresponsive
 *   → Next poll cycle detects zombie
 *   → Disconnect
 */

/*
 * === BINARY REFERENCES ===
 *
 * Zombie check function:      0x1070620
 * Slot iterator loop:         0x1071d00
 * Disconnect function:        0x106d8a0
 * "Disconnecting zombie":     0x00cbdfb8
 * "Zombie Controller":        0x00b9b370
 * "controller_idle_poll_interval": 0x00c89dad
 * Connection offset (normal): 0x190
 * Connection offset (alt):    0x180
 * Per-slot flag offset:       0x10b4
 * Alt mode flag offset:       0x1091fd
 */
