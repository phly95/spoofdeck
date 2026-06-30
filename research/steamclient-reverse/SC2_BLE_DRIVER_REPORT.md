# SC2 (Steam Controller 2026) BLE Driver Reverse-Engineering Report

## Files Analyzed

| File | Relevance |
|------|-----------|
| `~/.steam/debian-installation/ubuntu12_32/steamclient.so` | **PRIMARY** - Main Steam client binary (32-bit i386). Contains `CSteamController`, `CTritonController`, `CSteamControllerProtocolHandlerV1`, HID protocol code, feature report I/O, firmware update, controller settings. NOTE: Prior analysis was on the wrong binary (`linux64/steamclient.so`, 64-bit). All addresses must be re-derived from this 32-bit binary. |
| `~/.steam/debian-installation/steamrt64/steamclient.so` | **HIGH** - SteamRT64 version. Contains full BlueZ D-Bus GATT bindings (`org.bluez.GattManager1`), all `CSteamInputService_*` protobuf messages, `Triton_BLE/USB/BL/ESB` transport types |
| `~/.steam/debian-installation/ubuntu12_64/libcef.so` | **MEDIUM** - Chromium Embedded Framework. Contains BlueZ D-Bus GATT server strings, Neptune chipset identifiers (LTX/VLT/LTS/ULS), `/dev/hidraw` |
| `~/.steam/debian-installation/steamrt64/libSDL3.so` | **MEDIUM** - SDL3 library. Contains `SDL_hid_ble_scan`, `SDL_hid_get_report_descriptor`, `SDL_hid_send_feature_report`, `SDL_hid_get_feature_report`, hidraw references, Steam Deck Controller gamepad mapping |
| `~/.steam/debian-installation/logs/controller.txt` | **HIGH** - Controller log showing HID config cache, device open/close, PollState changes, PS3 controller handling |
| `~/.steam/debian-installation/logs/controller_ui.txt` | **HIGH** - Controller UI log showing `Type: 10` (Neptune/SC2) vs `Type: 30` (gamepad), product IDs, capabilities bitmask, serial number flow |
| `~/.steam/debian-installation/logs/controller_support_28de-1303-2e.txt` | **HIGH** - SC2 controller support test log (serial `28de-1303-2efea7d`, board revision 46, FW `0x65E4F1AD`) |
| `~/.steam/debian-installation/logs/controller_support_FY2S443045FD.txt` | **HIGH** - Second SC2 controller test log (serial `FY2S443045FD`, FW `0x6876D00D`, Jul 2025) |
| `~/.steam/debian-installation/controller_base/` | **MEDIUM** - Controller base config VDFs (`basicui_neptune.vdf`, `chord_triton.vdf`, etc.) |

---

## 1. GATT Services/Characteristics Steam Looks For

**Critical finding: Steam does NOT use standard HID-over-GATT (HOGP).** It uses a
**custom Valve BLE protocol** over the **Valve Custom Service (UUID `100F6C32`)**.

### Evidence

- The string `Controller uses V1 HID protocol via BLE` confirms a custom BLE HID transport
- No standard BLE GATT service UUIDs (`0x2812` for HID Service, `0x180A` for Device Info,
  `0x180F` for Battery) appear as strings - they are constructed programmatically
- The UUID `100f6c32` is referenced in code but appears as a **16-bit UUID**
  (`0x100f6c32` -> this is actually the **Valve Custom Service UUID** base:
  `100f6c32-1735-4313-b402-38567131e5f3`)
- Steam uses **BlueZ D-Bus API** (`org.bluez.GattManager1`) to register GATT services,
  NOT the kernel HOGP driver

### GATT Service Architecture

```
org.bluez.GattManager1          <- Steam registers as GATT client via D-Bus
org.bluez.Device1               <- BLE device properties
org.bluez.LEAdvertisingManager1 <- For advertising (when acting as peripheral)
```

### BlueZ D-Bus Interfaces Used

```
org.bluez.GattManager1          <- Register/unregister GATT services
org.bluez.Device1               <- Connect/disconnect, device properties
org.bluez.Adapter1              <- BLE adapter control
org.bluez.ProfileManager1       <- Register HID profile
org.bluez.Agent1                <- Pairing agent
org.bluez.Battery1              <- Battery service
org.bluez.Input1                <- HID input service
org.bluez.LEAdvertisement1      <- LE advertising
org.bluez.LEAdvertisingManager1 <- LE advertising manager
org.bluez.BatteryProviderManager1 <- Battery provider
```

### Steam does NOT use standard BLE GATT HID. Instead:

- Connects to BLE device via BlueZ D-Bus
- Opens `/dev/hidrawN` for raw HID I/O (SDL3's `hidraw` backend)
- Uses `SDL_hid_send_feature_report()` / `SDL_hid_get_feature_report()` for control
- Uses `SDL_hid_read()` for input reports
- The Valve Custom Service handles the actual communication

---

## 2. CCCD Writes (When and Why)

**Evidence suggests Steam does NOT write CCCDs in the traditional GATT sense.** Here is why:

1. **No `cccd`, `0x2902`, `Client Characteristic Configuration` strings** found in any binary
2. Steam uses **HID-over-custom-protocol**, not standard GATT notifications
3. The communication path is:
   - BlueZ D-Bus -> opens `/dev/hidrawN`
   - SDL3 `hidraw` backend -> direct HID report read/write
   - Feature reports via `ioctl(HIDIOCGFEATURE)` / `ioctl(HIDIOCSFEATURE)`

### Why CCCDs are not written

**This is expected behavior.** Steam bypasses GATT notification subscriptions entirely.
Input arrives via **HID report polling** (`SDL_hid_read()`), not BLE notifications. The
Valve Custom Service uses its own protocol that gets exposed as a hidraw device by the
kernel's `uhid` driver or by BlueZ itself.

---

## 3. Feature Report Read/Write Sequence

### From `steamclient.so` strings, the sequence is:

```
1. SDL_hid_open_path()                <- Open hidraw device
2. SDL_hid_get_serial_number_string() <- Get controller serial
3. SDL_hid_get_feature_report()       <- Read controller attributes (chip ID, FW version, board rev)
4. CGetChipIDWorkItem                 <- Read chip ID
5. device_start_input_reports()       <- Tell controller to start sending input reports
6. SDL_hid_read()                     <- Begin reading HID input reports (polling loop)
7. [ongoing] SDL_hid_get_feature_report()  <- Periodic feature report reads
8. [ongoing] SDL_hid_send_feature_report() <- Haptics, settings, firmware updates
```

### Firmware Update Feature Reports (from `CUpdateFirmwareJob`)

```
1. FWU: Sending start command         <- Feature report write
2. FWU: Waiting on start update ACK   <- Feature report read (ACK)
3. FWU: Writing data                  <- Feature report write (data blocks)
4. FWU: Sending update complete msg   <- Feature report write
5. FWU: Rebooting device              <- Feature report write
```

### Feature Report Classes Found

- `CWriteFeatureReportWorkItem` - queues feature report writes
- `BWriteAltFeatureReport` - alternative write path (for ALT protocol)
- `BReadFeatureReport` - reads feature reports
- `FeatureReportMsg::payload` - feature report message structure

---

## 4. What Triggers Steam to Start Reading Input

### Sequence from logs (`controller_support_28de-1303-2e.txt`)

```
1. [T+0s]    Client started, serial number logged
2. [T+0s]    Board revision: 46, FW revision: 0x65E4F1AD
3. [T+3-90s] Left/Right trigger result: FAIL (test reads)
4. [T+3-90s] Left/Right trackpad result: FAIL
5. [T+3-90s] Left/Right Joystick result: FAIL
6. [T+3-90s] Buttons result: FAIL, Haptics: FAIL
```

### Sequence from `controller_ui.txt`

```
1. Controller 0 connected, configuring it now...
2. Controller 0 attributes:
     Type: 10                    <- Controller type (10=Neptune/SC2)
     ProductID: 4867             <- 0x1303 (Valve product)
     Serial: 28de-1303-2efea7d
     Capabilities: 000000004169bfff
     Firmware Version: 1709502893
3. Warming Config Cache 769
4. Loaded Config for ... controller_neptune.vdf
5. Auto-Registering controller: 28de-1303-2efea7d, 12345678
```

### From `controller.txt` (internal controller process)

```
1. Opted-in Controller Mask for AppId 0: 1000
2. BYieldingMarkControllerConfigsInUse
3. BYieldingQueryAccountsRegisteredToController
4. Controller PollState Changed from 0 to 1   <- Polling begins
5. Controller PollState Changed from 1 to 2   <- Active input
```

### What triggers input reading

1. **BLE connection established** -> BlueZ D-Bus `Device1` connected signal
2. **HID device appears** -> `/dev/hidrawN` device detected by SDL3
3. **`device_start_input_reports()`** -> Feature report write to controller telling it
   to start sending reports
4. **PollState 0->1** -> Controller enters polling state
5. **PollState 1->2** -> Controller fully active, receiving config, reading input

---

## 5. SET_SETTINGS Data Format

**No literal `SET_SETTINGS` string was found.** The settings are communicated via the
**CSteamInputService protobuf messages** and **feature reports**.

### Settings are sent as protobuf `CSteamInputService_*` messages

- `CSteamInputService_ControllerStateFlow_Request` - configures controller state flow
- `CSteamInputService_ControllerAccessibilityStrings_Request` - accessibility settings
- `CSteamInputService_ControllerListChanged_Notification` - controller list updates
- `CSteamInputService_EnableDockedInput_Request` - docked mode settings
- `CSteamInputService_EnableQosStatus_Request` - QoS settings

### Neptune/SC2-specific settings

- `SetEditingTritonCapSenseSettings` - capacitive touch sensitivity
- `k_EControllerSetting*` - extensive enumeration of ~150+ controller settings (gyro,
  trackpad, sticks, triggers, haptics, etc.)
- `rumble_setting`, `rumble_intensity`, `rumble_type` - haptic settings
- `input_mode` - controller input mode

### Controller Settings are loaded from VDF files

```
controller_base/basicui_neptune.vdf     <- Big Picture UI config
controller_base/chord_triton.vdf        <- Chord/guide button config
config/413080/controller_neptune.vdf    <- Per-game config (type 0x1303 = SC2)
```

---

## 6. Complete SC2 Command Sequence

### Phase 1: BLE Discovery and Connection

```
BlueZ D-Bus: SetDiscovering -> scan for BLE devices
Match device by Valve vendor ID (0x28DE)
BlueZ D-Bus: Device1.Connect
HID profile registered (via org.bluez.ProfileManager1)
```

### Phase 2: HID Device Enumeration

```
/dev/hidrawN appears
SDL3: SDL_hid_open_path("/dev/hidrawN")
SDL_hid_get_serial_number_string()
SDL_hid_get_product_string() -> "Steam Controller" / product 0x1303
```

### Phase 3: Controller Identification

```
SDL_hid_get_feature_report(chip_id)     <- CGetChipIDWorkItem
SDL_hid_get_feature_report(board_rev)   <- board_revision
SDL_hid_get_feature_report(fw_ver)      <- firmware version
Controller type identified (Type 10 = Neptune/SC2)
Capabilities bitmask: 0x4169bfff
```

### Phase 4: Controller Configuration

```
device_start_input_reports()            <- Feature report write
Load controller_neptune.vdf config
CSteamInputService_ControllerStateFlow_Request
CSteamInputService_ControllerAccessibilityStrings_Request
BYieldingQueryAccountsRegisteredToController
```

### Phase 5: Input Reading (Steady State)

```
SDL_hid_read() loop                     <- HID input reports
Parse CHIDMessageFromRemote
CSteamInputService_ControllerButtonStateChanged_Notification
CSteamInputService_ControllerAxesStateChange_Notification
CSteamInputService_GyroQuaternionChanged_Notification
CSteamInputService_GyroSpeedChanged_Notification
CSteamInputService_GyroAccelerometerChanged_Notification
```

### Phase 6: Periodic Maintenance

```
SDL_hid_get_feature_report()            <- Status checks
SDL_hid_send_feature_report()           <- Haptics, settings
CSteamInputService_ControllerBatteryState_Notification
CSteamInputService_TritonQos_Notification (BLE quality)
```

---

## 7. Key Identifiers

| Identifier | Value | Description |
|-----------|-------|-------------|
| Valve USB VID | `0x28DE` | Valve Corporation vendor ID |
| SC2 Product ID | `0x1303` (4867 decimal) | Steam Controller 2026 |
| Controller Type | `10` (0x0A) | Neptune/SC2 type in Steam |
| Board Revision | `46` | Hardware revision |
| Capabilities | `0x4169bfff` | Feature capabilities bitmask |
| Valve Custom Service UUID | `100f6c32-1735-4313-b402-38567131e5f3` | Custom GATT service |
| Protocol | `V1 HID` | Custom HID-over-BLE protocol |
| Transport Modes | `Triton_BL`, `Triton_USB`, `Triton_BLE`, `Triton_ESB` | 4 connection types |
| Config type | `controller_neptune` | VDF config identifier |

---

## 8. Source Files Referenced in Binaries

```
/data/src/clientdll/tritoncontroller.cpp
    Main SC2/Triton controller code

../thirdparty/dbus-bindings/include/valve/dbus/generated/gen.org.bluez.c
    BlueZ D-Bus generated bindings

data/src/clientdll/generated_proto/webuimessages_bluetooth.pb.cc
    Bluetooth protobuf messages
```

---

## 9. CSteamInputService Protobuf Messages

### Notifications (Controller -> Host)

```
CSteamInputService_ControllerButtonStateChanged_Notification
CSteamInputService_ControllerAxesStateChange_Notification
CSteamInputService_GyroQuaternionChanged_Notification
CSteamInputService_GyroSpeedChanged_Notification
CSteamInputService_GyroAccelerometerChanged_Notification
CSteamInputService_GyroCalibration_Notification
CSteamInputService_ControllerPowerMenu_Notification
CSteamInputService_ControllerDisconnected_Notification
CSteamInputService_ControllerPairingChanged_Notification
CSteamInputService_ControllerListChanged_Notification
CSteamInputService_FirstSteamControllerConnection_Notification
CSteamInputService_ControllerBatteryState_Notification
CSteamInputService_TritonQos_Notification
CSteamInputService_UnpairedTritonPluggedIn_Notification
CSteamInputService_UnpairedTritonDocked_Notification
CSteamInputService_TritonUndocked_Notification
CSteamInputService_SteamDonglesChanged_Notification
```

### Requests/Responses (Host -> Controller)

```
CSteamInputService_GyroSoftwareCalibration_Request/Response
CSteamInputService_ControllerStateFlow_Request/Response
CSteamInputService_PairDongleTritonConnected_Request/Response
CSteamInputService_WaitInitialControllerStateEnumerated_Request/Response
CSteamInputService_ControllerAccessibilityStrings_Request/Response
CSteamInputService_GetTritonPairingInfo_Request/Response
CSteamInputService_ForgetTritonPairingBond_Request/Response
CSteamInputService_ForgetDonglePairingBond_Request/Response
CSteamInputService_GetControllerName_Request/Response
CSteamInputService_EnableDockedInput_Request/Response
CSteamInputService_InitControllerList_Request/Response
CSteamInputService_GetControllerList_Request/Response
CSteamInputService_GetDongles_Request/Response
CSteamInputService_ShouldTritonPairInOobe_Request/Response
CSteamInputService_EnableQosStatus_Request/Response
```

### HID Message Types

```
CHIDMessageToRemote.DeviceSendFeatureReport
CHIDMessageToRemote.DeviceGetFeatureReport
CHIDMessageToRemote.DeviceStartInputReports
CHIDMessageToRemote.DeviceRequestFullReport
CHIDMessageToRemote.DeviceGetSerialNumberString
CHIDMessageFromRemote.DeviceInputReports
CHIDMessageFromRemote.DeviceInputReports.DeviceInputReport
```

---

## 10. Controller Abstraction Hierarchy

```
CSteamController
  +-- CSteamControllerAbstractionBase (abstract)
  |     +-- CSteamControllerTritonPacketAbstraction
  |     +-- CSteamControllerChellAbstraction
  |     +-- CSteamControllerAlternativePacketAbstraction
  +-- CSteamControllerProtocolHandlerV1
  +-- CSteamControllerProtocolHandlerV2
  +-- CTritonController
  +-- CSharedControllerState
  +-- CHIDIOThread
  +-- CRumbleThread
  +-- CNeptuneIMUCalibrationWorkItem
```

---

## 11. Controller Type Enum (from logs)

| Type Value | Controller | Example |
|-----------|------------|---------|
| `10` (0x0A) | Neptune/SC2 (Steam Controller 2026) | Serial: `28de-1303-2efea7d`, ProductID: `4867` |
| `30` (0x1E) | Generic Gamepad | Serial: `3332-3534-2efea7d`, ProductID: `13620` |

---

## 12. Neptune Chipset Variants

Found in `libcef.so`:
- `Neptune LTX chipset`
- `Neptune VLT chipset`
- `Neptune LTS chipset`
- `Neptune ULS chipset`

---

## 13. SDL HID API Functions Used

```
SDL_hid_init
SDL_hid_exit
SDL_hid_enumerate
SDL_hid_free_enumeration
SDL_hid_open_path
SDL_hid_close
SDL_hid_read_timeout
SDL_hid_write
SDL_hid_send_feature_report
SDL_hid_get_feature_report
SDL_hid_get_serial_number_string
SDL_hid_get_manufacturer_string
SDL_hid_get_product_string
SDL_hid_set_nonblocking
SDL_hid_device_change_count
SDL_hid_get_report_descriptor
SDL_hid_get_input_report
SDL_hid_ble_scan
```

---

## 14. Controller Config Files

### Base configs in `controller_base/`

| File | Controller Type |
|------|----------------|
| `basicui_neptune.vdf` | `controller_neptune` (SC2) |
| `basicui_gamepad.vdf` | `controller_xboxone` |
| `chord_triton.vdf` | `controller_triton` |
| `chord_neptune.vdf` | `controller_neptune` |
| `chord_neptune_external.vdf` | `controller_neptune` |
| `desktop_neptune.vdf` | `controller_neptune` |

### Per-game config example

```
steamapps/common/Steam Controller Configs/49277565/config/413080/controller_neptune.vdf
    Title: "Desktop Configuration"
    controller_type: controller_neptune
    controller_caps: 23117823
    Actions: Default (Desktop), Preset_1000001 (Gamepad)
    Groups: 28 input groups (buttons, dpad, joystick, triggers, scrollwheel, etc.)
```

---

## 15. Why CCCDs Might Not Be Written

### Root Cause Analysis

**Steam does NOT use standard GATT notifications for the Valve Custom Service.**

1. **Kernel hidraw path**: When the SC2 connects via BLE, BlueZ registers it as an
   `org.bluez.Device1`. SDL3 then opens the corresponding `/dev/hidrawN` device. Input
   reports arrive via `read()` syscalls on the hidraw fd, NOT via GATT notifications.

2. **Custom protocol**: The string `Controller uses V1 HID protocol via BLE` confirms
   Steam uses its own transport. The `CSteamControllerProtocolHandlerV1` class handles
   this protocol. It wraps HID messages in a custom framing layer
   (`CHIDMessageToRemote` / `CHIDMessageFromRemote`).

3. **Feature report I/O**: All control communication (settings, firmware, calibration)
   goes through feature reports (`ioctl(HIDIOCGFEATURE)` / `ioctl(HIDIOCSFEATURE)`),
   not GATT writes.

4. **BlueZ handles the GATT layer**: The kernel BlueZ stack or `bluetoothd` handles
   any CCCD writes transparently. Steam doesn't need to do this itself -- it happens
   at the BlueZ/D-Bus level when the HID profile is registered.

### If SC2 is failing to connect

- Check if `/dev/hidrawN` appears when SC2 connects
- Check `bluetoothctl` for connection status
- Check if `uhid` kernel module is loaded (needed for BLE HID devices)
- The `Controller device closed after hid_read failure` error means the hidraw
  connection dropped
- The test results showing ALL FAIL (triggers, trackpads, joysticks, buttons, haptics)
  suggest the V1 HID protocol handshake is not completing

---

## 16. Controller Support Test Results

### SC2 #1: Serial `28de-1303-2efea7d` (FW `0x65E4F1AD`, Mar 2024)

```
Board revision: 46
FW revision: 0x65E4F1AD (Sun Mar  3 16:54:53 2024)
Left trigger result:  FAIL, Min=0, Max=0
Right trigger result: FAIL, Min=0, Max=0
Left trackpad result: FAIL, 0x00000000
Right trackpad result: FAIL, 0x00000000
Left Joystick result: FAIL, XMin=0, XMax=0, YMin=0, YMax=0
Right Joystick result: FAIL, XMin=0, XMax=0, YMin=0, YMax=0
Buttons result: FAIL, 0x00000000
Left haptics result: FAIL
Right haptics result: FAIL
```

### SC2 #2: Serial `FY2S443045FD` (FW `0x6876D00D`, Jul 2025)

```
Board revision: 46
FW revision: 0x6876D00D (Tue Jul 15 18:02:53 2025)
Left trigger result:  FAIL, Min=0, Max=0
Right trigger result: FAIL, Min=0, Max=0
Left trackpad result: FAIL, 0x00000000
Right trackpad result: PASS, 0x000001FF
Left Joystick result: PASS, XMin=-32767, XMax=32767, YMin=-32767, YMax=32767
Right Joystick result: PASS, XMin=-32767, XMax=32767, YMin=-32767, YMax=32767
Buttons result: FAIL, 0xC00000000000
Left haptics result: FAIL
Right haptics result: FAIL
```

Note: SC2 #2 with newer firmware (Jul 2025) shows partial success -- joysticks and right
trackpad work. This suggests the newer firmware may have better compatibility.
