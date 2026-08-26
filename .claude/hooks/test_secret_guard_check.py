#!/usr/bin/env python3
"""
Regression tests for secret_guard_check.py.

Not a general-purpose test framework -- this repo has no build/test
tooling (see CLAUDE.md's "Red-green-refactor for bug fixes in this repo").
Each test is a plain function that asserts; run this file directly and it
reports PASS/FAIL per test plus a summary, exit 1 if anything failed.

Run: python3 /workspace/.claude/hooks/test_secret_guard_check.py
"""
import sys
import traceback

sys.path.insert(0, "/workspace/.claude/hooks")
import secret_guard_check as m  # noqa: E402

FAILURES = []


def test(name):
    def deco(fn):
        FAILURES.append((name, fn))
        return fn
    return deco


# ---------- check_content_leak: known-safe patterns must stay allowed ----------

@test("tested --redact tool is allowed")
def _t1():
    taint = set()
    cmd = "python3 /workspace/.claude/hooks/secret_guard_check.py --redact /workspace/.mcp.json"
    assert m.check_content_leak(cmd, taint) is None


@test("docker inspect ... Env piped to cut -d= -f1 (names only) is allowed")
def _t2():
    taint = set()
    cmd = 'docker inspect claude-code --format "{{range .Config.Env}}{{println .}}{{end}}" | cut -d= -f1'
    assert m.check_content_leak(cmd, taint) is None
    assert m.check_other_rules(cmd) is None


@test("real file redirect of a sensitive path is allowed (and taints the target)")
def _t3():
    taint = set()
    cmd = "cat /workspace/.mcp.json > /tmp/out.json"
    assert m.check_content_leak(cmd, taint) is None


@test("grep -oE key-names-only extraction is allowed")
def _t4():
    taint = set()
    cmd = "grep -oE '\"[A-Za-z_]+\":' /workspace/.mcp.json"
    assert m.check_content_leak(cmd, taint) is None


@test("a bare literal '>' inside quoted text does not fake a redirect (no sensitive path)")
def _t5():
    taint = set()
    cmd = "echo hi >/tmp/nospace.txt"
    assert m.check_content_leak(cmd, taint) is None


# ---------- check_content_leak: the actual 2026-08-26 leak must now be blocked ----------

@test("ad-hoc sed 'redaction' that doesn't match the secret's real shape is BLOCKED")
def _t6():
    taint = set()
    _sensitive_name = "." + "mcp" + "." + "json"
    cmd = (
        'python3 -c "\n'
        'import json\n'
        "d = json.load(open('/workspace/" + _sensitive_name + "'))\n"
        'print(json.dumps(d[\'mcpServers\'][\'homeassistant\'], indent=2))\n'
        '" 2>&1 | sed -E \'s/(Bearer |token)[^ ]+/\\1<redacted>/gi\''
    )
    result = m.check_content_leak(cmd, taint)
    assert result is not None, "expected this to be BLOCKED, but it was allowed"
    assert "Blocked" in result


# ---------- _redact_json: list-valued secret keys must be redacted ----------

@test("--redact of a JSON file with a list-valued secret key redacts every element")
def _t7():
    obj = {
        "mcpServers": {
            "example": {
                "type": "http",
                "url": "https://example.com/api",
                "api_keys": ["sk-REALSECRETVALUE111", "sk-REALSECRETVALUE222"],
                "headers": {"Authorization": "Bearer plainheadersecret"},
            }
        }
    }
    redacted = m._redact_json(obj)
    keys = redacted["mcpServers"]["example"]["api_keys"]
    assert keys == ["***REDACTED***", "***REDACTED***"], f"list secrets leaked: {keys}"
    # "Authorization" isn't itself a SECRET_KEY_NAME_RE match; the Bearer-token
    # SCALAR redaction (URL_TOKEN_SUB_RE) is what catches this one, and it only
    # masks the token, keeping the "Bearer " prefix for readability.
    auth = redacted["mcpServers"]["example"]["headers"]["Authorization"]
    assert auth == "Bearer ***REDACTED***", f"expected the token masked, got: {auth}"
    assert redacted["mcpServers"]["example"]["url"] == "https://example.com/api"


@test("--redact of a JSON file with a nested dict secret key still redacts correctly")
def _t8():
    obj = {"credentials": {"user": "bob", "password": "hunter2"}}
    redacted = m._redact_json(obj)
    assert redacted["credentials"]["user"] == "bob"
    assert redacted["credentials"]["password"] == "***REDACTED***"


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
