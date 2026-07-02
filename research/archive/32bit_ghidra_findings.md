# 32-bit Binary RE Findings — Controller Behavior Map

> Generated: 2026-06-30 from Ghidra headless analysis of `ubuntu12_32/steamclient.so`
> Binary: 49MB, ELF 32-bit LSB, Intel 80386, not stripped

## Key Function Map (32-bit addresses)

| Address | Function | Source File | Description |
|---------|----------|-------------|-------------|
| `0x011b3a60` | CHIDIOThread_Main | `internalcallbacks.h` | Main HID I/O thread — creates worker threads, registers HID device callbacks |
| `0x011d5850` | CHIDIOThread_CWorkItem | `internalcallbacks.h` | CWorkItemThread — processes HID read/write work items |
| `0x011d8c40` | CHIDIOThread constructor | — | Allocates and initializes 0xBB78-byte controller manager object. 16 controller slots at stride 0xDC |
| `0x011e9be0` | Master controller constructor | — | Allocates and initializes 0xC34-byte master controller object |
| `0x011e9350` | PID-to-transport mapper | — | Maps PID to transport type: 0x1303→0 (BLE), 0x1302→3 (USB), 0x1304→1 (Dongle) |
| `0x01218840` | CGetControllerInfoWorkItem::RunFunc | — | Reads controller info via HID feature reports. Logs "Read failure" on error. Retries up to 51 times with 100ms sleep |
| `0x011cee30` | EYldWaitForControllerDetails | — | Blocks until controller details are ready. Calls `FUN_02ae47e0("EYldWaitForControllerDetails", 2000000, ...)` with 2-second timeout |
| `0x011f7630` | Zombie_Controller_Check | — | Detects zombie controllers (state=3, flag=0, connection!=1&&!=4). Logs "Zombie Controller" |
| `0x01219bf0` | BYieldingRegisterSteamController (identity path) | — | Checks controller identity before registration. Logs "couldn't get controller identity" on failure |
| `0x0121a690` | BYieldingRegisterSteamController | — | Full registration flow. Calls `AccountHardware.RegisterSteamController#1` API |
| `0x012191a0` | Per-controller slot initializer | `controller.cpp:0x1855` | Initializes 0xDC-byte controller slots. Sets offsets 0x1b0 (deadzone), 0x160 (graphics API), 0x1e8 (connection state) |
| `0x01202e70` | ControllerPersonalization | `controller.cpp` | Loads personalization settings (guide brightness, sounds, antidrift). Not a rumble handler despite our naming |
| `0x012042d0` | Rumble_Handler_2 | — | Second rumble-related function (needs further analysis) |
| `0x011cbae0` | Controller_Activity_Update | `controller.cpp:0x1772` | Updates controller activity. Checks `unControllerIndex < MAX_STEAM_CONTROLLERS` |
| `0x011e45d0` | SDL_JOYSTICK_HIDAPI_STEAM_Setup | — | Loads `libSDL3.so.0`, sets SDL env vars for HIDAPI Steam controller support |
| `0x011beca0` | QueryAccountsRegisteredToController | — | Queries which accounts are registered to a controller via `AccountHardware.QueryAccountsRegisteredToController#1` |
| `0x01217a30` | SET_SETTINGS dispatch | `controller.cpp:0xcc8` | Sends settings to controller. Fire-and-forget — no response read. Uses vtable[0x50] for write-only dispatch |
| `0x0123e1e0` | Gate_CHECK_Parent_Function | `controllerxinput_linux.cpp` | Initializes controller XInput subsystem. Sets up 16 controller slots with 0x800-byte pipe buffers |
| `0x0123e5da` | Gate CHECK function | — | 2103-byte function containing gate CHECK at 0x0123e5fb. Ghidra incorrectly merges this into FUN_0123e1e0 |
| `0x0173ce00` | Gate CLEAR — `RecvMsgAppStatus` | — | Only function that clears gate to 0. Called after successful controller status loop processing |
| `0x01789c00` | YRT_Parent_Function (ShaderCacheManager) | `shadercachemanager.cpp` | Contains gate SET at offset +0x540. Handles shader cache management and backend hit cache generation |
| `0x019aec80` | Graphics API type writer | — | Writes 1-4 to `[eax+0x160]` based on detected graphics API (GL/Vulkan/D3D12) |
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

**Root cause identified (2026-07-01)**: The controller initialization chain stalls because `CGetControllerInfoWorkItem::RunFunc` (0x01218840) calls wrapper vtable[5] (which internally calls `SDL_hid_read_timeout`) and gets 0 bytes. The read returns 0 because no ATT notifications reach `/dev/hidrawN` during the init window — the CCCD subscription registration has a timing gap where notifications are dropped before the subscription is registered.

The init chain:
```
CHIDIOThread_Main (0x011b3a60)
  → CWorkItemThread (0x011d5850)
    → CGetControllerInfoWorkItem::RunFunc (0x01218840)
      → Calls wrapper vtable[5] (SDL_hid_read_timeout internally)
      → Gets 0 bytes, retries 51 times × 100ms = 5.1 seconds
      → Logs "CGetControllerInfoWorkItem::RunFunc: Read failure" (controller.cpp:0x14cf)
      → After 51 retries: logs "too many read failures" → gives up
      → EYldWaitForControllerDetails (0x011cee30) times out after 2s
        → Gate SET at 0x0178a140 never reached
          → Gate [esi+0x17c] stays 0
            → 0x8F dispatcher path never entered
              → No haptic commands sent
```

### Haptic Pipeline (Post-Gate)

After the gate CHECK at `0x0123e5fb` passes (gate != 0), the code:
1. Validates command byte
2. Checks secondary flag `[esi+0x10c]`
3. Sets `[esi+0xa0] = 1` (haptic active)
4. Toggles state flag `[esi+0xa1]` or `[esi+0xa2]`
5. Calls `0x129ce50` (haptic dispatch core, 483 bytes) — iterates haptic targets
6. Computes intensity: `fild [esi+0x144] / rate + base_time`
7. Calls `0x129c8e0` (secondary processor, 741 bytes) — processes haptic effects

### Gate CLEAR Mechanism

The gate is cleared by exactly ONE function: `FUN_0173ce00` (0x0173ce00, `RecvMsgAppStatus`), at line 1614036:
```c
*(undefined1 *)(param_2 + 0x17c) = 0;  // CLEAR
```
This is the normal completion path after processing controller status updates. The gate is SET by 5 different functions but cleared only by this one. The function is dispatched for message type 0x251e from the `CRemoteClientManager` message dispatcher.

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

## BLE vs USB Transport Logic

The controller init function `FUN_0122ba20` (0x0122ba20, 9543 bytes) reads PID from `controller+0x48c` and sets the transport type at `controller+0xbc`:

| PID | Transport | `controller+0xbc` |
|-----|-----------|-------------------|
| 0x1303 (BLE SC2) | BLE | 2 |
| 0x1302 (USB SC2) | USB | 1 |
| 0x1220 (USB SC1) | USB | 1 |
| 0x1304 (Puck Dongle) | Dongle | 1 |
| Other | Unknown | 3 |

Key behavioral differences:
- **BLE** (type 2): Gets sensor-derived IMU polling rate via `FUN_01269650`
- **USB** (type 1): Gets config-forced IMU polling rate
- **BLE**: Gets timestamp-based timing via `FUN_01236770` when `0xbc > 1`
- **Both**: Skip extended initialization (only type 3 unknown PIDs get that)
- **Report to Steam**: Protocol type sent at report offset 0x51 (1=USB, 2=BLE)

The controller info struct (0x18 bytes) also stores transport at offset +4:
- 0 = USB/Dongle
- 1 = BLE

## Key Offset Map (Controller Object)

| Offset | Size | Description |
|--------|------|-------------|
| `+0x17c` | byte | **Haptic gate flag** (0=blocked, 1=enabled). SET by 5 functions, CLEAR only by `RecvMsgAppStatus` (0x0173ce00) |
| `+0x160` | dword | **Graphics API type** (1=GL, 2=Vulkan, 3=D3D12A, 4=D3D12B). Written by FUN_019aec80 (0x019aec80). NOTE: 32-bit offset is 0x160, NOT 0x1d8 (which is 64-bit) |
| `+0xbc` | int | **Protocol/transport type** (1=USB, 2=BLE, 3=other). Set during controller init based on PID |
| `+0x48c` | int | **Product ID** (0x1302=USB, 0x1303=BLE, 0x1304=Dongle) |
| `+0x1b0` | dword | Scale/deadzone factor (default 1.0f = 0x3f800000). Set by per-slot initializer |
| `+0xa0` | byte | Haptic active flag (set to 1 when haptic processing begins) |
| `+0x10c` | byte | Secondary haptic enable flag |
| `+0x144` | int | Haptic intensity integer |
| `+0x140` | ptr | Object pointer (used in many vtable calls) |
| `+0x4b0` | byte | "Is not dongle" flag (1=true for SC2, 0=false for dongle) |

## Next Steps

1. **Capture Steam controller.txt logs on host** — These contain the exact error messages from CGetControllerInfoWorkItem and the registration flow. Zero-effort, immediate answers.
2. **Capture btmon during BLE connection** — Shows the ATT traffic timing: when CCCDs are written, when our first notification arrives, when UHID_START fires. Identifies the timing gap.
3. **Verify CCCD write + notification flow** — Check if our `_notification_handles` set is populated when CGetControllerInfoWorkItem starts reading. Add logging to confirm CCCD writes arrive on the correct handles.
4. **Test with pre-sent notifications** — Modify our ATT server to send a burst of notifications immediately on connection (before waiting for Neptune input). This would pre-fill the UHID queue and ensure CGetControllerInfoWorkItem gets data.
5. **Native SC2 comparison** — Capture btmon + Steam logs with a real SC2 to establish the baseline timing (requires hardware we don't have).
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

---

## Firmware RE Findings (2026-06-30)

Ghidra analysis of the actual SC2 controller firmware (`IBEX_FW_6A3F2424.fw`) confirms and extends the host-side RE findings.

### Confirmed Matches (Firmware ↔ steamclient.so)

| Item | Firmware | steamclient.so | Status |
|------|----------|---------------|--------|
| Report 0x45 format | Byte-for-byte identical | Parsed correctly | ✅ Confirmed |
| PnP ID | VID=0x28DE, PID=0x1303 | Expected correctly | ✅ Confirmed |
| GET_ATTRIBUTES (0x83) | Handled in command dispatch | Handled in synthetic handler | ✅ Confirmed |
| 0x8F command | Exists in firmware command table | Blocked by host-side gate | ⚠️ Gate is host-side |

### Key Findings

1. **Command table**: 100 total commands in firmware (we handle 9). Jump table at `0x00053f94`.
2. **0x8F gate**: The gate at `[esi+0x17c]` is entirely in steamclient.so. Firmware handles 0x8F correctly.
3. **ESB protocol**: Puck is a transparent relay. Report IDs identical between ESB, USB, BLE ATT (Puck uses ESB, not BLE)
4. **GATT layout**: Only HID Service (0x1812) explicitly registered. Battery/Device Info NOT in firmware.
5. **Button bitmask**: Neptune HID path matches SDL3 exactly. No changes needed.
6. **State machine**: 25 states using Zephyr SMF. BLE and ESB coexist.

### Firmware-Specific Addresses

| Address | Function | Description |
|---------|----------|-------------|
| `0x0001d8d0` | `FUN_0001d8d0` | GATT registration — registers HID service with bt_gatt_pool API |
| `0x00013fe0` | `FUN_00013fe0` | Report sender — sets Report ID 0x45, copies 45 bytes, sends via BLE notification |
| `0x000127cc` | `FUN_000127cc` | Button bitfield assembly — builds 32-bit button bitmask |
| `0x000383c4` | `FUN_000383c4` | Main command dispatch — TBH jump table, 144 entries at `0x383d2` |
| `0x00054368` | `case 0x8f` | 0x8F sub-command dispatcher in firmware |
| `0x0003fc3e` | `FUN_0003fc3e` | CCCD gate — walks GATT DB before every notification send |
| `0x00042132` | `FUN_00042132` | 0xf2 ACK builder — 6-byte response `[01 00 00 00 00 f2]`, no payload |
| `0x000420ae` | `FUN_000420ae` | 0xf0 identity response — MAC + UUID (20B payload) |
| `0x0004214a` | `FUN_0004214a` | 0xf3 mode notification — mode byte (1B payload) |
| `0x00042108` | `FUN_00042108` | 0xf4 status response — timestamp + model (20B payload) |
| `0x00010d90` | `FUN_00010d90` | BLE command loop — handles 0xe2-0xe7, sends 0xf2 ACK after 0xe7 |
| `0x000445f2` | `fcn.000445f2` | Dispatch tail-call wrapper — sets r1=0, r2=0, branches to `0x383c4` |
| `0x0001b07c` | `fcn.0001b07c` | Message submit — parses message type, allocates buffer, submits to event bus |

## Firmware Binary Limitation

`ibex_firmware.bin` is 350,528 bytes (33.4% of nRF52840's 1MB flash). Command descriptor structures at `0x59b10`–`0x5a332` (19KB beyond the dump) are unreadable. Full flash dump via J-Link/SWD needed to read:
- 94 command descriptor structures (8-62 bytes each, variable-length)
- Haptic motor speed calculation code (addresses ≥ `0x55940`)
- 0x8F sub-command dispatcher implementation at `0x54368`

## Firmware Command Architecture

The dispatch at `FUN_000383c4` is a **pure lookup** — not a handler caller. The flow is:

1. Caller queries a lookup function for pending command type (returns negative value)
2. Caller negates to get positive command code (0x00-0x8F)
3. Dispatch loads descriptor pointer from flash via TBH table
4. Caller builds message structure: `[flags=0x1000003, msg_id, descriptor_ptr, buf_size=0x200]`
5. Message submitted to firmware event system via `fcn.0001b07c`
6. Event system processes the command using the descriptor

## Gate Mechanism (0x17c) — Full Interaction Map

The gate at offset 0x17c of the controller/status object has **7 interactions**:

| # | Function | Address | Operation | Context |
|---|----------|---------|-----------|---------|
| 1 | `FUN_0173ce00` (RecvMsgAppStatus) | 0x0173ce00 | **WRITE = 1** | Error/abnormal exit from message processing |
| 2 | `FUN_0173ce00` (RecvMsgAppStatus) | 0x0173ce00 | **WRITE = 0** | Normal path — after controller status loop completes |
| 3 | `FUN_0173fbb0` | 0x0173fbb0 | **WRITE = 1** | Conditional SET in a different message processing path |
| 4 | `FUN_016d5780` | 0x016d5780 | **READ `& 1`** | Bitmask check — gate is a multi-bit field, bit 0 = "enabled" |
| 5 | `FUN_01721710` | 0x01721710 | **READ** full byte | Used as BST lookup result — feeds into controller status |
| 6 | `FUN_02b92130` | 0x02b92130 | **READ == 0** check | Conditional gate check for a specific operation |
| 7 | `FUN_0247de42` | 0x0247de42 | **COPY** into message | Gate state is embedded in outgoing protocol messages |

## Input Path vs Command Path — Separation

The gate does NOT block input. The two paths are entirely separate:

**Input path (NOT gated):**
```
BLE ATT Notification → hog-ll → UHID → /dev/hidrawN
  → PollControllers (0x011e0930)
    → vtable[0x10]: non-blocking HID read
    → vtable[0x30]: PARSE report
    → vtable[0x34]: normalize sticks, apply deadzone
    → vtable[0x38]: apply calibration from VDF config
    → vtable[0x3c]: detect changes
  → Master Controller Processing (FUN_0126b130)
  → Per-Controller Processing (FUN_01285c30)
    → FUN_012857d0: generate Steam Input data
    → Create work item for Steam Input system
```

**Command path (GATED):**
```
Gate CHECK at 0x0123e5fb: cmp byte [esi+0x17c], 0
  → If 0: skip entire command pipeline
  → If 1: proceed with commands
    → 0x80 (Rumble), 0x81 (Clear Mappings), 0x83 (Get Attributes)
    → 0x85 (Set Mode), 0xB4 (Protocol Version), 0xEE/0xEF (Feature Messages)
    → Gyro enable/disable (0x50/0x30) via vtable[0x50]
    → Mode switch (0x08/0x09) via vtable[0x50]
```

**Why inputs work but haptics don't**: The gate blocks the command pipeline, but inputs bypass it entirely through the separate PollControllers path.

## Haptic Pipeline — Corrected

The addresses 0x129ce50 and 0x129c8e0 are **NOT haptic functions** — they are hash table and CUtlMap utility functions. The actual haptic pipeline is:

```
Game → SDL_RumbleJoystick(low_freq, high_freq)
  → HIDAPI_DriverSteamTriton_RumbleJoystick() [every 6ms, 40ms throttle]
  → SDL_hid_write(device, buffer, 10) [Report ID 0x80]
  → write("/dev/hidrawN") → kernel hidraw
  → uhid_hid_output_raw() → UHID_OUTPUT → BlueZ hog-ll
  → forward_report() → gatt_write_char() [ATT 0x12, handle 0x0019]
  → _on_haptic_write() → _forward_haptic_to_neptune()
  → PackedRumbleReport to /dev/hidraw3 → Neptune ERM motors
```

The Steam-generated haptic path (trackpad clicks, UI feedback) uses a different code path that is blocked by the gate. The config variables for this path include:
- `haptic_new`, `haptic_intensity`, `haptic_intensity_old`
- `haptic_off_divisor`, `ibex_rumble_deadzone`
- `g_RumbleRepeatAfterDelaySeconds` (0.050), `g_RumbleSustainTimeSeconds`

These are registered via `FUN_02587010` but the actual processing logic is in the Steam haptic work items (CHapticScriptWorkItem, CLegacySimpleHapticWorkItem, etc.), not at the addresses we previously identified.
