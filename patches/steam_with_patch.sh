#!/bin/sh
# Launch Steam with the 0x8F gate patch applied.
# The patch makes the haptic gate unconditional so BLE controllers
# get Steam-generated haptics (trackpad clicks, UI feedback).
export LD_PRELOAD="/home/philip/spoofdeck-modified/patches/sc2_gate_patch.so ${LD_PRELOAD:-}"
exec /usr/games/steam "$@"
