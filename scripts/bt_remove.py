#!/usr/bin/env python3
"""Remove a bonded Bluetooth device via bluetoothctl PTY."""
import pty
import os
import time
import select
import re
import sys


def main():
    pid, fd = pty.fork()
    if pid == 0:
        os.execvp("bluetoothctl", ["bluetoothctl"])
        os._exit(1)

    output = ""
    time.sleep(1)
    while select.select([fd], [], [], 0.5)[0]:
        try:
            data = os.read(fd, 4096)
            output += data.decode(errors="replace")
        except OSError:
            break

    # Remove the device
    addr = sys.argv[1] if len(sys.argv) > 1 else "<HOST_BT_MAC>"
    os.write(fd, ("remove " + addr + "\n").encode())
    time.sleep(2)
    while select.select([fd], [], [], 0.5)[0]:
        try:
            data = os.read(fd, 4096)
            output += data.decode(errors="replace")
        except OSError:
            break

    os.write(fd, b"quit\n")
    time.sleep(0.5)
    os.waitpid(pid, 0)
    print(re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', output))


if __name__ == "__main__":
    main()
