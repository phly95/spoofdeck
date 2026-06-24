#!/usr/bin/env python3
"""Management API advertising test - uses the BlueZ Management socket."""
import socket
import struct
import time
import sys
import os

# Management API opcodes
MGMT_OP_SET_POWERED = 0x0005
MGMT_OP_SET_CONNECTABLE = 0x000C
MGMT_OP_SET_ADVERTISING = 0x003E
MGMT_OP_SET_ADV_DATA = 0x003F
MGMT_OP_SET_SCAN_RSP = 0x0040
MGMT_OP_SET_LE = 0x0017
MGMT_INDEX_NONE = 0xFFFF

def mgmt_send(sock, opcode, data=b"", index=0):
    """Send Management API command and wait for response."""
    hdr = struct.pack("<HHI", len(data) + 6, opcode, index)
    sock.send(hdr + data)
    sock.settimeout(3)
    try:
        resp = sock.recv(1024)
        if len(resp) >= 6:
            plen, popcode, pindex = struct.unpack("<HHI", resp[:6])
            status = resp[6] if len(resp) > 7 else -1
            return popcode, status, resp
        return None, -1, resp
    except socket.timeout:
        return None, -1, None

def main():
    print("=== Management API Advertising Test ===")
    
    # Open Management socket
    try:
        sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_RAW, socket.BTPROTO_HCI)
        # Try binding to HCI channel MANAGEMENT (11)
        try:
            sock.bind((0, 11))
            print("[+] Bound to HCI channel MANAGEMENT")
        except Exception:
            try:
                sock.bind((0,))
                print("[+] Bound to hci0")
            except Exception as e:
                print(f"[-] Bind failed: {e}")
                sys.exit(1)
    except Exception as e:
        print(f"[-] Socket failed: {e}")
        sys.exit(1)

    # Step 1: Set LE mode
    print("[*] Setting LE mode...")
    opcode, status, resp = mgmt_send(sock, MGMT_OP_SET_LE, bytes([0x01]))
    print(f"    opcode=0x{opcode:04x} status=0x{status:02x}")

    # Step 2: Set Powered
    print("[*] Setting Powered on...")
    opcode, status, resp = mgmt_send(sock, MGMT_OP_SET_POWERED, bytes([0x01]))
    print(f"    opcode=0x{opcode:04x} status=0x{status:02x}")

    # Step 3: Set Connectable
    print("[*] Setting Connectable...")
    opcode, status, resp = mgmt_send(sock, MGMT_OP_SET_CONNECTABLE, bytes([0x01]))
    print(f"    opcode=0x{opcode:04x} status=0x{status:02x}")

    # Step 4: Set Advertising on
    print("[*] Setting Advertising on...")
    opcode, status, resp = mgmt_send(sock, MGMT_OP_SET_ADVERTISING, bytes([0x01]))
    print(f"    opcode=0x{opcode:04x} status=0x{status:02x}")

    # Step 5: Set Advertising Data (legacy format)
    # adv_data format: length + ad_type + data
    name = b"SC2"
    flags_ad = bytes([0x02, 0x01, 0x06])  # Flags: LE General Disc + BR/EDR Not
    name_ad = bytes([len(name) + 1, 0x09]) + name  # Complete Local Name
    adv_data = flags_ad + name_ad
    adv_data = adv_data.ljust(31, b"\x00")
    
    # MGMT_SET_ADV_DATA format: (2 bytes flags?) + adv_data(31) + scan_rsp(31)
    scan_data = b"\x00" * 31
    mgmt_adv = adv_data + scan_data
    
    print(f"[*] Setting adv data: {adv_data[:len(flags_ad)+len(name_ad)].hex()}")
    opcode, status, resp = mgmt_send(sock, MGMT_OP_SET_ADV_DATA, mgmt_adv)
    print(f"    opcode=0x{opcode:04x} status=0x{status:02x}")
    if resp:
        print(f"    resp: {resp[:20].hex()}")

    # Check final state
    print("\n[*] Waiting 10s for advertising...")
    time.sleep(10)
    
    # Disable
    print("[*] Disabling advertising...")
    opcode, status, resp = mgmt_send(sock, MGMT_OP_SET_ADVERTISING, bytes([0x00]))
    print(f"    opcode=0x{opcode:04x} status=0x{status:02x}")
    
    sock.close()
    print("[+] Done")

if __name__ == "__main__":
    main()
