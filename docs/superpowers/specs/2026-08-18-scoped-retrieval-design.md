# Scoped retrieval: live vs Archive/ — design

**Date:** 2026-08-18
**Issue:** https://github.com/dcltdw/bunnyforge/issues/66
**Status:** approved design, awaiting implementation plan
**Depends on:** #62 (landed as PR #67) — `Archive/` is ordinary walked canon,
mirrored section layout, walked by `iter_content_files` and served by every
MCP retrieval tool.

## The problem

With #62 landed, `search` and `list_entities` return live and archived
material together, distinguishable only by the `Archive/` path prefix. That
is the right *default* — the uniform behavior is a decision of record — but
it leaves the retrieval ergonomics unaddressed. The ticket names three use
cases:

1. **Generating a new story about a new place.** Archived material can
   contaminate the invention even when labelled: material read is material
   that shapes the output. This case wants archive material *absent at
   retrieval time*, not merely marked.
2. **Brainstorming about an established place or character.** The historical
   context is exactly what is wanted: archive-only, or both.
3. **New story in an established space.** Current player perceptions *and*
   the history of the last visit — two deliberate retrievals, composed.

Between design and this spec, use case 1 sharpened into something better
(§4): whether new invention draws on history is a *choice the GM owns*, not
a rule the tooling can hard-code — a successor faction rising from a retired
one's ashes is deliberate; a "new" place that quietly re-skins a retired one
is contamination. Same retrieval, opposite intent, and only the GM can tell
them apart.

## Decisions record

Settled on the ticket and in brainstorming with the GM, 2026-08-18:

| question | decision |
|---|---|
| Default scope | The union of live and archive — the uniform behavior #62 ships stays the default (ticket record). |
| Scope token names | `live` \| `archive` \| `both`. `both` rather than `all`: the domain has exactly two trees, and #62's `_`-means-not-canon design makes that structural (there is live canon and there is `Archive/`; a third tree has nowhere to come from). |
| Self-aware results | Every search hit and listing row carries `archived: true|false` — always present, never inferred from the path (ticket record). |
| scope × section | **Scope-resolved**: `section` resolves inside the chosen scope's tree. Under `scope="archive"`, `section="NPCs"` means `Archive/NPCs/`. Under the default `scope="both"`, `section` keeps today's top-level meaning exactly — every existing call is backward-identical. |
| The asymmetry | Accepted and documented: `scope="both"` + `section="NPCs"` returns live NPCs only (today's behavior), not the union of the live and archive resolutions. Backward-identical defaults are what it buys. |
| `campaign_overview` | Additive only: `sections` keeps its exact shape; a new `archive_sections` key breaks the archive down by mirror section. |
| Guidance home | Doctrine as primary (packaged `AGENTS.md`), tool descriptions carry the condensed form and point at the doctrine resource. |
| What the doctrine says | Not a use-case→scope mapping. **Scope is the GM's call, asked once at task start** (§4). |
| Revisions | No new-vs-revision carve-out. The scope attaches to the *work*, not the tool or the conversation: revising a piece later is the same creative task resumed, under the scope that governed its creation. |
| CLI surfaces | No change. `review` must validate all canon; exports follow visibility rules uniformly (#62); the GM has the filesystem. |
| Sequencing | #68 lands first, then #66; one release carries #62 + #68 + #66. Nothing released has seen #62's intermediate MCP behavior, so additive shape choices here are externally invisible until that release. |
| Generalization | The task-start ask is the first instance of a broader "establish context before work begins" doctrine — filed as #70, out of scope here. |

## Design

### 1. Parameter shape and semantics

`search` and `list_entities` gain `scope: str = "both"`. Valid values
`"live"`, `"archive"`, `"both"`; anything else is a `StoreError` naming the
valid values. A file is *archived* iff its first workspace-relative path
component equals `config.archive_dir`.

New signatures:

```python
def search(self, query: str, section: str | None = None,
           scope: str = "both") -> list[dict]: ...
def list_entities(self, section: str, scope: str = "both") -> list[dict]: ...
```

Semantics, by scope:

- **`both`** (default): today's behavior verbatim. `section` names the
  top-level directory; `Archive` is its own section (#62's record — live
  section listings stay uninflated). The only observable change is the new
  `archived` field on results (§2).
- **`live`**: archived files are excluded from the walk's results. `section`
  keeps its top-level meaning. Root docs are live and stay included in
  unsectioned search. `section="Archive"` + `scope="live"` is a
  contradiction and is refused with a `StoreError` that names the working
  alternatives (drop the section, or use `scope="archive"`).
- **`archive`**: archived files only, and `section` resolves *inside* the
  archive tree by mirror: `section="NPCs"` matches `Archive/NPCs/*` (first
  component is the archive dir, second is the section); `section=None` or
  `section="Archive"` means the whole archive. Section validation is
  unchanged (`_check_section`; unknown sections get the existing error).
  Files directly at `Archive/*.md` (no mirror) appear in whole-archive
  queries and in no mirror section — consistent with #62's
  default-to-entity handling of strays: visible, never a silent hole.

Untouched surfaces: `read_entity` (path-addressed; the caller knows what it
asked for), `generate_names`, the drafts and inbound families, and the write
side — `propose_revision`/`write_entity` keep accepting archive paths, which
are ordinary canon (#62).

### 2. Self-aware results

Every `list_entities` row and every `search` hit gains
`"archived": true|false`, computed from the first path component, present on
every element — so an agent buckets results without path parsing. The
search-truncation sentinel row (`{"path": "", "snippet": "(truncated …)"}`)
is a notice, not a result, and is unchanged. Draft and inbound listings are
not canon and get no marker.

Adding a key to result dicts is additive; nothing released consumes these
shapes yet (see sequencing decision).

### 3. `campaign_overview`

`sections` keeps its exact current shape: live top-level counts plus the
flat `Archive` total. One new key:

- `archive_sections`: counts of archived files by mirror section, using the
  same counting rule one level down — count `parts[1]` when
  `len(parts) > 2`. `Archive/NPCs/old-hag.md` counts under `"NPCs"`; a stray
  `Archive/x.md` is in the `Archive` total but no breakdown entry, exactly
  symmetric with how root docs are absent from `sections` today.
- Existence rule mirrors `sections`: the key is present only when the
  archive directory exists. A campaign that has never retired anything sees
  no `archive_sections`, absent-not-empty, the same philosophy the
  `sections` comment already records.

### 4. Guidance: scope is the GM's call, asked at task start

**Doctrine (primary home).** A short subsection in packaged
`data/doctrine/AGENTS.md`, adjacent to the existing "Do not present
`Archive/` material as current" bullet, in the doctrine's first-person GM
voice. Draft text — final wording at implementation, subject to the human
vocabulary read (§7):

> ### Retrieval scope: live, archive, or both
>
> - When answering questions or reporting what is established, read live
>   and archived material freely. Results are labelled, and the rules above
>   govern presentation: the archive is never current, and where it
>   disagrees with a live file, the live file wins.
> - Creative work on canon — inventing new material, or revising it later —
>   runs under a retrieval scope I own. Drawing on retired material can be
>   deliberate (a successor, an echo) or contamination (a "new" thing that
>   quietly re-skins a retired one). Labels do not protect generation:
>   material read is material that shapes the output. Only I can tell the
>   two intents apart.
> - So at the start of a task that will create or revise canon, ask me
>   whether its retrieval should be live-only, archive-only, or both —
>   unless my request already answers it, or the work's scope is already
>   established. The scope attaches to the work and persists: picking a
>   piece back up later continues under the scope it was made with. One ask
>   per task; hold it until the task changes or I re-scope it.
> - Mechanically: over MCP, pass `scope=` to `search` and `list_entities`;
>   on the filesystem, read or skip `Archive/` accordingly.

This governs filesystem agents (who never see MCP tool descriptions) as
well as the MCP surface, which is why the doctrine is the primary home. The
hand-reconcile cost to live campaigns is accepted: this release already
carries #62's edits to the same doctrine passages, so campaigns hand-diff
that region of `AGENTS.md` once either way.

**Tool descriptions (condensed form).** `search` and `list_entities`
docstrings gain roughly: *scope narrows retrieval to live canon only
(`"live"`), archived canon only (`"archive"`), or both (default; every
result is labelled `archived`). Under `scope="archive"`, `section` names
the mirrored section inside the archive (`section="NPCs"` →
`Archive/NPCs/`). When gathering material for creative work, the scope is
the GM's call — ask at task start if the request hasn't said. The AGENTS.md
doctrine resource carries the full rule.* `campaign_overview`'s description
mentions `archive_sections`. Final wording at implementation; also subject
to the human vocabulary read.

### 5. CLI surfaces: no change

Recorded as a decision, no code. `review`/checkup must validate *all*
canon — a scope parameter there would weaken the validator. Exports follow
per-file visibility rules uniformly, archive included (#62's decision). The
GM browsing history has the filesystem, where #62's layout (`Archive/` as a
plain mirrored tree) is already the ergonomic answer.

### 6. Implementation shape

All filtering lives in `_store.py`; `serve_mcp.py` only threads the new
parameter through the tool signatures and updates docstrings.

- One scope validator (valid-token check) and one match predicate shared by
  `search` and `list_entities`, so the two tools cannot drift: given a
  workspace-relative path's parts, the configured archive dir, a section,
  and a scope, decide membership. The contradiction refusal
  (`live` + `Archive`) lives beside the validator.
- `archived` computed in the same place membership is decided.
- `overview()` grows the `archive_sections` tally inside its existing
  single walk.
- No config changes, no new packaged files (`init.MANIFEST` untouched — the
  doctrine edit is in-place), no new dependencies, stdlib only.

### 7. Review step: human read for campaign vocabulary

With #65 deferred, **no automated check in either repo scans packaged prose
for campaign-specific vocabulary** (the campaign-side term guard's scan
roots all left at the switchover; it scans zero bytes). Every line of prose
this ticket ships into `src/bunnyforge/data/` — the doctrine subsection —
and, for the same reason, the new tool-description text, needs a deliberate
human read for setting coinages before merge. This is an explicit step in
the implementation plan and the PR checklist, not an assumption that a test
covers it.

### 8. Testing (contours; the plan makes these concrete)

- **Store, `search`:** live/archive/both × sectioned/unsectioned; archived
  hits excluded under `live`; mirror resolution under `archive`
  (`section="NPCs"` → `Archive/NPCs/` only); `section="Archive"` under
  `archive` equals unsectioned `archive`; strays at `Archive/*.md` visible
  in whole-archive queries; contradiction and bad-token refusals; `both`
  backward-identical to today plus the `archived` field; sentinel row
  unchanged; root docs present under `live`.
- **Store, `list_entities`:** the same matrix; `archived` present and
  correct on every row.
- **Store, `overview`:** `archive_sections` counts by mirror; stray files
  counted in the `Archive` total but no breakdown entry; key absent when no
  archive dir exists; `sections` byte-identical to today.
- **serve_mcp:** tool signatures expose `scope` with default `"both"`;
  docstrings mention the scope guidance (the existing suite's
  description-surface tests extend, if present).
- **Gate:** `bunnyforge init` → `bunnyforge review checkup` reports
  `Summary: 0 error(s), 0 warning(s)` unchanged.
- All tests scaffold into `tempfile.TemporaryDirectory()`; nothing writes
  into the repo (CI enforces this).

## Alternatives rejected

- **Orthogonal filters** (`section` keeps top-level meaning under every
  scope; `section="NPCs"` + `scope="archive"` refused as empty-by-
  construction): simplest and fully backward-compatible, but makes
  "archived NPCs" inexpressible as a filter — the mirror layout exists
  precisely to keep that addressable.
- **Mirror-section semantics everywhere** (archived files match both
  `Archive` and their mirror section under every scope): conceptually
  uniform, but sectioned listings under the default scope would include
  archived rows — revising #62's "live section listings stay uninflated"
  record for no gain the scope-resolved shape doesn't already provide.
- **`all` as the union token:** invites "all of what?"; with exactly two
  structurally-guaranteed trees, `both` says it.
- **Per-section live/archived count pairs in `overview`** (restructuring
  `sections` values into `{"live": n, "archived": m}`): most informative,
  but changes the type of an existing key when an additive sibling carries
  the same information.
- **A hard use-case→scope mapping in doctrine** ("generation ⇒ live-only"):
  the first design draft, revised away — history-informed invention is
  legitimate and deliberate; the mapping would forbid it. The ask-the-GM
  rule routes the decision to the only party who can make it.
- **Tool descriptions only / one doctrine sentence:** zero-to-minimal
  reconcile cost, but filesystem agents — the campaign repo's primary
  consumers — never see tool descriptions, and the ask-at-task-start rule
  governs them equally.
- **Recording a work's scope in draft front matter:** rejected as scope
  creep; the mechanism is the ask, and "same as when we made it" is a
  complete answer from the GM.

## Out of scope — deliberately

- **#70 — task-start context questions as a general doctrine.** The scope
  ask ships here as doctrine because #66 needs it; #70 designs the
  framework it folds into (what are we building; new NPCs or reused; the
  question list improving itself).
- **CLI scoping** for `review` and exports (§5 — a decision, not a
  deferral).
- **#65** (campaign-term guard over packaged data): deferred on its own
  ticket; §7 is this design's inherited mitigation.
- **The release and the live campaign's migration** (Anjeong pins a
  published version; migrates after the release carrying #62 + #68 + #66).
- **Any change to `read_entity`, the drafts/inbound families, or the write
  side.**
