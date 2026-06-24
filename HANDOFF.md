# Handoff Prompt for Next Agent — SC2 BLE Spoof Project

## What This Project Does

Make a **Steam Deck** present itself as a **Steam Controller 2026 (SC2)** over **Bluetooth Low Energy**, so that Steam Client on a host PC recognizes it as an SC2 with full Steam Input support (trackpads, gyro, haptics, back buttons).

## Current Status

**Working**: Raw L2CAP ATT server on CID 4 — MTU exchange and service discovery succeed. Host sees `ServicesResolved: yes` with all 5 GATT services (34 attributes). Pairing works via auto-confirm Agent1.

**Not yet working**: Connection drops after service discovery (~26s). Full HOGP lifecycle not complete — no `/dev/hidraw` on host, no input forwarding.

## The Blocker

Connection drops after service discovery. The host discovers all services but doesn't complete the characteristic discovery and reads needed to create `/dev/hidraw`. Suspected: missing ATT handlers for characteristic discovery (Read By Type for UUID `0x2803`) and characteristic reads.

## What to Do

1. Read AGENTS.md in full (mandatory reading list is in there)
2. Add missing ATT handlers (see AGENTS.md for details)
3. Test full HOGP lifecycle → `/dev/hidraw` → input forwarding

## Full Documentation

See AGENTS.md for architecture, how to run, gotchas, file structure, and all research documents.
