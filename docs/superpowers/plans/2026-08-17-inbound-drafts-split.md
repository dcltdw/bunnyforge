# Inbound/Drafts Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split serve-mcp's conflated staging directory into `_AgentDrafts/` (agent output with a full draft lifecycle: save, propose, update, list, read, promote) and `_ExtractInbound/` (the GM's inbound queue, read-only under an only-when-asked contract).

**Architecture:** All behaviour lands on `WorkspaceStore` (`src/bunnyforge/_store.py`) — it is the swap seam for a future hosted backend (issue #43), so the MCP layer (`serve_mcp.py`) only registers thin tools over store methods. Config (`_config.py`) renames `staging_dir` → `inbound_dir`, adds `drafts_dir`, and auto-excludes both from canon walks at load time. Revision provenance lives in one JSON manifest inside the drafts directory.

**Tech Stack:** Python 3.11+, stdlib only in `_store.py`/`_config.py`. The `mcp` SDK is an optional extra imported only inside function bodies of `serve_mcp.py`. Tests are stdlib `unittest`.

**Spec:** `docs/superpowers/specs/2026-08-17-inbound-drafts-split-design.md` — read it before starting; every task below argues from it.

## Global Constraints

- Python 3.11+; `_store.py` and `_config.py` import nothing outside the stdlib and the `bunnyforge` package.
- The `mcp` SDK is imported only inside function bodies in `serve_mcp.py`.
- The words "staging"/"staged" must not survive in any tool name, config key, store method, docstring, error message, or in `docs/serve-mcp.md`. (`deploy_export.py`'s wiki-staging vocabulary is a different concept — leave it alone.)
- TDD: every step-pair is failing-test-first. Run tests as `PYTHONPATH=src python3 -m unittest tests.test_store -v` (substitute the module).
- The `mcp` extra is NOT installed in this environment: `test_serve_mcp.py` classes guarded by `HAVE_MCP` **skip locally** and run in CI. Write them anyway; verify they at least import (`PYTHONPATH=src python3 -m unittest tests.test_serve_mcp -v` must end `OK (skipped=…)`).
- Baseline before Task 1: `PYTHONPATH=src python3 -m unittest discover -s tests` → `Ran 833 tests … OK (skipped=52)`. After every task the suite must be green (test counts will grow; skips grow with new SDK-gated tests).
- Work on branch `feat/inbound-drafts-split` (already created). Commit after each task with a `Co-Authored-By: Claude <model> <noreply@anthropic.com>` trailer naming the executing model.
- Error-message style: every `StoreError`/`ConfigError` names the valid next move (an alternative tool, the key to rename), never merely "no".

---

### Task 1: Config — `inbound_dir` / `drafts_dir` split

**Files:**
- Modify: `src/bunnyforge/_config.py` (Config namedtuple ~line 34; `_DEFAULTS` ~line 111; `load()` ~line 319)
- Modify: `src/bunnyforge/data/campaign.toml.in` (commented `[workspace]` block)
- Modify: `src/bunnyforge/_store.py` (only the two `config.staging_dir` attribute reads, lines ~207 and ~244 — method names change in Task 2, not here)
- Modify: `tests/test_config.py` (replace the three `staging_dir` tests at lines 249–267)
- Modify: `tests/test_store.py` (two `staging_dir = "_Inbox"` TOML strings, lines ~259 and ~324 → `inbound_dir = "_Inbox"`)

**Interfaces:**
- Consumes: nothing new.
- Produces: `Config.inbound_dir: str` (default `"_ExtractInbound"`), `Config.drafts_dir: str` (default `"_AgentDrafts"`); `Config.staging_dir` is gone. `Config.exclude_dirs` always contains both values. Every later task relies on these exact field names.

- [ ] **Step 1: Write the failing tests** — in `tests/test_config.py`, delete `test_staging_dir_defaults_to_extract_inbound`, `test_staging_dir_honours_explicit_override`, `test_staging_dir_wrong_type_raises` (lines 249–267) and put this in their place:

```python
    def test_inbound_dir_defaults_to_extract_inbound(self):
        # The GM's inbound queue: material authored elsewhere, awaiting
        # extraction. Excluded from every walk unconditionally (below).
        cfg = _config.load(self._ws(MINIMAL))
        self.assertEqual(cfg.inbound_dir, "_ExtractInbound")
        self.assertIn(cfg.inbound_dir, cfg.exclude_dirs)

    def test_drafts_dir_defaults_to_agent_drafts(self):
        cfg = _config.load(self._ws(MINIMAL))
        self.assertEqual(cfg.drafts_dir, "_AgentDrafts")
        self.assertIn(cfg.drafts_dir, cfg.exclude_dirs)

    def test_special_dirs_are_excluded_even_when_exclude_dirs_omits_them(self):
        # No configuration may un-exclude either special directory: a
        # workspace that customised exclude_dirs without them would silently
        # serve agent drafts as canon.
        cfg = _config.load(self._ws(
            MINIMAL + '\n[workspace]\nexclude_dirs = ["docs"]\n'))
        self.assertIn("_ExtractInbound", cfg.exclude_dirs)
        self.assertIn("_AgentDrafts", cfg.exclude_dirs)

    def test_overridden_special_dirs_are_auto_excluded_too(self):
        cfg = _config.load(self._ws(
            MINIMAL +
            '\n[workspace]\ninbound_dir = "_Inbox"\ndrafts_dir = "_Outbox"\n'))
        self.assertEqual(cfg.inbound_dir, "_Inbox")
        self.assertEqual(cfg.drafts_dir, "_Outbox")
        self.assertIn("_Inbox", cfg.exclude_dirs)
        self.assertIn("_Outbox", cfg.exclude_dirs)

    def test_staging_dir_key_is_refused_naming_the_rename(self):
        # load() ignores unknown keys, so without this check an old
        # staging_dir key would be silently dropped — a behaviour change
        # with no error.
        with self.assertRaises(_config.ConfigError) as ctx:
            _config.load(self._ws(
                MINIMAL + '\n[workspace]\nstaging_dir = "_Inbox"\n'))
        self.assertIn("inbound_dir", str(ctx.exception))

    def test_inbound_and_drafts_dir_wrong_type_raises(self):
        for key in ("inbound_dir", "drafts_dir"):
            with self.assertRaises(_config.ConfigError) as ctx:
                _config.load(self._ws(
                    MINIMAL + f'\n[workspace]\n{key} = ["x"]\n'))
            self.assertIn(key, str(ctx.exception))

    def test_special_dir_naming_a_section_raises(self):
        # drafts_dir = "Ideas" would auto-exclude a canon section from
        # every walker — silently, since auto-exclusion happens at load.
        for key, section in (("drafts_dir", "Ideas"), ("inbound_dir", "Briefs")):
            with self.assertRaises(_config.ConfigError) as ctx:
                _config.load(self._ws(
                    MINIMAL + f'\n[workspace]\n{key} = "{section}"\n'))
            self.assertIn(section, str(ctx.exception))

    def test_inbound_and_drafts_dir_must_differ(self):
        # Identical values would recreate the conflation this split kills.
        with self.assertRaises(_config.ConfigError) as ctx:
            _config.load(self._ws(
                MINIMAL +
                '\n[workspace]\ninbound_dir = "_X"\ndrafts_dir = "_X"\n'))
        self.assertIn("_X", str(ctx.exception))
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=src python3 -m unittest tests.test_config -v`
Expected: the new tests FAIL/ERROR (`AttributeError: 'Config' object has no attribute 'inbound_dir'`, missing ConfigError, etc.).

- [ ] **Step 3: Implement in `_config.py`**

In the `Config` namedtuple field string, replace `type_dirs staging_dir wiki_url` with `type_dirs inbound_dir drafts_dir wiki_url` (the `defaults=` list still maps onto the last five fields — do not touch it).

In `_DEFAULTS`: remove `"_ExtractInbound"` from the `exclude_dirs` list; replace the `staging_dir` entry and its comment with:

```python
    # The GM's inbound queue (material authored elsewhere, awaiting
    # extraction) and the agents' drafts directory (output awaiting GM
    # review). Both are appended to exclude_dirs at load time, so neither
    # appears in the default list above — a second copy would be a second
    # thing to drift, and no configuration may un-exclude them.
    "inbound_dir": "_ExtractInbound",
    "drafts_dir": "_AgentDrafts",
```

In `load()`, after the `ws` table is validated (near the `entity_dirs` block), add:

```python
    if "staging_dir" in ws:
        raise ConfigError(
            f"{path}: workspace.staging_dir was renamed — use inbound_dir "
            "for the GM's inbound queue. Agent drafts now live separately "
            "under drafts_dir (default _AgentDrafts).")

    inbound_dir = _str(ws, "inbound_dir")
    drafts_dir = _str(ws, "drafts_dir")
    if inbound_dir == drafts_dir:
        raise ConfigError(
            f"{path}: workspace.inbound_dir and workspace.drafts_dir are "
            f"both {inbound_dir!r} — they must name different directories; "
            "one is the GM's inbound queue, the other the agents' drafts")
    for key, val in (("inbound_dir", inbound_dir), ("drafts_dir", drafts_dir)):
        if val in entity_dirs or val in inherit_dirs:
            raise ConfigError(
                f"{path}: workspace.{key} = {val!r} names a content section "
                "— it would be excluded from every walk; pick a directory "
                "of its own (convention: a _-prefixed name)")
```

(Place this after `entity_dirs`/`inherit_dirs` are computed.) Then in the `return Config(...)` call: replace `staging_dir=_str(ws, "staging_dir"),` with `inbound_dir=inbound_dir, drafts_dir=drafts_dir,` and change the `exclude_dirs=` line to:

```python
        exclude_dirs=(frozenset(_str_tuple(ws, "exclude_dirs"))
                      | MANDATORY_EXCLUDES | {inbound_dir, drafts_dir}),
```

- [ ] **Step 4: Update the other reference sites**

`src/bunnyforge/_store.py`: change `self.ws.config.staging_dir` → `self.ws.config.inbound_dir` in `_staging()` (~line 207) and in `read_staged`'s error message (~line 244). Nothing else in this file yet.

`src/bunnyforge/data/campaign.toml.in`: in the commented `[workspace]` block, remove `"_ExtractInbound",` from the `exclude_dirs` example and append below `perceptions_dir`:

```
# inbound_dir     = "_ExtractInbound"  # the GM's inbound queue; always
#                                      # excluded from canon, listed or not
# drafts_dir      = "_AgentDrafts"     # agent output awaiting review; always
#                                      # excluded from canon, listed or not
```

`tests/test_store.py`: change both `'\n[workspace]\nstaging_dir = "_Inbox"\n'` strings (lines ~259, ~324) to `'\n[workspace]\ninbound_dir = "_Inbox"\n'`.

- [ ] **Step 5: Run the full suite**

Run: `PYTHONPATH=src python3 -m unittest discover -s tests`
Expected: OK, zero failures (853+ tests; skips unchanged).

- [ ] **Step 6: Commit**

```bash
git add src/bunnyforge/_config.py src/bunnyforge/_store.py src/bunnyforge/data/campaign.toml.in tests/test_config.py tests/test_store.py
git commit -m "feat: split staging_dir into inbound_dir and drafts_dir in config"
```

---

### Task 2: Store + tools — the drafts family

**Files:**
- Modify: `src/bunnyforge/_store.py` (module docstring; `_DRAFT_NAME_RE` area; replace the `-- staging --` and write-side sections wholesale)
- Modify: `src/bunnyforge/serve_mcp.py` (tool registrations, lines ~123–153)
- Modify: `tests/test_store.py` (replace `TestStageDraft`, `TestStageRevision`, `TestStagingReads`)
- Modify: `tests/test_serve_mcp.py` (replace the staging tool tests, lines ~110–167)

**Interfaces:**
- Consumes: `Config.drafts_dir`, `Config.perceptions_dir` (Task 1), `_common.split_front_matter`.
- Produces (later tasks call these exact signatures):
  - `WorkspaceStore.save_draft(section: str, name: str, content: str, subdir: str | None = None) -> str`
  - `WorkspaceStore.propose_revision(path: str, content: str) -> str`
  - `WorkspaceStore.list_drafts() -> list[dict]` — rows `{path, kind: "new"|"revision", title, summary}` plus `stale: bool|None` on revision rows only
  - `WorkspaceStore.read_draft(path: str) -> str`
  - Private helpers Tasks 3/6 reuse: `_drafts() -> Path`, `_draft_path(path: str) -> Path`, `_load_bases() -> dict[str, str]`, `_save_bases(dict) -> None`, `_set_base(shadow_rel: str, canon: Path) -> None`, module constant `BASES_NAME = ".proposal-bases.json"`.
- Removes: `stage_draft`, `stage_revision`, `list_staging`, `read_staged` (store); `list_staged`, `read_staged` (tools).

- [ ] **Step 1: Write the failing store tests** — in `tests/test_store.py`, add `import hashlib`, `import json` to the imports, then delete classes `TestStageDraft`, `TestStageRevision`, `TestStagingReads` and write in their place:

```python
class TestSaveDraft(StoreCase):
    def test_writes_into_drafts_and_slugs_the_name(self):
        ws = self.make_ws()
        store = _store.WorkspaceStore(ws)
        rel = store.save_draft("NPCs", "Old Man Cho", "---\ntitle: Cho\n---\n")
        self.assertEqual(rel, "_AgentDrafts/NPCs/old-man-cho.md")
        self.assertTrue((ws.root / rel).is_file())

    def test_slug_drops_apostrophes_and_collapses_separators(self):
        store = _store.WorkspaceStore(self.make_ws())
        rel = store.save_draft("NPCs", "Mara's  Old_Friend", "x")
        self.assertEqual(rel, "_AgentDrafts/NPCs/maras-old-friend.md")

    def test_subdir_nests_one_level_and_is_slugged(self):
        # Briefs live at Briefs/session-NNN/<name>.md; a draft brief must be
        # able to take its canonical shape, or every promotion re-nests by
        # hand.
        ws = self.make_ws()
        rel = _store.WorkspaceStore(ws).save_draft(
            "Briefs", "Kim Ha-eun", "x", subdir="Session 15")
        self.assertEqual(rel, "_AgentDrafts/Briefs/session-15/kim-ha-eun.md")

    def test_existing_draft_refusal_names_update_draft(self):
        store = _store.WorkspaceStore(self.make_ws())
        store.save_draft("NPCs", "Cho", "x")
        with self.assertRaises(_store.StoreError) as ctx:
            store.save_draft("NPCs", "Cho", "y")
        self.assertIn("update_draft", str(ctx.exception))

    def test_canonical_collision_refusal_names_propose_revision(self):
        # A new draft shadowing an existing canonical file would be
        # misreported as a revision and reviewed as a diff against the
        # wrong entity.
        store = _store.WorkspaceStore(self.make_ws())
        with self.assertRaises(_store.StoreError) as ctx:
            store.save_draft("NPCs", "Kim Ha-eun", "x")  # slug: kim-ha-eun
        self.assertIn("propose_revision", str(ctx.exception))

    def test_refuses_unknown_section_and_bad_names(self):
        store = _store.WorkspaceStore(self.make_ws())
        with self.assertRaises(_store.StoreError):
            store.save_draft("Nope", "Cho", "x")
        for bad in ("../escape", "a/b", ".hidden", "_underscore"):
            with self.assertRaises(_store.StoreError):
                store.save_draft("NPCs", bad, "x")
            with self.assertRaises(_store.StoreError):
                store.save_draft("NPCs", "Cho", "x", subdir=bad)

    def test_perceptions_are_not_draftable(self):
        # The perception record is by contract never agent-authored.
        store = _store.WorkspaceStore(self.make_ws())
        with self.assertRaises(_store.StoreError) as ctx:
            store.save_draft("Perceptions", "Cho", "x")
        listed = str(ctx.exception).split("one of:")[1]
        self.assertNotIn("Perceptions", listed)
        self.assertIn("Briefs", listed)

    def test_honours_configured_drafts_dir(self):
        ws = self.make_ws('\n[workspace]\ndrafts_dir = "_Outbox"\n')
        rel = _store.WorkspaceStore(ws).save_draft("NPCs", "Cho", "x")
        self.assertEqual(rel, "_Outbox/NPCs/cho.md")


class TestProposeRevision(StoreCase):
    def test_shadow_mirrors_the_canonical_path_and_records_a_base(self):
        ws = self.make_ws()
        store = _store.WorkspaceStore(ws)
        rel = store.propose_revision("NPCs/kim-ha-eun.md", "new text")
        self.assertEqual(rel, "_AgentDrafts/NPCs/kim-ha-eun.md")
        self.assertEqual((ws.root / rel).read_text(encoding="utf-8"),
                         "new text")
        bases = json.loads(
            (ws.root / "_AgentDrafts" / ".proposal-bases.json")
            .read_text(encoding="utf-8"))
        canon_hash = hashlib.sha256(
            (ws.root / "NPCs/kim-ha-eun.md").read_bytes()).hexdigest()
        self.assertEqual(bases[rel], canon_hash)

    def test_second_proposal_is_refused_and_the_first_survives(self):
        # The old latest-wins rule silently destroyed pending proposals —
        # routine, not rare: the end-of-session ritual proposes front-burner
        # updates every session.
        ws = self.make_ws()
        store = _store.WorkspaceStore(ws)
        store.propose_revision("NPCs/kim-ha-eun.md", "first")
        with self.assertRaises(_store.StoreError) as ctx:
            store.propose_revision("NPCs/kim-ha-eun.md", "second")
        self.assertIn("update_draft", str(ctx.exception))
        self.assertEqual(
            (ws.root / "_AgentDrafts/NPCs/kim-ha-eun.md")
            .read_text(encoding="utf-8"), "first")

    def test_requires_an_existing_target_naming_save_draft(self):
        store = _store.WorkspaceStore(self.make_ws())
        with self.assertRaises(_store.StoreError) as ctx:
            store.propose_revision("NPCs/nobody.md", "x")
        self.assertIn("save_draft", str(ctx.exception))

    def test_refuses_escapes(self):
        store = _store.WorkspaceStore(self.make_ws())
        with self.assertRaises(_store.StoreError):
            store.propose_revision("../outside.md", "x")


class TestDraftReads(StoreCase):
    """The agents' own outbox: freely readable, so a draft written last
    session is revisited rather than re-invented."""

    def test_listing_reports_kind_title_and_summary(self):
        ws = self.make_ws()
        store = _store.WorkspaceStore(ws)
        store.save_draft("NPCs", "Cho",
                         "---\ntitle: Old Man Cho\n"
                         "summary: A dockside fixer.\n---\nbody\n")
        store.propose_revision("NPCs/kim-ha-eun.md", "y")
        rows = {r["path"]: r for r in store.list_drafts()}
        cho = rows["_AgentDrafts/NPCs/cho.md"]
        self.assertEqual(cho["kind"], "new")
        self.assertEqual(cho["title"], "Old Man Cho")
        self.assertEqual(cho["summary"], "A dockside fixer.")
        self.assertNotIn("stale", cho)          # stale is revision-only
        rev = rows["_AgentDrafts/NPCs/kim-ha-eun.md"]
        self.assertEqual(rev["kind"], "revision")
        self.assertIs(rev["stale"], False)

    def test_title_falls_back_to_the_stem(self):
        store = _store.WorkspaceStore(self.make_ws())
        store.save_draft("NPCs", "Cho", "no front matter\n")
        [row] = store.list_drafts()
        self.assertEqual(row["title"], "cho")
        self.assertEqual(row["summary"], "")

    def test_revision_goes_stale_when_canon_moves(self):
        # A pending shadow must not silently revert the GM's interim edits;
        # stale is how the listing warns, and promote_draft later refuses.
        ws = self.make_ws()
        store = _store.WorkspaceStore(ws)
        store.propose_revision("NPCs/kim-ha-eun.md", "proposal")
        (ws.root / "NPCs/kim-ha-eun.md").write_text("GM edit",
                                                    encoding="utf-8")
        [row] = store.list_drafts()
        self.assertIs(row["stale"], True)

    def test_unrecorded_base_reports_stale_none(self):
        ws = self.make_ws()
        shadow = ws.root / "_AgentDrafts" / "NPCs"
        shadow.mkdir(parents=True)
        (shadow / "kim-ha-eun.md").write_text("hand-made", encoding="utf-8")
        [row] = _store.WorkspaceStore(ws).list_drafts()
        self.assertIsNone(row["stale"])

    def test_corrupt_manifest_reads_as_empty_not_an_error(self):
        # The manifest is a provenance cache, not a lock file.
        ws = self.make_ws()
        store = _store.WorkspaceStore(ws)
        store.propose_revision("NPCs/kim-ha-eun.md", "proposal")
        (ws.root / "_AgentDrafts" / ".proposal-bases.json").write_text(
            "not json", encoding="utf-8")
        [row] = store.list_drafts()
        self.assertIsNone(row["stale"])

    def test_listing_skips_underscore_components(self):
        # _AgentDrafts/_Rejected/ is the GM's rejection signal — never
        # listed, so rejected material cannot be resurrected by resume.
        ws = self.make_ws()
        store = _store.WorkspaceStore(ws)
        store.save_draft("NPCs", "Cho", "x")
        rejected = ws.root / "_AgentDrafts" / "_Rejected"
        rejected.mkdir(parents=True)
        (rejected / "dead.md").write_text("x", encoding="utf-8")
        self.assertEqual([r["path"] for r in store.list_drafts()],
                         ["_AgentDrafts/NPCs/cho.md"])

    def test_nothing_drafted_is_an_empty_list_not_an_error(self):
        store = _store.WorkspaceStore(self.make_ws())
        self.assertEqual(store.list_drafts(), [])

    def test_read_round_trips_a_draft(self):
        store = _store.WorkspaceStore(self.make_ws())
        rel = store.save_draft("NPCs", "Cho", "---\ntitle: Cho\n---\nbody\n")
        self.assertEqual(store.read_draft(rel), "---\ntitle: Cho\n---\nbody\n")

    def test_escape_and_absolute_paths_are_refused(self):
        store = _store.WorkspaceStore(self.make_ws())
        with self.assertRaises(_store.StoreError):
            store.read_draft("_AgentDrafts/../../outside.md")
        with self.assertRaises(_store.StoreError):
            store.read_draft("/etc/hosts")

    def test_a_canonical_path_is_refused_and_points_at_read_entity(self):
        store = _store.WorkspaceStore(self.make_ws())
        with self.assertRaises(_store.StoreError) as ctx:
            store.read_draft("NPCs/kim-ha-eun.md")
        self.assertIn("read_entity", str(ctx.exception))

    def test_an_underscore_component_is_refused(self):
        ws = self.make_ws()
        rejected = ws.root / "_AgentDrafts" / "_Rejected"
        rejected.mkdir(parents=True)
        (rejected / "dead.md").write_text("x", encoding="utf-8")
        with self.assertRaises(_store.StoreError):
            _store.WorkspaceStore(ws).read_draft(
                "_AgentDrafts/_Rejected/dead.md")

    def test_missing_draft_is_refused_pointing_at_the_listing(self):
        store = _store.WorkspaceStore(self.make_ws())
        with self.assertRaises(_store.StoreError) as ctx:
            store.read_draft("_AgentDrafts/NPCs/nobody.md")
        self.assertIn("list_drafts", str(ctx.exception))

    def test_canon_tools_refuse_draft_paths(self):
        # The inverse boundary: _AgentDrafts is auto-excluded, so the
        # canon read door must refuse it exactly as it refuses _Ignore/.
        store = _store.WorkspaceStore(self.make_ws())
        rel = store.save_draft("NPCs", "Cho", "x")
        with self.assertRaises(_store.StoreError):
            store.read_entity(rel)
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=src python3 -m unittest tests.test_store -v`
Expected: new classes FAIL/ERROR (`AttributeError: … no attribute 'save_draft'` etc.); pre-existing classes still pass.

- [ ] **Step 3: Implement in `_store.py`**

Add `import hashlib` and `import json` to the imports. Below `_DRAFT_NAME_RE`, add:

```python
BASES_NAME = ".proposal-bases.json"


def _slug(name: str) -> str:
    """A _DRAFT_NAME_RE-validated name, as a canon-style filename stem:
    lowercase, separators to single hyphens, apostrophes dropped. Canon
    files are kebab-case, and slugs are what let the drafts tree mirror
    canon — which is what lets promotion derive its destination."""
    s = name.lower().replace("'", "")
    s = re.sub(r"[\s_]+", "-", s)
    return re.sub(r"-+", "-", s).strip("-")
```

Replace the entire `# -- staging --` section (the `_staging` helper, `list_staging`, `read_staged`, and their comment block) and the write-side section (`stage_draft`, `stage_revision` — keep `write_entity`) with:

```python
    # -- agent drafts -------------------------------------------------------
    # The agents' outbox: drafts and proposed revisions awaiting GM review.
    # Excluded from the canon reads BY DESIGN (config auto-excludes it), so
    # it has its own labelled doors. _draft_path guards the inverse of
    # _canonical() — inside the drafts directory rather than outside it —
    # so these methods cannot be talked into serving canon. Underscore
    # components are machinery (the workspace's own convention): a draft
    # the GM moves to _Rejected/ is never listed or read again.

    def _drafts(self) -> Path:
        return self.ws.root / self.ws.config.drafts_dir

    def _draftable_sections(self) -> tuple[str, ...]:
        # The perception record is by contract never agent-authored.
        return tuple(s for s in self._sections()
                     if s != self.ws.config.perceptions_dir)

    def _slugged(self, raw: str, label: str) -> str:
        if not _DRAFT_NAME_RE.fullmatch(raw):
            raise StoreError(
                f"bad {label} name {raw!r} — letters, digits, spaces, "
                "- _ ' only, starting with a letter or digit")
        return _slug(raw)

    def _draft_path(self, path: str) -> Path:
        root = self.ws.root
        drafts = self._drafts()
        p = (root / path).resolve()
        if not p.is_relative_to(root):
            raise StoreError(f"path escapes the workspace: {path}")
        if not p.is_relative_to(drafts):
            raise StoreError(
                f"not a draft path: {path} — this tool serves "
                f"{self.ws.config.drafts_dir}/ only; canonical files are "
                "read with read_entity")
        if any(part.startswith("_")
               for part in p.relative_to(drafts).parts):
            raise StoreError(
                f"{path} is in a _-prefixed area of the drafts directory "
                "(the GM's machinery, e.g. _Rejected/) and is never served")
        if p.suffix != ".md":
            raise StoreError(
                f"not a draft markdown file: {path} — drafts are .md only")
        return p

    # The base manifest: workspace-relative shadow path -> SHA-256 of the
    # canonical file at proposal time. A provenance cache, not a lock file:
    # missing or unparseable reads as empty, and every save prunes entries
    # whose shadow is gone.

    def _bases_file(self) -> Path:
        return self._drafts() / BASES_NAME

    def _load_bases(self) -> dict[str, str]:
        try:
            raw = json.loads(self._bases_file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return {k: v for k, v in raw.items()
                if isinstance(k, str) and isinstance(v, str)}

    def _save_bases(self, bases: dict[str, str]) -> None:
        live = {k: v for k, v in bases.items()
                if (self.ws.root / k).is_file()}
        f = self._bases_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(live, indent=2, sort_keys=True) + "\n",
                     encoding="utf-8")

    def _set_base(self, shadow_rel: str, canon: Path) -> None:
        bases = self._load_bases()
        bases[shadow_rel] = hashlib.sha256(canon.read_bytes()).hexdigest()
        self._save_bases(bases)

    def save_draft(self, section: str, name: str, content: str,
                   subdir: str | None = None) -> str:
        if section not in self._draftable_sections():
            raise StoreError(
                f"unknown or undraftable section {section!r} — one of: "
                + ", ".join(self._draftable_sections()))
        rel = Path(section)
        if subdir is not None:
            rel = rel / self._slugged(subdir, "subdir")
        rel = rel / f"{self._slugged(name, 'draft')}.md"
        if (self.ws.root / rel).is_file():
            raise StoreError(
                f"{rel.as_posix()} already exists in canon — use "
                "propose_revision to suggest changes to it, or pick "
                "another name")
        dest = self._drafts() / rel
        if dest.exists():
            drel = dest.relative_to(self.ws.root).as_posix()
            raise StoreError(
                f"{drel} already exists — read_draft it and revise with "
                "update_draft, or pick another name")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        return dest.relative_to(self.ws.root).as_posix()

    def propose_revision(self, path: str, content: str) -> str:
        target = self._canonical(path)
        if not target.is_file() or target.suffix != ".md":
            raise StoreError(
                f"no such content file: {path} — propose_revision proposes "
                "changes to an existing file; use save_draft for new "
                "content")
        dest = self._drafts() / target.relative_to(self.ws.root)
        rel = dest.relative_to(self.ws.root).as_posix()
        if dest.exists():
            raise StoreError(
                f"a pending proposal already exists at {rel} — read_draft "
                "it, merge your changes into it, then update_draft")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        self._set_base(rel, target)
        return rel

    def list_drafts(self) -> list[dict]:
        """Every pending draft: path, kind ("new" content or a "revision"
        of an existing file), title and summary from front matter, and —
        for revisions — whether canon changed since it was proposed.
        Sorted, so two calls agree."""
        drafts = self._drafts()
        bases = self._load_bases()
        out = []
        for p in sorted(drafts.rglob("*.md")):
            if not p.is_file():
                continue
            inner = p.relative_to(drafts)
            if any(part.startswith("_") for part in inner.parts):
                continue
            rel = p.relative_to(self.ws.root).as_posix()
            fm, _body = _common.split_front_matter(
                p.read_text(encoding="utf-8"))
            mirrored = self.ws.root / inner
            row = {"path": rel,
                   "kind": "revision" if mirrored.is_file() else "new",
                   "title": fm.get("title") or p.stem,
                   "summary": fm.get("summary", "")}
            if row["kind"] == "revision":
                base = bases.get(rel)
                row["stale"] = (None if base is None else
                                hashlib.sha256(mirrored.read_bytes())
                                .hexdigest() != base)
            out.append(row)
        return out

    def read_draft(self, path: str) -> str:
        """Full text of one pending draft — unreviewed material, not
        canon."""
        p = self._draft_path(path)
        if not p.is_file():
            raise StoreError(
                f"no such draft: {path} — list_drafts shows what is "
                "pending")
        return p.read_text(encoding="utf-8")
```

Also update the module docstring (line ~6): replace "the staging/canonical boundary" with "the drafts/inbound/canonical boundaries", and in `_canonical()`'s docstring replace the staging paragraph with: "The drafts and inbound directories are among the excluded ones, so neither is readable through this method: the canon read tools serve canon. Each has its own labelled door — read_draft and read_inbound — guarding the inverse condition."

- [ ] **Step 4: Run store tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_store -v`
Expected: PASS.

- [ ] **Step 5: Update `serve_mcp.py` tool registrations** — replace the four tools `save_draft`, `propose_revision`, `list_staged`, `read_staged` (lines ~122–153) with:

```python
    @server.tool()
    def save_draft(section: str, name: str, content: str,
                   subdir: str | None = None) -> str:
        """Draft NEW content (a full markdown file, front matter included)
        into your drafts directory for the GM to review and promote. The
        name is slugged to kebab-case (put the display title in front
        matter); subdir nests one level, e.g. section="Briefs",
        subdir="session-015". Never overwrites — revise existing drafts
        with update_draft. Returns the draft's path."""
        return store.save_draft(section, name, content, subdir)

    @server.tool()
    def propose_revision(path: str, content: str) -> str:
        """Propose a full-file revision of an EXISTING canonical file, as
        a shadow copy in your drafts directory; the GM reviews it as a
        diff. One pending proposal per file: if one exists, read_draft it,
        merge, and update_draft instead. Returns the draft's path."""
        return store.propose_revision(path, content)

    @server.tool()
    def list_drafts() -> list[dict]:
        """List your own unpromoted drafts from this and earlier sessions:
        path, kind ("new" content or a "revision" of an existing file),
        title and summary, and for revisions whether canon has changed
        underneath them (stale). Nothing here is canon — it is your
        unreviewed work awaiting the GM. Pick a draft up and merge rather
        than writing it again."""
        return store.list_drafts()

    @server.tool()
    def read_draft(path: str) -> str:
        """Read one of your pending drafts in full. Paths come from
        list_drafts. Draft material is UNREVIEWED and not canon — do not
        treat it as established fact. For canonical files, use
        read_entity."""
        return store.read_draft(path)
```

- [ ] **Step 6: Rewrite the tool-layer tests** — in `tests/test_serve_mcp.py`, replace `test_staging_tools_always_registered`, `test_staging_read_tools_always_registered`, `test_list_staged_reports_what_was_staged`, `test_read_staged_round_trips_a_draft`, `test_read_staged_refuses_a_canonical_path`, and `test_save_draft_lands_in_staging` (keep every other test) with:

```python
    async def test_draft_tools_always_registered(self):
        # The drafts directory is the agent's own outbox: writing to it and
        # reading it back need no flag; nothing here can reach canon.
        server = serve_mcp.build_server(scaffold(self))
        names = {t.name for t in await server.list_tools()}
        self.assertLessEqual(
            {"save_draft", "propose_revision", "list_drafts", "read_draft"},
            names)

    async def test_list_drafts_reports_what_was_drafted(self):
        store = scaffold(self)
        server = serve_mcp.build_server(store)
        await server.call_tool("save_draft", {
            "section": "NPCs", "name": "Cho", "content": "x"})
        payload = await self._text(await server.call_tool("list_drafts", {}))
        self.assertIn("_AgentDrafts/NPCs/cho.md", payload)

    async def test_read_draft_round_trips(self):
        store = scaffold(self)
        server = serve_mcp.build_server(store)
        await server.call_tool("save_draft", {
            "section": "NPCs", "name": "Cho", "content": "draft body"})
        payload = await self._text(await server.call_tool(
            "read_draft", {"path": "_AgentDrafts/NPCs/cho.md"}))
        self.assertIn("draft body", payload)

    async def test_read_draft_refuses_a_canonical_path(self):
        # The two read doors stay separate: read_draft must not become a
        # second way into canon.
        server = serve_mcp.build_server(scaffold(self))
        result = await server.call_tool(
            "read_draft", {"path": "NPCs/kim-ha-eun.md"})
        self.assertTrue(result.isError)

    async def test_save_draft_lands_in_the_drafts_dir(self):
        store = scaffold(self)
        server = serve_mcp.build_server(store)
        await server.call_tool("save_draft", {
            "section": "NPCs", "name": "Cho", "content": "x"})
        self.assertTrue(
            (store.ws.root / "_AgentDrafts/NPCs/cho.md").is_file())
```

(Match the surrounding file's existing call/assertion style if it differs — e.g. how error results are asserted; `test_read_staged_refuses_a_canonical_path` at line ~141 shows the current idiom. Reuse it.)

- [ ] **Step 7: Run the full suite**

Run: `PYTHONPATH=src python3 -m unittest discover -s tests`
Expected: OK. `tests.test_serve_mcp` SDK-gated tests skip locally; confirm they import cleanly.

- [ ] **Step 8: Commit**

```bash
git add src/bunnyforge/_store.py src/bunnyforge/serve_mcp.py tests/test_store.py tests/test_serve_mcp.py
git commit -m "feat: drafts family — save/propose/list/read over _AgentDrafts with base manifest"
```

---

### Task 3: `update_draft` — the single overwrite door

**Files:**
- Modify: `src/bunnyforge/_store.py` (add one method after `propose_revision`)
- Modify: `src/bunnyforge/serve_mcp.py` (register one tool after `propose_revision`)
- Modify: `tests/test_store.py`, `tests/test_serve_mcp.py`

**Interfaces:**
- Consumes: `_draft_path`, `_drafts`, `_set_base` (Task 2).
- Produces: `WorkspaceStore.update_draft(path: str, content: str) -> str` (Task 6's refusal messages point at it — the name must match exactly).

- [ ] **Step 1: Write the failing tests** — append to `tests/test_store.py`:

```python
class TestUpdateDraft(StoreCase):
    def test_overwrites_an_existing_draft(self):
        ws = self.make_ws()
        store = _store.WorkspaceStore(ws)
        rel = store.save_draft("NPCs", "Cho", "old")
        self.assertEqual(store.update_draft(rel, "new"), rel)
        self.assertEqual((ws.root / rel).read_text(encoding="utf-8"), "new")

    def test_missing_draft_is_refused_naming_save_draft(self):
        store = _store.WorkspaceStore(self.make_ws())
        with self.assertRaises(_store.StoreError) as ctx:
            store.update_draft("_AgentDrafts/NPCs/nobody.md", "x")
        self.assertIn("save_draft", str(ctx.exception))

    def test_canonical_and_escape_paths_are_refused(self):
        store = _store.WorkspaceStore(self.make_ws())
        with self.assertRaises(_store.StoreError):
            store.update_draft("NPCs/kim-ha-eun.md", "x")
        with self.assertRaises(_store.StoreError):
            store.update_draft("../outside.md", "x")

    def test_rebaselines_a_revision_shadow(self):
        # The refusal flow that leads here forced a read-and-merge, so the
        # agent has seen current canon: updating a shadow re-records its
        # base, and the revision stops being stale.
        ws = self.make_ws()
        store = _store.WorkspaceStore(ws)
        store.propose_revision("NPCs/kim-ha-eun.md", "first")
        (ws.root / "NPCs/kim-ha-eun.md").write_text("GM edit",
                                                    encoding="utf-8")
        self.assertIs(store.list_drafts()[0]["stale"], True)
        store.update_draft("_AgentDrafts/NPCs/kim-ha-eun.md", "merged")
        self.assertIs(store.list_drafts()[0]["stale"], False)

    def test_underscore_component_is_refused(self):
        ws = self.make_ws()
        rejected = ws.root / "_AgentDrafts" / "_Rejected"
        rejected.mkdir(parents=True)
        (rejected / "dead.md").write_text("x", encoding="utf-8")
        with self.assertRaises(_store.StoreError):
            _store.WorkspaceStore(ws).update_draft(
                "_AgentDrafts/_Rejected/dead.md", "resurrect")
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=src python3 -m unittest tests.test_store.TestUpdateDraft -v`
Expected: ERROR, `no attribute 'update_draft'`.

- [ ] **Step 3: Implement** — in `_store.py`, after `propose_revision`:

```python
    def update_draft(self, path: str, content: str) -> str:
        """Overwrite one existing draft — the only overwrite door, so
        clobbering is always deliberate: the path must already exist,
        which means it came from list_drafts or read_draft."""
        p = self._draft_path(path)
        if not p.is_file():
            raise StoreError(
                f"no such draft: {path} — save_draft creates new drafts; "
                "list_drafts shows what exists")
        p.write_text(content, encoding="utf-8")
        rel = p.relative_to(self.ws.root).as_posix()
        mirrored = self.ws.root / p.relative_to(self._drafts())
        if mirrored.is_file():
            self._set_base(rel, mirrored)
        return rel
```

In `serve_mcp.py`, after `propose_revision`:

```python
    @server.tool()
    def update_draft(path: str, content: str) -> str:
        """Overwrite one of your existing drafts with revised content —
        the deliberate way to iterate on a draft across sessions.
        read_draft it first and merge; updating a revision shadow also
        re-baselines it against current canon. Paths come from
        list_drafts."""
        return store.update_draft(path, content)
```

In `tests/test_serve_mcp.py`, extend the registered-names assertion in `test_draft_tools_always_registered` to include `"update_draft"`.

- [ ] **Step 4: Run the full suite**

Run: `PYTHONPATH=src python3 -m unittest discover -s tests`
Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add src/bunnyforge/_store.py src/bunnyforge/serve_mcp.py tests/test_store.py tests/test_serve_mcp.py
git commit -m "feat: update_draft — the single deliberate overwrite door for drafts"
```

---

### Task 4: The inbound family — GM's queue, read-only, only-when-asked

**Files:**
- Modify: `src/bunnyforge/_store.py` (new section between the drafts family and `write_entity`)
- Modify: `src/bunnyforge/serve_mcp.py` (two tools after `read_draft`)
- Modify: `tests/test_store.py`, `tests/test_serve_mcp.py`

**Interfaces:**
- Consumes: `Config.inbound_dir` (Task 1).
- Produces:
  - `WorkspaceStore.list_inbound() -> list[dict]` — rows `{path, readable}` (Task 5 counts its length)
  - `WorkspaceStore.read_inbound(path: str) -> str`
  - `WorkspaceStore._inbound_path(path: str) -> Path` — the resolver a future `mark_extracted` reuses
  - Module constant `INBOUND_SUFFIXES = frozenset({".md", ".txt", ".html", ".htm"})`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_store.py`:

```python
class TestInbound(StoreCase):
    """The GM's inbound queue. Read-only, and only when the GM asks: the
    tool descriptions carry that contract; the store's job is that _Done/
    (and any _-prefixed area) is unreachable and every live file is
    honestly listed."""

    def seed_queue(self, ws) -> Path:
        q = ws.root / "_ExtractInbound"
        (q / "anjeonggm").mkdir(parents=True)
        (q / "anjeonggm" / "idea.txt").write_text("a harbor heist",
                                                  encoding="utf-8")
        (q / "page.html").write_text("<p>hi</p>", encoding="utf-8")
        (q / "README.md").write_text("readme", encoding="utf-8")
        (q / "scan.pdf").write_bytes(b"%PDF-1.4 not text")
        done = q / "_Done"
        done.mkdir()
        (done / "spent.txt").write_text("processed", encoding="utf-8")
        return q

    def test_lists_every_live_file_marking_readability(self):
        # ALL extensions are listed — a listing that hides files is the
        # defect this redesign fixes (17 of 18 files were invisible). A
        # PDF appears, honestly marked unreadable.
        ws = self.make_ws()
        self.seed_queue(ws)
        self.assertEqual(_store.WorkspaceStore(ws).list_inbound(), [
            {"path": "_ExtractInbound/README.md", "readable": True},
            {"path": "_ExtractInbound/anjeonggm/idea.txt", "readable": True},
            {"path": "_ExtractInbound/page.html", "readable": True},
            {"path": "_ExtractInbound/scan.pdf", "readable": False},
        ])

    def test_done_is_never_listed(self):
        # _Done/ holds processed source awaiting the GM's manual cleanup —
        # never read, exactly like _Ignore/. Tested before _Done/ exists
        # anywhere in the wild: this was the trap in the old rglob.
        ws = self.make_ws()
        self.seed_queue(ws)
        paths = [r["path"] for r in _store.WorkspaceStore(ws).list_inbound()]
        self.assertFalse(any("_Done" in p for p in paths))

    def test_hidden_dot_files_are_skipped(self):
        # .DS_Store and friends are machinery, not GM material; listing
        # them would inflate inbound_pending and clutter every offer.
        ws = self.make_ws()
        q = self.seed_queue(ws)
        (q / ".DS_Store").write_bytes(b"\x00")
        paths = [r["path"] for r in _store.WorkspaceStore(ws).list_inbound()]
        self.assertFalse(any(".DS_Store" in p for p in paths))

    def test_no_queue_is_an_empty_list_not_an_error(self):
        store = _store.WorkspaceStore(self.make_ws())
        self.assertEqual(store.list_inbound(), [])

    def test_read_round_trips_text(self):
        ws = self.make_ws()
        self.seed_queue(ws)
        store = _store.WorkspaceStore(ws)
        self.assertEqual(
            store.read_inbound("_ExtractInbound/anjeonggm/idea.txt"),
            "a harbor heist")

    def test_undecodable_bytes_are_replaced_not_a_crash(self):
        # Inbound material is generated elsewhere; one stray latin-1 byte
        # in a GM's .txt must not crash the tool.
        ws = self.make_ws()
        q = ws.root / "_ExtractInbound"
        q.mkdir()
        (q / "weird.txt").write_bytes(b"caf\xe9")
        out = _store.WorkspaceStore(ws).read_inbound(
            "_ExtractInbound/weird.txt")
        self.assertEqual(out, "caf\ufffd")

    def test_non_text_read_is_refused_with_the_convert_hint(self):
        ws = self.make_ws()
        self.seed_queue(ws)
        with self.assertRaises(_store.StoreError) as ctx:
            _store.WorkspaceStore(ws).read_inbound(
                "_ExtractInbound/scan.pdf")
        self.assertIn("convert", str(ctx.exception))

    def test_done_read_is_refused(self):
        ws = self.make_ws()
        self.seed_queue(ws)
        with self.assertRaises(_store.StoreError):
            _store.WorkspaceStore(ws).read_inbound(
                "_ExtractInbound/_Done/spent.txt")

    def test_canonical_path_is_refused_naming_read_entity(self):
        store = _store.WorkspaceStore(self.make_ws())
        with self.assertRaises(_store.StoreError) as ctx:
            store.read_inbound("NPCs/kim-ha-eun.md")
        self.assertIn("read_entity", str(ctx.exception))

    def test_escape_is_refused(self):
        store = _store.WorkspaceStore(self.make_ws())
        with self.assertRaises(_store.StoreError):
            store.read_inbound("_ExtractInbound/../../outside.md")

    def test_missing_file_is_refused_naming_the_listing(self):
        ws = self.make_ws()
        (ws.root / "_ExtractInbound").mkdir()
        with self.assertRaises(_store.StoreError) as ctx:
            _store.WorkspaceStore(ws).read_inbound(
                "_ExtractInbound/nothing.txt")
        self.assertIn("list_inbound", str(ctx.exception))

    def test_honours_configured_inbound_dir(self):
        ws = self.make_ws('\n[workspace]\ninbound_dir = "_Inbox"\n')
        q = ws.root / "_Inbox"
        q.mkdir()
        (q / "idea.txt").write_text("x", encoding="utf-8")
        rows = _store.WorkspaceStore(ws).list_inbound()
        self.assertEqual(rows, [{"path": "_Inbox/idea.txt",
                                 "readable": True}])
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=src python3 -m unittest tests.test_store.TestInbound -v`
Expected: ERROR, `no attribute 'list_inbound'`.

- [ ] **Step 3: Implement** — in `_store.py`, add below the drafts family (module constant next to `BASES_NAME`):

```python
INBOUND_SUFFIXES = frozenset({".md", ".txt", ".html", ".htm"})
```

```python
    # -- inbound queue ------------------------------------------------------
    # The GM's inbound queue: material authored elsewhere, awaiting
    # extraction into proper entity files. Read-only here, and the tool
    # descriptions add "only when the GM asks". _inbound_path is the shared
    # resolver a future mark_extracted() reuses — a move tool is one new
    # method, not a rewrite (its _Done/ destination would be constructed
    # internally, not through this reader's resolver, which refuses
    # _-prefixed components).

    def _inbound(self) -> Path:
        return self.ws.root / self.ws.config.inbound_dir

    @staticmethod
    def _machinery(parts: tuple[str, ...]) -> bool:
        # _-prefixed: the workspace's machinery convention (_Done/,
        # _Rejected/). .-prefixed: hidden files (.DS_Store) — never GM
        # material, and listing them would inflate inbound_pending.
        return any(part.startswith(("_", ".")) for part in parts)

    def _inbound_path(self, path: str) -> Path:
        root = self.ws.root
        inbound = self._inbound()
        p = (root / path).resolve()
        if not p.is_relative_to(root):
            raise StoreError(f"path escapes the workspace: {path}")
        if not p.is_relative_to(inbound):
            raise StoreError(
                f"not an inbound path: {path} — read_inbound serves "
                f"{self.ws.config.inbound_dir}/ only; canonical files are "
                "read with read_entity")
        if self._machinery(p.relative_to(inbound).parts):
            raise StoreError(
                f"{path} is in a processed or private area of the inbound "
                "queue (_- or .-prefixed) and is never read — _Done/ holds "
                "spent source awaiting the GM's cleanup")
        return p

    def list_inbound(self) -> list[dict]:
        """Every live file in the GM's inbound queue, whatever its type:
        workspace path, and whether read_inbound can return it. Sorted,
        so two calls agree."""
        inbound = self._inbound()
        if not inbound.is_dir():
            return []
        out = []
        for p in sorted(inbound.rglob("*")):
            if not p.is_file():
                continue
            if self._machinery(p.relative_to(inbound).parts):
                continue
            out.append({
                "path": p.relative_to(self.ws.root).as_posix(),
                "readable": p.suffix.lower() in INBOUND_SUFFIXES})
        return out

    def read_inbound(self, path: str) -> str:
        """Full text of one inbound file — the GM's unreviewed source
        material, not canon. Decoding is forgiving (errors="replace"):
        this material was generated outside the workspace."""
        p = self._inbound_path(path)
        if p.suffix.lower() not in INBOUND_SUFFIXES:
            raise StoreError(
                f"{path} is not a text format serve-mcp can return "
                f"({', '.join(sorted(INBOUND_SUFFIXES))}) — ask the GM to "
                "convert or summarize it")
        if not p.is_file():
            raise StoreError(
                f"no such inbound file: {path} — list_inbound shows the "
                "queue")
        return p.read_text(encoding="utf-8", errors="replace")
```

- [ ] **Step 4: Run store tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_store -v`
Expected: PASS.

- [ ] **Step 5: Register the tools** — in `serve_mcp.py`, after `read_draft`:

```python
    @server.tool()
    def list_inbound() -> list[dict]:
        """The GM's inbound queue: material the GM authored elsewhere,
        awaiting extraction into proper entity files. Call this only when
        the GM asks you to extract — do not act on the queue unbidden.
        (campaign_overview's inbound_pending count is how you may notice
        it is non-empty and offer.) Lists every file with whether
        read_inbound can return it. Nothing here is canon."""
        return store.list_inbound()

    @server.tool()
    def read_inbound(path: str) -> str:
        """Read one file from the GM's inbound queue, only when the GM
        asks you to extract. Paths come from list_inbound. The material
        is unreviewed source, not canon — extract it into drafts, show
        the GM, and confirm before anything else happens with it."""
        return store.read_inbound(path)
```

- [ ] **Step 6: Tool-layer tests** — in `tests/test_serve_mcp.py`, add to the SDK-gated `TestBuildServer`:

```python
    async def test_inbound_tools_always_registered(self):
        server = serve_mcp.build_server(scaffold(self))
        names = {t.name for t in await server.list_tools()}
        self.assertLessEqual({"list_inbound", "read_inbound"}, names)

    async def test_inbound_descriptions_carry_the_contract(self):
        # Regression: the old list_staged description said the opposite
        # ("use it to pick up drafts"), actively nudging the agent to read
        # the GM's queue unbidden. The contract phrase is load-bearing.
        server = serve_mcp.build_server(scaffold(self))
        descs = {t.name: (t.description or "")
                 for t in await server.list_tools()}
        for name in ("list_inbound", "read_inbound"):
            self.assertIn("only when the GM asks", descs[name])
```

- [ ] **Step 7: Run the full suite**

Run: `PYTHONPATH=src python3 -m unittest discover -s tests`
Expected: OK (new SDK tests skip locally).

- [ ] **Step 8: Commit**

```bash
git add src/bunnyforge/_store.py src/bunnyforge/serve_mcp.py tests/test_store.py tests/test_serve_mcp.py
git commit -m "feat: inbound queue tools — list_inbound/read_inbound under the only-when-asked contract"
```

---

### Task 5: `campaign_overview` counts

**Files:**
- Modify: `src/bunnyforge/_store.py` (`overview()`, ~line 86)
- Modify: `src/bunnyforge/serve_mcp.py` (`campaign_overview` docstring)
- Modify: `tests/test_store.py` (`TestOverview`)

**Interfaces:**
- Consumes: `list_inbound()`, `list_drafts()` (Tasks 2, 4).
- Produces: `overview()` result gains `"inbound_pending": int` and `"drafts_pending": int`.

- [ ] **Step 1: Write the failing test** — add to `TestOverview` in `tests/test_store.py`:

```python
    def test_counts_pending_inbound_and_drafts(self):
        # Defined as exactly len(list_inbound()) / len(list_drafts()), so
        # a count and the listing it advertises cannot disagree. 0 when
        # the directory is absent: a count is always present, and
        # "nothing pending" is the true answer either way.
        ws = self.make_ws()
        store = _store.WorkspaceStore(ws)
        self.assertEqual(store.overview()["inbound_pending"], 0)
        self.assertEqual(store.overview()["drafts_pending"], 0)
        store.save_draft("NPCs", "Cho", "x")
        q = ws.root / "_ExtractInbound"
        (q / "_Done").mkdir(parents=True)
        (q / "idea.txt").write_text("x", encoding="utf-8")
        (q / "scan.pdf").write_bytes(b"%PDF")
        (q / "_Done" / "spent.txt").write_text("x", encoding="utf-8")
        ov = store.overview()
        self.assertEqual(ov["inbound_pending"], 2)  # pdf counted, _Done not
        self.assertEqual(ov["drafts_pending"], 1)
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=src python3 -m unittest tests.test_store.TestOverview -v`
Expected: FAIL, KeyError `'inbound_pending'`.

- [ ] **Step 3: Implement** — in `overview()`, immediately before the `return out` line, add:

```python
        # Counts, not contents: the agent may notice the GM's queue is
        # non-empty and offer to extract, without reading it unbidden.
        out["inbound_pending"] = len(self.list_inbound())
        out["drafts_pending"] = len(self.list_drafts())
```

In `serve_mcp.py`, extend the `campaign_overview` docstring to:

```python
    @server.tool()
    def campaign_overview() -> dict:
        """Get your bearings in one call: the campaign's name, each section
        with how many entities it holds, the current front-burner and
        open-questions documents, and two counts — drafts_pending (your
        own unpromoted drafts; list_drafts to resume them) and
        inbound_pending (files in the GM's inbound queue). If
        inbound_pending is non-zero you may mention it and offer to
        extract; do not list or read the queue unless the GM asks. Call
        this before anything else."""
        return store.overview()
```

- [ ] **Step 4: Run the full suite**

Run: `PYTHONPATH=src python3 -m unittest discover -s tests`
Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add src/bunnyforge/_store.py src/bunnyforge/serve_mcp.py tests/test_store.py
git commit -m "feat: overview reports drafts_pending and inbound_pending"
```

---

### Task 6: `promote_draft` behind `--allow-direct-edits`

**Files:**
- Modify: `src/bunnyforge/_store.py` (one method after `read_draft`)
- Modify: `src/bunnyforge/serve_mcp.py` (inside the `if allow_direct_edits:` block, ~line 155)
- Modify: `tests/test_store.py`, `tests/test_serve_mcp.py`

**Interfaces:**
- Consumes: `_draft_path`, `_drafts`, `_load_bases`, `_save_bases`, `_bases_file` (Task 2); the git-guard pattern from `write_entity`.
- Produces: `WorkspaceStore.promote_draft(path: str) -> str` (returns the canonical path it created/updated).

- [ ] **Step 1: Write the failing tests** — append to `tests/test_store.py` (the git scaffold copies `TestWriteEntity.make_git_ws`'s pattern):

```python
class TestPromoteDraft(StoreCase):
    """The GM's in-chat approval is the gate; the flag gates the
    capability per-run. The destination is derived — slugs made the
    drafts tree mirror canon — so there is no dest parameter to get
    wrong."""

    def make_git_ws(self):
        ws = self.make_ws()
        for cmd in (["init", "-q"], ["config", "user.email", "t@t"],
                    ["config", "user.name", "t"], ["add", "-A"],
                    ["commit", "-qm", "seed"]):
            subprocess.run(["git", "-C", str(ws.root)] + cmd, check=True)
        return ws

    def _git(self, ws, *args) -> str:
        return subprocess.run(["git", "-C", str(ws.root), *args],
                              capture_output=True, text=True,
                              check=True).stdout

    def test_promotes_a_new_draft_and_commits(self):
        ws = self.make_git_ws()
        store = _store.WorkspaceStore(ws)
        rel = store.save_draft("Ideas", "Harbor Heist",
                               "---\ntitle: Harbor Heist\n---\nplot\n")
        out = store.promote_draft(rel)
        self.assertEqual(out, "Ideas/harbor-heist.md")
        self.assertIn("plot", (ws.root / out).read_text(encoding="utf-8"))
        self.assertFalse((ws.root / rel).exists())
        self.assertIn("serve-mcp: promote Ideas/harbor-heist.md",
                      self._git(ws, "log", "-1", "--format=%s"))
        self.assertEqual(self._git(ws, "status", "--porcelain").strip(), "")

    def test_promotes_a_fresh_revision_and_clears_its_base(self):
        ws = self.make_git_ws()
        store = _store.WorkspaceStore(ws)
        rel = store.propose_revision("NPCs/kim-ha-eun.md", "improved text")
        out = store.promote_draft(rel)
        self.assertEqual(out, "NPCs/kim-ha-eun.md")
        self.assertEqual((ws.root / out).read_text(encoding="utf-8"),
                         "improved text")
        self.assertFalse((ws.root / rel).exists())
        bases = json.loads(
            (ws.root / "_AgentDrafts" / ".proposal-bases.json")
            .read_text(encoding="utf-8"))
        self.assertEqual(bases, {})
        self.assertEqual(self._git(ws, "status", "--porcelain").strip(), "")

    def test_stale_revision_is_refused_not_applied(self):
        # Promoting a stale shadow would revert the GM's interim edits,
        # disguised inside an intended diff.
        ws = self.make_git_ws()
        store = _store.WorkspaceStore(ws)
        rel = store.propose_revision("NPCs/kim-ha-eun.md", "proposal")
        (ws.root / "NPCs/kim-ha-eun.md").write_text("GM edit",
                                                    encoding="utf-8")
        with self.assertRaises(_store.StoreError) as ctx:
            store.promote_draft(rel)
        self.assertIn("update_draft", str(ctx.exception))
        self.assertEqual(
            (ws.root / "NPCs/kim-ha-eun.md").read_text(encoding="utf-8"),
            "GM edit")  # canon untouched

    def test_unrecorded_base_is_refused(self):
        # Covers a hand-authored shadow AND a draft whose canonical
        # counterpart appeared after it was saved: target exists, no base
        # on record, so promotion cannot verify and refuses.
        ws = self.make_git_ws()
        store = _store.WorkspaceStore(ws)
        shadow = ws.root / "_AgentDrafts" / "NPCs"
        shadow.mkdir(parents=True)
        (shadow / "kim-ha-eun.md").write_text("hand-made", encoding="utf-8")
        with self.assertRaises(_store.StoreError):
            store.promote_draft("_AgentDrafts/NPCs/kim-ha-eun.md")

    def test_refuses_outside_a_git_repo_before_touching_anything(self):
        ws = self.make_ws()  # no git init
        store = _store.WorkspaceStore(ws)
        rel = store.save_draft("Ideas", "Heist", "plot")
        with self.assertRaises(_store.StoreError) as ctx:
            store.promote_draft(rel)
        self.assertIn("git", str(ctx.exception))
        self.assertTrue((ws.root / rel).is_file())   # draft still there
        self.assertFalse((ws.root / "Ideas/heist.md").exists())

    def test_missing_draft_is_refused(self):
        store = _store.WorkspaceStore(self.make_git_ws())
        with self.assertRaises(_store.StoreError) as ctx:
            store.promote_draft("_AgentDrafts/Ideas/nothing.md")
        self.assertIn("list_drafts", str(ctx.exception))
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=src python3 -m unittest tests.test_store.TestPromoteDraft -v`
Expected: ERROR, `no attribute 'promote_draft'`.

- [ ] **Step 3: Implement** — in `_store.py`, after `read_draft`:

```python
    def promote_draft(self, path: str) -> str:
        """Move one approved draft to its canonical location and commit.

        The destination is derived by stripping the drafts prefix — slugs
        made the two trees mirror. Order matters: every refusal fires
        before the filesystem changes, so a refused promotion leaves the
        draft exactly where it was."""
        p = self._draft_path(path)
        if not p.is_file():
            raise StoreError(
                f"no such draft: {path} — list_drafts shows what is "
                "pending")
        rel = p.relative_to(self.ws.root).as_posix()
        inner = p.relative_to(self._drafts())
        target = self.ws.root / inner
        target_rel = inner.as_posix()
        if target.is_file():
            # A revision: its recorded base must still match canon. None
            # (unrecorded) never equals a hash, so unverifiable shadows
            # are refused too rather than silently applied.
            base = self._load_bases().get(rel)
            if base != hashlib.sha256(target.read_bytes()).hexdigest():
                raise StoreError(
                    f"{target_rel} changed since this revision was "
                    "proposed (or its base is unrecorded) — read_entity "
                    "the current file, merge with update_draft, then "
                    "promote again")
        probe = subprocess.run(
            ["git", "-C", str(self.ws.root), "rev-parse",
             "--is-inside-work-tree"], capture_output=True, text=True)
        if probe.returncode != 0:
            raise StoreError(
                "promotion requires the workspace to be a git repository "
                "— refusing to change canon without history")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
        p.unlink()
        bases = self._load_bases()
        bases.pop(rel, None)
        self._save_bases(bases)
        # Stage exactly what promotion touched: the target, plus the
        # removed draft and the manifest when git can see them (a
        # never-tracked deleted path would fail `git add` as an unmatched
        # pathspec).
        bases_rel = self._bases_file().relative_to(self.ws.root).as_posix()
        spec = [target_rel]
        for cand in (rel, bases_rel):
            tracked = subprocess.run(
                ["git", "-C", str(self.ws.root), "ls-files", "--", cand],
                capture_output=True, text=True).stdout.strip()
            if tracked or (self.ws.root / cand).exists():
                spec.append(cand)
        for sub in (["add", "-A", "--"] + spec,
                    ["commit", "-m", f"serve-mcp: promote {target_rel}"]):
            done = subprocess.run(["git", "-C", str(self.ws.root)] + sub,
                                  capture_output=True, text=True)
            if done.returncode != 0:
                raise StoreError(
                    f"git {sub[0]} failed: "
                    f"{done.stderr.strip() or done.stdout.strip()}")
        return target_rel
```

- [ ] **Step 4: Run store tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_store -v`
Expected: PASS.

- [ ] **Step 5: Register the tool** — in `serve_mcp.py`, inside the existing `if allow_direct_edits:` block, after `write_entity`:

```python
        @server.tool()
        def promote_draft(path: str) -> str:
            """Move one draft the GM has just approved in this chat to its
            canonical location (derived from the draft path) and commit
            it. Only call this after the GM's explicit approval of that
            specific draft. A stale revision is refused — merge with
            update_draft first. Available only because this server was
            started with --allow-direct-edits."""
            return store.promote_draft(path)
```

In `tests/test_serve_mcp.py`, find the existing SDK-gated test asserting `write_entity` is registered only with the flag (~line 151) and extend it — or mirror it — so it also asserts: `"promote_draft"` absent from the default server's tool names, present with `allow_direct_edits=True`.

- [ ] **Step 6: Run the full suite**

Run: `PYTHONPATH=src python3 -m unittest discover -s tests`
Expected: OK.

- [ ] **Step 7: Commit**

```bash
git add src/bunnyforge/_store.py src/bunnyforge/serve_mcp.py tests/test_store.py tests/test_serve_mcp.py
git commit -m "feat: promote_draft — gated in-chat promotion with stale-base refusal"
```

---

### Task 7: Documentation

**Files:**
- Modify: `docs/serve-mcp.md` ("What the agent can do", lines ~92–139; nothing else in the file changes)
- Modify: `src/bunnyforge/data/doctrine/AGENTS.md` (directory rules ~line 179; `_ExtractInbound` section lines 78–102)

**Interfaces:** none — prose only. Source of truth: spec §6 and the spec appendix.

- [ ] **Step 1: Rewrite `docs/serve-mcp.md` "What the agent can do"** — replace everything from `**Write back, into staging:**` (line ~99) through the `--allow-direct-edits` paragraph's end (line ~135) with:

```markdown
**Write drafts:**

| tool | writes to |
|---|---|
| `save_draft(section, name, content, subdir=None)` | `<drafts_dir>/<section>/[<subdir>/]<slug>.md` — new content; names are slugged to kebab-case; never overwrites |
| `propose_revision(path, content)` | `<drafts_dir>/<path>`, mirroring the canonical path, so you review it as a diff; one pending proposal per file |
| `update_draft(path, content)` | an existing draft — the one deliberate overwrite door, for iterating across sessions |

All of it lands in the agents' drafts directory (`drafts_dir`, default
`_AgentDrafts`) and goes no further. That directory is always excluded
from the canon read tools — whatever `exclude_dirs` says — so drafts stay
invisible to every other bunnyforge command until you promote them.
**In the default configuration the agent cannot alter canon at all.**

**Read drafts back:** `list_drafts()` gives every pending draft with its
kind (`new` or `revision`), title, summary, and — for revisions — whether
canon changed underneath the proposal (`stale`). `read_draft(path)`
returns one in full. They exist so the agent picks up its own earlier
work and merges rather than re-writing; a `_`-prefixed subdirectory
(say, `_AgentDrafts/_Rejected/`, if you use rejection-by-moving) is
never listed or read, so rejected material stays rejected.

**The inbound queue — read only when you ask:** `_ExtractInbound/`
(`inbound_dir`) is yours: material you authored elsewhere, awaiting
extraction. `list_inbound()` lists every live file — all formats, each
marked `readable` or not — and `read_inbound(path)` returns text formats
(`.md`, `.txt`, `.html`, `.htm`; anything else is listed but refused
with a convert-it hint, and undecodable bytes are replaced rather than
crashing). Both tools' descriptions carry your AGENTS.md contract: the
agent calls them **only when you ask it to extract**. It learns the
queue is non-empty from `campaign_overview`'s `inbound_pending` count —
which permits noticing and offering, never unbidden reading.
`_ExtractInbound/_Done/` and any other `_`-prefixed area are invisible
to both tools, exactly like `_Ignore/`.

**Write back, into canon — only if you ask for it:**

    bunnyforge serve-mcp --allow-direct-edits ...

registers two more tools. `write_entity(path, content)` edits a
canonical file in place and commits each edit with a
`serve-mcp: edit <path>` message. `promote_draft(path)` moves a draft
you have just approved in chat to its canonical location (derived from
the draft path — slugged drafts mirror canon) and commits it as
`serve-mcp: promote <path>`; a revision whose base no longer matches
canon is refused, never silently applied over your interim edits.
Promotion deliberately does not touch `compendium.md` or
`front-burner.md` — index updates flow through `propose_revision` as
ever. Both tools refuse outside a git repository: without history there
is no review and no undo, and that is the only thing that makes
changing canon defensible. It is a per-run flag rather than a config
key on purpose — trading the review boundary for git history should be
a decision you make when starting the server, not a setting that
quietly persists.
```

Then sweep the rest of `docs/serve-mcp.md` for the words "staging"/"staged" (the intro table reference at ~line 106 and the "Read back its own staging" paragraph are covered by the replacement above; check nothing else remains): `grep -n "stag" docs/serve-mcp.md` must return nothing.

- [ ] **Step 2: Edit the scaffolded doctrine** — in `src/bunnyforge/data/doctrine/AGENTS.md`:

(a) In the directory rules (the list containing "Do not read `_ExtractInbound/` unless…", ~line 179), add after that bullet:

```markdown
- `_AgentDrafts/` is the agents' outbox: drafts and proposed revisions
  awaiting my review, written by the MCP tools (or by you, if I ask you to
  draft something). Read it freely; nothing in it is canon. If I reject a
  draft I delete it or move it to `_AgentDrafts/_Rejected/`, which is
  never read, like `_Ignore/`.
```

(b) In "Extracting from _ExtractInbound/" (lines 78–102): add a bullet after "**Read it only when I ask you to extract.**…":

```markdown
- **The MCP agent reaches this queue through `list_inbound` and
  `read_inbound`, under exactly these rules.**
```

and change the move bullet ("Once I confirm an extraction, move the spent source into `_ExtractInbound/_Done/`. Do not delete it; …") to begin:

```markdown
- **Extract, show me, confirm, then move — never delete.** Once I confirm
  an extraction, move the spent source into `_ExtractInbound/_Done/` — or,
  if you cannot move files, say so and I will. Do not delete it; I clear
  `_Done/` myself. And never move anything before I have confirmed. The
  active directory emptying is how we track what remains to process.
```

- [ ] **Step 3: Full-suite run and staging-vocabulary sweep**

Run: `PYTHONPATH=src python3 -m unittest discover -s tests`
Expected: OK.

Run: `grep -rn "staging\|staged" src/bunnyforge/_store.py src/bunnyforge/_config.py src/bunnyforge/serve_mcp.py docs/serve-mcp.md src/bunnyforge/data/doctrine/AGENTS.md src/bunnyforge/data/campaign.toml.in`
Expected: no output. (The doctrine's old "staging area" phrasings at lines 80 and 180 must be reworded to "inbound queue" as part of Step 2 if the grep still catches them.)

- [ ] **Step 4: Commit**

```bash
git add docs/serve-mcp.md src/bunnyforge/data/doctrine/AGENTS.md
git commit -m "docs: drafts/inbound vocabulary for serve-mcp and the scaffolded doctrine"
```

---

## After the last task

1. Full suite once more from a clean state: `git status` (clean), then `PYTHONPATH=src python3 -m unittest discover -s tests`.
2. The PR body should carry the release note verbatim: *"Agent-written drafts still in `_ExtractInbound/` from the old scheme should be moved to `_AgentDrafts/` or deleted. A `staging_dir` key in `campaign.toml` must be renamed to `inbound_dir`."* Plus the suggested live-workspace AGENTS.md edit (spec appendix) for the GM to apply by hand.
3. Open the PR with the `dcltdw:opening-a-pr` skill; do not merge — the GM reviews first.
