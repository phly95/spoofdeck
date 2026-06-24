#!/usr/bin/env python3
"""Configure BT adapter via btmgmt PTY interaction."""
import pty
import os
import time
import select
import re


def run_btmgmt_commands(commands):
    """Run btmgmt commands using PTY."""
    pid, fd = pty.fork()
    if pid == 0:
        os.execvp("btmgmt", ["btmgmt", "--index", "0"])
        os._exit(1)

    output = ""

    # Wait for initial prompt
    time.sleep(1)
    while select.select([fd], [], [], 0.5)[0]:
        try:
            data = os.read(fd, 4096)
            output += data.decode(errors="replace")
        except OSError:
            break

    # Send commands one by one
    for cmd in commands:
        print(f"  Sending: {cmd}")
        os.write(fd, (cmd + "\n").encode())
        time.sleep(1.5)
        while select.select([fd], [], [], 0.5)[0]:
            try:
                data = os.read(fd, 4096)
                output += data.decode(errors="replace")
            except OSError:
                break

    # Quit
    os.write(fd, b"quit\n")
    time.sleep(0.5)
    try:
        while select.select([fd], [], [], 0.2)[0]:
            data = os.read(fd, 4096)
            output += data.decode(errors="replace")
    except OSError:
        pass

    os.waitpid(pid, 0)
    return output


if __name__ == "__main__":
    print("Configuring BT adapter...")
    output = run_btmgmt_commands([
        "power off",
        "bredr off",
        "static-addr C2:12:34:56:78:9A",
        "power on",
    ])
    clean = re.sub(r'\x1b\[[0-9;]*m', '', output)
    print("btmgmt output:")
    print(clean)
