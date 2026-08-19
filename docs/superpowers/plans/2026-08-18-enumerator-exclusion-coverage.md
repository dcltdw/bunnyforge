# Enumerator Exclusion Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `TestEnumerator`'s vacuous exclusion assertions with exact-equality assertions that actually pin the enumerator's three unpinned filters — the `*.md` glob, the allowlist-driven top-level walk, and `exclude_dirs`.

**Architecture:** Test-only change to `tests/test_review.py`. Every `assertNotIn` in the two affected tests is replaced by a single exact-equality assertion on the full enumerated result, the idiom the three neighbouring `TestEnumerator` tests already use. Because the enumerator returns an enumerable list, exact equality is strictly stronger than "assert absent" — it closes the whole negative space, and a directory rename can never quietly turn it into a no-op. Two fixture entries are added and two are renamed so each filter has a file that would surface if the filter broke.

**Tech Stack:** Python ≥ 3.11, stdlib `unittest` only. No new dependencies, no production-code changes.

**Spec:** [GitHub issue #68](https://github.com/dcltdw/bunnyforge/issues/68), plus the design decisions recorded in "Design decisions" below (no separate spec file was written — the ticket carries the problem statement and this plan carries the resolution).

**Release context:** #68 is part of the release tracked by [issue #69](https://github.com/dcltdw/bunnyforge/issues/69) (#64, #62, #66 merged; #68, #65, #71 outstanding). Nothing else in the release touches `tests/test_review.py`.

## Global Constraints

- Python ≥ 3.11; **stdlib only at runtime**; no new dependencies of any kind.
- **No test may write into the repo.** Every test scaffolds into `tempfile.TemporaryDirectory()`. CI enforces this.
- **Never `pip install` into any shared environment.** The primary clone's venv runs a live campaign.
- Run the suite from the worktree root as:
  `PYTHONPATH=src python3 -m unittest discover -s tests -t .`
  Bare `python3` in a worktree resolves `bunnyforge` to the primary clone. Verify once per session with:
  `PYTHONPATH=src python3 -c "import bunnyforge; print(bunnyforge.__file__)"` — the path must be inside the worktree.
- Baseline on `main` after #66: `Ran 926 tests … OK (skipped=57)`. The 57 skips are the optional `mcp` extra and are expected locally.
- **Never commit to `main`.** Work on a branch. Every commit carries a `Co-Authored-By:` trailer naming the model.
- No production code is modified by this plan. Mutations to `src/bunnyforge/_common.py` appear only as **temporary verification steps** and every one of them is reverted with `git checkout src/bunnyforge/_common.py` inside the same task.

---

## Design decisions

Both decisions were settled during brainstorming against measured evidence. Do not re-litigate them; if the evidence looks wrong, re-run the probes below before changing course.

### The evidence

Three mutations to `src/bunnyforge/_common.py`, each run against the full suite on clean `main`:

| Mutation | Result |
|---|---|
| `_walk_md_files` glob accepts `.html` as well as `.md` | `Ran 926 tests … OK` — the extension filter is unpinned |
| `iter_content_files` also walks the workspace root (allowlist leak) | `Ran 926 tests … OK` — the allowlist is unpinned |
| the `config.exclude_dirs & set(parts)` filter is disabled | `Ran 926 tests … OK` — `exclude_dirs` is unpinned |

A fourth probe laid out the candidate fixture files and removed the allowlist: of `_Archive/old.md`, `_Templates/npc.md`, `_Sheets/session-001/notes.md` and `Sheets/session-001/notes.md`, **only the plain-named `Sheets/…` entry survived** the shared filter set. The other three die to `_common.is_machinery` regardless.

### Decision 1 — what the assertion is for

The ticket's option 1 (assert on a `.md` under the configured `sheets_dir`) is **duplicate coverage**: `sheets_dir` defaults to `_Sheets`, so such a file is caught by the `_`-prefix rule, which `test_machinery_components_are_skipped_by_the_general_rule` already pins with exact equality. Rejected.

The genuinely uncovered property is **"the top-level walk is allowlist-driven"** — a directory in no allowlist is not walked *even when its name carries no machinery marker*. That is the honest form of what "generated output is excluded" was reaching for. The "generated output" framing is dropped: generated output is `_Sheets` now, and the prefix rule owns it.

The ticket's option 2 (a non-`.md` file somewhere that *is* walked) is **also adopted** — mutation 1 shows nothing in the suite pins the `*.md` glob.

### Decision 2 — the convention

**No helper.** For an enumerable result, `assertEqual(rels, [...])` is strictly stronger than an "absent plus control present" helper: it closes the entire negative space rather than one path, it needs no new machinery, and three neighbouring tests already use it. The convention adopted by #68 is therefore *"when the result is enumerable, assert the whole set"*, recorded as a `TestEnumerator` class docstring in Task 3.

The helper question remains open only for **non-enumerable** negative assertions — a string absent from captured output, a file that should not exist — which is the ~35-call, ~10-file population. That is out of scope for #68 and gets its own ticket in Task 4.

---

### Task 1: Pin the glob and the allowlist in `test_categories_and_exclusions`

**Files:**
- Modify: `tests/test_review.py:41-65` (`TestEnumerator.test_categories_and_exclusions`)
- Test: `tests/test_review.py` (this *is* the test)

**Interfaces:**
- Consumes: `make_workspace(root, files)` from `tests/test_review.py:24`; `_config.open_workspace(root) -> Workspace`; `_common.iter_content_files(ws) -> list[FileRec]` where `FileRec` is a namedtuple `(path, fm, body, category)`.
- Produces: nothing later tasks depend on. Task 3 adds a docstring to the same class.

**Fixture changes in one place, so read all four before editing:**
- `Sheets/session-001/npc-mira-venn.html` → **removed**. Its directory is in no allowlist *and* its extension is filtered, so it could never appear under any bug.
- `NPCs/sheet.html` → **added**. `NPCs` *is* walked, so this file is held out solely by the `*.md` glob.
- `Maps/hexcrawl.md` → **added**. A plainly-named, plausible campaign directory that is in none of `entity_dirs`, `inherit_dirs`, `root_docs`, `archive_dir`, `exclude_dirs`, and carries no `_` or `.` prefix — so it is held out solely by the allowlist.
- `_Archive/old.md` and `_Templates/npc.md` → **kept**, but they stop being the point. They now document that machinery names at the root stay out; the exact-equality assertion covers them without a line each.

- [ ] **Step 1: Verify the import resolves inside the worktree**

Run from the worktree root:

```bash
PYTHONPATH=src python3 -c "import bunnyforge; print(bunnyforge.__file__)"
```

Expected: a path under `.claude/worktrees/<name>/src/bunnyforge/__init__.py`. If it points at `/Users/dcltdw/Github/bunnyforge/src/...` (no `.claude/worktrees` segment), stop — every later result would be measuring the primary clone.

- [ ] **Step 2: Confirm the clean baseline**

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -t . 2>&1 | grep -E "^(Ran|OK|FAILED)"
```

Expected: `Ran 926 tests in …` then `OK (skipped=57)`. Anything else means the worktree is not clean — resolve that before proceeding.

- [ ] **Step 3: Rewrite the test**

Replace the whole of `tests/test_review.py:41-65` with:

```python
    def test_categories_and_exclusions(self):
        # Exact equality, not four assertNotIns: the enumerator returns an
        # enumerable list, so asserting the whole set closes the entire
        # negative space at once. The assertNotIn form this replaced could
        # not fail -- it named a directory in no allowlist *and* an
        # extension the glob filters, so no bug could ever surface it (#68).
        #
        # Each excluded entry below is held out by exactly one filter, so a
        # regression in any single filter fails this test:
        #   NPCs/README.md      the README skip inside _walk_md_files
        #   NPCs/sheet.html     the *.md glob -- NPCs itself *is* walked
        #   Maps/hexcrawl.md    the allowlist: top-level walking covers only
        #                       entity_dirs + inherit_dirs + root_docs +
        #                       archive_dir, and Maps is in none of them
        #   _Archive/old.md     the general _-prefix rule (_common.is_machinery),
        #   _Templates/npc.md   not exclude_dirs, which since #62 defaults to
        #                       ["docs", "scripts", "tests"] and lists neither
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "NPCs/mira-venn.md": "---\ntype: npc\nvisibility: gm-only\n---\nbody",
                "NPCs/README.md": "# readme",
                "NPCs/sheet.html": "<html>",
                "Briefs/session-001/mira-venn.md": "---\ntype: brief\n---\nb",
                "compendium.md": "# Compendium",
                "_Archive/old.md": "---\ntype: npc\n---\nx",
                "_Templates/npc.md": "---\ntype: npc\n---\nx",
                "Maps/hexcrawl.md": "---\ntype: npc\n---\nx",
            })
            ws = _config.open_workspace(root)
            recs = _common.iter_content_files(ws)
            by_path = {r.path.relative_to(ws.root).as_posix(): r for r in recs}

            self.assertEqual(
                list(by_path),
                ["Briefs/session-001/mira-venn.md",
                 "NPCs/mira-venn.md",
                 "compendium.md"])

            self.assertEqual(by_path["NPCs/mira-venn.md"].category, "entity")
            self.assertEqual(
                by_path["Briefs/session-001/mira-venn.md"].category, "inherit")
            self.assertEqual(by_path["compendium.md"].category, "root")
```

Note on the expected list: `iter_content_files` returns records sorted by absolute POSIX path, so `list(by_path)` is already in ascending order. Uppercase sorts before lowercase, which is why `compendium.md` comes last.

- [ ] **Step 4: Run the test on clean production code**

```bash
PYTHONPATH=src python3 -m unittest tests.test_review.TestEnumerator.test_categories_and_exclusions -v
```

Expected: `OK`. If the exact-equality assertion fails here, the expected list is wrong — read the actual list in the failure message and reconcile it against the fixture before touching anything in `src/`.

- [ ] **Step 5: Prove the glob assertion can fail (mutation 1)**

This is the TDD "watch it fail" step. There is no implementation to write, so the failing run comes from a deliberate mutation instead.

In `src/bunnyforge/_common.py:129`, change:

```python
    for p in base.rglob("*.md"):
```

to:

```python
    for p in [q for q in base.rglob("*") if q.suffix in (".md", ".html")]:
```

Then run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_review.TestEnumerator.test_categories_and_exclusions -v
```

Expected: **FAIL**, with `NPCs/sheet.html` present in the actual list. On `main` this same mutation left all 926 tests passing — that is the hole this step closes.

- [ ] **Step 6: Revert mutation 1**

```bash
git checkout src/bunnyforge/_common.py
git status --short
```

Expected: `git status --short` lists only `tests/test_review.py` (and the plan file). `src/bunnyforge/_common.py` must not appear.

- [ ] **Step 7: Prove the allowlist assertion can fail (mutation 2)**

In `src/bunnyforge/_common.py`, in `iter_content_files`, replace:

```python
    return sorted(recs, key=lambda r: r.path.as_posix())
```

with:

```python
    seen = {r.path for r in recs}
    for extra in _walk_md_files(workspace, workspace, config,
                                lambda parts: "entity"):
        if extra.path not in seen:
            recs.append(extra)

    return sorted(recs, key=lambda r: r.path.as_posix())
```

Then run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_review.TestEnumerator.test_categories_and_exclusions -v
```

Expected: **FAIL**, with `Maps/hexcrawl.md` present in the actual list — and `_Archive/old.md`, `_Templates/npc.md` still absent, because the `_`-prefix rule catches those independently. That asymmetry is the whole reason `Maps/` is a plain name.

- [ ] **Step 8: Revert mutation 2**

```bash
git checkout src/bunnyforge/_common.py
git status --short
```

Expected: `src/bunnyforge/_common.py` absent from the output.

- [ ] **Step 9: Run the full suite**

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -t . 2>&1 | grep -E "^(Ran|OK|FAILED)|^(FAIL|ERROR): "
```

Expected: `Ran 926 tests …` then `OK (skipped=57)`. The test count is unchanged — this task rewrites a test, it does not add one.

- [ ] **Step 10: Commit**

```bash
git branch --show-current   # confirm you are NOT on main
git add tests/test_review.py
git commit -m "$(cat <<'EOF'
test: pin the *.md glob and the allowlist in test_categories_and_exclusions

The `assertNotIn("Sheets/session-001/npc-mira-venn.html", ...)` this
replaces could not fail: `_walk_md_files` globs `*.md` only, and top-level
walking is allowlist-driven, so a `.html` under an unlisted directory was
excluded twice over before any bug could reach it (#68).

Measured on main, the suite pinned neither filter -- making the glob accept
`.html`, or leaking the top-level walk to the workspace root, both left all
926 tests passing. The fixture now holds one file per filter (NPCs/sheet.html
for the glob, Maps/hexcrawl.md for the allowlist) and one exact-equality
assertion replaces the four assertNotIns, so the negative space is closed
rather than sampled.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Make `test_exclude_dirs_filters_nested_directories_too` exercise `exclude_dirs`

**Files:**
- Modify: `tests/test_review.py:67-83` (`TestEnumerator.test_exclude_dirs_filters_nested_directories_too`) — note the line numbers shift by Task 1's edit; locate the test by name.

**Interfaces:**
- Consumes: same three as Task 1 — `make_workspace`, `_config.open_workspace`, `_common.iter_content_files`.
- Produces: nothing later tasks depend on.

**Why this is in #68:** the ticket's complaint is that the comment "actively points at the wrong mechanism" — and the neighbour it points at has the same defect. Since #62, `_Archive` is not in `exclude_dirs` (whose default is `["docs", "scripts", "tests"]`, plus `_ExtractInbound` and `_AgentDrafts` appended at load time). So the fixture `NPCs/_Archive/old.md` is caught by `is_machinery` before `exclude_dirs` is ever consulted, and this test — named for the filter — did not exercise it. Mutation 3 confirmed it: disabling the `exclude_dirs` check entirely left all 926 tests passing. `docs` is a genuine `exclude_dirs` member, so the one-line fixture swap gives the filter its first coverage.

- [ ] **Step 1: Rewrite the test**

Replace the whole of `test_exclude_dirs_filters_nested_directories_too` with:

```python
    def test_exclude_dirs_filters_nested_directories_too(self):
        # test_categories_and_exclusions above only ever puts an excluded
        # directory at the workspace *root*, where entity/inherit dirs are
        # never walked from anyway -- so the exclude_dirs filter inside the
        # rglob loop never actually fires there. This puts one *inside* an
        # entity dir, the only place the filter is ever consulted.
        #
        # `docs` is a real exclude_dirs member (_config._DEFAULTS). The
        # fixture used to say NPCs/_Archive/, which since #62 is caught by
        # the _-prefix rule before exclude_dirs is consulted at all -- so
        # this test was named for a filter it never exercised (#68), and
        # disabling that filter left the whole suite passing.
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "NPCs/mira-venn.md": "---\ntype: npc\nvisibility: gm-only\n---\nbody",
                "NPCs/docs/notes.md": "---\ntype: npc\nvisibility: gm-only\n---\nx",
            })
            ws = _config.open_workspace(root)
            rels = [r.path.relative_to(ws.root).as_posix()
                    for r in _common.iter_content_files(ws)]

            self.assertEqual(rels, ["NPCs/mira-venn.md"])
```

- [ ] **Step 2: Run the test on clean production code**

```bash
PYTHONPATH=src python3 -m unittest tests.test_review.TestEnumerator.test_exclude_dirs_filters_nested_directories_too -v
```

Expected: `OK`.

- [ ] **Step 3: Prove it can fail (mutation 3)**

In `src/bunnyforge/_common.py:133`, change:

```python
        if config.exclude_dirs & set(parts):
```

to:

```python
        if False and config.exclude_dirs & set(parts):
```

Then run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_review.TestEnumerator.test_exclude_dirs_filters_nested_directories_too -v
```

Expected: **FAIL**, with `NPCs/docs/notes.md` in the actual list. On `main`, with the old `NPCs/_Archive/old.md` fixture, this mutation left all 926 tests passing.

- [ ] **Step 4: Revert mutation 3**

```bash
git checkout src/bunnyforge/_common.py
git status --short
```

Expected: `src/bunnyforge/_common.py` absent from the output.

- [ ] **Step 5: Run the full suite**

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -t . 2>&1 | grep -E "^(Ran|OK|FAILED)|^(FAIL|ERROR): "
```

Expected: `Ran 926 tests …` then `OK (skipped=57)`.

- [ ] **Step 6: Commit**

```bash
git branch --show-current   # confirm you are NOT on main
git add tests/test_review.py
git commit -m "$(cat <<'EOF'
test: give exclude_dirs its first real coverage

Since #62, `_Archive` is not in exclude_dirs -- the default is
["docs", "scripts", "tests"] plus the two staging dirs appended at load
time -- so this test's NPCs/_Archive/ fixture was caught by the `_`-prefix
rule before exclude_dirs was ever consulted. The test was named for a
filter it did not exercise, and disabling that filter on main left all 926
tests passing.

`docs` is a genuine exclude_dirs member, so nesting it under an entity dir
puts the filter under test in the one place it fires (#68).

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Record the exact-equality convention where the next reader will hit it

**Files:**
- Modify: `tests/test_review.py` — add a class docstring to `TestEnumerator` (currently `class TestEnumerator(unittest.TestCase):` at line 40, immediately followed by the first `def test_`).

**Interfaces:**
- Consumes: nothing.
- Produces: nothing. Documentation only.

**Why here and not in a doc file:** the repo has no contributor or testing-conventions document (`docs/` holds `adopting-doctrine.md` and `serve-mcp.md`; `src/bunnyforge/data/doctrine/AGENTS.md` is campaign doctrine shipped into workspaces, not test guidance). The class that demonstrates the convention is where someone editing these tests will actually read it.

- [ ] **Step 1: Add the docstring**

Insert immediately after `class TestEnumerator(unittest.TestCase):`, before the first test method:

```python
class TestEnumerator(unittest.TestCase):
    """Convention: assert the *whole* enumerated result, not absences.

    iter_content_files returns a list, so `assertEqual(rels, [...])` closes
    the entire negative space -- strictly stronger than an assertNotIn per
    excluded path, and it cannot quietly stop guarding anything when a
    directory is renamed. Three separate assertions went vacuous that way
    during #62 (a `Sheets` fixture kept passing after the default became
    `_Sheets`); #68 was the last of them. An assertNotIn here should be
    read as a bug unless the result genuinely is not enumerable.
    """

```

- [ ] **Step 2: Run the full suite**

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -t . 2>&1 | grep -E "^(Ran|OK|FAILED)|^(FAIL|ERROR): "
```

Expected: `Ran 926 tests …` then `OK (skipped=57)`. A docstring changes nothing, but an indentation slip would — this catches that.

- [ ] **Step 3: Commit**

```bash
git branch --show-current   # confirm you are NOT on main
git add tests/test_review.py
git commit -m "$(cat <<'EOF'
docs: record the assert-the-whole-set convention on TestEnumerator

Three assertions went vacuous during #62 because a rename left an
assertNotIn naming a path nothing produced any more. Exact equality on the
enumerated result has no such failure mode, costs nothing, and is already
what most of this class does -- so say so where the next editor will read
it. No helper: for an enumerable result, assertEqual already is one (#68).

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Close #68 and open the follow-up for non-enumerable negative assertions

**Files:** none — GitHub only.

**Interfaces:**
- Consumes: Tasks 1–3 merged.
- Produces: nothing.

Do this **after** the PR merges, not before. Opening the PR itself is covered by the `dcltdw:opening-a-pr` skill; merging and branch cleanup by `dcltdw:cleaning-up-after-pr-merge`.

- [ ] **Step 1: Record the Decision 2 outcome on #68**

```bash
gh issue comment 68 --body "$(cat <<'EOF'
Decision on "worth a moment's thought": **no helper.**

For an enumerable result, `assertEqual(rels, [...])` is strictly stronger
than an absent-plus-control helper — it closes the whole negative space
instead of one path, needs no new machinery, and was already the idiom of
three of the four neighbouring `TestEnumerator` tests. That convention is
now recorded as a `TestEnumerator` class docstring.

The helper question stays open only for **non-enumerable** negative
assertions — a string absent from captured output, a file that should not
exist — which is where the remaining ~35 `assertNotIn`/`assertFalse` calls
across ~10 test files live. Tracked separately.
EOF
)"
```

- [ ] **Step 2: Open the follow-up ticket**

```bash
gh issue create --title "Non-enumerable negative assertions have no guard against going vacuous" --body "$(cat <<'EOF'
Split out of #68, which settled the enumerable case: when a result is a
list, `assertEqual(result, [...])` closes the whole negative space and
cannot go vacuous under a rename. That convention is recorded on
`TestEnumerator`.

It does not reach the non-enumerable cases — a string absent from captured
output, a file that should not exist on disk, a key absent from a response.
There, "assert absent" is the only form available, and a rename can turn it
into a permanent pass with nothing to notice.

**Scale.** `tests/test_review.py` alone has 35 `assertNotIn`/`assertFalse`
calls; the pattern spans about ten test files. During #62 three negative
assertions went vacuous this way — e.g. `assertFalse((root / "Sheets").exists())`
kept passing after the `sheets_dir` default became `_Sheets`. Two were
caught in PR #67; the third became #68.

**Question to settle.** Whether a helper that asserts the target is absent
*and* that a deliberately-present control is found is worth adopting — and
if so, where it lives (a shared `tests/_asserts.py`? a mixin?) and whether
adoption is a sweep or opportunistic.

**Measured context from #68.** Three separate mutations to
`src/bunnyforge/_common.py` — accepting `.html` in the walk glob, leaking
the top-level walk to the workspace root, and disabling the `exclude_dirs`
filter — each left all 926 tests passing on main. Mutation probes are cheap
and were what made the gaps visible; whatever this ticket decides, that
technique is worth keeping.
EOF
)"
```

- [ ] **Step 3: Move the board cards**

Move #68 to **Done**. Put the new follow-up ticket in the backlog (Todo), not in the #69 release — #69 is already carrying #65 and #71.

---

## Self-Review

**Spec coverage.** The ticket raises four items and asks two questions:

| Ticket item | Task |
|---|---|
| Vacuous `assertNotIn` on the `.html` path | Task 1 (removed; replaced by exact equality) |
| Stale `Sheets/` fixture name | Task 1 (removed — `_Sheets` is the current name and the prefix rule already pins it) |
| Comment misattributing `_Archive`/`_Templates` to `exclude_dirs` | Task 1 (rewritten to name the `_`-prefix rule and quote the current `exclude_dirs` default) |
| "Framing points at the wrong mechanism", incl. the neighbour it points at | Task 2 |
| Decision 1 — what the assertion is for | Design decisions §1; implemented by Task 1 |
| Decision 2 — is a helper convention worth adopting | Design decisions §2; recorded by Task 3, follow-up filed by Task 4 |

**Placeholder scan.** No TBDs. Every code step carries the literal text to write; every verification step carries the exact command and the exact expected output.

**Type consistency.** `make_workspace(root, files) -> Path`, `_config.open_workspace(root) -> Workspace` (with `.root` and `.config`), `_common.iter_content_files(ws) -> list[FileRec]` where `FileRec = namedtuple("FileRec", "path fm body category")` — used identically in Tasks 1 and 2. Tasks 1 and 2 both reference `_common.iter_content_files` directly rather than the `review._common.iter_content_files` spelling some neighbouring tests use; both resolve to the same function, and the direct form matches what these two tests already do.

**Verification already done.** Every "Expected: FAIL" in this plan was run before the plan shipped, using the exact test bodies quoted in Tasks 1 and 2 against the exact mutations quoted in the same steps:

- both new test bodies pass on clean production code;
- mutation 1 fails Task 1's test with `NPCs/sheet.html` in the actual list;
- mutation 2 fails Task 1's test with `Maps/hexcrawl.md` in the actual list, and with `_Archive/old.md` / `_Templates/npc.md` still absent;
- mutation 3 fails Task 2's test with `NPCs/docs/notes.md` in the actual list;
- production code was reverted after each, and the suite returns to `Ran 926 tests … OK (skipped=57)`.

If any of these does not reproduce during execution, something in the worktree differs from what the plan was written against — stop and find out what before editing.

**One caveat for the executor.** Tasks 1–3 all edit `tests/test_review.py`, so they must run in order in one worktree; do not parallelise them across agents.
