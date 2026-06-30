/*
 * BYieldingRegisterSteamController — Registration Requirements
 *
 * Binary: ~/.steam/debian-installation/ubuntu12_32/steamclient.so (32-bit, 49MB)
 * Function VA: 0x10b3a60
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
 * BYieldingRegisterSteamController requires:
 *   1. Valid controller ID
 *   2. GetControllerInfo success (via 0x1070620)
 *   3. Controller must not change during registration
 *   4. AccountHardware.RegisterSteamController#1 RPC must succeed
 *   5. AccountHardware.CompleteSteamControllerRegistration#1 RPC must succeed
 *   6. Must not timeout
 *   7. Controller must not disconnect
 *
 * CGetControllerInfoWorkItem failure does NOT block registration.
 * It only affects account queries (falls back to local cache).
 */

/*
 * === REGISTRATION FLOW ===
 *
 * 1. BYieldingRegisterSteamController (0x10b3a60)
 *    - Entry: push rbp; sub $0x2c8, rsp
 *    - Calls 0x1070620 to get controller identity
 *    - If identity fails → "couldn't get identity before registration"
 *    - Calls AccountHardware.RegisterSteamController#1 via vtable[0x28]
 *    - If RPC fails → "Error committing registration"
 *
 * 2. BYieldingCompleteSteamControllerRegistration
 *    - Calls AccountHardware.CompleteSteamControllerRegistration#1
 *    - If fails → "Error committing registration completion"
 *
 * 3. BYieldingQueryAccountsRegisteredToController (0x108cf00)
 *    - Queries accounts registered to controller
 *    - If IPC query fails → "Error querying accounts... Will Try Local Cache!"
 *    - Falls back to local cache
 */

/*
 * === DISASSEMBLY (0x10b3a60) ===
 *
 * 0x10b3a60: push rbp
 * 0x10b3a61: mov rbp, rsp
 * 0x10b3a64: push esi/r14/r13/r12/ebx
 * 0x10b3a73: sub rsp, 0x2c8
 *
 * ; Check controller ID
 * 0x10b3320: test controller_id, controller_id
 * 0x10b3383: lea rax, "BYieldingRegisterSteamController - missing controller id"
 * 0x10b3396: ... (log and return error)
 *
 * ; Get controller identity
 * 0x10b3ba5: call 0x1070620         ; GetControllerInfo
 * 0x10b3bb1: test al, al
 * 0x10b3bb3: je 0x10b3ee8          ; if failed → error path
 *
 * ; Check controller version/state
 * 0x10b37ad: cmp version, version  ; controller changed?
 * 0x10b37b9: jne 0x10b3483         ; → "controller changed before registration"
 *
 * ; Call RegisterSteamController API
 * 0x10b3d3a: call [rax+0x28]       ; AccountHardware.RegisterSteamController#1
 * 0x10b3d51: test al, al
 * 0x10b3d53: jne 0x10b3f80         ; if succeeded → check version, commit
 *
 * ; Error paths
 * 0x10b3483: lea rax, "controller changed before registration"
 * 0x10b351b: lea rax, "couldn't get identity before registration"
 * 0x10b3863: lea rax, "Error committing registration of controller & account pair - controller disconnected."
 * 0x10b38d9: lea rax, "Error committing registration of controller & account pair: %s"
 * 0x10b3944: lea rax, "BYieldingRegisterSteamController - timed out"
 */

/*
 * === DATA REQUIRED FOR REGISTRATION ===
 *
 * 1. VALID CONTROLLER ID
 *    - Must be non-zero
 *    - Missing ID → immediate error
 *
 * 2. CONTROLLER IDENTITY (from 0x1070620)
 *    - Connection object at [ctx+0x190]
 *    - Vtable must be valid
 *    - Connection state must be queryable
 *    - Returns controller info needed for API call
 *
 * 3. CONTROLLER VERSION/STATE
 *    - Must not change during registration
 *    - Checked at 0x10b37ad
 *    - Mismatch → "controller changed before registration"
 *
 * 4. ACCOUNT HARDWARE API ACCESS
 *    - vtable[0x28] must be callable
 *    - AccountHardware.RegisterSteamController#1 must be reachable
 *    - AccountHardware.CompleteSteamControllerRegistration#1 must be reachable
 *
 * 5. NETWORK CONNECTIVITY
 *    - RPC calls must succeed
 *    - Timeout if server unreachable
 */

/*
 * === IS CGetControllerInfoWorkItem REQUIRED? ===
 *
 * NO. CGetControllerInfoWorkItem is for the QUERY path, not registration.
 *
 * The registration path uses:
 *   - 0x1070620 (GetControllerInfo) for identity
 *   - AccountHardware.RegisterSteamController#1 for registration
 *
 * The query path uses:
 *   - CGetControllerInfoWorkItem for account queries
 *   - Falls back to local cache on failure
 *
 * So CGetControllerInfoWorkItem failure means:
 *   - Account queries fail → local cache used
 *   - Registration can still succeed
 *   - Controller can still be used
 */

/*
 * === ERROR STRINGS ===
 *
 * 0x00ca0b50: "BYieldingRegisterSteamController - missing controller id"
 * 0x00cce280: "BYieldingRegisterSteamController"
 * 0x00cd4dc0: "BYieldingRegisterSteamController - couldn't get identity before registration."
 * 0x00cf82b8: "BYieldingRegisterSteamController - Error committing registration of controller & account pair - controller disconnected."
 * 0x00b9b9eb: "BYieldingRegisterSteamController - controller changed before registration."
 * 0x00b9b86f: "BYieldingRegisterSteamController - Error committing registration of controller & account pair: %s"
 * 0x00d62d30: "BYieldingRegisterSteamController - timed out"
 * 0x00b98b53: "BYieldingRegisterSteamController - controller disconnected while waiting."
 * 0x00b98bd7: "BYieldingRegisterSteamController - Error querying accounts registered to controller. Will Try Local Cache!"
 *
 * 0x00b9b7a3: "BYieldingCompleteSteamControllerRegistration - controller changed before completing registration."
 * 0x00b9b74f: "BYieldingCompleteSteamControllerRegistration - couldn't get controller identity."
 * 0x00b9b86f: "BYieldingCompleteSteamControllerRegistration - Error committing registration completion of controller & account pair: %s %s %s"
 * 0x00cc65d8: "BYieldingCompleteSteamControllerRegistration - Error committing registration completion of controller & account pair - controller disconnected: %s"
 *
 * 0x00b9ba50: "AccountHardware.RegisterSteamController#1"
 * 0x00ce2dc8: "AccountHardware.CompleteSteamControllerRegistration#1"
 */

/*
 * === BINARY REFERENCES ===
 *
 * Function VA:               0x10b3a60
 * GetControllerInfo call:    0x10b3ba5 → 0x1070620
 * RegisterSteamController:   0x10b3d3a (vtable[0x28])
 * CompleteRegistration:      0x10b3d4e
 * QueryAccounts:             0x108cf00
 * QueryAccounts IPC call:    0x108d01c (vtable[0x218])
 */
