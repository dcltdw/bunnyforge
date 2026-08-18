# Underscore Means Not-Canon Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement issue #62 per the approved spec: a `_`-prefixed path component means *not canon* (biconditionally), the archive becomes ordinary walked canon at `Archive/`, generated output gains the marker (`_Sheets/`, `_Reviews/`, `_Export/`), and a name-collisions check closes the review/deploy gap the walked archive opens.

**Architecture:** One predicate (`_common.is_machinery`) is honored by every surface: the walker skips machinery components, the store's canon resolver refuses them (absorbing PR #61's `propose_revision` guard), and both agent-facing families use it (resolving the drafts/inbound `.`-asymmetry). `exclude_dirs` shrinks to the repo-infrastructure exemption. The archive walks as a mirrored top-level section with categories derived from the mirrored inner section. Doctrine states the meaning in one new section; all edits to the packaged `AGENTS.md` are surgical hunks.

**Tech Stack:** Python ≥ 3.11, stdlib only. `unittest` via `python3 -m unittest discover -s tests -t . -v`. The MCP-dependent tests need `pip install -e '.[mcp]'`.

**Spec:** `docs/superpowers/specs/2026-08-18-underscore-means-not-canon-design.md` (committed on this branch). Read it before Task 1 — it carries the decision record, the evidence, and the amended collision-check scope (authority files only; the briefs pairing is doctrine-mandated duplication).

## Global Constraints

- **Python ≥ 3.11, stdlib only at runtime.** No new dependency.
- **`src/bunnyforge/data/doctrine/AGENTS.md` ships byte-identical into every workspace.** Task 8's seven hunks are the only edits to that file; no other rewording.
- **The fresh-workspace gate must stay green:** `bunnyforge init` then `bunnyforge review checkup` reports `Summary: 0 error(s), 0 warning(s).` (`tests/test_init.py::TestFreshWorkspacePassesTheGate`, plus a separate CI step).
- **No test may write into the repo.** CI has an explicit "No test wrote into the repo" step; tests scaffold into `tempfile.TemporaryDirectory()`.
- **Never commit to `main`.** Work on `feat/underscore-not-canon` (this branch); `main` is ruleset-protected and needs a PR plus four green checks.
- **Every commit carries a `Co-Authored-By:` trailer naming the AI model.**
- **Verify the interpreter before trusting any suite run:** in some worktrees bare `python3` resolves to another checkout's virtualenv. Run `python3 -c "import bunnyforge; print(bunnyforge.__file__)"` first; if the path is not inside this worktree, create a local venv (`python3 -m venv .venv && .venv/bin/pip install -e '.[mcp]'`) and use `.venv/bin/python` throughout.
- **Task order matters:** Task 1 must land before Task 2 (the machinery rule must own `_Templates/` exclusion before `exclude_dirs` stops enumerating it), and Task 2 before Task 3 (the archive walk reads `config.archive_dir`).

---

### Task 1: The predicate, and the walker honors it

`_common.is_machinery` is the one definition of "machinery-named". The walker (`iter_content_files`) starts skipping `_`/`.` components by rule rather than by enumeration. This also takes over `.git`/`.github` protection from `MANDATORY_EXCLUDES` (deleted in Task 2).

**Files:**
- Modify: `src/bunnyforge/_common.py` (add `is_machinery` after `split_aliases`, around line 165; use it in `iter_content_files`, lines 136-142)
- Test: `tests/test_review.py` (class `TestEnumerator`, line 40; new class `TestIsMachinery`)

**Interfaces:**
- Produces: `_common.is_machinery(part: str) -> bool` — True when one path component starts with `_` or `.`. Tasks 3, 4, and 5 consume it. Note `_common` imports `_config`, so `_config` can NEVER import this (Task 2 inlines its one config-value check instead).

- [ ] **Step 1: Write the failing tests**

In `tests/test_review.py`, add to `class TestEnumerator` after `test_exclude_dirs_filters_nested_directories_too`:

```python
    def test_machinery_components_are_skipped_by_the_general_rule(self):
        # #62: a leading _ means "not canon" wherever it appears. The rule
        # itself keeps these out -- none of these names is in exclude_dirs.
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "NPCs/mira-venn.md": "---\ntype: npc\nvisibility: gm-only\n---\nbody",
                "NPCs/_scratch/half-idea.md": "---\ntype: npc\n---\nx",
                "NPCs/_notes.md": "not canon by name",
                "NPCs/.hidden.md": "os droppings",
            })
            ws = _config.open_workspace(root)
            rels = [r.path.relative_to(ws.root).as_posix()
                    for r in review._common.iter_content_files(ws)]
            self.assertEqual(rels, ["NPCs/mira-venn.md"])

    def test_git_internals_are_never_walked(self):
        # Previously guaranteed by MANDATORY_EXCLUDES; the .-prefix rule
        # owns it now. Guarded here because Task 2 deletes that frozenset.
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "NPCs/mira-venn.md": "---\ntype: npc\nvisibility: gm-only\n---\nbody",
                "NPCs/.git/lost.md": "---\ntype: npc\n---\nx",
            })
            ws = _config.open_workspace(root)
            rels = [r.path.relative_to(ws.root).as_posix()
                    for r in review._common.iter_content_files(ws)]
            self.assertEqual(rels, ["NPCs/mira-venn.md"])
```

And a new class immediately after `TestEnumerator`:

```python
class TestIsMachinery(unittest.TestCase):
    def test_prefixes(self):
        for part, expect in [("_Ignore", True), (".git", True),
                             ("_notes.md", True), (".DS_Store", True),
                             ("NPCs", False), ("Archive", False),
                             ("kim-ha-eun.md", False), ("a_b.md", False)]:
            with self.subTest(part=part):
                self.assertEqual(review._common.is_machinery(part), expect)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_review -k "machinery or git_internals" -v`

Expected: FAIL — `AttributeError` for `is_machinery`, and the two enumerator tests finding the machinery paths in the walk.

- [ ] **Step 3: Implement**

In `src/bunnyforge/_common.py`, after `split_aliases` (around line 165):

```python
def is_machinery(part: str) -> bool:
    """True if one path component is machinery by naming convention (#62):
    _-prefixed (not canon -- _Ignore/, _Templates/, _AgentDrafts/, _Done/)
    or .-prefixed (hidden machine files -- .git, .DS_Store,
    .proposal-bases.json).

    One definition, honoured by iter_content_files, the store's canon
    resolver and both agent-facing families, and review's checks, so no
    two surfaces can disagree about what counts. _config.py's archive_dir
    validation inlines the same one-line test: _common imports _config,
    so importing this from there would be circular.
    """
    return part.startswith(("_", "."))
```

In `iter_content_files`, replace the loop body at lines 136-142:

```python
            for p in base.rglob("*.md"):
                if p.name.lower() == "readme.md":
                    continue
                parts = p.relative_to(workspace).parts
                if config.exclude_dirs & set(parts):
                    continue
                if any(is_machinery(part) for part in parts):
                    continue
                fm, body = split_front_matter(p.read_text(encoding="utf-8"))
                recs.append(FileRec(p, fm, body, category))
```

- [ ] **Step 4: Run the review suite to verify it passes**

Run: `python3 -m unittest tests.test_review -v`

Expected: PASS, including the pre-existing `test_categories_and_exclusions` and `test_exclude_dirs_filters_nested_directories_too` — the machinery rule now skips `_Archive`/`_Templates` redundantly with `exclude_dirs`, so behavior is unchanged there.

- [ ] **Step 5: Run the whole suite**

Run: `python3 -m unittest discover -s tests -t . -v`

Expected: PASS. Nothing else walks machinery-named paths today (verified during design: no shipped/scaffolded/sample path has one outside the documented directories).

- [ ] **Step 6: Commit**

```bash
git add src/bunnyforge/_common.py tests/test_review.py
git commit -m "feat: is_machinery — the walker skips _- and .-prefixed components by rule"
```

---

### Task 2: Configuration — exclude_dirs shrinks, archive_dir arrives, sheets_dir renames

**Files:**
- Modify: `src/bunnyforge/_config.py:31-32` (delete `MANDATORY_EXCLUDES`), `:34-38` (Config fields), `:111-132` (`_DEFAULTS`), `:328-341` (validation), `:342-364` (Config construction)
- Modify: `src/bunnyforge/data/campaign.toml.in` (the commented `exclude_dirs`, `sheets_dir` examples; add `archive_dir`)
- Test: `tests/test_config.py:55-59, 180`

**Interfaces:**
- Consumes: `_common.is_machinery` exists (Task 1) but is NOT importable here — inline the check.
- Produces: `Config.archive_dir: str` (default `"Archive"`), `Config.sheets_dir` default `"_Sheets"`, `Config.exclude_dirs` default contributing `{"docs", "scripts", "tests"}` plus the load-time `{inbound_dir, drafts_dir}` append (which stays). Tasks 3, 6 consume `config.archive_dir`.

- [ ] **Step 1: Check for positional Config construction**

Run: `grep -rn "Config(" tests/ src/ | grep -v "namedtuple\|ConfigError\|open_workspace\|_config.load"`

Expected: the only real constructor call is `_config.py`'s keyword-argument `return Config(...)`. If any test builds `Config` positionally, adding a field mid-string breaks it — fix that test to keywords in this task.

- [ ] **Step 2: Write the failing tests**

In `tests/test_config.py`, REPLACE `test_exclude_dirs_always_include_git` (lines 55-59) with:

```python
    def test_exclude_dirs_no_longer_carries_git(self):
        # .git/.github protection moved from MANDATORY_EXCLUDES to the
        # .-prefix machinery rule (#62) -- see test_review's
        # TestEnumerator.test_git_internals_are_never_walked for the
        # behavioural guard.
        cfg = _config.load(self._ws(MINIMAL + '\n[workspace]\nexclude_dirs = ["OnlyThis"]\n'))
        self.assertIn("OnlyThis", cfg.exclude_dirs)
        self.assertNotIn(".git", cfg.exclude_dirs)
        self.assertNotIn(".github", cfg.exclude_dirs)
```

(Keep the file's existing `MINIMAL` constant and `_ws` helper exactly as the old test used them.)

Update line 180's assertion from `self.assertEqual(cfg.sheets_dir, "Sheets")` to `self.assertEqual(cfg.sheets_dir, "_Sheets")`.

Add to the same class as the sheets_dir tests:

```python
    def test_archive_dir_default_and_override(self):
        cfg = _config.load(self._ws(MINIMAL))
        self.assertEqual(cfg.archive_dir, "Archive")
        cfg = _config.load(self._ws(
            MINIMAL + '\n[workspace]\narchive_dir = "History"\n'))
        self.assertEqual(cfg.archive_dir, "History")

    def test_archive_dir_rejects_machinery_and_collisions(self):
        # The archive is canon by definition (#62): a machinery-marked name
        # would exclude it from every walk, and a section or staging name
        # would double-book a directory that has another meaning.
        for bad in ('archive_dir = "_Archive"',
                    'archive_dir = ".Archive"',
                    'archive_dir = "NPCs"',
                    'archive_dir = "Briefs"'):
            with self.subTest(bad=bad):
                with self.assertRaises(_config.ConfigError):
                    _config.load(self._ws(
                        MINIMAL + "\n[workspace]\n" + bad + "\n"))

    def test_default_exclude_dirs_is_the_repo_infra_exemption(self):
        cfg = _config.load(self._ws(MINIMAL))
        # docs/scripts/tests plus the always-appended staging dirs; the
        # underscore names are the rule's job now, not the enumeration's.
        self.assertEqual(cfg.exclude_dirs,
                         frozenset({"docs", "scripts", "tests",
                                    "_ExtractInbound", "_AgentDrafts"}))
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_config -v`

Expected: FAIL — `archive_dir` attribute missing, sheets_dir still `"Sheets"`, `.git` still present in `exclude_dirs`.

- [ ] **Step 4: Implement**

In `src/bunnyforge/_config.py`:

1. Delete `MANDATORY_EXCLUDES` (lines 31-32) and its comment.
2. In the `Config = namedtuple(...)` field string, change `"briefs_dir sheets_dir perceptions_dir type_dirs inbound_dir drafts_dir "` to `"briefs_dir sheets_dir perceptions_dir archive_dir type_dirs inbound_dir drafts_dir "`.
3. In `_DEFAULTS`: `"exclude_dirs": ["docs", "scripts", "tests"],` (replacing the eight-entry list and trimming its comment to say the underscore names are covered by the machinery rule); `"sheets_dir": "_Sheets",`; add `"archive_dir": "Archive",` next to `"sheets_dir"`.
4. In `load()`, after the existing inbound/drafts validation block (ends line 340), add:

```python
    archive_dir = _str(ws, "archive_dir")
    if archive_dir in entity_dirs or archive_dir in inherit_dirs:
        raise ConfigError(
            f"{path}: workspace.archive_dir = {archive_dir!r} names a "
            "content section — the archive mirrors sections inside itself; "
            "pick a directory of its own")
    if archive_dir[:1] in ("_", "."):
        # Inline _common.is_machinery: _common imports _config, so the
        # shared predicate cannot be imported here.
        raise ConfigError(
            f"{path}: workspace.archive_dir = {archive_dir!r} is _- or "
            ".-prefixed — the archive is canon by definition (#62); a "
            "machinery-marked name would exclude it from every walk")
    if archive_dir in (inbound_dir, drafts_dir):
        raise ConfigError(
            f"{path}: workspace.archive_dir = {archive_dir!r} collides "
            "with inbound_dir/drafts_dir, which are excluded from every "
            "walk — the archive must not be")
```

5. In the `return Config(...)` call: `exclude_dirs=(frozenset(_str_tuple(ws, "exclude_dirs")) | {inbound_dir, drafts_dir}),` and add `archive_dir=archive_dir,` next to `sheets_dir=`.

In `src/bunnyforge/data/campaign.toml.in`, update the commented examples to mirror the new defaults exactly (the `exclude_dirs` example becomes one line `# exclude_dirs    = ["docs", "scripts", "tests"]`, `# sheets_dir      = "_Sheets"`, and add `# archive_dir     = "Archive"` beside it, preserving the file's column alignment).

- [ ] **Step 5: Run config and init suites**

Run: `python3 -m unittest tests.test_config tests.test_init -v`

Expected: PASS. If `tests/test_init.py` has a test asserting commented examples match `_DEFAULTS` (`test_every_defaultable_key_equals_its_default` or similar), it validates the `campaign.toml.in` edit — read its parsing rules and match the format it expects. `TestFreshWorkspacePassesTheGate` must stay green: `_Templates/` is now excluded by the machinery rule from Task 1, not by enumeration.

- [ ] **Step 6: Run the whole suite, then commit**

Run: `python3 -m unittest discover -s tests -t . -v`

Expected: PASS.

```bash
git add src/bunnyforge/_config.py src/bunnyforge/data/campaign.toml.in tests/test_config.py
git commit -m "feat: archive_dir config, _Sheets default, exclude_dirs shrinks to the repo-infra exemption"
```

---

### Task 3: The archive walks as canon

**Files:**
- Modify: `src/bunnyforge/_common.py` (`iter_content_files`, after the entity/inherit loops; `content_dir_names`, around line 174)
- Modify: `src/bunnyforge/_store.py:70-77` (`_sections`), the `_draftable_sections` method (around line 233)
- Test: `tests/test_review.py` (`TestEnumerator`), `tests/test_store.py` (`TestOverview` area and `TestSaveDraft`)

**Interfaces:**
- Consumes: `config.archive_dir` (Task 2), `is_machinery` (Task 1).
- Produces: archive files appear in `iter_content_files` with category derived from the mirrored section; `"Archive"` is a valid section for `list_entities`/`search`/`overview`; `content_dir_names` includes the archive dir (so `[[Archive]]` is a pass-through directory link). Tasks 5 and 6 rely on archive files being walked.

- [ ] **Step 1: Write the failing tests**

In `tests/test_review.py`, add to `TestEnumerator`:

```python
    def test_archive_is_walked_as_canon_with_mirrored_categories(self):
        # #62: Archive/ is the record of what happened -- ordinary canon,
        # mirrored layout. Category follows the mirrored section; unknown
        # mirrors and root-level strays default to entity so they stay
        # visible to the front-matter check (fail loud, never a silent hole).
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "NPCs/mira-venn.md": "---\ntype: npc\nvisibility: gm-only\n---\nbody",
                "Archive/NPCs/old-hag.md":
                    "---\ntype: npc\nvisibility: gm-only\nstatus: retired\n---\nx",
                "Archive/Briefs/session-001/old-brief.md": "---\ntype: brief\n---\nx",
                "Archive/stray.md": "---\ntype: npc\n---\nx",
                "Archive/_Done/never.md": "machinery inside canon stays out",
                "Archive/README.md": "# readme",
            })
            ws = _config.open_workspace(root)
            by_path = {r.path.relative_to(ws.root).as_posix(): r
                       for r in review._common.iter_content_files(ws)}
            self.assertEqual(by_path["Archive/NPCs/old-hag.md"].category, "entity")
            self.assertEqual(
                by_path["Archive/Briefs/session-001/old-brief.md"].category,
                "inherit")
            self.assertEqual(by_path["Archive/stray.md"].category, "entity")
            self.assertNotIn("Archive/_Done/never.md", by_path)
            self.assertNotIn("Archive/README.md", by_path)

    def test_archive_is_a_content_dir_name(self):
        # A bare [[Archive]] link is a directory link, like [[Mechanics]] --
        # content_dir_names feeds both the wikilink check and the exporter.
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {})
            ws = _config.open_workspace(root)
            self.assertIn("archive",
                          review._common.content_dir_names(ws.config))
```

In `tests/test_store.py`, add to `class TestOverview`:

```python
    def test_archive_is_a_section_of_its_own(self):
        # #62 fixed a latent contradiction: doctrine said "read the archive
        # freely" while the MCP surface refused it entirely. Now it lists,
        # reads, counts, and searches like any canon -- as its own section,
        # so live counts stay uninflated.
        ws = self.make_ws()
        arch = ws.root / "Archive" / "NPCs"
        arch.mkdir(parents=True)
        (arch / "old-hag.md").write_text(
            "---\ntitle: The Old Hag\nsummary: Retired rival of the ferry.\n"
            "visibility: gm-only\nstatus: retired\n---\ngone but recorded\n",
            encoding="utf-8")
        store = _store.WorkspaceStore(ws)
        ov = store.overview()
        self.assertEqual(ov["sections"]["NPCs"], 1)
        self.assertEqual(ov["sections"]["Archive"], 1)
        [row] = store.list_entities("Archive")
        self.assertEqual(row["path"], "Archive/NPCs/old-hag.md")
        self.assertEqual(row["title"], "The Old Hag")
        self.assertIn("recorded", store.read_entity("Archive/NPCs/old-hag.md"))
        hits = store.search("recorded", section="Archive")
        self.assertEqual(hits[0]["path"], "Archive/NPCs/old-hag.md")
```

In `tests/test_store.py`, add to `class TestSaveDraft`:

```python
    def test_archive_is_not_a_draftable_section(self):
        # New material never lands retired; archiving is a GM act. The
        # perceptions record has the same one-way property.
        store = _store.WorkspaceStore(self.make_ws())
        with self.assertRaises(_store.StoreError) as ctx:
            store.save_draft("Archive", "Old Thing", "x")
        self.assertIn("Archive", str(ctx.exception))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_review -k archive_is_walked -v && python3 -m unittest tests.test_store -k "archive_is_a_section or archive_is_not" -v`

Expected: FAIL — no archive records in the walk; `list_entities("Archive")` raises unknown-section; `save_draft("Archive", ...)` raises for the wrong reason (unknown section — the test asserts the message, which passes either way, so rely on the first two failures; the draftable test goes red only if `_sections` grows before `_draftable_sections` filters).

- [ ] **Step 3: Implement**

In `_common.iter_content_files`, after the entity/inherit loops and before the `return`:

```python
    # The archive walks as canon (#62): mirrored top-level layout,
    # Archive/<Section>/<file>.md. Category follows the mirror so archived
    # briefs stay brief-shaped to every check; unknown mirrors and files
    # directly at the archive root default to "entity" -- visible and
    # validated rather than silently skipped.
    inherit_names = set(config.inherit_dirs)
    base = workspace / config.archive_dir
    if base.is_dir():
        for p in base.rglob("*.md"):
            if p.name.lower() == "readme.md":
                continue
            parts = p.relative_to(workspace).parts
            if config.exclude_dirs & set(parts):
                continue
            if any(is_machinery(part) for part in parts):
                continue
            mirror = parts[1] if len(parts) > 2 else None
            category = "inherit" if mirror in inherit_names else "entity"
            fm, body = split_front_matter(p.read_text(encoding="utf-8"))
            recs.append(FileRec(p, fm, body, category))
```

In `content_dir_names`, include the archive:

```python
    return frozenset(d.lower() for d in
                     config.entity_dirs + config.inherit_dirs
                     + (config.archive_dir,))
```

In `_store.py`:

```python
    def _sections(self) -> tuple[str, ...]:
        cfg = self.ws.config
        return cfg.entity_dirs + cfg.inherit_dirs + (cfg.archive_dir,)
```

```python
    def _draftable_sections(self) -> tuple[str, ...]:
        # The perception record is by contract never agent-authored, and
        # new material never lands retired: archiving is a GM act.
        cfg = self.ws.config
        return tuple(s for s in self._sections()
                     if s not in (cfg.perceptions_dir, cfg.archive_dir))
```

- [ ] **Step 4: Run the review, store, and export suites**

Run: `python3 -m unittest tests.test_review tests.test_store tests.test_export_player -v`

Expected: PASS. `test_export_player` matters here: archive entity files now flow through the export walk under normal visibility rules (the spec's no-carve-out decision), and no existing test scaffolds an archive, so nothing should change — if something fails, read it before touching it.

- [ ] **Step 5: Run the whole suite, then commit**

Run: `python3 -m unittest discover -s tests -t . -v`

Expected: PASS.

```bash
git add src/bunnyforge/_common.py src/bunnyforge/_store.py tests/test_review.py tests/test_store.py
git commit -m "feat: Archive/ is walked, listed, read, and searched as ordinary canon"
```

---

### Task 4: The store enforces the one meaning

`_canonical` refuses machinery components (absorbing PR #61's `propose_revision` guard), and both families adopt the shared predicate — resolving the `.`-asymmetry (inbound skipped `.`-components, drafts did not).

**Files:**
- Modify: `src/bunnyforge/_store.py:79-97` (`_canonical`), `:263-267` (`_draft_path`), `:329-362` (`propose_revision` — delete the guard), `:391-393` (`list_drafts`), `:496-513` (inbound comment + delete the `_machinery` staticmethod), `:526, :544` (its call sites)
- Test: `tests/test_store.py` (`TestReadEntity`, `TestProposeRevision`, `TestDraftReads`)

**Interfaces:**
- Consumes: `_common.is_machinery` (Task 1). `_store` already imports `_common`.
- Produces: every canon door (`read_entity`, `write_entity`, `propose_revision`) refuses machinery paths via `_canonical`, with a message containing the phrase `not canon`. Task 8's doctrine text and Task 9's docs describe this behavior.

- [ ] **Step 1: Write the failing tests**

In `tests/test_store.py`, add to `class TestReadEntity`:

```python
    def test_machinery_paths_are_refused_as_not_canon(self):
        # #62: _-prefixed means not canon, and the canon tools serve canon.
        # This is the general rule that absorbed PR #61's propose_revision
        # guard -- refusal now happens at _canonical, one door for all.
        ws = self.make_ws()
        (ws.root / "NPCs" / "_notes.md").write_text("x", encoding="utf-8")
        store = _store.WorkspaceStore(ws)
        with self.assertRaises(_store.StoreError) as ctx:
            store.read_entity("NPCs/_notes.md")
        self.assertIn("not canon", str(ctx.exception))
```

In `class TestProposeRevision`, REPLACE the body of `test_refuses_a_target_with_an_underscore_component` (line 381) — same behavior, new mechanism — and add the dot case:

```python
    def test_refuses_a_target_with_an_underscore_component(self):
        # The refusal moved from a bespoke guard into _canonical (#62):
        # a machinery-named path is not canon, so there is nothing to
        # propose against. The old lockout (a shadow stranded in the
        # drafts machinery area) is structurally impossible now.
        ws = self.make_ws()
        (ws.root / "NPCs" / "_notes.md").write_text("secret", encoding="utf-8")
        store = _store.WorkspaceStore(ws)
        with self.assertRaises(_store.StoreError) as ctx:
            store.propose_revision("NPCs/_notes.md", "x")
        self.assertIn("NPCs/_notes.md", str(ctx.exception))
        self.assertFalse((ws.root / "_AgentDrafts").exists())

    def test_refuses_a_target_with_a_dot_component(self):
        ws = self.make_ws()
        hidden = ws.root / "NPCs" / ".hidden"
        hidden.mkdir()
        (hidden / "notes.md").write_text("secret", encoding="utf-8")
        store = _store.WorkspaceStore(ws)
        with self.assertRaises(_store.StoreError) as ctx:
            store.propose_revision("NPCs/.hidden/notes.md", "x")
        self.assertIn("NPCs/.hidden/notes.md", str(ctx.exception))
        self.assertFalse((ws.root / "_AgentDrafts").exists())

    def test_archive_targets_are_ordinary_canon(self):
        # Spec decision: no write carve-out. A revision to an archived file
        # mirrors into the drafts tree like any canon target; the doctrine,
        # not the tools, governs when editing history is appropriate.
        ws = self.make_ws()
        arch = ws.root / "Archive" / "NPCs"
        arch.mkdir(parents=True)
        (arch / "old-hag.md").write_text(
            "---\ntitle: Old Hag\n---\nx", encoding="utf-8")
        store = _store.WorkspaceStore(ws)
        rel = store.propose_revision("Archive/NPCs/old-hag.md", "y")
        self.assertEqual(rel, "_AgentDrafts/Archive/NPCs/old-hag.md")
```

In `class TestDraftReads`, after `test_an_underscore_component_is_refused` (line 488):

```python
    def test_a_dot_component_is_refused_like_an_underscore(self):
        # The two families disagreed: inbound skipped .-prefixed
        # components, drafts did not (#62). Unified: one predicate.
        ws = self.make_ws()
        hidden = ws.root / "_AgentDrafts" / ".obsidian"
        hidden.mkdir(parents=True)
        (hidden / "stray.md").write_text("x", encoding="utf-8")
        with self.assertRaises(_store.StoreError):
            _store.WorkspaceStore(ws).read_draft(
                "_AgentDrafts/.obsidian/stray.md")
```

And after `test_listing_skips_underscore_components` (line 454):

```python
    def test_listing_skips_dot_components(self):
        ws = self.make_ws()
        store = _store.WorkspaceStore(ws)
        store.save_draft("NPCs", "Cho", "x")
        hidden = ws.root / "_AgentDrafts" / ".trash"
        hidden.mkdir(parents=True)
        (hidden / "old.md").write_text("x", encoding="utf-8")
        self.assertEqual([r["path"] for r in store.list_drafts()],
                         ["_AgentDrafts/NPCs/cho.md"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_store -k "not_canon or dot_component" -v`

Expected: FAIL — `read_entity` returns content, the dot-target proposal succeeds, `read_draft` serves the hidden file, listing includes `.trash/old.md`. (The underscore propose test passes already via the old guard; it goes through the new path after Step 3.)

- [ ] **Step 3: Implement**

Replace `_canonical` (lines 79-97):

```python
    def _canonical(self, path: str) -> Path:
        """Resolve a workspace-relative path, refusing what is not canon.

        Two refusals, one meaning (#62): a _- or .-prefixed component is
        not canon by the naming convention — which is also what keeps the
        drafts and inbound directories out; each of those has its own
        labelled door (read_draft, read_inbound) guarding the inverse
        condition. An exclude_dirs component is repo infrastructure the
        config enumerates (docs/, scripts/, tests/).
        """
        root = self.ws.root
        p = (root / path).resolve()
        if not p.is_relative_to(root):
            raise StoreError(f"path escapes the workspace: {path}")
        parts = p.relative_to(root).parts
        if any(_common.is_machinery(part) for part in parts):
            raise StoreError(
                f"{path} has a _- or .-prefixed component, so it is not "
                "canon (the workspace naming convention); the canon tools "
                "serve canon only — drafts are read with read_draft, the "
                "inbound queue with read_inbound")
        excluded = self.ws.config.exclude_dirs & set(parts)
        if excluded:
            raise StoreError(
                f"path is in an excluded directory ({', '.join(sorted(excluded))}): "
                f"{path}")
        return p
```

In `propose_revision`, delete the entire guard (the `if any(part.startswith("_") ...)` block with its long comment, lines 337-352). Keep `inner = target.relative_to(self.ws.root)` — the shadow destination still uses it.

In `_draft_path`, replace lines 263-267:

```python
        if any(_common.is_machinery(part)
               for part in p.relative_to(drafts).parts):
            raise StoreError(
                f"{path} is in a _- or .-prefixed area of the drafts "
                "directory (the GM's machinery, e.g. _Rejected/, or hidden "
                "files) and is never served")
```

In `list_drafts`, replace lines 392-393:

```python
            if any(_common.is_machinery(part) for part in inner.parts):
                continue
```

Delete the `_machinery` staticmethod (lines 508-513). Replace its two call sites (lines 526 and 544) with the same shape:

```python
        if any(_common.is_machinery(part)
               for part in p.relative_to(inbound).parts):
```

(at line 544 the block ends with `continue` as today). In the comment block above `_inbound` (lines 496-503), change `which refuses _-prefixed components` to `which refuses _- and .-prefixed components`.

- [ ] **Step 4: Run the store suite**

Run: `python3 -m unittest tests.test_store -v`

Expected: PASS — including every pre-existing underscore/machinery test (`test_an_underscore_component_is_refused`, `test_underscore_component_is_refused` in `TestUpdateDraft`, `test_done_is_never_listed`, `test_hidden_dot_files_are_skipped`). If a test pinned the old guard's message text, update the assertion to the new message, not the code.

- [ ] **Step 5: Run the whole suite, then commit**

Run: `python3 -m unittest discover -s tests -t . -v`

Expected: PASS.

```bash
git add src/bunnyforge/_store.py tests/test_store.py
git commit -m "feat: _canonical refuses machinery paths — one rule absorbs the propose_revision guard"
```

---

### Task 5: The name-collisions check

The walked archive makes stem/alias collisions reachable, and the wiki exporter refuses ambiguous links while checkup stays silent. Scope per the amended spec: **authority files only** (categories `entity` and `root`); inherit files are exempt because the doctrine mandates the briefs pairing.

**Files:**
- Modify: `src/bunnyforge/review.py` (new check after `check_reveal_when`, around line 323; `CHECKS` at line 488; `SUITES["checkup"]` at line 502)
- Test: `tests/test_review.py` (new class after `TestRevealWhen`)

**Interfaces:**
- Consumes: `target_index` (already imported in review.py), `_rel`, `Finding`. Severity literal is `"error"`.
- Produces: `review.check_name_collisions(files: list[FileRec], workspace: Path) -> list[Finding]`, registered as `"name-collisions"` in the `checkup` suite. Do NOT add it to `_NEEDS_WORKSPACE`/`_NEEDS_WIKI`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_review.py` after `class TestRevealWhen`:

```python
class TestNameCollisions(unittest.TestCase):
    """#62: every stem and alias among authority files must name exactly
    one file. The exporter refuses ambiguous links; this check surfaces
    them at review time instead of deploy time."""

    def test_live_vs_archive_stem_collision_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "NPCs/old-hag.md": "---\ntype: npc\n---\nnew",
                "Archive/NPCs/old-hag.md":
                    "---\ntype: npc\nstatus: retired\n---\nold",
            })
            ws = _config.open_workspace(root)
            files = review._common.iter_content_files(ws)
            [f] = review.check_name_collisions(files, ws.root)
            self.assertEqual(f.severity, "error")
            self.assertIn("NPCs/old-hag.md", f.message)
            self.assertIn("Archive/NPCs/old-hag.md", f.message)

    def test_alias_collisions_are_errors_too(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "NPCs/kim.md": "---\ntype: npc\naliases: [The Ghost]\n---\nx",
                "NPCs/cho.md": "---\ntype: npc\naliases: [The Ghost]\n---\nx",
            })
            ws = _config.open_workspace(root)
            files = review._common.iter_content_files(ws)
            found = review.check_name_collisions(files, ws.root)
            self.assertEqual(len(found), 1)
            self.assertIn("NPCs/cho.md", found[0].message)
            self.assertIn("NPCs/kim.md", found[0].message)

    def test_the_briefs_pairing_is_exempt(self):
        # The doctrine REQUIRES a brief's stem to match its subject's
        # writeup (doctrine: "Brief filenames must match their writeup").
        # Inherit files are designed subordination, not ambiguous authority,
        # and they are never exported.
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "NPCs/mira-venn.md": "---\ntype: npc\n---\nx",
                "Briefs/session-001/mira-venn.md": "---\ntype: brief\n---\nx",
            })
            ws = _config.open_workspace(root)
            files = review._common.iter_content_files(ws)
            self.assertEqual(review.check_name_collisions(files, ws.root), [])

    def test_wired_into_checkup(self):
        self.assertIn("name-collisions", review.CHECKS)
        self.assertIn("name-collisions", review.SUITES["checkup"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_review -k NameCollisions -v`

Expected: FAIL with `AttributeError: ... no attribute 'check_name_collisions'`.

- [ ] **Step 3: Implement**

In `src/bunnyforge/review.py`, after `check_reveal_when`:

```python
def check_name_collisions(files: list[FileRec], workspace: Path) -> list[Finding]:
    """Every stem and alias among authority files must be unique (#62).

    The wiki exporter refuses ambiguous links rather than guessing, and
    with the archive walked, a retired file and its live replacement
    would collide silently until deploy time. Authority means categories
    "entity" and "root". Inherit files are exempt on purpose: the
    doctrine REQUIRES a brief's stem to match its subject's writeup
    (Briefs/session-014/mira-venn.md pairs with NPCs/mira-venn.md), the
    perception record follows the same subject-naming pattern, and
    inherit files are never exported — designed subordination, not
    ambiguity of authority.
    """
    authority = [r for r in files if r.category in ("entity", "root")]
    out: list[Finding] = []
    for name, paths in sorted(target_index(authority).items()):
        if len(paths) < 2:
            continue
        rels = sorted(_rel(p, workspace) for p in paths)
        out.append(Finding(
            "error", "name-collisions", rels[0],
            f"[[{name}]] is ambiguous: " + ", ".join(rels) +
            " — every stem and alias must name exactly one file; rename "
            "one (retiring a file whose name its replacement reuses "
            "means renaming at retire time)"))
    return out
```

Register it: in `CHECKS`, add `"name-collisions": check_name_collisions,` after `"reveal-when"`; in `SUITES["checkup"]`, append `"name-collisions"`.

- [ ] **Step 4: Run the review and init suites**

Run: `python3 -m unittest tests.test_review tests.test_init -v`

Expected: PASS. `TestFreshWorkspacePassesTheGate` is the critical one — a fresh workspace's root docs and READMEs have unique stems, so the new check contributes a `name-collisions  (0 finding(s))` block and the summary stays `0 error(s), 0 warning(s)`.

- [ ] **Step 5: Commit**

```bash
git add src/bunnyforge/review.py tests/test_review.py
git commit -m "feat: name-collisions checkup error — ambiguous stems surface at review, not deploy"
```

---

### Task 6: The compendium requirement follows the mirror

Retiring a file must not un-index it: an archived entity file answers to its mirrored section's `compendium_dirs` membership.

**Files:**
- Modify: `src/bunnyforge/review.py:262-281` (`check_compendium`)
- Test: `tests/test_review.py` (class `TestCompendium`, line 288)

**Interfaces:**
- Consumes: `ws.config.archive_dir` (Task 2); `check_compendium` is already in `_NEEDS_WORKSPACE`, so it receives the full `Workspace`.
- Produces: no new names — a behavior change Task 8's doctrine text describes ("update the file's compendium entry to its Archive/ path").

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_review.py`, inside `class TestCompendium`:

```python
    def test_archived_entity_files_still_require_indexing(self):
        # Retiring a file does not un-index it (#62): the compendium entry
        # moves with the file. Membership keys on the mirrored section.
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "Archive/NPCs/old-hag.md": "---\ntype: npc\n---\nx",
                "compendium.md": "# c\n",
            })
            ws = _config.open_workspace(root)
            files = review._common.iter_content_files(ws)
            found = review.check_compendium(files, ws)
            self.assertEqual([f.file for f in found],
                             ["Archive/NPCs/old-hag.md"])

    def test_archived_files_outside_compendium_sections_are_not_required(self):
        # Sessions is not a compendium dir live, so it is not one archived.
        with tempfile.TemporaryDirectory() as d:
            root = make_workspace(Path(d), {
                "Archive/Sessions/session-001.md": "---\ntype: session\n---\nx",
                "compendium.md": "# c\n",
            })
            ws = _config.open_workspace(root)
            files = review._common.iter_content_files(ws)
            self.assertEqual(review.check_compendium(files, ws), [])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_review -k archived -v`

Expected: the first test FAILS (no finding — `Archive` is not in `compendium_dirs`, so the check skips it); the second passes vacuously.

- [ ] **Step 3: Implement**

In `check_compendium`, replace the per-record filter:

```python
    for rec in files:
        if rec.category != "entity":
            continue
        parts = rec.path.relative_to(workspace).parts
        # An archived file answers to its mirrored section's compendium
        # membership: retiring a file does not un-index it (#62).
        section = parts[0]
        if section == ws.config.archive_dir and len(parts) > 2:
            section = parts[1]
        if section not in ws.config.compendium_dirs:
            continue
        if rec.path not in indexed_paths:
            out.append(Finding("warn", "compendium", _rel(rec.path, workspace),
                               "not indexed in compendium.md"))
```

- [ ] **Step 4: Run the review suite, then commit**

Run: `python3 -m unittest tests.test_review -v`

Expected: PASS.

```bash
git add src/bunnyforge/review.py tests/test_review.py
git commit -m "feat: archived entity files keep their compendium obligation via the mirror section"
```

---

### Task 7: Rename the generated output — `_Reviews/`, `_Export/`, gitignore, and every mention

`_Sheets` landed in Task 2 (config default). This task renames the two hardcoded output dirs and updates every literal and prose mention in code, tests, packaged gitignore, and README.

**Files:**
- Modify: `src/bunnyforge/review.py:75, 137, 688` (Reviews → _Reviews)
- Modify: `src/bunnyforge/export_player.py:3-12` (docstring), `:179` (description), `:192` (default dir)
- Modify: `src/bunnyforge/deploy_export.py:3-5` (docstring), `:244` (description), `:269` (help), `:299` (comment), `:301` (default dir)
- Modify: `src/bunnyforge/cli.py:63-64`, `src/bunnyforge/serve_mcp.py:23` (comment), `src/bunnyforge/run_tests.py:27` (comment) and `:171` (note), `src/bunnyforge/build_sheets.py:14` (docstring)
- Modify: `src/bunnyforge/data/root/gitignore` (the generated-output block)
- Modify: `README.md:48-49`
- Test: whatever `grep` finds (Step 1) — expected: `tests/test_review.py` (`TestHtml`), possibly `tests/test_export_player.py`, `tests/test_init.py` (gitignore assertions), `tests/test_run_tests.py`, `tests/test_scripts.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: the literal strings `"_Reviews"` and `"_Export"` where `"Reviews"`/`"Export"` were defaults. Task 9's docs and Task 8's doctrine hunks state the new names.

- [ ] **Step 1: Find every pinned expectation before changing anything**

Run:

```bash
grep -rn '"Reviews"\|Reviews/' src/bunnyforge/ tests/ README.md | grep -v _Reviews
grep -rn '"Export"\|Export/' src/bunnyforge/ tests/ README.md | grep -v "_Export\|ExportResult\|export_player\|deploy_export\|export-player\|deploy-export\|run_export\|make_export\|export ="
```

Record the hit list. Test files that pass explicit paths (e.g. `tests/test_deploy_export.py`'s `make_export(d / "Export", ...)` with `--export-dir`) need NO change — they exercise the override, not the default. Tests that assert the *default* location must move to the new names.

- [ ] **Step 2: Update the default-location tests to the new names (failing first)**

In the files found in Step 1, change expectations of the default output locations: `Reviews/<suite>.html` → `_Reviews/<suite>.html`, default export dir `Export` → `_Export`, and any gitignore-content assertion in `tests/test_init.py` to the new block below. Run the affected suites and confirm they now FAIL against the unchanged code.

- [ ] **Step 3: Implement the renames**

- `review.py:137`: `out_dir = workspace / "_Reviews"`; docstring line 75 `Write _Reviews/<suite>.html under workspace...`; argparse help line 688 `"Also write an HTML report to _Reviews/<suite>.html"`.
- `export_player.py:192`: `result, log = run_export(ws, ws.root / "_Export")`; description line 179 and the module docstring lines 3-12: `Export/` → `_Export/`.
- `deploy_export.py:301`: `... else ws.root / "_Export")`; docstring lines 3-5, description 244, `--export-dir` help 269, comment 299: `Export/` → `_Export/`.
- `cli.py:63-64`: the two command descriptions: `Export/` → `_Export/`.
- `serve_mcp.py:23`: comment `touches Export/ or the wiki` → `touches _Export/ or the wiki`.
- `run_tests.py:27` comment and `:171` note: `Export/, Reviews/ and _Ignore/` → `_Export/, _Reviews/, _Sheets/ and _Ignore/` (sheets are git-ignored generated output too — see the gitignore below).
- `build_sheets.py:14`: `Output: _Sheets/session-NNN/<name>.html` (the code itself reads `config.sheets_dir`, changed in Task 2).
- `data/root/gitignore`: replace the generated-output block:

```
# Generated by the tools, not campaign content — rebuildable at any time.
_Sheets/
_Reviews/
_Export/
```

- `README.md:48-49`: the two table rows: `Export/` → `_Export/`.

- [ ] **Step 4: Run the whole suite**

Run: `python3 -m unittest discover -s tests -t . -v`

Expected: PASS, including everything Step 2 turned red.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: generated output carries the marker — _Sheets/, _Reviews/, _Export/"
```

---

### Task 8: Doctrine — state the meaning once, rename in place

Seven surgical hunks in `src/bunnyforge/data/doctrine/AGENTS.md`. Line numbers are pre-edit; apply top-to-bottom so each hunk's numbers stay valid until used, and touch nothing else in the file.

**Files:**
- Modify: `src/bunnyforge/data/doctrine/AGENTS.md` (hunks below)
- Test: `tests/test_init.py`, class `TestPackagedDoctrineIsPortable` (line 51)

**Interfaces:**
- Consumes: behavior from Tasks 1-7 (the text describes it). `init.packaged_bytes("doctrine/AGENTS.md")` on the test side.
- Produces: the literal heading `## What a leading underscore means`; zero occurrences of `_Archive` anywhere in the file.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_init.py`, inside `class TestPackagedDoctrineIsPortable`:

```python
    def test_the_underscore_convention_is_stated_once(self):
        # #62: one statement of the meaning -- _ means not canon, both
        # directions, with the repo-infra exemption and the default read
        # contract -- and the archive rename is total: nothing in the
        # packaged doctrine may still say _Archive.
        doctrine = init.packaged_bytes("doctrine/AGENTS.md").decode("utf-8")
        self.assertIn("## What a leading underscore means", doctrine)
        section = doctrine.split("## What a leading underscore means", 1)[1]
        section = section.split("\n## ", 1)[0]
        for needle in ("not canon", "`docs/`", "`_Ignore/`",
                       "`_ExtractInbound/`", "`_AgentDrafts/`",
                       "`Archive/`", "[[campaign-doctrine]]"):
            with self.subTest(needle=needle):
                self.assertIn(needle, section)
        self.assertNotIn("_Archive", doctrine)
        self.assertNotIn("`Sheets/`", doctrine)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest tests.test_init -k underscore_convention -v`

Expected: FAIL — heading not found.

- [ ] **Step 3: Apply the seven hunks**

**Hunk 1 — lines 10-14** (the intro paragraph beginning `Two directories are outside the canon,` and ending `unless I name a file in it and ask.`) becomes:

```markdown
## What a leading underscore means

A `_`-prefixed name is **not canon** — that is the whole rule, and it runs
both ways: everything that is not canon carries the marker, except the
repo-infrastructure directories (`docs/`, `scripts/`, `tests/`), which keep
their ecosystem names. `.`-prefixed names are hidden machine files, invisible
everywhere. `Archive/` carries no underscore for the same reason: it is
canon — the record of what happened — see the retirement rule under **File
conventions**.

The marker says nothing about whether you may *read* a directory; each one
carries its own contract, stated where it is introduced. `_Ignore/` holds raw
material, plus retired work that set no precedent: **never read it** unless I
name a file in it and ask. `_Templates/` is the reference for front-matter
shape. `_ExtractInbound/` is read only when I ask (its own section below).
`_AgentDrafts/` is read freely. A `_`-directory this file does not name
defaults to **never read unless I ask**; campaign-specific exceptions belong
in `[[campaign-doctrine]]`.
```

**Hunk 2 — line 125**: `` (`Export/`, `Reviews/`, `Sheets/`) — `.gitignore` already excludes it. `` becomes `` (`_Export/`, `_Reviews/`, `_Sheets/`) — `.gitignore` already excludes it. ``

**Hunk 3 — line 162**: `file to `Export/` (gitignored, generated):` becomes `file to `_Export/` (gitignored, generated):`

**Hunk 4 — lines 187-190** (the `Do not present `_Archive/` material as current...` bullet) becomes:

```markdown
- Do not present `Archive/` material as current. It is canon, read like any
  canon — what was decided, what was tried, and why the thing that replaced
  it looks the way it does is exactly what it is for — but it is superseded
  by definition, so where it disagrees with a live file, the live file wins.
```

**Hunk 5 — line 263**: `` `Sheets/` is generated by `bunnyforge build-sheets` and must not be hand-edited `` becomes `` `_Sheets/` is generated by `bunnyforge build-sheets` and must not be hand-edited ``

**Hunk 6 — line 320**: `- Generated sheets in `Sheets/` are not canon and are not edited by hand.` becomes `- Generated sheets in `_Sheets/` are not canon and are not edited by hand.`

**Hunk 7 — lines 321-332** (the `Nothing is deleted.` bullet) becomes:

```markdown
- Nothing is deleted. Superseded material that was **used** moves to
  `Archive/` with `status: retired`, mirroring its section
  (`Archive/NPCs/old-hag.md`): it happened, so it is part of the record, and
  a retired thing still explains why what replaced it looks the way it does.
  That is why the archive is canon rather than machinery. Two rules when
  retiring: if the name will be reused by a replacement, rename the retiring
  file first — every stem and alias must name exactly one file, and
  `review checkup` enforces that — and update the file's `[[compendium]]`
  entry to its `Archive/` path. Material that never got used, or that was
  used once and can never be relevant again, sets no precedent — an
  abandoned draft of something later rebuilt from scratch, or a one-time
  instruction that did its job and whose steps the result has since
  contradicted. That moves to `_Ignore/` instead, which is never read at
  all. Note what the second move costs: `_Ignore/` is git-ignored, so the
  file leaves version control. It stays on disk, and its history up to the
  move remains, but a fresh clone will not contain it — which is the
  intended end state for material that constrains nothing.
```

Then verify the rename is total: `grep -n "_Archive\|\`Sheets/\|\`Reviews/\|\`Export/" src/bunnyforge/data/doctrine/AGENTS.md` must return nothing.

- [ ] **Step 4: Run the init suite and the portability check**

Run: `python3 -m unittest tests.test_init -v && python3 tests/check_portability.py`

Expected: PASS and clean. The wikilink test (`test_agents_md_wikilinks_resolve_with_only_root_docs`) matters: the new section's `[[campaign-doctrine]]` must resolve — it does, `campaign-doctrine.md` has been a root doc since #64. If the portability checker flags a term, the new wording is the bug, not the checker.

- [ ] **Step 5: Run the whole suite, then commit**

Run: `python3 -m unittest discover -s tests -t . -v`

Expected: PASS.

```bash
git add src/bunnyforge/data/doctrine/AGENTS.md tests/test_init.py
git commit -m "feat: AGENTS.md states the not-canon underscore rule, and the archive rename lands in doctrine"
```

---

### Task 9: Docs — serve-mcp, README already done, and the migration recipe

**Files:**
- Modify: `docs/serve-mcp.md:122-124`, `:140-141`, `:164`
- Modify: `docs/adopting-doctrine.md` (append a migration section)

**Interfaces:** none programmatic.

- [ ] **Step 1: Update serve-mcp.md**

At lines 122-124, replace:

```markdown
work and merges rather than re-writing; a `_`-prefixed subdirectory
(say, `_AgentDrafts/_Rejected/`, if you use rejection-by-moving) is
never listed or read, so rejected material stays rejected.
```

with:

```markdown
work and merges rather than re-writing; a `_`- or `.`-prefixed
subdirectory (say, `_AgentDrafts/_Rejected/`, if you use
rejection-by-moving) is never listed or read, so rejected material
stays rejected.
```

At lines 140-141, replace:

```markdown
`_ExtractInbound/_Done/` and any other `_`-prefixed area are invisible
to both tools, exactly like `_Ignore/`.
```

with:

```markdown
`_ExtractInbound/_Done/` and any other `_`- or `.`-prefixed area are
invisible to both tools, exactly like `_Ignore/`.
```

At line 164, change `Export/` to `_Export/`.

- [ ] **Step 2: Append the migration section to docs/adopting-doctrine.md**

```markdown
## Migrating to the not-canon underscore (#62)

Workspaces scaffolded before the underscore convention was defined carry
the old names. Five steps, once, from the workspace root:

1. **Make the archive canon.** `git mv _Archive Archive`, then restructure
   its contents to mirror sections (`Archive/NPCs/...`) where they do not
   already.
2. **Mark the generated output.** For each of `Sheets`, `Reviews`, `Export`
   that exists: `git mv Sheets _Sheets` (and likewise) — or simply delete
   them; all three are rebuilt by the tools.
3. **Update `campaign.toml`** if it sets these keys explicitly: `sheets_dir`
   becomes `"_Sheets"`, and `exclude_dirs` drops `_Ignore`, `_Archive`,
   `_Templates`, `Sheets`, and `Reviews` (the prefix rule owns them now),
   keeping `docs`, `scripts`, `tests`, and any campaign-specific entries.
4. **Take the packaged `AGENTS.md` and `.gitignore` whole** (see "Adopting
   a new version" above).
5. **Run `bunnyforge review checkup`.** Newly walked archive files may
   produce front-matter findings or name collisions with their
   replacements; fix or accept each — that review is the archive joining
   canon.

A workspace that skips this migration still works: old `_Archive/` is
skipped by the prefix rule exactly as `exclude_dirs` skipped it before, and
the old output directories were never walked. The archive simply stays
invisible until step 1 runs.
```

- [ ] **Step 3: Commit**

```bash
git add docs/serve-mcp.md docs/adopting-doctrine.md
git commit -m "docs: dot-prefix rule in serve-mcp, and the #62 migration recipe"
```

---

### Task 10: Verify in a clean checkout, then open the PR

**Files:** none modified.

- [ ] **Step 1: Verify where the artifact will live, not where you worked**

```bash
git worktree add /tmp/bf62-verify HEAD
cd /tmp/bf62-verify
python3 -m venv .venv && .venv/bin/pip install -e '.[mcp]'
.venv/bin/python -c "import bunnyforge; print(bunnyforge.__file__)"
.venv/bin/python -m unittest discover -s tests -t . -v
.venv/bin/python tests/check_portability.py
```

Expected: the `__file__` path is inside `/tmp/bf62-verify`; 0 failures from both. Record the actual output; do not paraphrase.

- [ ] **Step 2: Run the init-then-checkup gate as a real user would**

```bash
cd /tmp
/tmp/bf62-verify/.venv/bin/python -m bunnyforge.init /tmp/bf62-fresh --name "Verify"
/tmp/bf62-verify/.venv/bin/python -m bunnyforge.review checkup --workspace /tmp/bf62-fresh
```

Expected: `Summary: 0 error(s), 0 warning(s).` with `name-collisions  (0 finding(s))` in the report.

- [ ] **Step 3: Prove the new behavior end-to-end, once each**

```bash
mkdir -p /tmp/bf62-fresh/Archive/NPCs /tmp/bf62-fresh/NPCs
printf -- '---\ntype: npc\ncanon: canon\nvisibility: gm-only\nsummary: Probe.\nstatus: retired\n---\nx\n' > /tmp/bf62-fresh/Archive/NPCs/probe.md
printf -- '---\ntype: npc\ncanon: canon\nvisibility: gm-only\nsummary: Probe.\n---\nx\n' > /tmp/bf62-fresh/NPCs/probe.md
/tmp/bf62-verify/.venv/bin/python -m bunnyforge.review checkup --workspace /tmp/bf62-fresh
/tmp/bf62-verify/.venv/bin/python -m bunnyforge.review checkup --workspace /tmp/bf62-fresh --html
ls /tmp/bf62-fresh/_Reviews/
```

Expected: a `name-collisions` **error** naming both `probe` paths (plus compendium warnings for the unindexed probes — fine); the HTML report lands in `_Reviews/checkup.html`.

- [ ] **Step 4: Clean up**

```bash
rm -rf /tmp/bf62-fresh
git worktree remove /tmp/bf62-verify --force
```

- [ ] **Step 5: Open the PR**

Use the `dcltdw:opening-a-pr` skill. The PR body carries: the decision (underscore means not-canon, biconditional) and the one-paragraph argument; the archive-lockout contradiction it fixes; the collision-check scope amendment (authority files only — the briefs pairing is doctrine-mandated); the un-migrated-workspace safety property; and pointers to the spec (in this branch), issue #62 (`Closes #62`), and ticket #66 (scoped retrieval, deliberately not built here). Wait for four green checks and review approval; do not merge unprompted.

---

## Out of scope — deliberately

Recorded so an executor does not helpfully build them:

- **No `scope` parameter and no `archived:` field on search/list results.** That is ticket #66. #62 ships uniform retrieval; archive hits are recognizable by their `Archive/` path prefix.
- **No prefix-rule warning check.** The deleted first plan had checkup *warn* about machinery-named content files; under this design they are sanctioned not-canon and are simply skipped. Do not resurrect the warning.
- **`init` does not scaffold `Archive/`.** It appears when the GM first retires something.
- **No changes to the inbound/drafts read contracts or their doors.** They already fit the meaning.
- **No `save_draft` into `Archive`.** New material never lands retired; `_draftable_sections` excludes the archive (Task 3) and that is the whole feature.
- **Issue #65** (packaged-data campaign-term guard): adjacent, filed, separate.
- **The release and the Anjeong migration.** One release carries #64 + #62 afterwards; Anjeong (pinned 0.3.1) migrates after that release using Task 9's recipe.
