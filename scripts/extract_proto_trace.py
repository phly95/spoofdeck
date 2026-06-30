#!/usr/bin/env python3
"""
Extract structured protocol trace from SPOOFDECK_PROTO_LOG output.

Parses JSON log lines emitted by the ATT server and SC2 command handler
when SPOOFDECK_PROTO_LOG=1 is set.

Usage:
    python3 scripts/extract_proto_trace.py /path/to/hogp.log
    python3 scripts/extract_proto_trace.py --csv /path/to/hogp.log > trace.csv
    python3 scripts/extract_proto_trace.py --help

No third-party dependencies.
"""

import argparse
import csv
import json
import sys
from collections import defaultdict


# SC2 command bytes we track
TRACKED_CMDS = {
    0x81: "CLEAR_DIGITAL_MAPPINGS",
    0x83: "GET_ATTRIBUTES",
    0x87: "SET_SETTINGS_VALUES",
    0x8D: "SET_CONTROLLER_MODE",
    0x8F: "TRIGGER_HAPTIC_PULSE",
    0xAE: "GET_SERIAL",
    0xF2: "CAPABILITY_QUERY_UNKNOWN",
}


def parse_log(lines):
    """Parse structured JSON log lines. Returns list of parsed entries."""
    entries = []
    for lineno, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "event" not in entry:
            continue
        entries.append(entry)
    return entries


def extract_commands(entries):
    """Extract SC2 commands from parsed entries. Returns list of command dicts."""
    commands = []
    for e in entries:
        event = e.get("event", "")

        # SC2 command from write path (att_write_req or att_write_cmd with cmd field)
        if event in ("att_write_req", "att_write_cmd") and e.get("cmd"):
            cmd_hex = e["cmd"]
            try:
                cmd_byte = int(cmd_hex, 16)
            except ValueError:
                continue
            commands.append({
                "ts": e.get("ts", 0),
                "event": event,
                "cmd": cmd_hex,
                "cmd_byte": cmd_byte,
                "cmd_name": e.get("cmd_name", TRACKED_CMDS.get(cmd_byte, f"0x{cmd_byte:02x}")),
                "handle": e.get("handle", ""),
                "data": e.get("data", ""),
                "response": e.get("response", ""),
                "response_len": e.get("response_len", 0),
                "cb_invoked": e.get("cb_invoked"),
                "cb_result": e.get("cb_result"),
                "error": e.get("error"),
            })

        # SC2 command from the main_l2cap.py handler
        elif event == "sc2_cmd" and e.get("cmd"):
            cmd_hex = e["cmd"]
            try:
                cmd_byte = int(cmd_hex, 16)
            except ValueError:
                continue
            commands.append({
                "ts": e.get("ts", 0),
                "event": event,
                "cmd": cmd_hex,
                "cmd_byte": cmd_byte,
                "cmd_name": e.get("cmd_name", TRACKED_CMDS.get(cmd_byte, f"0x{cmd_byte:02x}")),
                "fr_id": e.get("fr_id", ""),
                "data": e.get("data", ""),
                "response": e.get("response", ""),
                "response_len": e.get("response_len", 0),
            })

    return commands


def compute_stats(commands):
    """Compute per-command statistics."""
    stats = defaultdict(lambda: {
        "count": 0,
        "first_ts": None,
        "last_ts": None,
        "retries": 0,
        "errors": 0,
        "name": "",
    })

    # Track seen (cmd_byte, data) pairs for retry detection
    seen = defaultdict(int)

    for cmd in commands:
        cb = cmd["cmd_byte"]
        name = cmd["cmd_name"]
        ts = cmd["ts"]

        s = stats[cb]
        s["count"] += 1
        s["name"] = name
        if s["first_ts"] is None or ts < s["first_ts"]:
            s["first_ts"] = ts
        if s["last_ts"] is None or ts > s["last_ts"]:
            s["last_ts"] = ts
        if cmd.get("error"):
            s["errors"] += 1

        # Retry detection: same command byte with same data prefix
        # (exact match of first 4 bytes = likely retry)
        key = (cb, cmd.get("data", "")[:8])
        seen[key] += 1
        if seen[key] > 1:
            s["retries"] += 1

    return dict(stats)


def print_chronological(commands):
    """Print chronological command list."""
    print("=" * 72)
    print("CHRONOLOGICAL COMMAND LIST")
    print("=" * 72)
    if not commands:
        print("  (no commands found)")
        return
    for i, cmd in enumerate(commands, 1):
        ts = cmd["ts"]
        name = cmd["cmd_name"]
        cb = cmd["cmd"]
        handle = cmd.get("handle", cmd.get("fr_id", "?"))
        data = cmd.get("data", "")
        resp_len = cmd.get("response_len", 0)
        err = cmd.get("error", "")
        retried = " [RETRY]" if cmd.get("_retried") else ""
        err_mark = f" ERROR={err}" if err else ""
        print(f"  {i:4d}  {ts:10.3f}  {cb:5s}  {name:30s}  handle={handle}  resp_len={resp_len:3d}{retried}{err_mark}")
        if data:
            print(f"        data: {data[:80]}{'...' if len(data) > 80 else ''}")


def print_counts(stats):
    """Print command counts."""
    print()
    print("=" * 72)
    print("COMMAND COUNTS")
    print("=" * 72)
    if not stats:
        print("  (no commands found)")
        return
    for cb_hex in sorted(stats.keys(), key=lambda x: int(x)):
        s = stats[cb_hex]
        name = s["name"]
        count = s["count"]
        print(f"  0x{cb_hex:02x}  {name:30s}  {count:5d}")


def print_retries(stats):
    """Print retry counts."""
    print()
    print("=" * 72)
    print("RETRY COUNTS (commands with duplicate data prefix)")
    print("=" * 72)
    if not stats:
        print("  (no commands found)")
        return
    for cb_hex in sorted(stats.keys(), key=lambda x: int(x)):
        s = stats[cb_hex]
        name = s["name"]
        retries = s["retries"]
        errors = s["errors"]
        print(f"  0x{cb_hex:02x}  {name:30s}  retries={retries:4d}  errors={errors:4d}")


def print_timestamps(stats):
    """Print first/last timestamp per command."""
    print()
    print("=" * 72)
    print("FIRST / LAST TIMESTAMP PER COMMAND")
    print("=" * 72)
    if not stats:
        print("  (no commands found)")
        return
    for cb_hex in sorted(stats.keys(), key=lambda x: int(x)):
        s = stats[cb_hex]
        name = s["name"]
        first = s["first_ts"]
        last = s["last_ts"]
        dur = (last - first) if first is not None and last is not None else 0
        print(f"  0x{cb_hex:02x}  {name:30s}  first={first:10.3f}  last={last:10.3f}  span={dur:8.3f}s")


def output_csv(commands, out):
    """Write CSV to out file object."""
    writer = csv.writer(out)
    writer.writerow([
        "ts", "event", "cmd", "cmd_name", "handle", "data",
        "response", "response_len", "cb_invoked", "cb_result", "error"
    ])
    for cmd in commands:
        writer.writerow([
            cmd.get("ts", ""),
            cmd.get("event", ""),
            cmd.get("cmd", ""),
            cmd.get("cmd_name", ""),
            cmd.get("handle", cmd.get("fr_id", "")),
            cmd.get("data", ""),
            cmd.get("response", ""),
            cmd.get("response_len", ""),
            cmd.get("cb_invoked", ""),
            cmd.get("cb_result", ""),
            cmd.get("error", ""),
        ])


def main():
    parser = argparse.ArgumentParser(
        description="Extract structured protocol trace from SPOOFDECK_PROTO_LOG output.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 scripts/extract_proto_trace.py /path/to/hogp.log
  python3 scripts/extract_proto_trace.py --csv /path/to/hogp.log > trace.csv

Set SPOOFDECK_PROTO_LOG=1 on the Deck to enable structured logging:
  SPOOFDECK_PROTO_LOG=1 systemd-run --unit=sc2-hogp python3 src/main_l2cap.py
"""
    )
    parser.add_argument(
        "logfile",
        help="Path to log file containing structured JSON log lines",
    )
    parser.add_argument(
        "--csv",
        action="store_true",
        dest="csv_output",
        help="Output CSV instead of human-readable report",
    )
    parser.add_argument(
        "--csv-file",
        default=None,
        help="Write CSV to this file instead of stdout (with --csv flag)",
    )

    args = parser.parse_args()

    # Read log file
    try:
        with open(args.logfile, "r") as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"Error: file not found: {args.logfile}", file=sys.stderr)
        sys.exit(1)
    except IOError as e:
        print(f"Error reading {args.logfile}: {e}", file=sys.stderr)
        sys.exit(1)

    entries = parse_log(lines)
    if not entries:
        print(f"No structured log entries found in {args.logfile}", file=sys.stderr)
        print("Make sure SPOOFDECK_PROTO_LOG=1 was set when running the service.", file=sys.stderr)
        sys.exit(1)

    commands = extract_commands(entries)

    # Mark retries
    seen = defaultdict(int)
    for cmd in commands:
        key = (cmd["cmd_byte"], cmd.get("data", "")[:8])
        seen[key] += 1
        if seen[key] > 1:
            cmd["_retried"] = True

    stats = compute_stats(commands)

    if args.csv_output:
        out = open(args.csv_file, "w", newline="") if args.csv_file else sys.stdout
        output_csv(commands, out)
        if args.csv_file:
            out.close()
    else:
        print(f"Log file: {args.logfile}")
        print(f"Total entries: {len(entries)}")
        print(f"Total SC2 commands: {len(commands)}")
        print()
        print_chronological(commands)
        print_counts(stats)
        print_retries(stats)
        print_timestamps(stats)


if __name__ == "__main__":
    main()
