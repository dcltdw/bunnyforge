# The Working Sequence (#111) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task, **inline, in one session** — this is one document plus link/test plumbing, and the three tasks are strictly sequential, so there is nothing for subagents to parallelise. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give bunnyforge one canonical, agent-served description of the end-to-end order of work in a campaign workspace — and make the README and `docs/serve-mcp.md` point at it under test instead of restating it.

**Architecture:** Prose-first change. A new `## The working sequence` section in the packaged `AGENTS.md` is the *only* full copy: it carries order and what is still owed when a step finishes, cites the owning section for every rule, and restates none. `docs/serve-mcp.md` links it and restates nothing; `README.md` carries a five-line outline plus a link, and a test binds that outline to the doctrine's `### Phase N — <name>` headings. Further tests bind the section's code-facing claims (tool names, the default `compendium_dirs` list, the section names it cites) to their sources, the way `test_init.py` already pins doctrine.

**Tech Stack:** Python ≥ 3.11, stdlib only, `unittest`. The optional `mcp` extra is installed in this worktree's `.venv`.

**Spec:** None as a separate file — dcltdw asked for the design to ride in this plan. The **Design decisions** section below is the spec; read it first, the tasks argue from it. Issue: https://github.com/dcltdw/bunnyforge/issues/111 (read the body *and* dcltdw's post-merge comment).

## Design decisions (approved by dcltdw, 2026-09-21)

### 1. The agent-facing copy is a section of the packaged `AGENTS.md`, not a new root doc

`serve_mcp.DOCTRINE_FILES` (`src/bunnyforge/serve_mcp.py:53`) serves workspace-root files as `bunnyforge://doctrine/<filename>`, so the copy must live in a root doc. The issue leaned towards a new `AGENTS.md` section; confirmed, for three reasons:

- **A new root doc costs more than the issue lists.** Beyond a `MANIFEST` entry and a `DOCTRINE_FILES` entry it needs a `root_docs` config default, a **Read order** entry, a bump to the `src/bunnyforge/README.md` count test — and existing workspaces never receive it without a new adoption step.
- **A second file is a second drift site.** The walkthrough sequences rules `AGENTS.md` already owns. In a separate file it would have to restate them; inside `AGENTS.md` it cites them by section name, which is already that file's idiom ("**Retrieval scope**, below, carries the full rule").
- **Size is fine:** 432 lines today, ~95 added; the file already carries MCP-specific content (**Direct edits to canon**, the inbound bullets).

Placement: directly after `## Task-start context`. Phase 0 *is* **Read order** plus **Task-start context** — the two sections just above — so the sequence picks up where they stop.

**House rule for the section:** it carries *order* and *what is still owed*. Every rule is cited to its owning section; none is restated. (`test_the_ask_discipline_has_one_owner` is the precedent.)

### 2. Drift: link by default; the little that is restated gets a test

- **Packaged `AGENTS.md`** — the only full copy.
- **`docs/serve-mcp.md`** — a pure link, no restatement: one paragraph opening "What the agent can do".
- **`README.md`** — a short "Working in a workspace" section: the five phase names in order, one clause each, and a link. Link-only was considered and rejected: an evaluator would land in a ~530-line file addressed to the agent in the GM's first person. The phase list is the most stable part, and one test makes drift fail CI.
- **Tests** bind: README outline ↔ doctrine phase headings; both links ↔ a real heading; the section's tool names ↔ `build_server`'s registered tools; its default `compendium_dirs` list ↔ `_config._DEFAULTS`; the section names it cites ↔ headings that exist.

### 3. Three corrections to the issue's Phase 0–4 draft

1. **Default mode has no `promote_draft`.** Without `--allow-direct-edits`, promotion is the GM's, by hand (`docs/serve-mcp.md`: "promotion is manual and yours"). Phases 2 and 3 cover both modes.
2. **The compendium line goes through `propose_revision` on `compendium.md`** — that is what `compendium_reminder` (`_store.py:645`) tells the agent. One proposal per file can be pending (`_store.py:503`), so several new entities share one compendium revision, extended with `update_draft`. A compendium line that lands before its entity dangles until both land — the same safety net as two drafts that link to each other.
3. **Doctrine contradicts itself on indexing.** `AGENTS.md` § File conventions says "New files must be added to `[[compendium]]`" unqualified, and the `compendium.md` stub says "when a new file is created anywhere in this workspace". Briefs and sessions must *not* be indexed (`_config.py:112`; `_store.py:654`). Both sentences are qualified in this PR — otherwise the new section and the old bullet disagree inside one file. (The stub is scaffold-once and GM-owned thereafter: the fix reaches new workspaces only, which is fine — say so in the CHANGELOG.)

### Facts verified against source at `43a60b8` (re-check any you lean on)

- `compendium_dirs` defaults to `NPCs, Factions, Setting, Mechanics, PCs, Ideas` (`_config.py:112`).
- `promote_draft` branches on `target.is_file()`; on the revision path it refuses a stale **or unrecorded** base, and the refusal text says "read_entity the current file, merge with update_draft, then promote again" (`_store.py:566-600`).
- `update_draft` on a revision shadow **re-baselines** it against current canon (`_store.py:523`; tool docstring `serve_mcp.py:196`) — which is why merge-then-retry works.
- `list_drafts` rows carry `kind` and, for revisions, `stale` (`_store.py:540-553`).
- No MCP tool runs `review checkup`; none reaches `_ExtractInbound/_Done/` (`serve_mcp.py:118-260` is the full tool list: 12 always, plus `write_entity` and `promote_draft` under the flag).
- The packaged `AGENTS.md` contains **no markdown tables** today — the new section uses lists, to match.
- `docs/adopting-doctrine.md` § "Adopting a new version" already covers a plain file copy: **no change to that file.**

## Global Constraints

- Python ≥ 3.11, stdlib only, no new dependencies.
- **Never commit to `main`.** Work stays on branch `docs/111-working-sequence` in the worktree `/Users/dcltdw/Github/.worktrees/bunnyforge/docs/111-working-sequence` (exists; this plan is committed there). Run `git branch --show-current` before every commit.
- **Use the worktree's venv for everything: `.venv/bin/python`, `.venv/bin/bunnyforge`.** The machine-wide `bunnyforge` is a *non-editable* 0.6.0 in site-packages: a bare `python3` run from this worktree imports **that** copy, so the doctrine tests would read the old `AGENTS.md` and mislead in both directions. `.venv/` is gitignored, already built (`pip install -e '.[mcp]'`), and local to the worktree. **Never `pip install` outside it** — an editable install from a worktree into the shared interpreter outlives the worktree.
- Once, before starting: `.venv/bin/python -c "import bunnyforge; print(bunnyforge.__file__)"` must print a path inside the worktree.
- Suite, from the worktree root: `.venv/bin/python -m unittest discover -s tests -t .` — baseline on `43a60b8`: `Ran 987 tests … OK`, mcp extra present so nothing mcp-gated is skipped.
- No test may write into the repo — temp dirs only. `git status --porcelain` must be empty after the suite.
- Packaged prose ships verbatim into every workspace. #65 (mechanical screening of packaged prose for campaign-specific terms) is still **open and deferred**, so the doctrine text must be cleared by a deliberate human read at PR time, and the PR body must say that is the basis for the portability claim. Use only the example names the file already uses (`mira-venn`, `session-014`, `harbor-guild`).
- Doctrine voice: the GM speaks in the first person ("I"), to the agent ("you"). Wrap at ≤ 78 columns. The tests flatten whitespace, so re-wrapping never breaks them.
- Every wikilink in the packaged `AGENTS.md` must resolve in a workspace holding only root docs (`test_agents_md_wikilinks_resolve_with_only_root_docs`). The text below uses only `[[front-burner]]`, `[[open-questions]]` and `[[compendium]]`.
- `CHANGELOG.md` entries land under `[Unreleased]` in this PR. No version bump.
- Commit trailer: stamp the AI model the session was asked to run as, e.g. `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- The primary clone (`~/Github/bunnyforge`) has an untracked `docs/credential-audit-2026-09-08.md`. It is not part of this work. Do not touch it.

## File structure

| file | change | responsibility |
|---|---|---|
| `src/bunnyforge/data/doctrine/AGENTS.md` | modify | gains `## The working sequence`; § File conventions bullet qualified |
| `src/bunnyforge/data/root/compendium.md` | modify | maintenance-rule sentence qualified |
| `tests/test_init.py` | modify | doctrine pins, beside the existing ones in `TestPackagedDoctrineIsPortable` |
| `tests/test_serve_mcp.py` | modify | the section's tool names ⊆ registered tools (mcp-gated) |
| `tests/test_docs.py` | **create** | the repo's own docs where they lean on packaged doctrine: links resolve, README outline matches |
| `README.md` | modify | new `## Working in a workspace`, between `## The workspace` and `## Names` |
| `docs/serve-mcp.md` | modify | one linking paragraph opening `## What the agent can do` |
| `CHANGELOG.md` | modify | `[Unreleased]` entries |

---

### Task 1: The doctrine section, its pins, and the indexing correction

**Files:**
- Modify: `src/bunnyforge/data/doctrine/AGENTS.md` (insert after `## Task-start context`, which ends at line 99, before `## Verify against the files, not against earlier prose` at line 101; replace one bullet in `## File conventions`, line 401-402)
- Modify: `src/bunnyforge/data/root/compendium.md:8-10`
- Test: `tests/test_init.py` (append methods to `TestPackagedDoctrineIsPortable`, after `test_direct_edits_are_used_only_when_asked`, before the module-level `def _packaged_data_root`)
- Test: `tests/test_serve_mcp.py` (append one method to `TestBuildServer`, the `IsolatedAsyncioTestCase` starting at line 398)

**Interfaces:**
- Produces, for Task 2: the heading `## The working sequence` (GitHub anchor `#the-working-sequence`) and exactly these five sub-headings, which Task 2's README test reads with the regex `^### Phase (\d) — (.+)$` (that is an em dash, U+2014):
  `### Phase 0 — Orient`, `### Phase 1 — Decide what kind of file this is`, `### Phase 2 — New material`, `### Phase 3 — Revising existing canon`, `### Phase 4 — Inbound extraction`

- [ ] **Step 1: Confirm the environment**

Run:
```bash
cd /Users/dcltdw/Github/.worktrees/bunnyforge/docs/111-working-sequence
git branch --show-current
.venv/bin/python -c "import bunnyforge; print(bunnyforge.__file__)"
```
Expected: `docs/111-working-sequence`, then a path under `.worktrees/bunnyforge/docs/111-working-sequence/src/`. If the second line names site-packages, stop — see Global Constraints.

- [ ] **Step 2: Write the failing doctrine pins in `tests/test_init.py`**

Append to `TestPackagedDoctrineIsPortable` (`re`, `_config` and `init` are already imported at the top of the file):

```python
    # -- #111: The working sequence ----------------------------------------
    # The one full copy of the end-to-end order of work. README.md and
    # docs/serve-mcp.md link it rather than restating it (tests/test_docs.py
    # binds those); what is pinned HERE is the section's own code-facing
    # claims, so the copy cannot drift from the code it describes.

    def _working_sequence(self) -> str:
        doctrine = init.packaged_bytes("doctrine/AGENTS.md").decode("utf-8")
        self.assertIn("\n## The working sequence\n", doctrine)
        section = doctrine.split("\n## The working sequence\n", 1)[1]
        return section.split("\n## ", 1)[0]

    def test_the_working_sequence_has_its_five_phases_in_order(self):
        # The headings are an interface: tests/test_docs.py reads them to
        # check the README's outline. Renaming one is fine -- it fails here
        # first, with the list to update in plain sight.
        phases = re.findall(r"^### Phase (\d) — (.+)$",
                            self._working_sequence(), re.MULTILINE)
        self.assertEqual(phases, [
            ("0", "Orient"),
            ("1", "Decide what kind of file this is"),
            ("2", "New material"),
            ("3", "Revising existing canon"),
            ("4", "Inbound extraction"),
        ])

    def test_the_working_sequence_states_the_default_compendium_dirs(self):
        # Which sections owe a compendium line is configuration, and the
        # section quotes the default. Bound to _config so a changed default
        # cannot leave doctrine teaching the old list -- and Briefs/Sessions
        # are asserted OUT of the default first, because the sentence telling
        # the agent never to index them is only true while that holds.
        flat = " ".join(self._working_sequence().split())
        defaults = _config._DEFAULTS["compendium_dirs"]
        stated = re.search(r"by default ((?:`[A-Za-z]+`,? ?)+)", flat)
        self.assertIsNotNone(
            stated,
            "the 'by default `NPCs`, ...' sentence has been reworded past "
            "the pattern this test reads -- restate the list or update the "
            "pattern; an unmatched regex must not pass vacuously")
        self.assertEqual(re.findall(r"`([A-Za-z]+)`", stated.group(1)),
                         list(defaults))
        for unindexed in ("Briefs", "Sessions"):
            with self.subTest(unindexed=unindexed):
                self.assertNotIn(unindexed, defaults)
                self.assertIn(f"`{unindexed}/`", flat)

    def test_the_working_sequence_carries_what_is_nowhere_else(self):
        # #111's list of things no other document says. One needle each:
        # promotion is one tool for drafts and revisions alike; by default
        # it is the GM's, by hand; the index entry rides a proposed revision;
        # revisions iterate through update_draft; nothing orders two linked
        # drafts; and the _Done/ move is reachable by no tool.
        flat = " ".join(self._working_sequence().split())
        for needle in ("same tool", "by hand", "`promote_draft`",
                       "`propose_revision`", "`update_draft`",
                       "Nothing enforces a promotion order",
                       "`_ExtractInbound/_Done/`", "No MCP tool reaches"):
            with self.subTest(needle=needle):
                self.assertIn(needle, flat)

    def test_the_working_sequence_cites_sections_that_exist(self):
        # The section restates no rule: it names the section that owns each
        # one. A renamed heading would leave that citation pointing nowhere,
        # and nothing else would notice -- a bold phrase is not a link.
        doctrine = init.packaged_bytes("doctrine/AGENTS.md").decode("utf-8")
        headings = re.findall(r"^#{2,3} (.+)$", doctrine, re.MULTILINE)
        flat = " ".join(self._working_sequence().split())
        for owner in ("Read order", "Task-start context",
                      "What gets written where",
                      "Which file a new fact belongs in", "Retrieval scope",
                      "File conventions", "Flag invented canon in drafts",
                      "Direct edits to canon", "Reviewing the workspace",
                      "Extracting from _ExtractInbound/",
                      "At the end of a working session"):
            with self.subTest(owner=owner):
                self.assertIn(f"**{owner}**", flat)
                self.assertTrue(
                    any(h.startswith(owner) for h in headings),
                    f"the working sequence cites **{owner}**, but no "
                    "heading in AGENTS.md starts with that")

    def test_file_conventions_defers_to_the_sequence_on_indexing(self):
        # The bullet used to say every new file needs a compendium line,
        # which is false for briefs and sessions and contradicted the
        # sequence from inside the same file. One owner: the bullet keeps
        # the rule, the sequence keeps which sections it covers.
        doctrine = init.packaged_bytes("doctrine/AGENTS.md").decode("utf-8")
        section = doctrine.split("\n## File conventions\n", 1)[1]
        section = " ".join(section.split("\n## ", 1)[0].split())
        self.assertNotIn("New files must be added", section)
        self.assertIn("a section the compendium indexes", section)
        self.assertIn("**The working sequence**", section)
```

- [ ] **Step 3: Write the failing tool-name test in `tests/test_serve_mcp.py`**

Add `import re` to the stdlib import block at the top (alphabetically, after `import os`). Then append to `TestBuildServer`:

```python
    async def test_the_working_sequence_names_only_real_tools(self):
        # #111: doctrine's working sequence names tools in backticks, and
        # a renamed or removed tool would leave it teaching a call that
        # does not exist. Derived from the prose rather than listed here,
        # so a tool newly mentioned is checked without touching this test.
        # NOT_TOOLS is every other snake_case identifier the section uses;
        # a new one fails below with its name, and belongs in this set.
        from bunnyforge import init
        NOT_TOOLS = {"compendium_dirs", "drafts_pending", "inbound_pending"}
        doctrine = init.packaged_bytes("doctrine/AGENTS.md").decode("utf-8")
        self.assertIn("\n## The working sequence\n", doctrine)
        section = doctrine.split("\n## The working sequence\n", 1)[1]
        section = section.split("\n## ", 1)[0]
        named = set(re.findall(r"`([a-z]+(?:_[a-z]+)+)`", section)) - NOT_TOOLS
        server = serve_mcp.build_server(scaffold(self),
                                        allow_direct_edits=True)
        registered = {t.name for t in await server.list_tools()}
        self.assertEqual(
            named - registered, set(),
            "the working sequence names a tool the server does not "
            "register (or a new non-tool identifier: add it to NOT_TOOLS)")
        # The floor: an extraction that found nothing would pass the check
        # above vacuously.
        self.assertGreaterEqual(named, {
            "campaign_overview", "save_draft", "update_draft",
            "propose_revision", "promote_draft", "list_inbound",
            "read_inbound"})
```

- [ ] **Step 4: Run the new tests and watch them fail**

Run:
```bash
.venv/bin/python -m unittest -v \
  tests.test_init.TestPackagedDoctrineIsPortable \
  tests.test_serve_mcp.TestBuildServer.test_the_working_sequence_names_only_real_tools 2>&1 | tail -30
```
Expected: the five new `test_init` tests and the one `test_serve_mcp` test FAIL — four on `'\n## The working sequence\n' not found`, `test_file_conventions_…` on `'New files must be added' unexpectedly found`. Every pre-existing test in the class still passes. If the serve_mcp test reports *skipped*, the venv lacks the mcp extra — stop and fix that (`.venv/bin/pip install -e '.[mcp]'`), because a skipped test has not been watched failing.

- [ ] **Step 5: Insert the section into the packaged `AGENTS.md`**

Insert the block below between the end of `## Task-start context` (the paragraph ending "…belongs upstream as a bunnyforge ticket.") and `## Verify against the files, not against earlier prose`, with one blank line on each side. Copy it exactly — the tests read its headings, its bold section names, and its backticked identifiers.

```markdown
## The working sequence

The other sections of this file are rules. This one is the order they apply
in, and what is still owed when each step finishes. It restates no rule:
each step names the section that owns it, and that section wins on any
disagreement. Tool names are the MCP server's; working on the filesystem
instead, the steps are the same and the tools are your own file operations.

When I ask how work here goes, this is the section to walk me through.

### Phase 0 — Orient

1. `campaign_overview` first: the sections, `[[front-burner]]`,
   `[[open-questions]]`, and two counts — `drafts_pending` and
   `inbound_pending`.
2. The doctrine, in the order **Read order** above fixes.
3. If `drafts_pending` is non-zero, `list_drafts` before starting anything
   new: earlier work is resumed and merged, not written again.
4. The **Task-start context** questions — in one message, and only the
   ones my request left open.

### Phase 1 — Decide what kind of file this is

Writeup, brief, or record. **What gets written where**, below, carries the
distinction, and **Which file a new fact belongs in** the choice of file.
Decide before drafting, because the kind decides what is owed once the
file lands:

- **The writeup** — true always, `NPCs/mira-venn.md`. Owes a line in
  `[[compendium]]`.
- **The brief** — true this session, `Briefs/session-014/mira-venn.md`.
  Owes no compendium line.
- **The record** — what happened, `Sessions/session-014.md`. Owes no
  compendium line, and is append-only.

The compendium indexes only the sections `compendium_dirs` names in
`campaign.toml` — by default `NPCs`, `Factions`, `Setting`, `Mechanics`,
`PCs`, `Ideas`. `Briefs/` and `Sessions/` are deliberately outside it: a
brief or a session record must **not** get a compendium line.

### Phase 2 — New material

1. **Check what exists** — `search` and `list_entities`, under the scope
   **Retrieval scope** settles. Archived names are still taken.
2. **Draft** — `save_draft`, with the full front matter `_Templates/`
   describes (**File conventions**).
3. **Say what you invented** — the short list after the draft that
   **Flag invented canon in drafts** asks for.
4. **I review.** The draft waits in `_AgentDrafts/`, where `list_drafts`
   and `read_draft` find it again. Iterate with `update_draft`;
   `save_draft` never overwrites.
5. **Promotion is mine to call.** By default you have no tool for it: I
   move the file out of `_AgentDrafts/` by hand. With direct edits
   enabled, `promote_draft` does it — only when I explicitly ask
   (**Direct edits to canon**). Approving a draft is not asking.
6. **Index it — if Phase 1 said a line is owed.** `propose_revision` on
   `compendium.md` adds the entry. `promote_draft` says so itself when it
   lands a file the compendium does not link yet; when I promote by hand
   nothing says so, so you raise it. Only one proposal per file can be
   pending: several new entities share one compendium revision, extended
   with `update_draft`.
7. **Current state** — if the new material moves it, propose the
   `[[front-burner]]` revision too (**Which file a new fact belongs in**).
8. **Verify** — `bunnyforge review checkup` (**Reviewing the workspace**).
   No MCP tool runs it: ask me to, and expect it clean only once
   everything from this task has landed.

**Drafts that link to each other.** Nothing enforces a promotion order.
Until both land, the checkup's wikilink check flags the dangling link —
that is the safety net working, not a fault to fix by unlinking. The same
holds for a compendium line that lands before the file it indexes.

### Phase 3 — Revising existing canon

1. `read_entity` the current file: the revision is proposed against
   exactly what you read.
2. `propose_revision` writes a shadow at the mirrored path under
   `_AgentDrafts/` and records the hash of the canon it was based on. One
   pending proposal per file — if one exists, `read_draft` it, merge, and
   `update_draft` instead.
3. I review it as a diff against the live file.
4. Promotion is the **same tool** as for a new draft — `promote_draft`,
   under the same explicit-ask rule — or my hand, by default. The tool
   branches on whether the target already exists. For a revision it
   refuses if canon changed after the proposal, or if no base was
   recorded. On that refusal: `read_entity` the current file, merge with
   `update_draft` (which re-bases the shadow), and ask me again.
   `list_drafts` marks such a revision `stale` before you get that far.
5. Some files take only a proposal, whatever I ask — **Direct edits to
   canon** lists them — and a past session takes only an append.
6. Steps 7 and 8 of Phase 2 apply unchanged. A revision owes no new
   compendium line unless it renames or retires the file
   (**File conventions**).

### Phase 4 — Inbound extraction

1. `inbound_pending` in the overview licenses noticing and offering —
   never listing, never reading. **Extracting from _ExtractInbound/**
   carries the whole contract.
2. When I ask: `list_inbound`, then `read_inbound`. A file marked
   unreadable needs converting first; say so rather than guessing at it.
3. What you extract becomes drafts, and from there it is Phase 1 and
   Phase 2 — conflict rule included: where the source disagrees with
   canon, stop and ask.
4. **Still owed at the end:** once I confirm the extraction, the spent
   source moves to `_ExtractInbound/_Done/`. No MCP tool reaches that
   move — tell me it is owed, and I will make it.

Whatever the phase, the last step is **At the end of a working session**,
below: say which files the work made stale, and draft the updates.
```

- [ ] **Step 6: Qualify the § File conventions bullet in the same file**

Replace:
```markdown
- New files must be added to `[[compendium]]` in the same sitting. An unindexed
  file is an invisible file.
```
with:
```markdown
- New files in a section the compendium indexes must be added to
  `[[compendium]]` in the same sitting. An unindexed file is an invisible
  file. Which sections those are — and which deliberately are not — is
  under **The working sequence** above, Phase 1.
```

- [ ] **Step 7: Qualify the `compendium.md` stub's maintenance rule**

In `src/bunnyforge/data/root/compendium.md`, replace:
```markdown
**Maintenance rule:** when a new file is created anywhere in this workspace, add
a line here in the same sitting. An unindexed file is an invisible file, and
`bunnyforge review checkup` warns about every entity missing from here.
```
with:
```markdown
**Maintenance rule:** when a new file is created in a section this compendium
indexes — `compendium_dirs` in `campaign.toml`; briefs and session records are
deliberately not indexed — add a line here in the same sitting. An unindexed
file is an invisible file, and `bunnyforge review checkup` warns about every
entity missing from here.
```

- [ ] **Step 8: Run the new tests and watch them pass**

Run the Step 4 command again.
Expected: all PASS, none skipped. If `test_the_working_sequence_names_only_real_tools` fails naming an identifier, either the prose has a typo in a tool name (fix the prose) or you introduced a new non-tool snake_case term (add it to `NOT_TOOLS`).

- [ ] **Step 9: Mutation check — prove the tool-name test can fail for the reason it exists**

The Step 4 failure was "section missing", which is not the failure this test is *for*. Watch the real one once, then undo it with the inverse `sed` — **not** `git checkout -- <file>`, which would revert the whole file to HEAD and discard Steps 5 and 6 along with the mutation:

```bash
sed -i '' 's/enabled, `promote_draft` does it/enabled, `promote_drafts` does it/' src/bunnyforge/data/doctrine/AGENTS.md
.venv/bin/python -m unittest tests.test_serve_mcp.TestBuildServer.test_the_working_sequence_names_only_real_tools 2>&1 | tail -8
sed -i '' 's/enabled, `promote_drafts` does it/enabled, `promote_draft` does it/' src/bunnyforge/data/doctrine/AGENTS.md
grep -c 'promote_drafts' src/bunnyforge/data/doctrine/AGENTS.md
```
Expected: the test FAILS with `promote_drafts` in the set difference; after the second `sed`, `grep -c` prints `0`. (`sed -i ''` is the macOS form; this plan runs on macOS.)

- [ ] **Step 10: Run the whole suite and the scaffold gate**

```bash
.venv/bin/python -m unittest discover -s tests -t . 2>&1 | tail -4
T=$(mktemp -d) && .venv/bin/bunnyforge init "$T/demo" --name Demo && .venv/bin/bunnyforge review checkup --workspace "$T/demo"; rm -rf "$T"
git status --porcelain
```
Expected: `Ran 993 tests … OK` (987 + 6); checkup reports `0 error(s), 0 warning(s)`; `git status` lists exactly the four files this task modified and nothing else. A wikilink warning from checkup means the inserted text links something a fresh workspace lacks — fix the text, not the check.

- [ ] **Step 11: Commit**

```bash
git branch --show-current   # docs/111-working-sequence
git add src/bunnyforge/data/doctrine/AGENTS.md src/bunnyforge/data/root/compendium.md tests/test_init.py tests/test_serve_mcp.py
git commit -m "docs(doctrine): the working sequence — order of work, and what each step still owes (#111)" -m "Packaged AGENTS.md gains the one full copy of the end-to-end sequence, citing the owning section for every rule and restating none. Tests bind its tool names to build_server, its default compendium_dirs list to _config, and its cited section names to headings that exist.

Also qualifies the two places doctrine said every new file needs a compendium line: only compendium_dirs sections do, and briefs and session records must not be indexed." -m "Co-Authored-By: <the model this session was asked to run as> <noreply@anthropic.com>"
```

---

### Task 2: README outline and `serve-mcp.md` link, bound by `tests/test_docs.py`

**Files:**
- Create: `tests/test_docs.py`
- Modify: `README.md` (insert a new section between the end of `## The workspace`, line 111, and `## Names`, line 113)
- Modify: `docs/serve-mcp.md` (insert one paragraph directly under the `## What the agent can do` heading, line 359)

**Interfaces:**
- Consumes, from Task 1: the heading `## The working sequence` in `src/bunnyforge/data/doctrine/AGENTS.md`, and its `### Phase N — <name>` sub-headings (em dash).
- Produces: nothing later tasks rely on.

- [ ] **Step 1: Write the failing tests — create `tests/test_docs.py`**

```python
"""test_docs.py — the repo's own docs, where they lean on packaged doctrine.

README.md and docs/serve-mcp.md do not describe how work in a workspace is
sequenced: the packaged AGENTS.md does, under "The working sequence", and
these two link to it (#111). That was a deliberate choice against three
prose copies -- the README's scaffold inventory has already drifted from
MANIFEST once, silently (#37) -- and a choice nothing enforces is a choice
that lasts until the next well-meant edit. So:

  * each doc must link the section, and the link must resolve -- to the
    packaged file, at a heading that exists;
  * the README's five-line outline, the one thing that IS restated, must
    match the doctrine's phase headings, names and order.

Read from the repo tree, not from the installed package: the link targets
are repo paths, and that is the file a reader following one lands on.
"""

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOCTRINE = REPO / "src" / "bunnyforge" / "data" / "doctrine" / "AGENTS.md"
LINKING_DOCS = ("README.md", "docs/serve-mcp.md")
ANCHOR = "the-working-sequence"


def _slug(heading: str) -> str:
    """GitHub's heading anchor: lowercased, punctuation dropped (hyphens
    and underscores survive), each space a hyphen."""
    kept = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return kept.replace(" ", "-")


class TestDocsLinkTheWorkingSequence(unittest.TestCase):

    def test_each_doc_links_the_section_and_the_link_resolves(self):
        doctrine = DOCTRINE.read_text(encoding="utf-8")
        slugs = {_slug(h) for h in
                 re.findall(r"^#{1,6} (.+)$", doctrine, re.MULTILINE)}
        self.assertIn(ANCHOR, slugs,
                      "AGENTS.md has no 'The working sequence' heading")
        for name in LINKING_DOCS:
            with self.subTest(doc=name):
                doc = REPO / name
                links = re.findall(r"\]\(([^)\s#]*AGENTS\.md)#([^)\s]+)\)",
                                   doc.read_text(encoding="utf-8"))
                self.assertIn(
                    ANCHOR, [anchor for _target, anchor in links],
                    f"{name} no longer links the working sequence — it "
                    "must link it rather than restate it (#111)")
                for target, anchor in links:
                    self.assertEqual((doc.parent / target).resolve(),
                                     DOCTRINE.resolve(), f"{name}: {target}")
                    self.assertIn(anchor, slugs,
                                  f"{name}: #{anchor} matches no heading")

    def test_the_readme_outline_matches_the_phase_headings(self):
        phases = re.findall(r"^### Phase (\d) — (.+)$",
                            DOCTRINE.read_text(encoding="utf-8"),
                            re.MULTILINE)
        self.assertTrue(phases, "no '### Phase N — name' headings found; "
                                "an empty list would match vacuously")
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertIn("\n## Working in a workspace\n", readme)
        section = readme.split("\n## Working in a workspace\n", 1)[1]
        section = section.split("\n## ", 1)[0]
        outline = re.findall(r"^(\d)\. \*\*(.+?)\*\*", section, re.MULTILINE)
        self.assertEqual(
            outline, phases,
            "README.md's outline and AGENTS.md's phase headings disagree "
            "— the doctrine is canonical; bring the README in line")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run and watch both fail**

Run: `.venv/bin/python -m unittest -v tests.test_docs 2>&1 | tail -15`
Expected: 2 FAIL — the first on `README.md no longer links the working sequence`, the second on `'\n## Working in a workspace\n' not found`.

- [ ] **Step 3: Add the README section**

Insert between the last paragraph of `## The workspace` (ends "…see [VS Code integration](#vs-code-integration) above.") and `## Names`:

```markdown
## Working in a workspace

Day to day, a campaign workspace is worked *with an agent* — over MCP
([`docs/serve-mcp.md`](docs/serve-mcp.md)) or directly on the files — and
the work has a fixed shape. The agent's doctrine carries it in full, as
[The working sequence](src/bunnyforge/data/doctrine/AGENTS.md#the-working-sequence);
in outline:

0. **Orient** — load the campaign overview and the doctrine, then ask
   whatever the request left open, once.
1. **Decide what kind of file this is** — a writeup (true always), a brief
   (true this session) or a record (what happened). The kind decides what
   is still owed after the file lands.
2. **New material** — check what exists, draft, review, promote, index,
   verify. A draft stays outside canon until you promote it.
3. **Revising existing canon** — a proposed revision, reviewed as a diff;
   one that canon has moved under is refused rather than applied.
4. **Inbound extraction** — material brought in from elsewhere becomes
   drafts, and only when you ask.

A test binds that outline to the doctrine's phase headings, so the two
cannot quietly fall out of step. The rules themselves live only there —
and because `serve-mcp` serves that file to the agent, you can also just
ask the agent to walk you through it.
```

- [ ] **Step 4: Add the `docs/serve-mcp.md` paragraph**

Insert directly under the `## What the agent can do` heading, before the `**Read canon:**` paragraph, with a blank line on each side:

```markdown
This section is an inventory: what each tool does. The *order* to use them
in — and what is still owed when a step finishes — is the agent's own
doctrine: the packaged `AGENTS.md`, under
[The working sequence](../src/bunnyforge/data/doctrine/AGENTS.md#the-working-sequence).
It reaches the agent as the `bunnyforge://doctrine/AGENTS.md` resource, so
asking the agent to walk you through it works too.
```

- [ ] **Step 5: Run and watch both pass**

Run: `.venv/bin/python -m unittest -v tests.test_docs 2>&1 | tail -8`
Expected: 2 tests, OK.

- [ ] **Step 6: Mutation check — the outline test must catch a reorder**

```bash
sed -i '' 's/^2\. \*\*New material\*\*/2. **New stuff**/' README.md
.venv/bin/python -m unittest tests.test_docs 2>&1 | tail -6
sed -i '' 's/^2\. \*\*New stuff\*\*/2. **New material**/' README.md
.venv/bin/python -m unittest tests.test_docs 2>&1 | tail -3
```
Expected: FAIL (`README.md's outline and AGENTS.md's phase headings disagree`), then OK.

- [ ] **Step 7: Read both rendered links once**

`grep -n "the-working-sequence" README.md docs/serve-mcp.md` — expect one hit each; the README's target has no `../`, the guide's has exactly one. (The test already proves both resolve; this is the 10-second human check that they are the links you meant.)

- [ ] **Step 8: Commit**

```bash
git branch --show-current   # docs/111-working-sequence
git add tests/test_docs.py README.md docs/serve-mcp.md
git commit -m "docs: README outlines the working sequence, serve-mcp.md links it — both under test (#111)" -m "One full copy lives in the packaged AGENTS.md. serve-mcp.md links it and restates nothing; the README restates only the five phase names, and tests/test_docs.py binds those, and both links, to the doctrine's headings." -m "Co-Authored-By: <the model this session was asked to run as> <noreply@anthropic.com>"
```

---

### Task 3: Changelog, the full CI gates, and the PR

**Files:**
- Modify: `CHANGELOG.md` (`## [Unreleased]`, lines 16-31)

**Interfaces:**
- Consumes: Tasks 1 and 2, committed.
- Produces: the PR.

- [ ] **Step 1: Add the changelog entries**

Under `## [Unreleased]` → `### Added`, append after the existing #110 bullet:

```markdown
- **The working sequence.** Packaged `AGENTS.md` gains a section giving
  the end-to-end order of work in a workspace — orient, decide what kind
  of file this is, new material, revising existing canon, inbound
  extraction — and what is still owed when each step finishes. It says
  what no document did: that `promote_draft` is one tool for new drafts
  and proposed revisions alike; that by default promotion is the GM's, by
  hand; that the compendium entry rides a proposed revision of
  `compendium.md`; that nothing orders two drafts which link to each
  other; and that moving spent inbound source to `_Done/` is manual. The
  README outlines it and `docs/serve-mcp.md` links it — neither restates
  it, and tests bind the outline, both links, the section's tool names
  and its default `compendium_dirs` list to their sources.
  **Existing workspaces:** adopt the new `AGENTS.md`
  ([`docs/adopting-doctrine.md`](docs/adopting-doctrine.md)). (#111)
```

Under `### Changed`, append after the existing #110 bullet:

```markdown
- Doctrine no longer says *every* new file needs a compendium line.
  `AGENTS.md` § File conventions and the scaffolded `compendium.md` now
  say what the code always did: only files in a `compendium_dirs` section
  are indexed, and briefs and session records must not be. The
  `compendium.md` stub is scaffold-once, so that half reaches new
  workspaces only. (#111)
```

- [ ] **Step 2: Commit**

```bash
git branch --show-current   # docs/111-working-sequence
git add CHANGELOG.md
git commit -m "docs(changelog): the working sequence, and the indexing correction (#111)" -m "Co-Authored-By: <the model this session was asked to run as> <noreply@anthropic.com>"
```

- [ ] **Step 3: Run every CI gate, from the committed tree**

Use superpowers:verification-before-completion. All four, in order, from the worktree root:

```bash
.venv/bin/python -m unittest discover -s tests -t . 2>&1 | tail -4
.venv/bin/python tests/check_portability.py | tail -1
T=$(mktemp -d) && .venv/bin/bunnyforge init "$T/demo" --name Demo && .venv/bin/bunnyforge review checkup --workspace "$T/demo"; rm -rf "$T"
git status --porcelain; test -z "$(git status --porcelain)" && echo CLEAN
```
Expected: `Ran 995 tests … OK` (987 + 6 + 2) with **no new skips**; `PASSED (seed=…)`; checkup `0 error(s), 0 warning(s)`; `CLEAN`. Report the actual numbers you saw, not these.

CI's `suite` job runs *without* the mcp extra, where the tool-name test skips by design; the `mcp-suite` job runs it. Nothing to do — but do not be surprised by the skip count differing between the two jobs.

- [ ] **Step 4: The human read that #65 cannot do yet**

Re-read the inserted `## The working sequence` section and the two qualified sentences once, as prose, for anything campaign-specific — a name, a place, a house term that is not `mira-venn` / `session-014` / a default directory. #65 is open, so nothing mechanical screens packaged prose; this read is the basis of the PR's portability claim. Also check each phase against the **Facts verified** list above one more time: the section is only worth having if every claim in it is true.

- [ ] **Step 5: Push and open the PR**

Scan the outgoing diff for secrets if the pre-push hook reports gitleaks missing (there should be none: prose and tests only).

Use the `dcltdw:opening-a-pr` skill — bunnyforge has no repo-local CLAUDE.md and no `pr-rigor` check, so the skill's own five sections apply unmodified, with its `Agent:` / `Model / version:` provenance fields. The body must include:
- `Closes #111`.
- Both design decisions in one paragraph each (section-not-new-doc; link-by-default with the README outline under test), and the three corrections to the issue's draft.
- That the portability claim for the packaged prose rests on a deliberate human read (#65 open).
- The verification numbers from Step 3, as observed.
- Note for the reviewer: the plan (`docs/superpowers/plans/2026-09-21-working-sequence.md`) rides in this PR and carries the design in place of a separate spec.

Follow the skill for the board card (project 7, "bunnyforge split"; the card was in **Todo** when this plan was written). Then **stop and wait for dcltdw's approval** — do not merge.

---

## Self-review (done at plan time)

- **Issue coverage:** the sequence (Phases 0-4) → Task 1 Step 5; which file kind / compendium owed → Phase 1 + the `compendium_dirs` test; `promote_draft` handles both → Phase 3 step 4 + "same tool" needle; two linked drafts → Phase 2 closing paragraph + needle; inbound and the manual `_Done/` move → Phase 4 + needles; README → Task 2 Step 3; served to the agent → it is in `AGENTS.md`, already in `DOCTRINE_FILES`, no code change; single source of truth → `tests/test_docs.py` + the Task 1 pins; post-merge comment (the #110 reminder; `AGENTS.md` silent on it) → Phase 2 step 6.
- **Not done, deliberately:** no tool inventory in the README (the issue's "Not proposed"); no change to `docs/adopting-doctrine.md`; no change to `serve_mcp.py`; no change to § Direct edits to canon — the sequence owns "what is owed", that section owns "when you may".
- **Name consistency:** heading `## The working sequence` / anchor `the-working-sequence` / phase regex `^### Phase (\d) — (.+)$` (em dash) are identical across Task 1's tests, Task 2's tests, the doctrine block, and both links. README outline items are the five phase names verbatim.
