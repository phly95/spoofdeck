#!/usr/bin/env python3
"""
Input handler for Steam Controller 2026 BLE Spoof.

Reads controller inputs from the Steam Deck's virtual Xbox 360 pad
(via evdev) and converts them to SC2-format HID input reports.

SC2 Input Report 0x45 (45 bytes):
  Offset  Size  Field
  0       1     Report ID (0x45)
  1       1     Sequence number
  2-5     4     Buttons (32-bit bitmask)
  6       1     Left trigger (0-255)
  7       1     Right trigger (0-255)
  8-9     2     Left stick X (signed 16-bit LE)
  10-11   2     Left stick Y (signed 16-bit LE)
  12-13   2     Right stick X (signed 16-bit LE)
  14-15   2     Right stick Y (signed 16-bit LE)
  16-17   2     Left trackpad X (signed 16-bit LE)
  18-19   2     Left trackpad Y (signed 16-bit LE)
  20-21   2     Right trackpad X (signed 16-bit LE)
  22-23   2     Right trackpad Y (signed 16-bit LE)
  24-35   12    IMU accel+gyro (6 × signed 16-bit LE)
  36-39   4     IMU timestamp (32-bit LE, microseconds)
  40-47   8     IMU quaternion (4 × signed 16-bit LE)
"""

import struct
import threading
import time

try:
    import evdev
    from evdev import ecodes
    HAS_EVDEV = True
except ImportError:
    HAS_EVDEV = False


# Xbox 360 → SC2 button mapping (packed into 16-bit bitmask for HID report)
XBOX_TO_SC2_BUTTON = {
    ecodes.BTN_SOUTH:  0x0001,  # Bit 0: A
    ecodes.BTN_EAST:   0x0002,  # Bit 1: B
    ecodes.BTN_NORTH:  0x0004,  # Bit 2: X
    ecodes.BTN_WEST:   0x0008,  # Bit 3: Y
    ecodes.BTN_TL:     0x0010,  # Bit 4: Left Bumper
    ecodes.BTN_TR:     0x0020,  # Bit 5: Right Bumper
    ecodes.BTN_SELECT: 0x0040,  # Bit 6: Back
    ecodes.BTN_START:  0x0080,  # Bit 7: Start
    ecodes.BTN_MODE:   0x0100,  # Bit 8: Guide/Steam
    ecodes.BTN_THUMBL: 0x0200,  # Bit 9: Left Stick Click
    ecodes.BTN_THUMBR: 0x0400,  # Bit 10: Right Stick Click
}

# D-pad as extra button bits (encoded from HAT0X/HAT0Y axis events)
DPAD_UP    = 0x0800  # Bit 11
DPAD_DOWN  = 0x1000  # Bit 12
DPAD_LEFT  = 0x2000  # Bit 13
DPAD_RIGHT = 0x4000  # Bit 14

# evdev axis codes
ABS_X = 0
ABS_Y = 1
ABS_Z = 2
ABS_RX = 3
ABS_RY = 4
ABS_RZ = 5
ABS_HAT0X = 16
ABS_HAT0Y = 17


class SC2InputReport:
    """Builds HID-format input reports matching the Report Map.

    Report Map layout (12 bytes, Report ID 1):
      Bytes 0-1: 16 buttons (1 bit each, LE)
      Bytes 2-3: X axis (signed 16-bit LE)
      Bytes 4-5: Y axis (signed 16-bit LE)
      Bytes 6-7: Rx axis (signed 16-bit LE)
      Bytes 8-9: Ry axis (signed 16-bit LE)
      Byte 10:   Z trigger (unsigned 8-bit)
      Byte 11:   Rz trigger (unsigned 8-bit)
    """

    def __init__(self):
        self.buttons = 0
        self.left_trigger = 0
        self.right_trigger = 0
        self.lx = 0
        self.ly = 0
        self.rx = 0
        self.ry = 0

    def to_bytes(self):
        """Convert to 12-byte HID report matching Report Map."""
        report = bytearray(12)

        # Buttons (16-bit LE, packed as 16 x 1-bit)
        struct.pack_into("<H", report, 0, self.buttons & 0xFFFF)

        # Sticks (signed 16-bit LE)
        struct.pack_into("<h", report, 2, self.lx)
        struct.pack_into("<h", report, 4, self.ly)
        struct.pack_into("<h", report, 6, self.rx)
        struct.pack_into("<h", report, 8, self.ry)

        # Triggers (unsigned 8-bit)
        report[10] = self.left_trigger
        report[11] = self.right_trigger

        return bytes(report)


class InputHandler:
    """
    Reads controller inputs from the Deck's virtual Xbox 360 pad
    and calls callbacks with SC2-format data.
    """

    def __init__(self, on_report=None, device_path=None):
        """
        Args:
            on_report: callback(report_bytes) called when a new report is ready
            device_path: explicit device path, or auto-detect Xbox 360 pad
        """
        self.on_report = on_report
        self.device_path = device_path
        self.device = None
        self.report = SC2InputReport()
        self._thread = None
        self._running = False
        self._dirty = False
        self._absinfo = {}  # cached absinfo dict: code -> absinfo

    def find_xbox_device(self):
        """Auto-detect Xbox 360 controller device."""
        if not HAS_EVDEV:
            print("[-] evdev not installed")
            return None

        for path in evdev.list_devices():
            try:
                dev = evdev.InputDevice(path)
                name = dev.name.lower()
                caps = dev.capabilities(verbose=False)

                # Check for Xbox 360 pad
                if ("xbox" in name or "360 pad" in name or "x-box" in name):
                    if ecodes.EV_ABS in caps and ecodes.EV_KEY in caps:
                        print(f"[+] Found Xbox device: {dev.name} at {path}")
                        return dev

                # Fallback: check for gamepad-like capabilities
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
        """Start reading input in a background thread."""
        if self._running:
            return

        if self.device_path:
            try:
                self.device = evdev.InputDevice(self.device_path)
                print(f"[+] Using device: {self.device.name}")
            except Exception as e:
                print(f"[-] Cannot open {self.device_path}: {e}")
                return
        else:
            self.device = self.find_xbox_device()
            if not self.device:
                print("[-] No Xbox 360 controller found")
                return

        self._running = True
        self._absinfo = dict(self.device.capabilities(verbose=False).get(ecodes.EV_ABS, []))
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        print("[+] Input handler started")

    def stop(self):
        """Stop reading input."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        if self.device:
            self.device.close()
            self.device = None

    def _read_loop(self):
        """Main input reading loop."""
        try:
            import select
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
        """Process a single input event."""
        if event.type == ecodes.EV_ABS:
            self._handle_abs(event)
        elif event.type == ecodes.EV_KEY:
            self._handle_key(event)

    def _handle_abs(self, event):
        """Handle absolute axis event."""
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
            # D-pad X
            if value < 0:
                self.report.buttons |= DPAD_LEFT
                self.report.buttons &= ~DPAD_RIGHT
            elif value > 0:
                self.report.buttons |= DPAD_RIGHT
                self.report.buttons &= ~DPAD_LEFT
            else:
                self.report.buttons &= ~(DPAD_LEFT | DPAD_RIGHT)
        elif code == ABS_HAT0Y:
            # D-pad Y
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
        """Handle button event."""
        sc2_button = XBOX_TO_SC2_BUTTON.get(event.code)
        if sc2_button is not None:
            if event.value:
                self.report.buttons |= sc2_button
            else:
                self.report.buttons &= ~sc2_button

        self._dirty = True
        self._send_if_needed()

    def _send_if_needed(self):
        """Send report if dirty and callback is set."""
        if self._dirty and self.on_report:
            report = self.report.to_bytes()
            self.on_report(report)
            self._dirty = False
            print(f"[input] Report sent: {report.hex()}")

    def _get_absinfo(self, code):
        """Get absinfo for an axis code from cached capabilities."""
        return self._absinfo.get(code)

    def _normalize_stick(self, value, absinfo):
        """Normalize stick value from device range to -32768..32767."""
        if absinfo is None:
            # Default Xbox 360 range
            min_val, max_val = -32768, 32767
        else:
            min_val = absinfo.min
            max_val = absinfo.max

        # Map to -32768..32767
        normalized = int((value - min_val) / (max_val - min_val) * 65535 - 32768)
        return max(-32768, min(32767, normalized))

    def _normalize_trigger(self, value, absinfo):
        """Normalize trigger value from device range to 0..255."""
        if absinfo is None:
            min_val, max_val = 0, 255
        else:
            min_val = absinfo.min
            max_val = absinfo.max

        normalized = int((value - min_val) / (max_val - min_val) * 255)
        return max(0, min(255, normalized))
