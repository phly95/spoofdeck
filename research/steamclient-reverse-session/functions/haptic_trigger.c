/*
 * What Triggers Haptic Writes — COMPLETE ANALYSIS
 *
 * Source of truth: SDL3 src/joystick/hidapi/SDL_hidapi_steam_triton.c
 *
 * Binary: ~/.steam/debian-installation/ubuntu12_32/steamclient.so (32-bit, 49MB)
 * Status: DETERMINED (from SDL3 source)
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
 * === HAPTIC WRITE TRIGGER CHAIN ===
 *
 * 1. Game calls SDL_RumbleJoystick(joystick, low_frequency_rumble, high_frequency_rumble)
 *
 * 2. SDL3 updates device context:
 *    ctx->low_frequency_rumble = low_frequency_rumble;
 *    ctx->high_frequency_rumble = high_frequency_rumble;
 *
 * 3. HIDAPI_DriverSteamTriton_UpdateDevice() is called periodically
 *    (every FAST_SCAN_INTERVAL = 6ms for Triton controllers)
 *
 * 4. UpdateDevice() checks two conditions:
 *    a) ctx->connected && joystick != NULL
 *    b) ctx->low_frequency_rumble || ctx->high_frequency_rumble (non-zero)
 *    c) (now - ctx->last_rumble_time) >= TRITON_RUMBLE_RESEND_INTERVAL_MS (40ms)
 *
 * 5. If all conditions met:
 *    - Calls HIDAPI_DriverSteamTriton_RumbleJoystick()
 *    - Constructs 10-byte OutputReportMsg:
 *        report_id = 0x80 (ID_OUT_REPORT_HAPTIC_RUMBLE)
 *        type = 0
 *        intensity = 0
 *        left.speed = low_frequency_rumble
 *        left.gain = 0
 *        right.speed = high_frequency_rumble
 *        right.gain = 0
 *    - Calls SDL_hid_write(device->dev, buffer, 10)
 *    - Updates ctx->last_rumble_time
 *
 * 6. When game sets rumble to 0, next UpdateDevice() call sees
 *    zero values and does NOT send any report. Controller's
 *    hardware safety timeout (~50ms) causes rumble to stop.
 */

/*
 * === LIZARD MODE TRIGGER ===
 *
 * Lizard mode is re-disabled periodically:
 *
 * SDL3: every 3000ms (ctx->last_lizard_update)
 *   if (!ctx->last_lizard_update || (now - ctx->last_lizard_update) >= 3000):
 *       DisableSteamTritonLizardMode(device->dev);
 *       ctx->last_lizard_update = now;
 *
 * Steam client (input_handler.py): every 2000ms
 *   if now - last_lizard_off >= 2.0:
 *       _send_lizard_off(self._neptune_fd)
 *       last_lizard_off = now
 *
 * The 5 lizard-off commands are sent in sequence:
 *   1. ClearDigitalMappings (0x81)
 *   2. RPadMode -> None (0x87, setting 8, value 7)
 *   3. LPadMode -> None (0x87, setting 7, value 7)
 *   4. SmoothAbsoluteMouse -> 0 (0x87, setting 24, value 0)
 *   5. SensitivityScaleAmount -> 0 (0x87, setting 21, value 0)
 */

/*
 * === CONDITIONS FOR HAPTIC WRITES ===
 *
 * For the Steam client (steamclient.so), haptic writes are triggered when:
 *
 * 1. A game uses the Steam Input API to rumble the controller
 *    (IVirtualController::TriggerHapticPulse or similar)
 *
 * 2. The CRumbleThread processes the haptic work item
 *    (CPulseHapticWorkItem, CSimpleHapticTickWorkItem, etc.)
 *
 * 3. The work item constructs a feature report or output report
 *    and sends it through the IPC pipe to the HID I/O thread
 *
 * 4. The HID I/O thread calls SDL_hid_write (for output reports)
 *    or SDL_hid_send_feature_report (for feature reports)
 *
 * Does SET_SETTINGS 0x09 lizard mode state affect haptics?
 *   - Lizard mode disables Steam Input processing
 *   - When lizard mode is ON, haptic commands from games are NOT processed
 *   - When lizard mode is OFF (SET_SETTINGS 0x09 with value 0), haptics work
 *   - So YES: lizard mode must be disabled for haptics to function
 */

/*
 * === RELEVANT BINARY ADDRESSES ===
 *
 * CRumbleThread string: VA 0x00aa5b00
 * CRumbleThread LEA ref: VA 0x0111d10b [32-bit: NEEDS RE-ANALYSIS]
 *   (jump table dispatcher at 0x0111d0a0 [32-bit: NEEDS RE-ANALYSIS] using string as table base)
 *
 * TriggerHapticPulse string: VA 0x00ab43f0
 * TriggerHapticPulse LEA refs: VA 0x01320765 [32-bit: NEEDS RE-ANALYSIS], 0x01320784 [32-bit: NEEDS RE-ANALYSIS], 0x01320859 [32-bit: NEEDS RE-ANALYSIS], 0x013208cb [32-bit: NEEDS RE-ANALYSIS]
 *   (in IClientTimeline dispatch, hash 0xf4ee1f05)
 *
 * ForceSimpleHapticEvent string: VA 0x00ab43b0
 * ForceSimpleHapticEvent LEA refs: VA 0x0132425b [32-bit: NEEDS RE-ANALYSIS], 0x0132427a [32-bit: NEEDS RE-ANALYSIS], 0x013242b6 [32-bit: NEEDS RE-ANALYSIS], 0x01324368 [32-bit: NEEDS RE-ANALYSIS]
 *
 * CWriteFeatureReportWorkItem RTTI: VA 0x00aa1880
 * CExitLizardModeWorkItem RTTI: VA 0x00aa19e0
 *
 * toggle_lizard string: VA 0x00ca6b56 (in string table at 0x02ae1ac8 [32-bit: NEEDS RE-ANALYSIS], index 0x1c)
 *   No direct LEA references — accessed via table lookup
 *
 * SDL_hid_send_feature_report string: VA 0x00cbb561
 *   Referenced at VA 0x00dfb22b (SDL HID vtable initialization)
 */
