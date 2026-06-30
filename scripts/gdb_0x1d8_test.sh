#!/bin/bash
# GDB test: What value does [controller+0x1d8] hold when the YieldingRunTestProgram dispatcher runs?
#
# This script:
# 1. Starts Steam under GDB
# 2. Sets a breakpoint at the dispatcher (0x015675a8)
# 3. When it hits, prints [rdi+0x1d8] and [rdi+0x208]
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
DISPATCHER_OFFSET=0x015675a8
VA=$((0x$BASE + $DISPATCHER_OFFSET))
VA_HEX=$(printf "0x%x" $VA)
echo "Dispatcher virtual address: $VA_HEX"

# Also calculate the gate check address
GATE_OFFSET=0x010d4da0
GATE_VA=$((0x$BASE + $GATE_OFFSET))
GATE_HEX=$(printf "0x%x" $GATE_VA)
echo "Gate check virtual address: $GATE_HEX"

# Kill the temporary Steam process
kill $STEAM_PID 2>/dev/null
sleep 2

echo ""
echo "=== GDB Script ==="
echo "Writing GDB batch script to /tmp/gdb_0x1d8_test.gdb"

cat > /tmp/gdb_0x1d8_test.gdb << GDBEOF
# GDB script: Watch [controller+0x1d8] in YieldingRunTestProgram dispatcher
set pagination off
set confirm off
set logging file /tmp/gdb_0x1d8_log.txt
set logging overwrite on
set logging enabled on

# Breakpoint on the dispatcher entry
break *$VA_HEX
commands
  silent
  printf "=== HIT # at %p ===\n", \$rip
  printf "  [rdi+0x1d8] = %d (0x%x)\n", *(int*)(\$rdi + 0x1d8), *(int*)(\$rdi + 0x1d8)
  printf "  [rdi+0x208] = %d (0x%x)\n", *(unsigned char*)(\$rdi + 0x208), *(unsigned char*)(\$rdi + 0x208)
  printf "  [rdi+0x008] = %d\n", *(unsigned char*)(\$rdi + 0x008)
  printf "  rdi = %p\n", \$rdi
  # Also check the vtable
  printf "  [rdi+0x000] (vtable) = %p\n", *(void**)(\$rdi)
  continue
end

# Also break on the gate check to see if it's ever reached
break *$GATE_HEX
commands
  silent
  printf "=== GATE CHECK at %p ===\n", \$rip
  printf "  [r15+0x208] = %d\n", *(unsigned char*)(\$r15 + 0x208)
  printf "  r15 = %p\n", \$r15
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
