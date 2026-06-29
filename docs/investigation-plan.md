# Investigation Plan: Haptics Root Cause & Fix

## Purpose

This document defines the methodology for investigating and fixing the haptics issue on the SC2 BLE spoof. It establishes rules for how to reason about evidence, how to avoid overstating conclusions, and how to structure the investigation so that each step builds on verified findings rather than assumptions.

---

## Part 1: Methodology — How to Think About This Problem

### 1.1 The Core Principle: Evidence Before Conclusion

Every statement about what IS or IS NOT the root cause must be supported by specific evidence. Evidence is a log line, a hex dump, a code path traced, a function call observed. A conclusion is an interpretation of that evidence. The two must never be conflated.

**Rule**: Before stating "X is the cause," you must be able to point to a specific piece of evidence that directly supports it. If the evidence is indirect or circumstantial, say so. If the evidence is consistent with multiple explanations, list all of them.

**Example of bad reasoning**:
> "SET_REPORT fails because the ATT server doesn't handle Write Command properly."

This is a conclusion stated as if it were evidence. The actual evidence might be: "btmon shows 487 ATT Error Response packets with code 0x05 (Insufficient Authentication) in response to Write Command packets." The conclusion about WHY it fails requires additional investigation.

**Example of good reasoning**:
> "btmon shows 487 Write Command (0x52) packets sent by the host to handle 0x0019. Each receives an ATT Error Response with code 0x05. This tells us the host IS sending writes, but the server is rejecting them due to authentication requirements. The next question is: why does our server require authentication for Write Command on handle 0x0019?"

### 1.2 The Confidence Scale

Every finding must be tagged with a confidence level. This prevents the group from treating hypotheses as confirmed facts.

| Level | Label | Definition | Example |
|-------|-------|------------|---------|
| 1 | **Confirmed** | Directly observed in logs, code, or capture. Multiple independent sources agree. | "btmon shows 487 SET_REPORT errors" |
| 2 | **Strongly Supported** | Consistent with all observed evidence, but one or two observations are missing. | "The notification on 0x0033 is likely required because Steam retries SET_SETTINGS every 3s without it" |
| 3 | **Plausible** | Consistent with some evidence, but alternative explanations exist. | "hog-ll may be failing because the ATT server returns wrong error codes" |
| 4 | **Speculative** | Based on inference from limited evidence or analogy to similar systems. | "Steam might require the notification before enabling haptic writes" |
| 5 | **Guess** | No direct evidence. Based on intuition or incomplete understanding. | "Maybe BlueZ needs a config change" |

**Rule**: When writing findings, tag each conclusion with its confidence level. When communicating with other agents or the user, never present a Level 3-5 finding as if it were Level 1-2.

### 1.3 The Hypothesis Lifecycle

Every hypothesis must go through a lifecycle:

1. **Formation**: Based on initial evidence, form a hypothesis. Tag it Level 3-4.
2. **Prediction**: State what you would observe IF the hypothesis is true. Be specific.
3. **Test**: Design an observation or experiment that tests the prediction.
4. **Evaluation**: Compare the observation to the prediction. Does it match?
5. **Update**: Based on the result, upgrade or downgrade the confidence level.

**Example**:

1. **Formation** (Level 4): "Steam may require the SET_SETTINGS notification before enabling haptic output."
2. **Prediction**: "If true, after we send the notification, the 487 SET_REPORT errors should decrease, and/or ATT Write Command (0x52) packets for haptic output should appear."
3. **Test**: Add the notification code, deploy, capture btmon.
4. **Evaluation**: Compare btmon before and after. Count SET_REPORT errors. Count 0x52 packets.
5. **Update**: If errors decrease → upgrade to Level 2-3. If no change → downgrade to Level 5 or discard.

### 1.4 What We Already Know (Verified Facts Only)

These are findings that have been confirmed through direct observation. They are tagged Level 1 unless noted otherwise.

1. **btmon shows 487 SET_REPORT errors** (Level 1) — Directly observed in `scratch/btmon_handshake.txt`. The errors are ATT Error Responses to Write Command (0x52) packets. Source: btmon capture on host PC.

2. **btmon shows zero ATT Write Command (0x52) packets for haptic output** (Level 1) — Directly observed. During the test session, no 0x52 packets were sent to handle 0x0019 (haptic output) or 0x0017 (output Report ID 0x02). Source: btmon capture.

3. **Steam schedules haptic work items** (Level 1) — `CPulseHapticWorkItem(0)` appears in Steam logs. The work item runs and completes in 0.0ms. Source: Steam log files on host.

4. **Our code does NOT send SET_SETTINGS notification** (Level 1) — `main_l2cap.py:522-525` contains a comment explicitly stating this is intentional. The notification on handle 0x0033 is never sent. Source: code inspection.

5. **A real SC2 sends the SET_SETTINGS notification** (Level 2) — This is based on btmon captures from a real SC2 (referenced in docs but not directly verified by us in this session). The claim is that the real device sends `[0x87, 0x01, register, 0x00 × 61]` on handle 0x0033 after each SET_SETTINGS write. Confidence is Level 2 because we have not personally captured and verified this from a real SC2 — we are relying on documentation and prior analysis.

6. **`0x17252a0` is dead code** (Level 1) — Zero callers confirmed via E8 scan, pointer search, vtable search, GOT search, relocation search, objdump, and axt. All methods agree. Source: multiple independent analysis methods.

7. **GATT metadata is correct** (Level 1) — Report Map declares output report 0x80, CHR_REPORT at handle 0x0019 has correct properties, Report Reference is `[0x80, 0x02]`, write callback is registered. Source: code inspection of `gatt_db.py` and `main_l2cap.py`.

8. **`controller+0x320` is inverted** (Level 2) — Non-zero means haptics disabled. Cleared in mode switch handler. This was found in binary analysis of steamclient.so. Confidence is Level 2 because we are inferring semantics from assembly patterns, not from source code or documentation.

### 1.5 What We Do NOT Know (Open Questions)

These are questions where we either have no evidence or have conflicting evidence. They are listed in order of importance.

1. **Why does SET_REPORT fail?** (Level 3 hypothesis: authentication issue) — We see 487 errors, but we don't know the specific ATT error code being returned. The hypothesis that it's an authentication issue is plausible but unconfirmed. The actual error code in the btmon capture needs to be examined more carefully.

2. **Does the SET_SETTINGS notification affect haptics?** (Level 4 hypothesis) — We hypothesize that the missing notification may be contributing to the haptic failure, but we have no evidence that sending it would change anything. This is an inference from the observation that Steam retries SET_SETTINGS every 3 seconds.

3. **What opcode does hog-ll use for haptic writes?** (Level 3 hypothesis: Write Command 0x52) — We assume hog-ll uses Write Command (0x52) for output reports, based on the HID over GATT specification. But we have not confirmed this from BlueZ source code or btmon captures of a working haptic device.

4. **What is the exact format of the haptic write?** (Level 3) — We assume 10 bytes with Report ID 0x80, based on the HID Report Map and SDL3 source code analysis. But we have not seen an actual haptic write from a working device.

5. **Does BlueZ hog-ll require SET_REPORT to succeed before output reports work?** (Level 2 hypothesis) — The HID over GATT specification says SET_REPORT is used to initialize output reports, but we haven't confirmed this from BlueZ source code. We're relying on the specification and the observation that SET_REPORT fails.

6. **What happens on a real SC2 with haptics?** (Level 3) — We don't have a btmon capture of a real SC2 receiving haptic writes. We're inferring from SDL3 source code and the HID spec.

### 1.6 The Anti-Pattern: Overstating Confidence

This is the most important section. Overstated confidence is the single biggest risk to this investigation. When we state things with false certainty, we:

1. Stop looking for alternative explanations
2. Skip verification steps
3. Make bad decisions based on wrong conclusions
4. Waste time chasing the wrong root cause

**Common overconfidence patterns to avoid**:

- **"X is the cause"** when you mean "X is consistent with the evidence"
- **"Y doesn't matter"** when you mean "Y hasn't been observed to matter in our tests"
- **"We've confirmed Z"** when you mean "Z appears to be true based on limited testing"
- **"The fix is straightforward"** when you mean "The fix appears straightforward based on our current understanding"
- **"This will definitely work"** when you mean "This is the most promising approach based on current evidence"

**The fix**: Use hedging language. Say "appears to," "is consistent with," "the evidence suggests," "based on our testing," "we hypothesize that." This is not weakness — it's intellectual honesty that prevents costly mistakes.

---

## Part 2: Investigation Plan — Step by Step

### Phase 1: Baseline Capture (Do Before Any Changes)

**Goal**: Establish a complete picture of what happens during a connection, before making any code changes.

**Why this matters**: We have btmon captures, but we haven't systematically examined them for specific ATT opcodes. We need to know exactly what the host sends and what the server responds with, for every PDU type.

**Step 1.1: Examine existing btmon capture for SET_REPORT details**

- Open `scratch/btmon_handshake.txt`
- Search for all Write Command (0x52) packets
- For each, note: timestamp, handle, data (first 2 bytes at minimum)
- Search for all ATT Error Response (0x01) packets
- For each, note: timestamp, request opcode, handle, error code
- Count total Write Commands vs total Error Responses
- Identify which handles receive Write Commands and which error codes are returned

**Deliverable**: A table of all Write Command packets and their responses, grouped by handle.

**Step 1.2: Examine existing btmon capture for the full connection sequence**

- From connection establishment to first input notification
- Note every ATT PDU type and count
- Note the order of operations (MTU exchange → service discovery → characteristic discovery → descriptor discovery → CCCD writes → ?)
- Identify where SET_REPORT fits in the sequence

**Deliverable**: A timeline of the ATT connection sequence.

**Step 1.3: Examine Deck logs for the same connection**

- From `scratch/logs_from_deck.txt` or similar
- Note every log line from our ATT server during the same connection
- Compare what the server received vs what btmon shows the host sent
- Identify any discrepancies

**Deliverable**: A comparison of host-sent vs server-received PDUs.

### Phase 2: Hypothesis Formation (Based on Phase 1 Findings)

**Goal**: After examining the evidence, form specific, testable hypotheses.

**Step 2.1: List all hypotheses for why SET_REPORT fails**

For each hypothesis:
- State it clearly
- List the evidence that supports it
- List the evidence that contradicts it
- State what additional evidence would confirm or refute it
- Assign a confidence level (1-5)

**Step 2.2: List all hypotheses for why haptics don't work**

Same format as 2.1. Note that SET_REPORT failure may or may not be the root cause — there could be multiple issues.

**Step 2.3: Rank hypotheses by testability and impact**

For each hypothesis:
- How easy is it to test? (easy/medium/hard)
- If true, what's the impact on haptics? (high/medium/low)
- What's the risk of pursuing this hypothesis if it's wrong? (low/medium/high)

**Deliverable**: A prioritized list of hypotheses with test plans.

### Phase 3: Targeted Investigation (Test Top Hypotheses)

**Goal**: Test the highest-priority hypotheses with minimal code changes.

**Step 3.1: Add diagnostic logging to `_handle_write_cmd()`**

Before fixing anything, we need to understand what the host is actually sending. Add logging that captures:
- All incoming Write Command (0x52) packets
- Handle, data, timestamp
- Whether the write was to a CCCD, feature report, or output report
- Whether the write triggered a callback

This is the single most important diagnostic step. Without it, we're flying blind.

**Step 3.2: Add diagnostic logging to `_handle_write()` (Write Request 0x12)**

Same as 3.1 but for Write Request packets. These are used for CCCD writes and potentially for SET_REPORT if hog-ll uses Write Request instead of Write Command.

**Step 3.3: Deploy and capture**

- Deploy the updated code to the Deck
- Connect from the host
- Capture btmon on the host simultaneously
- Capture Deck logs
- Compare the two

**Step 3.4: Analyze the results**

- What PDUs did the host send?
- What did the server respond with?
- Were there any error responses?
- What was the error code?

**Deliverable**: A detailed log of the ATT PDU exchange during connection.

### Phase 4: Fix Implementation (Based on Phase 3 Findings)

**Goal**: Implement fixes based on verified evidence, not hypotheses.

**Step 4.1: Fix the most likely root cause**

Based on Phase 3 findings, implement the fix for the most likely root cause. But:
- Only change one thing at a time
- Document what you changed and why
- Document what you expect to happen
- Document what actually happened

**Step 4.2: Test the fix**

- Deploy the fix
- Capture btmon
- Check if SET_REPORT errors decrease
- Check if haptic Write Commands appear
- Check if Steam logs show haptic activity

**Step 4.3: If the fix doesn't work, revert and try the next hypothesis**

Do not stack fixes. If Fix A doesn't work, revert it and try Fix B. Stacking fixes makes it impossible to know which change (if any) actually helped.

**Step 4.4: Document the result**

无论结果如何，记录：
- What was changed
- What was observed
- Whether it helped
- What the new hypothesis is (if applicable)

### Phase 5: Verification (Confirm the Fix Works)

**Goal**: Verify that the fix actually works, not just that the symptoms improved.

**Step 5.1: Verify haptic data reaches the Deck**

- Check Deck logs for `_on_haptic_write()` callbacks
- Verify the haptic payload is parsed correctly
- Verify the Neptune output report is sent

**Step 5.2: Verify the Neptune controller receives the haptic command**

- Check if the Neptune controller responds to the haptic command
- This may require checking hidraw output or Neptune status

**Step 5.3: Verify Steam shows haptic activity**

- Check Steam logs for haptic work items
- Verify they complete successfully (not in 0.0ms)
- Verify rumble is audible/visible on the Deck

**Step 5.4: End-to-end test**

- Launch a game that uses haptics
- Verify rumble works during gameplay
- Verify no regressions in input, trackpads, gyro, back buttons

---

## Part 3: Subagent Management Rules

### 3.1 What to Delegate

| Task | Agent Type | Why |
|------|-----------|-----|
| Reading BlueZ source code | explore | Large files, mechanical analysis |
| Parsing btmon captures | explore | Log parsing, pattern matching |
| Checking Deck SSH logs | general | SSH operations, log collection |
| Deploying code to Deck | general | Scripted operations, no judgment needed |
| Analyzing binary patterns | explore | Targeted disassembly, specific questions |
| Writing code changes | **main thread** | Requires full context, architecture understanding |
| Making investigation decisions | **main thread** | Requires synthesized evidence |

### 3.2 What NOT to Delegate

- **Decision-making**: Don't let a subagent decide what to do next. Get their findings, then decide.
- **Code changes**: Don't let a subagent edit files. Get their analysis, then make the change.
- **Confidence assessments**: Don't let a subagent state "X is the cause." Ask them for evidence, then assess confidence yourself.

### 3.3 How to Prompt Subagents

**Bad prompt** (leads to overconfident conclusions):
```
Analyze why SET_REPORT fails in the btmon capture and tell me the root cause.
```

**Good prompt** (leads to evidence-based findings):
```
Read scratch/btmon_handshake.txt. Find all ATT Error Response (0x01) packets.
For each, extract: timestamp, request opcode, handle, error code.
Group by error code.
Return the raw findings as a table. Do not interpret why the errors occur — just report what you see.
```

### 3.4 How to Evaluate Subagent Results

When a subagent returns findings:

1. **Check for raw evidence**: Did they include specific log lines, hex dumps, function addresses?
2. **Check for overconfidence**: Did they state conclusions as facts? If so, ask for the evidence.
3. **Check for completeness**: Did they answer all parts of the question?
4. **Check for consistency**: Do the findings agree with what we already know?

If the subagent's findings seem wrong or incomplete, don't accept them. Re-prompt with more specific instructions or examine the evidence yourself.

---

## Part 4: Communication Rules

### 4.1 When Writing Findings Documents

- Every finding must cite specific evidence (log line, hex dump, code reference)
- Every conclusion must be tagged with a confidence level (1-5)
- Alternative explanations must be listed when evidence is ambiguous
- What we DON'T know must be stated as clearly as what we DO know

### 4.2 When Communicating with the User

- State what we know (evidence), what we think (hypothesis), and what we're going to do (plan)
- Never say "the fix is X" before testing. Say "we're going to try X because [evidence suggests it may help]"
- If asked "will this work?" — say "the evidence suggests it may, because [reasons], but we need to test it"
- If a test fails — say "the test didn't produce the expected result. Here's what we observed: [findings]. This suggests [new hypothesis]."

### 4.3 When Writing Code Comments

- Don't write comments like "this is correct" or "this should work"
- Write comments like "this matches the behavior observed in [source]" or "this is based on the assumption that [X], which needs verification"
- Document what is known vs what is assumed

---

## Part 5: Risk Management

### 5.1 What Could Go Wrong

| Risk | Impact | Mitigation |
|------|--------|------------|
| Fix breaks existing functionality | High | Test all features after each change |
| Stale BlueZ state poisons testing | High | Clear bond data before each test cycle |
| Subagent overstates findings | Medium | Verify all claims against raw evidence |
| We chase the wrong root cause | Medium | Maintain ranked hypothesis list, test systematically |
| Fix works on one test but not another | Medium | Run multiple test cycles, document variability |
| We break the Deck's BT stack | Medium | Have recovery procedure ready |

### 5.2 Recovery Procedure

If something breaks:
1. Clear bond data on host: `sudo rm -rf /var/lib/bluetooth/<HOST_BT_MAC>/C2:12:34:56:78:9A && sudo rm -rf /var/lib/bluetooth/cache && sudo systemctl restart bluetooth`
2. Restart Deck service: `echo asdf | sudo -S systemctl restart sc2-hogp`
3. If Deck BT is broken: `echo asdf | sudo -S systemctl restart bluetooth && sleep 2 && echo asdf | sudo -S python3 /tmp/config_bt.py`
4. If nothing works: reboot the host (nuclear option)

### 5.3 What We Will NOT Do

- We will not make multiple simultaneous changes and hope one of them works
- We will not skip diagnostic logging and go straight to fixes
- We will not accept subagent conclusions without verification
- We will not state hypotheses as facts in documentation
- We will not chase a hypothesis that has been refuted by evidence

---

## Part 6: Success Criteria

### 6.1 Minimum Viable Success

- Deck logs show `_on_haptic_write()` being called with haptic data
- Neptune output report is sent successfully
- Steam logs show haptic work items completing in > 0.0ms

### 6.2 Full Success

- All of the above
- Audible/visible rumble during gameplay
- No regressions in input, trackpads, gyro, back buttons
- SET_REPORT errors decrease significantly (ideally to zero)
- Connection remains stable during haptic activity

### 6.3 What Counts as Failure

- After systematic investigation, no single change produces any improvement in haptic behavior
- If this happens, it means the root cause is either:
  - Outside the scope of what we can fix (e.g., a Steam/SDL3 bug)
  - In a part of the system we haven't examined yet
  - A combination of multiple issues that can't be isolated

If we reach this point, we should document everything we tried, what we observed, and what the remaining hypotheses are.

---

## Appendix A: ATT Opcode Quick Reference

| Opcode | Name | Direction | Response |
|--------|------|-----------|----------|
| 0x01 | Error Response | Server → Client | — |
| 0x02 | Exchange MTU Request | Client → Server | 0x03 |
| 0x04 | Find Information Request | Client → Server | 0x05 |
| 0x08 | Read By Type Request | Client → Server | 0x09 |
| 0x0A | Read Request | Client → Server | 0x0B |
| 0x0C | Read Blob Request | Client → Server | 0x0D |
| 0x10 | Read By Group Type Request | Client → Server | 0x11 |
| 0x12 | Write Request | Client → Server | 0x13 |
| 0x1B | Handle Value Notification | Server → Client | — |
| 0x52 | Write Command | Client → Server | — |

## Appendix B: GATT Handle Map (Key Handles)

| Handle | Description | Properties |
|--------|-------------|------------|
| 0x0012 | Gamepad Input (Report ID 0x01) | Read, Notify |
| 0x0014 | Gamepad CCCD | Read, Write |
| 0x0016 | Output (Report ID 0x02) | Read, Write No Response, Write |
| 0x0019 | Haptic Output (Report ID 0x80) | Read, Write No Response, Write |
| 0x001A | Haptic Report Reference | Read, Write |
| 0x001C | Mouse Input (Report ID 0x03) | Read, Notify |
| 0x0020 | Keyboard Input (Report ID 0x04) | Read, Notify |
| 0x0021 | Feature Report 0x00 | Read, Write |
| 0x0024 | Feature Report 0x01 | Read, Write |
| 0x0027 | Feature Report 0x85 | Read, Write |
| 0x0033 | SC2 Custom CHR_REPORT (Report ID 0x45) | Read, Notify |
| 0x0035 | SC2 Custom CCCD | Read, Write |
| 0x0037 | SC2 Custom CHR_REPORT (Report ID 0x47) | Read, Notify |

## Appendix C: File Locations

| File | Location | Purpose |
|------|----------|---------|
| btmon capture | `scratch/btmon_handshake.txt` | Host-side HCI traffic |
| Deck logs | `scratch/logs_from_deck.txt` | ATT server logs |
| Steam logs | Host `~/.steam/` or `/tmp/` | Steam client logs |
| Source code | `src/main_l2cap.py` | SC2 command handler, haptic forwarding |
| Source code | `src/att_server.py` | Raw L2CAP ATT server |
| Source code | `src/gatt_db.py` | GATT database |

---

*Document version: 1.0*
*Created: 2026-06-28*
*Status: Active*
