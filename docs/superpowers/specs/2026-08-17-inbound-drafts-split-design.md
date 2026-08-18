# Inbound/drafts split for serve-mcp — design

Date: 2026-08-17
Status: approved (brainstormed with the GM; adversarially reviewed; findings
triaged and folded in)
Builds on: docs/superpowers/specs/2026-08-16-serve-mcp-design.md, PR #60
(issue #59, "feat: serve-mcp read-only staging access")

## Problem

PR #60 gave the MCP agent read-back over the staging directory, but the
directory it read was doing two jobs under one name. `staging_dir`
(default `_ExtractInbound`) holds both:

1. **Agent output** — `save_draft` and `propose_revision` write there, and
   `list_staged`/`read_staged` read it back as "your own inbox".
2. **The GM's inbound queue** — material the GM generated elsewhere
   (`.txt`, `.html`, `.md`), awaiting an agent's help extracting it into
   proper entity files.

The conflation produces real defects in the live workspace: the
`rglob("*.md")` filter hides 17 of 18 inbound files; the one it surfaces
(`_ExtractInbound/README.md`) is mislabelled `"revision"` because a root
`README.md` happens to exist; and the tool descriptions ("use it to pick
up drafts from an earlier session") actively contradict the workspace
AGENTS.md contract for the queue ("Read it only when I ask you to
extract"). The GM's verdict: "staged" is the wrong name for any of this.

The GM's system model, which this design is measured against:

- **Inputs:** player perceptions from the wiki (existing flow, untouched);
  GM ideas landing in `_ExtractInbound/`; agent-generated content not yet
  approved.
- **Output:** approved material flows into the canonical sections.
- **Division of labor:** the claude.ai web agent over MCP is the *primary
  writing instrument*, across many sessions. The VSCode agent works on
  bunnyforge code, rarely on campaign writing. The GM reviews and
  promotes. The MCP tool surface is the main highway for the whole
  writing process, not a side door.

## Settled inputs

Decided by the GM before design; not revisited here:

1. Agent output moves to its own directory; `_ExtractInbound` becomes
   purely the GM's inbound queue.
2. Both agents (VSCode and MCP) may extract from the queue, under the
   existing AGENTS.md contract.
3. The queue is read **only when the GM asks**. The agent may notice it
   is non-empty and offer; it may not process it unbidden. Tool
   descriptions must encode this.
4. No move capability over the inbound queue in this release (the
   extract → show → confirm → move-to-`_Done/` step stays with whoever
   can move files). Design so adding it later is not a rewrite.
5. `search` stays canon-only.

Decided during design review (GM chose the maximal options):

6. `promote_draft` ships now, behind `--allow-direct-edits`.
7. Revision shadows carry base-hash tracking (not mtime, not deferred).
8. `save_draft` grows a `subdir` parameter for nested briefs.

## 1. Naming and vocabulary

Two directories, two word-families. "Staged"/"staging" survives nowhere —
not in tools, config keys, method names, docs, or error messages.

| concept | directory | config key | tools | vocabulary |
|---|---|---|---|---|
| Agent output awaiting GM review | `_AgentDrafts/` (new) | `drafts_dir` | `save_draft`, `propose_revision`, `update_draft`, `list_drafts`, `read_draft`, `promote_draft` | "drafts" |
| GM material awaiting extraction | `_ExtractInbound/` (unchanged on disk) | `inbound_dir` (replaces `staging_dir`) | `list_inbound`, `read_inbound` | "the inbound queue" |

- `_AgentDrafts` over `_Proposals`: the GM browsing the workspace sees
  *whose* material it is, and `save_draft` already speaks the word.
- Within `list_drafts`, `kind` is `"new" | "revision"` (was
  `"draft" | "revision"`): everything in the directory is a draft, so
  what discriminates is whether it proposes new content or revises an
  existing file.
- Store methods match their tools: `stage_draft`/`stage_revision` rename
  to `save_draft`/`propose_revision`; `list_staging`/`read_staged` are
  replaced by the four read methods above.

## 2. Config and migration

- `Config` gains `drafts_dir` (default `"_AgentDrafts"`) and renames
  `staging_dir` → `inbound_dir` (default `"_ExtractInbound"`).
- **Both are auto-excluded at load time**, alongside `MANDATORY_EXCLUDES`:
  `exclude_dirs = user's list | MANDATORY_EXCLUDES | {inbound_dir,
  drafts_dir}`. No configuration can un-exclude either special directory.
  `_ExtractInbound` drops out of the default `exclude_dirs` list and out
  of the `campaign.toml.in` comment block — keeping it there would be the
  second copy of a default that the template itself warns against.
- **Validation:** `ConfigError` when `drafts_dir` or `inbound_dir` names
  any entry of `entity_dirs`/`inherit_dirs`, or when the two name the
  same directory — either collision would silently exclude a canon
  section from every walker, or silently recreate the conflation this
  design exists to kill. Same pattern as the existing
  entity/inherit overlap check.
- **`staging_dir` in campaign.toml → hard `ConfigError`** naming the
  rename (`workspace.staging_dir was renamed — use inbound_dir`).
  `load()` ignores unknown keys, so without this the old key would be
  silently dropped and the workspace would quietly fall back to the
  default. The scaffold never shipped the key, so this trips
  approximately nobody, but the failure it prevents is silent.
- **No migration script.** Workspaces created by `init` have the whole
  `[workspace]` block commented out, so new defaults apply on upgrade
  with zero edits. `init` needs no new scaffolding: `save_draft`
  `mkdir -p`s its destination, so `_AgentDrafts/` appears on first use.
- **Release note, one line:** agent-written drafts still sitting in
  `_ExtractInbound/` from the old scheme should be moved to
  `_AgentDrafts/` or deleted; a `staging_dir` key in `campaign.toml`
  must be renamed to `inbound_dir`. (The live workspace's queue is all
  GM material, so no server-start detection is warranted.)

## 3. Store surface and guards

All behaviour on `WorkspaceStore` (stdlib only — it remains the swap seam
for a hosted git-backed backend, issue #43), in the existing
instructive-`StoreError` style: every refusal names the valid next move.

Shared rule for **both** directories: any path component beginning with
`_` below the family root is never listed, read, or written. This is the
workspace's own underscore-means-machinery convention; it makes
`_ExtractInbound/_Done/` unreadable without being named in code, and
makes `_AgentDrafts/_Rejected/` a workable GM rejection signal for free.
Each family gets one private resolver enforcing: no workspace escape,
inside the family root, no `_` component. The inbound resolver is the
deferred-move provision — a future `mark_extracted(path)` is one new
method reusing it (its `_Done/` *destination* is constructed internally,
not through the reader's resolver).

`_canonical()` is unchanged: both directories arrive in `exclude_dirs`
via config, so canon tools refuse them exactly as they refuse `_Ignore/`.

### Drafts family (agent output; read and write)

Names are slugified on write: lowercase; spaces and underscores become
hyphens; apostrophes drop; runs of hyphens collapse; leading/trailing
hyphens strip; empty result is refused. Input is still validated by
`_DRAFT_NAME_RE` first. The display title lives in front matter, where
the workspace convention already puts it. Slugs make the drafts tree
mirror canon (`_AgentDrafts/<section>/[<subdir>/]<slug>.md` ↔
`<section>/[<subdir>/]<slug>.md`), which is what lets `promote_draft`
derive its destination.

- `save_draft(section, name, content, subdir=None)` — writes
  `drafts_dir/<section>/[<subdir>/]<slug>.md`. `subdir` is validated by
  the same regex, slugified the same way, one level deep (nested briefs:
  `Briefs/session-015/<name>.md`). `perceptions_dir` is not draftable —
  the perception record is by contract never agent-authored. Refuses if
  the draft already exists (naming `update_draft`), and refuses if the
  **mirrored canonical file exists** (naming `propose_revision`) — a new
  draft colliding with a canonical name would otherwise be misreported
  as a revision and reviewed as a diff against the wrong entity.
- `propose_revision(path, content)` — target must be an existing
  canonical `.md` (as today); writes the shadow copy and records its
  **base** (below). Refuses if a shadow for `path` already exists,
  naming `read_draft` + `update_draft` — the previous latest-wins rule
  silently destroyed pending proposals, which the end-of-session ritual
  ("draft the updates" to front-burner, compendium, open-questions)
  makes routine, not rare.
- `update_draft(path, content)` — **the single overwrite door.** `path`
  must be an existing `.md` under `drafts_dir` (so the agent necessarily
  listed or read first). For a revision shadow, refreshes the recorded
  base to current canon — the refusal flow that led here already forced
  a read-and-merge.
- `list_drafts()` — sorted rows over `rglob("*.md")` (everything here is
  agent-written `.md` by construction), skipping `_` components:
  `{path, kind, title, summary}` with `stale` added on revision rows.
  `title`/`summary` come from front matter via the same extraction
  `list_entities` uses — thirty accumulated drafts must not cost thirty
  reads to find one. `kind` is `"revision"` iff the mirrored canonical
  file exists; sound now that only agent output lives here.
  `stale: true|false|null` — whether canon changed since the proposal's
  base was recorded; `null` when no base is on record.
- `read_draft(path)` — resolver guards, `.md`, exists; refusals name
  `list_drafts` and `read_entity`.
- `promote_draft(path)` — see §5.

### Base tracking

One manifest: `drafts_dir/.proposal-bases.json` (stdlib `json`; dot-file,
invisible to every walker and to `list_drafts`), mapping
workspace-relative shadow path → SHA-256 of the canonical file's bytes at
proposal time. `propose_revision` records; `update_draft` refreshes;
`promote_draft` verifies and removes; every write prunes entries whose
shadow no longer exists. A missing or unparseable manifest is treated as
empty (all bases unknown → `stale: null`), never an error: it is a cache
of provenance, not a lock file.

Rejected alternatives: sidecar-per-file (clutters the GM's view of the
drafts tree), front-matter injection (mutates agent-authored content),
mtime comparison (git checkouts refresh mtimes; a hint that lies invites
misplaced trust).

### Inbound family (GM queue; read only)

- `list_inbound()` — sorted `{path, readable}` over **all files** under
  `inbound_dir`, skipping `_` components. Every extension is listed: a
  listing that hides files is precisely the defect being fixed. `readable`
  is `suffix in {".md", ".txt", ".html", ".htm"}` — a PDF or image
  appears in the list, honestly marked unreadable.
- `read_inbound(path)` — resolver guards, then the suffix allowlist
  ("not a text format serve-mcp can return — ask the GM to convert or
  summarize it"), then exists. Reads with `errors="replace"`: this is
  foreign material generated elsewhere, and one stray non-UTF-8 byte in
  a GM's `.txt` must not crash the tool. Canon and drafts stay strict —
  they are workspace-authored.

## 4. Tool registrations, descriptions, campaign_overview

Descriptions are the contract's enforcement surface; each family states
its own.

- `save_draft` / `propose_revision` / `update_draft` — destination is
  "your drafts directory", for GM review and promotion.
- `list_drafts` / `read_draft` — keep the resume nudge, correct for this
  material: "your own unpromoted drafts from this and earlier sessions …
  pick one up and merge rather than writing it again. Nothing here is
  canon."
- `list_inbound` / `read_inbound` — encode the AGENTS.md contract:
  "The GM's inbound queue: material the GM authored elsewhere, awaiting
  extraction into proper entity files. Call this only when the GM asks
  you to extract. Do not act on its contents unbidden. Nothing in it is
  canon — it is unreviewed source material." **Both** tools sit under
  only-when-asked: the offer the agent is permitted to make comes from
  the overview count alone, not from unbidden filename enumeration.
- `campaign_overview` — `overview()` gains `inbound_pending` (defined as
  exactly `len(list_inbound())`, all files counted, readable or not) and
  `drafts_pending` (`len(list_drafts())`). Both are `0` when the
  directory is absent — a count field is always present, and "nothing
  pending" is the true answer either way (deliberately simpler than the
  sections' absent-vs-empty rule). The docstring states the permission
  boundary: if `inbound_pending` is non-zero you may mention it and
  offer to extract; do not list or read the queue unless asked.

## 5. Promotion

`promote_draft(path)` — registered only under `--allow-direct-edits`,
the same philosophy as `write_entity`: the capability is gated per-run at
server start; the GM's in-chat approval is the actual gate per call.

- Destination is **derived**: strip the `drafts_dir` prefix. No `dest`
  parameter to get wrong; slugs and `subdir` made the trees mirror.
- `kind: "new"` — the canonical target must **not** exist; parent
  directories are created as needed.
- `kind: "revision"` — the target must exist, and the recorded base must
  still match canon. Stale or unknown base → refusal naming the re-merge
  flow (`read_entity` current canon → `update_draft`, which re-baselines
  → retry). A stale shadow is *refused at promotion, not silently
  applied* — promoting it would revert the GM's interim canon edits,
  disguised inside an intended diff.
- Refuses outside a git repository, exactly as `write_entity` does:
  writes the target, removes the draft (and its manifest entry), stages
  both paths, commits once as `serve-mcp: promote <path>`.
- Deliberately **not** included: compendium or front-burner updates.
  Promotion moves one file; the end-of-session ritual already covers
  index updates via `propose_revision`, and the docs say so — promotion
  must not grow a hidden second job.

## 6. Documentation

- **`docs/serve-mcp.md`** — "What the agent can do" restructures around
  three vocabularies: **canon** (read tools, unchanged), **drafts** (the
  write tools land in `_AgentDrafts/`; `list_drafts`/`read_draft` read
  them back; `update_draft` iterates; `promote_draft` under
  `--allow-direct-edits`; promotion otherwise manual and the GM's),
  **inbound queue** (`_ExtractInbound/` is the GM's; `list_inbound`/
  `read_inbound` under the only-when-asked contract; `_`-prefixed
  subdirectories invisible; non-text files listed but refused on read).
  "Staging" leaves the document. The config paragraph documents
  `drafts_dir`/`inbound_dir` and notes both are always excluded from
  canon regardless of `exclude_dirs`.
- **`src/bunnyforge/data/doctrine/AGENTS.md`** (the scaffold) —
  - The directory taxonomy gains `_AgentDrafts/`: the agent's outbox;
    speculative by definition, never canon; agents may read it freely;
    a draft the GM rejects is deleted or moved to
    `_AgentDrafts/_Rejected/` (never read, like `_Done/`).
  - The `_ExtractInbound` section notes the MCP agent reaches the queue
    through `list_inbound`/`read_inbound` under the same contract, and
    rephrases the `_Done/` move per-surface: "move the spent source into
    `_ExtractInbound/_Done/` — or, if you cannot move files, say so and
    I will" — the current absolute phrasing orders the MCP agent to do
    something it cannot, inviting apology loops or false claims.
- **The live workspace's AGENTS.md** — the GM applies the same two
  edits; suggested text in the appendix. Code and this repo's docs do
  not depend on it.

## 7. Testing

TDD throughout; stdlib `unittest` against temp workspaces, matching the
existing suite.

- **Config:** defaults for both keys; auto-exclusion survives a custom
  `exclude_dirs` that omits them; `staging_dir` key raises the rename
  error; section/each-other collision validation.
- **Drafts:** slugify (spacing, apostrophes, case, empty); `subdir`
  validation and one-level depth; canonical-collision refusal;
  existing-draft refusal names `update_draft`; `propose_revision`
  refuses on existing shadow; `update_draft` overwrite + re-baseline;
  `list_drafts` kinds, titles/summaries, stale tri-state, `_` skip;
  `read_draft` refusals; canon tools refuse drafts paths;
  `perceptions_dir` not draftable.
- **Base manifest:** record/refresh/verify/prune lifecycle; missing and
  corrupt manifest read as empty.
- **Inbound:** `list_inbound` surfaces `.txt`/`.html`/`.md`, marks
  `.pdf` unreadable, skips `_Done/` and any `_` component (tested before
  `_Done/` ever exists in the wild — the trap named in the constraints);
  `read_inbound` refusals (canonical path, `_Done/`, non-text, missing);
  non-UTF-8 bytes return replaced characters.
- **Overview:** both counts agree with their listings; `0` when the
  directory is absent.
- **Promotion:** new/revision happy paths (file moved, manifest entry
  gone, one commit); stale and unknown-base refusals; target-exists
  refusal for `"new"`; non-git refusal; absent without
  `--allow-direct-edits`.
- **Tool layer:** registered names updated; one regression test pins the
  contract phrase ("only when the GM asks") in `list_inbound`'s
  description — deliberately, since a description saying the opposite is
  the live bug this redesign fixes.

## Adversarial review disposition

An adversarial subagent review traced the GM's three input flows through
the design. Its verdict shaped §§3–5: the directories and reads were
sound, but the write side of `_AgentDrafts/` had single-session
semantics (never-overwrite, latest-wins, no state, no metadata) under a
multi-session convergent workflow. Accepted findings: draft iteration
dead-end (→ `update_draft`); latest-wins clobbering (→ shadow-exists
refusal); no promotion path (→ `promote_draft` + slugs); rejection
unrepresentable (→ `_` skip + `_Rejected/` convention); AGENTS.md
contradictions (→ §6 edits); new-draft/canon collision (→ `save_draft`
refusal); flat briefs (→ `subdir`); discovery gap (→ `drafts_pending`,
richer `list_drafts` rows); stale shadows (→ base tracking); count
semantics (→ defined as the listing's length); config collisions (→
validation). Rejected: a server-start warning for legacy drafts in the
queue (the live queue is all GM material; the release note suffices).
The review could not break: the path-guard model, `_Done/` protection,
notice-and-offer, the perceptions flow, and publishing isolation.

## Appendix: suggested edit to the live workspace's AGENTS.md

Under the directory rules (alongside `_Ignore/`, `_Archive/`,
`_ExtractInbound/`):

> - `_AgentDrafts/` is the agents' outbox: drafts and proposed revisions
>   awaiting my review, written there by the MCP tools (or by you, if I
>   ask you to draft something). Read it freely; nothing in it is canon.
>   If I reject a draft I delete it or move it to `_AgentDrafts/_Rejected/`,
>   which is never read, like `_Ignore/`.

In the "Extracting from _ExtractInbound/" section, after the existing
bullets:

> - The MCP agent reaches this queue through `list_inbound` and
>   `read_inbound`, under exactly these rules.

And rephrase the move step:

> - Once I confirm an extraction, move the spent source into
>   `_ExtractInbound/_Done/` — or, if you cannot move files, say so and
>   I will.
