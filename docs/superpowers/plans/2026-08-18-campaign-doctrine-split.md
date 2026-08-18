# Campaign Doctrine Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the workspace's `AGENTS.md` into a package-owned half that can be replaced wholesale and a new GM-owned `campaign-doctrine.md`, so adopting new doctrine becomes a file copy instead of a merge.

**Architecture:** `AGENTS.md` stays exactly what it is — generic, packaged, byte-identical in every workspace. A new authored stub, `campaign-doctrine.md`, lands beside it at the workspace root in the same MANIFEST class as the existing root stubs (`canonical=None`, so no drift guard ever tracks it). The packaged `AGENTS.md` points at it from its **Read order** and states the precedence rule. Three consumers reach it three ways: Claude Code through the existing `@AGENTS.md` import chain and the Read order, the MCP agent through a fourth entry in `DOCTRINE_FILES`, and any other agent through the same prose Read order the other five root docs already rely on. Nothing in bunnyforge parses `AGENTS.md`; the pointer is prose, and what the tests enforce is that the pointer exists and its target resolves.

**Tech Stack:** Python ≥ 3.11, stdlib only. `unittest` (run via `python3 -m unittest discover -s tests -t . -v`). The MCP half needs the `mcp` extra (`pip install -e '.[mcp]'`).

**Spec:** https://github.com/dcltdw/bunnyforge/issues/32#issuecomment-5329315062 — the analysis comment on issue #32. Read it before Task 1; it carries the measurements every decision below rests on.

## Global Constraints

- **Package is stdlib-only at runtime.** No new dependency may be added by this work.
- **Python ≥ 3.11.**
- **The file is named `campaign-doctrine.md`** and is referenced as `[[campaign-doctrine]]`. Decided; do not rename it mid-implementation — it becomes a wikilink target inside packaged doctrine the moment it ships.
- **The fresh-workspace gate must stay green:** `bunnyforge init` followed by `bunnyforge review checkup` reports `Summary: 0 error(s), 0 warning(s).` (`tests/test_init.py::TestFreshWorkspacePassesTheGate`, and a separate CI step).
- **No test may write into the repo.** CI has an explicit "No test wrote into the repo" step. Every test scaffolds into `tempfile.TemporaryDirectory()`.
- **Work on a branch; never commit to `main`.** `main` is ruleset-protected and needs a PR plus four green checks.
- **Every commit carries a `Co-Authored-By:` trailer naming the AI model.**
- **`campaign-doctrine.md` has `canonical=None`.** It is an authored stub like `ROOT_STUBS`, not a copy of anything. Giving it a canonical would put it back under the drift guard, which is the exact thing this work exists to get it out from under.
- **Do not build `bunnyforge doctrine adopt`, `--check`, or any migration subcommand.** The analysis concluded both are unnecessary after the split. The migration is a written recipe run once.

---

### Task 1: Package the `campaign-doctrine.md` stub and land it at the workspace root

**Files:**
- Create: `src/bunnyforge/data/root/campaign-doctrine.md`
- Modify: `src/bunnyforge/init.py:75-76` (the `ROOT_STUBS` tuple)
- Test: `tests/test_init.py` (add to the class containing `test_does_not_write_reanchor_txt`, around line 455)

**Interfaces:**
- Consumes: `init.packaged_bytes(resource: str) -> bytes`, `init.MANIFEST`, the module-level `ROOT_STUBS` tuple.
- Produces: the packaged resource path `"root/campaign-doctrine.md"` and the workspace-root destination `"campaign-doctrine.md"`. Tasks 2, 3, 4 and 5 all refer to those two exact strings.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_init.py`, immediately after `test_does_not_write_reanchor_txt`:

```python
    def test_writes_the_campaign_doctrine_stub(self):
        # The GM-owned half of the doctrine split (#32). It lands like the
        # other root stubs -- authored, canonical=None -- because no packaged
        # version of it may ever overwrite what a campaign writes there. That
        # is the whole point: AGENTS.md becomes replaceable only once there is
        # somewhere else for campaign-specific rules to live.
        stub = _scaffold(self) / "campaign-doctrine.md"
        self.assertTrue(stub.is_file())
        self.assertEqual(stub.read_bytes(),
                         init.packaged_bytes("root/campaign-doctrine.md"))
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest tests.test_init -k campaign_doctrine_stub -v`

Expected: FAIL. The assertion on `stub.is_file()` fails, or `packaged_bytes` raises `FileNotFoundError` — either is the right red, because neither the packaged file nor the manifest entry exists yet.

- [ ] **Step 3: Create the packaged stub**

Create `src/bunnyforge/data/root/campaign-doctrine.md` with exactly this content. It follows the house style of the other root stubs (`data/root/out-of-game.md`): prose that says what the file is for, then headings whose HTML-comment prompts interview the GM.

```markdown
# Campaign Doctrine

Rules that apply to *this* campaign and no other. `[[AGENTS]]` is the generic
agent contract: the bunnyforge package owns it, ships it identically to every
workspace, and replaces it wholesale when you adopt a new version — so
anything campaign-specific written into it is lost on the next adoption. This
file is the other half, and it is yours. No packaged version of it will ever
overwrite what you write here.

Where a rule below contradicts `[[AGENTS]]`, this file wins — but say so in
the rule itself, naming the generic rule it displaces, so an exception is
visible from both sides rather than inferred.

An agent that finds this file empty should carry on with `[[AGENTS]]`
unchanged. Nothing here is required.

## Subtrees with their own rules

<!-- Directories that do not follow the workspace's normal conventions: a
     conlang enclave, an imported ruleset, anything with its own file format
     or its own checker. Say what stops applying, and what applies instead. -->

## Exemptions from the generic contract

<!-- Places where a rule in AGENTS.md does not hold here. Name the rule, say
     how it changes, and say why. An exemption nobody wrote a reason for gets
     re-litigated every few months. -->

## Extra tools and checks

<!-- Commands this campaign runs that bunnyforge does not ship: campaign
     tests, custom checkers, scripts an agent should run before saying
     something is done. -->
```

- [ ] **Step 4: Add the manifest entry**

In `src/bunnyforge/init.py`, extend `ROOT_STUBS` (currently lines 75-76) and its comment:

```python
# The root docs with no canonical in-repo source: the in-repo copies are live
# campaign state rather than doctrine, so these are authored generically for
# data/root/ instead. campaign-doctrine.md is here for the opposite reason --
# it is the GM-owned half of the doctrine split, and a canonical would put it
# back under the drift guard the split exists to get it out from under.
ROOT_STUBS = ("campaign-doctrine.md", "compendium.md", "front-burner.md",
              "open-questions.md", "out-of-game.md", "tickets.md")
```

No change to `MANIFEST` itself is needed — line 89 already expands `ROOT_STUBS` into `Packaged(f"root/{name}", name, None, False)` entries.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_init -v`

Expected: PASS, including `test_writes_the_campaign_doctrine_stub` and both directions of `TestPackagedDataMatchesItsCanonical` (the second direction — "every packaged file must be named by the manifest" — is what would have caught a `data/root/` file added without the `ROOT_STUBS` entry).

- [ ] **Step 6: Commit**

```bash
git add src/bunnyforge/data/root/campaign-doctrine.md src/bunnyforge/init.py tests/test_init.py
git commit -m "feat: scaffold campaign-doctrine.md, the GM-owned half of the doctrine split"
```

---

### Task 2: Make it a configured root doc

Root docs are what `_common.iter_content_files` walks and what `review.check_wikilinks` accepts as link targets (`src/bunnyforge/_common.py:111`). Until `campaign-doctrine.md` is in that list, Task 3's `[[campaign-doctrine]]` link is a broken wikilink and the 0/0 gate fails. This task must land before Task 3.

**Files:**
- Modify: `src/bunnyforge/_config.py:116-118` (`_DEFAULTS["root_docs"]`)
- Modify: `src/bunnyforge/data/campaign.toml.in:31-33` (the commented example)
- Test: `tests/test_init.py`, class `TestGeneratedConfig` (around line 462)

**Interfaces:**
- Consumes: `init.packaged_bytes("campaign.toml.in")`, `_config._DEFAULTS`.
- Produces: `"campaign-doctrine.md"` present in `_config._DEFAULTS["root_docs"]`. Task 3's wikilink test depends on this, because `tests/test_init.py::_root_doc_only_workspace` builds its probe workspace from exactly that list.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_init.py`, inside `class TestGeneratedConfig`:

```python
    def test_the_commented_root_docs_example_names_every_default(self):
        # campaign.toml.in teaches what is overridable by showing each default
        # commented out. That is a second copy of _DEFAULTS, and the class's
        # docstring is right that a second copy is a second thing to drift --
        # so guard the one list this change touches rather than trusting it.
        template = init.packaged_bytes("campaign.toml.in").decode("utf-8")
        for doc in _config._DEFAULTS["root_docs"]:
            with self.subTest(doc=doc):
                self.assertIn(f'"{doc}"', template)
```

- [ ] **Step 2: Run the test to verify it passes, then break it deliberately**

Run: `python3 -m unittest tests.test_init -k commented_root_docs -v`

Expected: PASS. This test is green against today's code — it is a guard being installed *before* the change that needs it, which is the right order. Confirm it can fail by temporarily adding `"nope.md"` to `_config._DEFAULTS["root_docs"]`, re-running (expect FAIL naming `nope.md`), then removing it. A guard you have not watched fail is not yet evidence that it can.

- [ ] **Step 3: Add the doc to the defaults**

In `src/bunnyforge/_config.py`, replace lines 116-118:

```python
    "root_docs": ["AGENTS.md", "campaign-doctrine.md", "compendium.md",
                  "front-burner.md", "open-questions.md", "out-of-game.md",
                  "situation-design.md", "style-guide.md", "tickets.md"],
```

- [ ] **Step 4: Update the commented example to match**

In `src/bunnyforge/data/campaign.toml.in`, replace lines 31-33:

```
# root_docs       = ["AGENTS.md", "campaign-doctrine.md", "compendium.md",
#                    "front-burner.md", "open-questions.md", "out-of-game.md",
#                    "situation-design.md", "style-guide.md", "tickets.md"]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_init -v`

Expected: PASS. `test_every_defaultable_key_equals_its_default` picks up the new default automatically; `test_the_commented_root_docs_example_names_every_default` now covers the new entry; `TestFreshWorkspacePassesTheGate` still reports 0/0 because Task 1 scaffolds the file that the new root-doc entry names.

- [ ] **Step 6: Commit**

```bash
git add src/bunnyforge/_config.py src/bunnyforge/data/campaign.toml.in tests/test_init.py
git commit -m "feat: campaign-doctrine.md is a root doc, so wikilinks can reach it"
```

---

### Task 3: Point the packaged doctrine at it

**Files:**
- Modify: `src/bunnyforge/data/doctrine/AGENTS.md:16-27` (the Read order list) and insert a new section immediately before it
- Test: `tests/test_init.py`, class `TestPackagedDoctrineIsPortable` (around line 51)

**Interfaces:**
- Consumes: `init.packaged_bytes("doctrine/AGENTS.md")`; `campaign-doctrine.md` present in `_config._DEFAULTS["root_docs"]` from Task 2.
- Produces: the literal string `[[campaign-doctrine]]` inside the `## Read order` section of the packaged `AGENTS.md`. Nothing downstream reads this programmatically — the test is the contract.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_init.py`, inside `class TestPackagedDoctrineIsPortable`:

```python
    def test_the_read_order_points_at_campaign_doctrine(self):
        # The include is prose, not an import: nothing can force an agent to
        # follow it, and the five root docs already in this list rest on the
        # same footing. What IS enforceable is that the pointer exists and
        # that its target resolves -- the second half is the wikilink test
        # above, which is why both live in this class.
        doctrine = init.packaged_bytes("doctrine/AGENTS.md").decode("utf-8")
        self.assertIn("## Read order", doctrine)
        read_order = doctrine.split("## Read order", 1)[1].split("\n## ", 1)[0]
        self.assertIn("[[campaign-doctrine]]", read_order,
                      "AGENTS.md no longer tells an agent to read the "
                      "campaign-owned half; the split is inert without it")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest tests.test_init -k read_order_points -v`

Expected: FAIL — `'[[campaign-doctrine]]' not found in` the Read order block, with the message about the split being inert.

- [ ] **Step 3: Add the ownership section and the Read order entry**

In `src/bunnyforge/data/doctrine/AGENTS.md`, insert this new section between the intro block (which ends at line 14 with the `_Ignore/` sentence) and `## Read order`:

```markdown
## This file and `[[campaign-doctrine]]`

This file is generic. The bunnyforge package owns it, ships it identically to
every workspace, and replaces it wholesale when a new version is adopted — so
anything written into it that is true of this campaign only will be lost.
`[[campaign-doctrine]]` is the other half: campaign-specific rules, owned by
me, never overwritten.

Where the two disagree, `[[campaign-doctrine]]` wins. It is required to name
the rule here that it displaces, so an exception is visible from both sides
rather than inferred.
```

Then replace the numbered list at lines 18-27 with:

```markdown
At the start of any working session, read in this order:

1. `[[campaign-doctrine]]` — this campaign's own rules. First, because it can
   override anything in this file, and it says so where it does.
2. `[[front-burner]]` — current state. Outranks every older file on any conflict.
3. `[[compendium]]` — the index. Use it to find what else is relevant.
4. `[[style-guide]]` — binding constraints on tone and voice.
5. `[[situation-design]]` — how prep material is structured. Read before
   building any scenario, NPC, or faction material.
6. `[[open-questions]]` — what is deliberately undecided.

Then read the entity files relevant to the task at hand.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_init -v`

Expected: PASS. Two tests matter here and both are pre-existing: `test_agents_md_wikilinks_resolve_with_only_root_docs` proves `[[campaign-doctrine]]` resolves in a workspace holding nothing but root docs, and `TestFreshWorkspacePassesTheGate::test_checkup_reports_no_errors_and_no_warnings` proves the real `init`→`checkup` path still reports `Summary: 0 error(s), 0 warning(s).`

If the wikilink test fails here, Task 2 was skipped or its `_DEFAULTS` edit was lost — `_root_doc_only_workspace` builds its probe from that list.

- [ ] **Step 5: Run the whole suite**

Run: `python3 -m unittest discover -s tests -t . -v`

Expected: PASS, 0 failures. `tests/test_review.py` and `tests/test_export_player.py` are the two most likely to notice a doctrine edit; if either fails, read the failure before changing anything — it is telling you something real about the new section.

- [ ] **Step 6: Commit**

```bash
git add src/bunnyforge/data/doctrine/AGENTS.md tests/test_init.py
git commit -m "feat: AGENTS.md names campaign-doctrine.md and fixes their precedence"
```

---

### Task 4: Serve it to the MCP agent

The MCP agent does not follow prose. Without this task the campaign-owned half simply is not visible to it. `serve_mcp` lists absent files as nothing at all (`src/bunnyforge/serve_mcp.py:40-43`, `214-222`), so this change is safe for workspaces scaffolded before the split.

**Files:**
- Modify: `src/bunnyforge/serve_mcp.py:40-43` (`DOCTRINE_FILES` and its comment)
- Test: `tests/test_serve_mcp.py`, in the class containing `test_doctrine_resource_lists_and_reads` (around line 207)

**Interfaces:**
- Consumes: `serve_mcp.build_server(store)`, the module-level `serve_mcp.DOCTRINE_FILES` tuple, and the test helper `scaffold(case) -> _store.WorkspaceStore` defined at `tests/test_serve_mcp.py:27`.
- Produces: the resource URI `bunnyforge://doctrine/campaign-doctrine.md`.

This task needs the MCP extra installed: `pip install -e '.[mcp]'`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_serve_mcp.py`, immediately after `test_absent_doctrine_file_is_not_listed`:

```python
    async def test_campaign_doctrine_is_served_when_present(self):
        # The MCP agent follows no include directive: a "see also" inside
        # AGENTS.md reaches it as literal text and nothing more. The GM-owned
        # half is visible to it only because the server lists it too.
        store = scaffold(self)
        (store.ws.root / "campaign-doctrine.md").write_text(
            "# Campaign Doctrine\nThe Language/ subtree has its own rules.\n",
            encoding="utf-8")
        server = serve_mcp.build_server(store)
        uris = {str(r.uri) for r in await server.list_resources()}
        self.assertIn("bunnyforge://doctrine/campaign-doctrine.md", uris)
        parts = list(await server.read_resource(
            "bunnyforge://doctrine/campaign-doctrine.md"))
        self.assertIn("own rules", "".join(p.content for p in parts))
```

Note the ordering: the file is written *before* `build_server`, because `build_server` registers resources once at assembly time (the `for filename in DOCTRINE_FILES` loop at line 214). A file created afterwards would not be listed.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest tests.test_serve_mcp -k campaign_doctrine_is_served -v`

Expected: FAIL — `'bunnyforge://doctrine/campaign-doctrine.md' not found in` the URI set.

- [ ] **Step 3: Add the file to `DOCTRINE_FILES`**

In `src/bunnyforge/serve_mcp.py`, replace lines 40-43:

```python
# Workspace doctrine, offered as MCP resources so a fresh conversation can
# load the house rules before it writes anything. Absent files are simply
# not listed -- which is also what makes campaign-doctrine.md safe to add
# here: a workspace scaffolded before the doctrine split does not have it,
# and gets exactly the three resources it got before.
DOCTRINE_FILES = ("style-guide.md", "situation-design.md", "AGENTS.md",
                  "campaign-doctrine.md")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_serve_mcp -v`

Expected: PASS, including the pre-existing `test_absent_doctrine_file_is_not_listed`, which is now also the regression guard for un-migrated workspaces.

- [ ] **Step 5: Commit**

```bash
git add src/bunnyforge/serve_mcp.py tests/test_serve_mcp.py
git commit -m "feat: serve-mcp serves campaign-doctrine.md alongside the packaged doctrine"
```

---

### Task 5: Documentation and the migration recipe

Five workspaces could exist; exactly one does. The migration is a written procedure run by hand, not a subcommand — see the Global Constraints. But it ships, because a workspace scaffolded before this change needs it and the plan document will not be there.

**Files:**
- Create: `docs/adopting-doctrine.md`
- Modify: `README.md:16-20` (the "Agent-first doctrine" bullet)
- Modify: `docs/serve-mcp.md:94-97` (the resources sentence)

**Interfaces:**
- Consumes: nothing programmatic. Every path and filename below comes from Tasks 1-4.
- Produces: nothing programmatic.

- [ ] **Step 1: Write the migration doc**

Create `docs/adopting-doctrine.md`:

```markdown
# Adopting packaged doctrine

`AGENTS.md` in your workspace is a copy of the one bunnyforge ships. The
package owns it: it is generic, identical in every workspace, and changes
when bunnyforge changes. `campaign-doctrine.md` beside it is yours, and no
release will ever touch it.

That split is what makes adoption cheap. Because nothing campaign-specific
lives in `AGENTS.md`, a new version is a file copy rather than a merge.

## Adopting a new version

From your workspace root, with the new bunnyforge installed:

    python3 -c "import pathlib; from bunnyforge import init; \
      pathlib.Path('AGENTS.md').write_bytes( \
        init.packaged_bytes('doctrine/AGENTS.md'))"
    git diff AGENTS.md

Read the diff — that is the whole review, and it is the reason this stays a
manual step. Then bump the `bunnyforge==` pin in `requirements.txt` in the
same commit, and run your campaign tests. `tests/test_campaign_drift.py`
compares your copy to the installed package byte for byte; it goes green when
the copy and the pin agree.

If the diff contains something you do not want, the answer is not to keep the
old bytes. Put the exception in `campaign-doctrine.md`, naming the generic
rule it displaces, and take the upstream copy whole.

## Migrating a workspace scaffolded before the split

Workspaces created before `campaign-doctrine.md` existed have their
campaign-specific rules written into `AGENTS.md` itself. Five steps, once:

1. **Find what is yours.** Diff your `AGENTS.md` against the version you
   currently pin, not against the newest one — otherwise upstream changes you
   have not adopted yet look like local edits:

       git -C /path/to/bunnyforge show vX.Y.Z:src/bunnyforge/data/doctrine/AGENTS.md > /tmp/pinned.md
       diff -u /tmp/pinned.md AGENTS.md

   What remains is your campaign's own material.

2. **Move it.** Create `campaign-doctrine.md` (copy the packaged stub from
   `python3 -c "from bunnyforge import init; print(init.packaged_bytes('root/campaign-doctrine.md').decode())"`)
   and cut those sections into it. Where a section overrides a rule in
   `AGENTS.md`, say which rule, in the section itself.

3. **Take the packaged `AGENTS.md` whole**, using the adopt command above.
   This performs any pending upstream adoption at the same time.

4. **Register the new file.** If your `campaign.toml` lists `root_docs`
   explicitly, add `"campaign-doctrine.md"` to it — an explicit list
   overrides the packaged default, so the new entry will not reach you
   otherwise. If the key is commented out, there is nothing to do.

5. **Turn the guard on.** If your `tests/test_campaign_drift.py` allowlists
   `AGENTS.md`, delete that entry. It exists because the file was a fork;
   after the split it is a copy again, and it can be compared exactly. Bump
   the pin and run the suite.

Step 5 is the point of the whole exercise. An allowlisted file is an
unguarded file, and `AGENTS.md` is the one you least want unguarded.
```

- [ ] **Step 2: Update the README bullet**

In `README.md`, replace lines 16-20:

```markdown
- **Agent-first doctrine.** `init` writes an `AGENTS.md` contract that
  tells an AI agent how to behave in the workspace — package-owned, so a
  new release replaces it wholesale — plus `campaign-doctrine.md` beside
  it for the rules that are yours alone. And doctrine *skeletons*: a style
  guide and a situation-design guide that interview you, each section
  explaining what belongs in it, so filling them in is answering
  questions rather than staring at a blank file.
```

- [ ] **Step 3: Update the serve-mcp doc**

In `docs/serve-mcp.md`, replace lines 94-97:

```markdown
**Read canon:** `campaign_overview`, `list_entities`, `read_entity`,
`search`, `generate_names`. Workspace doctrine (`style-guide.md`,
`situation-design.md`, `AGENTS.md`, `campaign-doctrine.md`) is served as
MCP *resources* — tell the agent to load them before it writes anything
for this campaign. `campaign-doctrine.md` carries the rules specific to
this campaign, and overrides `AGENTS.md` where the two disagree; a
workspace that predates it simply serves the other three.
```

- [ ] **Step 4: Verify the docs against the code you actually wrote**

Run: `python3 -c "from bunnyforge import init; print(init.packaged_bytes('root/campaign-doctrine.md').decode())"`

Expected: prints the stub from Task 1. This is the exact command `docs/adopting-doctrine.md` step 2 tells a GM to run; run it rather than assuming it works.

Then run: `python3 -c "from bunnyforge import serve_mcp; print(serve_mcp.DOCTRINE_FILES)"`

Expected: the four-tuple ending in `'campaign-doctrine.md'`, matching what `docs/serve-mcp.md` now claims.

- [ ] **Step 5: Run the full suite and the portability check**

Run:

```bash
python3 -m unittest discover -s tests -t . -v
python3 tests/check_portability.py
```

Expected: both pass. `check_portability.py` greps packaged data for campaign-specific terms; the new stub is generic, so it should be clean. If it flags something, the stub's wording is the bug, not the check.

- [ ] **Step 6: Commit**

```bash
git add docs/adopting-doctrine.md README.md docs/serve-mcp.md
git commit -m "docs: the doctrine ownership split, and how to adopt a new version"
```

---

### Task 6: Verify in a clean checkout, then open the PR

**Files:** none modified.

- [ ] **Step 1: Verify where the artifact will live, not where you worked**

A warm cache and uncommitted edits both mask failures the next person hits. Run the gate from a throwaway checkout of the branch:

```bash
git worktree add /tmp/bf-verify HEAD
cd /tmp/bf-verify
python3 -m venv .venv && .venv/bin/pip install -e '.[mcp]'
.venv/bin/python -m unittest discover -s tests -t . -v
.venv/bin/python tests/check_portability.py
```

Expected: 0 failures from both.

- [ ] **Step 2: Run the init-then-checkup gate as a real user would**

```bash
cd /tmp
/tmp/bf-verify/.venv/bin/python -m bunnyforge.init /tmp/bf-fresh --name "Verify"
/tmp/bf-verify/.venv/bin/python -m bunnyforge.review checkup --workspace /tmp/bf-fresh
ls /tmp/bf-fresh/campaign-doctrine.md
```

Expected: `Summary: 0 error(s), 0 warning(s).` and the file exists. Record the actual output; do not paraphrase it.

- [ ] **Step 3: Clean up the verification checkout**

```bash
rm -rf /tmp/bf-fresh
git worktree remove /tmp/bf-verify --force
```

- [ ] **Step 4: Open the PR**

Use the `dcltdw:opening-a-pr` skill. The PR body should carry: the measurement that motivated it (against `v0.3.1` the live workspace's `AGENTS.md` is the packaged file plus one appended section — no interleaving), the point that `AGENTS.md` is currently allowlisted out of `test_campaign_drift` and this is what lets it come back under the guard, and the note that `bunnyforge doctrine adopt` is deliberately not built. Link issue #32 and say it closes as Won't Do once this lands, rather than `Closes #32`.

Wait for four green checks and for review approval before merging. Do not merge unprompted.

---

## Out of scope — deliberately

Recorded so an executor does not helpfully add them:

- **`bunnyforge doctrine adopt` / `--check` / `doctrine split`.** The analysis concluded the split makes all three unnecessary; the drift test plus the pin test already *are* `--check`.
- **Anything touching `style-guide.skeleton.md` or `situation-design.skeleton.md`.** Those are real skeletons — 84→705 and 73→215 lines in the live workspace, interleaved beyond extraction, and correctly outside the drift guard already. There is no seam there and this change must not pretend otherwise.
- **The Anjeong migration itself.** Anjeong is a separate repository, pinned to `bunnyforge==0.3.1`, and nothing breaks until that pin moves. It follows `docs/adopting-doctrine.md` after this ships — and after #62 and the release, so it adopts everything in one move.
- **The release.** Ticket #62 (the leading-`_` convention) comes next, and the release comes last so it carries both decisions.
