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


# SC2 Button bitmask (32-bit)
SC2_BUTTON_A         = 0x00000001
SC2_BUTTON_B         = 0x00000002
SC2_BUTTON_X         = 0x00000004
SC2_BUTTON_Y         = 0x00000008
SC2_BUTTON_LB        = 0x00000010
SC2_BUTTON_RB        = 0x00000020
SC2_BUTTON_LGRIP     = 0x00000040
SC2_BUTTON_RGRIP     = 0x00000080
SC2_BUTTON_START     = 0x00000100
SC2_BUTTON_STEAM     = 0x00000200
SC2_BUTTON_LPAD_CLICK = 0x00000400
SC2_BUTTON_RPAD_CLICK = 0x00000800
SC2_BUTTON_LSTICK    = 0x00001000
SC2_BUTTON_RSTICK    = 0x00002000
SC2_BUTTON_DPAD_UP   = 0x00004000
SC2_BUTTON_DPAD_DOWN = 0x00008000
SC2_BUTTON_DPAD_LEFT = 0x00010000
SC2_BUTTON_DPAD_RIGHT = 0x00020000
SC2_BUTTON_LPAD_TOUCH = 0x00400000
SC2_BUTTON_RPAD_TOUCH = 0x00800000

# Xbox 360 → SC2 button mapping
XBOX_TO_SC2_BUTTON = {
    ecodes.BTN_SOUTH:  SC2_BUTTON_A,           # A
    ecodes.BTN_EAST:   SC2_BUTTON_B,           # B
    ecodes.BTN_NORTH:  SC2_BUTTON_X,           # X
    ecodes.BTN_WEST:   SC2_BUTTON_Y,           # Y
    ecodes.BTN_TL:     SC2_BUTTON_LB,          # Left Bumper
    ecodes.BTN_TR:     SC2_BUTTON_RB,          # Right Bumper
    ecodes.BTN_SELECT: SC2_BUTTON_START,       # Start (mapped from Select)
    ecodes.BTN_START:  SC2_BUTTON_STEAM,       # Steam (mapped from Start)
    ecodes.BTN_MODE:   SC2_BUTTON_STEAM,       # Guide → Steam
    ecodes.BTN_THUMBL: SC2_BUTTON_LSTICK,      # Left Stick Click
    ecodes.BTN_THUMBR: SC2_BUTTON_RSTICK,      # Right Stick Click
}

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
    """Builds SC2-format input reports (Report ID 0x45)."""

    def __init__(self):
        self.seq = 0
        self.buttons = 0
        self.left_trigger = 0
        self.right_trigger = 0
        self.lx = 0
        self.ly = 0
        self.rx = 0
        self.ry = 0
        self.lpad_x = 0
        self.lpad_y = 0
        self.rpad_x = 0
        self.rpad_y = 0

    def to_bytes(self):
        """Convert to 48-byte report."""
        report = bytearray(48)
        report[0] = 0x45  # Report ID
        report[1] = self.seq & 0xFF  # Sequence number

        # Buttons (32-bit LE)
        struct.pack_into("<I", report, 2, self.buttons)

        # Triggers
        report[6] = self.left_trigger
        report[7] = self.right_trigger

        # Sticks (signed 16-bit LE)
        struct.pack_into("<h", report, 8, self.lx)
        struct.pack_into("<h", report, 10, self.ly)
        struct.pack_into("<h", report, 12, self.rx)
        struct.pack_into("<h", report, 14, self.ry)

        # Trackpads (mapped from sticks when no trackpad present)
        struct.pack_into("<h", report, 16, self.lpad_x)
        struct.pack_into("<h", report, 18, self.lpad_y)
        struct.pack_into("<h", report, 20, self.rpad_x)
        struct.pack_into("<h", report, 22, self.rpad_y)

        # IMU data left as zeros (no IMU forwarding yet)

        self.seq = (self.seq + 1) & 0xFF
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
            for event in self.device.read_loop():
                if not self._running:
                    break
                self._handle_event(event)
        except Exception as e:
            if self._running:
                print(f"[-] Input read error: {e}")

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
            # Left stick X: normalize from device range to -32768..32767
            self.report.lx = self._normalize_stick(value, self.device.capabilities(verbose=False).get(ecodes.EV_ABS, {}).get(code))
        elif code == ABS_Y:
            self.report.ly = self._normalize_stick(value, self.device.capabilities(verbose=False).get(ecodes.EV_ABS, {}).get(code))
        elif code == ABS_RX:
            self.report.rx = self._normalize_stick(value, self.device.capabilities(verbose=False).get(ecodes.EV_ABS, {}).get(code))
        elif code == ABS_RY:
            self.report.ry = self._normalize_stick(value, self.device.capabilities(verbose=False).get(ecodes.EV_ABS, {}).get(code))
        elif code == ABS_Z:
            # Left trigger
            self.report.left_trigger = self._normalize_trigger(value, self.device.capabilities(verbose=False).get(ecodes.EV_ABS, {}).get(code))
        elif code == ABS_RZ:
            # Right trigger
            self.report.right_trigger = self._normalize_trigger(value, self.device.capabilities(verbose=False).get(ecodes.EV_ABS, {}).get(code))
        elif code == ABS_HAT0X:
            # D-pad X
            if value < 0:
                self.report.buttons |= SC2_BUTTON_DPAD_LEFT
                self.report.buttons &= ~SC2_BUTTON_DPAD_RIGHT
            elif value > 0:
                self.report.buttons |= SC2_BUTTON_DPAD_RIGHT
                self.report.buttons &= ~SC2_BUTTON_DPAD_LEFT
            else:
                self.report.buttons &= ~(SC2_BUTTON_DPAD_LEFT | SC2_BUTTON_DPAD_RIGHT)
        elif code == ABS_HAT0Y:
            # D-pad Y
            if value < 0:
                self.report.buttons |= SC2_BUTTON_DPAD_UP
                self.report.buttons &= ~SC2_BUTTON_DPAD_DOWN
            elif value > 0:
                self.report.buttons |= SC2_BUTTON_DPAD_DOWN
                self.report.buttons &= ~SC2_BUTTON_DPAD_UP
            else:
                self.report.buttons &= ~(SC2_BUTTON_DPAD_UP | SC2_BUTTON_DPAD_DOWN)

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
            self.on_report(self.report.to_bytes())
            self._dirty = False

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
