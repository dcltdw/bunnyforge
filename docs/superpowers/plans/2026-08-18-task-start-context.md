# Task-Start Context (#70) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generalize #66's task-start retrieval-scope question into a packaged doctrine framework of four contextual questions answered before any task's work begins, with a GM-owned growth point and a `campaign_overview` docstring pointer.

**Architecture:** Prose-first change. A new `## Task-start context` section in the packaged `AGENTS.md` owns the question list and the ask discipline; the retrieval-scope section's own ask sentences collapse into a pointer to it. The `campaign-doctrine.md` scaffold gains a commented stub for campaign-specific questions. `serve_mcp.py` changes by exactly one docstring sentence. Tests pin sections and phrases the way `test_init.py` / `test_serve_mcp.py` already do.

**Tech Stack:** Python ≥ 3.11, stdlib only, `unittest`. The `mcp>=2.0` extra is optional and absent from the local environment.

**Spec:** `docs/superpowers/specs/2026-08-18-task-start-context-design.md` (committed on this branch — read it first; the plan argues from it).

## Global Constraints

- Python ≥ 3.11, stdlib only, no new dependencies.
- No test may write into the repo — temp dirs only.
- Never pip install into any shared environment; the primary clone's venv runs a live campaign. A throwaway venv in the session scratchpad directory is fine (Task 3 uses one).
- Never commit to `main`. Work stays on branch `worktree-issue-70-task-start-context` in the worktree `/Users/dcltdw/Github/bunnyforge/.claude/worktrees/issue-68-enumerator-test` (already checked out there, spec committed). Run `git branch --show-current` before every commit.
- Suite, from the worktree root: `PYTHONPATH=src python3 -m unittest discover -s tests -t .`
  Baseline on `main` (2800873): `Ran 931 tests … OK (skipped=57)` — the 57 skips are the optional mcp extra.
- Once, before starting: `PYTHONPATH=src python3 -c "import bunnyforge; print(bunnyforge.__file__)"` must print a path inside the worktree, not the primary clone.
- #65 is deferred: nothing mechanically screens packaged prose for campaign-specific terms. Every packaged-prose change in this plan (Tasks 1–2) must be cleared by a deliberate human read at PR time, and the PR body must say that is the basis for the portability claim (same footing as PRs #72 and #75).
- Commit trailer: stamp the current AI model, e.g. `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.

---

### Task 1: Packaged doctrine — `## Task-start context` section, and the retrieval-scope collapse

**Files:**
- Modify: `src/bunnyforge/data/doctrine/AGENTS.md` (insert new section after "Clarify before proceeding", ends at line 71; replace one bullet in "Retrieval scope: live, archive, or both", lines 230–236)
- Test: `tests/test_init.py` (class `TestPackagedDoctrineIsPortable`)

**Interfaces:**
- Consumes: `init.packaged_bytes("doctrine/AGENTS.md")` (existing helper, returns the shipped bytes).
- Produces: the literal heading `## Task-start context` and the phrase `Task-start context` inside the retrieval-scope section — Task 2's stub comment and Task 3's docstring refer to the section by name.

- [ ] **Step 1: Write the failing tests**

Add to `TestPackagedDoctrineIsPortable` in `tests/test_init.py`, after `test_the_underscore_convention_is_stated_once`:

```python
    def test_task_start_context_carries_the_question_list(self):
        # #70: the standing checklist every task is held against before
        # work begins. Pin the section, the four questions, the bundling
        # discipline, and the campaign-side growth pointer.
        doctrine = init.packaged_bytes("doctrine/AGENTS.md").decode("utf-8")
        self.assertIn("## Task-start context", doctrine)
        section = doctrine.split("## Task-start context", 1)[1]
        section = section.split("\n## ", 1)[0]
        for needle in ("What are we building",
                       "new NPCs",
                       "live canon, the archive, or both",
                       "player-visible",
                       "in one message",
                       "[[campaign-doctrine]]"):
            with self.subTest(needle=needle):
                self.assertIn(needle, section)

    def test_the_ask_discipline_has_one_owner(self):
        # #70 collapsed the retrieval-scope section's own ask discipline
        # into Task-start context; the scope section must point there
        # instead of restating it. "ask me whether" and "One ask per task"
        # were the old restatement's spine.
        doctrine = init.packaged_bytes("doctrine/AGENTS.md").decode("utf-8")
        scope = doctrine.split("## Retrieval scope", 1)[1]
        scope = scope.split("\n## ", 1)[0]
        self.assertIn("Task-start context", scope)
        self.assertNotIn("ask me whether", scope)
        self.assertNotIn("One ask per task", scope)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=src python3 -m unittest tests.test_init.TestPackagedDoctrineIsPortable -v`
Expected: the two new tests FAIL (`'## Task-start context' not found` / `'Task-start context' not found`); the three existing tests in the class still PASS.

- [ ] **Step 3: Insert the new section**

In `src/bunnyforge/data/doctrine/AGENTS.md`, immediately after the "Clarify before proceeding" section — i.e. after the line `writing it.` (line 71) and before `## Verify against the files, not against earlier prose` — insert:

```markdown
## Task-start context

Some questions recur at the start of every task, and missing one is how
work goes wrong quietly. Before work begins, check each question below.
Skip the ones my request already answers and the ones that do not apply
to the kind of task at hand — skipping all of them is the normal case
for a complete request, and this list licenses no manufactured asks (see
**Clarify before proceeding** above). Ask me the rest **in one
message**, not one at a time.

1. **What are we building** — a plot, an encounter, a combat? A writeup
   or a brief? (**What gets written where**, below, carries the
   distinction.)
2. **Will new NPCs be created, or existing ones reused?**
3. **Should retrieval draw on live canon, the archive, or both?**
   (**Retrieval scope**, below, carries the full rule.)
4. **Is any of the output meant to be player-visible?** `gm-only` is the
   fail-safe default (**Player visibility**, below), but a wrong silent
   default costs a re-edit later.

Answers attach to the work and persist: picking a piece back up later
continues under the answers it was made with. One bundled ask per task;
hold the answers until the task changes or I re-answer.

The list is doctrine, and it grows as gaps appear. Questions specific to
one campaign belong in `[[campaign-doctrine]]`; a gap that would bite
any campaign belongs upstream as a bunnyforge ticket.
```

- [ ] **Step 4: Collapse the retrieval-scope ask bullet**

In the same file, in `## Retrieval scope: live, archive, or both`, replace this bullet (exact current text):

```markdown
- So at the start of a task that will create or revise canon, ask me
  whether its retrieval should be live-only, archive-only, or both —
  unless my request already answers it, or the work's scope is already
  established. The scope attaches to the work and persists: picking a
  piece back up later continues under the scope it was made with. One ask
  per task; hold it until the task changes or I re-scope it.
```

with:

```markdown
- So the scope question is one of the standing questions in **Task-start
  context** above, and runs under its discipline: raised when a task
  will create or revise canon and my request has not already answered
  it, bundled with the other open questions, held for the task.
```

The bullet's rationale siblings (answering vs. creative work, the contamination argument, the `scope=` mechanics bullet) stay untouched.

- [ ] **Step 5: Run the class to verify it passes**

Run: `PYTHONPATH=src python3 -m unittest tests.test_init.TestPackagedDoctrineIsPortable -v`
Expected: all five tests PASS — including `test_agents_md_wikilinks_resolve_with_only_root_docs`, which now also covers the new section's `[[campaign-doctrine]]` link.

- [ ] **Step 6: Commit**

```bash
git branch --show-current   # must print worktree-issue-70-task-start-context
git add src/bunnyforge/data/doctrine/AGENTS.md tests/test_init.py
git commit -m "feat: task-start context section in packaged doctrine; scope ask collapses into it (#70)

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `campaign-doctrine.md` scaffold — stub section for campaign-specific questions

**Files:**
- Modify: `src/bunnyforge/data/root/campaign-doctrine.md` (insert one section between "Exemptions from the generic contract" and "Extra tools and checks")
- Test: `tests/test_init.py` (alongside `test_writes_the_campaign_doctrine_stub`, ~line 493)

**Interfaces:**
- Consumes: `init.packaged_bytes("root/campaign-doctrine.md")`; Task 1's section name "Task-start context".
- Produces: the literal heading `## Task-start questions for this campaign` in every newly scaffolded workspace. Existing workspaces lack it harmlessly — nothing reads it mechanically (the graceful-absence stance `serve_mcp.py`'s `DOCTRINE_FILES` comment documents).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_init.py`, in the same class as `test_writes_the_campaign_doctrine_stub`, directly after that test:

```python
    def test_campaign_doctrine_stub_carries_task_start_section(self):
        # #70: campaign-specific task-start questions get a designated
        # home in the GM-owned half. Only new scaffolds receive it;
        # existing workspaces lack the section harmlessly because
        # nothing reads it mechanically.
        stub = init.packaged_bytes(
            "root/campaign-doctrine.md").decode("utf-8")
        self.assertIn("## Task-start questions for this campaign", stub)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=src python3 -m unittest tests.test_init -k task_start -v`
Expected: `test_campaign_doctrine_stub_carries_task_start_section` FAILS; Task 1's two tests PASS.

- [ ] **Step 3: Insert the stub section**

In `src/bunnyforge/data/root/campaign-doctrine.md`, between the "Exemptions from the generic contract" comment block and `## Extra tools and checks`, insert:

```markdown
## Task-start questions for this campaign

<!-- Extra questions this campaign's tasks must answer before work begins,
     beyond the generic set in AGENTS.md's "Task-start context" section.
     Also the place to strike or rephrase a generic question -- name the
     rule displaced, as with any exemption. -->
```

Match the file's comment style exactly: `<!--` flush with the margin, continuation lines indented five spaces, `-->` closing the last line.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m unittest tests.test_init -v`
Expected: all PASS — including `test_writes_the_campaign_doctrine_stub`, which compares the scaffolded file byte-for-byte to the packaged one and so covers the new section automatically.

- [ ] **Step 5: Commit**

```bash
git branch --show-current   # must print worktree-issue-70-task-start-context
git add src/bunnyforge/data/root/campaign-doctrine.md tests/test_init.py
git commit -m "feat: campaign-doctrine scaffold gains a task-start questions stub (#70)

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `campaign_overview` docstring — the task-start pointer

**Files:**
- Modify: `src/bunnyforge/serve_mcp.py:92-102` (the `campaign_overview` docstring only)
- Test: `tests/test_serve_mcp.py` (after `test_scope_guidance_reaches_the_descriptions`, ~line 283)

**Interfaces:**
- Consumes: the doctrine resource name "AGENTS.md" (already served as `bunnyforge://doctrine/AGENTS.md`); Task 1's phrase "task-start questions".
- Produces: nothing later tasks rely on. The `search`/`list_entities` scope mirrors are untouched — they are parameter-justified pointers, pinned by the existing `test_scope_guidance_reaches_the_descriptions`.

- [ ] **Step 1: Write the test**

Add to `tests/test_serve_mcp.py`, directly after `test_scope_guidance_reaches_the_descriptions`:

```python
    async def test_task_start_pointer_reaches_campaign_overview(self):
        # #70: campaign_overview is the "call this before anything else"
        # moment, so its description is where the task-start ritual gets
        # its hook. Pin the pointer phrases, not the list -- the AGENTS.md
        # doctrine resource owns the list.
        server = serve_mcp.build_server(scaffold(self))
        descs = {t.name: " ".join((t.description or "").split())
                 for t in await server.list_tools()}
        self.assertIn("task-start questions", descs["campaign_overview"])
        self.assertIn("in one message", descs["campaign_overview"])
```

- [ ] **Step 2: Build a scratchpad venv so the test can actually run**

The local environment lacks the `mcp` extra (that is the baseline's 57 skips), so without this the new test reports SKIP, not FAIL. In the session scratchpad directory (never the repo, never any shared venv):

```bash
python3 -m venv "$SCRATCHPAD/mcp-venv"
"$SCRATCHPAD/mcp-venv/bin/pip" install 'mcp>=2.0'
```

(`$SCRATCHPAD` = the session's scratchpad directory.) If the install cannot run (offline), skip Steps 3 and 5's venv runs, note in the commit/PR that the test was verified only as SKIP locally, and rely on the same footing the existing `test_scope_guidance_reaches_the_descriptions` has.

- [ ] **Step 3: Run the test to verify it fails**

Run: `PYTHONPATH=src "$SCRATCHPAD/mcp-venv/bin/python" -m unittest tests.test_serve_mcp -k task_start_pointer -v`
Expected: FAIL — `'task-start questions' not found in 'Get your bearings in one call: …'`.

- [ ] **Step 4: Append the docstring sentence**

In `src/bunnyforge/serve_mcp.py`, the `campaign_overview` docstring currently ends `Call this before anything else."""`. Extend it so the ending reads:

```python
        asks. Call this before anything else. Then, before work begins,
        answer the task-start questions in the AGENTS.md doctrine
        resource — ask the GM the ones the request has not answered, in
        one message."""
```

No other tool's docstring changes.

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=src "$SCRATCHPAD/mcp-venv/bin/python" -m unittest tests.test_serve_mcp -v`
Expected: all PASS (none skipped in the venv run).

- [ ] **Step 6: Commit**

```bash
git branch --show-current   # must print worktree-issue-70-task-start-context
git add src/bunnyforge/serve_mcp.py tests/test_serve_mcp.py
git commit -m "feat: campaign_overview points at the task-start questions (#70)

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Full-suite verification

**Files:**
- None created or modified. This task gates the branch, per superpowers:verification-before-completion.

**Interfaces:**
- Consumes: everything above.
- Produces: the verified branch the PR is opened from.

- [ ] **Step 1: Confirm the import resolves inside the worktree**

Run: `PYTHONPATH=src python3 -c "import bunnyforge; print(bunnyforge.__file__)"`
Expected: a path under `/Users/dcltdw/Github/bunnyforge/.claude/worktrees/issue-68-enumerator-test/src/`.

- [ ] **Step 2: Run the full suite with the system python**

Run: `PYTHONPATH=src python3 -m unittest discover -s tests -t .`
Expected: `Ran 935 tests … OK (skipped=58)` — baseline 931 + four new tests (two in Task 1, one each in Tasks 2–3), skips 57 + Task 3's test (skipped without the mcp extra). If the numbers differ from this arithmetic, stop and investigate before claiming done.

- [ ] **Step 3: Run the full suite with the scratchpad mcp venv**

Run: `PYTHONPATH=src "$SCRATCHPAD/mcp-venv/bin/python" -m unittest discover -s tests -t .`
Expected: `Ran 935 tests … OK` with far fewer skips (the mcp-gated tests now run, including Task 3's). Skip this step only if Task 2's venv could not be built.

- [ ] **Step 4: Confirm the working tree is clean and the repo untouched by tests**

Run: `git status --porcelain`
Expected: empty output. Any untracked file here means a test wrote into the repo — a constraint violation to fix, not ignore.

---

## Self-review notes (done at plan time)

- **Spec coverage:** Component 1 → Task 1 (both the new section and the collapse). Component 2 → Task 2. Component 3 → Task 3. Testing section → Tasks 1–3 tests + Task 4. Release/portability note → Global Constraints (human-read requirement, worded for the PR body). Out-of-scope items introduce no tasks. No gaps found.
- **Consistency:** the pinned phrases ("Task-start context", "task-start questions", "in one message", "live canon, the archive, or both") appear verbatim in the prose/docstring steps that must satisfy them; the negative pins ("ask me whether", "One ask per task") appear nowhere in the replacement bullet.
- **Skip arithmetic (Task 4) re-derived:** 931 baseline + 2 tests (Task 1) + 1 (Task 2) + 1 (Task 3) = 935; 57 baseline skips + Task 3's test = 58 under the system python. Task 4's expectations state exactly this.
