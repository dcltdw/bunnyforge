# Phase 2 Plan 6 — Splitting the Campaign-Coupled Name Tests: Design

> **Provenance:** a scrubbed copy of a development record from the
> private campaign repository where this tool was first built. Campaign
> identifiers are neutralised throughout; the verbatim original stays in
> that private repo. Staged for publication 2026-08-02.

**Status:** implemented 2026-07-31 (this plan's PR).
**Parent:** `2026-07-30-phase-2-workspace-and-package-design.md`, "Plan 6 —
split the campaign-coupled tests" and the classification rule recorded there.
**Measured at:** `main` @ `226f8c2`, 2026-07-31. Re-derive before relying;
this document's own numbers go stale the same way the parent's did.

## Goal

`tests/test_generate_names.py` currently mixes two audiences. Portable tests
prove the engine and ship with it at Phase 4; campaign-coupled tests pin
the campaign's real output and stay with it forever. This plan divorces
them: portable tests keep the filename `test_generate_names.py`; coupled
tests move to a new `tests/test_campaign_names.py`. A guard test makes the
boundary self-enforcing rather than one-time.

**The classification rule (from the parent):** a test is coupled if it
touches a golden constant, a named culture, or a `run_cli` call against the
real inventory.

## Measured surface (2026-07-31 at `226f8c2` — re-derive before relying)

- The file holds **82 tests** (parent said 76); the suite holds **368**, and
  both doors agree: `python3 -m ttrpgkit.run_tests` and
  `python3 -m unittest discover -s tests -t .`.
- Against the rule: **26 hard-coupled, 7 gray, 49 cleanly portable** (parent
  said 22/54 — stale, as it predicted).
- **The gray 7 are the finding the rule missed.** They pass all three greps —
  no golden, no named culture, no `run_cli` against the repo — but they read
  `INV`, and `INV` is built from `open_workspace(REPO)` at module scope
  (`test_generate_names.py:19`). The parent's grep-based done-criteria are
  necessary but not sufficient: a file passing them can still be unable to
  run outside this repo.
- **The campaign's `[names.spelling]` is commented out** (`campaign.toml:26`), so
  `INV.setting_spelling == _DEFAULT_SPELLING`. The three `TestCultureSpelling`
  layering tests are therefore currently degenerate: "inherits the setting
  layer" and "falls back to the built-in default" are indistinguishable when
  the two are identical. The rewrite (below) fixes this latent
  reach-exceeds-verification defect, not just the coupling.
- `test_ambiguous_alias_exits_nonzero_and_names_candidates` builds its own
  temp workspace but seeds it by copying one of the repo's real culture
  files — coupled by grep and by dependency.
- Two portable-staying sites hold campaign tokens the guard would catch
  (found at plan-writing, 2026-07-31): `test_the_key_is_derived_from_the_name`
  uses a campaign culture's two-word display name and its derived key as its
  key-derivation example (`test_generate_names.py:321-324`), and a
  `TestLoadErrorsAreClean` comment spells the campaign's name
  (`:913`). Commit 1 scrubs both: the example becomes a synthetic two-word
  name (same claim, watched failing via a `culture_key` mutation); the
  comment says "campaign" instead. A sweep of every other guard token over
  the portable-staying regions found nothing else.
- Discovery: both doors run `TestLoader().discover` over `tests/` with the
  default `test*.py` pattern (`run_tests.py:98`). A flat file split changes
  nothing; a directory split would touch discovery on both doors.
- `run_tests.py` fails the run if the suite writes into its own workspace
  (issue #61). This plan churns test files — the likeliest tripwire for that
  guard. It is a safety net here, not an obstacle.

### Classification by class

| class | tests | coupled | gray | portable |
|---|---|---|---|---|
| TestSeededOutputIsStable | 4 | 4 (goldens) | — | — |
| TestDisplayOrder | 2 | 2 | — | — |
| TestDistribution | 7 | 3 | 2 | 2 |
| TestCultureResolution | 3 | 2 | 1 | — |
| TestResolveOfficialCulture | 4 | 3 | 1 | — |
| TestCultureLoading | 28 | — | — | 28 |
| TestSpelling | 5 | — | — | 5 |
| TestAmbiguityAndFlags | 6 | 6 | — | — |
| TestGenderFlag | 7 | 6 | — | 1 |
| TestSpellingResolution | 5 | — | — | 5 |
| TestCultureSpelling | 5 | — | 3 | 2 |
| TestLoadErrorsAreClean | 6 | — | — | 6 |

## Decisions taken with the user (2026-07-31)

1. **Scope: this one file only.** The other 13 test files stay unclassified;
   Phase 4 inherits the mechanism, not a finished taxonomy.
2. **The gray 7: rewrite 6, recouple 1.** Six are engine claims that use
   `INV` only for convenience — they rewrite onto self-built synthetic
   fixtures and stay portable. `test_every_generated_name_satisfies_the_spelling`
   is different: `check_portability.py` already proves the engine property
   synthetically, so this test's *surviving* value is validating the
   campaign's real culture data — it classifies coupled and moves untouched.
3. **Boundary form: flat file split plus a guard test.** No directory split,
   no marker scheme. Discovery stays untouched on both doors. The guard makes
   the parent's done-criteria continuous instead of one-time.
4. **Rule over spirit.** The 26 rule-coupled tests move as-is, even the
   incidentally-coupled ones (the ambiguity pair, the workspace-agnostic
   `run_cli` flag tests). The rule is mechanical by design; portable-izing
   more tests is Phase 4's call (non-goal 3).
5. **Staging: rewrite in place, then move** (two commits, one PR — see
   Execution). The alternative orderings either leave a broken intermediate
   state (gray tests stranded without `INV`) or mix rewrites into the move
   commit, where deleted coverage hides.
6. **No cross-file imports.** Each file is self-contained; `run_cli_in`
   (~8 lines) is duplicated in both. The coupled file must not import from a
   file destined to leave at Phase 4, and vice versa.
7. **The guard lives in `test_campaign_names.py`** — necessarily: its
   forbidden-token list *contains* the culture and golden names, which may
   not appear in the portable file.

## The design

### End state

Two flat files in `tests/`; no other file touched.

**`tests/test_generate_names.py` (portable, keeps its name) — 55 tests**
(49 clean + 6 rewritten). Module docstring states the contract: every test
builds its own fixtures; no golden constant, no named culture, no
real-inventory access; must pass in any checkout of any campaign; ships with
the engine at Phase 4. Keeps `run_cli_in` (workspace-parameterised). Loses
`REPO`, `INV`, `run_cli`, the three goldens, and `EXPECTED_DISPLAY_ORDER`.

**Follow-up, same PR, after final review (2026-07-31):** 55 is accurate for
what this plan moved. The final review found that `synthetic_inventory`'s
unused `official_culture` parameter was hiding a real coverage gap — no
portable test exercised `official_name()`'s non-`None` path (see the
non-goals entry below). Closing it added one test to `TestDistribution`,
bringing the portable file to **56 tests**.

**`tests/test_campaign_names.py` (new, campaign-coupled) — 28 tests**
(27 moved + 1 guard). Gets `REPO`, `INV`, its own `run_cli_in` plus
`run_cli`, the three golden dicts with their full "never edit these"
commentary, and `EXPECTED_DISPLAY_ORDER`. Docstring: characterisation suite
pinning the campaign's real output; stays with the campaign.

**Count arithmetic: 82 = 55 + 27; the guard adds 1 ⇒ suite 368 → 369.**
The constraint is "never drops"; it grows by exactly one.

**Follow-up, same PR:** the `official_name()` coverage test above adds one
more ⇒ portable file 55 → 56, suite 369 → **370**.

**Split classes keep their names in both files** (`TestDistribution` will
exist in both modules — legal in unittest). Renaming during a move is where
review vigilance dies; each split class gets a one-line docstring pointing at
its counterpart instead. One test changes meaning honestly:
`test_the_official_culture_prints_no_official_column` asserts on the golden
constants themselves, so it moves with them — it was always a claim about
the campaign's captured output, not the engine.

### The 27 movers, by name

- **TestSeededOutputIsStable (4):** `test_person_names_are_stable_under_seed`,
  `test_place_names_are_stable_under_seed`,
  `test_gender_bias_is_stable_under_seed`,
  `test_the_official_culture_prints_no_official_column`
- **TestDisplayOrder (2):**
  `test_no_argument_run_visits_cultures_in_the_expected_order`,
  `test_multi_culture_run_prints_the_name_species_drawson_header`
- **TestDistribution (4):** `test_forced_syllables_is_honoured_exactly`,
  `test_hyphen_join_only_where_configured`,
  `test_concat_culture_never_hyphenates`,
  `test_every_generated_name_satisfies_the_spelling`
- **TestCultureResolution (2):**
  `test_resolve_accepts_culture_species_and_basis`,
  `test_unknown_culture_exits_nonzero`
- **TestResolveOfficialCulture (3):**
  `test_correctly_spelled_key_resolves_to_itself`,
  `test_display_name_spelling_normalises_to_the_key`,
  `test_unknown_value_raises_naming_it_and_the_available_cultures`
- **TestAmbiguityAndFlags (6):**
  `test_ambiguous_species_returns_all_candidates`,
  `test_ambiguous_alias_exits_nonzero_and_names_candidates`,
  `test_syllables_flag_forces_the_count`,
  `test_syllables_zero_is_rejected`, `test_syllables_negative_is_rejected`,
  `test_list_shows_each_culture_s_categories`
- **TestGenderFlag (6):**
  `test_omitted_gender_uses_every_category_in_declared_order`,
  `test_named_culture_lacking_the_category_errors_and_lists_its_own`,
  `test_across_all_cultures_an_unknown_category_errors`,
  `test_across_all_cultures_prints_only_those_having_it`,
  `test_empty_gender_against_named_culture_errors_cleanly`,
  `test_empty_gender_across_all_cultures_errors_cleanly`

### The six rewrites (commit 1, in place)

A module-level builder (e.g. `_synthetic_workspace(testcase)`) writes a temp
workspace — `campaign.toml` plus two synthetic culture files with distinct
species/basis and invented names resembling no real culture — and returns
what tests need via `open_workspace` + `load_inventory`: the same composition
path a real campaign takes. `TestLoadErrorsAreClean` already establishes the
pattern; this builder makes a *valid* workspace instead of a broken one.

1. `test_resolve_returns_none_for_unknown` — `resolve()` against the
   synthetic cultures dict; same claim, synthetic data.
2. `test_official_name_is_none_without_a_configured_culture` — improves: the
   synthetic workspace *omits* `[names].official_culture`, exercising the
   real unconfigured load path instead of `INV._replace(...)`.
3. `test_unconfigured_returns_none` — `resolve_official_culture(None/"",
   synthetic_cultures)`.
4. `test_a_culture_without_spelling_inherits_the_setting_layer` — the base
   becomes a synthetic setting layer **differing from `_DEFAULT_SPELLING` in
   at least one key** (e.g. `max_repeat=3`), so inheritance is finally
   provable.
5. `test_a_culture_spelling_block_overrides_the_setting` — same non-default
   base; asserts the untouched key comes from the *setting* value, which the
   degenerate base could not distinguish from the built-in default.
6. `test_the_culture_layer_actually_changes_generation` — same base, one
   constraint carried explicitly: the synthetic setting layer **must leave
   `max_join_length` at its default 9**, because the tight/loose contrast
   (a 20-character join rejected vs admitted) is the test's whole mechanism.
   The implementation plan restates this at the fixture definition.

Every rewrite is mutation-tested in commit 1: break the behaviour the test
pins (per-test mutation named in the plan), watch red, restore, watch green,
purging `__pycache__` after every mutation and restore (the Plan 4 phantom).

### The guard test (commit 2)

One test, `TestPortableBoundary`, in `test_campaign_names.py`:

- Asserts `tests/test_generate_names.py` exists (path from `__file__`),
  failing loudly if the portable file is renamed — a guard that silently
  scans nothing is this repo's least favourite defect.
- Scans its text with a `subTest` per token, so one run names every
  offending token and its line:
  - **case-sensitive, word-boundary:** `PERSON_SEED_42`, `PLACE_SEED_42`,
    `FEMALE_SEED_7`, `INV`, `REPO` — `\bINV\b` cannot false-positive on
    `load_inventory` or `InventoryError`. (`open_workspace` is deliberately
    NOT banned: the portable fixture builder legitimately calls it on
    synthetic temp workspaces — the same reason `run_cli_in` survives. The
    `REPO` and `INV` bans are what block the coupled use of it.);
  - **literal:** `run_cli(` — not a substring of `run_cli_in(`, so the
    portable helper survives;
  - **case-insensitive:** the ten culture keys and the campaign's name.
- Watched failing with one planted token per category (an identifier, a
  culture name, a `run_cli(` call), then removed.

**Consequence, carried as an explicit rule:** because the campaign's name is
forbidden and the counterpart file was then the campaign-named predecessor of
`test_campaign_names.py`, the portable file's docstrings and comments never
name that file — cross-references say "the campaign-coupled suite" instead.

## Execution

One branch off freshly-pulled `main`, one PR into `main`, two commits, each
independently green. Board card Todo → In Progress at PR open.

**Commit 1 — rewrite in place.** The six rewrites, the two token scrubs
(measured surface, last bullet), and the shared builder land inside
`test_generate_names.py`, still unsplit. Nothing moves. Gate:
suite green at 368 on both doors; goldens byte-compared against `main` via
the Plan 5 script verbatim (live golden tests passing is a weaker claim);
`check_portability.py` exit 0; checkup 0/0.

**Commit 2 — pure motion plus guard.** Create `test_campaign_names.py`; move
the 27 tests, three goldens, `EXPECTED_DISPLAY_ORDER`, `REPO`, `INV`,
`run_cli_in` + `run_cli`; write both module docstrings; add the guard.
**No moved test's body changes in this commit** (the guard is the only new
code) — review asks "did anything change besides location?", answered with
`git diff --color-moved=dimmed-zebra`. The one permitted edit class:
docstring cross-references and each file's actual import list.

**The goldens comparison script needs its paths updated after the move:** the
`main` side still reads `main:tests/test_generate_names.py`; the working
side reads `tests/test_campaign_names.py`. The script's `assert o and n`
already refuses to "pass" by comparing nothing, but the plan states the
updated invocation rather than leaving it to be rediscovered mid-failure.

### Verification battery at commit 2 (outputs captured, never asserted from memory)

| check | expected |
|---|---|
| `python3 -m ttrpgkit.run_tests` | 369, green — also exercises the issue #61 self-write guard, for which this plan's file churn is the likeliest tripwire |
| `python3 -m unittest discover -s tests -t .` | 369, green — both doors agree |
| goldens vs `main` | byte-identical, via the comparison script with updated paths |
| `export_player` | `5 exported, 9 skipped (gm-only), 0 skipped (mixed, no separator), 15 GM section(s) stripped` |
| `deploy_export --render-only` | `7 link(s) refused`, exit 1 (pre-existing content condition); staged checksum `fce5923ec0a1f32d6f598482bb3b7d2c213f0b4a`, computed path-independently: `(cd <dir> && find . -type f \| sort \| xargs shasum) \| shasum` |
| `review checkup` | 0 errors, 0 warnings |
| `python3 tests/check_portability.py` | exit 0 |
| manual greps on the portable file | zero hits for the goldens, the ten cultures, `run_cli(`, `INV`, `REPO`, the campaign name — the guard's predicate run once by hand, verifying the guard against an independent source |
| guard watched failing | one planted token per category → red → removed → green |

## Spec bookkeeping

The parent spec's Plan 6 section gets its status flip and the re-derived
numbers (26 + 7 + 49 measured 2026-07-31; final 55/28); carry-forward item 4
closes.

## Non-goals, recorded so Phase 4 inherits them as notes, not surprises

1. The other 13 test files stay unclassified. `test_retry_budgets.py` and
   `test_run_tests.py` are portable by construction but carry no formal
   ruling.
2. `test_samples.py`'s released NAME_ATTEMPTS test stays where it is —
   released ≠ relocated.
3. The incidentally-coupled movers (the ambiguity pair, the
   workspace-agnostic `run_cli` flag tests) *could* be portable-ized with
   synthetic fixtures. Phase 4 decides whether the shipped engine suite
   needs CLI-flag and ambiguity coverage; until then the campaign file
   carries it.
4. The guard polices one file. If Phase 4 wants a directory-shaped boundary,
   the moved files are already classified and the relocation is mechanical.
5. The split cost the portable file its only guard on `GIVEN_JOIN_ATTEMPTS`.
   Before the split, a cut budget was caught inside
   `test_generate_names.py` itself; after it, the sole test that still
   catches a cut `GIVEN_JOIN_ATTEMPTS` is
   `TestSeededOutputIsStable.test_gender_bias_is_stable_under_seed`, which
   moved to `tests/test_campaign_names.py` — the campaign-coupled half that
   stays behind at Phase 4. Measured 2026-07-31, final review: setting
   `GIVEN_JOIN_ATTEMPTS = 1` leaves all 55 portable tests green and produces
   exactly one coupled failure, `test_gender_bias_is_stable_under_seed`
   (one of the campaign's cultures). So the engine suite as packaged at
   Phase 4 ships blind to that budget; Phase 4 must re-home or re-create a
   portable guard for it (see `tests/test_retry_budgets.py`, which already
   guards `NAME_ATTEMPTS` for the same reason and records this gap for
   `GIVEN_JOIN_ATTEMPTS` in its module docstring).
6. **Same shape as item 5, but closed rather than deferred.** Final review
   also found that `synthetic_inventory`'s `official_culture` parameter
   (added for the rewrites) had no caller passing it, leaving the
   `if official_culture is not None` branch dead — and with it,
   `official_name()`'s non-`None` path unexercised anywhere in the portable
   file. Measured the same way as item 5: gutting `official_name()` to
   always return `None` left all 55 portable tests green; the only things
   that noticed were the campaign-coupled
   `test_place_names_are_stable_under_seed` and `tests/check_portability.py`
   (a separate gate script `test*.py` discovery does not collect). Unlike
   item 5, this did not wait
   for Phase 4: a follow-up in this PR added one test exercising the branch,
   discriminating it from a broken implementation by asserting the exact
   place name `synthetic_inventory`'s `wold` culture is bound to produce
   (its `place`/`place_tail` pools each hold one entry, so the result is
   seed-invariant) rather than merely `assertIsNotNone`.

## Success criteria

1. Suite green on both doors at every commit; 368 after commit 1, 369 after
   commit 2, never below.
2. The three goldens byte-identical to `main` — by the comparison script,
   not by the live tests alone. Regenerating a constant is prohibited.
3. Export gate exact and checksum unchanged; checkup 0/0;
   `check_portability.py` exit 0.
4. The portable file greps clean (goldens, cultures, `run_cli(`, `INV`,
   `REPO`, the campaign name), and the guard test enforces exactly that
   predicate — watched failing before it is trusted.
5. Commit 2 changes no moved test's body — the guard is its only new code
   (`--color-moved` review).
6. Every rewritten test's mutation watched red then green.
