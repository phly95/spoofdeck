#!/bin/bash
# Setup script for Steam Deck SC2 BLE Spoof
#
# This script:
# 1. Disables steamos-readonly
# 2. Installs D-Bus policy file
# 3. Restarts D-Bus
# 4. Re-enables steamos-readonly
# 5. Clones and patches steamdeck-bt-controller-emulator
#
# Run as root: echo '<password>' | sudo -S scripts/setup.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DBUS_POLICY_SRC="$PROJECT_DIR/dbus-config/com.steamdeck.hogp.conf"
DBUS_POLICY_DST="/etc/dbus-1/system.d/com.steamdeck.hogp.conf"
EMULATOR_REPO="https://github.com/ObKoro/steamdeck-bt-controller-emulator"
EMULATOR_DIR="$HOME/steamdeck-bt-controller-emulator"

echo "=== Steam Deck SC2 BLE Spoof Setup ==="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "[-] This script must be run as root."
    echo "    Use: echo '<password>' | sudo -S $0"
    exit 1
fi

# Step 1: Disable steamos-readonly
echo "[1/5] Disabling steamos-readonly..."
if command -v steamos-readonly &> /dev/null; then
    steamos-readonly disable
    echo "  [OK] steamos-readonly disabled"
else
    echo "  [SKIP] steamos-readonly not found (not SteamOS?)"
fi

# Step 2: Install D-Bus policy file
echo ""
echo "[2/5] Installing D-Bus policy file..."
if [ -f "$DBUS_POLICY_SRC" ]; then
    cp "$DBUS_POLICY_SRC" "$DBUS_POLICY_DST"
    chmod 644 "$DBUS_POLICY_DST"
    echo "  [OK] Policy file installed at $DBUS_POLICY_DST"
else
    echo "  [ERROR] Policy file not found at $DBUS_POLICY_SRC"
    exit 1
fi

# Step 3: Restart D-Bus
echo ""
echo "[3/5] Restarting D-Bus..."
if command -v systemctl &> /dev/null; then
    systemctl restart dbus
    echo "  [OK] D-Bus restarted"
else
    echo "  [SKIP] systemctl not available"
    echo "  Please restart D-Bus manually: sudo systemctl restart dbus"
fi

# Step 4: Re-enable steamos-readonly
echo ""
echo "[4/5] Re-enabling steamos-readonly..."
if command -v steamos-readonly &> /dev/null; then
    steamos-readonly enable
    echo "  [OK] steamos-readonly re-enabled"
else
    echo "  [SKIP] steamos-readonly not found"
fi

# Step 5: Clone and patch steamdeck-bt-controller-emulator
echo ""
echo "[5/5] Setting up steamdeck-bt-controller-emulator..."
if [ -d "$EMULATOR_DIR" ]; then
    echo "  [SKIP] Repository already cloned at $EMULATOR_DIR"
else
    echo "  Cloning repository..."
    git clone "$EMULATOR_REPO" "$EMULATOR_DIR"
    echo "  [OK] Repository cloned"
fi

# Apply patch
if [ -f "$EMULATOR_DIR/steamdeck_bt_controller_emulator/main.py" ]; then
    PATCH_FILE="$PROJECT_DIR/patches/check_static_addr.patch"
    if [ -f "$PATCH_FILE" ]; then
        echo "  Applying patch..."
        cd "$EMULATOR_DIR"
        # Check if patch is already applied
        if grep -q "PATCHED: Always return True" steamdeck_bt_controller_emulator/main.py 2>/dev/null; then
            echo "  [SKIP] Patch already applied"
        else
            # Apply the patch manually
            python3 -c "
import re

with open('steamdeck_bt_controller_emulator/main.py', 'r') as f:
    content = f.read()

old_func = '''def check_static_address_set():
    \"\"\"Check if the static BLE address is set.\"\"\"
    result = subprocess.run(
        [\"sudo\", \"btmgmt\", \"info\"],
        capture_output=True,
        text=True,
    )
    return \"StaticAddress\" in result.stdout'''

new_func = '''def check_static_address_set():
    \"\"\"Check if the static BLE address is set.

    PATCHED: Always return True to avoid btmgmt sudo issues.
    The static address must be set manually before running the emulator.
    Use: sudo btmgmt -> power off -> static-addr <DECK_BT_MAC_PUBLIC> -> power on -> le on
    \"\"\"
    return True'''

content = content.replace(old_func, new_func)

with open('steamdeck_bt_controller_emulator/main.py', 'w') as f:
    f.write(content)
"
            echo "  [OK] Patch applied"
        fi
        cd "$PROJECT_DIR"
    else
        echo "  [WARN] Patch file not found at $PATCH_FILE"
    fi
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Set static BLE address:"
echo "     sudo btmgmt"
echo "     power off"
echo "     static-addr <DECK_BT_MAC_PUBLIC>"
echo "     power on"
echo "     le on"
echo "     quit"
echo ""
echo "  2. Start the GATT server:"
echo "     python3 src/main.py --adapter hci0 --address <DECK_BT_MAC_PUBLIC>"
echo ""
echo "  3. Connect from host PC Steam Client"
echo ""
