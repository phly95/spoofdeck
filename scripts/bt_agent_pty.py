#!/usr/bin/env python3
import os
import pty
import sys
import time

print("[*] Spawning bluetoothctl in pseudo-terminal...")
pid, fd = pty.fork()
if pid == 0:
    # Child process: run bluetoothctl
    os.execvp("bluetoothctl", ["bluetoothctl"])
else:
    # Parent process: interact with bluetoothctl
    time.sleep(1.5)
    
    print("[*] Sending agent registration commands...")
    os.write(fd, b"agent NoInputNoOutput\n")
    time.sleep(0.5)
    os.write(fd, b"default-agent\n")
    time.sleep(0.5)
    
    # Forward output to stdout and auto-confirm pairing requests
    print("[+] Agent ready. Monitoring output...")
    while True:
        try:
            data = os.read(fd, 1024)
            if not data:
                break
            text = data.decode("utf-8", errors="ignore")
            sys.stdout.write(text)
            sys.stdout.flush()
            
            # Detect confirmation prompts and auto-respond "yes"
            if "Confirm passkey" in text or "(yes/no):" in text:
                print("\n[+] Auto-confirming passkey...")
                os.write(fd, b"yes\n")
            elif "Authorize service" in text:
                print("\n[+] Auto-authorizing service...")
                os.write(fd, b"yes\n")
        except OSError:
            break
