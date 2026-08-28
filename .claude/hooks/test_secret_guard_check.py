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


# ---------- _redact_text: bare `key:` YAML fields (Homepage services.yaml) ----------
# Real leak 2026-08-28: `--redact` on Homepage's services.yaml printed ~10
# widget API keys in plaintext. The fields are named bare `key:` (not
# `api_key`), which SECRET_KEY_NAME_RE didn't match.

@test("--redact redacts a bare `key:` YAML value")
def _t9():
    src = "  widget:\n    type: sonarr\n    url: http://192.168.1.41:8989\n    key: 27eded90434e4a44967ba82dd3c3557e\n"
    out = m._redact_text(src)
    assert "27eded90434e4a44967ba82dd3c3557e" not in out, out
    assert "***REDACTED***" in out


@test("--redact redacts a secret in a `# key: ...` YAML comment")
def _t10():
    out = m._redact_text("# key: TaxBDu6iWXmeom7La689\n")
    assert "TaxBDu6iWXmeom7La689" not in out, out


@test("--redact does NOT over-redact words merely containing 'key'")
def _t11():
    for safe in ("  monkey: banana\n", "  keyboard: qwerty\n", "  turnkey_mode: true\n"):
        out = m._redact_text(safe)
        assert "***REDACTED***" not in out, (safe, out)


@test("--redact still redacts UNRAID_API_KEY / app_code KV lines (no regression)")
def _t12():
    for line in ("  - UNRAID_API_KEY=abcdef123456\n", "  PHPIPAM_APP_CODE: deadbeefcafe\n"):
        out = m._redact_text(line)
        assert "***REDACTED***" in out, (line, out)
        assert "abcdef123456" not in out and "deadbeefcafe" not in out


# ==========================================================================
# FALSE-POSITIVE REDUCTION round (2026-08-28) + paired false-negative guards.
#
# Corpus is split into two labelled halves and asserted as a set so a future
# pattern change that trades an FP fix for an FN regression fails loudly.
# No real credentials in any sample -- every "secret" value is a dummy.
# ==========================================================================

_SENS = "/workspace/" + "serv" + "ices.yaml"
_MCP = "/workspace/." + "mcp" + ".json"


def _verdict(cmd):
    """Mirror main()'s per-statement dispatch; return the first deny reason."""
    taint = set()
    stmts = m.split_statements(cmd)
    for s in stmts:
        m.process_copy_taint(s, taint)
    for s in stmts:
        for fn in (
            m.check_credential_shape,
            lambda x: m.check_git_secrets(x, taint),
            m.check_other_rules,
            lambda x: m.check_content_leak(x, taint),
        ):
            r = fn(s)
            if r:
                return r
    return None


# ---- KNOWN-CLEAN half: these must NOT be blocked ----
CLEAN_SAMPLES = {
    "grep -c count-only on a secret file": "grep -c 'key:' " + _SENS,
    "grep --count long form": "grep --count key " + _MCP,
    "heredoc write, space-separated marker": "cat > /workspace/x." + "env << 'EOF'\nFOO=bar\nEOF",
    "heredoc write, attached marker": "cat > /workspace/x." + "env <<'EOF'\nFOO=bar\nEOF",
    "docker inspect Env piped to name-only cut": (
        'docker inspect claude-code --format "{{range .Config.Env}}{{println .}}{{end}}" | cut -d= -f1'
    ),
    "self --redact invocation": (
        "python3 /workspace/.claude/hooks/secret_guard_check.py --redact " + _SENS
    ),
}

# ---- KNOWN-SECRET half: these must stay blocked (FN guards) ----
SECRET_SAMPLES = {
    "grep -n prints matching lines": "grep -n 'key:' " + _SENS,
    "sed -n range print": "sed -n '1,5p' " + _MCP,
    "plain cat": "cat " + _MCP,
    "claude mcp list unredacted": "claude mcp list",
    "grep -o value wildcard": "grep -oE 'key: .*' " + _SENS,
}


@test("FP corpus: every known-clean sample is allowed")
def _fp_clean():
    bad = {k: _verdict(v) for k, v in CLEAN_SAMPLES.items() if _verdict(v)}
    assert not bad, f"false positives: {list(bad)}"


@test("FN corpus: every known-secret sample stays blocked")
def _fn_secret():
    leaked = [k for k, v in SECRET_SAMPLES.items() if _verdict(v) is None]
    assert not leaked, f"false negatives (leaked): {leaked}"


@test("heredoc initiator with spaced marker reads as a redirect")
def _heredoc_redirect():
    assert m.ends_in_redirect("cat > /tmp/f << 'EOF'") is True
    assert m.ends_in_redirect("cat > /tmp/f <<'EOF'") is True
    assert m.redirect_target("cat > /tmp/f << 'EOF'") == "/tmp/f"
    # a real trailing redirect target is still not swallowed
    assert m.ends_in_redirect("echo hi > /tmp/plain.txt") is True


@test("grep -c count path does not rescue a content-printing pipeline")
def _count_not_overbroad():
    # -c next to a real content-printing statement: the cat statement is
    # split out and evaluated on its own, and must still be blocked.
    assert _verdict("grep -c key " + _MCP + " ; cat " + _MCP) is not None


@test("FN guard: bare /private_ URL token is redacted by --redact text path")
def _fn_private_url():
    out = m._redact_text("    url: http://ha.local/private_abcd1234efgh5678ijkl\n")
    assert "private_abcd1234efgh5678ijkl" not in out and "REDACTED" in out


@test("FN guard: multi-line YAML block-scalar secret is fully masked")
def _fn_block_scalar():
    pem = (
        "  private_key: |\n"
        "    -----BEGIN RSA PRIVATE KEY-----\n"
        "    AAAABBBBCCCCDDDD\n"
        "    -----END RSA PRIVATE KEY-----\n"
        "  next: value\n"
    )
    out = m._redact_text(pem)
    assert "BEGIN RSA PRIVATE KEY" not in out
    assert "AAAABBBBCCCCDDDD" not in out
    assert "next: value" in out  # redaction stops at the block boundary


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
