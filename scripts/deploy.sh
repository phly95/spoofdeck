#!/bin/bash
# Deploy source files to Deck and restart sc2-hogp service.
#
# Usage:
#   scripts/deploy.sh              # Deploy all source files
#   scripts/deploy.sh main_l2cap   # Deploy only one file
#   scripts/deploy.sh --no-restart # Deploy without restarting service
#
# This replaces the repeated manual pattern:
#   sshpass scp ... && sshpass ssh ... systemctl restart sc2-hogp

set -euo pipefail

DECK_HOST="deck@<DECK_IP>"
SSH_OPTS="-o StrictHostKeyChecking=no"
DECK_DIR="/tmp/sc2-spoof/src"
LOCAL_DIR="$(cd "$(dirname "$0")/../src" && pwd)"

# Parse arguments
NO_RESTART=false
FILE_FILTER=""
for arg in "$@"; do
    case "$arg" in
        --no-restart) NO_RESTART=true ;;
        *) FILE_FILTER="$arg" ;;
    esac
done

# Source files to deploy
FILES=(main_l2cap.py att_server.py gatt_db.py input_handler.py agent.py adv.py bluez.py)

echo "=== Deploying to Deck ==="

deployed=0
for f in "${FILES[@]}"; do
    if [[ -n "$FILE_FILTER" && "$f" != *"$FILE_FILTER"* ]]; then
        continue
    fi
    src="$LOCAL_DIR/$f"
    if [[ -f "$src" ]]; then
        echo "  SCP: $f"
        sshpass -p '<DECK_PASSWORD>' scp $SSH_OPTS "$src" "$DECK_HOST:$DECK_DIR/$f"
        deployed=$((deployed + 1))
    fi
done

if [[ $deployed -eq 0 ]]; then
    echo "[-] No files matched '$FILE_FILTER'"
    exit 1
fi

echo "[+] Deployed $deployed file(s)"

if [[ "$NO_RESTART" == "false" ]]; then
    echo "=== Restarting sc2-hogp ==="
    sshpass -p '<DECK_PASSWORD>' ssh $SSH_OPTS "$DECK_HOST" \
        "echo <DECK_PASSWORD> | sudo -S systemctl restart sc2-hogp 2>&1; \
         sleep 2; \
         echo <DECK_PASSWORD> | sudo -S journalctl -u sc2-hogp -n 5 --no-pager 2>&1"
    echo "[+] Service restarted"
fi
