# Sample Settings — Design

> **Provenance:** a scrubbed copy of a development record from the
> private campaign repository where this tool was first built. Campaign
> identifiers are neutralised throughout; the verbatim original stays in
> that private repo. Staged for publication 2026-08-02.

**Date:** 2026-07-29
**Status:** Design approved; awaiting plan.
**Depends on:** Phase 1c Plan 3 (`[spelling]` layering, PR #43), which must merge first.
**Parent spec:** `docs/superpowers/specs/2026-07-29-portable-cultures-design.md`

## Goal

Ship a ladder of sample settings, each isolating one axis of the naming schema, so a new user can pick the one closest to their campaign, **copy it into place, and immediately get working names**.

Today the only worked example is `names/example/` — two cultures demonstrating the flat schema. It shows the file format but answers none of the questions a person actually arrives with: how do I model several peoples? genders that aren't male and female? a name that changes with context? an imperial administrative language over local vernaculars?

## The constraint this design had to route around

The parent spec forbids something a naive version of this feature would ship:

> **The tool ships no species-to-real-world-basis mappings, and must not.** Deciding that a given fantasy species draws on a given real-world naming tradition is a setting-authorship decision with obvious ways to go badly. […] Any pairing appearing in documentation is an illustration of the file format, never a default, a recommendation, or a starting point.

The obvious design for sample 2 — "humans are from X, elves are from Y, dwarves are from Z" — is exactly that mapping, and a `samples/` directory is a worse home for it than documentation, because the Phase 1c design describes the shipped example as *"what a new user copies to start"* — one of the three things that sentence names as forbidden.

**Resolution: decouple species from culture.** A culture is a **place**, not a people. Several species live in each place and share its names. Every sample culture ships `species = ""`. Lookup happens through `draws_on`, not species.

This never makes the decision the constraint is about, while still teaching the thing worth teaching: that good invented names are grounded in a real linguistic tradition.

## Two conventions, applied uniformly

**1. Culture `name` is an invented place; `draws_on` names a real attested tradition.**

The setting is fiction; the linguistic grounding is real and named. So the tool asserts nothing about any real polity or people, and a reader still learns where to go for source material.

**2. Traditions are historical and non-living.**

Sogdian, Old Turkic, Ge'ez, Imperial Aramaic, Nabataean, Meroitic, Tocharian, Elamite. Three reasons:

- **Non-Western**, as required.
- **No living community's current naming practice is flattened into fantasy flavour.** This is the milder cousin of the concern the parent spec cites, and it is cheap to avoid.
- **No overlap with the campaign.** The private campaign uses ten modern East and Southeast Asian traditions. Public samples drawing on the same set would substantially mirror it, cutting against the public/private split this whole phase exists to create.

## Layout

`samples/` at the repo root. Culture files live in a `cultures/` subdirectory of each sample.

```
samples/
  README.md                       the ladder, in teaching order
  1-one-people/
    README.md
    cultures/
      <one>.toml
  ...
  7-official-language/
    README.md
    campaign-additions.toml       setting-level lines to merge
    cultures/
      *.toml
```

**The `cultures/` subdirectory is load-bearing, not tidiness.** `load_cultures()` globs `*.toml` and treats every match as a culture, and the glob is non-recursive (verified). Putting cultures one level down means a sample can ship a real `campaign-additions.toml` without the loader trying to parse it as a malformed culture. It also makes the copy target unambiguous: you copy `cultures/*`, not "the parts of this directory that are cultures".

## The eight samples

Teaching order. Each sample is self-contained — no sample depends on another's cultures.

| # | Directory | Isolates | Copy-and-go |
|---|---|---|---|
| 1 | `1-one-people` | The floor. One culture, `categories = ["personal"]`, zero optional keys. | yes |
| 2 | `2-many-peoples` | Several cultures; alias lookup via `draws_on`; species decoupled. | yes |
| 3 | `3-name-shape` | `join`, `place_split`, `given_syllables`. | yes |
| 4 | `4-genders` | Genders that are not male/female. | yes |
| 5 | `5-name-registers` | Categories that are not genders at all. | yes |
| 6 | `6-spelling` | A culture's own `[spelling]` against the built-in floor. | yes |
| 7 | `7-official-language` | `official_culture` — local plus administrative names. | **no** |
| 8 | `8-capstone` | Everything at once. | **no** |

**"yes" carries a precondition.** Copy-and-go for samples 1–6 holds when the target campaign's `[names].official_culture` is unset, or already names a culture the sample itself supplies — the loader validates this and fails at import otherwise. The campaign's own `campaign.toml` points `official_culture` at one of its own cultures, which no sample ships, so copying any of samples 1–6 over the campaign's own `names/cultures/` also requires clearing or repointing that key first. Each sample's README states this explicitly rather than leaving "yes" to imply no setup at all.

### 1 — one-people

One culture, one category, no optional keys. `draws_on = "Sogdian"`.

Everyone in the setting shares one naming scheme regardless of species. This is also **what `init` ships**, inheriting that job from `names/example/`.

A single category demonstrates something easy to miss: `categories` need be neither plural nor gendered. Omitting `--gender` concatenates all categories, which here is just the one.

### 2 — many-peoples

Three invented places drawing on Sogdian, Old Turkic, and Ge'ez — Central Asian, steppe, and Horn of Africa.

Every culture ships `species = ""`, with a comment saying so explicitly: *anyone from here, whatever their species, has a name from here.* Lookup is by tradition (`generate_names.py sogdian`), which exercises `resolve()`'s `draws_on` path without touching species.

This is the sample that carries the decoupling lesson, so its README states the reasoning rather than leaving a reader to infer it from an empty field.

### 3 — name-shape

Two cultures with contrasting generation knobs: one `join = "hyphen"` with `place_split = 0.5`, one `concat` with no splitting, and different `given_syllables` weights.

Two is enough to contrast; a third would add files without adding a lesson.

### 4 — genders

One culture recognising four genders: **Nexus, Steward, Wildheart, Shaper**.

`categories = ["nexus", "steward", "wildheart", "shaper"]`, with a `given_<category>` pool for each.

**Category names are lowercase in the file and capitalised in prose.** Category matching is case-sensitive (verified), while culture names are case-insensitive through `culture_key()`. Lowercase keys mean `--gender nexus` works as typed; the README and the file's comments write them as Nexus, Steward, Wildheart, Shaper. Shipping capitalised keys would force `--gender Wildheart` on every invocation, and a sample that ships friction teaches friction.

This is the most directly useful sample in the ladder. It is also the **first thing in the repo to demonstrate what Phase 1c Plan 2 actually built** — the campaign's ten cultures and both current example files all still use `["m", "f"]`, so the feature that deleted `choices=["m","f","n"]` has no worked example anywhere.

### 5 — name-registers

Categories that are not genders at all: `["public", "kin", "initiate"]`. One person holds a public name, a name used within kin, and one taken at initiation.

This is the conceptual leap, which is why it follows the gender sample rather than preceding it: readers arrive asking how to do genders, and should get that answered before being shown that the mechanism was never about gender.

Note the mechanism honestly: categories select which pool the *given* name is drawn from, so these are registers of personal name, not separate name components.

### 6 — spelling

Two cultures with deliberately long syllables. One carries its own `[spelling]` raising `max_join_length`; the other does not, so its long compounds stay unreachable against the built-in floor of 9.

Copy-and-go, because a culture's `[spelling]` overrides the **built-in defaults** with no setting-level config required. Ships an **optional** `campaign-additions.toml` with a restrictive setting-wide `[names.spelling]`, so a reader can also watch the middle layer bite — and so the test can exercise all three layers.

`saltmarsh.toml`'s existing `[spelling]` block — placed there in PR #43 for measured reasons — becomes this sample's material rather than being deleted with the rest of `names/example/`.

### 7 — official-language

Regional places plus an administrative culture drawing on **Imperial Aramaic**, which was historically an actual administrative lingua franca layered over local vernaculars. The mechanism and the illustration reinforce each other instead of the illustration being arbitrary.

Places print `Local            official: Administrative`.

**Not copy-and-go.** `official_culture` lives in `campaign.toml` and has no culture-level equivalent, so this sample needs a two-line merge. Its README says so in the first paragraph rather than burying it.

### 8 — capstone

Several places, non-gender categories, mixed name shapes, one culture with its own `[spelling]`, a setting-wide `[names.spelling]`, and an official language. Requires the merge.

## What `names/example/` leaves behind

`names/example/` is deleted. Sample 1 inherits its three jobs:

| job | today | after |
|---|---|---|
| documents the schema | `names/example/` header comments | `samples/README.md` + `1-one-people/` |
| cannot rot | `test_shipped_worked_example_loads_cleanly` | a discovery test over every `samples/*/` |
| what `init` copies | `names/example/` | `samples/1-one-people/` |

The anti-rot test becomes **data-driven**: it discovers sample directories rather than naming them, so a ninth sample added later gets coverage automatically instead of silently going untested.

### Every reference to it, and what happens to each

Enumerated rather than described, because a stale pointer to a deleted directory is exactly the drift this project keeps having to clean up:

| reference | action |
|---|---|
| `names/example/riverfolk.toml`, `saltmarsh.toml` | deleted; `saltmarsh`'s `[spelling]` block becomes sample 6's material |
| `tests/test_generate_names.py` — `test_shipped_worked_example_loads_cleanly` | replaced by the discovery test |
| `2026-07-28-tool-campaign-split-design.md` — the `init` section | repointed to `samples/1-one-people/` |
| `2026-07-29-portable-cultures-design.md` — *The shipped fixture setting* | repointed |
| Phase 1c plans 1, 2 and 3 | **left untouched** |

The three plans are point-in-time execution records. They describe what their implementers were actually told, and rewriting them to match a later state erases the fact that the state changed — the same call already made for the mis-anchored `given_n` grep, which those plans still carry. The specs are the live documents; the plans are history.

## Testing

Two layers.

### Load coverage — discovery

Iterate every `samples/*/` directory, `load_cultures(sample / "cultures")`, and assert it loads with at least one culture. Cheap, and it is what makes the samples un-rottable when the schema next changes.

### Copy-and-go — subprocess against a temp workspace

This is the test that proves the design's central promise, and its shape is forced by two facts:

- **`CULTURES` and `SPELLING` are module-level, bound at import.** A test that copies files into place in-process would never see them, because `person_name`/`place_name` read the module dicts. So the CLI must run as a **subprocess**.
- **`WORKSPACE = Path(__file__).resolve().parent.parent`.** Copying `scripts/` and `campaign.toml` into a temp directory makes the subprocess resolve its workspace *there*.

Per sample: build a temp workspace → copy `cultures/*` into its `names/cultures/` → apply `campaign-additions.toml` if present → run the CLI as a subprocess → assert exit 0 and non-empty output → discard the temp directory.

**The test must never copy into the real `names/cultures/`.** Beyond mutating the working tree and leaking files on a crash, extra cultures change the no-argument iteration order and would **break the campaign's three golden constants** while present.

Because the test can apply the fragment a human is told to merge, all eight samples are covered uniformly. Only the *manual* flow has an extra step, and only for samples 7 and 8.

### Per-sample property assertions

Beyond loading, assert the thing each sample exists to teach:

- **4** — `categories` is exactly the four gender names; `--gender nexus` succeeds and draws only from `given_nexus`.
- **5** — no category is `m`, `f`, or `n`.
- **6** — the culture carrying `[spelling]` resolves to a different `max_join_length` than its sibling, and generates a compound the sibling cannot.
- **7** — a `--place` run prints `official:`.
- **8** — all of the above hold together.

## Runnability, stated honestly

Every sample is test-covered from day one, because `load_cultures()` and `resolve_spelling()` take their inputs directly.

**No sample is runnable against an unmodified `campaign.toml` without copying it into place**, because `--workspace` does not exist — `WORKSPACE` is derived from the script's location, and lazy config binding is Phase 2 carry-forward item 3. Copying into `names/cultures/` is the supported flow, and it works today. Each README says this rather than implying you can point the tool at a sample in situ.

## Success criteria

1. Eight sample directories, each loading through `load_cultures()`.
2. Copy-and-go proven by subprocess test in a temp workspace for all eight.
3. `names/example/` no longer exists; nothing references it.
4. The campaign's three golden constants pass byte-for-byte — no sample test touches `names/cultures/`.
5. No `.toml` file in any sample root; cultures live only in `cultures/`.
6. `grep -LE 'species *= *""' samples/*/cultures/*.toml` returns nothing — no sample asserts a species-to-tradition mapping. (Run verbatim without `-E` and the whitespace-tolerant pattern, the literal `grep -L 'species = ""'` returns all 17 files, because every culture pads its `=` for alignment — the same literal-grep defect already hit once with `names/example`.)
7. No sample's `draws_on` names a tradition the campaign uses.
8. `python3 scripts/review.py checkup` reports `0 error(s), 0 warning(s)`.

## Out of scope

- **`--workspace`.** Phase 2 owns it. Until then, copying into place is the flow.
- **Case-insensitive category matching.** The asymmetry with `culture_key()` is real and worth fixing eventually, but it is a production behaviour change and this ticket changes no production code. Sample 4 routes around it with lowercase keys.
- **Rewriting the campaign-coupled tests** against a sample. Parent spec carry-forward item 4; a later phase.
- **An `install-sample` helper.** Phase 3's `init` is the natural home for that; building one now would duplicate it.

## Estimated shape

Roughly 16 culture files, 9 READMEs, 3 `campaign-additions.toml`, one new test module. **No production code changes.**
