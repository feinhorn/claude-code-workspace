---
name: eng-task
description: Execute a task from the Notion "Engineering Tasks" database end to end — load the context packet, do the approved work, validate, adversarially review, and sync the closure record back to Notion over MCP. Use when Flynn runs `/eng-task <task page url, id, or name>`, or points you at an Engineering Tasks page and says run it / execute it / do the task. Triggers on 'eng-task', 'engineering task', 'run the task', 'execute the Notion task', 'do the Notion engineering task'.
---

# Engineering Task Execution

This skill **is** Steps 3–5 of the "⚙️ AI-Assisted Infrastructure Workflow" SOP.
You do not need to open that page — everything you must do is below.

Input: a **Notion Engineering Tasks page** (URL, page ID, or exact task name).

## Resolve the input first

Before anything else, decide whether the input names an **existing** Engineering Tasks
row. Only treat it as a new-task request when it starts with `new:`, or when no
existing row matches.

- A URL or page ID → `notion-fetch` it directly.
- Any other string → query the data source for a row whose **Task / Objective** matches
  (exact, then `LIKE`):
  `SELECT id, "Task / Objective", "Status" FROM "collection://3c5a7685-6021-4de3-8224-db561b552ff4" WHERE "Task / Objective" LIKE ?`
  Exactly one match → that is the task; go to **§0**. Multiple matches → ask Flynn which.
  Zero matches and no `new:` prefix → tell Flynn no such task exists; do not silently
  create one.

## Intake mode — `/eng-task new: <one-line objective>`

If the input starts with `new:` (or the resolve step above found no existing row and
Flynn confirms filing a new one), create the row instead of executing:

1. `notion-create-pages` under data source `collection://3c5a7685-6021-4de3-8224-db561b552ff4`
   with **Task / Objective** = the objective, **Status** = `Intake`.
2. Ask Flynn for **Task Type**, **System**, and any **Constraints & Boundaries** — set
   them via `notion-update-page`. Do not guess Task Type; it shapes every downstream
   prompt.
3. Apply the `New Engineering Task` template (`template_id` `e01a1f96-61d6-4deb-a31e-6d9171803427`)
   so Sections 1–5 exist on the page.
4. Stop. Tell Flynn the page URL and that Step 2 (Notion AI context packet) is next —
   this skill does not write the packet.

## Promoting an Investigate task to Fix

Use when a **concluded** Investigate task turns up a defect Flynn wants fixed in the
same task rather than a fresh one.

**Precondition — the investigation is done and signed off.** Hypotheses ruled in/out
with timestamped evidence, findings ranked (bug / monitoring gap / optimization), and
Flynn has confirmed *which specific findings* are being actioned. That confirmation is
the scope-escalation approval §2 otherwise forbids — record it in Section 4.

1. **Decide promote-in-place vs. new Fix task.** Promote in place only if *all* hold:
   the fix is small and tightly scoped to one finding; the investigation evidence
   already *is* the "characterise the defect first" artifact the Fix shape needs; and
   the fix crosses **no** boundary the original packet's Section C fenced off.
   File a **new Fix task** (fresh context packet) instead if the fix touches a fenced
   boundary, needs its own validation window (e.g. a recalibration + multi-day watch),
   bundles multiple independent fixes, or the packet's exit criteria already named it
   as follow-up work.
2. **Re-read the packet's Section C boundaries.** Any actioned finding whose fix
   crosses one → new task. No exceptions without Flynn explicitly re-approving that
   specific boundary in this session.
3. **Flip `Task Type` → `Fix`** (`notion-update-page`).
4. **Append a Section 2 addendum: "Fix scope (promoted from Investigate <date>)".**
   Per actioned finding: the exact defect + citation to the investigation evidence;
   the smallest coherent change; the testable pass/fail outcome; the concrete rollback
   command; and an explicit **out-of-scope** list (every other finding stays untouched).
   This addendum is the Fix workflow's defect-characterisation artifact.
5. **Status → In Progress** (move it back if it had already reached In Review).
6. **Execute under the Fix task-type shape** (§2): reproduce/characterise citing the
   investigation evidence, smallest change, regression test failing-before/passing-after,
   Section 4 Fix checklist, `/security-review` + `/code-review high` for material code,
   Flynn diff sign-off, then closure sync.
7. **Closure:** one record covers both phases (findings + fix). Section 5, Pages
   Updated, Docs Synced, and the AI System Reference capsule all reflect both.

**Guardrails:** the promotion is itself a scope change and needs explicit approval;
one promotion per task (a later second finding is a new task); if the fix cannot be
applied from the execution environment (no file access, wrong-file-write risk), that
is a blocker to raise *before* flipping `Task Type`, not mid-fix.

## 0. Load the task

1. `notion-fetch` the page. Read **Section 2 (the context packet)** in full, plus the
   **Task Type**, **System**, and **Constraints & Boundaries** properties. These
   properties are the source of truth — hydrate them straight from the fetched row.
   **Never re-ask a field that is already populated.** For an existing task, prompt
   only for a field that is genuinely empty (and for Task Type, only if unset — never
   guess it). An empty **Constraints & Boundaries** is normal: fall back to the
   packet's stated boundaries, don't prompt.
2. **Readiness gate — if any of these fail, stop and tell Flynn what's missing.** Do
   not fix them yourself and do not proceed on a "close enough" packet:
   - **Status** is not `Context Ready` (or already `In Progress` / `In Review`, i.e. a
     resumed run). `Intake` means the context packet hasn't been done and signed off —
     do not start.
   - Section 2 is empty or still the placeholder text — Step 2 (Notion AI context
     packet) hasn't run.
   - **Task Type** is unset, or Section 2 defines no testable outcome and no
     rollback / restore criterion — the task isn't specified well enough to execute.
3. Set **Status → In Progress** via `notion-update-page`.

## 1. Trust-but-verify — the ONLY context work you spend tokens on

The context packet is the knowledge layer's finished product. **Trust sections A–D.**
Do **not** re-derive them by re-reading Notion pages or sweeping the repo — that is
the token waste this workflow exists to avoid.

Your one job here: walk **packet section E ("Live facts to verify in session")** and
confirm each item against live state — git branch / HEAD, deployed-vs-committed
parity, container health, entity IDs, current config values. Log the result of every
check in the execution record.

- If a section-E check **substantively contradicts** the packet — a named container,
  path, entity, HEAD, or config value is not what the packet claims — stop and tell
  Flynn. The packet is wrong and the task is likely mis-scoped.
- **Expected divergence is not a contradiction.** Section E sometimes restates the
  task's *pre-execution* state ("Status is still `Intake`", "Section 2 is empty",
  "checklist unchecked"). Reaching this skill at all means the readiness gate passed,
  so that state has legitimately moved on. Log the current value and continue — do not
  stop. The live facts worth verifying are execution-time facts (branch, deployed-vs-
  committed parity, container health, identifiers, current config values), never the
  starting conditions. A well-authored section E lists only the former; when it lists
  the latter, treat those bullets as context, not as a gate.
- If the packet has **no section E** (predates the convention): do a minimal live-state
  check of the systems it names, and note that.

## 2. Execute

Stay inside the packet's approved scope. **Scope escalation is the named primary
failure mode of this workflow** — rotating a credential, editing an unrelated config,
or sweeping the filesystem when the task did not ask for it requires fresh explicit
approval.

Task-type shape:

- **Fix** — reproduce or characterise the defect *first*; smallest coherent change;
  a regression test that fails before and passes after.
- **Investigate** — evidence-preserving, discriminating checks only. **Do not implement
  a change** unless Section 2 explicitly approves one. Deliverable is findings + a
  recommended follow-up task.
- **Build New** — confirm the capability does not already exist; house conventions
  (Community Applications templates only for containers, credential-per-trust-boundary,
  no WAN exposure of management surfaces); plan backup, monitoring, ingress, rollback,
  teardown before building.
- **Add Feature** — for new capability landing *inside* an already-running,
  already-provisioned service (no new container/port/hostname). Confirm the
  capability doesn't already exist in the codebase; identify the shared
  helpers/patterns to reuse rather than reinvent; respect every constraint the
  host service's existing packet/doc already established (e.g. don't touch an
  unrelated documented workaround). Smallest coherent change; extend the
  service's existing regression suite rather than starting a new one. Skip the
  Build New checklist's port/hostname/capacity/monitoring/ingress items unless
  the feature itself adds a new external dependency, listener, or storage need
  — most Add Feature tasks have nothing to verify there.
- **Migrate** — preflight the target, back up the source, cut over, verify data
  integrity, hold a rollback window before retiring the source.
- **Retire** — prove zero active consumers and approved retention, then only reversible
  shutdown / cleanup steps.

**Hard stops** (CLAUDE.md + SOP Hard Rule) — stop and get explicit approval before:
destructive commands, production applies, credential rotation, firing an irrigation
valve / master switch, restarting Home Assistant, deleting entities / automations /
scripts / history. Never `grep -r` broadly on the live Unraid host (single combined
pattern, `grep -rlI`, `--exclude-dir` for plex/frigate/media/`*.db`, `ionice -c3`, ask
first). Never type a secret into a tool-call argument.

**Autonomy** — proceed through validation on your own, honouring the hard-stop list,
but:
- announce each irreversible step before taking it;
- before the first change that touches live state on anything holding persistent data
  or an access boundary (DB schema, credentials, container volumes, firewall, DNS),
  checkpoint with Flynn and dry-run / rehearse the rollback command first.

**Editing HA config.** The HA VM config dir is reachable at **`ssh ha`** (an
`~/.ssh/config` alias for `root@192.168.1.43:22`, key `id_ed25519_ha`, **passwordless**
— `BatchMode=yes` works). It lands in the Advanced SSH add-on container with `/config`
mounted — the `feinhorn/HA-Configs` git working tree (`git@github.com:feinhorn/HA-Configs.git`,
branch `main`). **Address it as `ssh ha`, not `ssh root@192.168.1.43`** — a raw-IP
invocation does not match the `Host ha` block and falls through to the wrong key.
Prefer editing files here directly (normal git flow, comments/anchors preserved) over
the MCP config API.

Fall back to the MCP config API (`ha_config_set_*`) only if `ssh ha` is genuinely
down. It writes only what HA exposes through its config API (automations/scripts that
round-trip on `ha_config_get_*`), not `packages/*.yaml` or `editable: false` helpers,
and it **rewrites the whole file through HA's serializer** (comments / anchors /
formatting flattened) — so record every object changed for git reconciliation and
confirm a current HA backup first. Note the repo often carries a pre-existing
unrelated diff (`custom_components/ecowitt_local/`, `frigate/`) — never commit without
Flynn's say. After any write, run `ha_get_system_health(include="config_check")` and
reload the affected domain; never a full HA restart without approval.

## 3. Validate

Universal (every task):
- linter / syntax / configuration checks pass
- no secret in any command, output, fixture, or doc
- scope stayed inside the packet
- rollback / restore procedure written as a concrete command and verified

Then run the matching **Section 4** task-type checklist from the page.

Review:
- **Material code change** → run `/security-review` and `/code-review high`.
- **Non-code change** → run the adversarial-review prompt in Section 4 of the page.
- **A change touching persistent data or an access boundary** → additionally ask Flynn
  to approve a **read-only** review subagent (Explore or general-purpose, scoped to
  read-only exploration) for an independent pass. Never a subagent that can edit or
  push under Flynn's git identity (CLAUDE.md).
- Classify findings **Blocker / Important / Minor**. Blockers must be fixed or
  explicitly waived by Flynn before closure.

## 4. Human sign-off

Present to Flynn: the diff / change summary, validation evidence, the concrete
rollback command, and all review findings.

**Do not apply to production and do not close the task until Flynn explicitly
approves.** `git push` only on explicit confirmation; never force-push `main`.

## 5. Closure sync (over MCP)

After sign-off:

1. **Scrub first.** Run the `scrub` skill over everything about to be written to
   Notion — execution log, diff summary, command output. No credential-shaped string
   reaches a Notion page. Non-negotiable ([[feedback_homelab_credential_handling]]).
2. Write into the task page via `notion-update-page`:
   - **Section 3** — working dir, session date, files modified, commands executed, diff summary.
   - **Section 4** — validation evidence and review findings.
   - **Section 5** — durable closure record following the compiled **Closure Prompt**
     structure: outcome + rationale, what changed, validation evidence, rollback /
     restore procedure, monitoring window.
3. **Canonical docs — hard gate.**
   - Update the affected subsystem page(s) and the infra map in Notion with verified
     live state, per CLAUDE.md's Homelab Documentation Rule. If a page genuinely needed
     no change, name the page you checked and why — a bare "nothing needed updating" is
     not acceptable.
   - **Always** append a Session Memory Capsule to the **AI System Reference**
     (`37d12807f3a281d4b180dad5bdf8e103`, its "Latest session capsules" section):
     date, task link, areas touched, what changed, verification evidence, follow-ups.
     Unconditional — every run writes one, a no-op investigation included.
   - Fill the task's **Pages Updated** property (page names + links you touched) and
     tick **Docs Synced**. The **Closure Gate** formula must read green before Flynn
     can close.
4. **Status → In Review** and set **Closed At** = today's date (this is the
   work-complete date the `Days Open` metric uses). **Do not set Closed** — only Flynn
   closes, after final verification.
5. If a credential was exposed or rotated at any point, run the `rotate` skill and log it.

## Working directory

This container works in `/workspace` (the `.claude` config tree). Host operations go
over SSH to `root@192.168.1.74`. Ignore any `/mnt/user/...` default in an older template.
