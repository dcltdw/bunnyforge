# Phase 4 — the public cut: Design

> **Provenance:** a scrubbed copy of a development record from the
> private campaign repository where this tool was first built. Campaign
> identifiers are neutralised throughout; the verbatim original stays in
> that private repo. Staged for publication 2026-08-02.

**Parent:** `2026-07-28-tool-campaign-split-design.md`, sections "Phases 4–5 —
DEFERRED" and "Why the phase boundary sits where it does". This document turns
that deferral into an authorised, buildable design. Where the two disagree,
this one governs; every deviation is listed in "Deviations from the parent
spec" below.

**Also governs from:** `2026-07-31-phase-3-init-design.md`, whose drift-guard
section explicitly defers its rework "recorded here so it is not rediscovered"
to this phase. That rework is designed in "The drift guard splits in three".

**Goal:** the tool becomes `bunnyforge` — a public, MIT-licensed,
`pip`-installable package at `github.com/dcltdw/bunnyforge` with fresh
history, its own CI, and a `bunnyforge` CLI — and the campaign repo becomes
its first consumer, depending on a pinned published version. This ends the
deliberate transitional state (campaign repo contains the package) that
Phases 2–3 created.

**State when written:** `main` at 1df6629, working tree clean, no open PRs,
no server branch but `main`. All standing gates re-derived this session, not
quoted: **398 tests** green through both doors (`python3 -m
ttrpgkit.run_tests` and `python3 -m unittest discover -s tests -t .`),
`review checkup` **0 errors, 0 warnings**, `tests/check_portability.py` exit
**0**, the campaign-name grep over `src/` **empty**.

## The question this phase had to answer first

The parent deferred Phases 4–5 to buy evidence: *"If the first campaign
session reveals `ENTITY_DIRS` is the wrong model, Phase 1–3 code changes a
tuple; a released package changes an interface with users on it."* Measured
today, that evidence has not arrived. The campaign has **0 entity files** in
every content directory except Mechanics (6 house rules) — byte-for-byte the
finding that shaped the original design. `ttrpgkit init` has never scaffolded
a real campaign. The dispatcher was deferred at Phase 3 for this same want of
evidence.

The case was put to the user before anything was designed, both directions:
deferral's failure mode is that it waits on play that may never come, and
self-play by the tool's author is weak evidence anyway — real evidence is a
stranger using the tool, which requires publishing. **The user decided
2026-07-31: cut now, with the sample-size-of-zero risk explicitly accepted.**
The recorded mitigation is the `0.x` version line: semver's 0.x rule
("anything may change before 1.0") is the public statement that these
interfaces are young and unproven. This spec's job is to make the cut clean,
not to relitigate the decision.

## Decisions taken with the user (2026-07-31)

| decision | choice |
|---|---|
| Go / no-go | **Cut now.** Evidence-from-play has not arrived and the risk of committing to unproven interfaces is accepted; mitigated by publishing as `0.1.0` under semver's 0.x rules, not as a stable release |
| Public name | **`bunnyforge`** — package, command, and repository. Unregistered on PyPI (HTTP 404, checked 2026-07-31); `github.com/dcltdw/bunnyforge` does not yet exist and will be created by this phase. The parent's anticipated rename is real: `ttrpgkit` → `bunnyforge`, mechanical, suite-guarded |
| Cut blockers | **All five open tool issues** resolved pre-cut: #24, #25, #69, #17 fixed; #27's decision written down and closed. No known bug or undocumented decision ships. #4 and #5 are campaign-side and stay |
| Phase 4/5 boundary | **Collapsed — one Phase 4**, staged internally; Phase 5 ceases to exist. The parent gave it no content beyond "deferred", and phases already decompose into many plans (Phase 2 took six) |
| Dispatcher | **Ships with the cut.** A published CLI's invocation style is the interface users get attached to; changing it after launch breaks users, before launch it breaks nobody. Overturns Phase 3's deferral — going public is the calculus change |
| Dev docs (28 plans/specs) | **Carry over, scrubbed** — scrubbed in place in the campaign repo so one canonical set exists, then copied at the cut; they leave the campaign repo at switchover. Campaign name and setting terms replaced per the scrub policy below |
| Work placement | **Maximal pre-cut** — everything that can land inside the current repo does, under the full 398-test net, so the cut itself is a copy of already-proven work |

> **Dev-docs row superseded (2026-08-02, the stage 5 redesign).** Two new
> user constraints overturned "carry over, scrubbed": **the historical
> record is preserved** — old plans and specs are not rewritten in a major
> way, and not deleted — and **the record may live only in the campaign
> repo**, so the public repo starts from scrubbed *copies*. Only the nine
> specs publish. The redesigned stage 5 section carries the new design;
> git history keeps the original.

## Measured ground truth

Measured 2026-07-31, this session; re-derive before building on any of it.

> **Stage 2 annotation (2026-08-01, the rename PR).** Re-derivation at stage 2
> caught four counts that have moved since this was measured. The suite is
> **444**, not the 398 in "State when written" — stage 1's five closures and
> stage 1b's derived-term gate each raised the floor. `src/` holds **14**
> modules, not 13 (`_dokuwiki_install.py` arrived with #24's wiki suite, #82).
> Dev docs number **33**, not 28 — stage 5's scrub inherits the larger corpus,
> everywhere this spec says "the 28". And "open issues exactly seven" no longer
> holds: #81 is open tool-side — see the annotation under *Deviations from the
> parent spec*.

> **Stage 3 annotation (2026-08-02, the stage 4 docs PR).** The dispatcher
> (#87) raised the floor to **455** — `tests/test_cli.py`'s 10 tests plus
> `run_tests` gaining `main(argv)` coverage. Two measured findings worth
> carrying forward: argparse `add_subparsers` + `nargs=REMAINDER` is broken
> for the dispatcher's contract on Python 3.13 — a leading option-like token
> after the subcommand (`bunnyforge review --help`) never reaches REMAINDER
> and dies as "unrecognized arguments" — so `cli.py` dispatches on the first
> token by hand; see the stage 3 plan for the verification matrix. And
> `python3 -m pip wheel .` leaves an untracked `build/` directory absent from
> `.gitignore`; stage 4's implementation PR carries the one-line fix. Note
> `test_cli.py` postdates every per-file reference count in this section and
> was classified at stage 4 like everything else.

> **Stage 4 annotation (the test-split PR).** The split re-derived every
> count. Pre-split floor **455**; post-split **460** = 427 portable + 33
> campaign (`test_campaign_names` 28, `test_campaign_terms` 4,
> `test_campaign_run_tests` 1). Files new since this spec's reference
> counts: `test_cli.py` (10, portable — its REPO hits are ship-tree reads),
> `test_dokuwiki_install.py` (16, portable), `test_campaign_terms.py`
> (campaign by design). Only one test physically relocated (the real-repo
> hygiene test out of `test_run_tests.py`); three de-couplings made
> shipped-content coverage portable instead of exiling it
> (`test_samples`, `test_init`'s doctrine fixture, `test_config`'s culture
> literal). The isolated portable run is a standing CI job until stage 8.

- `main` at 1df6629, clean; open issues exactly seven: #69, #27, #25, #24,
  #17 (tool), #4, #5 (campaign).
- Entity files: 0 in NPCs, Factions, Setting, Sessions, PCs, Ideas, Briefs,
  Perceptions, Handouts; 6 in Mechanics.
- PyPI: `bunnyforge` unregistered (HTTP 404 from
  `pypi.org/simple/bunnyforge/`); `ttrpgkit` also unregistered, so the
  working name was never squatted-in by us either.
- `github.com/dcltdw/bunnyforge`: 404 — does not exist.
- `src/ttrpgkit/` holds 13 modules plus `data/` (35 files) and a package
  README. `pyproject.toml`: `name = "ttrpgkit"`, `version = "0.1.0"`,
  `requires-python = ">=3.11"`, **no `[project.scripts]`**, package-data glob
  ships `data/**/*`.
- `TTRPGKIT_WORKSPACE` (the env-var override) threads through **9 modules**;
  the rename must catch it.
- Current CI (`.github/workflows/tests.yml`): single Python **3.13**, one
  door only (`run_tests -v`). The public CI below is strictly stronger.
- Campaign references per test file (case-insensitive campaign-name or
  `REPO` hits): the campaign-named predecessor of `test_campaign_names` 18
  (already campaign-side by design), `test_workspace` 10, `test_init` 8,
  `test_samples` 8, `test_retry_budgets` 8, `test_run_tests` 5;
  `test_deploy_export`, `test_export_player`, `test_generate_names`,
  `test_review`, `test_scripts` 1 each; `test_config`, `test_dokuwiki`,
  `test_import_perceptions`, `test_portability`, `check_portability` 0.
- Dev docs: **28** markdown files under `docs/superpowers/` (the parent
  checked 7). Campaign-name density up to 40 hits per file; setting-term
  hits (the then-checked subset of what is now the derived list) up to 29
  per file. The campaign name itself was never in the parent's checked
  pattern.
- `names/cultures/` holds exactly ten files — the ten culture stems, the
  derivation basis for the scrub term list.

## The design — eight stages

Stages 1–5 happen in the campaign repo under the full suite; stage 6 creates
the public repo; stages 7–8 finish the split. Each stage is one or more
plan/PR pairs, every PR on a branch off current `main`, approval before
merge.

### Stage 1 — hygiene: close all five tool issues

Five small plans, five PRs, one issue each:

- **#24** — `review.py` gains the wiki-config suite asserting live DokuWiki
  config invariants.
- **#25** — `import_perceptions.main()` stops silently dropping blank pages
  and reports them in its summary.
- **#69** — `species` / `draws_on` get load-time type validation, closing
  the last unvalidated optional culture keys (adjacent to init, which
  scaffolds a culture file into every workspace).
- **#17** — wiki export rewrites wikilinks so rendered pages link to
  wrappers, not raw content. The one real feature in the stage.

> **Stale when written:** the wikilink rewriting had already shipped on
> 2026-07-27 (a10f3a8), four days before this spec was drafted. #80 established
> that and closed #17 by documenting the shipped behaviour — and its one
> unverified assumption — rather than building anything. Stage 1 therefore
> contained no feature work at all.
- **#27** — the keep-hand-rolled-converters decision is written into the
  tool's docs (its revisit triggers included) and the issue closed as a
  recorded decision, not fixed code.

Suite floor rises as fixes add tests; each PR states its new floor.

### Stage 2 — rename: `ttrpgkit` → `bunnyforge`

One plan, one PR, in place: `src/ttrpgkit/` → `src/bunnyforge/`, every
import, `pyproject.toml`'s `name`, `TTRPGKIT_WORKSPACE` →
`BUNNYFORGE_WORKSPACE` across its 9 modules, test imports, and doc
references. Gate: full suite green through both doors under the new name,
checkup 0/0, portability exit 0. `grep -rni ttrpgkit` may still hit
historical dev docs; those stand by design — records keep the old name —
and stage 5's staged copies own the uses that publish.

### Stage 3 — the `bunnyforge` dispatcher

A new `cli.py`: thin argparse-of-subcommands mapping

```
bunnyforge init | review | export-player | deploy-export |
          import-perceptions | build-sheets | names | test
```

onto the existing `main(argv)` functions, plus
`[project.scripts] bunnyforge = "bunnyforge.cli:main"`. Module invocations
(`python3 -m bunnyforge.review`) keep working unchanged — the dispatcher
adds a front door, it does not move the house. Tests: each subcommand
reaches its module's main; `--help` lists all subcommands; an unknown
subcommand exits non-zero with one `error:` line, never a traceback.

Ordering: rename **before** dispatcher, so the dispatcher is born under its
real name and no `ttrpgkit`-named artifact ever gains new code.

### Stage 4 — the test split

The Phase 2 Plan 6 exercise (`test_generate_names.py` / the campaign-named
names test, guarded by `TestPortableBoundary`), extended to the rest of the
suite.

**Classification rule** (Plan 6's, restated): a test is campaign-coupled if
it touches the live campaign workspace, a golden constant derived from the
campaign's inventories, or a `REPO`-rooted path; portable if it builds its own
fixtures or exercises pure logic. The measured reference counts above are a
scent, not a verdict — every hit gets read at plan time. In particular,
`test_init`'s 8 hits are mostly the drift guard, which the next section
transforms rather than relocates, and a single `REPO` hit can be as shallow
as a fixture-path constant.

**Mechanics:** each mixed file splits into a portable file (keeps its name,
ships) and a campaign file (`test_campaign_<topic>.py`, stays).
The campaign-named names test is renamed `test_campaign_names.py` to join the
convention (and so no shipped doc need cite a campaign-named path).
`TestPortableBoundary` generalises from one file to a suite-wide guard: it
walks every portable test file and fails on any campaign marker — the
campaign name, or `REPO`-rooted paths outside fixtures. That guard is what
keeps the public suite public after the cut, when no human is comparing.

**Gate:** combined test count across both groups ≥ the pre-split count
(splitting must not delete coverage); suite green through both doors; and
the portable group green **in isolation** — run with the campaign files
removed from discovery. That isolated run is the dress rehearsal for the
cut.

### Stage 5 — the docs scrub

> **Redesigned 2026-08-02 with the user; this section is rewritten in
> place (git history keeps the original).** The stage as first designed
> scrubbed all dev docs in place, so exactly one canonical set existed and
> the cut copied it. Two new constraints overturned that: **the historical
> record is preserved** — old plans and specs are not rewritten in a major
> way, and not deleted — and **the record may live only in the campaign
> repo**; the public repo can start from scrubbed copies. The first
> design's decisive argument ("stage 6 copies this tree, so exempted
> records would publish the campaign's name hundreds of times") is
> dissolved by a copy-based cut rather than contradicted by it. The
> 2026-08-02 stage 5 plan stands verbatim as a record of the first design;
> a new plan supersedes it by reference.

**What publishes: the nine specs only.** The specs document designs that
still hold — current documentation, worth a public reader's time. The 27
plans are accounts of de-campaigning a private campaign; they stay in the
campaign repo, verbatim, forever, and their remaining scrub work (293
anchored hit lines, all in plan files) is cancelled.

- **The staging tree.** The scrubbed copies land in
  `public-docs/superpowers/specs/`, mirroring the destination layout;
  stage 6 copies the tree verbatim into the public repo and stage 8
  removes it, its job done. `docs/superpowers/` itself is never touched.
- **The content already exists.** The never-merged scrub branch
  (`feature/stage-5-docs-scrub`, tagged `stage-5-scrub-source` before it
  is eventually deleted) holds all nine specs fully scrubbed — 148
  anchored hit lines to zero, through three rounds of adversarial review.
  Stage 5 lifts those files rather than redoing the judgement. The term
  list stays derived, not guessed — `names/cultures/*.toml` plus the two
  extra terms `test_campaign_terms.py` defines — and the ratified
  replacement policy (R1–R9, in the superseded plan) governs any new
  scrub prose.
- **This spec's staged copy gets the redesign applied on top,** so the
  public copy tells the true genesis story of its own repo, not the
  first-design story its scrub predates. The redesign prose is written
  campaign-neutral from birth, so this costs no scrub work.
- **The wiki-export spec publishes only after a dedicated redaction
  pass.** It carries a real hostname, a domain, a wiki root, two other
  campaigns' names, and a player account name — none of them derived-term
  hits, so no term gate can ever catch them — plus stale pre-rename
  script paths left whole for internal consistency. The pass replaces the
  identifiers with neutral example forms, finishes the paths, and **the
  user reviews that file's staged diff** before the stage 5 PR merges.
- **Provenance header.** Each staged copy opens with a short note: a
  scrubbed copy of a private campaign repo's development record, campaign
  identifiers neutralised. The copies are openly derived artifacts, not
  corrected records — "reads naturally to a stranger" still governs, and
  truth-of-record is carried by the verbatim originals.

**Gate: a one-shot battery over the staging tree,** recorded in the stage
5 PR; no standing test. The planned fourth scan root over
`docs/superpowers/` is cancelled — the private tree legitimately keeps
campaign terms forever — so `test_campaign_terms.py`'s docstring promise
of it is corrected and the suite floor stays 460. The battery, every
member empty:

- the `\b`-anchored derived-term grep;
- the unanchored sweep for derivative tokens the anchored gate cannot see
  (terms inside longer tokens or across underscores);
- **the broken-stem sweep** — a culture stem broken by a space or hyphen
  (a two-word display form, a hyphenated filename) is a substring of
  *neither* pattern above once the separator is inserted; execution on
  the scrub branch found thirteen such survivors, so this sweep is a
  first-class battery member here and at stage 6;
- a literal grep for the wiki-export spec's known identifiers — knowable
  constants, checked mechanically here, never shipped in a test.

**Drift cannot bite.** Nothing downstream ever reads the private docs
again: stage 6 copies the staging tree exactly once, and the two lineages
are independent thereafter. Future tool dev docs are born in the public
repo; campaign-side dev docs continue here. Stage 6–8 annotations append
to this private spec only — the public copy is a labeled snapshot.
Preventing two-version drift was the whole argument for scrubbing in
place; a record frozen at the cut plus born-public future docs reaches
the same end without rewriting history.

### Stage 6 — the cut

`dcltdw/bunnyforge` is created **private**, assembled, proven green in its
own CI, and only then flipped public — no broken or campaign-tainted state
is ever publicly visible. Fresh history per the parent: the first commit is
the assembled tree; no campaign content is ever committed to it. Contents:

```
pyproject.toml            name = "bunnyforge", version = "0.1.0",
                          requires-python = ">=3.11", zero runtime deps,
                          [project.scripts] bunnyforge
LICENSE                   MIT
README.md                 new, public-facing: what it is, install,
                          quickstart (init → review checkup → names),
                          campaign.toml, the DokuWiki export pipeline
.github/workflows/
  tests.yml               matrix 3.11 / 3.12 / 3.13; both suite doors +
                          tests/check_portability.py
  publish.yml             PyPI trusted publishing, tag-triggered (stage 7)
src/bunnyforge/           the package, data/ included
tests/                    the portable files + check_portability.py
samples/                  the eight-sample ladder
docs/superpowers/         specs/ — the nine staged spec copies (stage 5);
                          future dev docs are born here
```

The campaign repo's root `README.md` belongs to the campaign and does not
travel; the public README is authored new for this repo.

**Cut gates, run in the new repo before flipping public:** portable suite
green on all three Python versions; a fresh `bunnyforge init` workspace
passes `review checkup` with 0 errors, 0 warnings; `grep -riE '<derived
term list>'` empty over the **entire tree**, docs included, plus stage 5's
broken-stem sweep (separator-broken stems are invisible to the anchored
grep); a secrets scan of the assembled tree before the first push.

> **Gate scope, settled by stage 1b (#83):** the derived-term grep cannot run
> as a blanket pass/fail gate over the entire tree — the user decided some
> culture-name references may legitimately remain, and the *enforced* gate
> (`tests/test_campaign_terms.py`) is scoped to `src/` and `samples/` with `\b`
> word boundaries, because the derived list contains an ordinary English word
> and stems short enough to sit inside longer tokens. At stage 6, run the
> whole-tree grep with the same word boundaries as a *review* pass and judge
> its hits; the automatic gate remains the scoped one.

### Stage 7 — publish

Tag `v0.1.0`; `publish.yml` releases to PyPI via **trusted publishing**
(OIDC — no long-lived token to store or leak). Post-publish smoke, in a
clean venv on a path containing no checkout:

```
pip install bunnyforge
bunnyforge init /tmp/demo --name Demo
bunnyforge review checkup --workspace /tmp/demo   → 0 errors, 0 warnings
```

### Stage 8 — switchover

One PR in the campaign repo that ends the transitional state.

**Leaves the campaign repo:** `src/`, `pyproject.toml`, the portable test
files, the staging tree `public-docs/` (copied at stage 6, its job done),
and the current `tests.yml`.

**Arrives:** `requirements.txt` pinning `bunnyforge==0.1.0` (exact); a
campaign CI workflow — `pip install -r requirements.txt`, then `python3 -m
unittest discover -s tests -t .`; and `test_campaign_drift.py` (below).

**Stays:** all campaign content and state docs, `names/cultures/` (the ten
inventories), the campaign-coupled tests, and the tool's dev docs under
`docs/superpowers/` — the development record through the cut, preserved
verbatim (2026-08-02 user constraint); future tool dev docs are born
public, campaign-side dev docs continue here. (The parent's architecture
also sketches a campaign-local `scripts/`; measured today it does not
exist, and this phase does not create it — it appears when campaign work
first needs it.)

## The drift guard splits in three

Today `tests/test_init.py` asserts byte-equality between `data/` and in-repo
canonicals in four pairings: `AGENTS.md`, the 16 `_Templates/` files, the 10
directory READMEs, and the sample culture. Phase 3's spec says this is "only
trivially possible while the package and the campaign share one repository"
and hands this phase the rework. The cut severs the filesystem relationship,
and the **canonical direction flips: `data/` inside the package becomes
canonical**; the campaign's live copies become downstream.

**1. Package side — ships public.** What the package can still see:

- *Manifest completeness:* every manifest entry names an existing `data/`
  file, and every file under `data/` appears in the manifest — no orphans in
  either direction. This is what catches "added a template, forgot the
  manifest" once no campaign copy exists to disagree with.
- *Init fidelity:* `init`'s output is byte-identical to the `data/` sources
  it copies — already implied by the manifest-driven writer, now asserted.
- *Sample coherence:* `data/cultures/vashkand.toml` ↔ sample 1's culture
  file. Both live in the public repo, so this pairing survives as a true
  byte-equality test, unchanged.
- The init-then-checkup and init-then-generate gates, unchanged.

**2. Campaign side — stays private.** A new `test_campaign_drift.py`: for
each tracked file (AGENTS.md, the 16 templates, the 10 READMEs), compare
the campaign's live copy against the **installed** package's `data/` via
`importlib.resources`. A byte difference fails, subject to a per-file
**allowlist carrying a one-line reason** for deliberate divergence. The
semantics are drift *awareness*, not enforcement: the test fires on package
upgrades ("upstream changed AGENTS.md — adopt or allowlist") and on local
edits ("you customised a template — allowlist or upstream it"). Files that
legitimately differ by design — the filled-in `style-guide.md` and
`situation-design.md`, the live state docs — were never guarded and stay
unguarded, exactly as Phase 3 drew that line.

**3. Until stage 8**, the existing byte-equality test runs unchanged. The
transitional state keeps its guard until the moment it ends.

## What replaces green-at-every-commit

Every phase so far stayed green in one repo under one suite; that
arrangement ends here. Its replacement is **two suites, two CIs, one pin**:

1. **bunnyforge CI**, every commit: portable suite green on 3.11/3.12/3.13
   through both doors, init-then-checkup 0/0, `check_portability.py` exit 0,
   derived-term grep empty over the whole tree.
2. **Campaign-repo CI**, every commit: campaign suite green against the
   *exact pinned version* of bunnyforge.
3. **The pin is the coupling point.** Upgrading bunnyforge in the campaign
   repo is a deliberate PR that bumps `requirements.txt` and reruns the
   campaign suite, where `test_campaign_drift.py` surfaces upstream doctrine
   and template changes for adoption or allowlisting. Nothing changes underneath
   the campaign silently.

Suite floors reset honestly at the split: **398 is a one-repo number that
stops being meaningful.** Each repo's floor is its measured count at cut
time, recorded in the cut and switchover PRs respectively, and each
successor spec tracks its own floor from there.

## Deviations from the parent spec

- **Phase 5 is erased.** The parent deferred "Phases 4–5" as a unit but gave
  5 no content of its own. User decision 2026-07-31: one collapsed Phase 4,
  staged internally.
- **"Migrate the tool issues" is expected to be a no-op.** The parent lists
  issue migration as Phase 4 work; the user's cut-blocker decision closes
  all five open tool issues *before* the cut, so there should be nothing
  left to migrate. If anything is open at stage 6 regardless, it is
  re-filed by hand in the public tracker (fresh repo, no transfer
  machinery) and closed in the campaign repo with a pointer.

> **Not a no-op after all:** #81 (assert effective permissions for GM
> namespaces — the invariant #24's wiki suite could not reach from config
> alone) was opened during stage 1 and will still be open at the cut. The
> fallback above is now the plan of record: re-file it by hand in the public
> tracker at stage 6 and close it in the campaign repo with a pointer.
- **`docs/superpowers/` does not ship verbatim.** The parent's architecture
  carries it over and calls it "checked for setting terms … and found
  clean" — stale twice over: the corpus has grown from 7 to 28 files, and
  the campaign name itself was never in the checked pattern. Measured today
  the docs are saturated with campaign terms. They ship **scrubbed** (user
  decision), under a derived-term gate.

> **Amended 2026-08-02:** narrowed — only the nine specs ship, as scrubbed
> staged copies under `public-docs/`; the plans stay in the campaign repo
> verbatim, and the tree no longer leaves at stage 8. See the redesigned
> stage 5.
- **The dispatcher ships, overturning Phase 3's deferral.** Phase 3 deferred
  it "until init has actually been used"; the user decided 2026-07-31 that
  going public changes the calculus — the published invocation style is
  itself an interface commitment, cheapest to set before anyone depends on
  it.
- **"Little more than moving that tree into a fresh repository"
  understates.** The parent's Phase 2 entry describes Phase 4 that way. As
  designed it is eight stages, because the user front-loaded issue hygiene,
  the dispatcher, the test split, and the docs scrub into the cut. The
  parent's core claim — the *move itself* is cheap because Phases 2–3 did
  the hard part — survives intact; stage 6 is the smallest stage here.
- **The campaign repo pins with `requirements.txt`, not a package
  dependency.** The parent says the campaign "depends on the published
  package" without naming a mechanism. After stage 8 the campaign repo has
  no `pyproject.toml` (it is a campaign, not a package), so the pin lives in
  `requirements.txt`.

## Out of scope

- **1.0.** Interface stabilisation, deprecation policy, and anything else
  that promotes bunnyforge out of 0.x. That is where evidence-from-use
  finally gets its say.
- Any second wiki backend; DokuWiki remains the only target (parent).
- A `bunnyforge.testing` fixtures module for campaign-local tests — still
  deferred until a real campaign test demands it (parent's out-of-scope,
  unchanged by the split).
- Migrating `_Ignore/` (79 untracked files, agents forbidden) — untouched,
  as in every phase.
- Issues #4 and #5 — campaign-side; they stay open in the campaign repo.
- Any scrub of the campaign repo's *git history* — the public repo's history
  is fresh, and the campaign repo stays private; rewriting its past buys
  nothing.

## Success criteria

1. **Stage 1:** issues #24, #25, #69, #17, #27 all closed before any public
   artifact exists; each closing PR green at or above the floor the previous
   PR set, the count stated explicitly.
2. **Stage 2:** suite green through both doors under the `bunnyforge` name;
   `BUNNYFORGE_WORKSPACE` honoured and `TTRPGKIT_WORKSPACE` gone;
   `grep -rni ttrpgkit src/ tests/` empty.
3. **Stage 3:** every subcommand dispatches to its module's main; from a
   pip install, `bunnyforge --help` lists all eight subcommands; unknown
   subcommand → one `error:` line, exit 1.
4. **Stage 4:** combined test count ≥ the pre-split count; the portable
   group green in isolation with campaign files removed from discovery;
   `TestPortableBoundary` guards every portable file.
5. **Stage 5:** the staging tree holds the nine staged spec copies; the
   anchored derived-term grep, the unanchored derivative sweep, the
   broken-stem sweep, and the wiki-identifier grep all empty over it, with
   the term-list derivation recorded in the plan; the user has reviewed
   the wiki-export staged diff; the suite floor unchanged at 460 (no new
   scan root). `docs/superpowers/` itself is untouched.
6. **Stage 6:** `dcltdw/bunnyforge`'s first *public* state is green on
   3.11, 3.12, and 3.13; a fresh `bunnyforge init` workspace passes
   `review checkup` 0/0; the derived-term grep and the broken-stem sweep
   are empty over the entire public tree; no secrets in the assembled
   tree.
7. **Stage 7:** in a clean venv containing no checkout,
   `pip install bunnyforge` then init → checkup passes 0/0.
8. **Stage 8:** the campaign repo contains no `src/` and no
   `pyproject.toml`; pins `bunnyforge==0.1.0` exactly; campaign CI is green;
   `test_campaign_drift.py` present and green; `review checkup` on the live
   workspace (via the installed package) reports 0/0.
9. Both repos' suite floors measured and recorded at cut time, in the cut
   and switchover PRs.
10. Every campaign-repo PR on a branch off current `main` with approval before
    merge; the public repo adopts the same rule from its first PR onward.
