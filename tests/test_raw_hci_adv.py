#!/usr/bin/env python3
"""Raw HCI legacy advertising test - bypasses BlueZ entirely."""
import socket
import struct
import time
import sys

def hci_send(sock, opcode, data=b""):
    """Send HCI command and wait for event."""
    pkt = struct.pack("<BH", 0x01, opcode) + bytes([len(data)]) + data
    sock.send(pkt)
    # Read command complete/event
    sock.settimeout(2)
    try:
        resp = sock.recv(256)
        return resp
    except socket.timeout:
        return None

def main():
    print("=== Raw HCI Legacy Advertising Test ===")
    
    # Open HCI user channel (requires root)
    try:
        sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_RAW, socket.BTPROTO_HCI)
        # Bind to hci0 with HCI_CHANNEL_USER
        sock.bind((0, 1))  # (dev_id, HCI_CHANNEL_USER)
        print("[+] Opened HCI user channel on hci0")
    except PermissionError:
        print("[-] Need root for HCI user channel")
        sys.exit(1)
    except Exception as e:
        print(f"[-] Failed: {e}")
        sys.exit(1)

    # HCI command opcodes
    OGF_LE_CTL = 0x08
    LE_SET_ADV_ENABLE = (OGF_LE_CTL << 10) | 0x000A
    LE_SET_ADV_PARAMS = (OGF_LE_CTL << 10) | 0x0006
    LE_SET_ADV_DATA = (OGF_LE_CTL << 10) | 0x0008
    LE_SET_SCAN_RSP = (OGF_LE_CTL << 10) | 0x0009
    LE_SET_RANDOM_ADDR = (OGF_LE_CTL << 10) | 0x0005

    # Disable advertising first
    print("[*] Disabling advertising...")
    resp = hci_send(sock, LE_SET_ADV_ENABLE, bytes([0x00]))
    print(f"    Response: {resp.hex() if resp else 'timeout'}")

    # Set advertising parameters (legacy connectable)
    # adv_interval_min, adv_interval_max, adv_type, own_addr_type,
    # peer_addr_type, peer_addr(6), adv_channel_map, adv_filter_policy
    adv_type = 0x00  # ADV_IND (connectable, scannable)
    adv_interval = 0x00A0  # 100ms in 0.625ms units
    params = struct.pack("<HH", adv_interval, adv_interval)
    params += struct.pack("BB", adv_type, 0x00)  # type, own addr type (public)
    params += struct.pack("BB", 0x00, 0x00) * 6  # peer addr type + addr (empty)
    params += struct.pack("BBB", 0x07, 0x00, 0x00)  # chan map=all, filter=any
    print(f"[*] Setting legacy adv params (type=0x{adv_type:02x}, interval={adv_interval})...")
    resp = hci_send(sock, LE_SET_ADV_PARAMS, params)
    print(f"    Response: {resp.hex() if resp else 'timeout'}")

    # Set advertising data: Flags + Complete Name "SC2"
    name = b"SC2"
    flags_ad = bytes([0x02, 0x01, 0x06])  # len=2, type=Flags, LE General+BR/EDR Not
    name_ad = bytes([len(name) + 1, 0x09]) + name  # type=Complete Name
    adv_data = flags_ad + name_ad
    adv_data = adv_data.ljust(31, b"\x00")
    print(f"[*] Setting adv data: {adv_data.hex()}")
    resp = hci_send(sock, LE_SET_ADV_DATA, adv_data)
    print(f"    Response: {resp.hex() if resp else 'timeout'}")

    # Set scan response data: Complete Name "Steam Controller 2026"
    full_name = b"Steam Controller 2026"
    sr_name_ad = bytes([len(full_name) + 1, 0x09]) + full_name
    scan_data = sr_name_ad.ljust(31, b"\x00")
    print(f"[*] Setting scan response data...")
    resp = hci_send(sock, LE_SET_SCAN_RSP, scan_data)
    print(f"    Response: {resp.hex() if resp else 'timeout'}")

    # Enable advertising
    print("[*] Enabling legacy advertising...")
    resp = hci_send(sock, LE_SET_ADV_ENABLE, bytes([0x01]))
    status = resp[4] if resp and len(resp) > 4 else -1
    print(f"    Response: {resp.hex() if resp else 'timeout'}")
    print(f"    Status: 0x{status:02x}")

    if status == 0:
        print("[+] LEGACY ADVERTISING IS ACTIVE!")
        print("[+] Host PC should now see address <DECK_BT_MAC_PUBLIC>")
        print("[*] Waiting 15 seconds for host to scan...")
        time.sleep(15)
        
        # Disable
        print("[*] Disabling advertising...")
        hci_send(sock, LE_SET_ADV_ENABLE, bytes([0x00]))
        print("[+] Done")
    else:
        print(f"[-] Failed to enable (status 0x{status:02x})")
        print("[*] Trying extended advertising path...")
        
        # Try LE Set Extended Advertising Parameters
        LE_SET_EXT_ADV_PARAMS = (OGF_LE_CTL << 10) | 0x0036
        LE_SET_EXT_ADV_DATA = (OGF_LE_CTL << 10) | 0x0037
        LE_SET_EXT_ADV_ENABLE = (OGF_LE_CTL << 10) | 0x0039
        
        # Extended params: handle=1, legacy flag set, connectable
        ext_params = bytes([0x01])  # adv handle
        ext_params += struct.pack("<H", 0x0060)  # event_properties: legacy + connectable
        ext_params += struct.pack("<HH", 0x00A0, 0x00A0)  # intervals
        ext_params += struct.pack("BB", 0x00, 0x00)  # own addr, peer addr type
        ext_params += b"\x00" * 6  # peer addr
        ext_params += struct.pack("<BBb", 0x07, 0x00, 0x7F)  # chan map, filter, tx power
        
        resp = hci_send(sock, LE_SET_EXT_ADV_PARAMS, ext_params)
        print(f"    Ext Adv Params: {resp.hex() if resp else 'timeout'}")
        
        # Set extended adv data
        ext_data = bytes([0x01])  # adv handle
        ext_data += bytes([0x00])  # operation: intermediate
        ext_data += bytes([len(adv_data)])  # fragment preference
        ext_data += adv_data
        
        resp = hci_send(sock, LE_SET_EXT_ADV_DATA, ext_data)
        print(f"    Ext Adv Data: {resp.hex() if resp else 'timeout'}")
        
        # Enable extended advertising
        ext_enable = bytes([0x01])  # enable
        ext_enable += bytes([0x01])  # num instances
        ext_enable += bytes([0x01])  # adv handle
        ext_enable += struct.pack("<H", 0x0000)  # duration (0 = forever)
        ext_enable += bytes([0x00])  # max events
        
        resp = hci_send(sock, LE_SET_EXT_ADV_ENABLE, ext_enable)
        ext_status = resp[4] if resp and len(resp) > 4 else -1
        print(f"    Ext Adv Enable: status=0x{ext_status:02x}")
        
        if ext_status == 0:
            print("[+] EXTENDED advertising enabled (legacy flag)!")
            print("[*] Waiting 15 seconds...")
            time.sleep(15)
            hci_send(sock, LE_SET_EXT_ADV_ENABLE, bytes([0x00, 0x01, 0x01, 0x00, 0x00, 0x00]))
            print("[+] Done")
        else:
            print("[-] Extended advertising also failed")

    sock.close()

if __name__ == "__main__":
    main()
