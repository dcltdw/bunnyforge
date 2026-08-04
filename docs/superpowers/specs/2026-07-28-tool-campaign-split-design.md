# Splitting the Tool from the Campaign — Design

> **Provenance:** a scrubbed copy of a development record from the
> private campaign repository where this tool was first built. Campaign
> identifiers are neutralised throughout; the verbatim original stays in
> that private repo. Staged for publication 2026-08-02.

**Date:** 2026-07-28
**Status:** Phases 1–3 **complete** (Phase 3 landed 2026-07-31, #73). **Phase 4 is authorised**
(user decision 2026-07-31) and designed in
`docs/superpowers/specs/2026-07-31-phase-4-public-cut-design.md`, which governs everything after
Phase 3. **Phase 5 no longer exists** — that spec collapses Phases 4–5 into one staged Phase 4.
The public name is **`bunnyforge`**, and PyPI publishing is in scope. The deferral this document
records throughout is spent; where the two disagree, the Phase 4 spec governs.
**Supersedes:** issue #29 (`setup_campaign.py` staleness) — see *Relationship to open issues*.

## Goal

Separate this workspace into two things:

- a **public tool** — an opinionated way to run a TTRPG campaign as a filesystem workspace
  managed by a Claude agent, synchronised one-way with DokuWiki;
- a **private campaign** — its setting, canon, state, and craft doctrine.

The tool becomes a `pip`-installable package with a fresh public history. The campaign repo
stays private, keeps its history and issues, and depends on the package.

## The finding that shaped this design

The framing "extract a tool from a campaign" is backwards. Measured on disk:

| Directory | Entity files |
|---|---|
| NPCs, Factions, Setting, Sessions, PCs, Ideas, Briefs, Perceptions, Handouts | **0** each |
| Mechanics | 6 (house rules) |
| `_Ignore/` (untracked; agents are forbidden to read it) | 79 raw notes |

The working tree matches git exactly — no untracked canon. This is **mature tooling with a
campaign not yet written**: 174 tests, six shipped issues, zero NPCs.

Two consequences drive everything below:

1. The split is cheap *now* and gets monotonically more expensive. Entanglement grows with
   every entity file written, not in code but in doctrine prose and in the volume of any
   later untangling.
2. Because the tool is most of what exists, the risky part is not separating the code. It is
   committing to public abstractions — a config schema, an entity model, a CLI — derived
   from **a single setting that has not yet been played**. That is the whole reason Phases
   4–5 are deferred.

### What is actually campaign-specific

Small and enumerable:

1. `style-guide.md` — 705 lines; a setting bible wearing a style-guide title
   (*the campaign's tonal-register declaration*, the ten cultures, the campaign register table,
   naming rules separating the capital from the campaign's official culture).
2. `generate_names.py` — 331 lines, where the engine is generic and the syllable inventories
   are setting content.
3. `situation-design.md` — 215 lines. Contains **zero** campaign-name mentions, so it is not
   setting-coupled; it is kept private because it is the author's craft opinion. Those are
   different reasons and this document does not conflate them.
4. Campaign state — `compendium.md`, `front-burner.md`, `open-questions.md`,
   `out-of-game.md`, `tickets.md`, `reanchor.txt`.
5. `_ExtractInbound/` (16 wiki exports), `Mechanics/` (6 house rules), `_Ignore/` (79 files).
6. Code constants naming the campaign or its shape — **seven, in four files**, not the two an
   earlier draft of this document claimed:
   - `deploy_export.BASE_NAMESPACE` — the campaign's base namespace as a literal
   - the `ENTITY_DIRS` / `INHERIT_DIRS` / `ROOT_DOCS` tuples in `_common.py`
   - `build_sheets.py:44-47` — `NPCS`, `FACTIONS`, `SETTING`, `BRIEFS`
   - `import_perceptions.py:34` — `PERCEPTIONS`

   > **Correction.** This list said "exactly two" until Phase 1's whole-branch review found the
   > other five. The error matters beyond bookkeeping: it is what made Phase 1's plan omit
   > `build_sheets.py` and `import_perceptions.py` from every task's file list, so those two
   > scripts still hardcode five directory names that `campaign.toml` now claims to own. Rename
   > `entity_dirs` in config today and `review.py`, `export_player.py` and `deploy_export.py` all
   > follow while `build_sheets.py` silently walks directories that no longer exist — the same
   > failure mode this document cites as the reason `compendium_dirs` had to become explicit,
   > reproduced one script over. **Phase 2 owns the fix**; it already touches all six scripts.

Everything else is tool, including `docs/superpowers/` (7 plans and specs), which was checked
for setting terms (the then-checked subset of what is now the derived list) and found clean.

> **Stale twice over — do not act on that last sentence.** The corpus has grown from 7 files to
> **29** (measured 2026-07-31), and the campaign name itself was never in the checked pattern.
> Measured against the same tree today: **27 of the 29 files mention the campaign by name**, and
> **16** match even that narrower subset. The docs are saturated, not clean. Phase 4's stage
> 5 scrubs them in place under a **derived** term list — generated from `names/cultures/*.toml`
> stems plus the two extra terms `test_campaign_terms.py` defines, because every
> enumeration-by-reading in this project's history has been incomplete, this sentence included.

## Governing principle

> **Operational doctrine ships as content; craft doctrine ships as skeleton.**

`AGENTS.md` describes how the agent *behaves* — read order, clarify-before-proceeding,
verify-against-files, version control, visibility enforcement. That is coupled to the tooling,
so it ships filled in (scrubbed of its 13 campaign-name mentions).

`style-guide.md` and `situation-design.md` describe how the *author* makes things. They ship as
**skeletons that interview the user**, and the filled-in campaign versions stay private.

## Architecture

### Public repository

Fresh history. No campaign content is ever committed to it. MIT licensed.

```
pyproject.toml                  requires-python = ">=3.11", zero runtime dependencies
src/<pkg>/
  common.py  dokuwiki.py  export_player.py  deploy_export.py
  import_perceptions.py   review.py  build_sheets.py
  config.py                     NEW — loads and validates campaign.toml
  names/__init__.py             engine only; no inventories
  cli.py                        console_scripts entry point
  data/
    templates/*.md              12 entity templates, AGENT CONTRACT blocks intact
    doctrine/AGENTS.md          real content, scrubbed
    doctrine/style-guide.skeleton.md
    doctrine/situation-design.skeleton.md
    campaign.toml.in
tests/                          all 174, imports rewritten to package imports
docs/superpowers/               7 plans + specs, carried over
README.md  LICENSE  .github/workflows/tests.yml
```

> **Read this sketch as intent, not as the manifest.** The Phase 4 spec's stage 6 holds the
> assembled contents as designed. Three differences worth flagging here: `tests/` ships only the
> **portable** files (stage 4 splits the suite; campaign-coupled tests stay in the campaign
> repo), `docs/superpowers/` ships **scrubbed** rather than carried over verbatim (see the
> annotation under *What is actually campaign-specific*), and `samples/` — the eight-sample
> ladder, which postdates this sketch — ships too.

Both skeletons are written by `init` to their **canonical names** (`style-guide.md`,
`situation-design.md`), never to `*.skeleton.md`. `ROOT_DOCS` lists those exact paths as
wikilink targets and `review checkup` fails on a dangling link. The `.skeleton` suffix exists
only inside `data/`.

### The private campaign repo

Keeps its history, issues, and identity.

```
campaign.toml                   marker file + config
style-guide.md                  705 lines, filled in
situation-design.md             215 lines, filled in
compendium.md  front-burner.md  open-questions.md  out-of-game.md  tickets.md  reanchor.txt
NPCs/ Factions/ Setting/ Sessions/ PCs/ Ideas/ Briefs/ Perceptions/ Handouts/ Mechanics/
_ExtractInbound/  _Ignore/
names/cultures.toml             the campaign's ten inventories
scripts/                        campaign-local only
tests/                          campaign-local only
```

`scripts/` and `tests/` in the campaign are for campaign-specific work, importing the
installed package like any library (`from <pkg> import common`). This is only possible
*because* of the Phase 2 refactor; under today's design `scripts/` **is** the tool.

Their purpose, stated so the directories do not become graveyards: assert campaign invariants
that `review checkup` cannot know — "every NPC names a faction that exists", "no session file
references a later session", "every `reveal_when` trigger appears in `front-burner.md`".
Campaign tests run on stdlib discovery (`python -m unittest discover -s tests`); the tool's
`run_tests.py` is the *tool's* runner and stays public.

## `campaign.toml`

Serves double duty: it marks the workspace root and holds configuration. Read with stdlib
`tomllib`. `init` writes it from a text template, so no TOML *writer* is needed.

```toml
[campaign]
name      = "<campaign name>"
namespace = "<ns>"             # was deploy_export.BASE_NAMESPACE

[workspace]
entity_dirs     = ["NPCs", "Factions", "Setting", "Mechanics", "PCs", "Ideas", "Sessions", "Handouts"]
inherit_dirs    = ["Briefs", "Perceptions"]
compendium_dirs = ["NPCs", "Factions", "Setting", "Mechanics", "PCs", "Ideas"]
root_docs       = ["AGENTS.md", "compendium.md", "front-burner.md", "open-questions.md",
                   "out-of-game.md", "situation-design.md", "style-guide.md", "tickets.md"]
exclude_dirs    = ["_Ignore", "_Archive", "_ExtractInbound", "_Templates",
                   "Sheets", "Reviews", "docs", "scripts", "tests", ".github", ".git"]

[names]
inventories = "names/cultures.toml"    # optional; omit to disable the generator
profile     = "english"                # pronounceability profile; see the generate_names section
```

### Why `compendium_dirs` is explicit

`review.py:211` currently reads:

```python
COMPENDIUM_DIRS = set(ENTITY_DIRS) - {"Sessions", "Handouts"}
```

A derived set that hardcodes two directory names. The moment `entity_dirs` becomes
configurable, that subtraction silently does the wrong thing for any user who renames those
directories — a latent bug that only a public user would hit. The config states the set
outright.

### Why `scripts` and `tests` stay in `exclude_dirs`

They would otherwise drop out once the tool moves, but the campaign now has its own; they must
not be walked as content.

### Error behaviour

- No `campaign.toml` found while walking up → a clear *"not inside a campaign workspace; run
  `<pkg> init`"* message, not a traceback.
- Missing optional key → documented default.
- Missing `namespace` → hard error; it has no safe default.
- `[names].inventories` absent or pointing at a missing file → the name generator reports
  *"no inventories configured"* and exits non-zero; every other command is unaffected.

## Workspace resolution and imports

Six scripts currently do `WORKSPACE = Path(__file__).resolve().parent.parent`, plus
`sys.path.insert(0, .../scripts)` to import siblings by bare module name. The tools infer the
workspace from where they physically sit, which is why `scripts/` must live at
`<workspace>/scripts/`.

This becomes one function: **walk up from cwd until `campaign.toml` is found**, with an
explicit `--workspace` override. Strictly better than today — commands become runnable from
any subdirectory, which `parent.parent` never allowed. The `sys.path` manipulation disappears
into ordinary package imports.

## `<pkg> init` replaces `setup_campaign.py`

The headline simplification.

| | Today | After |
|---|---|---|
| Size | 2,293 lines — **44%** of all script code | ~150 lines + real files |
| Payloads | 4 scripts as zlib+base64 blobs | none |
| Prose | embedded copies of AGENTS.md, scripts/README.md, all templates | real files in `data/` |
| Drift test | none exists | structurally impossible |
| Ships | 4 of 10 scripts, no export pipeline | the installed package |

Templates and doctrine become real files that `init` copies; it then writes `campaign.toml`
from `campaign.toml.in`. Issue #29 closes by deletion rather than by repair.

## `generate_names`: engine vs data

Syllable assembly and the pronounceability filter are generic. The ten culture inventories are
campaign setting content that happens to live in a `.py` file. The engine ships public and reads
inventories from the path in `[names].inventories`; the campaign's inventories move to
`names/cultures.toml` in the private repo.

Three defects found while designing this. They are stated here because the split alone does not
fix them, and a public tool should not ship them:

1. **`given_len` is dead data.** Declared in all ten cultures and documented at
   `generate_names.py:38` as "how many syllables a personal name runs to" — and never read.
   Generation uses a hardcoded `rng.random() < 0.65` single-vs-compound coin flip. Syllable
   length is therefore not an existing parameter to expose; it is unimplemented.
2. **The module docstring oversells the filter.** Line 11 claims "no consonant clusters, no
   more than three syllables, no tone marks or diacritics." `pronounceable()` actually checks
   three forbidden substrings, total length > 12, non-ASCII, and triple repeated letters. There
   is no consonant-cluster check and nothing counts syllables anywhere in the file.
3. **Campaign specifics inside the engine.** Lines 223 and 316 branch on the official
   culture's `label` and `key` respectively to pick a hyphenated join.

### Parameters the public engine must take

**Audience language.** The filter is implicitly tuned for English speakers ("Reject anything an
English speaker would stumble over on sight"). It becomes a named **profile** — a data
description of what to reject, not a linguistics engine:

```toml
[profile.english]
max_length = 12
ascii_only = true
max_repeat = 2                      # reject triple letters
forbidden  = ["ng'", "''", "--"]
```

Shipped default is `english`, reproducing today's behaviour exactly. Users define others.
**Explicitly out of scope:** real phonotactics — syllable-structure rules, per-language
consonant-cluster legality. Implementing that means guessing at linguistics for languages
nobody has asked for yet. The profile mechanism is the seam where it could later attach.

**Syllable length.** Implemented for the first time, as a weighted range rather than a fixed
count, so that today's output distribution survives as the default:

```toml
given_syllables = { min = 1, max = 2, weights = [0.65, 0.35] }   # == current behaviour
```

with a `--syllables N` CLI override forcing an exact count. A "syllable" is one element drawn
from an inventory pool, which is what those pools already contain.

**Species and real-world basis.** Already half-built via `species` / `draws_on` and `resolve()`;
the split makes the mapping user-defined rather than the campaign's.

> **The tool ships no species-to-real-world-basis mappings, and must not.** Deciding that a
> given fantasy species draws on a given real-world naming tradition is a setting-authorship
> decision with obvious ways to go badly. The campaign makes those choices for itself, in its own
> private inventories file. The public tool provides only the *mechanism* for a campaign to
> declare whatever mapping it chooses, and takes no position on what that mapping should be.
> Any pairing appearing in documentation is an illustration of the file format, never a
> default, a recommendation, or a starting point.

Illustrating the format only — the specific pairings below carry no endorsement and ship
nowhere:

> **Superseded twice — this is the current schema, as shipped.** The block below originally
> showed a `[culture.<key>]` wrapper table, a `label` field, and the three fixed pools
> `given_m`/`given_f`/`given_n`. Phase 1c Plan 1 (#37) made the file *be* the culture and
> derived its key from `name`; Plan 2 (#40) replaced the fixed pools with arbitrary
> per-culture `categories`. Kept current rather than as a historical curiosity, because
> **Phase 3's `init` ships whatever this section describes** — an implementer reading a
> two-phase-stale schema would scaffold campaigns that do not load.

```toml
# names/cultures/<your-key>.toml — one file per culture; bare keys before any table.
name            = "<display name>"   # the key is derived from this
species         = "<your species>"   # optional
draws_on        = "<tradition you chose>"   # optional
categories      = ["<your categories>"]     # any names you like
join            = "concat"           # or "hyphen"
given_syllables = { min = 2, max = 3, weights = [0.7, 0.3] }
family          = [...]
given_<category> = [...]             # one self-contained pool per declared category
place           = [...]
place_tail      = [...]
```

`<pkg> names <species>` then resolves through `species`, exactly as `aasimar` resolves today.
`join` replaces the hardcoded official-culture branch. Cultures are discovered by scanning the
directory named by `[names].cultures`, so adding one means dropping in a file and editing
nothing else.

**What `init` ships as a starting setting:** a small worked example — since the sample-settings
work (`2026-07-29-sample-settings-design.md`, #46), this is `samples/1-one-people/`: one
culture (`vashkand.toml`) with `species` left empty and `draws_on` naming a real historical
tradition. Enough to show the schema and produce output, with no species-to-tradition mapping
asserted. A user who wants none deletes the file and the generator reports that no cultures are
configured. (This section originally pointed at `names/example/`, deleted by that same work —
sample 1 of its eight-sample ladder inherited this fixture's three jobs.)

**Ambiguity rule:** with user-defined inventories two cultures may share a `species` or
`draws_on`. An ambiguous alias lists the matching culture keys and exits non-zero rather than
silently picking one.

## Testing

The whole suite moves to the public repo and **must stay green through every phase** — that is
the entire reason Phases 1–3 happen in-place, before anything is cut. It was 174 tests when
this was written and is 237 after Phase 1b; the number is a moving target, the invariant is
not. Carry-forward item 4 is the exception that proves it: green is necessary but not
sufficient, because some of those tests cannot cross the repo boundary as written.

Three additions the split demands:

1. **Config loading** — missing file, missing required key, missing optional key, malformed
   TOML, `entity_dirs` naming a directory that does not exist.
2. **`init` produces a workspace that immediately passes `review checkup`.** This is the
   regression test `setup_campaign.py` never had, and the one that would have caught #29.
3. **Name generation** — the seeded byte-for-byte reproduction of today's output under default
   config (the Phase 1b guard rail); `--syllables N` producing exactly N elements; an ambiguous
   species alias exiting non-zero and naming its candidates; a missing or unreadable
   inventories file reporting cleanly rather than raising. **All four shipped in Phase 1b.**

The generator had **no dedicated test file** when this was written. Phase 1b gave it one, and —
as required here — the seeded-output test was its first commit, confirmed passing against the
unchanged code before any refactoring began. Phase 1c adds a fifth demand: a culture file must
produce byte-identical output when copied into a different setting, proven by
`tests/check_portability.py` against generated cultures rather than by inspection.

All 6 existing test files need their imports rewritten from `sys.path` + bare-name imports to
package imports. Mechanical, but it touches every test file.

## Phasing

### Phase 1 — de-campaign in place
Extract `namespace` and the directory tuples into `campaign.toml` and a new `config.py`;
author both skeletons; scrub `AGENTS.md`. Also scrub the campaign's name from module
docstrings (`_common.py:3`, `generate_names.py:3`) and from user-facing strings
(`generate_names.py:278`, an argparse `description=` that prints to anyone running `--help`).
No structural change; suite stays at 174 plus new config tests.

### Phase 1b — the name generator
Move the ten inventories to `names/cultures.toml`; add profiles, `given_syllables`, and `join`;
delete the two hardcoded official-culture branches; implement the ambiguity rule; correct the
overselling docstring. Separated from Phase 1 because it is not extraction — `given_syllables`
and profiles are **new functionality**, and the phase carries the only behaviour-change risk in
Phases 1–3. It depends on Phase 1 only for the `[names]` config block.

Its guard rail: with the shipped `english` profile and
`given_syllables = { min = 1, max = 2, weights = [0.65, 0.35] }`, a fixed `--seed` must
reproduce today's output **byte-for-byte** for all ten cultures. Defaults preserve behaviour;
only explicit configuration changes it.

The guard rail held for the whole phase. Phase 1b budgeted for re-baselining the three golden
constants at its Task 5 and **did not need to** — `random.choices` with weights summing to
exactly 1.0 consumes the same single `rng.random()` draw and partitions at the same point the
old comparison did, and the TOML defaults reconstruct the old hardcoded constants exactly. All
three constants are byte-identical to their pre-phase values.

### Phase 1c — portable cultures and arbitrary name categories
Full design: `docs/superpowers/specs/2026-07-29-portable-cultures-design.md`.

Make a culture a **portable unit** — one self-describing file that can be handed to someone
running a different game in a different setting and still produce the names its author
intended. Phase 1b got the data out of Python but left two things that defeat portability: a
culture is a `[culture.X]` block inside one shared file, and pronounceability lives at file
scope, so an imported culture silently takes on the importing setting's constraints. Measured,
a permissively-authored culture pasted into a restrictive setting loses **91% of its
two-syllable given-name combinations** without crashing or warning.

Splits `names/cultures.toml` into `names/cultures/*.toml` discovered by directory scan;
replaces `label`/`order` with a single `name` field the key is derived from; generalises the
hardwired `m`/`f`/`n` into arbitrary per-culture `categories` (`--sex` becomes `--gender`);
and replaces named profiles with a three-layer `[spelling]` resolution — built-in defaults,
then `campaign.toml`'s `[names.spelling]`, then the culture's own table. `--profile` and
`[profile.*]` are removed. Ships `tests/check_portability.py`, which manufactures two cultures
with **disjoint alphabets** and proves both that a fully-specified culture is byte-identical
across two settings *and the converse* — that one omitting spelling keys differs across
settings whose defaults differ.

Unlike Phase 1b, **one golden constant genuinely re-baselines here.** `PLACE_SEED_42` and
`FEMALE_SEED_7` survive; `PERSON_SEED_42` regenerates, because self-contained categories change
what "any" draws from. Their survival is a design consequence of folding `given_n` in a
specific order, which the plans must preserve.

**This phase is four plans and four PRs**, per its design's decomposition: per-file loader,
then categories, then spelling layering, then the portability check and fixture. The loader
deliberately precedes categories so the storage change and the behaviour change are never in
flight together.

### Phase 2 — workspace resolution and package layout
Replace `parent.parent` with the marker-file walk and the `sys.path` hack with package
imports. Rewrite test imports. Highest blast radius of any phase.

**Three items carried forward from Phase 1's whole-branch review.** All three are gaps in *this
document* rather than in Phase 1's execution, and all three are cheap here and expensive
anywhere else, because Phase 2 already touches all six scripts:

1. **Finish the de-campaigning of workspace shape.** `build_sheets.py:44-47` and
   `import_perceptions.py:34` still bind five directory names to literals — see the correction
   under *What is actually campaign-specific*. Until they read config, "the workspace's shape
   lives in `campaign.toml`" is only true of four of the six scripts.
2. **Import-time config failures must stop producing tracebacks — in *both* loaders.** This
   document already requires *"a clear 'not inside a campaign workspace; run `<pkg> init`'
   message, **not a traceback**"*. Two separate sites violate it, and a fix that addresses only
   the first would leave the second silently broken:

   - `scripts/_config.py`'s `CONFIG = load(WORKSPACE)` — a missing or malformed `campaign.toml`.
   - `scripts/generate_names.py`'s `CULTURES, ORDER, _RAW = load_inventories(...)` — a missing or
     malformed `names/cultures.toml`, added in Phase 1b.

   Both raise at **import**, so no `main()` can catch either and the user sees a stack trace
   instead of the message that was carefully written for them. Neither was fixed in its own
   phase because the fix is a `try`/`except` around the import in every entry point — code
   Phase 2 deletes when it makes binding lazy. Phase 2 owns both; check both when closing this.

   **Phase 1c renames the second site**, so match on shape rather than on this exact line:
   `load_inventories` becomes a directory scan, `ORDER` disappears with `order`, and the path
   becomes `names/cultures/`. The defect is unchanged — a module-level call that raises at
   import — and Phase 1c adds two more ways for it to fire, since a culture file missing `name`
   and two files whose names collide are both load errors.
3. **Config binding must become lazy before `--workspace` can work.** `_config.py`'s
   module-level `CONFIG`, `_common.py`'s re-exports, `deploy_export.py`'s `BASE_NAMESPACE` and
   `PROTECTED_PAGE_IDS`, and `render_tree`'s `base: str = BASE_NAMESPACE` default all snapshot
   the config at import — before argv is read. An explicit `--workspace /elsewhere` cannot change
   any of them as currently written. Phase 1 correctly did not invent an accessor nobody needed;
   Phase 2 must budget for converting every one of those bindings.

**Two further items, carried forward from Phase 1b's whole-branch review and the Phase 1c
design.** Neither is a gap in execution. Both are places where this campaign's specifics
survive inside code that is meant to ship without it, which is precisely what Phase 4 cannot
carry:

4. **The generator's own tests are coupled to the campaign's inventories.** **Roughly a third**
   of the tests in `tests/test_generate_names.py` bind to this campaign — the golden constants,
   a `CULTURES` lookup keyed by a campaign culture, or a `run_cli` call that reads the real
   shipped inventory. The rest are already portable: they build their own fixtures or exercise
   pure validation, so they would survive the public cut untouched. Since this document keeps
   the culture data in the private campaign repo while the engine ships public, **that coupled
   third is the part of the generator's test coverage that cannot ship with the generator.**

   **Deliberately stated as a ratio, not a count.** Every absolute number written here has gone
   stale within a phase: the Phase 1c design says "17 of 29" (measured mid-Phase-1b), this item
   said "16 of 45" after 1b's fix waves, and Phase 1c Plan 1 took the file to **59 (24 coupled,
   35 portable)**. The ratio has held near a third throughout. Re-derive the count when you
   actually need one — classify a test as coupled if it touches a golden constant, a named
   culture, or a `run_cli` call against the real inventory — and do not copy a number forward
   from prose, including this sentence.

   Phase 1c ships the fixture setting that makes rewriting them possible, and rewrites whatever
   its category migration touches anyway; the remaining bulk is Phase 2 or 3 work, recorded
   here because nothing else outlives the phase that found it. (The fixture itself shipped as
   `names/example/`, then was superseded by `samples/1-one-people/` once the sample-settings
   work, #46, deleted `names/example/` and replaced it with an eight-sample ladder.)
5. **The remaining untunable constants.** `range(10)` (the given-name join retry budget) and
   `range(50)` (name and place retries) are tuned against *this campaign's* pool sizes, and the
   `given_syllables` default of `min = 1, max = 2` is hardcoded in two places. All are inert
   today and all have the same shape as the `max_join_length` bug Phase 1b found — a constant
   tuned for this campaign that silently overrides a different setting's configuration. Recorded so
   that the enumeration of "the campaign-specific bits" is not claimed complete a sixth time;
   every previous enumeration made by reading code has been incomplete, while the one exercise
   that actually built a second setting found a real bug immediately.

This is where `scripts/` becomes `src/<pkg>/` **inside the campaign repo**, alongside a
`pyproject.toml`, with the repo installed editable (`pip install -e .`). So between Phase 2
and Phase 4 the campaign repo *contains* the package — a deliberate transitional state, and
the thing that lets every phase stay green in one repo under one test suite. Phase 4 is then
little more than moving that tree into a fresh repository.

### Phase 3 — `init` — LANDED (#73, 2026-07-31)
Delete `setup_campaign.py`; build `<pkg> init` over real `data/` files; add the
init-then-checkup regression test.

**As shipped, with two corrections to the above.** `setup_campaign.py` was not deleted here —
it went in Phase 2 Plan 1 (#51), by user decision, so Phase 3's scope was only building `init`.
And this entry's premise that the doctrine ships verbatim held only after a fix: `AGENTS.md`
carried two example wikilinks to campaign-specific files which no campaign-term grep caught and
which made a fresh workspace report 2 checkup warnings. Both are now portable, guarded by a
test that runs the real wikilink check against a root-docs-only workspace. `init` ships as
`python3 -m ttrpgkit.init` over a 35-file `data/` tree behind a byte-equality drift guard; the
unified dispatcher was deferred again, for want of evidence from actual use. Governing detail:
`docs/superpowers/specs/2026-07-31-phase-3-init-design.md`.

### Phase 4 — the public cut — AUTHORISED 2026-07-31
Cut the public repository (fresh history, MIT, CI, README), migrate the tool issues, and make
the campaign repo depend on the published package.

**Authorised and designed:** `2026-07-31-phase-4-public-cut-design.md`. Three things that
document settles which this one left open or wrong:

- **Phase 5 is erased.** This document deferred "Phases 4–5" as a unit but gave 5 no content of
  its own; the user collapsed them into one Phase 4, staged internally into eight stages.
- **Issue migration is expected to be a no-op.** All five open tool issues (#24, #25, #69, #17,
  #27) are cut blockers, closed *before* the cut, so there should be nothing left to migrate.
- **"Little more than moving that tree into a fresh repository"** (the Phase 2 entry's
  description of this phase) understates it: the user front-loaded issue hygiene, the
  dispatcher, the test split, and the docs scrub into the cut. The claim that the *move itself*
  is cheap survives — stage 6 is the smallest stage of the eight.

**Each of Phases 1, 1b, 2 and 3 becomes its own implementation plan and its own PR, and Phase
1c becomes four** — **eight in total**. They are too large for one plan and each has a natural
green checkpoint.

**All of Phases 1–3 have landed — as thirteen plans, not the eight predicted above.** Phase 1
shipped as #31, Phase 1b as #33, Phase 1c's four as #37, #40, #43 and #46, Phase 3 as #73.
Phase 2 was the estimate that broke: budgeted here as one plan, it took **six** (#51, #54, #56,
#58, #60, #68), which is what "highest blast radius of any phase" turned out to cost. The
per-phase boundaries all held; only the within-phase plan count was wrong.

### Why the phase boundary sits where it does

Phases 1–3 improve the codebase whether or not anything is ever published: ~2,000 fewer lines,
configuration instead of constants, commands runnable from any directory, and a latent bug in
`review.py` fixed. They are reversible and private.

Phases 4–5 are the irreversible public commitment. Deferring them buys the thing the finding
above says is missing: evidence. If the first campaign session reveals `ENTITY_DIRS` is the
wrong model, Phase 1–3 code changes a tuple; a released package changes an interface with
users on it.

> **The evidence never arrived, and the cut went ahead anyway.** Measured 2026-07-31, the
> campaign still had 0 entity files everywhere but Mechanics — byte-for-byte the finding above.
> The user was shown both failure modes (deferral waits on play that may never come; self-play
> by the tool's author is weak evidence regardless, since real evidence needs a stranger, which
> needs publishing) and decided to cut now with the sample-size-of-zero risk explicitly
> accepted. The recorded mitigation is the `0.x` version line: semver's "anything may change
> before 1.0" is the public statement that these interfaces are young and unproven. See the
> Phase 4 spec, "The question this phase had to answer first".

## Risks and trade-offs

- **Phase 2 blast radius.** It touches all 6 scripts and all 6 test files. The suite (174 when
  this was written; 237 after Phase 1b) is a real net but not a total one — nothing currently
  tests the workspace-derivation logic itself, because it is a one-line constant.
- **~~`generate_names.py` has no tests at all.~~ RETIRED by Phase 1b.** As written this said:
  verified, no test file references it; 331 lines, rewritten more than any other file in any
  other phase; the single largest unguarded surface in Phases 1–3, which is why Phase 1b's first
  commit had to be the seeded characterisation test confirmed passing against the *current* code
  before anything moved. That is what happened. `tests/test_generate_names.py` now exists, the
  characterisation test was the first commit, and its three golden constants survived every task
  byte-for-byte. The residual risk is narrower and is recorded as carry-forward item 4: the
  tests exist but are coupled to this campaign, so they cannot yet ship with the engine.
- **Ordering against PR #28.** This work must land *after* #28 merges. Both touch
  `setup_campaign.py` and `scripts/README.md`.
- **Opportunity cost.** This is infrastructure work while zero canon exists. If play starts
  soon, it delays the campaign. The counter is that it gets more expensive every week.
- **Sample size of one.** Acknowledged and mitigated by deferring Phases 4–5 rather than by
  designing around it.
- **`_Ignore/` is never touched.** 79 files of unmigrated raw material, untracked and
  off-limits to agents. No phase reads, moves, or migrates it.

## Relationship to open issues

- **#29** (`setup_campaign.py` embeds 4 of 10 scripts, ships no export pipeline) — superseded,
  and **closed** when Phase 2 Plan 1 (#51) deleted the script. The defect behind it is now
  guarded rather than merely gone: `init`'s packaged copies are held byte-identical to their
  in-repo canonicals by a drift test, so the silent staleness #29 reported would fail the
  suite today.
- **#24** (`review.py` wiki-config suite), **#25** (importer drops blank pages) — independent
  tool bugs. Better fixed *before* the public cut so no known bug ships, but they do not block
  Phases 1–3.
- **#27** (decision record: keep hand-rolled converters) — unaffected.
- **#4**, **#5** — campaign-content issues; they stay with the campaign repo.

## Open decisions

**None remain.** The one entry below was resolved by the user on 2026-07-31 and is kept for the
record rather than deleted.

- **Public package, command, and repository name.** ~~Deliberately unresolved; `<pkg>` is the
  placeholder throughout.~~ **RESOLVED 2026-07-31: `bunnyforge`** — package, command, and
  repository, per the Phase 4 spec's decisions table. Unregistered on PyPI when checked, and
  `github.com/dcltdw/bunnyforge` did not yet exist. Read `<pkg>` as `bunnyforge` throughout this
  document. The anticipated rename is real work, and is Phase 4's stage 2: `ttrpgkit` →
  `bunnyforge`, including `TTRPGKIT_WORKSPACE` → `BUNNYFORGE_WORKSPACE` across the 9 modules that
  thread it.

  **However** — Phase 2 needs a *working* import name, because it creates the package
  directory. "Nothing in Phases 1–3 depends on the name" is therefore not quite true, and this
  spec does not pretend otherwise. Phase 2 adopts a working name; Phase 4 renames it to the
  chosen public one. That rename is a mechanical find-and-replace across the package directory,
  its imports, and `pyproject.toml`, fully guarded by the suite, so the cost of deferring is
  minutes rather than a redesign. Pick any placeholder at Phase 2 that is not `scripts` — that
  name collides with the campaign-local `scripts/` directory introduced later.

## Out of scope

- Any second wiki backend. DokuWiki is the only target.
- A `<pkg>.testing` module of workspace fixtures for campaign-local tests. An obvious eventual
  want, but no campaign test exists yet to say what the fixtures should be; building it now
  means guessing. Revisit after the first real campaign test.
- Migrating `_Ignore/`.
- ~~Publishing to PyPI (Phase 4).~~ **Now in scope**, as Phase 4's stage 7: `bunnyforge` 0.1.0
  released via trusted publishing (OIDC, no stored token), with a post-publish smoke test in a
  clean venv on a path containing no checkout. It was out of scope *here* because Phase 4 was
  unauthorised; authorising Phase 4 brought it in.

## Success criteria for Phases 1–3

1. The suite is green at every commit, **never below the count the previous phase ended on**,
   with the number asserted explicitly rather than inferred from a green "OK". The baseline was
   174 when this was written; Phase 1 added the config tests and Phase 1b ended at **237**, which
   is what Phase 1c must not regress below. A phase that ends with fewer tests than it started
   has deleted coverage, and must say which and why. The runner is
   `python3 scripts/run_tests.py` through Phase 1 and `python3 src/<pkg>/run_tests.py` (or the
   console entry point) from Phase 2, once the tree moves.
2. `review checkup` reports `0 error(s), 0 warning(s)` throughout.
3. `export_player` and `deploy_export --render-only` produce byte-identical output to their
   pre-refactor runs — the same 5 exported / 9 skipped and the same seven link refusals.
4. The campaign-name grep over the package tree returns **nothing** — not in code, not in module
   docstrings, not in argparse `description=` strings, which are user-facing output rather
   than comments. The namespace reaches the code only through `campaign.toml`.
5. `setup_campaign.py` no longer exists, and a fresh `<pkg> init` workspace passes
   `review checkup` with no manual fixes.

**Criterion 5 closed with #73**, and is now asserted continuously rather than by hand:
`tests/test_init.py::TestFreshWorkspacePassesTheGate` scaffolds a workspace as a real child
process and fails the suite if checkup reports anything but 0 errors and 0 warnings — the
regression test `setup_campaign.py` never had. Measured on `main` at #73: the suite stands at
**398** against the 174 baseline above, `review checkup` reports 0/0 (criterion 2), and
the campaign-name grep over `src/` is empty (criterion 4).
