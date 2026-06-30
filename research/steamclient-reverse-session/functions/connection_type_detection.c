/*
 * Connection Type Detection — COMPLETE ANALYSIS
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
 * Steam determines connection type (BLE, USB, Dongle) via:
 * 1. Product ID dispatch at 0x010c4a00 [32-bit: NEEDS RE-ANALYSIS] (primary method)
 * 2. Connection type bitfield at controller+0x180 (runtime state)
 * 3. Protobuf transport enum (wireless_transport field)
 *
 * The product ID determines the transport at handler creation time.
 * The bitfield tracks active transport connections at runtime.
 */

/*
 * === METHOD 1: PRODUCT ID DISPATCH (0x010c4a00 [32-bit: NEEDS RE-ANALYSIS]) ===
 *
 * The function at 0x010c4a00 [32-bit: NEEDS RE-ANALYSIS] is the main HID protocol dispatch.
 * It reads the product ID from [r12+0x3c] and routes to the
 * appropriate handler path.
 *
 * Flow:
 *   r12 → handler object (48 bytes)
 *   eax ← [r12+0x3c] (product ID)
 *
 *   cmp eax, 0x1106     → 0x010c4c30 [32-bit: NEEDS RE-ANALYSIS] (upper branch)
 *   cmp eax, 0x1104     → 0x010c4734 [32-bit: NEEDS RE-ANALYSIS]
 *   cmp eax, 0x1042     → 0x010c4a59 [32-bit: NEEDS RE-ANALYSIS] (generic V1 HID)
 *   sub eax, 0x1101; cmp eax, 1 → ja 0x010c4b51 [32-bit: NEEDS RE-ANALYSIS] (unrecognized)
 *   cmp eax, 0x1303     → 0x010c4de0 [32-bit: NEEDS RE-ANALYSIS] (BLE path!)
 *   sub eax, 0x1304; cmp eax, 1 → jbe 0x010c4c40 [32-bit: NEEDS RE-ANALYSIS] (dongle path)
 *
 * Product ID → Transport → Handler Path:
 *
 *   0x1002-0x1004  USB         0x010c4a59 [32-bit: NEEDS RE-ANALYSIS]
 *   0x1042         Generic     0x010c4a59 [32-bit: NEEDS RE-ANALYSIS]
 *   0x1101-0x1102  Generic     0x010c4a59 [32-bit: NEEDS RE-ANALYSIS]
 *   0x1104         ?           0x010c4734 [32-bit: NEEDS RE-ANALYSIS]
 *   0x1106         ?           0x010c4c30 [32-bit: NEEDS RE-ANALYSIS]
 *   0x1142         Generic     0x010c4a59 [32-bit: NEEDS RE-ANALYSIS]
 *   0x1220         USB         0x010c4940 [32-bit: NEEDS RE-ANALYSIS]
 *   0x1303         BLE         0x010c4de0 [32-bit: NEEDS RE-ANALYSIS] → 0x010c4e0c [32-bit: NEEDS RE-ANALYSIS]
 *   0x1304-0x1305  Dongle      0x010c4c40 [32-bit: NEEDS RE-ANALYSIS]
 *   0x28de         ?           0x010c48b6 [32-bit: NEEDS RE-ANALYSIS] → 0x010c46ec [32-bit: NEEDS RE-ANALYSIS]
 */

/*
 * === METHOD 2: BLE FLAG IN HANDLER OBJECT ===
 *
 * Each transport path sets a flag at handler+0x08:
 *
 * BLE path (0x010c4e71 [32-bit: NEEDS RE-ANALYSIS]):
 *   mov byte [r12 + 8], 1     ; BLE = 1
 *
 * Dongle path (0x010c4c40 [32-bit: NEEDS RE-ANALYSIS]):
 *   mov byte [r12 + 8], 0     ; BLE = 0
 *
 * USB path (0x010c4940 [32-bit: NEEDS RE-ANALYSIS]):
 *   mov byte [r12 + 8], 0     ; BLE = 0
 *
 * This flag is a metadata marker used throughout the code to
 * conditionally execute BLE-specific logic (e.g., different
 * initialization sequences, bond management, timing).
 */

/*
 * === METHOD 3: CONNECTION TYPE BITFIELD (controller+0x180) ===
 *
 * At runtime, the connection type is stored as a bitfield at
 * controller offset 0x180. This is loaded and checked in the
 * function at 0x0111b180 [32-bit: NEEDS RE-ANALYSIS]:
 *
 *   mov r13, [rdi+0x180]     ; load connection type bitfield
 *   test r13, r13
 *   je 0x111b340              ; if null, skip
 *
 * A jump table at 0x00aa5ab4 dispatches based on individual bit checks:
 *
 *   Bit  Shift  Location      Possible Meaning
 *   0    shr 0  0x0111b2f0 [32-bit: NEEDS RE-ANALYSIS]    transport type A
 *   1    shr 1  0x0111b300 [32-bit: NEEDS RE-ANALYSIS]    transport type B
 *   2    shr 2  0x0111b2d0 [32-bit: NEEDS RE-ANALYSIS]    transport type C
 *   3    shr 3  0x0111b310 [32-bit: NEEDS RE-ANALYSIS]    transport type D
 *   5    shr 5  0x0111b2b0 [32-bit: NEEDS RE-ANALYSIS]    transport type E
 *   11   shr 0xb 0x0111b330 [32-bit: NEEDS RE-ANALYSIS]   transport type F
 *   12   shr 0xc 0x0111b2c0 [32-bit: NEEDS RE-ANALYSIS]   transport type G
 *   24   shr 0x18 0x0111b208 [32-bit: NEEDS RE-ANALYSIS]  transport type H
 *   25   shr 0x19 0x0111b320 [32-bit: NEEDS RE-ANALYSIS]  transport type I
 *   39   shr 0x27 0x0111b1d4 [32-bit: NEEDS RE-ANALYSIS]  "wired" check → stored at [rsp+0xf]
 *
 * The bit 39 check (wired) is used to determine if the controller
 * is connected via a wired (USB) connection vs wireless (BLE/Dongle).
 */

/*
 * === METHOD 4: PROTOBUF TRANSPORT ENUM ===
 *
 * From the string table at 0x00a74076:
 *
 *   Value  Name           Description
 *   0      Triton_BL      Triton bootloader
 *   1      Proteus_BL     Proteus bootloader
 *   2      Triton_USB     Triton wired USB
 *   3      Triton_BLE     Triton Bluetooth LE
 *   4      Triton_ESB     Triton dongle (ESB)
 *   5      Proteus_USB    Proteus wired USB
 *   6      Nereid_USB     Nereid wired USB
 *
 * "Triton" = SC2 controller codename
 * "ESB" = Enhanced ShockBurst (Nordic's protocol for dongle)
 * "BL" = Bootloader
 * "Proteus" = Steam Controller 1 (original)
 * "Nereid" = Another controller variant
 *
 * The protobuf field "wireless_transport" at 0x00ae1435 encodes this
 * value in messages sent between Steam client and controller.
 */

/*
 * === HOW TRANSPORT AFFECTS HAPTICS ===
 *
 * 1. BLE (0x1303, Triton_BLE):
 *    - Haptics sent via ATT Write Command (0x52) to output report handle (0x0019)
 *    - BlueZ HOG profile handles the BLE communication
 *    - steamclient.so sends feature reports via IPC to bluetoothd
 *    - bluetoothd forwards via ATT operations
 *    - The set_report_cb() error (ATT error 0x0E) may indicate initialization issues
 *
 * 2. USB (0x1302, Triton_USB):
 *    - Haptics sent via SDL_hid_write() directly (no BLE stack)
 *    - steamclient.so opens /dev/hidrawN directly
 *    - Feature reports via SDL_hid_send_feature_report()
 *    - Output reports via SDL_hid_write()
 *
 * 3. Dongle (0x1304/0x1305, Triton_ESB):
 *    - Haptics sent via dongle protocol (ESB - Enhanced ShockBurst)
 *    - Similar to USB but through dongle's wireless interface
 *    - steamclient.so communicates with dongle via hidraw
 *    - Dongle forwards to controller via ESB
 *
 * KEY DIFFERENCE:
 * - BLE: steamclient.so → IPC → bluetoothd → ATT → controller
 * - USB: steamclient.so → SDL_hid_write() → /dev/hidrawN → controller
 * - Dongle: steamclient.so → SDL_hid_write() → dongle → ESB → controller
 */

/*
 * === BLE-SPECIFIC INITIALIZATION ===
 *
 * The BLE path at 0x010c4e0c [32-bit: NEEDS RE-ANALYSIS] sets up additional state:
 *
 *   0x010c4e56 [32-bit: NEEDS RE-ANALYSIS]: mov edi, 0x30              ; sizeof = 48 bytes
 *   0x010c4e5f [32-bit: NEEDS RE-ANALYSIS]: call 0x2a6ca70             ; operator new
 *   0x010c4e71 [32-bit: NEEDS RE-ANALYSIS]: mov byte [r12 + 8], 1     ; BLE flag = 1
 *   0x010c4e77 [32-bit: NEEDS RE-ANALYSIS]: mov qword [r12], rax      ; vtable = 0x02ae1b58 [32-bit: NEEDS RE-ANALYSIS]
 *   0x010c4e9d [32-bit: NEEDS RE-ANALYSIS]: call 0x2228880             ; string init (bond state?)
 *   0x010c4ea2 [32-bit: NEEDS RE-ANALYSIS]: jmp 0x10c4a0e             ; common exit (vtable overwrite)
 *
 * The call to 0x2228880 after BLE handler creation may initialize
 * BLE-specific state (bond management, connection parameters, etc.).
 *
 * Related BLE strings:
 *   "tritoncontroller.cpp" at 0x00cbf534
 *   "triton bond state" at 0x00cc0a90
 *   "triton pair bond" at 0x00c1b97f
 *   "Failed to read triton info from controller" at 0x00cc468f
 */

/*
 * === V1 HID PROTOCOL VARIANTS ===
 *
 * The binary recognizes 4 V1 HID protocol variants:
 *
 * 1. "Controller uses V1 HID protocol\n" (0x00cef4d0)
 *    - Generic USB/unknown controller
 *    - Handler: 0x010c4a59 [32-bit: NEEDS RE-ANALYSIS]
 *
 * 2. "Controller uses V1 HID protocol via USB\n" (0x00cf1150)
 *    - Explicit USB connection
 *    - Handler: 0x010c4940 [32-bit: NEEDS RE-ANALYSIS]
 *
 * 3. "Controller uses V1 HID protocol via Dongle\n" (0x00ba2bac)
 *    - Dongle (ESB) connection
 *    - Handler: 0x010c4c40 [32-bit: NEEDS RE-ANALYSIS]
 *
 * 4. "Controller uses V1 HID protocol via BLE\n" (0x00ba2c28)
 *    - Bluetooth LE connection
 *    - Handler: 0x010c4de0 [32-bit: NEEDS RE-ANALYSIS] → 0x010c4e0c [32-bit: NEEDS RE-ANALYSIS]
 *
 * 5. "Unrecognized controller using V1 HID protocol\n" (0x00cef4d0)
 *    - Unknown product ID
 *    - Handler: 0x010c4b51 [32-bit: NEEDS RE-ANALYSIS]
 *
 * Additionally: "Controller uses V2 HID protocol" at 0x00cef00f
 *    - Newer protocol version (not used for SC2)
 */

/*
 * === BINARY REFERENCES ===
 *
 * Product ID dispatch: 0x010c4a00 [32-bit: NEEDS RE-ANALYSIS]
 * BLE handler: 0x010c4de0 [32-bit: NEEDS RE-ANALYSIS] → 0x010c4e0c [32-bit: NEEDS RE-ANALYSIS]
 * Dongle handler: 0x010c4c40 [32-bit: NEEDS RE-ANALYSIS]
 * USB handler: 0x010c4940 [32-bit: NEEDS RE-ANALYSIS]
 * Generic handler: 0x010c4a59 [32-bit: NEEDS RE-ANALYSIS]
 * Common exit: 0x010c4a0e [32-bit: NEEDS RE-ANALYSIS]
 * Connection bitfield: controller+0x180
 * Jump table: 0x00aa5ab4
 * BLE flag: handler+0x08
 * Initialized flag: handler+0x28
 *
 * String references:
 * "Controller uses V1 HID protocol via BLE" at 0x00ba2c28
 * "Controller uses V1 HID protocol via Dongle" at 0x00ba2bac
 * "Controller uses V1 HID protocol via USB" at 0x00cf1150
 * "Controller uses V1 HID protocol" at 0x00cef4d0
 * "Unrecognized controller using V1 HID protocol" at 0x00cef4d0
 * "V2 HID protocol" at 0x00cef00f
 *
 * Protobuf transport enum: 0x00a74076
 * "wireless_transport" field: 0x00ae1435
 * "tritoncontroller.cpp": 0x00cbf534
 * "triton wireless protocol": 0x00c1b90b
 * "triton bond state": 0x00cc0a90
 * "triton pair bond": 0x00c1b97f
 */
