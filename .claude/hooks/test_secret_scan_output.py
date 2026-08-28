#!/usr/bin/env python3
"""
Regression tests for secret_scan_output.py (the PostToolUse second-line
entropy / known-prefix scanner).

Same plain-assert style as test_secret_guard_check.py -- this repo has no
build/test tooling. Run: python3 /workspace/.claude/hooks/test_secret_scan_output.py

Focus of this round (2026-08-28): cut false positives without weakening any
real-secret detection. Every "secret" literal below is a dummy.
"""
import sys
import traceback

sys.path.insert(0, "/workspace/.claude/hooks")
import secret_scan_output as m  # noqa: E402

FAILURES = []


def test(name):
    def deco(fn):
        FAILURES.append((name, fn))
        return fn
    return deco


def cats(text):
    return {c for c, _ in m.scan_text(text)}


# ---------- FALSE POSITIVES that must now be suppressed ----------

@test("env assignment with a short dummy value no longer warns")
def _fp1():
    # the var NAME was inflating this past the 24-char candidate threshold
    assert cats("UNRAID_API_KEY=abcdef123456") == set()


@test("filesystem path is not a high-entropy finding")
def _fp2():
    assert "high-entropy string" not in cats(
        "matched /boot/config/plugins/dockerMan/templates-user/x.xml"
    )


@test("low-diversity padded/sequential blob is not a finding")
def _fp3():
    assert "high-entropy string" not in cats("blob AAAABBBBCCCCDDDDEEEEFFFFGGGG here")
    assert "high-entropy string" not in cats("x ABABABABABABABABABABABABABAB y")


@test("reading a file under .claude/hooks/ suppresses the scan entirely")
def _fp4():
    payload = {
        "tool_name": "Read",
        "tool_input": {"file_path": "/workspace/.claude" + "/hooks/" + "test_secret_guard_check.py"},
        "tool_response": "AKIAIOSFODNN7EXAMPLE and sk-ABCDEFGHIJKLMNOPQRSTUVWX",
    }
    import io
    import json
    import contextlib
    buf = io.StringIO()
    stdin_bak = sys.stdin
    sys.stdin = io.StringIO(json.dumps(payload))
    try:
        with contextlib.redirect_stdout(buf):
            try:
                m.main()
            except SystemExit:
                pass
    finally:
        sys.stdin = stdin_bak
    assert buf.getvalue().strip() == "", buf.getvalue()


# ---------- REAL detections that must STILL fire ----------

@test("known-prefix keys still detected (unchanged path)")
def _keep1():
    assert "AWS Access Key ID" in cats("key: AKIAIOSFODNN7EXAMPLE")
    assert "URL-embedded private_ token" in cats("http://ha.local/private_abcd1234efgh5678ijkl")
    assert "PEM private key block" in cats("-----BEGIN RSA PRIVATE KEY-----")


@test("a standalone high-entropy secret is still flagged")
def _keep2():
    assert "high-entropy string" in cats("value is k7Gx2pQ9mZ4vL8wRcnT6yB3dF5hJ0aVpW1uEoI")


@test("high-entropy value after KEY= is still flagged on its own merit")
def _keep3():
    assert "high-entropy string" in cats("SECRET=k7Gx2pQ9mZ4vL8wRcnT6yB3dF5hJ0aVpW1uEoI")


@test("base64-shaped secret (has + /) is not swallowed by the path filter")
def _keep4():
    assert "high-entropy string" in cats("tok dGhpcytzL2Jhc2U2NC9zZWNyZXQ+aGVyZQ==more")


@test("Bash output under a hooks path is NOT suppressed (skip is Read-only)")
def _keep5():
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "cat /workspace/.claude/hooks/x"},
        "tool_response": {"stdout": "AKIAIOSFODNN7EXAMPLE"},
    }
    import io
    import json
    import contextlib
    buf = io.StringIO()
    stdin_bak = sys.stdin
    sys.stdin = io.StringIO(json.dumps(payload))
    try:
        with contextlib.redirect_stdout(buf):
            try:
                m.main()
            except SystemExit:
                pass
    finally:
        sys.stdin = stdin_bak
    assert "AWS Access Key ID" in buf.getvalue()


def main():
    passed, failed = 0, 0
    for name, fn in FAILURES:
        try:
            fn()
        except Exception as e:
            failed += 1
            print(f"FAIL: {name}")
            print("  " + "".join(traceback.format_exception_only(type(e), e)).strip())
        else:
            passed += 1
            print(f"PASS: {name}")
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
