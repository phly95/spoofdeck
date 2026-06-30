⚠️ DISCLAIMER: PARTIALLY CONVERTED — MIXED 32/64-BIT ADDRESSES

Some addresses in this file have been converted to 32-bit equivalents.
Others are still from the 64-bit binary and are INVALID for the running process.

  64-bit binary: ~/.steam/debian-installation/linux64/steamclient.so (46MB, x86_64)
  32-bit binary: ~/.steam/debian-installation/ubuntu12_32/steamclient.so (49MB, i386)

Addresses tagged [32-bit: NEEDS RE-ANALYSIS] are converted but unverified.
Addresses without this tag are still 64-bit and WRONG.
All addresses should be verified via GDB on the running process.

Verified: 2026-06-30
- Steam process: ELF 32-bit LSB pie executable (i386)
- steamclient.so loaded: ubuntu12_32/steamclient.so
- YieldingRunTestProgram string: 0x00bfc7e3 (32-bit) vs 0x00d6d17b (64-bit)

# Haptic Payload Construction - Analysis

## Status: PARTIALLY DETERMINED

## Key Functions Found

### TriggerHapticPulse Function
- Location: VA 0x013205a3 [32-bit: NEEDS RE-ANALYSIS] (function start)
- References string "TriggerHapticPulse" at VA 0x00ab43f0
- This is a dispatch function that handles different haptic event types

### ForceSimpleHapticEvent Function
- Location: VA 0x01322dae [32-bit: NEEDS RE-ANALYSIS] (function start)
- References string "ForceSimpleHapticEvent" at VA 0x00ab43b0

### CRumbleThread Function
- Location: VA 0x0111b370 [32-bit: NEEDS RE-ANALYSIS] (function start)
- References string "CRumbleThread" at VA 0x00aa5b00

## Analysis of TriggerHapticPulse (0x013205a3 [32-bit: NEEDS RE-ANALYSIS])

The function at 0x013205a3 [32-bit: NEEDS RE-ANALYSIS] is a large dispatch function that:
1. Takes parameters: rsi (controller?), rcx (callback?), rdx (data?)
2. Reads a hash/dword from [rsp+0x8] and dispatches based on it
3. For TriggerHapticPulse case (hash 0xf4ee1f05):
   - Gets a haptic work item from rax = call 0x26cf5b0
   - Logs "TriggerHapticPulse" string
   - Reads 8 bytes from the controller into [rsp+0x38]
   - Reads 1 byte into [rsp+0x28]
   - Formats and sends the haptic data

## Haptic Command Format (Inferred)

Based on the code patterns and the NEPTUNE_LIZARD_OFF_CMDS from input_handler.py:

The haptic command is sent as a Feature Report 0x00 with this format:
```
Byte 0:    0x01 (report type)
Byte 1:    0x00 (padding)
Byte 2:    0x87 (SET_SETTINGS command) or other command
Byte 3:    Register index (e.g., 0x09 for lizard mode)
Byte 4-5:  Value (little-endian word)
Byte 6+:   Additional data (varies)
```

For haptics specifically, the command likely uses:
- Command byte: 0x85 or similar (haptic control)
- Register: motor selection (left/right)
- Value: intensity/speed

## What's Missing

The exact byte format of the haptic Feature Report 0x00 payload was not fully determined.
The function at 0x013205a3 [32-bit: NEEDS RE-ANALYSIS] dispatches to different handlers, but the actual buffer
construction happens deeper in the call chain.

To complete this analysis, we would need to:
1. Trace the call at 0x01320765 [32-bit: NEEDS RE-ANALYSIS] into the actual haptic handler
2. Find where the 64-byte buffer is constructed
3. Identify which bytes correspond to motor selection and intensity

## String References

| String | VA | Used In |
|--------|-----|---------|
| TriggerHapticPulse | 0x00ab43f0 | 0x01320765 [32-bit: NEEDS RE-ANALYSIS], 0x01320784 [32-bit: NEEDS RE-ANALYSIS], 0x01320859 [32-bit: NEEDS RE-ANALYSIS], 0x013208cb [32-bit: NEEDS RE-ANALYSIS] |
| ForceSimpleHapticEvent | 0x00ab43b0 | 0x0132425b [32-bit: NEEDS RE-ANALYSIS], 0x0132427a [32-bit: NEEDS RE-ANALYSIS], 0x013242b6 [32-bit: NEEDS RE-ANALYSIS], 0x01324368 [32-bit: NEEDS RE-ANALYSIS] |
| CRumbleThread | 0x00aa5b00 | 0x0111d10b [32-bit: NEEDS RE-ANALYSIS] |
| CPulseHapticWorkItem | 0x00aa28e2 | (not found via LEA) |
