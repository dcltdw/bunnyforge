# Scoped Retrieval (#66) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `scope: "live" | "archive" | "both"` to the MCP `search` and `list_entities` tools with symmetric scope-resolved section semantics, label every result with `archived`, add `campaign_overview`'s `archive_sections` breakdown, and ship the ask-the-GM-at-task-start retrieval doctrine.

**Architecture:** All filtering lives in `_store.py` — one validator (`_check_retrieval`) and one membership predicate (`_in_scope`) shared by both tools so they cannot drift. `serve_mcp.py` only threads the parameter and carries the condensed guidance in docstrings. The packaged doctrine gets one new section (the primary home for the scope-is-the-GM's-call rule).

**Tech Stack:** Python ≥ 3.11, stdlib only at runtime. Tests via `unittest` discovery. The `mcp` SDK is an optional extra used only by `serve_mcp` tests (they skip without it).

**Spec:** `docs/superpowers/specs/2026-08-18-scoped-retrieval-design.md` — the plan argues from the spec; read both. The spec's decisions table is binding (notably: symmetric scope-resolution, `both` as the default token, the revision of #62's listings record).

## Global Constraints

- Python ≥ 3.11, **stdlib only at runtime**; no new dependencies.
- **No new packaged files** — the doctrine edit is in-place, so `init.MANIFEST` must not change (`tests/test_init.py` proves it complete both ways).
- Default scope is `"both"` — the union behavior stays the default (ticket decision of record).
- No test may write into the repo (CI enforces); every test scaffolds into `tempfile.TemporaryDirectory()`.
- Fresh-workspace gate must stay green: `bunnyforge init` → `bunnyforge review checkup` reports `Summary: 0 error(s), 0 warning(s)`.
- **Worktree Python:** bare `python3` resolves `bunnyforge` to the primary clone. Run every test/gate command with `PYTHONPATH=src` from the worktree root, and verify once with `PYTHONPATH=src python3 -c "import bunnyforge; print(bunnyforge.__file__)"` (must print this worktree's path). Never pip install into any shared environment.
- The `mcp` extra is not installed in the worktree environment: `test_serve_mcp`'s `HAVE_MCP` tests **skip locally** (baseline: 901 tests, 54 skips) and run in CI's dedicated mcp job. Write them anyway; do not chase local skips.
- Never commit to `main`; work stays on this worktree branch (`worktree-scoped-retrieval-66`); every commit carries a `Co-Authored-By:` trailer naming the current model.
- **Human vocabulary read (spec §7):** with #65 deferred, no automated check scans packaged prose for campaign vocabulary. Every line of new prose in `src/bunnyforge/data/` and the new tool docstrings needs a deliberate GM read before the PR merges — Task 5 ends at that checkpoint; it is a review step, not a test.

---

### Task 1: Store — scope validation and scoped `search`

**Files:**
- Modify: `src/bunnyforge/_store.py` (constant near `SEARCH_CAP:33`; two new methods after `_check_section:74`; rewrite `search:163`)
- Test: `tests/test_store.py` (helper on `StoreCase:23`; new class after `TestSearch`, which ends ~line 222)

**Interfaces:**
- Consumes: `_common.iter_content_files(ws)` (existing), `self._check_section(section)` (existing), `self.ws.config.archive_dir` (existing, default `"Archive"`).
- Produces (Tasks 2–4 rely on these exact names):
  - `_store.SCOPES = ("live", "archive", "both")` (module constant)
  - `WorkspaceStore._check_retrieval(section: str | None, scope: str) -> None` — raises `StoreError` on a bad scope token, unknown section, or the `live`+`Archive` contradiction.
  - `WorkspaceStore._in_scope(parts: tuple[str, ...], section: str | None, scope: str) -> bool` — membership of one walked file, `parts` being its workspace-relative path components.
  - `WorkspaceStore.search(query, section=None, scope="both")` — hits now carry `"archived": bool`.
  - Test helper `StoreCase.make_archived_ws()` — `make_ws()` plus `Archive/NPCs/old-hag.md` and stray `Archive/stray.md`.

- [ ] **Step 1: Add the archive fixture helper and write the failing tests**

In `tests/test_store.py`, add to `StoreCase` (below `make_ws`):

```python
    def make_archived_ws(self, toml_extra: str = "") -> _config.Workspace:
        """make_ws plus a mirrored archive: one archived NPC, and one
        stray file directly at the archive root (no mirror section)."""
        ws = self.make_ws(toml_extra)
        arch = ws.root / "Archive" / "NPCs"
        arch.mkdir(parents=True)
        (arch / "old-hag.md").write_text(
            "---\ntitle: The Old Hag\nsummary: Retired rival on the "
            "ferry route.\nstatus: retired\n---\n"
            "She haunted the ferry route.\n", encoding="utf-8")
        (ws.root / "Archive" / "stray.md").write_text(
            "---\ntitle: Stray\nsummary: A stray archived note.\n---\n"
            "ferry flotsam\n", encoding="utf-8")
        return ws
```

(`"ferry"` now matches all four content files: the live NPC's front matter, `front-burner.md`, the archived NPC, and the stray — one query exercises every bucket.)

Add a new test class directly after `TestSearch`:

```python
class TestScopedSearch(StoreCase):
    """#66: scope: live | archive | both, section resolving inside the
    scope's tree(s), every hit labelled archived."""

    def test_default_scope_is_both_and_labels_every_hit(self):
        store = _store.WorkspaceStore(self.make_archived_ws())
        by_path = {h["path"]: h["archived"] for h in store.search("ferry")}
        self.assertEqual(by_path, {
            "NPCs/kim-ha-eun.md": False,
            "front-burner.md": False,
            "Archive/NPCs/old-hag.md": True,
            "Archive/stray.md": True,
        })

    def test_scope_live_excludes_archived_hits_keeps_root_docs(self):
        store = _store.WorkspaceStore(self.make_archived_ws())
        paths = {h["path"] for h in store.search("ferry", scope="live")}
        self.assertEqual(paths, {"NPCs/kim-ha-eun.md", "front-burner.md"})

    def test_scope_archive_returns_only_archived_hits(self):
        store = _store.WorkspaceStore(self.make_archived_ws())
        paths = {h["path"] for h in store.search("ferry", scope="archive")}
        self.assertEqual(paths,
                         {"Archive/NPCs/old-hag.md", "Archive/stray.md"})

    def test_sectioned_both_is_the_union_of_the_trees(self):
        # section="NPCs" covers NPCs/ AND Archive/NPCs/ under the default.
        store = _store.WorkspaceStore(self.make_archived_ws())
        paths = {h["path"] for h in store.search("ferry", section="NPCs")}
        self.assertEqual(paths,
                         {"NPCs/kim-ha-eun.md", "Archive/NPCs/old-hag.md"})

    def test_sectioned_archive_scope_resolves_the_mirror(self):
        store = _store.WorkspaceStore(self.make_archived_ws())
        hits = store.search("ferry", section="NPCs", scope="archive")
        self.assertEqual([h["path"] for h in hits],
                         ["Archive/NPCs/old-hag.md"])

    def test_sectioned_live_scope_stays_pure_live(self):
        store = _store.WorkspaceStore(self.make_archived_ws())
        hits = store.search("ferry", section="NPCs", scope="live")
        self.assertEqual([h["path"] for h in hits], ["NPCs/kim-ha-eun.md"])

    def test_section_archive_means_the_whole_archive(self):
        # Under "both" and "archive" alike; strays included.
        store = _store.WorkspaceStore(self.make_archived_ws())
        for scope in ("both", "archive"):
            paths = {h["path"] for h in
                     store.search("ferry", section="Archive", scope=scope)}
            self.assertEqual(
                paths, {"Archive/NPCs/old-hag.md", "Archive/stray.md"},
                scope)

    def test_a_stray_archive_file_is_in_no_mirror_section(self):
        # "flotsam" appears only in Archive/stray.md, which has no mirror.
        store = _store.WorkspaceStore(self.make_archived_ws())
        self.assertEqual(store.search("flotsam", section="NPCs"), [])
        self.assertEqual(
            [h["path"] for h in store.search("flotsam")],
            ["Archive/stray.md"])

    def test_scope_live_with_section_archive_is_a_refused_contradiction(self):
        store = _store.WorkspaceStore(self.make_archived_ws())
        with self.assertRaises(_store.StoreError) as ctx:
            store.search("ferry", section="Archive", scope="live")
        self.assertIn("contradicts", str(ctx.exception))
        self.assertIn("archive", str(ctx.exception).lower())

    def test_unknown_scope_is_refused_naming_the_valid_ones(self):
        store = _store.WorkspaceStore(self.make_archived_ws())
        with self.assertRaises(_store.StoreError) as ctx:
            store.search("ferry", scope="everything")
        for token in ("live", "archive", "both"):
            self.assertIn(token, str(ctx.exception))
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `PYTHONPATH=src python3 -m unittest tests.test_store.TestScopedSearch -v`
Expected: FAIL/ERROR on every test — `search() got an unexpected keyword argument 'scope'` and, for the default-scope test, a missing `archived` key.

- [ ] **Step 3: Implement scope in `_store.py`**

Add the constant next to the other module constants (after `NAME_COUNT_CAP`):

```python
SCOPES = ("live", "archive", "both")  # exactly two trees exist (#62), so
                                      # "both" is the honest union token
```

Add two methods to `WorkspaceStore` directly after `_check_section`:

```python
    def _check_retrieval(self, section: str | None, scope: str) -> None:
        """Validate a search/list_entities filter pair before any walk.

        scope names which tree(s) to read. One combination is a
        contradiction rather than an empty answer -- the archive
        section under a scope that excludes archived files -- and a
        contradiction is refused, not served (#66).
        """
        if scope not in SCOPES:
            raise StoreError(f"unknown scope {scope!r} — one of: "
                             + ", ".join(SCOPES))
        if section is not None:
            self._check_section(section)
            if scope == "live" and section == self.ws.config.archive_dir:
                raise StoreError(
                    f"section {section!r} contradicts scope 'live': "
                    "archived files are exactly what it excludes — drop "
                    "the section, or use scope 'archive'")

    def _in_scope(self, parts: tuple[str, ...], section: str | None,
                  scope: str) -> bool:
        """One walked file's membership under a validated filter (#66).

        A file is archived iff its first component is the archive dir.
        section names the CONTENT section and resolves inside the
        scope's tree(s): live files match on parts[0], archived files
        on their mirror (parts[1]); the archive dir's own name denotes
        the archive tree. A stray directly at Archive/*.md has no
        mirror, so it matches whole-archive queries and no section.
        """
        archive = self.ws.config.archive_dir
        archived = parts[0] == archive
        if (scope == "live" and archived) or \
                (scope == "archive" and not archived):
            return False
        if section is None:
            return True
        if section == archive:
            return archived
        if archived:
            return len(parts) > 2 and parts[1] == section
        return parts[0] == section
```

Rewrite `search` (replacing the `_check_section` call and the
`rel.startswith` filter; the docstring's first paragraph is unchanged):

```python
    def search(self, query: str, section: str | None = None,
               scope: str = "both") -> list[dict]:
        """Case-insensitive substring search across content files.

        Deliberately literal rather than clever: an agent that can see the
        matched text decides relevance better than a ranking heuristic
        would, and a substring match is explainable when it surprises.

        scope and section resolve per _in_scope (#66); every hit says
        whether it is archived, so the caller buckets hits without
        parsing paths.
        """
        q = query.strip().lower()
        if not q:
            raise StoreError("empty search query")
        self._check_retrieval(section, scope)

        archive = self.ws.config.archive_dir
        hits: list[dict] = []
        for rec in _common.iter_content_files(self.ws):
            rel = rec.path.relative_to(self.ws.root)
            if not self._in_scope(rel.parts, section, scope):
                continue
            text = rec.path.read_text(encoding="utf-8")
            i = text.lower().find(q)
            if i == -1:
                continue
            lo = max(0, i - SNIPPET_RADIUS)
            hi = min(len(text), i + len(q) + SNIPPET_RADIUS)
            hits.append({"path": rel.as_posix(), "snippet": text[lo:hi],
                         "archived": rel.parts[0] == archive})
            if len(hits) >= SEARCH_CAP:
                # Say so rather than truncating silently: a capped reply that
                # looks complete is worse than a short one that admits it.
                hits.append({"path": "", "snippet":
                             f"(truncated at {SEARCH_CAP} hits — "
                             "narrow the query)"})
                break
        return hits
```

(The truncation sentinel keeps its exact two-key shape — spec §2: it is a notice, not a result.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=src python3 -m unittest tests.test_store.TestScopedSearch tests.test_store.TestSearch tests.test_store.TestOverview -v`
Expected: all PASS (existing `TestSearch`/`TestOverview` prove no regression — their assertions are key-access/subset style and tolerate the new field).

- [ ] **Step 5: Commit**

```bash
git add src/bunnyforge/_store.py tests/test_store.py
git commit -m "feat: scoped search — scope live|archive|both, archived flag (#66)"
```

(Append the `Co-Authored-By:` trailer naming the current model — here and on every commit below.)

---

### Task 2: Store — scoped `list_entities`

**Files:**
- Modify: `src/bunnyforge/_store.py` (`list_entities:138`)
- Test: `tests/test_store.py` (new class after `TestScopedSearch`; amend `TestListEntities.test_lists_title_and_summary:118`)

**Interfaces:**
- Consumes: `_check_retrieval`, `_in_scope`, `make_archived_ws` (Task 1, exact signatures above).
- Produces: `WorkspaceStore.list_entities(section: str, scope: str = "both") -> list[dict]`, rows `{"path", "title", "summary", "archived"}` — Task 4's tool layer passes `scope` straight through.

- [ ] **Step 1: Write the failing tests**

New class after `TestScopedSearch`:

```python
class TestScopedListEntities(StoreCase):

    def test_sectioned_both_lists_live_and_mirrored_archived_rows(self):
        # #62's collision check makes archived names taken; the listing
        # that says "what already exists" must therefore show them.
        store = _store.WorkspaceStore(self.make_archived_ws())
        rows = {r["path"]: r for r in store.list_entities("NPCs")}
        self.assertEqual(set(rows), {"NPCs/kim-ha-eun.md",
                                     "Archive/NPCs/old-hag.md"})
        self.assertFalse(rows["NPCs/kim-ha-eun.md"]["archived"])
        self.assertTrue(rows["Archive/NPCs/old-hag.md"]["archived"])
        self.assertEqual(rows["Archive/NPCs/old-hag.md"]["title"],
                         "The Old Hag")

    def test_scope_live_lists_only_the_live_tree(self):
        store = _store.WorkspaceStore(self.make_archived_ws())
        self.assertEqual(
            [r["path"] for r in store.list_entities("NPCs", scope="live")],
            ["NPCs/kim-ha-eun.md"])

    def test_scope_archive_resolves_the_mirror(self):
        store = _store.WorkspaceStore(self.make_archived_ws())
        self.assertEqual(
            [r["path"] for r in
             store.list_entities("NPCs", scope="archive")],
            ["Archive/NPCs/old-hag.md"])

    def test_section_archive_lists_the_whole_archive_strays_included(self):
        store = _store.WorkspaceStore(self.make_archived_ws())
        self.assertEqual(
            {r["path"] for r in store.list_entities("Archive")},
            {"Archive/NPCs/old-hag.md", "Archive/stray.md"})

    def test_scope_live_with_section_archive_is_refused(self):
        store = _store.WorkspaceStore(self.make_archived_ws())
        with self.assertRaises(_store.StoreError) as ctx:
            store.list_entities("Archive", scope="live")
        self.assertIn("contradicts", str(ctx.exception))

    def test_unknown_scope_is_refused(self):
        store = _store.WorkspaceStore(self.make_archived_ws())
        with self.assertRaises(_store.StoreError):
            store.list_entities("NPCs", scope="everything")
```

Amend the existing full-equality test (`TestListEntities.test_lists_title_and_summary`) — the row gains the always-present flag:

```python
    def test_lists_title_and_summary(self):
        store = _store.WorkspaceStore(self.make_ws())
        self.assertEqual(store.list_entities("NPCs"), [{
            "path": "NPCs/kim-ha-eun.md",
            "title": "Kim Ha-eun",
            "summary": "Kim Ha-eun is a ferry captain in Testmere harbor.",
            "archived": False,
        }])
```

- [ ] **Step 2: Run to verify the new class fails**

Run: `PYTHONPATH=src python3 -m unittest tests.test_store.TestScopedListEntities tests.test_store.TestListEntities -v`
Expected: `TestScopedListEntities` FAILS (`unexpected keyword argument 'scope'`; union row missing); the amended equality test FAILS (no `archived` key yet).

- [ ] **Step 3: Implement**

Replace `list_entities` in `_store.py`:

```python
    def list_entities(self, section: str, scope: str = "both") -> list[dict]:
        """One section's files: workspace path, title, one-line summary,
        and whether the file is archived.

        Summaries come from front matter, where this workspace's convention
        puts a retrievable one-sentence description — which is what makes a
        listing useful to an agent that has not read the files.

        section resolves inside the scope's tree(s) (#66): the default
        "both" lists live and mirrored archived members together, each
        row labelled, because archived names are still taken (#62's
        collision check) and a listing that hides them invites reuse.
        """
        self._check_retrieval(section, scope)
        archive = self.ws.config.archive_dir
        out = []
        for rec in _common.iter_content_files(self.ws):
            rel = rec.path.relative_to(self.ws.root)
            if not self._in_scope(rel.parts, section, scope):
                continue
            out.append({"path": rel.as_posix(),
                        "title": rec.fm.get("title") or rec.path.stem,
                        "summary": rec.fm.get("summary", ""),
                        "archived": rel.parts[0] == archive})
        return out
```

- [ ] **Step 4: Run the store suite to verify everything passes**

Run: `PYTHONPATH=src python3 -m unittest tests.test_store -v`
Expected: all PASS (including `TestOverview.test_archive_is_a_section_of_its_own` and `TestOverview.test_counts_agree_with_list_entities`, which exercise the old call shapes).

- [ ] **Step 5: Commit**

```bash
git add src/bunnyforge/_store.py tests/test_store.py
git commit -m "feat: scoped list_entities — union sections, archived flag (#66)"
```

---

### Task 3: Store — `campaign_overview`'s `archive_sections`

**Files:**
- Modify: `src/bunnyforge/_store.py` (`overview:109`)
- Test: `tests/test_store.py` (add to `TestOverview:37`)

**Interfaces:**
- Consumes: `make_archived_ws` (Task 1).
- Produces: `overview()` result gains `"archive_sections": dict[str, int]` — present iff the archive directory exists; counts by mirror section (`parts[1]`, only when `len(parts) > 2`). Task 4's `campaign_overview` docstring names this key.

- [ ] **Step 1: Write the failing tests**

Add to `TestOverview`:

```python
    def test_archive_sections_breaks_the_archive_down_by_mirror(self):
        store = _store.WorkspaceStore(self.make_archived_ws())
        ov = store.overview()
        # The stray at Archive/stray.md is in the flat total but no
        # breakdown entry -- the sections rule applied one level down,
        # exactly as root docs are absent from sections.
        self.assertEqual(ov["sections"]["Archive"], 2)
        self.assertEqual(ov["archive_sections"], {"NPCs": 1})

    def test_archive_sections_absent_without_an_archive(self):
        # Absent, not empty: same philosophy as sections.
        store = _store.WorkspaceStore(self.make_ws())
        self.assertNotIn("archive_sections", store.overview())
```

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=src python3 -m unittest tests.test_store.TestOverview -v`
Expected: the two new tests FAIL with `KeyError: 'archive_sections'` (first) — the second may pass trivially before implementation; that is fine, it pins the absence rule against regression.

- [ ] **Step 3: Implement**

In `overview()`, replace the counting loop and the `out` construction (the docstring, root-doc, and pending-count code are untouched):

```python
        counts: dict[str, int] = {}
        archive_counts: dict[str, int] = {}
        archive = cfg.archive_dir
        for rec in _common.iter_content_files(self.ws):
            parts = rec.path.relative_to(self.ws.root).parts
            if len(parts) > 1:
                counts[parts[0]] = counts.get(parts[0], 0) + 1
            # The archive breakdown applies the sections rule one level
            # down (#66): count the mirror when there is one. A stray at
            # Archive/*.md stays in the flat Archive total only, as root
            # docs are absent from sections.
            if parts[0] == archive and len(parts) > 2:
                archive_counts[parts[1]] = archive_counts.get(parts[1], 0) + 1
        # Only directories that exist: a section the campaign has not created
        # yet is absent, not empty. Reporting it as 0 would present an unused
        # part of the layout as an emptied one.
        sections = {d: counts.get(d, 0) for d in self._sections()
                    if (self.ws.root / d).is_dir()}

        out: dict = {"name": cfg.name, "sections": sections}
        if (self.ws.root / archive).is_dir():
            out["archive_sections"] = archive_counts
```

- [ ] **Step 4: Run to verify they pass**

Run: `PYTHONPATH=src python3 -m unittest tests.test_store.TestOverview -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bunnyforge/_store.py tests/test_store.py
git commit -m "feat: campaign_overview archive_sections breakdown (#66)"
```

---

### Task 4: serve_mcp — thread `scope`, docstring guidance

**Files:**
- Modify: `src/bunnyforge/serve_mcp.py` (`campaign_overview:91`, `list_entities:103`, `search:116`)
- Test: `tests/test_serve_mcp.py` (add to `TestBuildServer:98`)

**Interfaces:**
- Consumes: `store.search(query, section, scope)`, `store.list_entities(section, scope)` (Tasks 1–2), `overview()`'s `archive_sections` key (Task 3).
- Produces: the MCP tool surface — `search(query, section=None, scope="both")`, `list_entities(section, scope="both")`. Docstrings are the condensed guidance (spec §4): they are part of the deliverable and of the Task 5 vocabulary read.

- [ ] **Step 1: Write the failing tests**

Add to `TestBuildServer` (async, `HAVE_MCP`-gated by the class decorator; they will SKIP locally and run in CI's mcp job — verify by inspection and CI, not by forcing a local venv):

```python
    async def test_search_and_list_entities_expose_scope(self):
        server = serve_mcp.build_server(scaffold(self))
        tools = {t.name: t for t in await server.list_tools()}
        for name in ("search", "list_entities"):
            scope = tools[name].inputSchema["properties"]["scope"]
            self.assertEqual(scope.get("default"), "both", name)

    async def test_scope_guidance_reaches_the_descriptions(self):
        # The description is the API the remote agent reads: it must name
        # the scope choices and say the scope is the GM's call to make.
        server = serve_mcp.build_server(scaffold(self))
        descs = {t.name: " ".join((t.description or "").split())
                 for t in await server.list_tools()}
        for name in ("search", "list_entities"):
            self.assertIn("scope", descs[name], name)
            self.assertIn("ask", descs[name], name)
        self.assertIn("archive_sections", descs["campaign_overview"])

    async def test_search_scope_live_excludes_archived_hits(self):
        store = scaffold(self)
        arch = store.ws.root / "Archive" / "NPCs"
        arch.mkdir(parents=True)
        (arch / "old.md").write_text(
            "---\ntitle: Old\nsummary: Retired.\n---\nShe knows the "
            "tides.\n", encoding="utf-8")
        server = serve_mcp.build_server(store)
        payload = await self._text(await server.call_tool(
            "search", {"query": "tides", "scope": "live"}))
        self.assertIn("kim-ha-eun", payload)
        self.assertNotIn("Archive/NPCs/old.md", payload)
```

- [ ] **Step 2: Run to verify state**

Run: `PYTHONPATH=src python3 -m unittest tests.test_serve_mcp.TestBuildServer -v`
Expected locally: the three new tests report SKIP (`mcp extra not installed`). That is the environment working as documented, not a pass — correctness lands with CI's mcp job in Task 6. If your environment does have the extra: they must FAIL now (no `scope` parameter yet) and pass after Step 3.

- [ ] **Step 3: Implement the tool layer**

Replace the three tool definitions in `build_server`:

```python
    @server.tool()
    def campaign_overview() -> dict:
        """Get your bearings in one call: the campaign's name, each section
        with how many entities it holds (the Archive count is the flat
        total; archive_sections breaks it down by mirrored section), the
        current front-burner and open-questions documents, and two
        counts — drafts_pending (your own unpromoted drafts; list_drafts
        to resume them) and inbound_pending (files in the GM's inbound
        queue). If inbound_pending is non-zero you may mention it and
        offer to extract; do not list or read the queue unless the GM
        asks. Call this before anything else."""
        return store.overview()

    @server.tool()
    def list_entities(section: str, scope: str = "both") -> list[dict]:
        """List one section's files with titles, one-line summaries, and
        an archived flag. section names the content section in either
        tree: the default scope="both" lists live and archived members
        together (section="NPCs" covers NPCs/ and Archive/NPCs/), while
        scope="live" or scope="archive" narrows to one tree. Use it to
        see what already exists before inventing something new —
        archived names are still taken. For creative work the scope is
        the GM's call: ask at task start if the request has not said
        (the AGENTS.md doctrine resource carries the rule)."""
        return store.list_entities(section, scope)

    @server.tool()
    def search(query: str, section: str | None = None,
               scope: str = "both") -> list[dict]:
        """Search the workspace for a phrase, returning each file that
        matches, the text around the match, and an archived flag. scope
        narrows retrieval to live canon ("live"), archived canon
        ("archive"), or both (default — every hit is labelled). Use it
        to check what has already been established about a name, place,
        or idea. For creative work the scope is the GM's call: ask at
        task start if the request has not said (the AGENTS.md doctrine
        resource carries the rule)."""
        return store.search(query, section, scope)
```

- [ ] **Step 4: Run the file's suite**

Run: `PYTHONPATH=src python3 -m unittest tests.test_serve_mcp -v`
Expected: no failures; the `HAVE_MCP` tests skip locally (CI's mcp job runs them in Task 6's PR).

- [ ] **Step 5: Commit**

```bash
git add src/bunnyforge/serve_mcp.py tests/test_serve_mcp.py
git commit -m "feat: serve-mcp threads scope; docstrings carry the scope guidance (#66)"
```

---

### Task 5: Doctrine — "Retrieval scope" section, then the human vocabulary read

**Files:**
- Modify: `src/bunnyforge/data/doctrine/AGENTS.md` (insert a new `##` section between "Never invent canon", which ends at line 217, and "## Speculative material stays speculative" at line 219)

No automated test asserts doctrine prose (deliberately — it is the GM's text, not the code's). The gates for this task are `test_init`'s manifest checks staying green (in-place edit, no manifest change) and the human read below.

- [ ] **Step 1: Insert the doctrine section**

After the "Never invent canon" bullet list (after line 217's end of section, before `## Speculative material stays speculative`), insert exactly:

```markdown
## Retrieval scope: live, archive, or both

- When answering questions or reporting what is established, read live and
  archived material freely. Results are labelled, and the rules above
  govern presentation: the archive is never current, and where it disagrees
  with a live file, the live file wins.
- Creative work on canon — inventing new material, or revising it later —
  runs under a retrieval scope I own. Drawing on retired material can be
  deliberate (a successor, an echo) or contamination (a "new" thing that
  quietly re-skins a retired one). Labels do not protect generation:
  material read is material that shapes the output. Only I can tell the
  two intents apart.
- So at the start of a task that will create or revise canon, ask me
  whether its retrieval should be live-only, archive-only, or both —
  unless my request already answers it, or the work's scope is already
  established. The scope attaches to the work and persists: picking a
  piece back up later continues under the scope it was made with. One ask
  per task; hold it until the task changes or I re-scope it.
- Mechanically: over MCP, pass `scope=` to `search` and `list_entities`;
  on the filesystem, read or skip `Archive/` accordingly.
```

- [ ] **Step 2: Verify the packaging gates**

Run: `PYTHONPATH=src python3 -m unittest tests.test_init tests.test_portability -v`
Expected: all PASS (in-place edit: manifest complete both ways; no structural markers in the new prose).

- [ ] **Step 3: Commit**

```bash
git add src/bunnyforge/data/doctrine/AGENTS.md
git commit -m "docs: doctrine — retrieval scope is the GM's call, asked at task start (#66)"
```

- [ ] **Step 4: CHECKPOINT — human vocabulary read (blocks the PR)**

Present to the GM, verbatim and in one place, every line of new prose this branch ships: the doctrine section above and the three tool docstrings from Task 4. Ask for an explicit read for campaign-specific vocabulary (setting coinages, character/place names, machine paths). **No automated check covers this** (#65 deferred; spec §7). Do not open the PR until the GM confirms the prose is clean or supplies replacements — apply any replacements and amend/commit before proceeding.

---

### Task 6: Full verification and PR

**Files:** none new — verification and delivery.

- [ ] **Step 1: Full suite from the worktree**

```bash
PYTHONPATH=src python3 -c "import bunnyforge; print(bunnyforge.__file__)"
PYTHONPATH=src python3 -m unittest discover -s tests -t .
```
Expected: the import path is inside THIS worktree; suite reports `OK` — baseline was `Ran 901 tests … OK (skipped=54)`, now more tests, same skip count.

- [ ] **Step 2: Fresh-workspace gate**

```bash
GATE=$(mktemp -d)
PYTHONPATH=src python3 -m bunnyforge init "$GATE/demo" --name Demo
PYTHONPATH=src python3 -m bunnyforge review checkup --workspace "$GATE/demo"
```
Expected: `Summary: 0 error(s), 0 warning(s)`.

- [ ] **Step 3: Repo hygiene**

```bash
git -C . status --porcelain
```
Expected: empty (no test wrote into the repo; nothing uncommitted).

- [ ] **Step 4: Push and open the PR**

Scan the outgoing diff for secrets if the gitleaks pre-push hook is unavailable. Then push the branch and open a PR against `main` **using the `dcltdw:opening-a-pr` skill** (required by the collaboration rules). The PR body must:
- link issue #66 and the spec (`docs/superpowers/specs/2026-08-18-scoped-retrieval-design.md`);
- state the #62-record revision (sectioned default listings now include labelled archived rows) so the reviewer sees it was deliberate;
- record that the Task 5 human vocabulary read happened and what it covered.

Wait for four green checks and the GM's approval — do not merge unprompted. On merge, use `dcltdw:cleaning-up-after-pr-merge`.
