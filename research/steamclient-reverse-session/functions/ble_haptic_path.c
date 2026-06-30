/*
 * BLE vs USB Code Paths for Haptic/Output Reports — COMPLETE ANALYSIS
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
 * The Steam client binary does NOT call SDL_hid_write() directly for haptic
 * output reports. Instead, it uses feature reports (SDL_hid_send_feature_report)
 * via protobuf IPC. The BLE vs USB distinction affects handler initialization
 * but ALL transport types share the same output report vtable (0x02ae1c10 [32-bit: NEEDS RE-ANALYSIS]).
 *
 * The BLE flag at handler+0x08 is a metadata marker that gates behavior
 * elsewhere in the code, NOT at the vtable level.
 *
 * CRITICAL FINDING: The addresses 0x013205a3 [32-bit: NEEDS RE-ANALYSIS] and 0x01322dae [32-bit: NEEDS RE-ANALYSIS] from previous
 * sessions are NOT haptic functions — they are IClientTimeline and
 * IClientVideo vtable dispatchers respectively.
 */

/*
 * === BLE HANDLER OBJECT (48 bytes, allocated at 0x010c4e0c [32-bit: NEEDS RE-ANALYSIS]) ===
 *
 * Offset  Size  Description
 * +0x00   8     vtable pointer → 0x02ae1c10 [32-bit: NEEDS RE-ANALYSIS] (OUTPUT REPORT vtable)
 * +0x08   1     BLE flag: 1=BLE, 0=USB/Dongle
 * +0x10   8     context/parent pointer (ebx stored here)
 * +0x18   8     null (zeroed on init)
 * +0x20   8     null (zeroed on init)
 * +0x28   1     "initialized" flag (set to 1 after registration)
 *
 * BLE path (0x010c4e0c [32-bit: NEEDS RE-ANALYSIS]):
 *   mov byte [r12 + 8], 1     ; BLE flag = 1
 *   mov qword [r12], rax      ; vtable = 0x02ae1b58 [32-bit: NEEDS RE-ANALYSIS] (initial vtable)
 *
 * Dongle path (0x010c4c40 [32-bit: NEEDS RE-ANALYSIS]):
 *   mov byte [r12 + 8], 0     ; BLE flag = 0
 *   mov qword [r12], rax      ; vtable = 0x02ae1b58 [32-bit: NEEDS RE-ANALYSIS] (initial vtable)
 *
 * USB path (0x010c4940 [32-bit: NEEDS RE-ANALYSIS]):
 *   mov byte [r12 + 8], 0     ; BLE flag = 0
 *   mov qword [r12], rax      ; vtable = 0x02ae1b58 [32-bit: NEEDS RE-ANALYSIS] (initial vtable)
 *
 * COMMON EXIT (0x010c4a0e [32-bit: NEEDS RE-ANALYSIS]):
 *   lea rax, [0x02ae1c10 [32-bit: NEEDS RE-ANALYSIS]]     ; Load OUTPUT REPORT vtable
 *   mov byte [r12+0x28], 1    ; Set "initialized" flag
 *   mov qword [r12], rax      ; OVERWRITE vtable → 0x02ae1c10 [32-bit: NEEDS RE-ANALYSIS]
 *   jmp 0x10c4850             ; Jump to common cleanup
 *
 * KEY: ALL paths (BLE, USB, Dongle) end up with the SAME vtable (0x02ae1c10 [32-bit: NEEDS RE-ANALYSIS]).
 * The BLE flag at +0x08 does NOT change the vtable or output report structure.
 */

/*
 * === OUTPUT REPORT VTABLE AT 0x02ae1c10 [32-bit: NEEDS RE-ANALYSIS] ===
 *
 * This vtable is used by ALL transport types. It provides the interface
 * for sending output/feature reports to the controller.
 *
 * The vtable delegates to the SDL HID vtable at 0x02c69a10 [32-bit: NEEDS RE-ANALYSIS], which is
 * populated by dlsym() at startup.
 */

/*
 * === SDL HID VTABLE AT 0x02c69a10 [32-bit: NEEDS RE-ANALYSIS] ===
 *
 * Populated by entry.init345 (0x01760e80 [32-bit: NEEDS RE-ANALYSIS]) using dlsym().
 *
 * Slot   Offset  Function
 * 0      +0x00   (data/context)
 * 1      +0x08   (data/context)
 * 2      +0x10   (function ptr)
 * 3      +0x18   SDL_hid_write ← THIS IS THE ONE
 * 4      +0x20   (function ptr)
 * 5      +0x28   (function ptr)
 * ...
 *
 * Resolution order (from entry.init345):
 *   1. SDL_hid_get_product_string
 *   2. SDL_hid_get_manufacturer_string
 *   3. SDL_hid_close
 *   4. SDL_hid_get_feature_report
 *   5. SDL_hid_send_feature_report
 *   6. SDL_hid_set_nonblocking
 *   7. SDL_hid_read_timeout
 *   8. SDL_hid_write          ← resolved via dlsym at 0x00e16f04
 *   9. SDL_hid_open_path
 *  10. SDL_hid_free_enumeration
 *  11. SDL_hid_enumerate
 *  12. SDL_hid_device_change_count
 *  13. SDL_hid_exit
 *  14. SDL_hid_init
 */

/*
 * === CONNECTION TYPE BITFIELD AT CONTROLLER+0x180 ===
 *
 * The connection type is stored as a bitfield at controller offset 0x180.
 * Individual bits are checked to determine transport type:
 *
 * Bit  Shift  Location        Likely Meaning
 * 0    shr 0  0x0111b2f0 [32-bit: NEEDS RE-ANALYSIS]      transport flag
 * 1    shr 1  0x0111b300 [32-bit: NEEDS RE-ANALYSIS]      transport flag
 * 2    shr 2  0x0111b2d0 [32-bit: NEEDS RE-ANALYSIS]      transport flag
 * 3    shr 3  0x0111b310 [32-bit: NEEDS RE-ANALYSIS]      transport flag
 * 5    shr 5  0x0111b2b0 [32-bit: NEEDS RE-ANALYSIS]      transport flag
 * 11   shr 0xb 0x0111b330 [32-bit: NEEDS RE-ANALYSIS]     transport flag
 * 12   shr 0xc 0x0111b2c0 [32-bit: NEEDS RE-ANALYSIS]     transport flag
 * 24   shr 0x18 0x0111b208 [32-bit: NEEDS RE-ANALYSIS]    transport flag
 * 25   shr 0x19 0x0111b320 [32-bit: NEEDS RE-ANALYSIS]    transport flag
 * 39   shr 0x27 0x0111b1d4 [32-bit: NEEDS RE-ANALYSIS]    "wired" check (stored at [rsp+0xf])
 *
 * The bitfield is loaded from [rdi+0x180] at 0x0111b191 [32-bit: NEEDS RE-ANALYSIS]:
 *   mov r13, [rdi+0x180]     ; load connection type bitfield
 *   test r13, r13
 *   je 0x111b340              ; if null, skip
 *
 * Then a jump table at 0x00aa5ab4 dispatches based on bit checks.
 * The jne at 0x0111b21a [32-bit: NEEDS RE-ANALYSIS] (after bit 24 check) jumps to:
 *   mov byte [rax+0x108], 0   ; clear pending flag
 */

/*
 * === KEY FINDING: NO BLE-SPECIFIC GATE ON OUTPUT REPORTS ===
 *
 * After exhaustive search:
 * 1. ALL transport types use the same output report vtable (0x02ae1c10 [32-bit: NEEDS RE-ANALYSIS])
 * 2. The BLE flag (handler+0x08) is metadata only - no conditional at vtable level
 * 3. The binary does NOT have separate SDL_hid_write paths for BLE vs USB
 * 4. The actual haptic output report construction was NOT found in the binary
 *
 * The binary uses feature reports via CWriteFeatureReportWorkItem protobuf IPC,
 * NOT output reports via SDL_hid_write. The SDL_hid_write path exists in the
 * vtable but may only be used for non-haptic purposes (e.g., sensor data).
 *
 * The haptic output report (0x80) path that we see in btmon captures comes from
 * the BlueZ HOG profile (bluetoothd), not from steamclient.so directly.
 * steamclient.so sends feature reports via IPC, and bluetoothd handles the
 * actual BLE HID communication.
 */

/*
 * === PRODUCT ID → TRANSPORT MAPPING ===
 *
 * Product ID  Hex     Transport  Handler Path
 * 0x1002-4    0x1002  USB        0x010c4a59 [32-bit: NEEDS RE-ANALYSIS] (generic V1 HID)
 * 0x1042      0x1042  Generic    0x010c4a59 [32-bit: NEEDS RE-ANALYSIS]
 * 0x1101-2    0x1101  Generic    0x010c4a59 [32-bit: NEEDS RE-ANALYSIS]
 * 0x1104      0x1104  ?          0x010c4734 [32-bit: NEEDS RE-ANALYSIS]
 * 0x1106      0x1106  ?          0x010c4c30 [32-bit: NEEDS RE-ANALYSIS]
 * 0x1142      0x1142  Generic    0x010c4a59 [32-bit: NEEDS RE-ANALYSIS]
 * 0x1220      0x1220  USB        0x010c4940 [32-bit: NEEDS RE-ANALYSIS]
 * 0x1303      0x1303  BLE        0x010c4de0 [32-bit: NEEDS RE-ANALYSIS] → 0x010c4e0c [32-bit: NEEDS RE-ANALYSIS]
 * 0x1304      0x1304  Dongle     0x010c4c40 [32-bit: NEEDS RE-ANALYSIS]
 * 0x1305      0x1305  Dongle     0x010c4c40 [32-bit: NEEDS RE-ANALYSIS]
 * 0x28de      0x28de  ?          0x010c48b6 [32-bit: NEEDS RE-ANALYSIS] → 0x010c46ec [32-bit: NEEDS RE-ANALYSIS]
 *
 * All paths: allocate 0x30 bytes, set vtable to 0x02ae1b58 [32-bit: NEEDS RE-ANALYSIS],
 * then common exit overwrites vtable to 0x02ae1c10 [32-bit: NEEDS RE-ANALYSIS].
 */

/*
 * === PROTOBUF TRANSPORT ENUM (from string table at 0x00a74076) ===
 *
 * Value  Name           Description
 * 0      Triton_BL      Triton bootloader
 * 1      Proteus_BL     Proteus bootloader
 * 2      Triton_USB     Triton wired USB
 * 3      Triton_BLE     Triton Bluetooth LE    ← THIS IS THE ONE
 * 4      Triton_ESB     Triton dongle (ESB)
 * 5      Proteus_USB    Proteus wired USB
 * 6      Nereid_USB     Nereid wired USB
 *
 * "Triton" is Valve's codename for the SC2 BLE controller.
 * "ESB" = Enhanced ShockBurst (Nordic's protocol used by the dongle).
 */

/*
 * === REFERENCES ===
 *
 * BLE handler allocation: 0x010c4de0 [32-bit: NEEDS RE-ANALYSIS] → 0x010c4e0c [32-bit: NEEDS RE-ANALYSIS]
 * Dongle handler: 0x010c4c40 [32-bit: NEEDS RE-ANALYSIS]
 * USB handler: 0x010c4940 [32-bit: NEEDS RE-ANALYSIS]
 * Common exit (vtable overwrite): 0x010c4a0e [32-bit: NEEDS RE-ANALYSIS]
 * Output report vtable: 0x02ae1c10 [32-bit: NEEDS RE-ANALYSIS]
 * SDL HID vtable: 0x02c69a10 [32-bit: NEEDS RE-ANALYSIS]
 * Connection type bitfield: controller+0x180
 * Jump table: 0x00aa5ab4
 *
 * String references:
 * "Controller uses V1 HID protocol via BLE" at 0x00ba2c28
 * "Controller uses V1 HID protocol via Dongle" at 0x00ba2bac
 * "Controller uses V1 HID protocol via USB" at 0x00cf1150
 * "Controller uses V1 HID protocol" at 0x00cef4d0
 * "tritoncontroller.cpp" at 0x00cbf534
 * "triton wireless protocol" at 0x00c1b90b
 * "triton bond state" at 0x00cc0a90
 * "triton pair bond" at 0x00c1b97f
 */
