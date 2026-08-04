# Phase 1c — Portable Cultures and Arbitrary Name Categories

> **Provenance:** a scrubbed copy of a development record from the
> private campaign repository where this tool was first built. Campaign
> identifiers are neutralised throughout; the verbatim original stays in
> that private repo. Staged for publication 2026-08-02.

**Date:** 2026-07-29
**Status:** Design approved; awaiting plan.
**Depends on:** Phase 1b (`docs/superpowers/plans/2026-07-28-phase-1b-name-generator.md`), which must merge first.
**Parent spec:** `docs/superpowers/specs/2026-07-28-tool-campaign-split-design.md`

## Goal

Make a **culture a portable unit**: one file, self-describing, that a person can hand to someone running a different game, in a different setting, and have it produce the names its author intended.

Two things block that today. Cultures live as `[culture.X]` blocks inside one shared file, so copying one means editing two places and hoping the surrounding file agrees. And pronounceability lives at file scope, so an imported culture silently takes on the importing setting's constraints.

Along the way, generalise the hardwired `m`/`f`/`n` model into arbitrary per-culture categories.

## The measurement that motivates this

A Nahuatl-style culture, authored under permissive spelling rules and pasted into a setting using the restrictive defaults (measured against Phase 1b's `english` profile, the predecessor of this design's `[spelling]` block):

| | places reachable | two-syllable given names reachable |
|---|---|---|
| home setting | 16/16 | 132/132 |
| pasted elsewhere | 13/16 | **12/132** |

It does not crash. It does not warn. **91% of its given-name combinations silently become unreachable** and it stops sounding like itself. That is the bug this phase exists to fix, and it is a design property rather than a defect in any line of code.

## Decisions

Each was settled with the human partner during design.

| Decision | Ruling |
|---|---|
| Category scope | **Per-culture.** Each culture declares its own categories. |
| Shared pool | **None.** Categories are self-contained; no `given_n` merged into others. |
| Cross-culture `--gender X` | **Print only the cultures that have it.** Error, listing what exists where, if none do. |
| Unit of portability | **One file per culture**, not one struct in a shared file. |
| Self-awareness | **A single `name` field** in the file; the key is derived from it. |
| `order` | **Removed entirely.** |
| `--profile` | **Removed entirely.** |
| Scope | **Gender and per-file bundled into one phase**, because both rewrite the same storage and splitting means migrating the inventories twice. |

## Architecture

### Culture files

```
names/cultures/
  vashkand.toml
  taksha-shri.toml
  ashgrove.toml        ← drop a file in; it is picked up
```

Discovery is a **directory scan** of `*.toml`. There is no index, so adding a culture requires editing nothing else — the fix for the `order` problem, where a pasted culture loaded, was reachable by name, and was invisible to a no-argument run.

There is **no `[culture.X]` wrapper**; the file is the culture.

```toml
# names/cultures/taksha-shri.toml — self-contained; copy it anywhere.
name       = "Taksha Shri"
species    = ""                 # optional
draws_on   = ""                 # optional
categories = ["m", "f"]

given_m    = [...]
given_f    = [...]
family     = [...]
place      = [...]
place_tail = [...]

join            = "concat"                                    # optional
place_split     = 0.5                                         # optional
given_syllables = { min = 1, max = 2, weights = [0.65, 0.35] } # optional

[spelling]                      # optional; see Spelling resolution
max_join_length = 20
```

**The `[spelling]` table must come last**, after every flat key. In TOML a bare key following a table header belongs to that table, so a `[spelling]` block placed above `name` would silently swallow it. This project has already been bitten by that scoping rule twice; the shipped example and the generated fixture both put `[spelling]` last, and the loader rejects a culture file missing `name` — which is what a misplaced `[spelling]` produces.

### Identity

A single `name` field carries both the display string and the key. The key is `name` lowercased with spaces and hyphens removed — the normalisation `resolve()` already performs, so `"Taksha Shri"`, `"taksha shri"` and `"TAKSHASHRI"` all reach the same culture today.

`label` is **removed**; `name` replaces it.

The **filename is convention only**. It is not read, and a culture file works under any filename. Matching the key is good manners, not a requirement.

**Collisions are an error.** Two files whose names normalise identically fail to load, with a message naming **both file paths**. Without this, one culture silently shadows the other depending on directory-scan order.

The derived key is what everything else refers to: the CLI's culture argument, `resolve()`'s return value, and `campaign.toml`'s `official_culture`. A setting naming `official_culture = "vashkand"` matches the file whose `name` normalises to `vashkand`, whatever that file is called. An `official_culture` matching no culture is a load-time error, not a silent no-op.

### Categories

A culture declares `categories`, and supplies a `given_<category>` pool for each. Pools are **self-contained** — there is no shared pool merged into others.

Validation, at load:
- `categories` present, a non-empty list of strings
- every listed category has a `given_<category>` key holding a non-empty list of strings
- every `given_*` key names a listed category — this catches `givne_sparker` and `categories = ["holdre"]` alike, which a keys-only design cannot

### Spelling resolution — three layers

> **A note on the name, because it is a rename.** Phase 1b called this bundle a *profile* and let you select one by name (`[profile.english]`, `--profile strict`). That named-selection mechanism is deleted. The bundle of constraints survives, is renamed **`spelling`**, and becomes layered rather than selected.
>
> The rename is not cosmetic: `profile` was doing two jobs — naming the deleted lookup mechanism *and* naming the surviving constraint block — which is genuinely confusing to read. It is also more accurate. Every one of the five keys constrains **written form**: length, character set, repeated letters, forbidden substrings. The code calls it "pronounceability" because the intent is a name a player can say aloud, but the checks are orthographic.

Each layer overrides individual keys of the one beneath:

1. **Built-in defaults** — `max_length=12`, `ascii_only=true`, `max_repeat=2`, `forbidden=["ng'", "''", "--"]`, `max_join_length=9`
2. **The setting** — `[names.spelling]` in `campaign.toml`
3. **The culture's own `[spelling]`** table

Layer 3 is what makes portability real: a culture whose syllables need `max_join_length = 20` says so in its own file and carries that with it.

**Named profiles and the `--profile` flag are removed.** Both existed because a profile was a file-level setting one might want to swap wholesale. Once pronounceability is per-culture, a global override mostly makes imported cultures generate badly. `[profile.strict]`, the fixture invented in Phase 1b to test the flag, goes with it.

### Setting-level configuration

```toml
[names]
cultures = "names/cultures"      # a DIRECTORY (was: inventories, a file)
official_culture = "vashkand"    # optional; omit and the feature disappears

[names.spelling]                 # optional setting-wide overrides
ascii_only = true
```

`inventories` is renamed to `cultures` because it now names a directory.

### CLI

**Shipped in Plan 2 (#40).** Written in the future tense below because that is how it was
designed; `--sex` no longer exists, so read "today" as "before Plan 2".

- **`--sex` becomes `--gender`**, free-form values instead of `choices=["m","f","n"]`. The tool is unpublished; no alias.
- **Omitted** → all of that culture's categories, concatenated in declared order. Matches the old `--sex n`.
- **A named culture lacking the category** → error naming that culture's actual categories.
- **Across all cultures** → print only those having it; error listing what exists where, if none do.
- **`--list`** gains a categories column and loses nothing.
- Culture display order is **alphabetical by key**, since `order` is gone.

## The portability check

A script that **manufactures two cultures with randomised parameters, proves two properties, reports, and tears everything down.** It is the detector this project has repeatedly needed: every enumeration of "the campaign-specific bits" made by reading code has been incomplete — five times — while the one exercise that *built a second setting* found a real bug immediately.

It lives at `tests/check_portability.py`, runs standalone with a report, and is also exercised by the suite so it cannot rot.

### Generated cultures

Two cultures with randomised: category count (1–5) and arbitrary category names (never `m`/`f`/`n`), pool sizes, syllable lengths, `join`, `place_split`, `given_syllables` range and weights, and `[spelling]` constraints.

**Their alphabets are disjoint.** Culture A's syllables are built from one character set, culture B's from another with no overlap. That is what makes contamination decisive rather than inferential: any character from B's alphabet appearing in an A name is contamination, with no need to parse joins or reason about pool membership.

Randomisation is **seeded**, default fixed so the suite is deterministic; an explicit seed argument allows exploratory fuzzing. A failure reports its seed so it can be reproduced.

### Property 1 — fully contained in its one file

For a culture whose `[spelling]` fully specifies every key:

- generate names with seed S in setting X;
- generate names with seed S in setting Y — a different directory, a different sibling culture, different `[names.spelling]` settings, no `official_culture`;
- **assert the output is identical.**

And the converse, so inheritance is proven rather than assumed: a culture that *omits* spelling keys, placed in two settings whose `[names.spelling]` differ, **must** produce different output. A test that only checks the first property would also pass if the spelling layers were ignored entirely.

### Property 2 — only the data specified

Against generated names from culture A:

- **No cross-contamination.** No name contains any character from B's disjoint alphabet. Checked for family names, given names across every category, and place names.
- **Categories are honoured.** Names requested for category C draw only from `given_C`. With per-category disjoint sub-alphabets, this is a character check too.
- **No generator assumptions leak.** Specifically: a culture with a single category works; a culture with five works; category names bearing no resemblance to `m`/`f`/`n` work; a culture omitting `join` concatenates; omitting `place_split` never splits; omitting `given_syllables` uses 1–2; omitting `species`/`draws_on` loads and generates; and with no `official_culture` configured, no official name is ever produced.

### Reporting and teardown

Prints a per-property report naming what was generated, what was checked, and the seed. Everything is created under a temporary directory and removed afterwards, including on failure — the workspace is never written to.

## The shipped fixture setting

> **Superseded.** `names/example/` shipped as described below, then was deleted once the
> sample-settings work landed (`2026-07-29-sample-settings-design.md`, #46) and replaced by
> `samples/1-one-people/`, sample 1 of an eight-sample ladder that inherited this fixture's
> three jobs. The rest of this section is kept as the historical record of what Plan 1 and
> Plan 3 actually built; it no longer describes the current tree.

`names/example/` — a small, invented, complete setting shipped with the tool: two or three cultures with placeholder `species`/`draws_on`, demonstrating every key including a `[spelling]` block.

It replaces Phase 1b's single `names/example.toml`, which the per-file layout obsoletes, and serves three purposes: it documents the schema by example; it gives the generator's tests a setting that is not this campaign's; and it is what a new user copies to start.

> **Partly shipped already.** Plan 1 created `names/example/` with `riverfolk.toml` and
> `saltmarsh.toml` and deleted `names/example.toml`, because leaving a worked example of the
> *old* schema in the tree for three more plans would have been worse than moving the work
> forward. Between them the pair demonstrates every key that exists today, with one setting
> all three optional keys and the other omitting all three.
>
> **What is still owed: the `[spelling]` block.** It cannot be demonstrated until Plan 3
> creates it, so **Plan 3 must add `[spelling]` to one of the two example files** — placed
> last, after every bare key, which is the trap this document warns about above. A fixture
> that omits the one key the phase exists to introduce would document the schema by
> understating it.

**The problem it solves is concrete.** A third of the generator's tests are coupled to the campaign's inventories — the golden constants, named-culture `CULTURES` lookups, hardcoded expected names. The parent spec keeps `names/cultures/` in the private campaign repo while the engine ships public, so **that fraction of the tool's coverage of its own generator cannot ship with the tool.** The fixture is what lets those tests be rewritten against public data.

> **Do not quote a fixed count here.** This paragraph originally said "17 of the generator's 29
> tests", measured mid-Phase-1b. The file has since been 29, 45, and is **59 as of Plan 1
> (24 coupled, 35 portable)**. The ratio has held near a third throughout while every absolute
> number went stale within a phase. Re-derive it when you need it; the parent spec's
> carry-forward item 4 is the durable record.

Rewriting all 17 is **not** in this phase. This phase ships the fixture and rewrites what the category migration touches anyway; the rest is Phase 2 or 3 work, and the parent spec should record it.

**Placeholder discipline applies.** The fixture ships `species = ""` and `draws_on = ""`. Which real naming tradition a fantasy species draws on is a setting-authorship decision, and the tool takes no position on it — the constraint the parent spec already carries.

## Migration

The campaign's ten cultures become ten files under `names/cultures/`, each with `categories = ["m", "f"]`, `given_m` = old `given_m + given_n` and `given_f` = old `given_f + given_n`, in that order. `given_n` disappears; `label` becomes `name`; the old `names/cultures.toml` is deleted.

Nothing is lost. `--sex n` never meant "neutral names" — it meant "any" — which the omitted `--gender` flag still gives.

## Test consequences

> **Corrected after Plan 1 landed.** This section was written against goldens that were
> single strings captured from a no-argument, all-cultures run. Plan 1 re-shaped all three
> into **dicts keyed by culture**, captured from single-culture runs, because removing `order`
> re-partitions the shared RNG stream and would otherwise have broken every one of them. The
> fates below are unchanged in substance; the units they apply to are now per-culture entries.

| Golden constant | Fate |
|---|---|
| `PLACE_SEED_42` | **survives, all ten entries** — places never touch given pools |
| `FEMALE_SEED_7` | **survives, all ten entries** — `given_f` is the identical pool in identical order |
| `PERSON_SEED_42` | **regenerates, all ten entries** — "any" becomes `m+n+f+n`, neutral syllables duplicated |

One constant re-baselines, in the phase that causes it. The plan must record its previous values in the commit message — now ten entries rather than one string.

This is worth stating plainly because Phase 1b expected a re-baseline, planned for it, and then did not need one — the guard rail survived every task. Here the loss is real and unavoidable: self-contained categories change what "any" draws from.

The other two surviving is not a lucky accident but a design consequence of folding `given_n` in **order**, and the plan must preserve that order for exactly this reason.

**The re-baseline is now per-culture, which is a real gain.** Under the old shape a regenerated
`PERSON_SEED_42` was one opaque string: any accidental extra change hid inside it. Now a
diff names the culture that moved, so "only the categories change caused this" is checkable
rather than asserted.

## Out of scope

- **Rewriting all 17 campaign-coupled tests** against the fixture. Ships the fixture; leaves the bulk migration to a later phase.
- **The remaining untunable constants.** `range(10)` (join retries) and `range(50)` (name and place retries) are tuned against this campaign's pool sizes, and `min=1, max=2` is hardcoded as the `given_syllables` default in two places. All inert today; all the same shape as the `max_join_length` bug. Recorded so the enumeration is not claimed complete a sixth time.
- **Restoring deliberate culture ordering.** `order` is removed; alphabetical is the rule. If it is missed, an optional list in `campaign.toml` is the cheapest way back.
- **Anything in the parent spec's Phase 2** — workspace resolution, package layout, lazy config binding.

## Success criteria

1. A culture file is copied from one setting into another, unmodified, and produces byte-identical output for the same seed — proven by the portability check, not by inspection.
2. `grep -rnE "given_(m|f|n)\b" scripts/` returns nothing; no category name is known to the engine.

   > **The word boundary is load-bearing, and its absence made this criterion unsatisfiable.**
   > As originally written this read `grep -rn "given_m\|given_f\|given_n" scripts/`, which can
   > *never* be empty: `given_n` is the first seven characters of `given_name()`, the module's
   > central function. Plan 2 hit this and correctly flagged it rather than renaming
   > `given_name()` to satisfy a literal grep — a rename that would have rippled through
   > `person_name()`, the docstring, and the tests for a cosmetic fix to a regex.
   >
   > Anchored as above it returns nothing, which is the real claim: every surviving `given_`
   > construction in `scripts/` is a dynamic f-string (`given_{cat}`), and the only hardcoded
   > `given_`-prefixed literal is `"given_syllables"` — a tuning table, not a category.
   >
   > `docs/superpowers/plans/2026-07-29-phase-1c-plan-2-categories.md` carries the unanchored
   > version in three places. It is left alone deliberately: plans are point-in-time execution
   > records, and that one records what the implementer was actually told. This document is the
   > live one.
3. The suite is green at every commit, with the count asserted explicitly, never inferred from a green "OK".
4. **Generation is unchanged except where categories change it.** `PLACE_SEED_42` and `FEMALE_SEED_7` pass byte-for-byte across the whole phase, all ten entries each; only `PERSON_SEED_42` re-baselines, and only in the plan that introduces categories.

   > **This criterion originally read "byte-identical to their Phase 1b values", and that is
   > now impossible to satisfy — not because behaviour changed, but because the constants did.**
   > Plan 1 re-captured all three from single-culture runs, so their literal values differ from
   > their Phase 1b values while the generation they characterise is provably identical. The
   > original wording conflated the constant's text with the behaviour it guards, and those two
   > decoupled the moment the goldens were re-shaped. Read it as a statement about *generation*,
   > which is what it was always reaching for, and take Plan 1's own commit as the baseline
   > rather than Phase 1b's.
5. `python3 scripts/review.py checkup` reports `0 error(s), 0 warning(s)`.
6. A culture file omitting `name`, or colliding with another, fails at load with a message naming the file — both files, in the collision case.

## Decomposition

This is larger than one plan. Expect roughly four, each its own PR:

1. **Per-file loader** — directory scan, `name` identity, collision detection, `[names].cultures`; the campaign migrated to ten files with the existing m/f/n pools intact so the goldens hold. **DONE** — PR #37.
2. **Categories** — the general model, `--gender`, `given_n` folded in, `PERSON_SEED_42` re-baselined. **DONE** — PR #40.
3. **Spelling layering** — three layers, `--profile` and named profiles removed, `[spelling]` in culture files, **and `[spelling]` added to the shipped example** (see *The shipped fixture setting*). **DONE** — PR #43. The example's `[spelling]` landed on `saltmarsh.toml`, not `riverfolk.toml`: riverfolk's longest two-syllable join is 8 characters against a built-in cap of 9, so an override there would have been inert, while saltmarsh's is 11 and genuinely needs one.
4. **Portability check** — `tests/check_portability.py`. Originally "portability check and fixture"; Plan 1 shipped `names/example/` early and Plan 3 completes it, so what remains here is the check itself. **DONE** — branch `phase-1c-portability`; PR #46.

Plan 1 deliberately precedes plan 2 so the storage change and the behaviour change are never in flight together — the same reason Phase 1b repointed its tests before deleting the code they tested.
