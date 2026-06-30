/*
 * Haptic Feature Report Write — COMPLETE PROTOCOL REFERENCE
 *
 * Source of truth: SDL3 src/joystick/hidapi/steam/controller_structs.h
 *                  SDL3 src/joystick/hidapi/steam/controller_constants.h
 *                  SDL3 src/joystick/hidapi/SDL_hidapi_steam_triton.c
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
 * === HAPTIC OUTPUT REPORTS (NOT Feature Reports!) ===
 *
 * IMPORTANT: Haptic commands use SDL_hid_write (output reports),
 * NOT SDL_hid_send_feature_report (feature reports).
 *
 * This is a critical distinction:
 * - Feature Reports: used for SET_SETTINGS, GET_ATTRIBUTES, etc.
 *   Sent via SDL_hid_send_feature_report() with Report ID 0x01
 * - Output Reports: used for haptic commands
 *   Sent via SDL_hid_write() with Report IDs 0x80-0x85
 */

/*
 * === HAPTIC OUTPUT REPORT IDs (ValveTritonOutReportMessageIDs) ===
 *
 * 0x80 = ID_OUT_REPORT_HAPTIC_RUMBLE     (10 bytes)
 * 0x81 = ID_OUT_REPORT_HAPTIC_PULSE      (8 bytes)
 * 0x82 = ID_OUT_REPORT_HAPTIC_COMMAND     (4 bytes)
 * 0x83 = ID_OUT_REPORT_HAPTIC_LFO_TONE   (10 bytes)
 * 0x84 = ID_OUT_REPORT_HAPTIC_LOG_SWEEP  (9 bytes)
 * 0x85 = ID_OUT_REPORT_HAPTIC_SCRIPT      (4 bytes)
 */

/*
 * === HAPTIC RUMBLE (ID_OUT_REPORT_HAPTIC_RUMBLE = 0x80) ===
 *
 * Output Report ID: 0x80
 * Total size: HID_RUMBLE_OUTPUT_REPORT_BYTES = 10
 *
 * Byte 0:   report_id = 0x80
 * Byte 1:   type (uint8)  — haptic type (0 = HAPTIC_TYPE_OFF)
 * Byte 2-3: intensity (uint16 LE) — overall intensity
 * Byte 4-5: left.speed (uint16 LE) — left motor speed (low_frequency_rumble)
 * Byte 6:   left.gain (int8) — left motor gain (0)
 * Byte 7-8: right.speed (uint16 LE) — right motor speed (high_frequency_rumble)
 * Byte 9:   right.gain (int8) — right motor gain (0)
 *
 * C code (HIDAPI_DriverSteamTriton_RumbleJoystick):
 *
 *   Uint8 buffer[HID_RUMBLE_OUTPUT_REPORT_BYTES] = { 0 };
 *   OutputReportMsg *msg = (OutputReportMsg *)(buffer);
 *
 *   msg->report_id = ID_OUT_REPORT_HAPTIC_RUMBLE;  // 0x80
 *   msg->payload.hapticRumble.type = 0;
 *   msg->payload.hapticRumble.intensity = 0;
 *   msg->payload.hapticRumble.left.speed = low_frequency_rumble;
 *   msg->payload.hapticRumble.left.gain = 0;
 *   msg->payload.hapticRumble.right.speed = high_frequency_rumble;
 *   msg->payload.hapticRumble.right.gain = 0;
 *
 *   rc = SDL_hid_write(device->dev, buffer, sizeof(buffer));
 */

/*
 * === HAPTIC PULSE (ID_OUT_REPORT_HAPTIC_PULSE = 0x81) ===
 *
 * Output Report ID: 0x81
 * Total size: HID_HAPTIC_PULSE_OUTPUT_REPORT_BYTES = 8
 *
 * Byte 0:   side (uint8) — 0x01=L, 0x02=R, 0x03=Both
 * Byte 1-2: on_us (uint16 LE) — pulse on duration in microseconds
 * Byte 3-4: off_us (uint16 LE) — pulse off duration in microseconds
 * Byte 5-6: repeat_count (uint16 LE) — number of repetitions
 * Byte 7:   (unused/padding)
 */

/*
 * === HAPTIC COMMAND (ID_OUT_REPORT_HAPTIC_COMMAND = 0x82) ===
 *
 * Output Report ID: 0x82
 * Total size: HID_HAPTIC_COMMAND_REPORT_BYTES = 4
 *
 * Byte 0: side (uint8)
 * Byte 1: command (uint8) — 0=Off, 1=tick, 2=click, 3=tone, 4=rumble, 5=noise, 6=script, 7=sweep
 * Byte 2: gain_db (int8)
 * Byte 3: (unused/padding)
 */

/*
 * === HAPTIC LFO TONE (ID_OUT_REPORT_HAPTIC_LFO_TONE = 0x83) ===
 *
 * Output Report ID: 0x83
 * Total size: HID_HAPTIC_LFO_TONE_REPORT_BYTES = 10
 *
 * Byte 0: side (uint8)
 * Byte 1: gain_db (int8)
 * Byte 2-3: frequency (uint16 LE)
 * Byte 4-5: duration_ms (uint16 LE)
 * Byte 6-7: lfo_freq (uint16 LE)
 * Byte 8:   lfo_depth (uint8) — percentage, typically 100
 * Byte 9:   (unused/padding)
 */

/*
 * === HAPTIC LOG SWEEP (ID_OUT_REPORT_HAPTIC_LOG_SWEEP = 0x84) ===
 *
 * Output Report ID: 0x84
 * Total size: HID_HAPTIC_LOG_SWEEP_REPORT_BYTES = 9
 *
 * Byte 0: side (uint8)
 * Byte 1: gain_db (int8)
 * Byte 2-3: duration_ms (uint16 LE)
 * Byte 4-5: start.frequency (uint16 LE)
 * Byte 6-7: end.frequency (uint16 LE)
 * Byte 8:   (unused/padding)
 */

/*
 * === HAPTIC SCRIPT (ID_OUT_REPORT_HAPTIC_SCRIPT = 0x85) ===
 *
 * Output Report ID: 0x85
 * Total size: HID_HAPTIC_SCRIPT_REPORT_BYTES = 4
 *
 * Byte 0: side (uint8)
 * Byte 1: script_id (uint8)
 * Byte 2: gain_db (int8)
 * Byte 3: (unused/padding)
 */

/*
 * === FEATURE REPORT HAPTIC COMMANDS (via SDL_hid_send_feature_report) ===
 *
 * These are the older feature-report-based haptic commands (Report ID 0x01):
 *
 * ID_TRIGGER_HAPTIC_PULSE (0x8F):
 *   MsgFireHapticPulse {
 *     which_pad (uint8)
 *     pulse_duration (uint16 LE)
 *     pulse_interval (uint16 LE)
 *     pulse_count (uint16 LE)
 *     dBgain (int16 LE)
 *     priority (uint8)
 *   }
 *
 * TriggerHaptic (via FeatureReportMsg payload):
 *   MsgTriggerHaptic {
 *     side (uint8) — 0x01=L, 0x02=R, 0x03=Both
 *     cmd (uint8) — haptic_type_t enum
 *     ui_intensity (uint8) — 0-4
 *     dBgain (int8)
 *     freq (uint16 LE)
 *     dur_ms (int16 LE) — negative=infinite
 *     noise_intensity (uint16 LE)
 *     lfo_freq (uint16 LE)
 *     lfo_depth (uint8)
 *     rand_tone_gain (uint8)
 *     script_id (uint8)
 *     lss_start_freq (uint16 LE)
 *     lss_end_freq (uint16 LE)
 *   }
 *
 * SimpleRumble (via FeatureReportMsg payload):
 *   MsgSimpleRumbleCmd {
 *     unRumbleType (uint8)
 *     unIntensity (uint16 LE)
 *     unLeftMotorSpeed (uint16 LE)
 *     unRightMotorSpeed (uint16 LE)
 *     nLeftGain (int8)
 *     nRightGain (int8)
 *   }
 */

/*
 * === WHAT TRIGGERS HAPTIC WRITES ===
 *
 * From SDL3 HIDAPI_DriverSteamTriton_UpdateDevice:
 *
 *   1. Game/application calls SDL_RumbleJoystick(low_freq, high_freq)
 *   2. This sets ctx->low_frequency_rumble and ctx->high_frequency_rumble
 *   3. UpdateDevice() is called periodically (every FAST_SCAN_INTERVAL = 6ms)
 *   4. If rumble values are non-zero AND ≥40ms since last rumble:
 *      - Calls HIDAPI_DriverSteamTriton_RumbleJoystick()
 *      - Sends output report 0x80 via SDL_hid_write()
 *   5. Rumble is resent every 40ms while non-zero (safety timeout)
 *   6. When game stops rumbling (sets both to 0), no more reports sent
 *
 * Timing constants:
 *   TRITON_RUMBLE_RESEND_INTERVAL_MS = 40
 *   TRITON_SENSOR_UPDATE_INTERVAL_US = 4032
 *   FAST_SCAN_INTERVAL = 6 (ms)
 *   SLOW_SCAN_INTERVAL = 9 (ms)
 *
 * Lizard mode re-disable:
 *   - SDL3: DisableSteamTritonLizardMode() called every 3000ms
 *   - Steam client: _send_lizard_off() called every 2000ms (from input_handler.py)
 */

/*
 * === BINARY REFERENCES (steamclient.so) ===
 *
 * TriggerHapticPulse LEA references:
 *   VA 0x01320765 [32-bit: NEEDS RE-ANALYSIS], 0x01320784 [32-bit: NEEDS RE-ANALYSIS], 0x01320859 [32-bit: NEEDS RE-ANALYSIS], 0x013208cb [32-bit: NEEDS RE-ANALYSIS]
 *   (all in IClientTimeline dispatch function, hash 0xf4ee1f05)
 *
 * ForceSimpleHapticEvent LEA references:
 *   VA 0x0132425b [32-bit: NEEDS RE-ANALYSIS], 0x0132427a [32-bit: NEEDS RE-ANALYSIS], 0x013242b6 [32-bit: NEEDS RE-ANALYSIS], 0x01324368 [32-bit: NEEDS RE-ANALYSIS]
 *
 * CRumbleThread LEA reference:
 *   VA 0x0111d10b [32-bit: NEEDS RE-ANALYSIS] (in jump table dispatcher using CRumbleThread string
 *   at 0x00aa5b00 as base for offset table)
 *
 * RTTI class names:
 *   "27CWriteFeatureReportWorkItem" at VA 0x00aa1880
 *   "23CExitLizardModeWorkItem" at VA 0x00aa19e0
 *   "CPulseHapticWorkItem" at VA 0x00aa28e2 (approx)
 *   "CSimpleHapticTickWorkItem" at VA 0x00aa1bf0 (approx)
 *   "CHapticToneWorkItem" at VA 0x00aa1c10 (approx)
 *   "CLegacySimpleHapticWorkItem" at VA 0x00aa1c30 (approx)
 *   "CHapticScriptWorkItem" at VA 0x00aa1c50 (approx)
 */
