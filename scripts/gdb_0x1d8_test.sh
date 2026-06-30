#!/bin/bash
# GDB test: What value does [controller+0x1d8] hold when the YieldingRunTestProgram dispatcher runs?
#
# NOTE: This script targets the 32-bit binary (ubuntu12_32/steamclient.so).
# 64-bit equivalents: rdi → edi, r15 → esi, 0x208 → 0x17c
#
# This script:
# 1. Starts Steam under GDB
# 2. Sets a breakpoint at the dispatcher
# 3. When it hits, prints [edi+0x1d8] and [esi+0x17c]
# 4. Logs all hits to /tmp/gdb_0x1d8_log.txt
#
# Usage: Run this script, then connect the Deck's BLE device.

source /home/philip/spoofdeck-modified/pii.env

echo "=== GDB Test: [controller+0x1d8] Value ==="
echo ""

# Step 1: Find steamclient.so in a running Steam process (if any)
STEAM_PID=$(pgrep -f "steam" | head -1)
if [ -n "$STEAM_PID" ]; then
    echo "Found existing Steam process (PID: $STEAM_PID). Killing it..."
    kill $STEAM_PID 2>/dev/null
    sleep 2
fi

# Step 2: Start Steam briefly to find steamclient.so base address
echo "Starting Steam briefly to find steamclient.so base address..."
steam &
STEAM_PID=$!
sleep 5

# Find steamclient.so base address
MAPS=$(cat /proc/$STEAM_PID/maps 2>/dev/null | grep "steamclient.so" | head -1)
if [ -z "$MAPS" ]; then
    echo "ERROR: Could not find steamclient.so in process maps"
    echo "Trying alternative method..."
    # Try finding it in the steam process tree
    STEAM_PID=$(pgrep -f "steam" | head -1)
    MAPS=$(cat /proc/$STEAM_PID/maps 2>/dev/null | grep "steamclient.so" | head -1)
fi

if [ -z "$MAPS" ]; then
    echo "ERROR: Still could not find steamclient.so"
    echo "Available maps:"
    cat /proc/$STEAM_PID/maps 2>/dev/null | head -20
    kill $STEAM_PID 2>/dev/null
    exit 1
fi

BASE=$(echo "$MAPS" | awk '{print $1}' | cut -d'-' -f1)
echo "steamclient.so base: 0x$BASE"

# Calculate virtual address for the dispatcher
# NOTE: 64-bit offset was 0x015675a8 — must find 32-bit equivalent via GDB/string search
DISPATCHER_OFFSET=0x015675a8  # [NEEDS RE-ANALYSIS] — placeholder, find via: info functions YieldingRunTestProgram
VA=$((0x$BASE + $DISPATCHER_OFFSET))
VA_HEX=$(printf "0x%x" $VA)
echo "Dispatcher virtual address: $VA_HEX (offset: 0x$(printf '%x' $DISPATCHER_OFFSET)) [NEEDS RE-ANALYSIS for 32-bit]"

# Also calculate the gate check address
# NOTE: 64-bit offset was 0x010d4da0 — 0x208 offset becomes 0x17c in 32-bit (esi+0x17c)
GATE_OFFSET=0x010d4da0  # [NEEDS RE-ANALYSIS] — placeholder, find via breakpoint on 0x8F dispatch
GATE_VA=$((0x$BASE + $GATE_OFFSET))
GATE_HEX=$(printf "0x%x" $GATE_VA)
echo "Gate check virtual address: $GATE_HEX (offset: 0x$(printf '%x' $GATE_OFFSET)) [NEEDS RE-ANALYSIS for 32-bit]"

# Kill the temporary Steam process
kill $STEAM_PID 2>/dev/null
sleep 2

echo ""
echo "=== GDB Script ==="
echo "Writing GDB batch script to /tmp/gdb_0x1d8_test.gdb"

cat > /tmp/gdb_0x1d8_test.gdb << GDBEOF
# GDB script: Watch [controller+0x1d8] in YieldingRunTestProgram dispatcher
# NOTE: 32-bit registers (edi, esi) instead of 64-bit (rdi, r15)
# NOTE: 0x208 gate offset becomes 0x17c in 32-bit (esi+0x17c)
set pagination off
set confirm off
set logging file /tmp/gdb_0x1d8_log.txt
set logging overwrite on
set logging enabled on

# Breakpoint on the dispatcher entry
# NOTE: $VA_HEX is placeholder — replace with actual 32-bit address after RE
break *$VA_HEX
commands
  silent
  printf "=== HIT # at %p ===\n", \$eip
  printf "  [edi+0x1d8] = %d (0x%x)\n", *(int*)(\$edi + 0x1d8), *(int*)(\$edi + 0x1d8)
  printf "  [esi+0x17c] = %d (0x%x) [gate: was [r15+0x208] in 64-bit]\n", *(unsigned char*)(\$esi + 0x17c), *(unsigned char*)(\$esi + 0x17c)
  printf "  [edi+0x008] = %d\n", *(unsigned char*)(\$edi + 0x008)
  printf "  edi = %p (controller obj)\n", \$edi
  printf "  esi = %p (was r15 in 64-bit)\n", \$esi
  # Also check the vtable
  printf "  [edi+0x000] (vtable) = %p\n", *(void**)(\$edi)
  continue
end

# Also break on the gate check to see if it's ever reached
# NOTE: $GATE_HEX is placeholder — replace with actual 32-bit address after RE
break *$GATE_HEX
commands
  silent
  printf "=== GATE CHECK at %p ===\n", \$eip
  printf "  [esi+0x17c] = %d [was r15+0x208 in 64-bit]\n", *(unsigned char*)(\$esi + 0x17c)
  printf "  esi = %p\n", \$esi
  continue
end

echo "Starting Steam under GDB..."
echo "When Steam starts, connect the Deck BLE device."
echo "Breakpoints will log to /tmp/gdb_0x1d8_log.txt"
echo ""
run
GDBEOF

echo ""
echo "=== Instructions ==="
echo "1. Run: gdb -x /tmp/gdb_0x1d8_test.gdb --args steam"
echo "2. When Steam starts, connect the Deck BLE device"
echo "3. Check /tmp/gdb_0x1d8_log.txt for results"
echo ""
echo "Or run this one-liner:"
echo "  gdb -batch -x /tmp/gdb_0x1d8_test.gdb --args steam 2>&1 | tee /tmp/gdb_output.txt"
echo ""
echo "The dispatcher virtual address is: $VA_HEX"
echo "The gate check virtual address is: $GATE_HEX"
