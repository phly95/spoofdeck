#!/usr/bin/env python3

import os
import struct
import select
import threading
import time

try:
    import evdev
    from evdev import ecodes
    HAS_EVDEV = True
except ImportError:
    HAS_EVDEV = False


# Triton 32-bit button bitmask constants — from SDL3 SDL_hidapi_steam_triton.c
# These map evdev button codes to the Triton SC2 32-bit bitmask positions.
XBOX_TO_SC2_BUTTON = {
    ecodes.BTN_SOUTH:  0x00000001,  # bit 0: A
    ecodes.BTN_EAST:   0x00000002,  # bit 1: B
    ecodes.BTN_NORTH:  0x00000004,  # bit 2: X
    ecodes.BTN_WEST:   0x00000008,  # bit 3: Y
    ecodes.BTN_TL:     0x00080000,  # bit 19: Left Bumper
    ecodes.BTN_TR:     0x00000200,  # bit 9: Right Bumper
    ecodes.BTN_SELECT: 0x00004000,  # bit 14: Menu (right button) → Back/Select
    ecodes.BTN_START:  0x00000040,  # bit 6: View (left button) → Start
    ecodes.BTN_MODE:   0x00010000,  # bit 16: Steam
    ecodes.BTN_THUMBL: 0x00008000,  # bit 15: L3
    ecodes.BTN_THUMBR: 0x00000020,  # bit 5: R3
}

# Standard HID gamepad DPad positions (for 12-byte evdev path, bits 11-14)
DPAD_UP    = 0x0800
DPAD_DOWN  = 0x1000
DPAD_LEFT  = 0x2000
DPAD_RIGHT = 0x4000

ABS_X = 0
ABS_Y = 1
ABS_Z = 2
ABS_RX = 3
ABS_RY = 4
ABS_RZ = 5
ABS_HAT0X = 16
ABS_HAT0Y = 17

NEPTUNE_LIZARD_OFF_CMDS = [
    b'\x81' + b'\x00' * 63,                          # ClearDigitalMappings
    b'\x87\x03\x08\x07\x00' + b'\x00' * 59,          # RPadMode -> TrackpadMode.None (0x07)
    b'\x87\x03\x07\x07\x00' + b'\x00' * 59,          # LPadMode -> TrackpadMode.None (0x07)
    b'\x87\x03\x18\x00\x00' + b'\x00' * 59,          # SmoothAbsoluteMouse -> 0
    b'\x87\x03\x15\x00\x00' + b'\x00' * 59,          # SensitivityScaleAmount -> 0
]


class SC2InputReport:
    def __init__(self):
        self.buttons = 0
        self.left_trigger = 0
        self.right_trigger = 0
        self.lx = 0
        self.ly = 0
        self.rx = 0
        self.ry = 0

    def to_bytes(self):
        report = bytearray(12)
        struct.pack_into("<H", report, 0, self.buttons & 0xFFFF)
        struct.pack_into("<h", report, 2, self.lx)
        struct.pack_into("<h", report, 4, self.ly)
        struct.pack_into("<h", report, 6, self.rx)
        struct.pack_into("<h", report, 8, self.ry)
        report[10] = self.left_trigger
        report[11] = self.right_trigger
        return bytes(report)


def find_neptune_hidraw():
    base = "/sys/class/hidraw"
    if not os.path.isdir(base):
        return None
    for entry in os.listdir(base):
        device_dir = os.path.join(base, entry, "device")
        uevent_path = os.path.join(device_dir, "uevent")
        if not os.path.isfile(uevent_path):
            continue
        try:
            with open(uevent_path, "r") as f:
                content = f.read()
        except OSError:
            continue
        if "28DE" not in content or "1205" not in content:
            continue
        if "input2" not in content:
            continue
        dev_path = os.path.join("/dev", entry)
        if os.path.exists(dev_path):
            print(f"[+] Found Neptune hidraw: {dev_path}")
            return dev_path
    return None


def _send_lizard_off(fd):
    for cmd in NEPTUNE_LIZARD_OFF_CMDS:
        try:
            os.write(fd, cmd)
        except OSError:
            pass


class InputHandler:
    def __init__(self, on_report=None, device_path=None):
        self.on_report = on_report
        self.device_path = device_path
        self.device = None
        self._thread = None
        self._running = False
        self._dirty = False
        self._absinfo = {}
        self._is_neptune = False
        self._neptune_fd = None
        self.report = SC2InputReport()
        self.seq_num = 0
        self.start_time = time.monotonic()
        
        # State tracking for Mouse and Keyboard emulation (Lizard mode)
        self.prev_rpad_x = None
        self.prev_rpad_y = None
        self.prev_lpad_x = None
        self.prev_lpad_y = None
        self.last_mouse_buttons = 0
        self.last_kbd_report = b'\x00' * 8

    def _parse_neptune_report(self, raw):
        if len(raw) < 64 or raw[2] != 0x09:
            return None
        report = SC2InputReport()

        self.seq_num = (self.seq_num + 1) & 0xFF
        timestamp_us = int((time.monotonic() - self.start_time) * 1000000) & 0xFFFFFFFF

        btn8 = raw[8]
        btn9 = raw[9]
        btn10 = raw[10]
        btn11 = raw[11]
        btn13 = raw[13]
        btn14 = raw[14]

        b = 0
        # Byte 8:
        # a (bit 7/0x80) -> BTN_SOUTH (0x0001)
        if btn8 & 0x80: b |= 0x0001
        # b (bit 5/0x20) -> BTN_EAST (0x0002)
        if btn8 & 0x20: b |= 0x0002
        # x (bit 6/0x40) -> BTN_NORTH (0x0004)
        if btn8 & 0x40: b |= 0x0004
        # y (bit 4/0x10) -> BTN_WEST (0x0008)
        if btn8 & 0x10: b |= 0x0008
        # l1 (bit 3/0x08) -> BTN_TL (0x0010)
        if btn8 & 0x08: b |= 0x0010
        # r1 (bit 2/0x04) -> BTN_TR (0x0020)
        if btn8 & 0x04: b |= 0x0020

        # Byte 9:
        # options (bit 4/0x10) -> BTN_SELECT (0x0040)
        if btn9 & 0x10: b |= 0x0040
        # menu (bit 6/0x40) -> BTN_START (0x0080)
        if btn9 & 0x40: b |= 0x0080
        # steam (bit 5/0x20) -> BTN_MODE (0x0100)
        if btn9 & 0x20: b |= 0x0100

        # Byte 10:
        # l3 (bit 6/0x40) -> BTN_THUMBL (0x0200)
        if btn10 & 0x40: b |= 0x0200

        # Byte 11:
        # r3 (bit 2/0x04) -> BTN_THUMBR (0x0400)
        if btn11 & 0x04: b |= 0x0400

        # D-pad (Byte 9):
        # up (bit 0/0x01) -> DPAD_UP (0x0800)
        if btn9 & 0x01: b |= 0x0800
        # down (bit 3/0x08) -> DPAD_DOWN (0x1000)
        if btn9 & 0x08: b |= 0x1000
        # left (bit 2/0x04) -> DPAD_LEFT (0x2000)
        if btn9 & 0x04: b |= 0x2000
        # right (bit 1/0x02) -> DPAD_RIGHT (0x4000)
        if btn9 & 0x02: b |= 0x4000

        # Back grips: L4 (byte 13 bit 1/0x02), L5 (byte 9 bit 7/0x80), R4 (byte 13 bit 2/0x04), R5 (byte 10 bit 0/0x01)
        if (btn13 & 0x02) or (btn9 & 0x80) or (btn13 & 0x04) or (btn10 & 0x01):
            b |= 0x8000

        report.buttons = b

        lx = struct.unpack_from('<h', raw, 48)[0]
        ly = struct.unpack_from('<h', raw, 50)[0]  # No negate: SC2 stores Y as-is, SDL negates
        rx = struct.unpack_from('<h', raw, 52)[0]
        ry = struct.unpack_from('<h', raw, 54)[0]  # No negate: SC2 stores Y as-is, SDL negates

        report.lx = lx
        report.ly = ly
        report.rx = rx
        report.ry = ry

        lt = struct.unpack_from('<H', raw, 44)[0]
        rt = struct.unpack_from('<H', raw, 46)[0]
        # SC2 expects triggers as signed 16-bit (0-32767 range, same as Neptune)
        left_trigger_16 = min(32767, lt)
        right_trigger_16 = min(32767, rt)
        report.left_trigger = min(255, lt >> 7)
        report.right_trigger = min(255, rt >> 7)

        # --- 45-byte SC2 BLE Custom Report (Report 0x45) ---
        # Triton 32-bit button bitmask — from SDL3 src/joystick/hidapi/SDL_hidapi_steam_triton.c
        # Neptune byte layout: see linux/drivers/hid/hid-steam.c steam_do_deck_input_event()
        b32 = 0
        if btn8 & 0x80: b32 |= (1 << 0)   # A
        if btn8 & 0x20: b32 |= (1 << 1)   # B
        if btn8 & 0x40: b32 |= (1 << 2)   # X
        if btn8 & 0x10: b32 |= (1 << 3)   # Y
        if btn14 & 0x04: b32 |= (1 << 4)  # QAM (Quick Access Menu)
        if btn11 & 0x04: b32 |= (1 << 5)  # R3
        if btn9 & 0x40: b32 |= (1 << 6)   # View / Options (left button, two squares)
        if btn13 & 0x04: b32 |= (1 << 7)  # R4 (Right Paddle 1)
        if btn10 & 0x01: b32 |= (1 << 8)  # R5 (Right Paddle 2)
        if btn8 & 0x04: b32 |= (1 << 9)   # R (Right Bumper)
        if btn9 & 0x08: b32 |= (1 << 10)  # DPad Down
        if btn9 & 0x02: b32 |= (1 << 11)  # DPad Right
        if btn9 & 0x04: b32 |= (1 << 12)  # DPad Left
        if btn9 & 0x01: b32 |= (1 << 13)  # DPad Up
        if btn9 & 0x10: b32 |= (1 << 14)  # Menu (right button, three lines)
        if btn10 & 0x40: b32 |= (1 << 15) # L3
        if btn9 & 0x20: b32 |= (1 << 16)  # Steam
        if btn13 & 0x02: b32 |= (1 << 17) # L4 (Left Paddle 1)
        if btn9 & 0x80: b32 |= (1 << 18)  # L5 (Left Paddle 2)
        if btn8 & 0x08: b32 |= (1 << 19)  # L (Left Bumper)
        if btn13 & 0x80: b32 |= (1 << 20) # Right Joystick Touch
        if btn10 & 0x10: b32 |= (1 << 21) # Right Touchpad Touch
        if btn10 & 0x04: b32 |= (1 << 22) # Right Touchpad Click
        if btn8 & 0x02: b32 |= (1 << 23)  # Right Trigger Click
        if btn13 & 0x40: b32 |= (1 << 24) # Left Joystick Touch
        if btn10 & 0x08: b32 |= (1 << 25) # Left Touchpad Touch
        if btn10 & 0x02: b32 |= (1 << 26) # Left Touchpad Click
        if btn8 & 0x01: b32 |= (1 << 27)  # Left Trigger Click

        lpad_x = struct.unpack_from('<h', raw, 16)[0]
        lpad_y = struct.unpack_from('<h', raw, 18)[0]
        rpad_x = struct.unpack_from('<h', raw, 20)[0]
        rpad_y = struct.unpack_from('<h', raw, 22)[0]

        accel_x = struct.unpack_from('<h', raw, 24)[0]
        accel_y = struct.unpack_from('<h', raw, 26)[0]
        accel_z = struct.unpack_from('<h', raw, 28)[0]
        gyro_x = struct.unpack_from('<h', raw, 30)[0]
        gyro_y = struct.unpack_from('<h', raw, 32)[0]
        gyro_z = struct.unpack_from('<h', raw, 34)[0]
        # Trackpad pressure/force sensors (Neptune bytes 56-59)
        lpad_force = struct.unpack_from('<H', raw, 56)[0]
        rpad_force = struct.unpack_from('<H', raw, 58)[0]

        # SC2 45-byte report layout from SDL3 TritonMTUNoQuat_t struct:
        # [0]      seq_num (1 byte)
        # [1-4]    buttons (32-bit)
        # [5-6]    sTriggerLeft (signed 16-bit, 0-32767)
        # [7-8]    sTriggerRight (signed 16-bit, 0-32767)
        # [9-10]   sLeftStickX (signed 16-bit)
        # [11-12]  sLeftStickY (signed 16-bit)
        # [13-14]  sRightStickX (signed 16-bit)
        # [15-16]  sRightStickY (signed 16-bit)
        # [17-18]  sLeftPadX (signed 16-bit)
        # [19-20]  sLeftPadY (signed 16-bit)
        # [21-22]  unPressureLeft (unsigned 16-bit)
        # [23-24]  sRightPadX (signed 16-bit)
        # [25-26]  sRightPadY (signed 16-bit)
        # [27-28]  unPressureRight (unsigned 16-bit)
        # [29-32]  timestamp (uint32_t)
        # [33-34]  accel_x (signed 16-bit)
        # [35-36]  accel_y (signed 16-bit)
        # [37-38]  accel_z (signed 16-bit)
        # [39-40]  gyro_x (signed 16-bit)
        # [41-42]  gyro_y (signed 16-bit)
        # [43-44]  gyro_z (signed 16-bit)
        report45 = bytearray(45)
        report45[0] = self.seq_num
        struct.pack_into("<I", report45, 1, b32)
        struct.pack_into("<h", report45, 5, left_trigger_16)
        struct.pack_into("<h", report45, 7, right_trigger_16)
        struct.pack_into("<h", report45, 9, lx)
        struct.pack_into("<h", report45, 11, ly)
        struct.pack_into("<h", report45, 13, rx)
        struct.pack_into("<h", report45, 15, ry)
        struct.pack_into("<h", report45, 17, lpad_x)
        struct.pack_into("<h", report45, 19, lpad_y)
        struct.pack_into("<H", report45, 21, lpad_force)  # unPressureLeft
        struct.pack_into("<h", report45, 23, rpad_x)
        struct.pack_into("<h", report45, 25, rpad_y)
        struct.pack_into("<H", report45, 27, rpad_force)  # unPressureRight
        struct.pack_into("<I", report45, 29, timestamp_us)
        struct.pack_into("<h", report45, 33, accel_x)
        struct.pack_into("<h", report45, 35, accel_y)
        struct.pack_into("<h", report45, 37, accel_z)
        struct.pack_into("<h", report45, 39, gyro_x)
        struct.pack_into("<h", report45, 41, gyro_y)
        struct.pack_into("<h", report45, 43, gyro_z)

        # --- Lizard Mode Mouse Emulation ---
        rpad_touch = bool(btn10 & 0x10)
        lpad_touch = bool(btn10 & 0x08)

        dx_mouse = 0
        dy_mouse = 0
        if rpad_touch:
            if self.prev_rpad_x is None or self.prev_rpad_y is None:
                self.prev_rpad_x = rpad_x
                self.prev_rpad_y = rpad_y
            else:
                dx = rpad_x - self.prev_rpad_x
                dy = self.prev_rpad_y - rpad_y
                dx_mouse = int(dx / 150)
                dy_mouse = int(dy / 150)
                self.prev_rpad_x = rpad_x
                self.prev_rpad_y = rpad_y
        else:
            self.prev_rpad_x = None
            self.prev_rpad_y = None

        scroll_y = 0
        if lpad_touch:
            if self.prev_lpad_x is None or self.prev_lpad_y is None:
                self.prev_lpad_x = lpad_x
                self.prev_lpad_y = lpad_y
            else:
                scroll_dy = lpad_y - self.prev_lpad_y
                scroll_y = int(scroll_dy / 300)
                self.prev_lpad_x = lpad_x
                self.prev_lpad_y = lpad_y
        else:
            self.prev_lpad_x = None
            self.prev_lpad_y = None

        # Clamp mouse coordinates to signed 8-bit
        dx_mouse = max(-127, min(127, dx_mouse))
        dy_mouse = max(-127, min(127, dy_mouse))
        scroll_y = max(-127, min(127, scroll_y))

        # Mouse button states
        mouse_buttons = 0
        if (btn10 & 0x04) or (rt > 10000):  # RPadPress or Right Trigger -> Left Click
            mouse_buttons |= 0x01
        if (btn10 & 0x02) or (lt > 10000):  # LPadPress or Left Trigger -> Right Click
            mouse_buttons |= 0x02
        if (btn10 & 0x40):  # L3 -> Middle Click
            mouse_buttons |= 0x04

        # Verify mouse changes
        mouse_report = None
        if (mouse_buttons != self.last_mouse_buttons) or (dx_mouse != 0) or (dy_mouse != 0) or (scroll_y != 0):
            mouse_report = struct.pack('<Bbbb', mouse_buttons, dx_mouse, dy_mouse, scroll_y)
            self.last_mouse_buttons = mouse_buttons

        # --- Lizard Mode Keyboard Emulation ---
        active_keys = []
        if btn9 & 0x01: active_keys.append(0x52)  # Dpad Up -> Up Arrow
        if btn9 & 0x08: active_keys.append(0x51)  # Dpad Down -> Down Arrow
        if btn9 & 0x04: active_keys.append(0x50)  # Dpad Left -> Left Arrow
        if btn9 & 0x02: active_keys.append(0x4F)  # Dpad Right -> Right Arrow
        if btn8 & 0x80: active_keys.append(0x28)  # A -> Return
        if btn8 & 0x20: active_keys.append(0x29)  # B -> Escape
        if btn8 & 0x40: active_keys.append(0x2C)  # X -> Spacebar
        if btn8 & 0x10: active_keys.append(0x2B)  # Y -> Tab
        if btn9 & 0x10: active_keys.append(0x2B)  # Options -> Tab
        if btn9 & 0x40: active_keys.append(0x29)  # Menu -> Esc

        active_keys = active_keys[:6]
        while len(active_keys) < 6:
            active_keys.append(0)

        modifiers = 0
        if btn8 & 0x08: modifiers |= 0x01  # L1 -> Left Control
        if btn8 & 0x04: modifiers |= 0x02  # R1 -> Left Shift
        if btn9 & 0x20: modifiers |= 0x08  # Steam button -> Left GUI (Super/Win)

        kbd_report_candidate = struct.pack('<BB6B', modifiers, 0, *active_keys)
        kbd_report = None
        if kbd_report_candidate != self.last_kbd_report:
            kbd_report = kbd_report_candidate
            self.last_kbd_report = kbd_report_candidate

        return {
            'gamepad_12b': report.to_bytes(),
            'gamepad_45b': bytes(report45),
            'mouse_4b': mouse_report,
            'kbd_8b': kbd_report
        }

    def find_xbox_device(self):
        if not HAS_EVDEV:
            print("[-] evdev not installed")
            return None
        for path in evdev.list_devices():
            try:
                dev = evdev.InputDevice(path)
                name = dev.name.lower()
                caps = dev.capabilities(verbose=False)
                if ("xbox" in name or "360 pad" in name or "x-box" in name):
                    if ecodes.EV_ABS in caps and ecodes.EV_KEY in caps:
                        print(f"[+] Found Xbox device: {dev.name} at {path}")
                        return dev
                if ecodes.EV_ABS in caps and ecodes.EV_KEY in caps:
                    keys = caps.get(ecodes.EV_KEY, [])
                    if ecodes.BTN_SOUTH in keys and ecodes.BTN_EAST in keys:
                        print(f"[+] Found gamepad: {dev.name} at {path}")
                        return dev
                dev.close()
            except Exception:
                continue
        return None

    def start(self):
        if self._running:
            return

        if self.device_path:
            if self.device_path.startswith("/dev/hidraw"):
                self._is_neptune = True
                try:
                    self._neptune_fd = os.open(self.device_path, os.O_RDWR | os.O_NONBLOCK)
                    print(f"[+] Neptune hidraw opened: {self.device_path}")
                except OSError as e:
                    print(f"[-] Cannot open {self.device_path}: {e}")
                    return
            elif self.device_path.startswith("/dev/input/"):
                if not HAS_EVDEV:
                    print("[-] evdev not installed")
                    return
                try:
                    self.device = evdev.InputDevice(self.device_path)
                    print(f"[+] Using device: {self.device.name}")
                except Exception as e:
                    print(f"[-] Cannot open {self.device_path}: {e}")
                    return
            else:
                print(f"[-] Unknown device path format: {self.device_path}")
                return
        else:
            neptune_path = find_neptune_hidraw()
            if neptune_path:
                self._is_neptune = True
                try:
                    self._neptune_fd = os.open(neptune_path, os.O_RDWR | os.O_NONBLOCK)
                    print(f"[+] Neptune hidraw opened: {neptune_path}")
                except OSError as e:
                    print(f"[-] Cannot open {neptune_path}: {e}")
                    return
            else:
                self.device = self.find_xbox_device()
                if not self.device:
                    print("[-] No Neptune controller or Xbox 360 controller found")
                    return

        self._running = True
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        print("[+] Input handler started" + (" (Neptune)" if self._is_neptune else " (evdev)"))

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        if self._neptune_fd is not None:
            try:
                os.close(self._neptune_fd)
            except OSError:
                pass
            self._neptune_fd = None
        if self.device:
            self.device.close()
            self.device = None

    def _read_loop(self):
        if self._is_neptune:
            self._neptune_read_loop()
        else:
            self._evdev_read_loop()

    def _neptune_read_loop(self):
        _send_lizard_off(self._neptune_fd)
        last_lizard_off = time.monotonic()
        print(f"[input] Neptune read loop started")
        retry_count = 0
        max_retries = 10
        while self._running and retry_count < max_retries:
            try:
                while self._running:
                    r, _, _ = select.select([self._neptune_fd], [], [], 1.0)
                    now = time.monotonic()
                    if now - last_lizard_off >= 2.0:
                        _send_lizard_off(self._neptune_fd)
                        last_lizard_off = now
                    if r:
                        try:
                            raw = os.read(self._neptune_fd, 64)
                        except BlockingIOError:
                            continue
                        if len(raw) == 64:
                            reports = self._parse_neptune_report(raw)
                            if reports and self.on_report:
                                self.on_report(reports)
                                if self.seq_num % 100 == 0:
                                    g12 = reports.get('gamepad_12b', b'')
                                    m4 = reports.get('mouse_4b')
                                    m4_hex = m4.hex() if m4 else 'None'
                                    print(f"[input] Neptune reports forwarded (throttled): 12b={g12.hex()[:8]}... mouse_4b={m4_hex}")
            except Exception as e:
                if not self._running:
                    break
                retry_count += 1
                print(f"[-] Neptune read error ({retry_count}/{max_retries}): {type(e).__name__}: {e}")
                # Try to reopen the device
                try:
                    os.close(self._neptune_fd)
                except OSError:
                    pass
                time.sleep(2)  # Wait for device to recover
                try:
                    from input_handler import find_neptune_hidraw
                    dev_path = find_neptune_hidraw()
                    if dev_path:
                        # BUG: Initial open at line 429 uses O_RDWR, but reopen uses O_RDONLY.
                        # After reopen, write operations (lizard-off, haptics) will fail silently.
                        self._neptune_fd = os.open(dev_path, os.O_RDWR | os.O_NONBLOCK)
                        self.device_path = dev_path
                        print(f"[input] Neptune device reopened: {dev_path}")
                        last_lizard_off = time.monotonic()
                        # Retry counter resets on successful reopen — the 10-retry limit only applies
                        # to consecutive failures. A single successful reopen allows 10 more retries.
                        retry_count = 0  # Reset on successful reopen
                    else:
                        print(f"[-] Neptune device not found, retrying in 5s...")
                        time.sleep(5)
                except Exception as reopen_err:
                    print(f"[-] Neptune reopen failed: {reopen_err}")
                    time.sleep(5)
        if retry_count >= max_retries:
            print(f"[-] Neptune read loop gave up after {max_retries} retries")

    def _evdev_read_loop(self):
        self._absinfo = dict(self.device.capabilities(verbose=False).get(ecodes.EV_ABS, []))
        try:
            print(f"[input] Read loop started on {self.device.path}")
            while self._running:
                r, _, _ = select.select([self.device.fd], [], [], 1.0)
                if r:
                    for event in self.device.read_loop():
                        self._handle_event(event)
        except Exception as e:
            if self._running:
                print(f"[-] Input read error: {type(e).__name__}: {e}")

    def _handle_event(self, event):
        if event.type == ecodes.EV_ABS:
            self._handle_abs(event)
        elif event.type == ecodes.EV_KEY:
            self._handle_key(event)

    def _handle_abs(self, event):
        code = event.code
        value = event.value
        if code == ABS_X:
            self.report.lx = self._normalize_stick(value, self._get_absinfo(code))
        elif code == ABS_Y:
            self.report.ly = self._normalize_stick(value, self._get_absinfo(code))
        elif code == ABS_RX:
            self.report.rx = self._normalize_stick(value, self._get_absinfo(code))
        elif code == ABS_RY:
            self.report.ry = self._normalize_stick(value, self._get_absinfo(code))
        elif code == ABS_Z:
            self.report.left_trigger = self._normalize_trigger(value, self._get_absinfo(code))
        elif code == ABS_RZ:
            self.report.right_trigger = self._normalize_trigger(value, self._get_absinfo(code))
        elif code == ABS_HAT0X:
            if value < 0:
                self.report.buttons |= DPAD_LEFT
                self.report.buttons &= ~DPAD_RIGHT
            elif value > 0:
                self.report.buttons |= DPAD_RIGHT
                self.report.buttons &= ~DPAD_LEFT
            else:
                self.report.buttons &= ~(DPAD_LEFT | DPAD_RIGHT)
        elif code == ABS_HAT0Y:
            if value < 0:
                self.report.buttons |= DPAD_UP
                self.report.buttons &= ~DPAD_DOWN
            elif value > 0:
                self.report.buttons |= DPAD_DOWN
                self.report.buttons &= ~DPAD_UP
            else:
                self.report.buttons &= ~(DPAD_UP | DPAD_DOWN)
        self._dirty = True
        self._send_if_needed()

    def _handle_key(self, event):
        sc2_button = XBOX_TO_SC2_BUTTON.get(event.code)
        if sc2_button is not None:
            if event.value:
                self.report.buttons |= sc2_button
            else:
                self.report.buttons &= ~sc2_button
        self._dirty = True
        self._send_if_needed()

    def _send_if_needed(self):
        if self._dirty and self.on_report:
            report = self.report.to_bytes()
            report_dict = {
                'gamepad_12b': report,
                'gamepad_45b': None,
                'mouse_4b': None,
                'kbd_8b': None
            }
            self.on_report(report_dict)
            self._dirty = False
            print(f"[input] Report sent: {report.hex()}")

    def _get_absinfo(self, code):
        return self._absinfo.get(code)

    def _normalize_stick(self, value, absinfo):
        if absinfo is None:
            min_val, max_val = -32768, 32767
        else:
            min_val = absinfo.min
            max_val = absinfo.max
        normalized = int((value - min_val) / (max_val - min_val) * 65535 - 32768)
        return max(-32768, min(32767, normalized))

    def _normalize_trigger(self, value, absinfo):
        if absinfo is None:
            min_val, max_val = 0, 255
        else:
            min_val = absinfo.min
            max_val = absinfo.max
        normalized = int((value - min_val) / (max_val - min_val) * 255)
        return max(0, min(255, normalized))
