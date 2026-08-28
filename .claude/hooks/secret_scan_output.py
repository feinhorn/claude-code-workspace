#!/usr/bin/env python3
"""
PostToolUse secret-scan: best-effort, after-the-fact alarm for a secret that
already made it into a tool result.

IMPORTANT LIMITATION (documented in secret-guard.sh's own header, and true
here too): by the time a PostToolUse hook runs, the tool's output has already
been returned and is already part of the transcript. This CANNOT redact or
un-print anything -- it can only raise a fast, visible alarm so a leak gets
caught and escalated (via the `rotate` skill / Notion log) immediately
instead of being noticed days later. The PreToolUse chain (secret-guard.sh)
remains the primary defense; this is a second-line detector for whatever
slips past it (a genuinely novel command shape, a tool response that embeds
a secret HA/UniFi/etc. hand back that Claude never asked for directly, etc).

Never prints the actual matched secret value anywhere (stdout, the warning
text, or the log file) -- only the category name and a short redacted
preview, so the warning mechanism can't itself become a second leak.

Usage: secret_scan_output.py < PostToolUse-hook-json
Output: a PostToolUse JSON decision (only when something was found), else
nothing. Exit code is always 0.
"""
import json
import math
import re
import sys
from datetime import datetime, timezone

LOG_FILE = "/workspace/.claude/hooks/.secret_scan_output.log"

# ---------- known credential-shape prefixes ----------
# (name, regex) -- regex should capture the FULL matched token so we can
# measure/redact it, but we never print the captured text itself.
KNOWN_PREFIX_PATTERNS = [
    ("AWS Access Key ID", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("OpenAI-style key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")),
    ("PEM private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("Bearer token", re.compile(r"\bBearer\s+[A-Za-z0-9\-_.=]{20,}")),
    # HA MCP add-on's own generated URL secret shape (the 2026-08-21 /
    # 2026-08-26 incidents both leaked exactly this).
    ("URL-embedded private_ token", re.compile(r"/private_[A-Za-z0-9_-]{10,}")),
]

# ---------- generic high-entropy run detector ----------
# Catches secret shapes with no recognizable prefix (raw API keys, random
# passwords). Deliberately noisy -- this is a WARN, not a block, so a false
# positive costs a glance, not a blocked workflow.
ENTROPY_CANDIDATE_RE = re.compile(r"[A-Za-z0-9+/_=-]{24,}")
ENTROPY_THRESHOLD = 4.0  # bits/char; random base64/hex sits ~4.0-6.0, English text ~3.0-3.5
ASSIGNMENT_PREFIX_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-]*[:=]")


def shannon_entropy(s):
    if not s:
        return 0.0
    counts = {}
    for c in s:
        counts[c] = counts.get(c, 0) + 1
    length = len(s)
    return -sum((n / length) * math.log2(n / length) for n in counts.values())


def strip_assignment_prefix(s):
    """`VARNAME=value` / `VARNAME:value` -> `value`.

    The variable NAME is real English-ish text; bundled with its value into
    one entropy candidate it both inflates the length past the threshold and
    can drag a benign value over the bits/char bar (or, the reverse, a long
    boring name can mask a short real secret's own entropy). The value on its
    own is still measured -- this only drops the name half. Real incident:
    `UNRAID_API_KEY=abcdef123456` (a dummy) warned as one 27-char blob.
    """
    # Only a leading `identifier=` / `identifier:` -- NOT a bare '=' or ':'
    # anywhere in the run, since '=' is also base64 padding and ':' shows up
    # inside real tokens. `+`/`/` in the run stop the identifier match, so a
    # base64 blob is left fully intact.
    return ASSIGNMENT_PREFIX_RE.sub("", s, count=1)


def looks_like_low_entropy_noise(s):
    # Common false-positive shapes: git commit hashes / hex digests (pure
    # hex, no mixed-case+digit variety needed for a real secret), and
    # repeated-char runs.
    if re.fullmatch(r"[0-9a-f]{24,}", s, re.I):
        return True
    if len(set(s)) <= 3:
        return True
    # Low character diversity: a real random secret exercises most of its
    # alphabet; padded / sequential / repeated test values
    # ("AAAABBBBCCCCDDDD...", "ABABABAB...") do not. 0.30 is well below where
    # real 32-char hex (~0.5) or base64 (~0.6+) tokens sit.
    if len(s) >= 20 and len(set(s)) / len(s) < 0.30:
        return True
    # Filesystem-path / plain-URL shape: 2+ '/' separators and no base64
    # padding chars. A genuine URL-embedded credential is still caught by the
    # KNOWN_PREFIX 'private_' / 'Bearer' / JWT patterns regardless of this.
    if s.count("/") >= 2 and "+" not in s and "=" not in s:
        return True
    return False


def redacted_preview(s):
    if len(s) <= 8:
        return "*" * len(s)
    return s[:3] + "..." + s[-2:] + f" ({len(s)} chars)"


def scan_text(text):
    """Returns a list of (category, preview) tuples. Never returns the raw match."""
    findings = []
    for name, pattern in KNOWN_PREFIX_PATTERNS:
        for m in pattern.finditer(text):
            findings.append((name, redacted_preview(m.group())))

    for m in ENTROPY_CANDIDATE_RE.finditer(text):
        s = m.group()
        core = strip_assignment_prefix(s)
        if len(core) < 24:
            # value half alone is short -- the length came from the var name
            continue
        if looks_like_low_entropy_noise(core):
            continue
        if shannon_entropy(core) >= ENTROPY_THRESHOLD:
            findings.append(("high-entropy string", redacted_preview(core)))

    return findings


def extract_output_text(payload):
    # Tool response shape varies by tool (Bash: stdout/stderr; Read: content;
    # MCP tools: arbitrary JSON) -- serialize whatever's there and scan it
    # all rather than special-casing each tool's schema.
    tr = payload.get("tool_response", payload.get("tool_output", ""))
    if isinstance(tr, (dict, list)):
        try:
            return json.dumps(tr, ensure_ascii=False)
        except Exception:
            return str(tr)
    return str(tr or "")


def log_finding(tool_name, findings):
    try:
        with open(LOG_FILE, "a") as f:
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            categories = ", ".join(sorted({c for c, _ in findings}))
            f.write(f"[{ts}] tool={tool_name} categories={categories} count={len(findings)}\n")
    except Exception:
        pass  # logging failure shouldn't block the hook from returning a verdict


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool_name = payload.get("tool_name", "") or ""

    # This repo's own hook directory holds the secret-guard source (full of
    # credential-shaped REGEX PATTERN strings) and its regression tests (full
    # of deliberately fake secrets -- dummy AWS keys, `AAAA...` blobs, sample
    # `/private_` URLs). Reading those files reliably trips this scanner with
    # nothing real behind it, which trains the reader to wave the warning
    # away -- the opposite of what a second-line alarm is for. A real secret
    # committed into a file here would be a separate incident caught by the
    # PreToolUse git-staging checks, not something this PostToolUse pass can
    # do anything about anyway. Scope the skip narrowly: Read only, this one
    # directory only.
    ti = payload.get("tool_input", {}) or {}
    fp = ti.get("file_path", "") if isinstance(ti, dict) else ""
    if tool_name == "Read" and isinstance(fp, str) and "/.claude/hooks/" in fp:
        sys.exit(0)

    text = extract_output_text(payload)
    if not text:
        sys.exit(0)

    findings = scan_text(text)
    if not findings:
        sys.exit(0)

    log_finding(tool_name, findings)

    categories = sorted({c for c, _ in findings})
    previews = "; ".join(f"{c}: {p}" for c, p in findings[:5])
    reason = (
        f"SECRET-SCAN WARNING: this {tool_name or 'tool'} output matched "
        f"{len(findings)} pattern(s) that look like a credential ({', '.join(categories)}). "
        f"This is an after-the-fact alarm -- the output already reached the transcript, so "
        f"treat the underlying credential as exposed now: stop, tell Flynn, and log a rotation "
        f"task via the `rotate` skill / Notion 'Credential Rotation Needed' page. Previews "
        f"(redacted, not the real values): {previews}"
    )
    print(json.dumps({"decision": "block", "reason": reason}))
    sys.exit(0)


if __name__ == "__main__":
    main()
