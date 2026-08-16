# Ship the Visibility Colour Language in the Scaffold (#34) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans
> to implement this plan **inline** in the executing session. Two data files
> and a manifest edit do not amortize per-task subagent overhead. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** A fresh `bunnyforge init` workspace inherits the VS Code visibility
colour language's source-view half — shipped inert — via two new packaged
files under `data/vscode/`.

**Architecture:** Two authored data files (`data/vscode/settings.json`,
`data/vscode/extensions.json`) join `init.py`'s MANIFEST as `canonical=None`
entries, exactly like `root/gitignore`. The settings file carries the managed
block between bunnyforge marker comments, fully disabled with a reserved
`//- ` line prefix, so bunnyforge#33's `vscode on`/`off` can toggle it later
without a JSONC parser. `init` gains one line of output pointing at the file.

**Tech Stack:** Python ≥3.11 stdlib only; `unittest`; no new dependencies.

**Spec:** https://github.com/dcltdw/bunnyforge/issues/34 (deliverable and
scope) and the cross-ticket contract recorded below — #33
(https://github.com/dcltdw/bunnyforge/issues/33) consumes this ticket's marker
strings and off-prefix byte-for-byte, so they are frozen here.

## Global Constraints

- **Stdlib only**, Python ≥3.11 (`pyproject.toml: requires-python = ">=3.11"`).
- **Campaign-neutral:** no private campaign's name may appear in any packaged
  file; the existing portability tests must stay green.
- **Ships inert:** every line between the markers must be a comment; a
  scaffolded workspace must render identically to one without these files
  until a user acts.
- **No recommendation for the preview extension** in `extensions.json` — it is
  not on the VS Code Marketplace, so the entry could never resolve. Its id may
  appear **only inside comments**.
- **Command-neutral wording:** nothing user-facing in this PR names
  `bunnyforge vscode` — that command does not exist until #33. Point at the
  file, not the command. (Code comments may reference issue numbers.)
- Branch off current `main`; never commit to `main`; PR body per AGENTS.md
  (files changed annotated new/modified, work breakdown, provenance); every
  commit carries a `Co-Authored-By:` trailer for the executing model.
- Test invocations: single module `python3 -m unittest tests.test_init -v`;
  full suite `python3 -m unittest discover -s tests -t . -v`. If imports fail,
  the package needs `python3 -m pip install -e .` first.

## The cross-ticket contract (frozen by this PR)

#33 will parse these bytes forever. Decided 2026-08-15 with both tickets in
view; do not adjust them here without flagging it as a design change.

1. **Marker lines** — full-line JSONC comments on their own lines, matched by
   exact string equality after stripping surrounding whitespace:
   - begin: `// bunnyforge:begin visibility-colouring`
   - end: `// bunnyforge:end visibility-colouring`
   Exactly one of each, begin before end. Human-facing prose lives in ordinary
   comment lines *above* the begin marker, never in the marker line itself.
2. **Off-state encoding** — a disabled line is
   `original-indent + "//- " + original-body`. The `//- ` prefix (slash,
   slash, hyphen, space) is reserved for the toggle; ordinary comments use
   plain `// `. Enabling = deleting the prefix; the original indentation is
   preserved because the prefix sits *after* the leading whitespace.
3. **Region placement** — the managed region comes **first** in the settings
   object; the `markdown.preview.frontMatter` pin follows it. The disabled
   active block ends `//- },` (comma included) so that the enabled file is
   strict-JSON-valid with the pin after it, and the off file is
   strict-JSON-valid because the pin (last member) has no trailing comma.
4. **The pin stays outside the region** — it serves the preview half, whose
   off is "extension not installed"; `vscode off` must never remove it.

---

### Task 1: The two data files, their MANIFEST entries, and the contract tests

**Files:**
- Create: `src/bunnyforge/data/vscode/settings.json`
- Create: `src/bunnyforge/data/vscode/extensions.json`
- Modify: `src/bunnyforge/init.py` (MANIFEST, after the `root/gitignore` entry)
- Test: `tests/test_init.py` (new class `TestVscodeScaffold`)

**Interfaces:**
- Consumes: `init.packaged_bytes(resource)`, `init.MANIFEST`, the `Packaged`
  namedtuple — all existing.
- Produces: the packaged files at resources `vscode/settings.json` and
  `vscode/extensions.json`, destinations `.vscode/settings.json` and
  `.vscode/extensions.json`. #33 depends on the marker strings, the `//- `
  prefix, and the file being byte-for-byte what `enable/disable` round-trips.

- [ ] **Step 1: Branch off current main**

```bash
cd ~/Github/bunnyforge
git checkout main && git pull
git checkout -b feat/34-vscode-scaffold
git branch --show-current   # confirm: feat/34-vscode-scaffold
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_init.py` (module already imports `json`? It does not —
add `import json` to its imports):

```python
# The cross-ticket contract with the `bunnyforge vscode` command (#33):
# these strings are frozen — #33 parses them. Hardcoded here because the
# constants live in vscode.py, which does not exist until #33; that ticket
# adds a drift test binding its constants to these packaged bytes.
VSCODE_MARKER_BEGIN = "// bunnyforge:begin visibility-colouring"
VSCODE_MARKER_END = "// bunnyforge:end visibility-colouring"
VSCODE_OFF_PREFIX = "//- "


class TestVscodeScaffold(unittest.TestCase):
    """The packaged .vscode/ files: inert on arrival, valid JSONC in both
    toggle states, and never recommending an extension that cannot resolve.

    These tests deliberately do NOT pin the comment prose — #33 rewords the
    headers to name the `bunnyforge vscode` command once it exists, and that
    must not break this suite.
    """

    def _settings_lines(self) -> list[str]:
        return (init.packaged_bytes("vscode/settings.json")
                .decode("utf-8").split("\n"))

    def test_settings_carries_exactly_one_marker_pair_in_order(self):
        stripped = [l.strip() for l in self._settings_lines()]
        self.assertEqual(stripped.count(VSCODE_MARKER_BEGIN), 1)
        self.assertEqual(stripped.count(VSCODE_MARKER_END), 1)
        self.assertLess(stripped.index(VSCODE_MARKER_BEGIN),
                        stripped.index(VSCODE_MARKER_END))

    def test_the_managed_region_ships_fully_inert(self):
        stripped = [l.strip() for l in self._settings_lines()]
        begin = stripped.index(VSCODE_MARKER_BEGIN)
        end = stripped.index(VSCODE_MARKER_END)
        region = [l for l in stripped[begin + 1:end] if l]
        self.assertTrue(region, "managed region is empty")
        for line in region:
            self.assertTrue(line.startswith("//"),
                            f"live line inside the shipped region: {line!r}")
        self.assertTrue(
            any(l.startswith(VSCODE_OFF_PREFIX) for l in region),
            "no //-  disabled block — nothing for `vscode on` to enable")

    def _as_json(self, *, enabled: bool):
        """The file as strict JSON: comments dropped, //-  lines optionally
        re-enabled first — simulating exactly what #33's toggle does."""
        kept = []
        for raw in self._settings_lines():
            indent = raw[:len(raw) - len(raw.lstrip())]
            body = raw.strip()
            if enabled and body.startswith(VSCODE_OFF_PREFIX):
                kept.append(indent + body[len(VSCODE_OFF_PREFIX):])
            elif not body.startswith("//"):
                kept.append(raw)
        return json.loads("\n".join(kept))

    def test_settings_is_strict_json_with_the_block_off(self):
        self.assertEqual(self._as_json(enabled=False),
                         {"markdown.preview.frontMatter": "table"})

    def test_settings_is_strict_json_with_the_block_enabled(self):
        data = self._as_json(enabled=True)
        self.assertEqual(data["markdown.preview.frontMatter"], "table")
        self.assertEqual(set(data["highlight.regexes"]), {
            r"^(visibility:\s*gm-only\s*)$",
            r"^(visibility:\s*player-visible\s*)$",
            r"^(visibility:\s*mixed\s*)$",
            r"^(## GM notes\s*)$",
            r"^(reveal_when:.*)$",
        })
        for rule in data["highlight.regexes"].values():
            self.assertEqual(rule["filterLanguageRegex"], "markdown")

    def test_extensions_recommends_only_the_marketplace_extension(self):
        lines = (init.packaged_bytes("vscode/extensions.json")
                 .decode("utf-8").split("\n"))
        data = json.loads("\n".join(
            l for l in lines if not l.strip().startswith("//")))
        self.assertEqual(
            data, {"recommendations": ["fabiospampinato.vscode-highlight"]})

    def test_the_preview_extension_appears_only_in_comments(self):
        # It is not on the Marketplace; a recommendation entry could never
        # resolve, so its id must never appear on a live line.
        for resource in ("vscode/settings.json", "vscode/extensions.json"):
            for line in (init.packaged_bytes(resource)
                         .decode("utf-8").split("\n")):
                if "bunnyforge-visibility-preview" in line:
                    self.assertTrue(
                        line.strip().startswith("//"),
                        f"{resource}: live reference to the unlisted "
                        f"extension: {line!r}")
```

- [ ] **Step 3: Run the new tests to verify they fail**

Run: `python3 -m unittest tests.test_init.TestVscodeScaffold -v`
Expected: FAIL/ERROR — `FileNotFoundError` from `packaged_bytes` (the data
files do not exist yet).

- [ ] **Step 4: Create `src/bunnyforge/data/vscode/settings.json`**

Exact content. Note the `//- ` prefix always sits *after* the line's original
indentation (contract item 2), and the disabled active block ends `//- },`
(contract item 3):

```jsonc
{
  // ── Visibility colouring ────────────────────────────────────────────
  // Colours workspace .md files by their front-matter `visibility`
  // (see AGENTS.md -> Player visibility). Rendered by the
  // fabiospampinato.vscode-highlight extension (see extensions.json).
  //
  // Hue roles (constant in every palette): red = gm-only and the
  // `## GM notes` boundary, green = player-visible, cyan = mixed.
  // Each rule carries "dark" and "light" variants; VS Code applies the
  // half matching the current theme automatically.
  //
  // Two axes:
  //   mode      dark | light      — automatic, via the theme
  //   contrast  high | saturated | subtle
  //
  // The block between the two bunnyforge marker comments below is
  // managed; the marker lines themselves must not be edited. The block
  // ships OFF: every disabled line starts with "//- " — a prefix
  // reserved for the toggle; ordinary comments use plain "//". To turn
  // colouring on, delete every "//- " prefix. ACTIVE LEVEL: high; to
  // switch, re-disable the high block and enable one alternate below.
  // bunnyforge:begin visibility-colouring
  //- "highlight.regexes": {
    //- "^(visibility:\\s*gm-only\\s*)$": {
      //- "regexFlags": "gm",
      //- "filterLanguageRegex": "markdown",
      //- "decorations": [{
        //- "isWholeLine": true,
        //- "dark":  { "backgroundColor": "#ff3333", "color": "#000000" },
        //- "light": { "backgroundColor": "#b91c1c", "color": "#ffffff" }
      //- }]
    //- },
    //- "^(visibility:\\s*player-visible\\s*)$": {
      //- "regexFlags": "gm",
      //- "filterLanguageRegex": "markdown",
      //- "decorations": [{
        //- "isWholeLine": true,
        //- "dark":  { "backgroundColor": "#00ff00", "color": "#000000" },
        //- "light": { "backgroundColor": "#15803d", "color": "#ffffff" }
      //- }]
    //- },
    //- "^(visibility:\\s*mixed\\s*)$": {
      //- "regexFlags": "gm",
      //- "filterLanguageRegex": "markdown",
      //- "decorations": [{
        //- "isWholeLine": true,
        //- "dark":  { "backgroundColor": "#00ffff", "color": "#000000" },
        //- "light": { "backgroundColor": "#0e7490", "color": "#ffffff" }
      //- }]
    //- },
    //- "^(## GM notes\\s*)$": {
      //- "regexFlags": "gm",
      //- "filterLanguageRegex": "markdown",
      //- "decorations": [{
        //- "isWholeLine": true,
        //- "dark":  { "backgroundColor": "#ff3333", "color": "#000000" },
        //- "light": { "backgroundColor": "#b91c1c", "color": "#ffffff" }
      //- }]
    //- },
    //- "^(reveal_when:.*)$": {
      //- "regexFlags": "gm",
      //- "filterLanguageRegex": "markdown",
      //- "decorations": [{
        //- "isWholeLine": true,
        //- "fontStyle": "italic",
        //- "dark":  { "color": "#8a8a8a" },
        //- "light": { "color": "#777777" }
      //- }]
    //- }
  //- },
  // ── ALTERNATE: saturated ───────────────────────────────────────────
  // "highlight.regexes": {
  //   "^(visibility:\\s*gm-only\\s*)$": { "regexFlags": "gm", "filterLanguageRegex": "markdown",
  //     "decorations": [{ "isWholeLine": true,
  //       "dark":  { "backgroundColor": "#ef4444", "color": "#000000" },
  //       "light": { "backgroundColor": "#fca5a5", "color": "#000000",
  //                  "borderStyle": "solid", "borderColor": "#dc2626", "borderWidth": "0 0 0 3px" } }] },
  //   "^(visibility:\\s*player-visible\\s*)$": { "regexFlags": "gm", "filterLanguageRegex": "markdown",
  //     "decorations": [{ "isWholeLine": true,
  //       "dark":  { "backgroundColor": "#22c55e", "color": "#000000" },
  //       "light": { "backgroundColor": "#86efac", "color": "#000000",
  //                  "borderStyle": "solid", "borderColor": "#16a34a", "borderWidth": "0 0 0 3px" } }] },
  //   "^(visibility:\\s*mixed\\s*)$": { "regexFlags": "gm", "filterLanguageRegex": "markdown",
  //     "decorations": [{ "isWholeLine": true,
  //       "dark":  { "backgroundColor": "#06b6d4", "color": "#000000" },
  //       "light": { "backgroundColor": "#67e8f9", "color": "#000000",
  //                  "borderStyle": "solid", "borderColor": "#0891b2", "borderWidth": "0 0 0 3px" } }] },
  //   "^(## GM notes\\s*)$": { "regexFlags": "gm", "filterLanguageRegex": "markdown",
  //     "decorations": [{ "isWholeLine": true,
  //       "dark":  { "backgroundColor": "#ef4444", "color": "#000000" },
  //       "light": { "backgroundColor": "#fca5a5", "color": "#000000",
  //                  "borderStyle": "solid", "borderColor": "#dc2626", "borderWidth": "0 0 0 3px" } }] },
  //   "^(reveal_when:.*)$": { "regexFlags": "gm", "filterLanguageRegex": "markdown",
  //     "decorations": [{ "isWholeLine": true, "fontStyle": "italic",
  //       "dark": { "color": "#8a8a8a" }, "light": { "color": "#777777" } }] }
  // }
  // ── ALTERNATE: subtle ──────────────────────────────────────────────
  // "highlight.regexes": {
  //   "^(visibility:\\s*gm-only\\s*)$": { "regexFlags": "gm", "filterLanguageRegex": "markdown",
  //     "decorations": [{ "isWholeLine": true,
  //       "dark":  { "backgroundColor": "#513333", "color": "#e6d6d6" },
  //       "light": { "backgroundColor": "rgba(185,28,28,0.14)",
  //                  "borderStyle": "solid", "borderColor": "rgba(185,28,28,0.8)", "borderWidth": "0 0 0 3px" } }] },
  //   "^(visibility:\\s*player-visible\\s*)$": { "regexFlags": "gm", "filterLanguageRegex": "markdown",
  //     "decorations": [{ "isWholeLine": true,
  //       "dark":  { "backgroundColor": "#31463a", "color": "#d8e4dc" },
  //       "light": { "backgroundColor": "rgba(21,128,61,0.12)",
  //                  "borderStyle": "solid", "borderColor": "rgba(21,128,61,0.8)", "borderWidth": "0 0 0 3px" } }] },
  //   "^(visibility:\\s*mixed\\s*)$": { "regexFlags": "gm", "filterLanguageRegex": "markdown",
  //     "decorations": [{ "isWholeLine": true,
  //       "dark":  { "backgroundColor": "#2f4a4e", "color": "#d5e4e6" },
  //       "light": { "backgroundColor": "rgba(14,116,144,0.12)",
  //                  "borderStyle": "solid", "borderColor": "rgba(14,116,144,0.8)", "borderWidth": "0 0 0 3px" } }] },
  //   "^(## GM notes\\s*)$": { "regexFlags": "gm", "filterLanguageRegex": "markdown",
  //     "decorations": [{ "isWholeLine": true,
  //       "dark":  { "backgroundColor": "#513333", "color": "#e6d6d6" },
  //       "light": { "backgroundColor": "rgba(185,28,28,0.14)",
  //                  "borderStyle": "solid", "borderColor": "rgba(185,28,28,0.8)", "borderWidth": "0 0 0 3px" } }] },
  //   "^(reveal_when:.*)$": { "regexFlags": "gm", "filterLanguageRegex": "markdown",
  //     "decorations": [{ "isWholeLine": true, "fontStyle": "italic",
  //       "dark": { "color": "#8a8a8a" }, "light": { "color": "#777777" } }] }
  // }
  // bunnyforge:end visibility-colouring

  // ── Markdown preview ────────────────────────────────────────────────
  // The preview half of the visibility colouring: the
  // dcltdw.bunnyforge-visibility-preview extension (see extensions.json
  // for how to install it) decorates the front-matter table the preview
  // renders. Pinned to "table" so a user-level "hide" or an upstream
  // default change cannot silently remove the table the decorator needs.
  // Deliberately OUTSIDE the managed block: it belongs to the preview
  // half, and turning source-view colouring off must not remove it.
  "markdown.preview.frontMatter": "table"
}
```

- [ ] **Step 5: Create `src/bunnyforge/data/vscode/extensions.json`**

Exact content:

```jsonc
{
  // The visibility line-highlighting in settings.json is rendered by
  // this extension. Without it installed, files simply render plain.
  //
  // The markdown-preview half of the same colour language lives in
  // dcltdw.bunnyforge-visibility-preview. It is deliberately NOT listed
  // below: it is not on the VS Code Marketplace (publishing there now
  // requires an Azure DevOps org linked to an active Azure
  // subscription), so a recommendation entry could never resolve.
  // Install it from its GitHub releases instead —
  //   https://github.com/dcltdw/bunnyforge-visibility-preview/releases/latest
  //   code --install-extension <downloaded .vsix file>
  // It is optional: absent, the preview renders the plain front-matter
  // table.
  "recommendations": ["fabiospampinato.vscode-highlight"]
}
```

- [ ] **Step 6: Add the two MANIFEST entries**

In `src/bunnyforge/init.py`, immediately after the
`Packaged("root/gitignore", ".gitignore", None, False),` line:

```python
    # The VS Code visibility colour language, source-view half (#34).
    # Ships INERT: the managed block is disabled with "//- " prefixes;
    # `bunnyforge vscode` (#33) toggles it between the marker comments.
    # canonical=None: authored stubs, no in-repo canonical source.
    Packaged("vscode/settings.json", ".vscode/settings.json", None, False),
    Packaged("vscode/extensions.json", ".vscode/extensions.json", None, False),
```

- [ ] **Step 7: Run the new tests to verify they pass**

Run: `python3 -m unittest tests.test_init.TestVscodeScaffold -v`
Expected: PASS (all 6).

- [ ] **Step 8: Run the whole init suite**

Run: `python3 -m unittest tests.test_init -v`
Expected: PASS. This is load-bearing: the existing manifest tests
(`test_every_manifest_resource_is_a_real_packaged_file`,
`test_every_packaged_file_is_named_by_the_manifest`,
`test_manifest_destinations_are_unique`,
`test_init_output_is_byte_identical_to_its_data_sources`,
`test_writes_every_manifest_destination_and_nothing_else`) now cover the new
entries automatically, and `TestFreshWorkspacePassesTheGate` proves the
scaffolded `.vscode/` does not disturb the checkup 0/0 gate. If checkup DOES
flag `.vscode/` files, stop and report — that is a design problem to surface,
not to paper over.

- [ ] **Step 9: Commit**

```bash
git add src/bunnyforge/data/vscode/ src/bunnyforge/init.py tests/test_init.py
git commit -m "feat: scaffold the VS Code visibility colouring, inert (#34)"
```
(Include the executing model's `Co-Authored-By:` trailer.)

---

### Task 2: The one-line pointer in init's output

**Files:**
- Modify: `src/bunnyforge/init.py` (the success prints in `main`)
- Test: `tests/test_init.py` (one test in `TestWhatInitWrites`)

**Interfaces:**
- Consumes: `init.main(argv)` — existing.
- Produces: one stdout line containing `.vscode/settings.json`. #33 rewords
  this line to name `bunnyforge vscode setup` and updates this test.

- [ ] **Step 1: Write the failing test**

Add to `TestWhatInitWrites` in `tests/test_init.py`:

```python
    def test_points_at_the_inert_vscode_scaffold_once(self):
        # One line, not a paragraph (#34) — and command-neutral: the
        # `bunnyforge vscode` command does not exist until #33.
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(
                init.main([str(tmp / "new"), "--name", "X"]), 0)
        pointing = [l for l in out.getvalue().splitlines()
                    if ".vscode/settings.json" in l]
        self.assertEqual(len(pointing), 1, out.getvalue())
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest tests.test_init.TestWhatInitWrites.test_points_at_the_inert_vscode_scaffold_once -v`
Expected: FAIL — 0 matching lines.

- [ ] **Step 3: Add the line to `init.main`**

In `src/bunnyforge/init.py`, between the existing "Created campaign
workspace" print and the "Next:" print:

```python
    print(f"Created campaign workspace {path} — {len(written)} files "
          f"(name {args.name!r}, namespace {namespace!r}).")
    print("Optional: VS Code colouring by visibility ships off — "
          "see .vscode/settings.json.")
    print(f"Next: cd {path} && bunnyforge review checkup")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m unittest tests.test_init -v`
Expected: PASS (the whole module, to catch any output-shape assumptions).

- [ ] **Step 5: Commit**

```bash
git add src/bunnyforge/init.py tests/test_init.py
git commit -m "feat: init points at the inert VS Code scaffold (#34)"
```

---

### Task 3: Verification and PR

- [ ] **Step 1: Full suite**

Run: `python3 -m unittest discover -s tests -t . -v`
Expected: PASS, including the portability/campaign-term checks. Report the
actual counts; do not summarize a run you have not watched complete.

- [ ] **Step 2: Manual smoke of the scaffold**

```bash
cd "$(mktemp -d)"
python3 -m bunnyforge.init demo --name "Demo"
cat demo/.vscode/settings.json demo/.vscode/extensions.json
```
Expected: init reports the file count (two higher than before), prints the
new Optional line once, and the two files match the plan's content.

- [ ] **Step 3: Push and open the PR**

```bash
git push -u origin feat/34-vscode-scaffold
```

Open a PR **based on `main`** (state that explicitly in the report to the
user). Title: `Ship the visibility colour language in the scaffold, inert
(#34)`. Body sections per AGENTS.md:
- **Files changed** — `src/bunnyforge/data/vscode/settings.json` (new),
  `src/bunnyforge/data/vscode/extensions.json` (new),
  `src/bunnyforge/init.py` (modified), `tests/test_init.py` (modified),
  `docs/superpowers/plans/2026-08-15-vscode-scaffold-files.md` (new, this plan).
- **Work breakdown** — what shipped and why inert; name the frozen contract
  (markers, `//- ` prefix, region-first placement) and that #33 consumes it.
- **Provenance** — `Agent:` and `Model / version:` of the executing session.

Then **stop and wait for review** — do not merge.

## Out of scope (resist)

- The `bunnyforge vscode` command, and any wording that names it — #33.
- Any change to existing workspaces (init refuses non-empty directories by
  design; #33's `on` handles retrofit).
- Decorating further front-matter fields; the wiki tint half.
- A version bump/release — the maintainer decides release timing.
