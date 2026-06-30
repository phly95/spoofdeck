/*
 * Zombie Check vs Identity Check — Same Function, Different Callers
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
 * === ANSWER: YES, SAME FUNCTION ===
 *
 * 0x1070620 is BOTH the identity check AND the zombie check.
 * It is called from two places:
 *
 * 1. BYieldingRegisterSteamController at 0x10b3bac
 *    - Purpose: verify controller identity before registration
 *    - Failure: "couldn't get identity before registration"
 *
 * 2. Slot iterator (zombie check) at 0x1072106
 *    - Purpose: verify controller is still alive
 *    - Failure: "Disconnecting zombie controller %d"
 */

/*
 * === ZOMBIE CHECK CALL SITE (0x1072106) ===
 *
 * The slot iterator iterates 16 controller slots (0-15):
 *
 * 0x1072070: add ebx, 1          ; next slot
 * 0x1072074: cmp ebx, 0x10       ; done with all 16?
 * 0x1072078: je 0x10720c0        ; → exit loop
 *
 * For each slot:
 * 0x1072100: mov esi, r12d       ; slot_index
 * 0x1072103: mov rdi, rcx        ; controller_obj
 * 0x1072106: call 0x1070620      ; GetControllerInfo()
 * 0x107210b: test al, al
 * 0x107210d: jne 0x1072021       ; if success → skip (not a zombie)
 *
 * ; If 0x1070620 returned 0:
 * 0x1072113: ... (setup logging)
 * 0x107214b: lea rcx, "Disconnecting zombie controller %d\n"
 * 0x107218e: call 0x104ca50      ; format log message
 * 0x107219c: lea rsi, "Disconnecting zombie controller %d\n"
 * 0x10721a3: lea rdi, [0x2c4fbe0]
 * 0x10721aa: call 0x1790ba0      ; logMsg("Disconnecting zombie controller %d\n", slot)
 *
 * 0x10721af: mov rax, [rbp-0x1a8]  ; controller obj
 * 0x10721b6: cmp byte [rax+0x1091fd], 0  ; flag check
 * 0x10721bd: je 0x1072021        ; if flag not set, skip disconnect
 * 0x10721c3: mov rdi, [rax+0x180]  ; connection object
 * 0x10721ca: lea rcx, "Zombie Controller"
 * 0x10721d1: xor edx, edx
 * 0x10721d3: mov esi, r12d       ; slot_index
 * 0x10721d6: call 0x106d8a0      ; DISCONNECT controller
 * 0x10721db: jmp 0x1072021       ; continue to next slot
 */

/*
 * === ZOMBIE CHECK FLOW ===
 *
 * 1. Iterate slots 0-15
 * 2. For each slot:
 *    a. Check vtable validity (0x1072084-0x1072098)
 *    b. Check flag byte at [controller+0x1091fd] (0x10720a1)
 *    c. Load connection object from [controller+0x190] (0x10720ae)
 *    d. Call connection vtable[0x28] to check slot state (0x1071d45)
 *    e. If state OK → check slot state byte (0x1072006)
 *    f. If slot state == 3 → call 0x1070620 (0x1072106)
 *    g. If 0x1070620 returns 0 → disconnect as zombie (0x10721d6)
 *
 * The zombie check is more thorough than just calling 0x1070620.
 * It first checks:
 *   - Connection exists (offset 0x190)
 *   - Connection vtable[0x28] reports valid state
 *   - Slot state byte == 3 (some "active" state)
 *
 * Only if all these pass does it call 0x1070620 for the final check.
 *
 * But the critical point: if the slot data isn't ready (offset 0x200 == 0),
 * 0x1070620 returns 0, and the controller is disconnected as zombie.
 */

/*
 * === KEY INSIGHT: WHAT MAKES A CONTROLLER A "ZOMBIE" ===
 *
 * A controller becomes a zombie when:
 *
 * 1. It connected successfully (BLE connection established)
 * 2. Steam opened /dev/hidrawN and started polling
 * 3. BUT the feature report handshake didn't complete within ~6 seconds
 * 4. The slot ready flag at offset 0x200 is still 0
 * 5. The zombie timer fires, calls 0x1070620, gets 0
 * 6. Controller is disconnected
 *
 * The ~6 second window is the time between:
 *   - BLE connection established (controller opens)
 *   - Zombie timer fires (periodic check)
 *
 * Our ATT server must complete the feature report handshake within this window.
 */

/*
 * === THE HANDSHAKE RACE ===
 *
 * Timeline:
 *   T+0s:    BLE connection established
 *   T+0s:    Steam opens /dev/hidrawN
 *   T+0s:    Steam starts reading Feature Report 0x00
 *   T+0s:    Steam reads serial number, chip ID, etc.
 *   T+0-2s:  Steam sends 0xf2 commands multiple times
 *   T+0-2s:  Steam reads GET_ATTRIBUTES responses
 *   T+2s:    Steam populates slot data (offset 0x1f8+)
 *   T+2s:    Slot ready flag set (offset 0x200 != 0)
 *   T+6s:    Zombie timer fires → calls 0x1070620
 *            → If ready flag set: returns 1 (not zombie)
 *            → If ready flag NOT set: returns 0 (zombie) → disconnect
 *
 * If the handshake takes longer than 6 seconds, the controller is killed.
 *
 * Our problem: the feature report handshake responses must be FAST.
 * The 0xf2 responses, GET_ATTRIBUTES, and serial read must all complete
 * before the zombie timer fires.
 */

/*
 * === DISCONNECT FUNCTION (0x106d8a0) ===
 *
 * When the zombie check decides to disconnect:
 *
 * 0x10721c3: mov rdi, [rax+0x180]   ; connection object
 * 0x10721ca: lea rcx, "Zombie Controller"  ; disconnect reason
 * 0x10721d1: xor edx, edx
 * 0x10721d3: mov esi, r12d           ; slot_index
 * 0x10721d6: call 0x106d8a0          ; disconnect function
 *
 * This function:
 *   - Logs the disconnection
 *   - Closes the HID device
 *   - Tears down the connection
 *   - Frees the slot resources
 */

/*
 * === TIMER INTERVAL ===
 *
 * The zombie timer interval is not directly visible in the disassembly
 * of 0x1070620. It's set elsewhere in the controller management code.
 *
 * From observed behavior: ~6 seconds between connection and zombie disconnect.
 * This matches Steam's internal timer for controller health checks.
 */
