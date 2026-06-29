#!/bin/bash
# Test UHID output path by writing a haptic report to /dev/hidrawN
# Usage: sudo bash test_haptic_write.sh [hidrawN]
#
# This writes a 10-byte haptic rumble report (Report ID 0x80) to the
# specified hidraw device. If the UHID output path works, BlueZ's
# forward_report() should forward this to the BLE device.

HIDRAW="${1:-/dev/hidraw0}"
REPORT_ID=0x80
TYPE=0x00
INTENSITY_LO=0x00
INTENSITY_HI=0x00
LEFT_SPEED_LO=0xFF
LEFT_SPEED_HI=0x00
LEFT_GAIN=0x00
RIGHT_SPEED_LO=0xFF
RIGHT_SPEED_HI=0x00
RIGHT_GAIN=0x00

echo "Testing UHID output path on $HIDRAW"
echo "Writing haptic rumble: left=255, right=255"

# Write the report using Python (hexlify for exact byte control)
printf 'qwerasdf\n' | sudo -S python3 -c "
import os, sys
# Report ID 0x80 + 9 bytes payload = 10 bytes total
report = bytes([
    0x80,  # Report ID
    0x00,  # type (HAPTIC_TYPE_RUMBLE)
    0x00, 0x00,  # intensity (uint16 LE)
    0xFF, 0x00,  # left.speed (uint16 LE) = 255
    0x00,        # left.gain (int8)
    0xFF, 0x00,  # right.speed (uint16 LE) = 255
    0x00,        # right.gain (int8)
])
print(f'Writing {len(report)} bytes to $HIDRAW: {report.hex()}')
try:
    fd = os.open('$HIDRAW', os.O_WRONLY)
    os.write(fd, report)
    os.close(fd)
    print('Write succeeded!')
except Exception as e:
    print(f'Write failed: {e}')
    sys.exit(1)
"
