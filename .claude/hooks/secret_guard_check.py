#!/usr/bin/env python3
"""
Core decision engine for secret-guard.sh's Bash-command checks.

Rewritten from a pure-bash/regex implementation after adversarial testing
kept finding statement-boundary bugs: grep/sed's `$` anchors to the end of
EVERY line on multi-line input (not just the whole string), so a naive
"does this command end in a redirect" check got fooled by an EARLIER line's
`>` when a later, unrelated line (e.g. a trailing `cat sensitive.json`)
should have been evaluated on its own. A follow-up fix that split on real
newlines then broke heredocs (`cat > file <<'EOF' ... EOF`), since heredoc
bodies contain real newlines but aren't separate shell statements.

This version properly tracks heredoc boundaries and evaluates each real
statement independently, using shlex for quote-aware tokenizing instead of
whitespace-splitting (which shattered quoted JSON blobs into garbage tokens).

Usage: secret_guard_check.py <command-text-on-stdin>
Output: a single line, "ALLOW" or "DENY:<reason>". Exit code is always 0;
the caller (secret-guard.sh) decides what to do with the verdict.
"""
import os
import re
import shlex
import sys

TAINT_FILE = "/workspace/.claude/hooks/.secret_taint"

SENSITIVE_BASENAME_RE = re.compile(
    r"^(compose\.ya?ml|services\.ya?ml|settings\.local\.json|\.mcp\.json|secrets\.ya?ml|.*\.env)$", re.I
)
SENSITIVE_KEY_RE = re.compile(r"(^|/)id_(rsa|dsa|ecdsa|ed25519)[A-Za-z0-9_]*$")
VALUE_REVEALING_RE = re.compile(
    r'\.url\b|"url"|\'url\'|\.token\b|"token"|\'token\'|password|secret|private_|'
    r'api_?key|\.get\(|\[["\']?(url|token|key|password|secret|env)["\']?\]|\.env\b',
    re.I,
)
CONTENT_TOOL_RE = re.compile(
    r"\b(cat|less|more|bat|jq|yq|python[0-9.]*|base64|xxd|od|hexdump|dd|strings|awk|head|tail|sed|nl|pr)\b",
    re.I,
)
GREP_RE = re.compile(r"\bgrep\b", re.I)
GREP_CONTEXT_FLAGS_RE = re.compile(
    r"(^|[\s])-[A-Za-z]*[ABC][A-Za-z]*([\s]|$|[0-9])|--(after|before|context)-context\b"
)
GREP_ONLY_MATCHING_RE = re.compile(r"(^|[\s])(-[A-Za-z]*o[A-Za-z]*([\s]|$)|--only-matching\b)")
GREP_VALUE_WILDCARD_RE = re.compile(r"\.\*|\.\+|\[\^")
REDACTED_PIPE_RE = re.compile(r"\bsed\b.*REDACTED", re.I)
# `sed -i` edits the file in place and (absent -n + an explicit `p` command,
# which is unusual and easy to eyeball-catch separately) produces NO stdout
# -- nothing lands in the transcript. Without this, any in-place edit of a
# newly-protected sensitive path (e.g. inserting a <Config> line into an
# Unraid template) gets wrongly denied by the generic content-leak rule,
# which was written for tools that print content, not tools that only write.
# User-authorized 2026-08-20 ("Yes, add a sed -i carve-out") after the
# phpIPAM template-XML fix (above) blocked a legitimate sed -i insert.
SED_INPLACE_NO_PRINT_RE = re.compile(r"\bsed\b[^|;]*\s-[A-Za-z]*i[A-Za-z]*(\s|$)")
SED_EXPLICIT_PRINT_RE = re.compile(r"\bsed\b[^|;]*\s-[A-Za-z]*n[A-Za-z]*(\s|$).*\bp\b|/p(['\"]|\s|$)")
KEYS_WORD_RE = re.compile(r"\bkeys\b")
# Allows an optional trailing heredoc marker after the target -- `cat > file
# <<'EOF'` genuinely redirects cat's stdout to `file`; the heredoc marker
# just supplies its stdin and doesn't change that. Target chars exclude `<`
# so the match stops before reaching the marker instead of swallowing it.
ENDS_IN_REDIRECT_RE = re.compile(r">>?\s*([^&|;\s<]+)\s*(?:<<-?\s*[\"']?\w+[\"']?)?\s*$")
TEE_RE = re.compile(r"\btee\b", re.I)
DEVSTDOUT_RE = re.compile(r">\s*/dev/(stdout|tty)")


# ---------- heredoc-aware statement splitting ----------

def split_statements(cmd):
    """Split a (possibly multi-line) command into individual logical
    statements. Heredoc bodies (and their terminator line) are consumed and
    dropped -- they're data, not statements; the initiating line (which
    still shows whether the heredoc's *own* command redirects output) is
    kept as one atomic statement. Everything else is split on ; && || | and
    real newlines."""
    lines = cmd.split("\n")
    statements = []
    heredoc_marker = None
    strip_tabs = False
    i, n = 0, len(lines)
    heredoc_start_re = re.compile(r"<<(-?)\s*([\"']?)(\w+)\2")
    while i < n:
        line = lines[i]
        if heredoc_marker is not None:
            check = line.lstrip("\t") if strip_tabs else line
            if check == heredoc_marker:
                heredoc_marker = None
            i += 1
            continue
        m = heredoc_start_re.search(line)
        if m:
            strip_tabs = m.group(1) == "-"
            heredoc_marker = m.group(3)
            stripped = line.strip()
            if stripped:
                statements.append(stripped)
            i += 1
            continue
        # NB: deliberately NOT splitting on a bare "|" -- a pipeline
        # (`cmd1 | cmd2`) is one atomic data-flow unit, and safety
        # mitigations like `| sed ... REDACTED` or `| cut -d= -f1` only work
        # if analyzed together with what they're piped from. Splitting on it
        # (tried during testing) broke exactly that: `claude mcp list | sed
        # ...REDACTED...` got shattered into two pieces and denied, because
        # the first piece alone doesn't contain the word REDACTED.
        for part in re.split(r";|&&|\|\|", line):
            part = part.strip()
            if part:
                statements.append(part)
        i += 1
    return statements


# ---------- taint tracking ----------

def _canon(p):
    try:
        return os.path.realpath(p) if p else p
    except Exception:
        return p


def load_taint():
    try:
        with open(TAINT_FILE) as f:
            return set(line.rstrip("\n") for line in f)
    except FileNotFoundError:
        return set()


def taint_path(p, cache):
    if not p:
        return
    canon = _canon(p)
    if canon in cache:
        return
    cache.add(canon)
    try:
        with open(TAINT_FILE, "a") as f:
            f.write(canon + "\n")
    except Exception:
        pass


UNRAID_FLASH_SECRET_RE = re.compile(
    r"/boot/config/(passwd|shadow|smbpasswd|secrets\.tdb|ident\.cfg)$|"
    r"/boot/config/(ssh|ssl|wireguard)/|"
    r"/boot/config/[^/]+\.key$",
    re.I,
)

# Unraid Docker Community-Applications templates (both user overrides and the
# CA cache copy) routinely embed live credentials as <Config> element values
# -- e.g. IPAM_DATABASE_PASS in a phpIPAM template. The `Mask="true"`
# attribute on a <Config> tag only controls masking in Unraid's *web UI*; it
# has zero effect on the raw file content, so any command that prints whole
# <Config> lines (not just their Name= attributes) leaks the plaintext value
# just like compose.yaml/services.yaml would. Confirmed real incident
# 2026-08-20: `grep -n '<Config' my-phpIPAM-www.xml` printed IPAM_DATABASE_PASS
# in plaintext while only the Config *structure* was needed.
UNRAID_DOCKER_TEMPLATE_RE = re.compile(
    r"/boot/config/plugins/dockerMan/templates-(user|community)/.*\.xml$", re.I,
)


def is_sensitive_path(p, taint_cache):
    if not p:
        return False
    base = os.path.basename(p)
    if SENSITIVE_BASENAME_RE.match(base):
        return True
    if SENSITIVE_KEY_RE.search(p) and not p.endswith(".pub"):
        return True
    if UNRAID_FLASH_SECRET_RE.search(p):
        return True
    if UNRAID_DOCKER_TEMPLATE_RE.search(p):
        return True
    if os.path.exists(p):
        try:
            real = os.path.realpath(p)
        except Exception:
            real = None
        if real:
            if SENSITIVE_BASENAME_RE.match(os.path.basename(real)):
                return True
            if real in taint_cache:
                return True
    canon = _canon(p)
    if canon in taint_cache:
        return True
    return False


def tokenize(stmt):
    try:
        return shlex.split(stmt)
    except ValueError:
        return stmt.split()


SENSITIVE_BASENAME_SUBSTRING_RE = re.compile(
    # \.env\b (not a bare ".env" without the trailing boundary) so
    # "app.environment" doesn't false-positive -- \b requires a non-word char
    # (or end of string) right after "env", which "ironment" doesn't have.
    # The /boot/config/... alternatives are Unraid flash-drive config paths
    # confirmed to hold real secrets: passwd/shadow/smbpasswd (Unix/Samba
    # password hashes), secrets.tdb (Samba domain-join secrets), ident.cfg
    # (has a DOMAIN_PASSWD field, confirmed via a keys-only scan), the ssh/
    # ssl/wireguard subdirectories (host keys, webGUI TLS private key, VPN
    # configs), and *.key files directly under /boot/config (license keys).
    # Path-scoped (not bare basenames like "passwd") since those basenames
    # alone are too generic/common to safely blanket-match everywhere.
    r"(compose\.ya?ml|services\.ya?ml|settings\.local\.json|\.mcp\.json|secrets\.ya?ml|\.env\b|"
    r"/boot/config/(passwd|shadow|smbpasswd|secrets\.tdb|ident\.cfg)\b|"
    r"/boot/config/(ssh|ssl|wireguard)/|"
    r"/boot/config/[^/\s]+\.key\b|"
    r"/boot/config/plugins/dockerMan/templates-(user|community)/[^\s\"']*\.xml\b)",
    re.I,
)


SCRIPT_INTERPRETER_RE = re.compile(
    r"^(python[0-9.]*|bash|sh|zsh|perl|ruby|node|nodejs)$", re.I
)


INLINE_FLAG_RE = re.compile(r"^(-c|-e|--command)$")


def _file_source_mentions_sensitive(path):
    if not os.path.isfile(path):
        return False
    try:
        with open(path, "r", errors="ignore") as f:
            src = f.read()
    except Exception:
        return False
    return bool(SENSITIVE_BASENAME_SUBSTRING_RE.search(src))


def _scan_tokens_for_interpreter(toks, depth=0):
    # Found via adversarial testing (2026-08-21): checking only toks[0] for
    # an interpreter missed every wrapper prefix -- `bash -c '...'`, `env
    # python3 x.py`, `timeout 10 python3 x.py`, `nohup python3 x.py &`.
    # Scanning every token position for an interpreter-looking name (rather
    # than assuming it's first) catches all of those without needing to
    # special-case each wrapper command by name.
    if depth > 3:
        return False
    for i, t in enumerate(toks):
        if not SCRIPT_INTERPRETER_RE.match(os.path.basename(t)):
            continue
        j = i + 1
        while j < len(toks):
            nt = toks[j]
            if INLINE_FLAG_RE.match(nt):
                if j + 1 >= len(toks):
                    break
                inline = toks[j + 1]
                if SENSITIVE_BASENAME_SUBSTRING_RE.search(inline):
                    return True
                try:
                    inner_toks = shlex.split(inline)
                except ValueError:
                    inner_toks = inline.split()
                for it in inner_toks:
                    if _file_source_mentions_sensitive(it):
                        return True
                if _scan_tokens_for_interpreter(inner_toks, depth + 1):
                    return True
                break
            if nt.startswith("-"):
                j += 1
                continue
            if _file_source_mentions_sensitive(nt):
                return True
            break
    return False


def _script_source_mentions_sensitive(stmt):
    # Real incident (2026-08-21, HA MCP token in .mcp.json's url field): a
    # homemade Python redaction script hardcoded the sensitive file's path
    # INSIDE its own source rather than taking it as a CLI argument. The
    # Bash command text that invoked it (e.g. `python3 redact.py`) never
    # mentioned ".mcp.json" anywhere, so the raw-substring/tokenized checks
    # below both missed it entirely and the (flawed) script ran unchecked.
    # Close that class generically: if a command runs an interpreter against
    # a local script file, look inside that file for a sensitive-filename
    # mention before trusting the command line alone.
    toks = tokenize(stmt)
    if not toks:
        return False
    return _scan_tokens_for_interpreter(toks)


def statement_mentions_sensitive_path(stmt, taint_cache):
    # Raw substring search first -- catches a sensitive filename embedded
    # inside a larger token (e.g. `python3 -c "print(open('settings.local.
    # json').read())"`, where the filename isn't its own shlex token, so a
    # tokenized-path check alone misses it). This mirrors the original
    # (pre-rewrite) implementation's primary check.
    if SENSITIVE_BASENAME_SUBSTRING_RE.search(stmt):
        return True
    for tok in tokenize(stmt):
        if is_sensitive_path(tok, taint_cache):
            return True
    if _script_source_mentions_sensitive(stmt):
        return True
    return False


# ---------- redirect helpers (per statement, not per whole command) ----------

HEREDOC_MARKER_TOKEN_RE = re.compile(r"^<<-?[\"']?\w+[\"']?$")


def _redirect_info(stmt):
    """Token-aware replacement for a raw string-tail regex.

    Real incident (2026-08-26): ENDS_IN_REDIRECT_RE matched a bare '>' inside
    a *quoted* sed replacement string (`.../<redacted>/gi'`) and mistook it
    for a real shell redirect to a file named after the trailing quote/flags,
    wrongly marking a content-leaking statement as "safe, redirected to a
    file". A literal '>' can appear anywhere inside quoted text (redaction
    placeholders like `<redacted>`/`<REMOVED>`, HTML-ish snippets, `a > b`
    comparisons in scripts) without being a shell operator at all. shlex-based
    tokenizing already strips quotes into single words, so a quoted chunk
    containing '>' becomes one token that doesn't itself start with '>' --
    checking the token stream instead of the raw string closes this class
    generically, the same way `tokenize()` already fixed quoted-blob
    mis-splitting elsewhere in this file.
    """
    toks = tokenize(stmt)
    while toks and HEREDOC_MARKER_TOKEN_RE.match(toks[-1]):
        toks.pop()
    if not toks:
        return False, None

    last = toks[-1]
    if last in (">", ">>"):
        return False, None  # dangling operator, no target -- not a real redirect
    if last.startswith(">>"):
        return True, last[2:]
    if last.startswith(">"):
        return True, last[1:]
    if len(toks) >= 2 and toks[-2] in (">", ">>"):
        return True, last
    return False, None


def ends_in_redirect(stmt):
    is_redirect, _ = _redirect_info(stmt)
    if not is_redirect:
        return False
    if TEE_RE.search(stmt):
        return False
    if DEVSTDOUT_RE.search(stmt):
        return False
    return True


def redirect_target(stmt):
    _, target = _redirect_info(stmt)
    return target


def keys_only_safe(stmt):
    return bool(KEYS_WORD_RE.search(stmt)) and not VALUE_REVEALING_RE.search(stmt)


# `cut -d= -f1` on KEY=VALUE lines (e.g. from `docker inspect --format
# '{{range .Config.Env}}{{println .}}{{end}}'`) keeps only the field before
# the first `=` -- the variable NAME, discarding the value. This is exactly
# the safe pattern check_other_rules' own docker-inspect deny message
# recommends, but nothing previously recognized it as safe: found via
# regression testing that the hook's own suggested remediation got denied
# by itself.
NAME_ONLY_CUT_RE = re.compile(r"\bcut\b[^|;]*-d\s*['\"]?=['\"]?[^|;]*-f\s*1\b", re.I)


# ---------- cp/mv/scp/rsync/docker-cp taint propagation ----------

COPY_PATTERNS = [
    (re.compile(r"^(cp|mv)(\s|$)"), {"cp", "mv"}),
    (re.compile(r"^scp(\s|$)"), {"scp"}),
    (re.compile(r"^rsync(\s|$)"), {"rsync"}),
    (re.compile(r"^docker\s+cp(\s|$)"), {"docker", "cp"}),
]


def process_copy_taint(stmt, taint_cache):
    for pattern, cmdwords in COPY_PATTERNS:
        if not pattern.match(stmt):
            continue
        toks = tokenize(stmt)
        # Trailing shell constructs (2>&1, >/dev/null, &, ...) aren't the
        # real destination argument -- strip them before treating the last
        # remaining token as one.
        while toks and (re.match(r"^\d*>{1,2}.*$", toks[-1]) or toks[-1] == "&"):
            toks.pop()
        if len(toks) < 3:
            continue
        dest = toks[-1]
        src_sensitive = False
        for t in toks[:-1]:
            if t in cmdwords or t.startswith("-"):
                continue
            if is_sensitive_path(t, taint_cache):
                src_sensitive = True
        if src_sensitive:
            taint_path(dest, taint_cache)
        return  # only one copy-pattern can match a given statement


# ---------- other command-specific rules (per statement) ----------

def check_other_rules(stmt):
    """Returns a deny reason string, or None."""
    low = stmt

    if re.search(r"\bclaude\b.*\bmcp\b.*\b(list|get)\b", low, re.I) and not REDACTED_PIPE_RE.search(low):
        return ("Blocked: 'claude mcp list/get' prints full server URLs including embedded tokens in "
                "plaintext, with no suppressing flag. Pipe through a redaction filter, e.g.: "
                "claude mcp list 2>&1 | sed -E 's#(https?://[^ ]*private_)[A-Za-z0-9_-]+#\\1[REDACTED]#g'")

    if re.search(r"\bdocker\b.*\binspect\b", low, re.I) and re.search(r"\benv\b|\.Config\.Env", low, re.I) \
       and not ends_in_redirect(low) and not keys_only_safe(low) and not NAME_ONLY_CUT_RE.search(low):
        return ("Blocked: 'docker inspect ... Env' dumps the full container environment, including "
                "secrets, in plaintext. To check for a var's existence/name only, filter to names: e.g. "
                "docker inspect <c> --format '{{range .Config.Env}}{{println .}}{{end}}' | cut -d= -f1")

    if re.search(r"\bdocker\b.*\bexec\b", low, re.I) and re.search(r"\b(printenv|env)\s*(2>&1)?\s*$", low) \
       and not ends_in_redirect(low) and not keys_only_safe(low) and not NAME_ONLY_CUT_RE.search(low):
        return ("Blocked: 'docker exec ... env/printenv' dumps the full in-container environment, "
                "including secrets, in plaintext. Filter to names only: e.g. docker exec <c> env | cut -d= -f1 "
                "-- or check one specific var's presence with 'docker exec <c> printenv VARNAME >/dev/null && echo set'.")

    if re.search(r"\bunraid-api\b.*\bapikey\b", low, re.I) and "--delete" not in low and not ends_in_redirect(low):
        return ("Blocked: 'unraid-api apikey' prints the key value in plaintext with no suppressing flag "
                "(only --delete avoids this). Redirect to a file instead of printing (> path), or "
                "create/rotate the key through the Unraid webGUI where it's never in this transcript.")

    if re.search(r"\bdocker\b\s+cp\b", low, re.I) and re.search(r"(^|\s)-\s*$", low) and not ends_in_redirect(low):
        # only a real risk if the source looks like it names a sensitive file
        toks = tokenize(low)
        if any(SENSITIVE_BASENAME_RE.match(os.path.basename(t.split(":")[-1])) for t in toks if ":" in t or "/" in t):
            return ("Blocked: 'docker cp <container>:path -' streams the file's content (as a tar archive) "
                    "to stdout -- same risk as cat. Copy to a real destination path instead of '-', or check "
                    "existence with 'docker exec <c> test -f <path> && echo exists'.")

    if re.search(r"\bmongo(sh)?\b", low, re.I) and re.search(r"\bfind(One)?\(", low) and not ends_in_redirect(low):
        if _mongo_unprojected(low):
            return ("Blocked: an unprojected MongoDB find/findOne against UniFi's embedded DB returns the "
                    "full matching document(s), which can include credentials -- CLAUDE.md mandates a "
                    "projected query. Add a second {field: 1} projection argument, e.g. "
                    "db.setting.findOne({_id: '...'}, {specificField: 1}).")

    unifi_reason = check_unifi_rest(low)
    if unifi_reason:
        return unifi_reason

    return None


# UniFi's classic REST API (rest/account, rest/radius*, rest/vpn*, rest/wlanconf)
# returns full objects on a bare GET, same "unprojected query" risk class as the
# Mongo case above -- confirmed real incident (Notion): a VPN/RADIUS password and
# a RADIUS server's private key/certs both leaked this way in a past session.
UNIFI_REST_RISKY_RE = re.compile(r"/rest/(account|radius\w*|vpn\w*|wlanconf)\b", re.I)


def check_unifi_rest(stmt):
    if not re.search(r"\bcurl\b", stmt, re.I):
        return None
    if not UNIFI_REST_RISKY_RE.search(stmt):
        return None
    if ends_in_redirect(stmt) or REDACTED_PIPE_RE.search(stmt):
        return None
    # Safe if piped through jq with a real (non-bare-".") field filter.
    m = re.search(r"\bjq\b\s+(-[A-Za-z]+\s+)?[\"']?([^\"'\n|]+)", stmt)
    if m and m.group(2).strip() not in (".", ""):
        return None
    return ("Blocked: this curl call targets a UniFi REST endpoint known to return credential-bearing "
            "objects in full (rest/account, rest/radius*, rest/vpn*, rest/wlanconf can all include "
            "passwords/PSKs/certs) -- the same unprojected-query risk CLAUDE.md flags for Mongo applies "
            "here too. Pipe through jq with a specific field filter (not bare '.'), e.g. "
            "... | jq '.data[].name', or redirect to a file instead of printing.")


def _mongo_unprojected(cmd):
    for m in re.finditer(r"find(One)?\s*\(", cmd):
        depth = 0
        top_level_comma = False
        for c in cmd[m.end() - 1:]:
            if c in "([{":
                depth += 1
            elif c in ")]}":
                depth -= 1
                if depth == 0:
                    break
            elif c == "," and depth == 1:
                top_level_comma = True
        if not top_level_comma:
            return True
    return False


# ---------- main content-leak check (per statement) ----------

SELF_REDACT_INVOKE_RE = re.compile(r"secret_guard_check\.py['\"]?\s+--(redact|read|check)\b")


def check_content_leak(stmt, taint_cache):
    """Returns a deny reason string, or None. Also performs taint
    propagation as a side effect when a redirect is what makes it safe."""
    # The redactor itself necessarily mentions sensitive filenames in its own
    # invocation (`secret_guard_check.py --redact .mcp.json`) -- without this
    # carve-out the hook would deny the very tool it tells Claude to use.
    if SELF_REDACT_INVOKE_RE.search(stmt):
        return None
    mentions_sensitive = statement_mentions_sensitive_path(stmt, taint_cache)
    if not mentions_sensitive:
        return None

    has_grep = bool(GREP_RE.search(stmt))
    has_content_tool = bool(CONTENT_TOOL_RE.search(stmt))
    if not (has_grep or has_content_tool):
        return None

    # sed -i in-place edit with no explicit print -- writes to the file,
    # nothing to stdout/transcript. Only applies when sed is the sole
    # content-tool match in this statement (an `-i` flag doesn't make some
    # OTHER tool in the same pipeline safe).
    if has_content_tool and re.search(r"\bsed\b", stmt, re.I) and not has_grep:
        other_content_tools = CONTENT_TOOL_RE.findall(stmt)
        if all(t.lower() == "sed" for t in other_content_tools):
            if SED_INPLACE_NO_PRINT_RE.search(stmt) and not SED_EXPLICIT_PRINT_RE.search(stmt):
                return None

    if has_grep and GREP_CONTEXT_FLAGS_RE.search(stmt):
        return ("Blocked: grep with -A/-B/-C context flags against a file known to hold plaintext secrets "
                "(directly, via symlink, or as a tracked copy). Context flags pull KEY=VALUE or 'key: <secret>' "
                "lines into the transcript. Use 'grep -n <pattern> <file>' for line numbers only, then edit "
                "by line/pattern with sed, or read specific known-safe lines.")

    # NOT trusted here (real incident, 2026-08-26): REDACTED_PIPE_RE only checks
    # that the literal word "redacted" appears somewhere after `sed` -- it can't
    # verify the sed pattern actually matches the secret's real shape. A `python3
    # -c` one-liner printed .mcp.json's embedded HA MCP URL (secret is a bare
    # `/private_XXXX` path segment, not a `token`/`Bearer`-prefixed value); the
    # piped `sed 's/(Bearer |token...)...<redacted>/'` never matched that shape,
    # so the real secret passed straight through to the transcript while this
    # check waved it through on the word "redacted" alone. Ad-hoc sed/awk
    # "redaction" of a sensitive-path statement is no longer trusted at all --
    # only the tested `--redact` tool (SELF_REDACT_INVOKE_RE, checked above),
    # a real redirect, or a genuine keys-only extraction are accepted.
    is_redirected = ends_in_redirect(stmt)
    is_keys_only = keys_only_safe(stmt)

    if is_redirected and not is_keys_only:
        taint_path(redirect_target(stmt), taint_cache)

    if is_redirected or is_keys_only:
        return None

    if has_grep:
        has_only_matching = bool(GREP_ONLY_MATCHING_RE.search(stmt))
        has_value_wildcard = bool(GREP_VALUE_WILDCARD_RE.search(stmt))
        if has_only_matching and not has_value_wildcard:
            return None

    if UNRAID_DOCKER_TEMPLATE_RE.search(stmt) or "templates-user" in stmt or "templates-community" in stmt:
        return ("Blocked: Unraid docker-template XML (templates-user/templates-community) can hold live "
                "credentials as <Config> element values -- Mask=\"true\" only affects the Unraid web UI, "
                "NOT the raw file, so a plain grep/cat still prints the plaintext value (confirmed incident: "
                "IPAM_DATABASE_PASS leaked this way). Extract Name= attributes only, e.g. "
                "grep -oE 'Name=\"[A-Za-z0-9_ ]*\"' file.xml, or redirect full output to a file instead of "
                "printing it.")

    return ("Blocked: this command could print the contents (or a value) of a file known to hold plaintext "
            "secrets (directly, via symlink, via a script that reads it internally, or as a tracked copy of "
            "compose.yaml/services.yaml/settings.local.json/.mcp.json) to the visible tool output. Use the "
            "tested redactor rather than writing a new one-off script -- past ad hoc scripts have missed "
            "cases (e.g. a token embedded in a JSON 'url' field, not just env/headers dict values): "
            "python3 /workspace/.claude/hooks/secret_guard_check.py --redact '<path>' -- or extract key "
            "NAMES only (jq/python '...keys...', or grep -oE with a key-name-only pattern), or redirect full "
            "output to a file instead of printing it (> path, no later pipe/tee).")


# Confirmed real incident (Notion, docker-deploy repo, different host): a
# .s3_upload.env with a live app password and a docker-compose.yml with
# hardcoded DB/admin passwords were committed to git as the repo's root
# commit -- permanent history, not a transcript-only exposure. That same
# workspace already has a separate secret-scan pre-commit hook elsewhere
# that was bypassed with --no-verify, which is the strongest signal that
# --no-verify itself deserves scrutiny alongside the staged files.
GIT_STAGE_RE = re.compile(r"^git\s+(add|commit)\b")
GIT_BROAD_ADD_RE = re.compile(r"(^|\s)(-A|--all)(\s|$)")


def check_git_secrets(stmt, taint_cache):
    if not GIT_STAGE_RE.match(stmt.strip()):
        return None
    toks = tokenize(stmt)
    is_commit = toks[1] == "commit" if len(toks) > 1 else False

    if is_commit and "--no-verify" in toks:
        return ("Blocked: 'git commit --no-verify' skips any pre-commit secret-scan hook that may be "
                "configured on this repo. A real incident bypassed exactly this kind of hook and "
                "committed live credentials to history. Commit without --no-verify, or if a hook is "
                "genuinely misfiring on non-secret content, fix/adjust the hook rather than bypassing it.")

    risky = [t for t in toks[2:] if not t.startswith("-")
             and (SENSITIVE_BASENAME_RE.match(os.path.basename(t)) or is_sensitive_path(t, taint_cache))]
    if risky:
        return ("Blocked: 'git " + toks[1] + "' names a file known to hold plaintext secrets (" +
                ", ".join(risky) + "). Committing it puts the secret in git history permanently, which "
                "is worse than a transcript exposure -- it survives even after rotation until history is "
                "rewritten. gitignore it instead, or if it must be tracked, confirm its current content "
                "is safe (e.g. a template with placeholder values, not live credentials) first.")

    if toks[1] == "add" and GIT_BROAD_ADD_RE.search(stmt):
        return ("Blocked: 'git add -A/--all' stages the entire working tree, which can't be statically "
                "verified safe -- it may pick up a .env/secrets.yaml/compose.yaml or similar file created "
                "or modified earlier in this session. Stage specific paths instead, or run 'git status' "
                "first to see what would be included.")

    return None


# A credential typed *directly* into a command is exposed by the command
# text itself, appearing in the transcript as the tool-call input -- output
# redirection doesn't help here (unlike every other check above) since the
# secret is already visible before the command even runs. This matches
# CLAUDE.md's existing rule for this container ("never type a password/API
# key directly into a Bash command... read/write credentials programmatically
# so the literal secret never appears in a tool call"); a separate incident
# elsewhere (an S3 secret key pasted in plaintext during recovery work) gave
# the concrete shapes worth pattern-matching.
CREDENTIAL_SHAPE_PATTERNS = [
    ("AWS access key ID", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("PEM private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("Bearer token", re.compile(r"[Aa]uthorization[\"']?\s*[:=]\s*[\"']?Bearer\s+[A-Za-z0-9\-_.=]{16,}")),
]


def check_credential_shape(stmt):
    for name, pattern in CREDENTIAL_SHAPE_PATTERNS:
        if pattern.search(stmt):
            return (f"Blocked: this command appears to contain a literal {name} typed directly into it. "
                    "The command text itself is visible in the transcript regardless of what the command "
                    "does or where its output goes -- redirecting output doesn't help here. Read the "
                    "credential from a file or environment variable set outside this command instead (e.g. "
                    "a script that sources it, or '--header \"Authorization: Bearer $TOKEN\"' with $TOKEN "
                    "already exported), so the literal value never appears as a tool-call argument.")
    return None


# ---------- canonical redaction mode ----------
#
# Added 2026-08-21 after a homemade one-off Python redaction script (written
# ad hoc to inspect .mcp.json's structure) only redacted `env`/`headers`
# dict values and missed that this MCP server's config embeds its
# long-lived token directly in the `url` string instead -- printing it in
# plaintext. Rather than rely on someone re-deriving correct redaction logic
# under time pressure each time, this gives a single tested implementation
# every deny message can point to.
import json

SECRET_KEY_NAME_RE = re.compile(
    r"password|secret|token|api[_-]?key|apikey|private_|pass\b|pwd|credential|"
    # phpIPAM's PHPIPAM_APP_CODE functions as an API credential (paired with
    # PHPIPAM_APP_ID to authenticate) but doesn't match any generic secret-shaped
    # substring above. Confirmed real leak 2026-08-24: printed in plaintext by
    # --redact when reading compose.yaml. Scoped to "app_code"/"app-code" (not
    # bare "code") to avoid false-positiving on unrelated fields like
    # STATUS_CODE/ZIP_CODE/COUNTRY_CODE.
    r"app[_-]?code",
    re.I
)
URL_TOKEN_SUB_RE = re.compile(
    r"(private_|token=|api[_-]?key=|apikey=|Bearer\s+)([A-Za-z0-9_\-\.]{6,})", re.I
)
URL_USERPASS_SUB_RE = re.compile(r"(://[^/:@\s]+:)([^/:@\s]+)(@)")


def _redact_scalar(v):
    if isinstance(v, str):
        v = URL_TOKEN_SUB_RE.sub(lambda m: m.group(1) + "***REDACTED***", v)
        v = URL_USERPASS_SUB_RE.sub(lambda m: m.group(1) + "***REDACTED***" + m.group(3), v)
    return v


def _redact_json(obj, parent_key=None):
    # Bug found via testing (2026-08-26): the old version only checked
    # SECRET_KEY_NAME_RE at the dict level, against a directly-string-valued
    # key -- a list of secret strings under a matching key (e.g.
    # "api_keys": ["sk-...", "sk-..."]) recursed into the list branch with
    # the key-name check never applied to its string elements, so every
    # value printed in full plaintext. Checking parent_key at the STRING
    # leaf (regardless of how many list/dict levels it took to get there)
    # closes this for any nesting shape, not just one more special case.
    if isinstance(obj, dict):
        return {k: _redact_json(v, k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact_json(v, parent_key) for v in obj]
    if isinstance(obj, str):
        if parent_key is not None and SECRET_KEY_NAME_RE.search(str(parent_key)):
            return "***REDACTED***"
        return _redact_scalar(obj)
    return obj


# Matches both plain `KEY: value`/`KEY=value` lines and YAML bullet-list
# env entries (`  - KEY=value`), which is this container's actual
# compose.yaml format for UNRAID_API_KEY/UNIFI_NETWORK_API_KEY_CONTAINER --
# found missing via testing against a realistic fixture. Group 2 (the key
# name alone) is checked against SECRET_KEY_NAME_RE by *search*, not
# adjacency to `=`/`:` -- a plain `api[_-]?key=` adjacency match (as used by
# URL_TOKEN_SUB_RE) misses real key names like UNIFI_NETWORK_API_KEY_CONTAINER
# where something follows "KEY" before the separator.
KV_LINE_RE = re.compile(r'^(\s*(?:-\s+)?)([\w.\-]+)(\s*[:=]\s*)(.+)$')
XML_CONFIG_RE = re.compile(r'(<Config\b[^>]*Name="([^"]*)"[^>]*>)([^<]*)(</Config>)', re.I)


BLOCK_SCALAR_VALUE_RE = re.compile(r'^[|>][+\-]?\s*(#.*)?$')


def _indent_of(line):
    return len(line) - len(line.lstrip(" "))


def _redact_text(text):
    out_lines = []
    lines = text.split("\n")
    skip_below_indent = None  # redact-and-drop ALL lines more indented than this
    placeholder_emitted = False
    for line in lines:
        if skip_below_indent is not None:
            if line.strip() == "" or _indent_of(line) > skip_below_indent:
                # Bug found via testing: emitting the placeholder and
                # immediately clearing skip mode only masked the block
                # scalar's FIRST line -- a multi-line secret (e.g. an
                # embedded PEM key) had every line after that printed
                # untouched. Stay in skip mode for the whole block; emit
                # exactly one placeholder for it, drop the rest.
                if line.strip() != "" and not placeholder_emitted:
                    out_lines.append(line[:_indent_of(line)] + "***REDACTED (block scalar)***")
                    placeholder_emitted = True
                continue
            skip_below_indent = None
            placeholder_emitted = False
        m = KV_LINE_RE.match(line)
        if m and SECRET_KEY_NAME_RE.search(m.group(2)):
            # YAML block scalar (`key: |` / `key: >`, optionally `|-`/`>+`
            # etc.) -- the secret's real content is on FOLLOWING more-indented
            # lines, not the value token itself. Found via testing: without
            # this, `password: |` got redacted but the actual multi-line
            # value (e.g. an embedded PEM key) printed untouched below it.
            if BLOCK_SCALAR_VALUE_RE.match(m.group(4).strip()):
                out_lines.append(m.group(1) + m.group(2) + m.group(3) + m.group(4))
                skip_below_indent = _indent_of(line)
                continue
            out_lines.append(m.group(1) + m.group(2) + m.group(3) + "***REDACTED***")
            continue
        line = URL_TOKEN_SUB_RE.sub(lambda mm: mm.group(1) + "***REDACTED***", line)
        line = URL_USERPASS_SUB_RE.sub(lambda mm: mm.group(1) + "***REDACTED***" + mm.group(3), line)
        line = XML_CONFIG_RE.sub(
            lambda mm: mm.group(1) + (
                "***REDACTED***" if mm.group(3).strip() and SECRET_KEY_NAME_RE.search(mm.group(2))
                else mm.group(3)
            ) + mm.group(4),
            line,
        )
        out_lines.append(line)
    return "\n".join(out_lines)


def redact_file(path):
    try:
        with open(path, "r", errors="ignore") as f:
            raw = f.read()
    except Exception as e:
        print(f"ERROR: could not read {path}: {e}", file=sys.stderr)
        sys.exit(2)

    try:
        obj = json.loads(raw)
    except Exception:
        obj = None

    if obj is not None:
        print(json.dumps(_redact_json(obj), indent=2))
    else:
        print(_redact_text(raw))


def check_read(file_path):
    taint_cache = load_taint()
    if is_sensitive_path(file_path, taint_cache):
        print(
            "DENY:Blocked: '" + file_path + "' is known to hold plaintext secrets -- directly, via a "
            "symlink, or as a tracked copy of compose.yaml/services.yaml/settings.local.json/.mcp.json/an "
            "SSH private key. Use the tested redactor instead of a one-off script or sed one-liner (which "
            "have missed cases before, e.g. a token embedded in a JSON 'url' field, not just env/headers "
            "values): python3 /workspace/.claude/hooks/secret_guard_check.py --redact '" + file_path + "'"
        )
    else:
        print("ALLOW")


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--read":
        check_read(sys.argv[2])
        return

    if len(sys.argv) >= 3 and sys.argv[1] == "--redact":
        redact_file(sys.argv[2])
        return

    cmd = sys.stdin.read()
    taint_cache = load_taint()
    statements = split_statements(cmd)

    for stmt in statements:
        process_copy_taint(stmt, taint_cache)

    for stmt in statements:
        reason = check_credential_shape(stmt)
        if reason:
            print("DENY:" + reason)
            return
        reason = check_git_secrets(stmt, taint_cache)
        if reason:
            print("DENY:" + reason)
            return
        reason = check_other_rules(stmt)
        if reason:
            print("DENY:" + reason)
            return
        reason = check_content_leak(stmt, taint_cache)
        if reason:
            print("DENY:" + reason)
            return

    print("ALLOW")


if __name__ == "__main__":
    main()
