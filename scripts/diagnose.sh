#!/bin/bash
# Diagnose Deck status — all key info in one SSH call.
#
# Usage:
#   scripts/diagnose.sh           # Full diagnostic
#   scripts/diagnose.sh --logs 20 # Show last 20 log lines
#   scripts/diagnose.sh --bt      # Include BT adapter state
#   scripts/diagnose.sh --input   # Include input device info
#
# This replaces the repeated pattern of 5-10 separate SSH commands
# checking service status, logs, connection state, and devices.

set -euo pipefail

# Load local configuration (not tracked by git)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$SCRIPT_DIR/../pii.env" ]; then
    source "$SCRIPT_DIR/../pii.env"
else
    echo "ERROR: pii.env not found. Copy pii.env.example to pii.env and fill in your values."
    exit 1
fi

DECK_HOST="$DECK_USER@$DECK_IP"
SSH_OPTS="-o StrictHostKeyChecking=no"
SSH_CMD="sshpass -p $DECK_PASSWORD ssh $SSH_OPTS $DECK_HOST"

LOG_LINES=10
SHOW_BT=false
SHOW_INPUT=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --logs)
            if [[ -n "${2:-}" && "$2" =~ ^[0-9]+$ ]]; then
                LOG_LINES="$2"
                shift 2
            else
                LOG_LINES=10
                shift 1
            fi
            ;;
        --bt)
            SHOW_BT=true
            shift 1
            ;;
        --input)
            SHOW_INPUT=true
            shift 1
            ;;
        *)
            shift 1
            ;;
    esac
done

echo "=========================================="
echo "  Steam Deck SC2 Diagnostics"
echo "=========================================="
echo ""

echo "--- Service Status ---"
$SSH_CMD "echo $DECK_PASSWORD | sudo -S systemctl status sc2-hogp --no-pager 2>&1 | head -10" 2>/dev/null || echo "  (not running)"
echo ""

echo "--- Last $LOG_LINES Log Lines ---"
$SSH_CMD "echo $DECK_PASSWORD | sudo -S journalctl -u sc2-hogp -n $LOG_LINES --no-pager 2>&1" 2>/dev/null
echo ""

echo "--- Connection State ---"
$SSH_CMD "bluetoothctl info C2:12:34:56:78:9A 2>/dev/null | head -8" 2>/dev/null || echo "  (no connection)"
echo ""

if [[ "$SHOW_BT" == "true" ]]; then
    echo "--- BT Adapter ---"
    $SSH_CMD "echo $DECK_PASSWORD | sudo -S btmgmt info 2>&1 | head -10" 2>/dev/null
    $SSH_CMD "bluetoothctl show 2>/dev/null | head -8" 2>/dev/null
    echo ""
fi

if [[ "$SHOW_INPUT" == "true" ]]; then
    echo "--- Input Devices ---"
    $SSH_CMD "ls /sys/class/input/ 2>/dev/null | while read d; do
        name=\$(cat /sys/class/input/\$d/device/name 2>/dev/null)
        if echo \"\$name\" | grep -qi 'controller\|steam\|gamepad\|xbox'; then
            echo \"  \$d: \$name\"
        fi
    done" 2>/dev/null
    echo ""
fi

echo "--- Processes ---"
$SSH_CMD "ps aux | grep -E 'sc2|hogp|blue' | grep -v grep 2>/dev/null" 2>/dev/null || echo "  (none)"
echo ""

echo "=========================================="
echo "  Diagnostics complete"
echo "=========================================="
