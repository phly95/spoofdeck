# Actor Prompt Guide

> How to formulate prompts for explore/general subagents. Read this before spawning any actor.

---

## Template: RE / Binary Analysis Actor

```markdown
You are reverse-engineering [TARGET] to answer [QUESTION].

## Context

[What we know so far — max 10 lines. Include:]
- [Current symptom/log output]
- [What was already tried]
- [Why this matters — what it blocks]

Key addresses/strings:
- [VA] — [what it is]
- [String] at [VA] — [context]

## What You Must Find

### 1. [QUESTION] (CRITICAL/HIGH/MEDIUM)

Steps:
1. [Specific starting point — function name, RTTI string, or address]
2. [What to look for]
3. [What to save]

Save to: research/steamclient-reverse-session/functions/[name].c

### 2. [QUESTION] (CRITICAL/HIGH/MEDIUM)

[Same format]

## Tools

**IMPORTANT: `aaa` is too slow on 46MB binaries — it will timeout. Use these instead:**

```bash
# Targeted disassembly — no analysis needed, instant
r2 -q -c 's 0xADDR; pd 50' BINARY 2>/dev/null

# Basic analysis only (fast, ~10s)
r2 -q -c 'aa; s 0xADDR; af; pdf' BINARY 2>/dev/null

# If function boundaries are already known
r2 -q -c 's 0xADDR; af; pdf' BINARY 2>/dev/null

# Search for strings
r2 -q -c '/ STRING' BINARY 2>/dev/null

# Find xrefs to an address (requires basic analysis first)
r2 -q -c 'aa; axt @ 0xADDR' BINARY 2>/dev/null
```

**Rule of thumb**: Never use `aaa` or `aaaa`. Use `aa` (basic) or `s; pd` (raw) instead.

## Workspace

Use research/steamclient-reverse-session/ — update findings.md, save code to functions/.

## Stop Condition

Deliver ONE of:
1. "[Answer to question with evidence]"
2. "[Function does X, fails because Y]"
3. "[Our ATT server is missing/incorrect field Z]"

Before you start, re-read relevant files to ensure proper understanding.
```

---

## Template: Deploy/Test Actor

```markdown
Deploy [WHAT] to the Deck and verify [WHAT].

## Steps

1. Deploy files:
   sshpass -p '<DECK_PASSWORD>' scp -o StrictHostKeyChecking=no -r [LOCAL_PATH] deck@<DECK_IP>:[REMOTE_PATH]

2. Restart service:
   sshpass -p '<DECK_PASSWORD>' ssh -o StrictHostKeyChecking=no deck@<DECK_IP> "echo <DECK_PASSWORD> | sudo -S systemctl restart sc2-hogp"

3. Connect on host:
   printf '<HOST_SUDO_PASSWORD>\n' | sudo -S bluetoothctl remove C2:12:34:56:78:9A
   printf '<HOST_SUDO_PASSWORD>\n' | sudo -S bluetoothctl --timeout 10 scan on
   printf '<HOST_SUDO_PASSWORD>\n' | sudo -S bluetoothctl connect C2:12:34:56:78:9A

4. Check results:
   [Specific log grep commands]

## Stop Condition

Report:
1. [Did X happen?]
2. [What do the logs show?]
3. [Pass/fail]
```

---

## Template: Source Code Analysis Actor

```markdown
Read [FILE] and answer these questions about [TOPIC].

## Questions

1. [Specific question]
2. [Specific question]
3. [Specific question]

## Context

[Why these questions matter — 2-3 sentences]

Save answers to: research/steamclient-reverse-session/functions/[name].c

## Stop Condition

Deliver concise answers (not full source). Include addresses/code snippets as evidence.
```

---

## Key Principles

### Always Include
- **Context**: What we know, what was tried, why it matters
- **Specific starting points**: Function names, VAs, string references
- **Concrete questions**: Not "analyze this" but "what does X read?"
- **Save paths**: Where to put findings
- **Stop condition**: What to deliver back

### Never Include
- Full source code dumps
- Vague instructions ("investigate this area")
- Multiple unrelated tasks in one actor

### Prompt Length
- RE actors: 40-80 lines
- Deploy actors: 15-25 lines
- Source analysis: 10-20 lines

### Parallelism Rules
- Multiple explore actors reading local files: SAFE
- One SSH actor + one local-file actor: SAFE
- Two SSH actors in parallel: UNSAFE (serialize)
- btmon + pairing in parallel: UNSAFE (serialize)

---

## Example: Good vs Bad

### Bad
```
Analyze why the controller becomes zombie. Check the binary and find the timer.
```

### Good
```
You are reverse-engineering why the SC2 BLE controller becomes zombie 6 seconds after opening.

## Context

Steam log shows:
- "!! Steam controller device opened for index 0"
- "Controller PollState Changed from 0 to 1"
- "Disconnecting zombie controller 0" (6 seconds later)

The zombie disconnect is state-based, not time-based:
- Slot state == 3, per-slot flag at 0x10b4 == 0, connection state != 1 && != 4
- 6-second interval is the polling frequency of the slot iterator

Binary: ~/.steam/debian-installation/ubuntu12_32/steamclient.so

## What You Must Find

### 1. What Does the Connection State Query Return? (HIGH)

The zombie check at 0x1070620 calls vtable[0x18] to get connection state.

Steps:
1. Disassemble 0x1070620
2. Trace what vtable[0x18] does for our BLE controller
3. What value does it return — 1, 4, or something else?
4. If it returns something other than 1/4, why?

Save to: research/steamclient-reverse-session/functions/zombie_connection_state.c

### 2. What Sets the Per-Slot Flag at 0x10b4? (MEDIUM)

This flag bypasses zombie check when non-zero.

Steps:
1. Search for writes to offset 0x10b4
2. What condition sets/clears this flag?
3. Is it set when input reports flow?

Save to: research/steamclient-reverse-session/functions/zombie_flag_0x10b4.c

## Stop Condition

Deliver ONE of:
1. "Connection state returns X because Y"
2. "Flag at 0x10b4 is set/cleared by function at 0xADDR"
3. "Zombie is triggered by condition, controller must do X to prevent it"
```
