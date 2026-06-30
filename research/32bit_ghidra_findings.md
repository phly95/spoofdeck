# 32-bit Binary RE Findings — Controller Behavior Map

> Generated: 2026-06-30 from Ghidra headless analysis of `ubuntu12_32/steamclient.so`
> Binary: 49MB, ELF 32-bit LSB, Intel 80386, not stripped

## Key Function Map (32-bit addresses)

| Address | Function | Source File | Description |
|---------|----------|-------------|-------------|
| `0x011b3a60` | CHIDIOThread_Main | `internalcallbacks.h` | Main HID I/O thread — creates worker threads, registers HID device callbacks |
| `0x011d5850` | CHIDIOThread_CWorkItem | `internalcallbacks.h` | CWorkItemThread — processes HID read/write work items |
| `0x01218840` | CGetControllerInfoWorkItem::RunFunc | — | Reads controller info via HID feature reports. Logs "Read failure" on error. Retries up to 51 times with 100ms sleep |
| `0x011cee30` | EYldWaitForControllerDetails | — | Blocks until controller details are ready. Calls `FUN_02ae47e0("EYldWaitForControllerDetails", 2000000, ...)` with 2-second timeout |
| `0x011f7630` | Zombie_Controller_Check | — | Detects zombie controllers (state=3, flag=0, connection!=1&&!=4). Logs "Zombie Controller" |
| `0x01219bf0` | BYieldingRegisterSteamController (identity path) | — | Checks controller identity before registration. Logs "couldn't get controller identity" on failure |
| `0x0121a690` | BYieldingRegisterSteamController | — | Full registration flow. Calls `AccountHardware.RegisterSteamController#1` API |
| `0x01202e70` | ControllerPersonalization | `controller.cpp` | Loads personalization settings (guide brightness, sounds, antidrift). Not a rumble handler despite our naming |
| `0x012042d0` | Rumble_Handler_2 | — | Second rumble-related function (needs further analysis) |
| `0x011cbae0` | Controller_Activity_Update | `controller.cpp:0x1772` | Updates controller activity. Checks `unControllerIndex < MAX_STEAM_CONTROLLERS` |
| `0x011e45d0` | SDL_JOYSTICK_HIDAPI_STEAM_Setup | — | Loads `libSDL3.so.0`, sets SDL env vars for HIDAPI Steam controller support |
| `0x011beca0` | QueryAccountsRegisteredToController | — | Queries which accounts are registered to a controller via `AccountHardware.QueryAccountsRegisteredToController#1` |
| `0x0123e1e0` | Gate_CHECK_Parent_Function | `controllerxinput_linux.cpp` | Initializes controller XInput subsystem. Sets up 16 controller slots with 0x800-byte pipe buffers. Contains gate CHECK at offset +0x11a |
| `0x01789c00` | YRT_Parent_Function (ShaderCacheManager) | `shadercachemanager.cpp` | Contains gate SET at offset +0x540. Handles shader cache management and backend hit cache generation |
| `0x00ec1330` | 0x8F_Dispatcher_1 | — | First command dispatcher with jump table. `cmp eax, 0x8f` at +0x74 |
| `0x00eed350` | 0x8F_Dispatcher_2 | — | Second command dispatcher with jump table. `cmp eax, 0x8f` at +0x74 |

## SDL Configuration (from FUN_011e45d0)

Steam loads SDL3 and sets these environment variables at startup:

| Variable | Value | Effect |
|----------|-------|--------|
| `SDL_JOYSTICK_HIDAPI_STEAM` | `"1"` | **Enables Steam HIDAPI driver** — this is the path that talks to SC2 |
| `SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS` | `"1"` | Allows input even when Steam window not focused |
| `SDL_JOYSTICK_ENHANCED_REPORTS` | `"1"` | Uses enhanced report format |
| `SDL_AUTO_UPDATE_JOYSTICKS` | `"1"` | Auto-discovers new controllers |
| `SDL_JOYSTICK_RAWINPUT` | `"1"` | Enables raw input path |
| `SDL_JOYSTICK_HIDAPI_STEAMXBOX` | `"0"` | Disables SteamXbox HIDAPI |
| `SDL_JOYSTICK_LINUX_DEADZONES` | `"0"` | Disables Linux deadzone handling |

**Critical insight**: `SDL_JOYSTICK_HIDAPI_STEAM=1` means Steam uses SDL3's HIDAPI driver for Steam controllers. This bypasses the kernel's `hid-steam` driver and communicates directly via HID feature/output reports.

## Haptic Pipeline (Inferred from code structure)

### Path 1: Game-level rumble (WORKING)
```
Game calls SDL_RumbleJoystick()
  → SDL_hid_write() to /dev/hidrawN
    → Kernel hog-ll → ATT Write Request (0x12) to handle 0x0019
      → _on_haptic_write() in main_l2cap.py
        → _forward_haptic_to_neptune() → os.write() to /dev/hidraw3
```
This path works because it's initiated by the game via SDL, not by Steam's internal controller logic.

### Path 2: Steam-generated haptics (NOT WORKING — blocked by gate)
```
Steam controller logic
  → Gate CHECK at [esi+0x17c] (offset 0x11a in FUN_0123e1e0)
    → If gate == 0: code path SKIPPED
      → 0x8F TRIGGER_HAPTIC_PULSE never dispatched
        → No haptic output to controller
```

**The gate at `[esi+0x17c]`** is checked in `FUN_0123e1e0` (the controller XInput initializer). When this byte is 0, the entire code path that sends 0x8F haptic commands is skipped. The gate is SET to 1 in `FUN_01789c00` (YRT_Parent_Function/ShaderCacheManager) at offset +0x540.

### Why the gate stays 0 on BLE
1. `FUN_01789c00` (gate SET) is never called on BLE connections
2. The YieldingRunTestProgram function it contains requires the HID connection to be fully established
3. On BLE, the HID connection stalls during initialization, so the gate never gets set
4. With gate == 0, the 0x8F dispatcher path is never entered

## Controller Registration Flow

```
1. BYieldingRegisterSteamController (0x0121a690)
   → QueryAccountsRegisteredToController (0x011beca0)
     → AccountHardware.QueryAccountsRegisteredToController#1 API
   → If no accounts: register new
   → AccountHardware.RegisterSteamController#1 API
   
2. BYieldingCompleteSteamControllerRegistration (0x01219bf0)
   → Checks controller identity
   → EYldWaitForControllerDetails (0x011cee30) with 2s timeout
   → AccountHardware.CompleteSteamControllerRegistration#1 API

3. Zombie detection: FUN_011f7630
   → Checks slot state == 3, flag == 0, connection state != 1 && != 4
```

## Key Offset Map (Controller Object)

| Offset | Size | Description |
|--------|------|-------------|
| `+0x17c` | byte | **Haptic gate flag** (0=blocked, 1=enabled). Checked by gate CHECK, set by YRT. This is the critical BLE blocker |
| `+0x1d8` | dword | **Graphics API type** (0=unset, 1=GL, 2=Vulkan, 3=D3D12A, 4=D3D12B). Written by constructor |
| `+0x1b0` | dword | Parent vtable pointer. Read by constructor, stored at +0x1d8 initially |
| `+0x1a8` | dword | Set to 0xC by 0x8F handler |
| `+0x1b0` | dword | Set to 0x3F by 0x8F handler |
| `+0x140` | ptr | Object pointer (used in many vtable calls) |
| `+0x428` | int | Backend hit cache generation |

## Next Steps

1. **Verify gate mechanism**: Set GDB watchpoint on `[esi+0x17c]` in the running Steam process to confirm it stays 0 on BLE
2. **Find what calls FUN_01789c00**: Trace the call chain that would set the gate
3. **Analyze FUN_012042d0** (Rumble_Handler_2): This may contain the actual haptic output path
4. **Map the 0x8F dispatcher jump table**: Find where command 0x8F jumps to in the dispatcher at 0x00ec1330
5. **Investigate LD_PRELOAD patch point**: If the gate CHECK at 0x0123e5fa can be patched to skip the check, haptics should work

## Files

| File | Content |
|------|---------|
| `exports/32bit/functions.csv` | 141,351 functions |
| `exports/32bit/strings.csv` | 56,317 strings |
| `exports/32bit/call_graph.csv` | 16,494 call edges |
| `exports/32bit/controller_decompiled_32bit.txt` | Decompiled C for 14 key functions |
| `exports/32bit/controller_xrefs_32bit.txt` | Xrefs to 12 controller-related strings |
| `exports/32bit/key_disassembly.txt` | Assembly for 9 known addresses |
| `exports/64bit/decompiled_64bit.txt` | Decompiled C for 18 key addresses (64-bit reference) |
