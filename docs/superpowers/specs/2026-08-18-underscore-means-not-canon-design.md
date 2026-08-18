# The leading underscore means "not canon" — design

**Date:** 2026-08-18
**Issue:** https://github.com/dcltdw/bunnyforge/issues/62
**Status:** approved design, awaiting implementation plan
**Supersedes:** an earlier plan for #62 (option-C-shaped, committed and deliberately deleted) — see "Alternatives rejected".

## The problem

Issue #62: a leading `_` on a workspace path is treated as a convention but has
no single meaning. At the top level it spans three incompatible read contracts
(`_Ignore/` never read, `_Archive/` read freely, `_ExtractInbound/` read when
asked), and it is enforced two different ways (`_common.iter_content_files`
honours `_` directories only because `exclude_dirs` names them;
`_store.py` applies a general any-`_`-component refusal for the drafts and
inbound families, which also disagree with each other about `.`-prefixed
components).

## The decision

**A `_`-prefixed path component means the path is not canon. Biconditionally:
everything in the workspace that is not canon carries the marker** — except
repo-infrastructure directories (`docs/`, `scripts/`, `tests/`), which keep
their ecosystem-conventional names; the doctrine states that exemption
explicitly. `.`-prefixed components are OS/tool droppings and are invisible
everywhere. Read contracts are per-directory and are *not* what `_` encodes.

The consequence that unlocks it: the data changes to fit the rule, not the
rule to fit the data. `_Archive/` is canon — it is the record of what
happened — so it loses the marker. `Sheets/`, `Reviews/`, and `Export/` are
generated non-canon output, so they gain it.

This resolves #62's counterexample (`_Archive/` was the one underscore path
whose contents are canon) instead of weakening the rule around it, and it
collapses the two enforcement mechanisms into one.

### Evidence this rests on (measured, not assumed)

1. Six of the seven underscore paths already fit "`_` = not canon" *using the
   doctrine's own words*: `_Ignore/` ("it is not canon"), `_ExtractInbound/`
   ("none of it canon"), `_AgentDrafts/` ("nothing in it is canon"),
   `_Templates/` (machinery), nested `_Done/`/`_Rejected/` (never read).
   `_Archive/` is the only misfit — and it is misnamed, not mis-ruled.
2. The doctrine's "read `_Archive/` freely and reason from it" is currently
   honorable only by filesystem agents. The MCP agent is locked out entirely:
   `read_entity` resolves through `_canonical` (`_store.py:92`), which refuses
   every `exclude_dirs` component; `_Archive` is not listed, not readable, not
   searchable over MCP. Making the archive canon fixes a latent contradiction,
   not just a name.
3. No shipped, scaffolded, or sample path has a `_`- or `.`-prefixed component
   outside the documented directories (`find samples src/bunnyforge/data
   -name '_*'` / `-name '.*'`: both empty). PR #61's `propose_revision` guard
   (`_store.py:337`) only ever fires on path shapes nothing sanctions — but
   the lockout it prevents is mechanical fact (an unguarded proposal's shadow
   lands in the drafts machinery area: invisible to every draft tool, yet
   permanently occupying the one-proposal-per-file slot). Under this design
   the general rule moves into `_canonical`, the lockout becomes structurally
   impossible, and the special-case guard is deleted rather than retired.
4. The MCP tools cannot create `_`/`.`-leading paths (`_DRAFT_NAME_RE`,
   `_store.py:40`, requires a leading alphanumeric); only the GM can, by hand.
5. `pathlib.rglob("*.md")` matches `.foo.md` and descends into `.dir/`
   (verified), so today's drafts listing genuinely serves hidden paths;
   `Path(".foo.md").suffix == ".md"`.
6. The wiki exporter refuses ambiguous wikilinks (`_dokuwiki.py:163`) while
   `check_wikilinks` flags only *broken* ones — ambiguity is silent at review
   time and fatal at deploy time. `resolve_target` has no true path-form
   lookup (it falls back to the last path segment), so a stem shared between
   a live file and an archived one cannot be disambiguated by writing a
   fuller link. Walking the archive makes this collision class reachable,
   which is why this design adds a collision check (§5).

### Decisions record

Settled in brainstorming with the GM, 2026-08-18:

| question | decision |
|---|---|
| What does `_` mean? | Not canon. |
| Biconditional? | Yes — non-canon gets the marker, except repo infra (`docs/`, `scripts/`, `tests/`). |
| Archive canon scope | Full canon: walked, validated, listed, searched, exported, indexed, writable. No carve-outs. |
| Archive layout | Mirrored top-level: `Archive/NPCs/old-hag.md` (the `_AgentDrafts/` pattern). |
| Archive name | `Archive/`. |
| Player export of archive | Yes, per normal visibility rules. |
| Compendium indexing of archive | Yes, required (keyed off the mirrored inner section). |
| Write tools on archive | Yes, ordinary canon. |
| Name collisions | Forbidden: checkup **error** on any stem/alias resolving to >1 walked file — live-vs-archive *and* live-vs-live. Rename-on-retire is the discipline. |
| Canon walkers adopt the general prefix rule? | Yes — skip/refuse any `_` component (safe now that the meaning is defined). |
| `.`-prefix handling | Uniform: invisible everywhere (walkers, drafts, inbound). |
| Default read contract for an unnamed `_` dir | Never read unless the GM asks. Campaign exceptions go in `campaign-doctrine.md`. |
| Generated-output renames | `Sheets/`→`_Sheets/`, `Reviews/`→`_Reviews/`, `Export/`→`_Export/`. |
| `MANDATORY_EXCLUDES` (`.git`, `.github`) | Deleted — redundant under the dot rule. |
| `Archive` in listings/counts | Its own section: live section counts stay uninflated. |
| Scoped retrieval (live/archive/all search) | **Out of scope** — ticket #66. #62 ships uniform search; default scope stays `all` there too. |

## Design

### 1. One predicate, honored everywhere

`_common.is_machinery(part: str) -> bool` — true when a path component starts
with `_` or `.`. Consumers:

- `iter_content_files` skips any path containing a machinery component.
- `_store._canonical` refuses machinery components (message names the
  convention). This is what absorbs PR #61's `propose_revision` guard: the
  guard and its bespoke comment are deleted; `propose_revision`, `read_entity`,
  `write_entity` all inherit the refusal from `_canonical`.
- The drafts family (`_draft_path`, `list_drafts`) and the inbound family
  (`_inbound_path`, `list_inbound`) both use it below their family roots —
  the existing `_machinery` staticmethod (`_store.py:508-513`) is replaced by
  the shared predicate, resolving the `.`-asymmetry (drafts previously skipped
  only `_`).

Note the inversion from the deleted earlier plan: with `_` *defined* as "not
canon", walkers skipping `_` paths is the rule working, not silent hiding. A
GM parks anything outside canon by prefixing it. There is no checkup warning
for machinery-named files in content dirs — they are sanctioned now.
(§4's check is about something else: name collisions.)

### 2. Configuration

- `exclude_dirs` default shrinks to `["docs", "scripts", "tests"]` — the
  repo-infrastructure exemption, which is now the *only* reason the
  enumeration exists. The underscore entries are redundant under the general
  rule. `exclude_dirs` keeps its semantics (matched against any path
  component, as today) for GM-added non-underscore exclusions.
- `MANDATORY_EXCLUDES` is deleted (`.git`/`.github` are dot-prefixed).
- `inbound_dir` and `drafts_dir` stay appended to `exclude_dirs` at load time:
  they are configurable to non-underscore names, and no configuration may
  un-exclude them.
- New config key `archive_dir`, default `"Archive"`, following the
  `briefs_dir`/`sheets_dir` pattern. Validation: must not equal an
  entity/inherit dir, must not be `_`-prefixed (it is canon by definition).
- `sheets_dir` default changes `"Sheets"` → `"_Sheets"`.
- `campaign.toml.in`'s commented examples update to match every default they
  mirror.

### 3. The archive is ordinary canon

- **Layout:** `Archive/<Section>/<file>.md`, mirroring live sections. Not
  scaffolded by `init` (like today's `_Archive/`, it appears on first retire).
- **Walking:** `iter_content_files` gains the archive root as a walk root.
  Category is derived from the mirrored inner section (`Archive/NPCs/*` →
  `entity`, `Archive/Briefs/*` → `inherit`); a file under `Archive/` whose
  mirror dir is not a configured section (including files directly at
  `Archive/x.md`) defaults to `entity` so it stays visible and the
  front-matter check can flag it — fail loud, never a silent hole.
- **Sections:** `Archive` is its own section for `list_entities`, `search`'s
  `section=` filter, and `overview` counts (`_sections()` grows it), so live
  counts stay honest.
- **Checks:** front-matter, visibility-audit, wikilinks, compendium all apply.
  Compendium indexing is *required* for archived entity files whose mirrored
  section is in `compendium_dirs` (the check keys on the mirror, not on
  `Archive` itself). Retiring a file therefore includes updating its
  compendium entry — stated in the doctrine's retire procedure.
- **Export:** normal visibility rules; no carve-out. `deploy_export`/wiki
  export treat archived files like any canon file.
- **Writes:** `write_entity` and `propose_revision` accept archive paths like
  any canon path. The doctrine still governs *when* editing history is
  appropriate; the tools do not.
- **Retirement semantics** live in front matter and doctrine, not code:
  `status: retired`, "do not present as current", "live file wins".

### 4. New checkup check: name collisions

`review.check_name_collisions` (registered `"name-collisions"`, in the
`checkup` suite): any stem or alias that `target_index` maps to more than one
walked file is an **error** naming every colliding path. Scope: all
duplicates — live-vs-archive and live-vs-live — because the exporter refuses
both identically (evidence §6). Deliberate duplicates are acceptable via the
existing `[[accept]]` mechanism. Fresh workspaces are clean, so the 0/0 gate
holds.

This check is what enforces rename-on-retire: archiving a file whose name its
replacement will reuse forces a rename at retire time, keeping every file
uniquely addressable by bare stem (the reason the prefer-live resolution
alternative was rejected — see below).

### 5. Renames of generated output

| old | new | where the name lives |
|---|---|---|
| `Sheets/` | `_Sheets/` | `sheets_dir` config default (`_config.py:129`); doctrine mention |
| `Reviews/` | `_Reviews/` | literals in `review.py:75,137,688`; `run_tests.py` note |
| `Export/` | `_Export/` | literals in `export_player.py`, `deploy_export.py` (incl. `--export-dir` help) |

Packaged `.gitignore` (`data/root/gitignore`): the generated-output block
becomes `_Sheets/`, `_Reviews/`, `_Export/` (adding the previously missing
export entry); `_Ignore/` entry unchanged.

### 6. Doctrine (packaged `AGENTS.md`)

Edits are surgical hunks; the file ships byte-identical into workspaces and
live campaigns diff against it.

- **One new section states the meaning**: `_` component ⇒ not canon;
  biconditional with the repo-infra exemption named (`docs/`, `scripts/`,
  `tests/`); `.` ⇒ invisible; read contracts are per-directory and listed as
  pointers (`_Ignore/` never, `_Templates/` reference, `_ExtractInbound/`
  when asked, `_AgentDrafts/` freely, nested `_Done/`/`_Rejected/` never);
  default contract for an unnamed `_` directory: **never read unless I ask**,
  with campaign-specific exceptions declared in `[[campaign-doctrine]]`.
- **The `_Archive/` passages become `Archive/` passages**: it is canon — the
  record of what happened — read and reasoned from like any canon, with the
  existing "do not present as current / superseded by definition / live file
  wins" rules intact.
- **The retire procedure** gains two explicit steps: rename first if the name
  will be reused (the collision check enforces it), and update the file's
  compendium entry to its `Archive/` path.
- **`Sheets/` mentions** become `_Sheets/`.

### 7. Compatibility and migration

**An un-migrated workspace under the new code keeps today's effective
behavior.** Old `_Archive/` (top-level or nested) is skipped by the prefix
rule exactly as `exclude_dirs` skipped it before. `Sheets/`, `Reviews/`,
`Export/` were never walked (top-level walking is allowlist-driven) and
remain unwalked. Drift is limited to: new report/sheet/export runs write to
the new `_`-named output dirs, `read_entity` no longer refuses the old output
dirs, and the archive stays invisible until the GM renames it — the same
invisibility as today, so nothing regresses.

**Migration recipe** (a section in `docs/adopting-doctrine.md`, run once by
hand, same shape as the #64 recipe):

1. `git mv _Archive Archive` — and restructure its contents into mirrored
   section form if they are not already (`Archive/NPCs/...`).
2. `git mv Sheets _Sheets; git mv Reviews _Reviews; git mv Export _Export`
   (each only if present; they are rebuildable, so deleting instead is fine).
3. `campaign.toml`: if `exclude_dirs` or `sheets_dir` are set explicitly,
   update them (explicit values override new defaults and would otherwise
   pin the old names).
4. Take the new packaged `AGENTS.md` and `.gitignore` whole.
5. Run `bunnyforge review checkup`: expect collision errors or front-matter
   findings from newly walked archive files; fix or `[[accept]]` each — that
   review *is* the archive joining canon.

The live campaign (Anjeong, pinned to 0.3.1) migrates after the release that
carries #64 and #62; out of scope here.

### 8. Testing (contours; the plan will make these concrete)

- Predicate: unit tests for `is_machinery`; walker skips `_`/`.` components;
  `_canonical` refuses them (which covers `read_entity`/`propose_revision`/
  `write_entity` in one place); drafts/inbound dot-unification tests; the
  PR #61 guard's tests are *rewritten* against `_canonical`'s refusal, not
  deleted (`NPCs/_notes.md` must still be refused — by the general rule now).
- Archive: walked with correct category/section mapping; listed as its own
  section; searchable; exported per visibility; compendium requirement keyed
  on the mirror section; absent-archive workspaces unaffected.
- Collisions: error on live-live and live-archive stem and alias collisions;
  clean fresh workspace; acceptance works.
- Renames: `review --html` writes `_Reviews/`; sheets build writes
  `_Sheets/`; export writes `_Export/`; gitignore matches.
- Gate: `bunnyforge init` → `review checkup` reports
  `Summary: 0 error(s), 0 warning(s).` unchanged.
- All tests scaffold into `tempfile.TemporaryDirectory()`; nothing writes
  into the repo.

## Alternatives rejected

- **Issue #62's option A as originally framed** (prefix rule everywhere,
  meaning undefined): rejected earlier for silently hiding ordinary content.
  Adopted *here* only because the meaning is now defined and the data is
  renamed to match — what a walker skips is not-canon by definition, not by
  accident.
- **Option B (decorative `_`, enumeration is the authority):** loses the
  general rule the drafts/inbound families genuinely need, and retires a
  guard whose failure mode is real (evidence §3).
- **Option C, sharpened (the deleted first plan):** kept the top-level
  read-contract muddle and merely documented it; `_Archive/` stayed the
  counterexample; the MCP archive lockout stayed. Deliberately superseded by
  this design at the GM's direction.
- **Archive as canon-but-dormant (readable, unwalked)** and **rename-only**:
  both preserve special cases; full canon needed no carve-outs after the
  export/compendium/write decisions all landed on uniformity.
- **Nested (`NPCs/Archive/`) or flat (`Archive/x.md`) archive layouts:**
  nested inflates every live listing and forces per-section carve-outs; flat
  loses section structure. Mirrored top-level matches the existing
  `_AgentDrafts/` precedent.
- **Prefer-live wikilink resolution on collisions:** would bake "live wins"
  into resolution but leave archived files unaddressable by bare stem and
  checkup still silent; forbid-reuse keeps every stem unique and surfaces the
  problem at review time.
- **One-directional marker (keep `Sheets/`, `Reviews/`, `Export/` unmarked):**
  leaves not-canon-without-the-marker misfits — the mirror image of the
  `_Archive` problem this design exists to fix.

## Out of scope — deliberately

- **Scoped retrieval (`live`/`archive`/`all` search and listing scopes, and
  per-element archived markers): ticket #66.** #62 ships uniform retrieval;
  do not add a scope parameter or an `archived` field here.
- **Issue #65** (packaged data has no campaign-term guard): adjacent, filed,
  separate.
- **The release** (one release carries #64 + #62, afterwards) and **the
  Anjeong migration** (pinned to 0.3.1; migrates after that release).
- **`init` scaffolding `Archive/`**: it appears on first retire, like today.
- **Any change to the inbound/drafts read contracts or doors**: they already
  fit the new meaning.
