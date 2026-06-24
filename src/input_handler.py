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


XBOX_TO_SC2_BUTTON = {
    ecodes.BTN_SOUTH:  0x0001,
    ecodes.BTN_EAST:   0x0002,
    ecodes.BTN_NORTH:  0x0004,
    ecodes.BTN_WEST:   0x0008,
    ecodes.BTN_TL:     0x0010,
    ecodes.BTN_TR:     0x0020,
    ecodes.BTN_SELECT: 0x0040,
    ecodes.BTN_START:  0x0080,
    ecodes.BTN_MODE:   0x0100,
    ecodes.BTN_THUMBL: 0x0200,
    ecodes.BTN_THUMBR: 0x0400,
}

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
    b'\x01\x00\x81' + b'\x00' * 61,
    b'\x01\x00\x87\x03\x08\x07\x00' + b'\x00' * 57,
    b'\x01\x00\x87\x03\x15\x00\x00' + b'\x00' * 57,
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


def _parse_neptune_report(raw):
    if len(raw) < 64 or raw[2] != 0x09:
        return None
    report = SC2InputReport()

    btn8 = raw[8]
    btn9 = raw[9]
    btn10 = raw[10]
    btn11 = raw[11]
    btn13 = raw[13]
    btn14 = raw[14]

    b = 0
    if btn8 & 0x01: b |= 0x0001
    if btn8 & 0x04: b |= 0x0002
    if btn8 & 0x02: b |= 0x0004
    if btn8 & 0x08: b |= 0x0008
    if btn8 & 0x10: b |= 0x0010
    if btn8 & 0x20: b |= 0x0020
    if btn9 & 0x02: b |= 0x0040
    if btn9 & 0x08: b |= 0x0080
    if btn9 & 0x04: b |= 0x0100
    if btn10 & 0x02: b |= 0x0200
    if btn11 & 0x20: b |= 0x0400
    if btn9 & 0x80: b |= 0x0800
    if btn9 & 0x10: b |= 0x1000
    if btn9 & 0x20: b |= 0x2000
    if btn9 & 0x40: b |= 0x4000
    report.buttons = b

    report.lx = struct.unpack_from('<h', raw, 48)[0]
    report.ly = struct.unpack_from('<h', raw, 50)[0]
    report.rx = struct.unpack_from('<h', raw, 52)[0]
    report.ry = struct.unpack_from('<h', raw, 54)[0]

    lt = struct.unpack_from('<H', raw, 44)[0]
    rt = struct.unpack_from('<H', raw, 46)[0]
    report.left_trigger = min(255, lt >> 7)
    report.right_trigger = min(255, rt >> 7)

    return report.to_bytes()


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
                        report_bytes = _parse_neptune_report(raw)
                        if report_bytes and self.on_report:
                            self.on_report(report_bytes)
                            print(f"[input] Report sent: {report_bytes.hex()}")
        except Exception as e:
            if self._running:
                print(f"[-] Neptune read error: {type(e).__name__}: {e}")

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
            self.on_report(report)
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
