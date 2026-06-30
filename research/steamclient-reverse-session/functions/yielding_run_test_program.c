/*
 * YieldingRunTestProgram — Complete Analysis
 *
 * The gate mechanism that controls Steam-generated haptics (0x8F dispatch).
 *
 * Binary: ~/.steam/debian-installation/linux64/steamclient.so
 * Status: VERIFIED (2026-06-29), but [rdi+0x1d8] theory UNVERIFIED
 *
 * This document is the authoritative reference for the YieldingRunTestProgram
 * analysis. All addresses verified via radare2 targeted disassembly.
 *
 * IMPORTANT (2026-06-29 evening): The theory that [rdi+0x1d8] at the
 * dispatcher 0x015675a8 represents a controller state type is UNVERIFIED.
 * 0x1d8 may be a graphics API type (1=GL, 2=Vulkan, 3/4=D3D12).
 * GDB watchpoint is the definitive test.
 */

/*
 * === EXECUTIVE SUMMARY ===
 *
 * YieldingRunTestProgram is a JOB NAME in Steam's internal job/task system
 * (defined in /data/src/common/job.cpp). It is NOT a standalone function.
 *
 * The job:
 *   1. Allocates a 0x210-byte job context
 *   2. Initializes it via 0x156d6a0 (general-purpose job allocator)
 *   3. Sets [r15+0x208] = 1 (the 0x8F haptic gate flag)
 *   4. Registers with the job system under the name "YieldingRunTestProgram"
 *   5. Spawns a subprocess (controller test program) and waits for it
 *   6. Has a 60-second timeout (0xea60)
 *
 * The gate flag [r15+0x208] at 0x10d4da0 controls whether 0x8F haptic
 * commands are dispatched. If 0, the entire vtable dispatch is skipped.
 *
 * On native Deck: state 1-2 → YieldingRunTestProgram runs → gate opens
 * On BLE:         state 3-4 → different path → gate stays closed
 *
 * IMPORTANT: What [rdi+0x1d8] holds is UNVERIFIED. It may be a graphics
 * API type (1=GL, 2=Vulkan, 3/4=D3D12) instead of a controller state.
 * The "state 1-2 vs 3-4" routing theory needs GDB verification.
 */

/*
 * === THE DISPATCHER FUNCTION (0x015675a8) ===
 *
 * Size: 18,300 bytes, 52 basic blocks
 * Purpose: Controller message dispatcher — routes based on controller state/type
 * Source: Part of Steam's controller subsystem (tritoncontroller.cpp related)
 *
 * Entry:
 *   0x015675a8:  push rbp
 *   0x015675a9:  mov rbp, rdi           ; rbp = controller object
 *   0x015675ad:  sub rsp, 0x138          ; 312-byte stack frame
 *
 * The function reads [rdi+0x1d8] (controller state/type) and branches:
 *
 *   State 1-2: → 0x1567610 (MAIN PATH — includes YieldingRunTestProgram)
 *   State 3-4: → 0x1567910 (ALTERNATIVE PATH — 16-byte alloc, no gate set)
 *   Other:     → early return
 *
 * The state/type value determines which controller initialization path to take.
 * This is NOT a transport-type check (BLE vs USB) — it's a controller
 * classification that affects which features are enabled.
 */

/*
 * === THE STATE CHECK ===
 *
 *   0x015675c7:  mov eax, dword [rdi + 0x1d8]    ; Load controller state/type
 *   0x015675cd:  lea edx, [rax - 1]
 *   0x015675d0:  cmp edx, 1
 *   0x015675d3:  jbe 0x1567610                    ; state==1 → jump (jbe = unsigned <=)
 *                                                   ; state==2 → jump (2-1=1, 1<=1)
 *
 *   0x015675d5:  sub eax, 3
 *   0x015675d8:  cmp eax, 1
 *   0x015675db:  jbe 0x1567910                    ; state==3 → jump (3-3=0, 0<=1)
 *                                                   ; state==4 → jump (4-3=1, 1<=1)
 *
 *   State 0 or >=5: falls through to early return
 */

/*
 * === MAIN PATH (state 1-2) ===
 *
 *   0x01567610:  ... (large setup: ~0x1E0 bytes of stack frame initialization)
 *   0x015677e3:  cmp byte [rsp + 0x127], 0        ; Check prerequisite flag
 *   0x015677ee:  js 0x15678f0                     ; If not set, jump to fallback
 *
 *   0x015677f4:  mov edi, 0x210                    ; Allocate 0x210-byte object
 *   0x015677f9:  call 0x2a6ca70                    ; operator new(0x210)
 *
 *   0x01567814:  mov r15, rax                      ; Save pointer in r15
 *
 *   0x01567817:  call 0x156d6a0                    ; Initialize job context
 *   ;   Inside 0x156d6a0:
 *   ;     0x156d702: mov dword [rbx + 8], 1        ; state = 1
 *   ;     0x156d8a1: mov byte [rbx + 0x208], 0     ; CLEARS gate to 0
 *   ;     (sets up vtable at 0x02ac0eb8, mutex, etc.)
 *
 *   0x0156781c:  mov byte [r15 + 0x208], 1        ; *** SET 0x8F GATE TO 1 ***
 *
 *   0x0156782a:  call 0x2844a00                    ; Start retry timer
 *
 *   0x01567847:  lea rsi, "YieldingRunTestProgram" ; Job name
 *   0x0156784e:  call 0x27a2370                    ; Register with job system
 *   ;   Inside job.cpp:
 *   ;     Validates "this == g_pJobCur"
 *   ;     Sets [rbp + 0x38] = 1
 *   ;     Stores name at [rbp + 0x170]
 *
 *   0x01567853:  test al, al                       ; Did registration succeed?
 *   0x01567855:  jne 0x15678b0                     ; If yes, check process result
 *
 *   ; Error paths:
 *   0x01567871:  "Error: %s: failed to wait for process: %s"
 *   0x015678d8:  "Error: %s: process timed out: %s"
 */

/*
 * === ALTERNATIVE PATH (state 3-4) ===
 *
 *   0x01567910:  mov edi, 0x10                      ; Allocate ONLY 16 bytes!
 *   0x01567915:  call 0x2a6ca70                     ; operator new(0x10)
 *   0x01567921:  mov r15, rax                       ; Save pointer
 *   0x01567944:  movups xmmword [r15], xmm0        ; Initialize 16-byte object
 *
 * This path:
 *   - Does NOT allocate 0x210-byte context
 *   - Does NOT call 0x156d6a0 (job init)
 *   - Does NOT set [r15+0x208] = 1
 *   - Does NOT register with job system
 *   - The 0x8F gate stays CLOSED
 */

/*
 * === THE GATE CHECK (0x010d4da0) ===
 *
 * Called for every 0x8F haptic command attempt:
 *
 *   0x010d4da0:  cmp byte [r15 + 0x208], 0       ; Is haptic gate open?
 *   0x010d4da8:  movzx eax, byte [r15 + 0xe1]
 *   0x010d4db0:  je 0x10d4fd0                      ; If gate==0 → SKIP dispatch
 *                                                   ; If gate==1 → proceed
 *
 * When gate is open, the vtable dispatch proceeds:
 *   0x010d4dfc:  mov rax, [r15+0xa8]               ; load HID device array
 *   0x010d4e08:  mov rax, [rax+rdx*8]              ; index into array
 *   0x010d4e0e:  mov rdi, [rax]                    ; load object pointer
 *   0x010d4e11:  mov rax, [rdi]                    ; load vtable
 *   0x010d4e14:  call [rax+0x10]                   ; dispatch vtable[0x10]
 *
 * The vtable method at 0x017605b0 is a trivial setter:
 *   mov [rdi+0x20], rsi   ; store context pointer
 *   ret
 */

/*
 * === FLAG LIFECYCLE ===
 *
 *   Cleared at 0x156d8a1: mov byte [rbx + 0x208], 0  (during job init)
 *   Set at 0x156781c:     mov byte [r15 + 0x208], 1  (after YieldingRunTestProgram)
 *   Cleared at 0x119f3b1: mov byte [rdi + 0x208], 0  (during cleanup)
 *   Checked at 0x10d4da0: cmp byte [r15 + 0x208], 0  (gate for 0x8F dispatch)
 *
 * In normal BLE operation: the flag is set to 0 at 0x156d8a1 (init), then
 * the alternative path is taken (state 3-4), so it's never set back to 1.
 * The flag stays 0 permanently.
 */

/*
 * === WHY IT'S NAMED "YieldingRunTestProgram" ===
 *
 * Breaking down the name:
 *   "Yielding" — Steam job system naming convention for blocking/waiting jobs.
 *     Other examples: BYieldingRunAPIJob, BYieldingCompleteSteamControllerRegistration,
 *     YieldingCheckForUpdateBIOS, YieldingCheckForUpdateOS, YieldingApplyUpdateBIOS
 *
 *   "Run" — Executes something
 *
 *   "Test Program" — Runs a test program on the controller hardware.
 *     Evidence: error strings "failed to wait for process" and "process timed out"
 *     indicate it spawns a subprocess and waits for it to complete.
 *
 * The function at 0x27a2370 (where the name is registered) is in
 * /data/src/common/job.cpp — Steam's job/task management system.
 */

/*
 * === WHAT [rdi+0x1d8] REPRESENTS ===
 *
 * This is at offset 0x1d8 in the controller object. Based on the branching:
 *   State 1-2: "primary" controller path (full init, YieldingRunTestProgram)
 *   State 3-4: "secondary" controller path (minimal init, no test program)
 *
 * PREVIOUS THEORY (UNVERIFIED):
 *   This is likely a controller protocol version or connection maturity state:
 *     - Native Deck Neptune (PID 0x1205): gets state 1-2 (full initialization)
 *     - BLE SC2 spoof (PID 0x1303): gets state 3-4 (different init path)
 *     - USB SC2: likely state 1-2 (same as native)
 *     - Dongle SC2: likely state 1-2 (same as native)
 *
 *   The value is set during controller object construction, before this
 *   dispatcher is called. It's not a runtime state — it's a classification
 *   assigned at creation time.
 *
 * UPDATED THEORY (2026-06-29 evening) — UNVERIFIED:
 *   The value at 0x1d8 may be a graphics API type, not a controller state:
 *     - 0x01559070 writes [object+0x1d8] = graphics API type
 *     - 1=GL, 2=Vulkan, 3=D3D12 path A, 4=D3D12 path B
 *     - Values 3/4 are NEVER written as immediates to 0x1d8
 *     - The BLE handler at 0x010c4e0c sets [r12+0x08] = 1 but it's NEVER READ
 *     - The controller constructor reads [parent+0x1B0] into [controller+0x1d8]
 *       but it gets overwritten later
 *
 *   The connection between the shader compilation path and the
 *   YieldingRunTestProgram path is unverified. A 5-minute GDB watchpoint
 *   would resolve this definitively.
 *
 * CONSERVATIVE INTERPRETATION:
 *   Until GDB verification, treat 0x1d8 as UNVERIFIED. The dispatcher at
 *   0x015675a8 DOES branch on it, and the gate mechanism IS verified. But
 *   what value BLE devices get, and why, remains unknown.
 */

/*
 * === CONNECTION TO 0x8F ===
 *
 * Native Deck flow:
 *   1. Controller registered → state set to 1-2
 *   2. Dispatcher takes main path
 *   3. YieldingRunTestProgram allocates 0x210-byte context
 *   4. Job context init clears [obj+0x208] = 0
 *   5. YieldingRunTestProgram sets [obj+0x208] = 1
 *   6. Gate opens → 0x8F haptic commands are dispatched
 *   7. Steam haptics work (trackpad clicks, UI feedback)
 *
 * BLE flow:
 *   1. Controller registered → state set to 3-4
 *   2. Dispatcher takes alternative path
 *   3. Allocates only 16-byte object
 *   4. [obj+0x208] stays 0 (never set to 1)
 *   5. Gate stays closed → 0x8F never dispatched
 *   6. Steam haptics don't work
 *
 * The SET_SETTINGS retry loop (0x87 commands) and GET_SERIAL retries
 * are SEPARATE from this mechanism. They don't affect the state value
 * at [rdi+0x1d8]. The state is set at controller object creation time.
 *
 * IMPORTANT: The "state set to 3-4" theory is UNVERIFIED. The actual value
 * at [rdi+0x1d8] for BLE devices needs GDB verification. It may be a
 * graphics API type, not a controller state.
 */

/*
 * === IMPORTANT CLARIFICATION ===
 *
 * The [reg+0x1b0] = 1 flag found at 0x15e22fe, 0x15e28ae, 0x15e2e8e,
 * 0x15e30d6, 0x15e354c, 0x15e7934 are ALL SteamOS UPDATE MANAGEMENT functions:
 *
 *   0x15e22fe — YieldingCheckForUpdateBIOS (BIOS firmware update checker)
 *   0x15e28ae — YieldingCheckForUpdateOS (SteamOS update checker)
 *   0x15e2e8e — BYieldingRunAPIJob (Steam API job runner)
 *   0x15e30d6 — BYieldingRunAPIJob (OS branch detection)
 *   0x15e354c — BYieldingRunAPIJob (another variant)
 *   0x15e7934 — YieldingApplyUpdateBIOS (BIOS firmware update applier)
 *
 * They call the same 0x156d6a0 allocator but set [reg+0x1b0] = 1
 * (job context initialized flag). They have NOTHING to do with controllers.
 *
 * The 0x156d6a0 function is a GENERAL-PURPOSE job context allocator used
 * across many Steam subsystems (controllers, updates, API jobs).
 */

/*
 * === BINARY REFERENCES ===
 *
 * Dispatcher entry:         0x015675a8
 * Job allocation:           0x015677f4 (mov edi, 0x210)
 * Gate flag set:            0x0156781c (mov byte [r15+0x208], 1)
 * Job name reference:       0x01567847 (lea rsi, "YieldingRunTestProgram")
 * Job system registration:  0x0156784e (call 0x27a2370)
 * Job allocator:            0x0156d6a0 (called from 0x01567817)
 * Gate check:               0x010d4da0 (cmp byte [r15+0x208], 0)
 * Gate skip target:         0x010d4fd0 (je when gate==0)
 * vtable dispatch:          0x010d4e14 (call [rax+0x10])
 * vtable method:            0x017605b0 (trivial setter)
 * operator new(0x210):      0x02a6ca70
 * operator new(0x10):       0x02a6ca70 (same allocator, different size)
 * Error: wait failed:       0x00d72898 ("Error: %s: failed to wait for process: %s")
 * Error: timeout:           0x00c9b7d8 ("Error: %s: process timed out: %s")
 * Job system (job.cpp):     0x027a2370
 * Job system assertion:     "this == g_pJobCur" at 0x00d4b25c
 * Job.cpp source path:      "/data/src/common/job.cpp" at 0x00d3c63d
 * String "YieldingRun...":  0x00d6d17b
 * Alternative path entry:   0x01567910 (16-byte alloc)
 * Flag clear (init):        0x0156d8a1 (mov byte [rbx+0x208], 0)
 * Flag clear (cleanup):     0x0119f3b1 (mov byte [rdi+0x208], 0)
 */
