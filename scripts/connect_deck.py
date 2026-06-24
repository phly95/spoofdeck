#!/usr/bin/env python3
"""Connect to SteamDeckHoG via BLE - robust version."""
import subprocess
import time
import select
import os
import re

TARGET = "C2:12:34:56:78:9A"

proc = subprocess.Popen(
    ["bluetoothctl"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    bufsize=0,
)
fd = proc.stdout.fileno()

def send(cmd):
    proc.stdin.write((cmd + "\n").encode())
    proc.stdin.flush()

def read_output(timeout=3):
    out = b""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r, _, _ = select.select([fd], [], [], min(0.5, deadline - time.time()))
        if r:
            try:
                data = os.read(fd, 4096)
                if data:
                    out += data
                else:
                    break
            except OSError:
                break
        elif out:
            break
    return out.decode(errors="replace")

def strip_ansi(text):
    return re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)

# Startup
time.sleep(1)
read_output(1)

# Clean power cycle
send("power off")
read_output(2)
time.sleep(2)
send("power on")
read_output(3)

# Register agent
send("agent NoInputNoOutput")
read_output(1)
send("default-agent")
read_output(1)

# Scan
print("=== Scanning ===")
send("scan on")

# Wait for device
found = False
for i in range(30):
    out = read_output(1)
    if f"[NEW] Device {TARGET}" in out:
        print(f"  Found {TARGET} after {i+1}s")
        found = True
        time.sleep(2)  # Let device fully register in BlueZ
        break

if not found:
    print("  Device not found. Aborting.")
    send("quit")
    proc.wait(timeout=5)
    exit(1)

# Stop scan
send("scan off")
read_output(1)

# Connect
print(f"\n=== Connecting ===")
send(f"connect {TARGET}")

# Monitor for 30s
deadline = time.time() + 30
while time.time() < deadline:
    out = read_output(1)
    if out:
        clean = strip_ansi(out)
        for line in clean.split("\n"):
            line = line.strip()
            if not line:
                continue
            # Print significant events
            if any(kw in line for kw in [
                "Connected:", "Paired:", "Bonded:", "Services",
                "Request", "Confirm", "HID", "hidraw", "error",
                "Error", "Failed", "Connection successful",
                "attempting", "Attempting"
            ]):
                print(f"  {line}")

# Final check
print("\n=== Final state ===")
send(f"info {TARGET}")
info = strip_ansi(read_output(2))
for line in info.split("\n"):
    line = line.strip()
    if any(kw in line for kw in ["Paired", "Bonded", "Connected", "Services", "UUID"]):
        print(f"  {line}")

# Check hidraw
result = subprocess.run(["ls", "-la", "/dev/hidraw*"], capture_output=True, text=True)
print(f"\n=== /dev/hidraw ===")
print(result.stdout if result.stdout else f"  {result.stderr.strip()}")

send("quit")
proc.wait(timeout=5)
