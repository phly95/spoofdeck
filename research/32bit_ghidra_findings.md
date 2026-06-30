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

## Haptic Pipeline (Verified from BlueZ 5.86 source + Ghidra decompilation)

### Path 1: Game-level rumble (WORKING)
```
Game calls SDL_RumbleJoystick()
  → SDL_hid_write() to /dev/hidrawN
    → Kernel hog-ll → UHID_OUTPUT event
      → BlueZ hog-ll forward_report() (hog-lib.c:746)
        → ATT Write Request (0x12) to handle 0x0019
          → _on_haptic_write() in main_l2cap.py
            → _forward_haptic_to_neptune() → os.write() to /dev/hidraw3
```
This path works because it's initiated by the game via SDL, not by Steam's internal controller logic.

### Path 2: Steam-generated haptics (NOT WORKING — init chain stalls)

**Root cause identified (2026-06-30)**: The entire command dispatch path is never entered on BLE because the controller initialization chain stalls.

The init chain:
```
CHIDIOThread_Main (0x011b3a60)
  → CWorkItemThread (0x011d5850)
    → CGetControllerInfoWorkItem::RunFunc (0x01218840)
      → Calls vtable[5] = SDL_hid_read_timeout() to read input reports
      → Gets 0 bytes, retries 51 times × 100ms = 5.1 seconds
      → Logs "CGetControllerInfoWorkItem::RunFunc: Read failure" (controller.cpp:0x14cf)
      → After 51 retries: logs "too many read failures" → gives up
      → EYldWaitForControllerDetails (0x011cee30) times out after 2s
        → Gate SET at 0x0178a140 never reached
          → Gate [esi+0x17c] stays 0
            → 0x8F dispatcher path never entered
              → No haptic commands sent
```

### Why SDL_hid_read_timeout returns 0 bytes

The notification pipeline from our ATT server to Steam's hid_read is:
```
1. Our Python sends ATT Notification PDU on handle 0x0012 (12 bytes gamepad data)
2. Host kernel Bluetooth stack delivers to BlueZ hog-ll
3. report_value_cb() (hog-lib.c:323) strips 3-byte ATT header → 12 bytes raw report
4. bt_uhid_input(uhid, report->numbered ? report->id : 0, pdu, len) (uhid.c:464)
5. If report->numbered: UHID_INPUT2 = [0x01] + [12 bytes] = 13 bytes
6. If uhid->started is false: events are QUEUED, not delivered to /dev/hidrawN
7. Once UHID_START received: queue is flushed → events delivered to /dev/hidrawN
8. SDL_hid_read_timeout() reads from /dev/hidrawN → CGetControllerInfoWorkItem
```

**The `uhid->started` gate (uhid.c:486-493)**:
```c
/* Queue events if UHID_START has not been received yet */
if (!uhid->started) {
    queue_push_tail(uhid->input, util_memdup(&ev, sizeof(ev)));
    return 0;  // event queued, not delivered
}
return bt_uhid_send(uhid, &ev);  // event delivered to /dev/hidrawN
```

The `numbered` flag is set in `set_numbered()` (hog-lib.c:780) based on `UHID_DEV_NUMBERED_INPUT_REPORTS` kernel flag, which is set in `uhid_start()` (uhid.c:382) after `UHID_CREATE2` is processed.

**Most likely cause**: CGetControllerInfoWorkItem starts reading BEFORE notifications reach `/dev/hidrawN`. Possible reasons:
1. Our input handler hasn't started sending yet (Neptune `/dev/hidraw3` not available, startup delay)
2. CCCD writes from hog-ll haven't been processed yet (notification handles not in `_notification_handles`)
3. UHID device creation is slow (Report Map → UHID_CREATE2 → kernel → UHID_START)

### Notification-to-hid_read timing analysis

The hog-ll initialization sequence (from BlueZ 5.86 source):
```
bt_hog_attach() (hog-lib.c:1720)
  → Discovers Report characteristics (char_discovered_cb / foreach_hog_chrc)
    → discover_report() → discover_report_cb()
      → Reads Report Reference descriptor → report_reference_cb()
        → report->id = pdu[1];  report->type = pdu[2]
        → For INPUT reports: reads CCCD → ccc_read_cb() → write_ccc()
          → report_ccc_written_cb() → g_attrib_register(ATT_OP_HANDLE_NOTIFY, report_value_cb)
  → read_report_map() → report_map_read_cb() → uhid_create() → bt_uhid_create()
    → Kernel processes UHID_CREATE2 → creates /dev/hidrawN → sends UHID_START
      → uhid_start() → uhid->started = true → queue_flushed
```

**Critical**: Notification callbacks are registered (step 3) BEFORE UHID device is created (step 4). So our notifications CAN reach hog-ll before UHID_START. They get queued and delivered once the queue is flushed.

**The question is timing**: How long between BLE connection and CGetControllerInfoWorkItem's first read? If it's less than ~1 second, notifications may not have arrived yet.

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

1. **Capture Steam controller.txt logs on host** — These contain the exact error messages from CGetControllerInfoWorkItem and the registration flow. Zero-effort, immediate answers.
2. **Capture btmon during BLE connection** — Shows the ATT traffic timing: when CCCDs are written, when our first notification arrives, when UHID_START fires. Identifies the timing gap.
3. **Verify CCCD write + notification flow** — Check if our `_notification_handles` set is populated when CGetControllerInfoWorkItem starts reading. Add logging to confirm CCCD writes arrive on the correct handles.
4. **Test with pre-sent notifications** — Modify our ATT server to send a burst of notifications immediately on connection (before waiting for Neptune input). This would pre-fill the UHID queue and ensure CGetControllerInfoWorkItem gets data.
5. **Native SC2 comparison** — Capture btmon + Steam logs with a real SC2 to establish the baseline timing.
6. **GDB on host Steam process** — Breakpoint on `CGetControllerInfoWorkItem::RunFunc` (0x01218840) to see what `hid_read` returns and how many retries it takes.

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
