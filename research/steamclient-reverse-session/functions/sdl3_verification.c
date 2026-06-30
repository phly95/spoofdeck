/*
 * SDL3 Source Comparison — SET_SETTINGS Verification Analysis
 *
 * Source: https://github.com/libsdl-org/SDL
 * File: src/joystick/hidapi/SDL_hidapi_steam_triton.c
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
 * SDL3's Triton driver performs **NO verification** after SET_SETTINGS.
 * It sends the feature report and only checks that the HID write succeeded.
 * There is NO get_feature_report call, NO echo comparison, NO readback.
 *
 * This means SET_SETTINGS is SUPPOSED to be fire-and-forget.
 * The Steam client binary is NOT SUPPOSED to verify SET_SETTINGS either.
 */

/*
 * === DisableSteamTritonLizardMode (SDL3) ===
 *
 * static bool DisableSteamTritonLizardMode(SDL_hid_device *dev)
 * {
 *     int rc;
 *     Uint8 buffer[HID_FEATURE_REPORT_BYTES] = { 1 };  // Report ID = 1
 *     FeatureReportMsg *msg = (FeatureReportMsg *)(buffer + 1);
 *
 *     msg->header.type = ID_SET_SETTINGS_VALUES;           // 0x87
 *     msg->header.length = 1 * sizeof(ControllerSetting);  // 3
 *     msg->payload.setSettingsValues.settings[0].settingNum = SETTING_LIZARD_MODE;  // 9
 *     msg->payload.setSettingsValues.settings[0].settingValue = LIZARD_MODE_OFF;    // 0
 *
 *     rc = SDL_hid_send_feature_report(dev, buffer, sizeof(buffer));
 *     if (rc != sizeof(buffer)) {
 *         return false;  // <-- ONLY checks if HID write succeeded
 *     }
 *     return true;       // <-- NO readback, NO verification
 * }
 *
 * KEY: After sending, it only checks rc == sizeof(buffer).
 * There is NO call to SDL_hid_get_feature_report.
 * There is NO memcmp or echo comparison.
 */

/*
 * === HIDAPI_DriverSteamTriton_SetSensorsEnabled (SDL3) ===
 *
 * Also uses SET_SETTINGS (0x87) for IMU mode:
 *
 *     msg->header.type = ID_SET_SETTINGS_VALUES;           // 0x87
 *     msg->header.length = 1 * sizeof(ControllerSetting);  // 3
 *     msg->payload.setSettingsValues.settings[0].settingNum = SETTING_IMU_MODE;  // 48
 *     msg->payload.setSettingsValues.settings[0].settingValue = ...;
 *
 *     rc = SDL_hid_send_feature_report(device->dev, buffer, sizeof(buffer));
 *     if (rc != sizeof(buffer)) {
 *         return false;
 *     }
 *     ctx->report_sensors = enabled;
 *     return true;
 *
 * Same pattern: send, check return value, no readback.
 */

/*
 * === ALL send_feature_report CALLS IN SDL3 TRITON DRIVER ===
 *
 * Line  Function                          Purpose
 * 138   DisableSteamTritonLizardMode      SET_SETTINGS (0x87) — lizard mode off
 * 644   SendJoystickEffect                Passthrough raw feature report (no 0x87)
 * 669   SetSensorsEnabled                 SET_SETTINGS (0x87) — IMU mode
 *
 * Total: 3 calls. None are followed by get_feature_report.
 */

/*
 * === get_feature_report CALLS IN SDL3 TRITON DRIVER ===
 *
 * NONE. Zero calls to SDL_hid_get_feature_report in the entire file.
 *
 * This confirms: SDL never reads settings back from the controller.
 */

/*
 * === COMPARISON WITH GET_ATTRIBUTES ===
 *
 * GET_ATTRIBUTES (0x83) is NOT used by the SDL3 Triton driver at all.
 * The driver only uses:
 *   - ID_SET_SETTINGS_VALUES (0x87) — for configuration
 *   - ID_TRIGGER_HAPTIC_PULSE (0x8F) — for haptics (via SendJoystickEffect)
 *   - Raw feature reports — for passthrough
 *
 * GET_ATTRIBUTES is used elsewhere in the Steam client binary (for
 * initial controller enumeration), but NOT by the SDL Triton driver.
 */

/*
 * === KEY CONSTANTS FROM controller_constants.h ===
 *
 * ID_SET_SETTINGS_VALUES   = 0x87   (SET_SETTINGS command)
 * ID_GET_SETTINGS_VALUES   = 0x89   (GET_SETTINGS — available but unused)
 * ID_GET_ATTRIBUTES_VALUES = 0x83   (GET_ATTRIBUTES — available but unused)
 *
 * SETTING_LIZARD_MODE = 9
 * LIZARD_MODE_OFF     = 0
 * SETTING_IMU_MODE    = 48
 */

/*
 * === BUFFER LAYOUT FROM controller_structs.h ===
 *
 * #define HID_FEATURE_REPORT_BYTES 64
 *
 * typedef struct {
 *     unsigned char type;      // command ID (e.g. 0x87)
 *     unsigned char length;    // payload length in bytes
 * } FeatureReportHeader;
 *
 * typedef struct {
 *     unsigned char settingNum;    // e.g. 9 = SETTING_LIZARD_MODE
 *     unsigned short settingValue; // e.g. 0 = LIZARD_MODE_OFF
 * } ControllerSetting;
 *
 * typedef struct {
 *     FeatureReportHeader header;
 *     union { ... } payload;
 * } FeatureReportMsg;
 *
 * Buffer construction:
 *   Uint8 buffer[64] = { 1 };  // byte 0 = report ID (always 1)
 *   FeatureReportMsg *msg = (FeatureReportMsg *)(buffer + 1);
 *   msg->header.type = 0x87;
 *   msg->header.length = 3;
 *   msg->payload.setSettingsValues.settings[0].settingNum = N;
 *   msg->payload.setSettingsValues.settings[0].settingValue = V;
 *
 * Final buffer:
 *   [01] [87] [03] [09] [00 00] [00...]  (64 bytes)
 *    ID   CMD  LEN  REG  VALUE   PADDING
 */

/*
 * === IMPLICATION FOR STEAM CLIENT BINARY ===
 *
 * Since SDL3 does NOT verify SET_SETTINGS, the Steam client binary
 * is NOT SUPPOSED to verify it either. The verification read that
 * the user is seeing is NOT part of the SET_SETTINGS protocol.
 *
 * The "retry every 3s" behavior is likely:
 * 1. The state machine re-processes unsent settings periodically
 * 2. If the send fails (vtable[0x10] returns error), the entry
 *    remains in the settings array and is retried
 * 3. The 3-second interval is the state machine's polling period
 *
 * The verification (vtable[0x130] = get_feature_report) is only
 * called when a verify object (r13) is non-null. For SET_SETTINGS,
 * this object is NULL, so the verify step is skipped.
 */
