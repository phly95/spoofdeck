#!/usr/bin/env bash
# Steam wrapper that applies the SC2 0x8F haptic gate patch via LD_AUDIT.
#
# Install:
#   cp ~/.steam/debian-installation/steam.sh ~/.steam/debian-installation/client.sh
#   cp patches/steam_audit_wrapper.sh ~/.steam/debian-installation/steam.sh
#   chmod +x ~/.steam/debian-installation/steam.sh
#
# Uninstall:
#   cp ~/.steam/debian-installation/client.sh ~/.steam/debian-installation/steam.sh

STEAMDIR="$(dirname "$0")"
SC2_AUDIT_LIB="/home/philip/spoofdeck-modified/patches/sc2_gate_audit.so"

if [ -f "$SC2_AUDIT_LIB" ]; then
    export LD_AUDIT="$SC2_AUDIT_LIB"
fi

# exec -a sets $0 so client.sh sees itself as "steam.sh"
exec -a steam.sh "$STEAMDIR/client.sh" "$@"
