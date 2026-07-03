#!/usr/bin/env bash
# Steam wrapper: LD_AUDIT 0xbc classification patch (A/B test).
#
# Patches the PID dispatch at 0x121ba9c to write USB class (1) instead of
# BLE class (2) for PID 0x1303. Tests whether +0xbc drives vtable selection.
#
# Uses both 64-bit stub (for the 64-bit Steam parent) and 32-bit patcher
# (for the 32-bit steamclient.so process). Colon-separated in LD_AUDIT.

STEAMDIR="$(dirname "$0")"
SC2_AUDIT_LIB64="/home/philip/spoofdeck-modified/patches/sc2_gate_audit_64.so"
SC2_AUDIT_LIB32="/home/philip/spoofdeck-modified/patches/sc2_gate_audit.so"

AUDIT_PATH=""
[ -f "$SC2_AUDIT_LIB64" ] && AUDIT_PATH="$SC2_AUDIT_LIB64"
[ -f "$SC2_AUDIT_LIB32" ] && AUDIT_PATH="${AUDIT_PATH:+$AUDIT_PATH:}$SC2_AUDIT_LIB32"

if [ -n "$AUDIT_PATH" ]; then
    export LD_AUDIT="$AUDIT_PATH"
fi

# Set STEAMEXE so client.sh uses "steam" instead of basename($0) which gives "client"
export STEAMEXE=steam

exec "$STEAMDIR/client.sh" "$@"
