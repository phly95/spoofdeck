#!/usr/bin/env python3
"""Auto-pair with Steam Deck over BLE using pexpect.

Handles the KDE pairing dialog automatically by intercepting the
passkey confirmation prompt and answering 'yes'.

Usage:
    python3 scripts/pair.py           # Full cycle: remove → scan → pair
    python3 scripts/pair.py --connect # Just connect (skip remove)
    python3 scripts/pair.py --status  # Just check connection status

This replaces the repeated manual pattern of spawning bluetoothctl
and manually handling the Confirm passkey prompt.
"""

import pexpect
import sys
import time
import argparse

TARGET = "C2:12:34:56:78:9A"
TIMEOUT = 60


def check_status():
    """Check connection status."""
    bl = pexpect.spawn("bluetoothctl", encoding="utf-8", timeout=10)
    bl.send(f"info {TARGET}\n")
    try:
        bl.expect("Connected: yes", timeout=5)
        print(f"Connected to {TARGET}")
        bl.send("quit\n")
        bl.close()
        return True
    except pexpect.TIMEOUT:
        print(f"Not connected to {TARGET}")
        bl.send("quit\n")
        bl.close()
        return False


def auto_pair(skip_remove=False):
    """Remove, scan, connect (NOT pair — pair tries BR/EDR which tears down LE)."""
    bl = pexpect.spawn("bluetoothctl", encoding="utf-8", timeout=TIMEOUT)
    bl.logfile_read = sys.stdout

    bl.expect("bluetooth")

    if not skip_remove:
        bl.send(f"remove {TARGET}\n")
        try:
            bl.expect("has been removed", timeout=10)
        except pexpect.TIMEOUT:
            bl.expect("bluetooth", timeout=5)

    bl.send("scan on\n")
    bl.expect("bluetooth", timeout=5)

    try:
        bl.expect("Steam Controller 2026", timeout=30)
        print("\n>>> Found Steam Controller!")
    except pexpect.TIMEOUT:
        print("\n>>> Device not found in 30s, aborting")
        bl.send("quit\n")
        bl.close()
        return False

    time.sleep(3)

    # Use connect, NOT pair. pair tries BR/EDR classic which fails and
    # tears down the entire LE connection (Challenge #33).
    bl.send(f"connect {TARGET}\n")

    try:
        while True:
            idx = bl.expect(
                ["Connection successful", "ServicesResolved: yes",
                 "Failed to connect", "Already connected",
                 pexpect.TIMEOUT, pexpect.EOF],
                timeout=30,
            )
            if idx == 0:
                print("\n>>> Connection successful!")
            elif idx == 1:
                print("\n>>> ServicesResolved: yes")
                break
            elif idx == 2:
                print("\n>>> Failed to connect")
                break
            elif idx == 3:
                print("\n>>> Already connected")
                break
            elif idx == 4:
                print("\n>>> Timeout")
                break
            elif idx == 5:
                print("\n>>> EOF")
                break
    except Exception as e:
        print(f"\n>>> Exception: {e}")

    bl.send(f"info {TARGET}\n")
    bl.expect("bluetooth", timeout=10)
    bl.send("quit\n")
    bl.close()
    return True


def main():
    parser = argparse.ArgumentParser(description="Auto-pair with Steam Deck")
    parser.add_argument("--connect", action="store_true",
                        help="Skip remove, just scan and pair")
    parser.add_argument("--status", action="store_true",
                        help="Check connection status only")
    args = parser.parse_args()

    if args.status:
        sys.exit(0 if check_status() else 1)
    else:
        sys.exit(0 if auto_pair(skip_remove=args.connect) else 1)


if __name__ == "__main__":
    main()
