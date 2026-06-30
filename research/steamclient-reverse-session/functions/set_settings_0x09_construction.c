/*
 * SET_SETTINGS 0x09 Command Construction — COMPLETE PROTOCOL REFERENCE
 *
 * Source of truth: SDL3 src/joystick/hidapi/steam/controller_structs.h
 *                  SDL3 src/joystick/hidapi/steam/controller_constants.h
 *                  SDL3 src/joystick/hidapi/SDL_hidapi_steam_triton.c
 *
 * Binary: ~/.steam/debian-installation/ubuntu12_32/steamclient.so (32-bit, 49MB)
 * Status: DETERMINED (from SDL3 source — not directly traced in binary)
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
 * === FEATURE REPORT FORMAT (Report ID 0x00) ===
 *
 * The SC2 uses 64-byte vendor HID reports via Feature Report 0x00.
 * The buffer layout (from controller_structs.h):
 *
 * Byte 0:   Report ID (always 0x01 for host->device commands)
 * Byte 1:   FeatureReportHeader.type   (command byte)
 * Byte 2:   FeatureReportHeader.length (payload length in bytes)
 * Byte 3+:  Payload (varies by command)
 *
 * NOTE: The SDL3 buffer is initialized as: { 1 } (Report ID = 1)
 * Then FeatureReportMsg* is cast from buffer+1, so header starts at byte 1.
 *
 * Total buffer size: HID_FEATURE_REPORT_BYTES = 64
 */

/*
 * === COMMAND BYTE VALUES (FeatureReportMessageIDs enum) ===
 *
 * 0x80 = ID_SET_DIGITAL_MAPPINGS
 * 0x81 = ID_CLEAR_DIGITAL_MAPPINGS
 * 0x82 = ID_GET_DIGITAL_MAPPINGS
 * 0x83 = ID_GET_ATTRIBUTES_VALUES
 * 0x84 = ID_GET_ATTRIBUTE_LABEL
 * 0x85 = ID_SET_DEFAULT_DIGITAL_MAPPINGS
 * 0x86 = ID_FACTORY_RESET
 * 0x87 = ID_SET_SETTINGS_VALUES         <--- THIS IS THE ONE
 * 0x88 = ID_CLEAR_SETTINGS_VALUES
 * 0x89 = ID_GET_SETTINGS_VALUES
 * 0x8A = ID_GET_SETTING_LABEL
 * 0x8B = ID_GET_SETTINGS_MAXS
 * 0x8C = ID_GET_SETTINGS_DEFAULTS
 * 0x8D = ID_SET_CONTROLLER_MODE
 * 0x8E = ID_LOAD_DEFAULT_SETTINGS
 * 0x8F = ID_TRIGGER_HAPTIC_PULSE
 * 0x9F = ID_TURN_OFF_CONTROLLER
 * 0xA1 = ID_GET_DEVICE_INFO
 */

/*
 * === SET_SETTINGS BUFFER LAYOUT ===
 *
 * For a single setting:
 *   Byte 0:  0x01              (Report ID)
 *   Byte 1:  0x87              (ID_SET_SETTINGS_VALUES)
 *   Byte 2:  0x03              (length = 1 × sizeof(ControllerSetting) = 3)
 *   Byte 3:  settingNum        (ControllerSettings enum, 1 byte)
 *   Byte 4:  settingValue low  (uint16 LE)
 *   Byte 5:  settingValue high (uint16 LE)
 *   Bytes 6-63: 0x00           (padding)
 *
 * For N settings:
 *   Byte 2:  N × 3
 *   Bytes 3 to (3 + N×3 - 1): N × ControllerSetting structs
 */

/*
 * === ControllerSettings ENUM VALUES ===
 *
 * 0  = SETTING_MOUSE_SENSITIVITY
 * 1  = SETTING_MOUSE_ACCELERATION
 * 2  = SETTING_TRACKBALL_ROTATION_ANGLE
 * 3  = SETTING_HAPTIC_INTENSITY_UNUSED
 * 4  = SETTING_LEFT_GAMEPAD_STICK_ENABLED
 * 5  = SETTING_RIGHT_GAMEPAD_STICK_ENABLED
 * 6  = SETTING_USB_DEBUG_MODE
 * 7  = SETTING_LEFT_TRACKPAD_MODE
 * 8  = SETTING_RIGHT_TRACKPAD_MODE
 * 9  = SETTING_LIZARD_MODE               <--- THIS IS THE ONE
 * 10 = SETTING_DPAD_DEADZONE
 * 15 = SETTING_HAPTIC_INCREMENT
 * 21 = SETTING_SENSITIVITY_SCALE_AMOUNT
 * 24 = SETTING_SMOOTH_ABSOLUTE_MOUSE
 * 48 = SETTING_IMU_MODE
 * 70 = SETTING_HAPTICS_ENABLED
 * 79 = SETTING_HAPTIC_INTENSITY
 */

/*
 * === LIZARD MODE VALUES (LizardModeState_t enum) ===
 *
 * 0 = LIZARD_MODE_OFF
 * 1 = LIZARD_MODE_ON
 */

/*
 * === SET_SETTINGS 0x09 (Disable Lizard Mode) ===
 *
 * Exact byte sequence (64 bytes):
 *
 *   01 87 03 09 00 00 00 00 00 00 00 00 00 00 00 00
 *   00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
 *   00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
 *   00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
 *
 * Decoded:
 *   [0]    0x01 = Report ID
 *   [1]    0x87 = ID_SET_SETTINGS_VALUES
 *   [2]    0x03 = length (3 bytes = 1 setting)
 *   [3]    0x09 = SETTING_LIZARD_MODE
 *   [4]    0x00 = value low byte (LIZARD_MODE_OFF = 0)
 *   [5]    0x00 = value high byte
 *   [6-63] 0x00 = padding
 */

/*
 * === SDL3 C CODE (DisableSteamTritonLizardMode) ===
 *
 *   Uint8 buffer[HID_FEATURE_REPORT_BYTES] = { 1 };
 *   FeatureReportMsg *msg = (FeatureReportMsg *)(buffer + 1);
 *
 *   msg->header.type = ID_SET_SETTINGS_VALUES;           // 0x87
 *   msg->header.length = 1 * sizeof(ControllerSetting);  // 3
 *   msg->payload.setSettingsValues.settings[0].settingNum = SETTING_LIZARD_MODE;  // 9
 *   msg->payload.setSettingsValues.settings[0].settingValue = LIZARD_MODE_OFF;    // 0
 *
 *   rc = SDL_hid_send_feature_report(dev, buffer, sizeof(buffer));
 */

/*
 * === KNOWN SET_SETTINGS COMMANDS (from input_handler.py NEPTUNE_LIZARD_OFF_CMDS) ===
 *
 * These are the 5 commands sent in sequence to disable lizard mode:
 *
 * 1. ClearDigitalMappings:
 *    01 81 00 00 00 00 00 ... (64 bytes, command 0x81, length 0)
 *
 * 2. RPadMode -> TrackpadMode.None:
 *    01 87 03 08 07 00 00 ... (64 bytes)
 *    settingNum = 8 (SETTING_RIGHT_TRACKPAD_MODE)
 *    settingValue = 7 (TRACKPAD_NONE)
 *
 * 3. LPadMode -> TrackpadMode.None:
 *    01 87 03 07 07 00 00 ... (64 bytes)
 *    settingNum = 7 (SETTING_LEFT_TRACKPAD_MODE)
 *    settingValue = 7 (TRACKPAD_NONE)
 *
 * 4. SmoothAbsoluteMouse -> 0:
 *    01 87 03 18 00 00 00 ... (64 bytes)
 *    settingNum = 24 (SETTING_SMOOTH_ABSOLUTE_MOUSE)
 *    settingValue = 0
 *
 * 5. SensitivityScaleAmount -> 0:
 *    01 87 03 15 00 00 00 ... (64 bytes)
 *    settingNum = 21 (SETTING_SENSITIVITY_SCALE_AMOUNT)
 *    settingValue = 0
 */

/*
 * === HOW THE STEAM CLIENT SENDS IT ===
 *
 * The Steam client (steamclient.so) does NOT call SDL_hid_send_feature_report
 * directly. Instead, it uses a protobuf-based IPC mechanism:
 *
 * 1. A CWriteFeatureReportWorkItem is created with the 64-byte buffer
 * 2. The buffer is wrapped in a CHIDMessageToRemote protobuf:
 *    - oneof field #6: device_send_feature_report
 *    - sub-message: { device: uint32, data: bytes }
 * 3. The protobuf message is sent over IPC to the Steam remote process
 * 4. The remote process calls SDL_hid_send_feature_report on the physical device
 *
 * CExitLizardModeWorkItem (RTTI string at 0x00aa19e0) is the work item
 * class used specifically to exit lizard mode.
 *
 * The toggle_lizard string (VA 0x00ca6b56) is in a string table at
 * 0x02ae1ac8 [32-bit: NEEDS RE-ANALYSIS] (index 0x1c) — accessed via table lookup, not direct LEA.
 *
 * SDL_hid_send_feature_report is loaded dynamically via CDynamicFunc wrapper
 * (string at 0x00cbb561).
 */

/*
 * === VERIFICATION (from findings.md) ===
 *
 * After sending SET_SETTINGS, Steam reads Feature Report 0x00 back
 * to verify the setting took effect. The response should echo back
 * the current settings state.
 *
 * Retry behavior:
 * - Retry interval: ~3 seconds
 * - No retry count limit
 * - Failure: controller disconnects or times out
 */
