# IBEX (SC2 BLE) Firmware — Complete Command Table

**Source**: `ibex_firmware.bin` (ARM Cortex-M4, nRF52840, 343 KB)  
**Dispatch function**: `FUN_000383c4` at `0x000383c4` (426 bytes)  
**Response formatter**: `FUN_0000c55c` at `0x0000c55c` (538 bytes)  
**Command size lookup**: `FUN_00013c30` at `0x00013c30` (14 bytes, covers codes 0x00–0x55)  
**Descriptor table**: `*DAT_00013d10` → `0x2000b070` (RAM, 12-byte entries × 86 commands)  
**Size table**: `*DAT_00013c40` → `0x2000d168` (RAM, short × 86 entries)  

> **Note**: The firmware binary is truncated by ~19 KB. Command handler code at addresses ≥ `0x55940` is not in the extract. Handler descriptions below are inferred from response formatter logic, string references, steamclient.so RE, and existing protocol analysis.

---

## Summary

- **95 command codes** in the main dispatch switch (`FUN_000383c4`)
- **5 additional commands** handled outside the main table (0x81, 0x84, 0x85, 0x87, 0xAE)
- **100 total commands** identified from firmware RE
- **25 commands** have response format definitions in `FUN_0000c55c`
- **86 commands** (0x00–0x55) have size entries in the command size lookup table

---

## Complete Command Table

### System / Query (0x00–0x24)

| Code | Handler Descriptor | Category | Description | Response Format | Known |
|------|-------------------|----------|-------------|:-:|:-:|
| `0x00` | `DAT_00038690` → `0x59b10` | system | **NOOP / Ping** — Returns default descriptor on unknown/null command | No (crash on code 0x00) | ✅ |
| `0x01` | `DAT_00038814` → `0x59b18` | system | **GET serial/info type 1** — Response: code `0x0c`, 8-byte payload | ✅ Response code `0x0c`, 8 bytes | |
| `0x02` | `DAT_00038694` → `0x59b22` | system | **GET device ID / version** — Response: code `0x1a`, 1-byte payload | ✅ Response code `0x1a`, 1 byte | |
| `0x03` | `DAT_00038698` → `0x59b3c` | system | **System query 3** | No | |
| `0x04` | `DAT_0003869c` → `0x59b4c` | system | **GET settings value (subset)** — Response: code `0x3e`, sub `0x04`, 20-byte payload | ✅ Response code `0x3e`, sub `0x04`, 20 bytes | |
| `0x05` | `DAT_000386a0` → `0x59b64` | system | **GET settings value (short)** — Response: code `0x3e`, sub `0x0c`, 4-byte payload | ✅ Response code `0x3e`, sub `0x0c`, 4 bytes | |
| `0x06` | `DAT_000386a4` → `0x59b6e` | system | **GET settings value (3-byte)** — Response: code `0x3e`, sub `0x0a`, 3-byte payload | ✅ Response code `0x3e`, sub `0x0a`, 3 bytes | |
| `0x07` | `DAT_000386a8` → `0x59b88` | system | **GET settings value (5-byte)** — Response: code `0x3e`, sub `0x0d`, 5-byte payload | ✅ Response code `0x3e`, sub `0x0d`, 5 bytes | |
| `0x08` | `DAT_000386ac` → `0x59b9a` | system | **GET controller mode/state** — Response: code `0x05`, 4-byte payload | ✅ Response code `0x05`, 4 bytes | |
| `0x09` | `DAT_000386b4` → `0x59bc5` | system | **GET battery level** — Response: code `0x08`, 4-byte payload. Called by `FUN_00013c30(9)` | ✅ Response code `0x08`, 4 bytes | |
| `0x0a` | `DAT_000386b8` → `0x59bd5` | system | **GET firmware version** — Response: code `0x30`, 3-byte payload | ✅ Response code `0x30`, 3 bytes | |
| `0x0b` | `DAT_000386c0` → `0x59bfe` | system | **GET multi-byte setting** — Response: code `0x13`, variable payload (`count*4+1`). Called by `FUN_00013c30(0xb)` | ✅ Response code `0x13`, variable | |
| `0x0c` | `DAT_000386c4` → `0x59c10` | system | **GET 2-byte config** — Response: code `0x57`, 2-byte payload. Called by `FUN_00013c30(0xc)` | ✅ Response code `0x57`, 2 bytes | |
| `0x0d` | `DAT_000386c8` → `0x59c21` | system | **GET controller type** — Response: code `0x0e`, 6-byte payload. Validates `param_2[3:5] == 0x2083` | ✅ Response code `0x0e`, validates magic `0x2083` | |
| `0x0e` | `DAT_000386cc` → `0x59c33` | system | **System query 0x0e** | No | |
| `0x0f` | `DAT_000386d0` → `0x59c3f` | system | **System query 0x0f** | No | |
| `0x10` | `DAT_000386d4` → `0x59c55` | system | **GET controller state** — Complex response: builds 19 or 31-byte controller state data (sticks, triggers, buttons). Checks `FUN_00000d5c(0x29)` for variant | ✅ Complex, 19 or 31 bytes | |
| `0x11` | `DAT_000386d8` → `0x59c6d` | system | **GET config type 11** — Response: code `0x3e`, sub `0x07` | ✅ Response code `0x3e`, sub `0x07` | |
| `0x12` | `DAT_000386dc` → `0x59c79` | system | **GET config type 12** — Response: code `0x3e`, sub `0x0c` | ✅ Response code `0x3e`, sub `0x0c` | |
| `0x13` | `DAT_000386e0` → `0x59c8b` | system | **GET config type 13** — Response: code `0x3e`, sub `0x12` | ✅ Response code `0x3e`, sub `0x12` | |
| `0x14` | `DAT_000386e4` → `0x59c9a` | system | **GET config type 14** — Response: code `0x3e`, sub `0x13` | ✅ Response code `0x3e`, sub `0x13` | |
| `0x15` | `DAT_000386f0` → `0x59cd6` | system | **GET config type 15** — Response: code `0x3e`, sub `0x20` | ✅ Response code `0x3e`, sub `0x20` | |
| `0x16` | `DAT_000386f4` → `0x59ce5` | system | **GET config type 16** — Response: code `0x3e`, sub `0x21` | ✅ Response code `0x3e`, sub `0x21` | |
| `0x17` | `DAT_00038700` → `0x59d38` | system | **GET extended info 17** — Response: code `0xff`, sub `0xa2`, 11-byte payload | ✅ Response code `0xff`, sub `0xa2` | |
| `0x18` | `DAT_00038704` → `0x59d56` | system | **GET extended info 18** — Response: code `0xff`, sub `0xa3`, 5-byte payload | ✅ Response code `0xff`, sub `0xa3` | |
| `0x19` | `DAT_00038708` → `0x59d76` | system | **GET firmware/hardware info** — Response: code `0xff`, sub `0x80`, 13-byte payload | ✅ Response code `0xff`, sub `0x80` | |
| `0x1a` | `DAT_0003870c` → `0x59d8d` | system | **System query 0x1a** | No | |
| `0x1b` | `DAT_00038710` → `0x59d9c` | system | **System query 0x1b** | No | |
| `0x1c` | `DAT_00038718` → `0x59dbf` | system | **System query 0x1c** | No | |
| `0x1d` | `DAT_00038720` → `0x59de5` | system | **System query 0x1d** | No | |
| `0x1e` | `DAT_00038724` → `0x59df2` | system | **System query 0x1e** | No | |
| `0x1f` | `DAT_00038728` → `0x59e08` | system | **System query 0x1f** | No | |
| `0x20` | `DAT_0003872c` → `0x59e17` | system | **System query 0x20** | No | |
| `0x21` | `DAT_00038730` → `0x59e23` | system | **System query 0x21** | No | |
| `0x22` | `DAT_00038734` → `0x59e52` | system | **System query 0x22** | No | |
| `0x23` | `DAT_00038738` → `0x59e63` | system | **System query 0x23** | No | |
| `0x24` | `DAT_0003873c` → `0x59e7e` | system | **System query 0x24** | No | |

### Config (0x25–0x5f)

| Code | Handler Descriptor | Category | Description | Response Format | Known |
|------|-------------------|----------|-------------|:-:|:-:|
| `0x2d` | `DAT_00038744` → `0x59ea7` | config | **Config 0x2d** | No | |
| `0x2e` | `DAT_0003874c` → `0x59ec7` | config | **Config 0x2e** — Used by `FUN_00013c30(0x2e)` for controller state sizing | No | |
| `0x3c` | `DAT_00038750` → `0x59ecf` | config | **Config 0x3c** | No | |
| `0x3d` | `DAT_000387b0` → `0x5a113` | config | **Config 0x3d** | No | |
| `0x3e` | `DAT_00038754` → `0x59edc` | config | **GET/SET settings values** — ID_GET_SETTINGS_VALUES / ID_SET_SETTINGS_VALUES. Used with response code `0x3e`. String refs: `%s: GET: ID_GET_SETTINGS_VALUES`, `%s: SET: ID_SET_SETTINGS_VALUES` | ✅ (response prefix `0x3e`) | ✅ |
| `0x3f` | `DAT_00038758` → `0x59ef1` | config | **Config 0x3f** | No | |
| `0x40` | `DAT_0003875c` → `0x59f05` | config | **Config 0x40** | No | |
| `0x41` | `DAT_00038760` → `0x59f23` | config | **Config 0x41** | No | |
| `0x42` | `DAT_00038764` → `0x59f2e` | config | **Config 0x42** | No | |
| `0x43` | `DAT_00038768` → `0x59f41` | config | **Config 0x43** | No | |
| `0x44` | `DAT_0003876c` → `0x59f59` | config | **Config 0x44** — Used by `FUN_00013c30(0x44)` | No | |
| `0x53` | `DAT_00038788` → `0x59fca` | config | **Config 0x53** | No | |
| `0x54` | `DAT_0003878c` → `0x59ff0` | config | **Config 0x54** | No | |
| `0x55` | `DAT_00038790` → `0x5a015` | config | **Config 0x55** | No | |
| `0x56` | `DAT_00038794` → `0x5a035` | config | **Config 0x56** | No | |
| `0x57` | `DAT_00038798` → `0x5a073` | config | **Config 0x57** | No | |
| `0x58` | `DAT_0003879c` → `0x5a099` | config | **Config 0x58** | No | |
| `0x5a` | `DAT_000387a0` → `0x5a0b2` | config | **Config 0x5a** | No | |
| `0x5b` | `DAT_000387a4` → `0x5a0c6` | config | **Config 0x5b** | No | |
| `0x5c` | `DAT_000387a8` → `0x5a0e1` | config | **Config 0x5c** | No | |
| `0x5f` | `DAT_000387f8` → `0x5a2d9` | config | **Config 0x5f** | No | |

### Input Reports (0x45–0x47)

| Code | Handler Descriptor | Category | Description | Response Format | Known |
|------|-------------------|----------|-------------|:-:|:-:|
| `0x45` | `DAT_00038770` → `0x59f69` | input | **Standard gamepad input report (12 bytes)** — Sticks, triggers, buttons. Primary HID input. | No (streaming) | ✅ |
| `0x46` | `DAT_00038774` → `0x59f77` | input | **Alternate input report** | No (streaming) | |
| `0x47` | `DAT_00038778` → `0x59f8b` | input | **Extended input report (45 bytes)** — SC2 custom with trackpads, IMU, force sensors. Called by `FUN_00013c30(0x47)`. | No (streaming) | ✅ |

### LED (0x4a, 0x4d)

| Code | Handler Descriptor | Category | Description | Response Format | Known |
|------|-------------------|----------|-------------|:-:|:-:|
| `0x4a` | `DAT_00038780` → `0x59fab` | led | **GET LED color** — String: `%s: GET: ID_GET_LED_COLOR`, `get_id_get_led_color` | No | |
| `0x4d` | `DAT_00038784` → `0x59fbe` | led | **SET LED color** — String: `%s: SET: ID_SET_LED_COLOR`, `get_id_set_led_color` | No | |

### Calibration (0x68–0x79)

| Code | Handler Descriptor | Category | Description | Response Format | Known |
|------|-------------------|----------|-------------|:-:|:-:|
| `0x68` | `DAT_000387cc` → `0x5a1d4` | calibration | **Touch calibration (right)** — String: `cal/touch_r` | No | |
| `0x69` | `DAT_000387ac` → `0x5a0f9` | calibration | **Touch calibration (left)** — String: `cal/touch_l` | No | |
| `0x6a` | `DAT_000387b4` → `0x5a11b` | calibration | **Pressure calibration (right)** — String: `cal/prs_r` | No | |
| `0x6b` | `DAT_000387b8` → `0x5a14b` | calibration | **Pressure calibration (left)** — String: `cal/prs_l` | No | |
| `0x6c` | `DAT_000387bc` → `0x5a16a` | calibration | **Calibration 0x6c** | No | |
| `0x6d` | `DAT_000387c0` → `0x5a189` | calibration | **Calibration 0x6d** | No | |
| `0x6e` | `DAT_000387c4` → `0x5a1a0` | calibration | **Calibration 0x6e** | No | |
| `0x6f` | `DAT_000387c8` → `0x5a1c1` | calibration | **Calibration 0x6f** | No | |
| `0x70` | `DAT_000387d0` → `0x5a1ed` | calibration | **Calibration 0x70** | No | |
| `0x71` | `DAT_000387d8` → `0x5a21a` | calibration | **Calibration 0x71** | No | |
| `0x72` | `DAT_00038748` → `0x59eb0` | calibration | **Calibration 0x72** | No | |
| `0x73` | `DAT_000386f8` → `0x59cf6` | calibration | **Calibration 0x73** | No | |
| `0x74` | `DAT_00038804` → `0x5a332` | calibration | **Calibration 0x74** | No | |
| `0x75` | `DAT_000386e8` → `0x59caa` | calibration | **Calibration 0x75** | No | |
| `0x76` | `DAT_00038714` → `0x59dab` | calibration | **Calibration 0x76** | No | |
| `0x77` | `DAT_000386ec` → `0x59cb7` | calibration | **Calibration 0x77** | No | |
| `0x78` | `DAT_000386b0` → `0x59bac` | calibration | **Calibration 0x78** | No | |
| `0x79` | `DAT_000386bc` → `0x59be1` | calibration | **Calibration 0x79** | No | |

### Battery / Power (0x7a–0x7f)

| Code | Handler Descriptor | Category | Description | Response Format | Known |
|------|-------------------|----------|-------------|:-:|:-:|
| `0x7a` | `DAT_00038800` → `0x5a321` | battery | **Battery 0x7a** — Fuel gauge / battery status | No | |
| `0x7b` | `DAT_0003877c` → `0x59f9a` | battery | **Battery 0x7b** — Power management | No | |
| `0x7c` | `DAT_000387e0` → `0x5a253` | battery | **Battery 0x7c** | No | |
| `0x7d` | `DAT_000387d4` → `0x5a204` | battery | **Battery 0x7d** | No | |
| `0x7e` | `DAT_000386fc` → `0x59d1a` | battery | **Battery 0x7e** | No | |
| `0x7f` | `DAT_000387e4` → `0x5a26d` | battery | **Battery 0x7f** | No | |

### Haptic (0x80)

| Code | Handler Descriptor | Category | Description | Response Format | Known |
|------|-------------------|----------|-------------|:-:|:-:|
| `0x80` | `DAT_000387dc` → `0x5a23b` | haptic | **SET haptic/rumble output** — ID_SET_DIGITAL_MAPPINGS or haptic pulse. String: `Failed to set haptics master gain` nearby. | No | ✅ |

### Config / Mapping (0x86)

| Code | Handler Descriptor | Category | Description | Response Format | Known |
|------|-------------------|----------|-------------|:-:|:-:|
| `0x86` | `DAT_0003871c` → `0x59dd7` | config | **Config 0x86** — Between haptic and firmware range | No | |

### Firmware / Bootloader (0x8a–0x8f)

| Code | Handler Descriptor | Category | Description | Response Format | Known |
|------|-------------------|----------|-------------|:-:|:-:|
| `0x8a` | `DAT_00038740` → `0x59e91` | firmware | **GET setting label** — ID_GET_SETTING_LABEL. String: `t/dis/fw` (Device Info firmware rev) nearby. | No | |
| `0x8b` | `DAT_000387fc` → `0x5a2fb` | firmware | **GET settings max values** — ID_GET_SETTINGS_MAXS | No | |
| `0x8c` | `DAT_000387e8` → `0x5a289` | firmware | **GET default settings** — ID_GET_SETTINGS_DEFAULTS | No | |
| `0x8d` | `DAT_000387ec` → `0x5a29c` | firmware | **SET controller mode** — ID_SET_CONTROLLER_MODE (lizard ↔ Steam Input) | No | |
| `0x8e` | `DAT_000387f0` → `0x5a2b2` | firmware | **Load default settings** — ID_LOAD_DEFAULT_SETTINGS. String: `%s: GET: ID_LOAD_DEFAULT_SETTINGS_VALUES` | No | |
| `0x8f` | `DAT_000387f4` → `0x5a2c6` | firmware | **0x8F sub-command dispatcher** — Main haptic/mapping command router. Handler at `0x54368`. Dispatches to sub-commands for haptic pulses, attribute queries, etc. | No | ✅ |

---

## Commands NOT in Main Dispatch Table

These 5 commands are documented from steamclient.so RE or protocol analysis but are **not** in the 95-entry dispatch switch. They may be handled at a higher level within the firmware or by a different code path.

| Code | Name | Direction | Description | Source |
|------|------|-----------|-------------|--------|
| `0x81` | ID_CLEAR_DIGITAL_MAPPINGS | Host→Device | Clear mappings (exit lizard mode). Sent periodically to prevent lizard mode re-enable. | Steam client RE, our code |
| `0x84` | ID_GET_ATTRIBUTE_LABEL | Host→Device | Get attribute label/description string | steamclient.so |
| `0x85` | ID_SET_DEFAULT_DIGITAL_MAPPINGS | Host→Device | Set default button mappings | steamclient.so |
| `0x87` | ID_SET_SETTINGS_VALUES | Host→Device | Set controller settings (alternate path) | Steam client RE, our code |
| `0xAE` | ID_GET_SERIAL | Bidirectional | Get controller serial number (handled at BLE co-processor level) | Steam client RE |

---

## Response Formatter Details (`FUN_0000c55c`)

The response formatter handles **25 command codes** for BLE-to-controller IPC response construction:

| Input Code | Response Code | Sub/Length | Notes |
|:----------:|:-------------:|:----------:|-------|
| `0x01` | `0x0c` | 8 bytes | Fixed payload |
| `0x02` | `0x1a` | 1 byte | Single byte response |
| `0x04` | `0x3e` | sub `0x04`, 20 bytes | Settings data |
| `0x05` | `0x3e` | sub `0x0c`, 4 bytes | Settings data |
| `0x06` | `0x3e` | sub `0x0a`, 3 bytes | Settings data |
| `0x07` | `0x3e` | sub `0x0d`, 5 bytes | Settings data |
| `0x08` | `0x05` | 4 bytes | Controller state |
| `0x09` | `0x08` | 4 bytes | Battery/status |
| `0x0a` | `0x30` | 3 bytes | Version info |
| `0x0b` | `0x13` | variable (`count*4+1`) | Multi-value settings |
| `0x0c` | `0x57` | 2 bytes | 16-bit config |
| `0x0d` | `0x0e` | 6 bytes | Validates magic `0x2083` |
| `0x10` | `0x3e` | 19 or 31 bytes | Complex controller state |
| `0x11` | `0x3e` | sub `0x07` | Config data |
| `0x12` | `0x3e` | sub `0x0c` | Config data |
| `0x13` | `0x3e` | sub `0x12` | Config data |
| `0x14` | `0x3e` | sub `0x13` | Config data |
| `0x15` | `0x3e` | sub `0x20` | Config data |
| `0x16` | `0x3e` | sub `0x21` | Config data |
| `0x17` | `0xff` | sub `0xa2`, 11 bytes | Extended info |
| `0x18` | `0xff` | sub `0xa3`, 5 bytes | Extended info |
| `0x19` | `0xff` | sub `0x80`, 13 bytes | Firmware/hardware info |
| `0x82` | `0xff` | error `0x0d` | GET_DIGITAL_MAPPINGS error response |
| `0x83` | `0xff` | error `0x02` | GET_ATTRIBUTES error response |

---

## Gaps in the Dispatch Table

The following command code ranges are **not handled** by the main dispatch:

| Range | Count | Notes |
|-------|:-----:|-------|
| `0x25–0x2c` | 8 | Config gap |
| `0x2f–0x3b` | 13 | Config gap |
| `0x48–0x49` | 2 | Input gap |
| `0x4b–0x4c` | 2 | LED gap |
| `0x4e–0x52` | 5 | Config gap |
| `0x59` | 1 | Config gap |
| `0x5d–0x5e` | 2 | Config gap |
| `0x60–0x67` | 8 | Calibration gap |
| `0x81–0x85` | 5 | Firmware/mapping gap (some handled outside table) |
| `0x87–0x89` | 3 | Firmware gap (0x87 handled outside table) |
| `0x90–0xff` | 112 | Upper range (some documented: 0x9F, 0xA1, 0xAE, 0xBA, 0xF2) |

---

## String References (Command Identification)

Key strings in the firmware binary that identify command handlers:

| String | Address | Likely Command | Category |
|--------|---------|----------------|----------|
| `CLEAR DIGITAL MAPPINGS` | `0x49028` | `0x81` | Mapping |
| `%s: GET: ID_GET_LED_COLOR` | `0x48e95` | `0x4a` | LED |
| `%s: SET: ID_SET_LED_COLOR` | `0x48eaf` | `0x4d` | LED |
| `%s: SET: ID_TURN_OFF` | `0x48f16` | (not in table) | Power |
| `%s: SET: ID_REBOOT_INTO_ISP` | `0x48f2b` | (not in table) | Firmware |
| `%s: SET: ID_FIRMWARE_UPDATE_REBOOT` | `0x48f47` | (not in table) | Firmware |
| `%s: SET: ID_SET_USER_STORE` | `0x48faf` | (not in table) | Config |
| `%s: GET: ID_GET_USER_STORE` | `0x48fe1` | (not in table) | Config |
| `%s: GET: ID_LOAD_DEFAULT_SETTINGS_VALUES` | `0x4903f` | `0x8e` | Config |
| `%s: GET: ID_GET_SETTINGS_VALUES` | `0x49068` | `0x3e` | Config |
| `%s: SET: ID_SET_SETTINGS_VALUES` | `0x49088` | `0x3e` | Config |
| `%s: GET: ID_GET_ATTRIBUTES_VALUES` | `0x50f62` | `0x8f` sub | Firmware |
| `%s: GET: ID_GET_STRING_ATTRIBUTE, TAG: %u` | `0x50fa4` | `0x8f` sub | Firmware |
| `settings/haptics/haptic_master_gain_db` | `0x4861e` | Haptic config | Haptic |
| `settings/haptics/enabled` | `0x48667` | Haptic config | Haptic |
| `settings/sensors/imu/mode` | `0x490c1` | IMU config | Config |
| `cal/touch_r` | `0x489a7` | `0x68` | Calibration |
| `cal/touch_l` | `0x489b3` | `0x69` | Calibration |
| `cal/prs_r` | `0x489bf` | `0x6a` | Calibration |
| `cal/prs_l` | `0x489c9` | `0x6b` | Calibration |
| `esb/bond` | `0x49177` | ESB bonding | System |
| `controller_settings` | `0x48810` | Settings namespace | Config |

---

## Key Architecture Notes

1. **DAT_ values are NOT handler function pointers** — They point to descriptor structures in flash/RAM beyond the binary extract (addresses `0x59b10`–`0x5a332`). These descriptors likely contain: handler function pointer, min/max packet size, flags, and name string pointer.

2. **The dispatch function is a pure lookup table** — It takes a command code, returns the corresponding DAT_ descriptor pointer. The caller then uses the descriptor to invoke the actual handler.

3. **Response formatter is BLE-side** — `FUN_0000c55c` formats responses for commands that travel between the BLE stack and the main controller logic within the same nRF52840 chip. Not all commands go through this path.

4. **Command size table is runtime** — `FUN_00013c30` reads from RAM (`0x2000d168`), so the size data is initialized at boot from flash configuration. Covers codes `0x00`–`0x55` only.

5. **0x8F is the master dispatcher** — It's a sub-command router that handles haptic pulses, attribute queries, and mapping operations. The case `0x8f` handler at `0x54368` (in the truncated region) processes the sub-command byte that follows.

6. **Upper range (0x90+)** — Several commands above `0x8f` are documented from steamclient.so: `0x9F` (turn off), `0xA1` (get device info), `0xAE` (get serial), `0xBA` (get chip ID), `0xF2` (capability query). These are likely handled at a different code path within the same firmware, not in the main Ibex dispatch.

### Resolved TBH Jump Table (2026-07-01)

The dispatch uses a Thumb `tbh [pc, r3, lsl 1]` instruction at `0x000383ce`. The 144-entry halfword table starts at `0x000383d2`. Each entry is a 2-byte offset from the table base (`target = 0x383d2 + entry * 2`).

| Code Range | Entries | Default Handler | Notes |
|------------|---------|-----------------|-------|
| 0x00–0x24 | Unique per command | — | System commands, all unique handlers |
| 0x25–0x2c | 0x014c → `0x03866a` | Default | Unhandled |
| 0x2d–0x2e | Unique | — | Config |
| 0x2f–0x3b | 0x014c → `0x03866a` | Default | Unhandled |
| 0x3c–0x47 | Unique | — | Config + input |
| 0x48–0x49 | 0x014c → `0x03866a` | Default | Unhandled |
| 0x4a | Unique | — | LED GET |
| 0x4b–0x4c | 0x014c → `0x03866a` | Default | Unhandled |
| 0x4d | Unique | — | LED SET |
| 0x4e–0x52 | 0x014c → `0x03866a` | Default | Unhandled |
| 0x53–0x58 | Unique | — | Config |
| 0x59 | 0x014c → `0x03866a` | Default | Unhandled |
| 0x5a–0x5c | Unique | — | Config |
| 0x5d–0x5e | 0x014c → `0x03866a` | Default | Unhandled |
| 0x5f | Unique (0x0144 → `0x03865a`) | — | Config |
| 0x60–0x67 | 0x014c → `0x03866a` | Default | Unhandled |
| 0x68–0x71 | Unique | — | Calibration |
| 0x72 | Unique (0x00ec → `0x0385aa`) | — | Calibration |
| 0x73–0x7e | Unique | — | Calibration + battery |
| 0x7f | Unique (0x013a → `0x038646`) | — | Battery |
| 0x80 | Unique (0x0136 → `0x03863e`) | — | **Haptic motor output** |
| 0x81–0x85 | 0x014c → `0x03866a` | Default | Handled outside dispatch |
| 0x86 | Unique (0x00d6 → `0x03857e`) | — | Config |
| 0x87–0x89 | 0x014c → `0x03866a` | Default | 0x87 handled outside dispatch |
| 0x8a | Unique (0x00e8 → `0x0385a2`) | — | Firmware |
| 0x8b–0x8e | Unique | — | Firmware |
| 0x8f | Unique (0x0142 → `0x038656`) | — | **Sub-command dispatcher** |

### Dispatch Callers (2026-07-01)

The dispatch at `0x000383c4` is called by **1 tail-call wrapper** at `0x445f2` (sets r1=0, r2=0, branches to dispatch). Two higher-level callers invoke the wrapper:

| Caller | Address | Call Sites | Purpose |
|--------|---------|------------|---------|
| `fcn.000180a8` | `0x180c8` | 1 | Controller command processing |
| `fcn.00018320` | `0x183ac`, `0x1841a` | 2 | Controller command processing |

Both callers follow the same pattern:
1. Look up command type from a lookup function (returns negative value)
2. Negate to get positive command code
3. Call dispatch via wrapper → get descriptor pointer in r0
4. Build 0x20-byte message structure: `[flags=0x1000003, msg_id, descriptor_ptr, buf_size=0x200]`
5. Submit to firmware event system via `fcn.0001b07c`

### 0xf2 ACK Format (2026-07-01)

The 0xf2 response is **NOT a capability data response** — it is a minimal 6-byte ACK sent after 0xe7 (mapping) commands:

```
[0x01, 0x00, 0x00, 0x00, 0x00, 0xf2]
 count   (zeroed)              type
```

Built by `FUN_00042132` at `0x00042132`. Part of a response family:
| Function | Type Byte | Payload | Purpose |
|----------|-----------|---------|---------|
| `FUN_000420ae` | 0xf0 | MAC + UUID (20B) | Identity response |
| `FUN_00042132` | 0xf2 | None | **Mapping ACK** |
| `FUN_0004214a` | 0xf3 | Mode byte (1B) | Mode notification |
| `FUN_00042108` | 0xf4 | Timestamp + model (20B) | Status response |

The "capability query" interpretation from steamclient.so likely goes through a different protocol path (HID Feature Reports over ESB/USB, not BLE L2CAP commands).
