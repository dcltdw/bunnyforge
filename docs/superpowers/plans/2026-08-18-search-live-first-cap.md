# Search Live-First Ordering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task, inline. The tasks all edit `src/bunnyforge/_store.py` and `tests/test_store.py` sequentially — do NOT parallelise them across subagents. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `search` returns live hits before archived hits, so `SEARCH_CAP` keeps the current answer instead of filling with superseded material — and the truncation sentinel says truthfully what was cut.

**Architecture:** One production file changes: `WorkspaceStore.search` in `src/bunnyforge/_store.py` re-sorts the walk with a `(is_archived, path)` key and replaces the static truncation sentinel with a case-aware one appended only when a 51st match actually exists. `iter_content_files` is untouched — its global path order is a pinned convention its four other callers rely on. `serve_mcp.py`'s `search` tool description gains one sentence stating the ordering promise. Everything else (`list_entities`, `campaign_overview`, review, exports, doctrine prose) is a deliberate non-change.

**Tech Stack:** Python ≥ 3.11, stdlib only. No new dependencies.

**Spec:** [GitHub issue #71](https://github.com/dcltdw/bunnyforge/issues/71), plus the design decisions recorded below (no separate spec file — the ticket carries the problem statement and its four open questions; this plan carries their resolution and the measured evidence). The #66 spec (`docs/superpowers/specs/2026-08-18-scoped-retrieval-design.md`) stays the authority on scope semantics; see Decision 6 for the one sentence of it this plan supersedes.

**Release context:** #71 is the last unstarted code item (with #65) in the release tracked by [issue #69](https://github.com/dcltdw/bunnyforge/issues/69). #69's "Notes for whoever cuts it" carries a contingency paragraph for #71 *not* landing — Task 3 makes that paragraph moot and says so on the tracker.

## Global Constraints

- Python ≥ 3.11; **stdlib only at runtime**; no new dependencies of any kind.
- **No test may write into the repo.** Every test scaffolds into `tempfile.TemporaryDirectory()` (the `StoreCase` base class already does). CI enforces this.
- **Never `pip install` into any shared environment.** The primary clone's venv runs a live campaign.
- Run the suite from the worktree root as:
  `PYTHONPATH=src python3 -m unittest discover -s tests -t .`
  Bare `python3` in a worktree resolves `bunnyforge` to the primary clone. Verify once per session with:
  `PYTHONPATH=src python3 -c "import bunnyforge; print(bunnyforge.__file__)"` — the path must be inside the worktree.
- Baseline on this branch (`worktree-issue-71-search-live-first`, forked from `main` at `a42cc79`): `Ran 926 tests … OK (skipped=57)` — verified in this worktree before this plan was written. The 57 skips are the optional `mcp` extra and are expected locally.
- **Never commit to `main`.** Work on `worktree-issue-71-search-live-first`. Every commit carries a `Co-Authored-By:` trailer naming the model running the session; the commit messages below assume Opus 5 — adjust the trailer if the session's model directive differs.

---

## Design decisions

The ticket raises four questions and warns against adopting its own one-line fix unexamined. All six decisions below were settled during brainstorming against probes run in this worktree (evidence table follows). Do not re-open them; if the evidence looks wrong, re-run the probes before changing course.

### The evidence

Probes run against `a42cc79` in this worktree, on scratch workspaces scaffolded into temp directories (60-file corpus per the ticket's reproduction, plus boundary cases):

| Probe | Result |
|---|---|
| 60 archived + 1 live file, all matching, default scope | 50 real hits, **0 live** — first hit `Archive/NPCs/extra-000.md`. Ticket reproduced exactly. |
| Same corpus, `section="NPCs"` | Identical — sections resolve across both trees (#66), and `Archive/NPCs/` still sorts first. The section filter does not rescue. |
| Exactly `SEARCH_CAP` matches | Sentinel row appears **today even though nothing was cut** — the notice lies at the boundary. (Pre-existing; fixed by Task 2's check-before-append.) |
| Candidate fix applied, 60 archived + 1 live | Live hit first, then 49 archived, then sentinel. |
| Candidate fix, 50 live + 1 archived matches | Last *shown* hit is live, yet the overflow (51st) match is archived → the "no live hits were cut" sentinel correctly fires. This is why the discriminator is the overflow match, **not** the last shown hit. |
| Candidate fix, full suite | **Exactly one failure**: `test_truncation_sentinel_shape_and_position`, on its pinned sentinel *text*. Confirms from the failing side that no current test encodes the live/archive interleaving — `TestSearch`/`TestScopedSearch` multi-hit assertions are set- or dict-based; the ordered ones are single-element. |
| Candidate fix reverted | Suite back to `Ran 926 tests … OK (skipped=57)`. |

### Decision 1 — result order becomes a contract, but a minimal one (ticket Q1)

**Yes: `search` promises that every live hit precedes every archived hit, with workspace-path order within each tree. Nothing more.**

This is not a relevance promise — `search`'s own docstring already rejects ranking ("deliberately literal rather than clever: an agent that can see the matched text decides relevance better than a ranking heuristic would"), and that stance stands. Live-first is the *ordering expression of a semantic commitment already shipped*: #62 made the archive "superseded, never current"; #66's doctrine says where archive disagrees with live, live wins. A reply that leads with superseded material under a cap contradicts doctrine the moment the cap binds. The promise is one sentence, stable, and exactly what makes the cap honest. "Promises are easier to add than remove" is acknowledged and accepted knowingly: this one is small, and removing it would mean re-deciding that superseded material may again displace current material — not a plausible future.

### Decision 2 — live-first generalizes; a per-tree cap does not (ticket Q2)

Generalization test: with no cap at all, would live-first still be right? Yes — an agent reading top-down meets current material first, archived rows follow, labelled. The ordering is meaningful independent of the cap, so it is not cap special-casing.

**Per-tree cap rejected.** It needs a quota constant with no principled value; it makes truncation two-dimensional, so the sentinel gets harder to keep true; within each tree the cut stays lexicographically arbitrary, so its "representative" claim is weak; and it can be strictly *worse* for live material — a 25/25 quota cuts live hits even when only 30 live files match and 20 slots go begging. Live-first strictly dominates for the tree doctrine says matters: **whenever live matches ≤ SEARCH_CAP, every live hit is in the reply.** The one thing a quota adds — guaranteed archive representation in a mixed truncated reply — already has a documented door (`scope="archive"`), and Task 2's sentinel names it at exactly the moment it is the right advice.

**Relevance ordering rejected** per the recorded design stance quoted in Decision 1.

### Decision 3 — interaction with an explicit scope (ticket Q3)

Under `scope="live"` or `scope="archive"` the sort key is inert — one tree, path order preserved (the key's second element). Verified by probe. Under an explicit `scope="both"` the union is reordered; that is the point, not a surprise, once the ordering is documented at the tool surface (Task 1 adds it to both the store docstring and the MCP tool description). No information is lost: every hit carries `archived`, so a caller wanting path-interleaved order can re-sort trivially. The #66 doctrine is *served*, not contradicted: the question-answering agent it sends to the default scope is precisely the agent this fix protects.

### Decision 4 — `SEARCH_CAP` stays 50 (ticket Q4)

The cap sizes the *reply* for the reading agent's context, not the corpus; the archive doubling the corpus does not change how many hits a reply should carry, only which hits — and live-first fixes which. Raising the cap merely moves the starvation threshold while the archive grows monotonically toward it. Recorded as decided-not-doing; the constant remains one line if a future GM wants it configurable.

### Decision 5 — the sentinel becomes truthful and case-aware (extends the ticket)

Live-first makes the shipped sentinel advice dead: under the new order, a default-scope reply's live hits are exactly what `scope="live"` would return (capped), so "pass scope='live'" can never surface anything the agent doesn't already have. The static text was also already wrong under explicit scopes — a `scope="archive"` search that truncates today tells the agent to *exclude archived material*. Since "the message text is the API" (house rule on `StoreError`, same principle), the sentinel is rewritten with three variants keyed on scope and on whether the **overflow match** (the would-be 51st hit) is archived, and — fixing the boundary lie measured above — appended only when that 51st match exists:

- `scope="both"`, overflow archived → every cut hit is archived: `(truncated at 50 hits — no live hits were cut, only archived ones; narrow the query, or pass scope='archive' to search the archive alone)`. Worded "no live hits were cut" rather than "every live hit is shown" so it stays literally true (vacuously) under `section="Archive"`, where live hits are impossible.
- `scope="both"`, overflow live → live material itself overflowed: `(truncated at 50 hits — live hits were cut and archived material was not reached; narrow the query, or add a section filter)`
- `scope="live"` or `scope="archive"` → one tree, no scope advice to give: `(truncated at 50 hits — narrow the query, or add a section filter)`

(The `50` is `SEARCH_CAP` via f-string throughout.)

### Decision 6 — deliberate non-changes

- **`iter_content_files` keeps its global path sort.** Its ordering is pinned by `TestEnumerator`'s whole-list assertions and relied on by `overview`, `list_entities`, review, and both exporters. The re-sort lives inside `search`, the only caller with a cap.
- **`list_entities` keeps path order.** No cap → no starvation → no defect. The ordering promise stays scoped to the one tool where it earns its keep; widening it doubles the contract for zero defect fixed. If a future ticket wants surface-wide consistency, live-first composes cleanly.
- **No doctrine (`src/bunnyforge/data/`) changes.** Doctrine speaks of scopes, never ordering, and stays correct as written. This also adds no unguarded packaged prose while #65 is unlanded.
- **The #66 spec's sentinel promise is kept in shape, superseded in text.** Shape (`{"path": "", "snippet": …}`, a notice not a result, no `archived` key, last row) survives unchanged. The spec's implicit static-text-always-appended behavior is superseded by Decision 5; specs are dated records and are not retro-edited — this paragraph is the record of the supersession.

---

### Task 1: Live before archived — the ordering contract and the cap fix

**Files:**
- Modify: `src/bunnyforge/_store.py` (`WorkspaceStore.search`, currently lines 237–278; the `search` docstring)
- Modify: `src/bunnyforge/serve_mcp.py` (the `search` tool docstring, currently lines 125–137)
- Test: `tests/test_store.py` (new class `TestLiveFirstSearch` after `TestScopedSearch`)

**Interfaces:**
- Consumes: `StoreCase.make_ws()` / `StoreCase.make_archived_ws()` from `tests/test_store.py:23-49`; `_store.SEARCH_CAP`; `WorkspaceStore.search(query, section=None, scope="both") -> list[dict]` with hit dicts `{"path", "snippet", "archived"}` and a sentinel row `{"path": "", "snippet": "(truncated …)"}`.
- Produces: the ordering behavior Task 2's sentinel tests build on (live hits strictly before archived hits in every `search` reply), and the `TestLiveFirstSearch` class Task 2 adds tests to.

- [ ] **Step 1: Verify the import resolves inside the worktree, on the right branch**

```bash
git branch --show-current
PYTHONPATH=src python3 -c "import bunnyforge; print(bunnyforge.__file__)"
```

Expected: `worktree-issue-71-search-live-first`, and a path containing `.claude/worktrees/`. If the import points at `/Users/dcltdw/Github/bunnyforge/src/...` with no worktree segment, stop — every later result would measure the primary clone.

- [ ] **Step 2: Confirm the clean baseline**

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -t . 2>&1 | grep -E "^(Ran|OK|FAILED)"
```

Expected: `Ran 926 tests …` then `OK (skipped=57)`.

- [ ] **Step 3: Write the two failing tests**

Add to `tests/test_store.py`, as a new class immediately after `TestScopedSearch` (before `TestScopedListEntities`):

```python
class TestLiveFirstSearch(StoreCase):
    """#71: every live hit precedes every archived hit, path order within
    each tree -- so SEARCH_CAP keeps the current answer instead of letting
    an archive that outgrew it fill the reply with superseded material.
    A minimal ordering contract, not relevance: the walk stays literal.
    """

    def test_live_hits_precede_archived_hits(self):
        # Exact list, per the TestEnumerator convention: order is the
        # contract here, so a set-based assertion would test nothing.
        # Uppercase sorts before lowercase, hence NPCs/ before
        # front-burner.md within the live group.
        store = _store.WorkspaceStore(self.make_archived_ws())
        self.assertEqual(
            [h["path"] for h in store.search("ferry")],
            ["NPCs/kim-ha-eun.md", "front-burner.md",
             "Archive/NPCs/old-hag.md", "Archive/stray.md"])

    def test_cap_prefers_live_hits_over_a_larger_archive(self):
        # The defect (#71): an archive bigger than SEARCH_CAP used to fill
        # the whole reply -- 50 archived hits, zero live, including the
        # live file that is the current answer. Live-first means every
        # live hit is present whenever live matches <= SEARCH_CAP.
        ws = self.make_ws()
        arch = ws.root / "Archive" / "NPCs"
        arch.mkdir(parents=True)
        for i in range(_store.SEARCH_CAP):
            (arch / f"extra-{i:03d}.md").write_text(
                f"---\ntitle: Extra {i}\nsummary: x\n---\nferry\n",
                encoding="utf-8")
        store = _store.WorkspaceStore(ws)
        hits = store.search("ferry")
        # 2 live + 48 archived fill the cap; the sentinel row ends it.
        self.assertEqual(
            [h["path"] for h in hits],
            ["NPCs/kim-ha-eun.md", "front-burner.md"]
            + [f"Archive/NPCs/extra-{i:03d}.md"
               for i in range(_store.SEARCH_CAP - 2)]
            + [""])
        self.assertFalse(hits[0]["archived"])
        self.assertTrue(hits[2]["archived"])
```

- [ ] **Step 4: Run them to verify they fail**

```bash
PYTHONPATH=src python3 -m unittest tests.test_store.TestLiveFirstSearch -v
```

Expected: **both FAIL**. `test_live_hits_precede_archived_hits` shows the actual order `['Archive/NPCs/old-hag.md', 'Archive/stray.md', 'NPCs/kim-ha-eun.md', 'front-burner.md']`; `test_cap_prefers_live_hits_over_a_larger_archive` shows 50 `Archive/NPCs/extra-*` paths and no live path at all — the defect, in a test. If either *passes* here, stop: the code under test is not `a42cc79`-clean.

- [ ] **Step 5: Implement the sort**

In `src/bunnyforge/_store.py`, `search`, replace:

```python
        hits: list[dict] = []
        for rec in _common.iter_content_files(self.ws):
```

with:

```python
        # Live before archived, path order within each tree (#71): an
        # archive that has outgrown SEARCH_CAP must not fill the reply
        # before any live file is seen. Re-sorted here, not in
        # iter_content_files, whose global path order its other callers
        # (and TestEnumerator's whole-list assertions) rely on.
        recs = sorted(
            _common.iter_content_files(self.ws),
            key=lambda r: (self._is_archived(
                r.path.relative_to(self.ws.root).parts),
                r.path.as_posix()))
        hits: list[dict] = []
        for rec in recs:
```

Then fix the now-false comment inside the cap block. Replace:

```python
                # Say so rather than truncating silently: a capped reply that
                # looks complete is worse than a short one that admits it.
                # Archived hits sort first (#66), so a large archive can
                # fill the cap before any live hit is seen -- name the
                # scope that actually works around it, not just "narrow".
```

with:

```python
                # Say so rather than truncating silently: a capped reply that
                # looks complete is worse than a short one that admits it.
                # Live sorts first (#71), so what survived the cap is the
                # current material.
```

(The sentinel *text* is unchanged in this task; Task 2 owns it.)

- [ ] **Step 6: State the promise in the store docstring**

In the same file, extend `search`'s docstring. After the paragraph ending `…so the caller buckets hits without parsing paths.`, add:

```python

        Hits are ordered live-first (#71): every live hit precedes every
        archived hit, path order within each tree -- so a capped reply
        keeps current material. That ordering is the whole promise;
        relevance stays the caller's job.
```

- [ ] **Step 7: State the promise in the MCP tool description**

In `src/bunnyforge/serve_mcp.py`, in the `search` tool docstring, change the sentence:

```
        (section="NPCs" covers NPCs/ and Archive/NPCs/). Use it
        to check what has already been established about a name, place,
        or idea.
```

to:

```
        (section="NPCs" covers NPCs/ and Archive/NPCs/). Live hits come
        before archived ones, so a truncated reply keeps current
        material. Use it to check what has already been established
        about a name, place, or idea.
```

- [ ] **Step 8: Run the new tests to verify they pass**

```bash
PYTHONPATH=src python3 -m unittest tests.test_store.TestLiveFirstSearch -v
```

Expected: both PASS.

- [ ] **Step 9: Run the full suite**

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -t . 2>&1 | grep -E "^(Ran|OK|FAILED)|^(FAIL|ERROR): "
```

Expected: `Ran 928 tests …` then `OK (skipped=57)` — the two new tests, and nothing else moved. In particular `test_truncation_sentinel_shape_and_position` still passes: its fixture is all-live and this task did not touch the sentinel text.

- [ ] **Step 10: Commit**

```bash
git branch --show-current   # confirm: worktree-issue-71-search-live-first
git add src/bunnyforge/_store.py src/bunnyforge/serve_mcp.py tests/test_store.py
git commit -m "$(cat <<'EOF'
fix: search returns live hits before archived ones, so the cap keeps the current answer

Archive/ sorts lexicographically before every live section, and search
walked that order into SEARCH_CAP -- on a campaign whose archive outgrew
the cap, a default-scope search returned 50 archived hits and zero live
ones, including the live file that was the current answer (#71). Reproduced
at 60 archived + 1 live: 50 real hits, none live, and section="NPCs" does
not rescue it because sections resolve across both trees (#66).

The walk is re-sorted inside search with a (is_archived, path) key: live
before archived, path order within each tree, every live hit present
whenever live matches fit the cap. That one sentence is now the tool's
ordering contract -- deliberately minimal, the ordering expression of
doctrine already shipped (#62: the archive is superseded, never current),
not a relevance promise; the docstring still sends relevance judgement to
the caller. iter_content_files keeps its global path sort, which its other
callers and TestEnumerator's whole-list assertions rely on.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: A sentinel that says truthfully what was cut

**Files:**
- Modify: `src/bunnyforge/_store.py` (the cap block inside `search`; one docstring sentence)
- Modify: `tests/test_store.py` (`TestSearch.test_truncation_sentinel_shape_and_position`; three new tests in `TestLiveFirstSearch`)

**Interfaces:**
- Consumes: Task 1's ordering (live strictly before archived), `TestLiveFirstSearch` from Task 1, `_store.SEARCH_CAP`.
- Produces: the final sentinel behavior — appended only when a 51st match exists, text in exactly three variants (verbatim below); nothing after this task depends on it, but the PR body in Task 3 describes it.

**The three sentinel texts, normative** (`{SEARCH_CAP}` interpolated; tests assert full-string equality, closing the negative space the way an `assertNotIn` on a substring could not):

| Condition | Snippet |
|---|---|
| `scope="both"`, overflow match archived | `(truncated at {SEARCH_CAP} hits — no live hits were cut, only archived ones; narrow the query, or pass scope='archive' to search the archive alone)` |
| `scope="both"`, overflow match live | `(truncated at {SEARCH_CAP} hits — live hits were cut and archived material was not reached; narrow the query, or add a section filter)` |
| `scope="live"` or `scope="archive"` | `(truncated at {SEARCH_CAP} hits — narrow the query, or add a section filter)` |

- [ ] **Step 1: Update the existing sentinel test and add three new ones**

First, in `TestSearch.test_truncation_sentinel_shape_and_position` (fixture: `SEARCH_CAP + 5` live files, no archive — so the overflow match is live), replace the two text assertions:

```python
        self.assertIn(f"truncated at {_store.SEARCH_CAP} hits",
                      sentinel["snippet"])
        self.assertIn("scope='live'", sentinel["snippet"])
```

with one exact-equality assertion:

```python
        self.assertEqual(
            sentinel["snippet"],
            f"(truncated at {_store.SEARCH_CAP} hits — live hits were "
            "cut and archived material was not reached; narrow the "
            "query, or add a section filter)")
```

(The shape assertions above it — `set(sentinel) == {"path", "snippet"}`, `path == ""`, last row, `archived` on every real hit — stay: that is the #66 spec promise this plan keeps.)

Then add to `TestLiveFirstSearch`:

```python
    def test_no_sentinel_when_the_cap_is_exactly_met(self):
        # Pre-#71 the sentinel appeared whenever the reply reached the
        # cap, even with nothing left to cut -- a complete reply that
        # claimed to be truncated. Now it appears only when a 51st match
        # exists.
        ws = self.make_ws()
        arch = ws.root / "Archive" / "NPCs"
        arch.mkdir(parents=True)
        for i in range(_store.SEARCH_CAP - 2):
            (arch / f"extra-{i:03d}.md").write_text(
                f"---\ntitle: Extra {i}\nsummary: x\n---\nferry\n",
                encoding="utf-8")
        store = _store.WorkspaceStore(ws)
        hits = store.search("ferry")   # exactly SEARCH_CAP matches
        self.assertEqual(len(hits), _store.SEARCH_CAP)
        self.assertNotEqual(hits[-1]["path"], "")

    def test_sentinel_when_only_archived_hits_were_cut(self):
        # The starved-cap case from test_cap_prefers_live_hits_over_a_
        # larger_archive: the overflow match is archived, so every cut
        # hit is archived and the notice names the scope that reaches
        # them. scope='live' would be dead advice here -- under
        # live-first, the default reply's live hits already are the
        # scope='live' reply.
        ws = self.make_ws()
        arch = ws.root / "Archive" / "NPCs"
        arch.mkdir(parents=True)
        for i in range(_store.SEARCH_CAP):
            (arch / f"extra-{i:03d}.md").write_text(
                f"---\ntitle: Extra {i}\nsummary: x\n---\nferry\n",
                encoding="utf-8")
        store = _store.WorkspaceStore(ws)
        hits = store.search("ferry")
        self.assertEqual(
            hits[-1]["snippet"],
            f"(truncated at {_store.SEARCH_CAP} hits — no live hits "
            "were cut, only archived ones; narrow the query, or pass "
            "scope='archive' to search the archive alone)")

    def test_explicit_scope_sentinel_gives_no_scope_advice(self):
        # One tree was asked for; telling the agent to change scope
        # would contradict its own request (the shipped static text did
        # exactly that under scope='archive').
        ws = self.make_ws()
        for i in range(_store.SEARCH_CAP + 1):
            (ws.root / "NPCs" / f"live-{i:03d}.md").write_text(
                f"---\ntitle: Live {i}\nsummary: x\n---\nferry\n",
                encoding="utf-8")
        arch = ws.root / "Archive" / "NPCs"
        arch.mkdir(parents=True)
        for i in range(_store.SEARCH_CAP + 1):
            (arch / f"old-{i:03d}.md").write_text(
                f"---\ntitle: Old {i}\nsummary: x\n---\nferry\n",
                encoding="utf-8")
        store = _store.WorkspaceStore(ws)
        for scope in ("live", "archive"):
            hits = store.search("ferry", scope=scope)
            self.assertEqual(
                hits[-1]["snippet"],
                f"(truncated at {_store.SEARCH_CAP} hits — narrow the "
                "query, or add a section filter)",
                scope)
```

- [ ] **Step 2: Run all four to verify they fail**

```bash
PYTHONPATH=src python3 -m unittest tests.test_store.TestLiveFirstSearch tests.test_store.TestSearch.test_truncation_sentinel_shape_and_position -v
```

Expected: the three new tests and the modified one **FAIL** (each on sentinel presence or text; the two Task 1 tests in the class still pass). If `test_no_sentinel_when_the_cap_is_exactly_met` passes here, the implementation somehow preceded the test — stop and check `git status`.

- [ ] **Step 3: Implement the truthful sentinel**

In `src/bunnyforge/_store.py`, `search`, replace the whole cap block:

```python
            lo = max(0, i - SNIPPET_RADIUS)
            hi = min(len(text), i + len(q) + SNIPPET_RADIUS)
            hits.append({"path": rel.as_posix(), "snippet": text[lo:hi],
                         "archived": self._is_archived(rel.parts)})
            if len(hits) >= SEARCH_CAP:
                # Say so rather than truncating silently: a capped reply that
                # looks complete is worse than a short one that admits it.
                # Live sorts first (#71), so what survived the cap is the
                # current material.
                hits.append({"path": "", "snippet":
                             f"(truncated at {SEARCH_CAP} hits — narrow "
                             "the query, or pass scope='live' to exclude "
                             "archived material)"})
                break
        return hits
```

with:

```python
            if len(hits) >= SEARCH_CAP:
                # This match is the 51st, so the reply is genuinely
                # truncated -- a reply of exactly SEARCH_CAP matches gets
                # no sentinel, because nothing was cut. Say what WAS cut:
                # live sorts first (#71), so an archived overflow match
                # means every remaining match is archived too, while a
                # live one means live material itself overflowed. Under
                # an explicit single-tree scope there is no scope advice
                # to give -- the shipped static text used to recommend
                # scope='live' even to a scope='archive' caller.
                if scope != "both":
                    advice = "narrow the query, or add a section filter"
                elif self._is_archived(rel.parts):
                    advice = ("no live hits were cut, only archived "
                              "ones; narrow the query, or pass "
                              "scope='archive' to search the archive "
                              "alone")
                else:
                    advice = ("live hits were cut and archived material "
                              "was not reached; narrow the query, or "
                              "add a section filter")
                hits.append({"path": "", "snippet":
                             f"(truncated at {SEARCH_CAP} hits — {advice})"})
                break
            lo = max(0, i - SNIPPET_RADIUS)
            hi = min(len(text), i + len(q) + SNIPPET_RADIUS)
            hits.append({"path": rel.as_posix(), "snippet": text[lo:hi],
                         "archived": self._is_archived(rel.parts)})
        return hits
```

(Note the structural change: the cap check moves **before** the append and examines the current — overflow — record. That is what makes "truncated" true and the variant choice correct even when the last shown hit is live but the overflow is archived, the 50-live-+-1-archived case from the evidence table.)

- [ ] **Step 4: Extend the store docstring**

In `search`'s docstring, after the sentence added in Task 1 (`…relevance stays the caller's job.`), add:

```python
        A truncated reply ends with a sentinel row that says which
        tree the cut hits came from; a reply that exactly fills the
        cap with nothing left over gets no sentinel.
```

- [ ] **Step 5: Run the four tests to verify they pass**

```bash
PYTHONPATH=src python3 -m unittest tests.test_store.TestLiveFirstSearch tests.test_store.TestSearch.test_truncation_sentinel_shape_and_position -v
```

Expected: all PASS (five in the class + the modified one).

- [ ] **Step 6: Run the full suite**

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -t . 2>&1 | grep -E "^(Ran|OK|FAILED)|^(FAIL|ERROR): "
```

Expected: `Ran 931 tests …` then `OK (skipped=57)` — three new tests on top of Task 1's 928.

- [ ] **Step 7: Commit**

```bash
git branch --show-current   # confirm: worktree-issue-71-search-live-first
git add src/bunnyforge/_store.py tests/test_store.py
git commit -m "$(cat <<'EOF'
fix: the truncation sentinel says what was cut, and only fires when something was

Live-first ordering (#71) made the shipped advice dead: a default reply's
live hits now ARE the scope='live' reply, so "pass scope='live'" could
never surface anything the agent did not already have -- and the static
text was recommending it even to scope='archive' callers. The sentinel now
has three variants keyed on scope and on whether the overflow match is
archived: "no live hits were cut" (the archive is what remains, and
scope='archive' reaches it), "live hits were cut" (narrowing is the only
route), or plain "narrow the query" under an explicit single-tree scope.

The cap check also moves before the append: the sentinel fires only when a
51st match exists, so a reply that exactly fills the cap no longer claims
to be truncated. The #66 shape promise is unchanged -- {path, snippet},
a notice not a result, last row.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: PR and release bookkeeping

**Files:** none — GitHub only.

**Interfaces:**
- Consumes: Tasks 1–2 committed on `worktree-issue-71-search-live-first`.
- Produces: nothing.

- [ ] **Step 1: Push and open the PR — use the `dcltdw:opening-a-pr` skill**

The skill governs the body and the reporting; base `main`, title along the lines of `search returns live hits before archived ones, so the cap keeps the current answer (#71)`, body must contain `Closes #71` and should summarize Decisions 1 and 5 (the ordering contract and the sentinel rewrite) so the review is of the design, not just the diff. Before pushing, honor the pre-push secret-scan rule from AGENTS.md.

- [ ] **Step 2: Wait for approval — do not self-merge**

- [ ] **Step 3: On merge — use the `dcltdw:cleaning-up-after-pr-merge` skill**

It owns branch/worktree cleanup and the board move of #71 to **Done**.

- [ ] **Step 4: Update the release tracker**

```bash
gh issue comment 69 --body "$(cat <<'EOF'
#71 landed. The "Notes for whoever cuts it" contingency ("If #71 does not
land in this release, say so in the release notes") is moot; the release
notes can instead say: search now returns live hits before archived ones,
so a capped reply keeps current material, and the truncation notice says
which tree was cut (and no longer fires on a reply that exactly fills the
cap). SEARCH_CAP stays 50 -- decided in the #71 plan, Decision 4.
EOF
)"
```

Also tick the `- [ ] #71` checkbox in #69's body (`gh issue edit 69 --body …` with the one-character change, or ask the GM to tick it if editing feels heavy-handed for a comment-tracked item).

---

## Self-Review

**Spec coverage.** The ticket's four questions and its two verify-don't-trust items:

| Ticket item | Where |
|---|---|
| Q1 — is order part of the contract? | Decision 1; implemented Task 1 (sort + both docstrings) |
| Q2 — does live-first generalize? | Decision 2 (per-tree cap and relevance ordering rejected with reasons) |
| Q3 — interaction with explicit scope | Decision 3; pinned by Task 2's explicit-scope sentinel test and Task 1's inert-key reasoning (probe-verified) |
| Q4 — revisit SEARCH_CAP? | Decision 4 — stays 50, recorded as decided-not-doing |
| "No test encodes the interleaving" | Verified twice: by reading (set/dict/single-element assertions) and by running the candidate fix (exactly one failure, the sentinel text pin) |
| Mutation-probe house style | Not needed here — this plan changes production code, so plain TDD supplies the watch-it-fail step (Task 1 Step 4, Task 2 Step 2); probes were used at plan time instead, evidence table above |
| #66 doctrine interaction | Decision 3 and Decision 6 — doctrine unchanged and served; spec supersession recorded |
| Sentinel stays true (release-tracker concern) | Decision 5; Task 2 |

**Placeholder scan.** No TBDs; every code step carries literal text, every run step carries the exact command and expected outcome, sentinel strings are normative in a table.

**Type consistency.** `search(query, section=None, scope="both") -> list[dict]`; hit rows `{"path": str, "snippet": str, "archived": bool}`; sentinel `{"path": "", "snippet": str}`; `_is_archived(parts: tuple[str, ...]) -> bool` — used identically across Tasks 1–2. Task 2's replacement block includes the comment text exactly as Task 1's Step 5 left it.

**Verification already done at plan time** (evidence table): the defect reproduces at `a42cc79`; the Task 1 sort plus the Task 2 sentinel logic (same mechanism, near-identical wording) were applied together in this worktree, produced every behavior the tests below pin — including the overflow-vs-last-hit discriminator case — broke exactly one existing test (the one Task 2 Step 1 updates), and were fully reverted. If execution sees different failures, stop and compare the worktree against `a42cc79` before editing.

**Executor caveat.** Tasks 1–2 edit the same two files and Task 2 builds on Task 1's ordering — run strictly in sequence, inline, in this worktree.
