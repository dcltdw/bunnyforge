# Phase 3 — `ttrpgkit init`: Design

> **Provenance:** a scrubbed copy of a development record from the
> private campaign repository where this tool was first built. Campaign
> identifiers are neutralised throughout; the verbatim original stays in
> that private repo. Staged for publication 2026-08-02.

**Parent:** `2026-07-28-tool-campaign-split-design.md`, section "Phase 3 — `init`".
This document turns that section into a buildable design. Where the two disagree,
this one governs; every deviation is listed in "Deviations from the parent spec"
below.

**Goal:** `python3 -m ttrpgkit.init` scaffolds a complete campaign workspace —
one that passes `review checkup` with 0 errors, 0 warnings and runs the name
generator, with no manual fixes — from real data files the package carries,
guarded against drift by test rather than by discipline.

**State when written:** `main` at 19d03f5. Phase 2 complete (all six plans,
PRs #51–#60 plus Plan 6). 373 tests green on both doors
(`python3 -m ttrpgkit.run_tests` and `python3 -m unittest discover -s tests -t .`),
checkup 0/0, `tests/check_portability.py` exit 0. No open PRs.

## The stale premise, corrected

The parent's Phase 3 entry says "Delete `setup_campaign.py`; build `<pkg> init`",
and its headline table compares against a 2,293-line "Today" that no longer
exists. **`setup_campaign.py` was deleted in Phase 2 Plan 1 (#51)** — a user
decision recorded in the Phase 2 spec's decisions table and its "Deviations from
the parent spec" section. The parent was never annotated to point there; this
document is now that pointer. Phase 3's remaining scope is therefore *only*
building `init`: roughly 150 lines of code, a `data/` tree of real files, and
the init-then-checkup regression test the parent demands.

The gap is real and open: since #51 merged there has been **no way to create a
second campaign workspace**. `samples/` is not a substitute — the samples are
culture-data teaching ladders (each a `cultures/` directory plus a
`campaign-additions.toml` fragment, no `campaign.toml`); even
`tests/test_workspace.py`'s copied-sample test builds the rest of its workspace
by hand.

## Decisions taken with the user (2026-07-31)

| decision | choice |
|---|---|
| Dispatcher | **init only** — ships as `python3 -m ttrpgkit.init`, matching all seven existing tools. The unified `ttrpgkit` console-script dispatcher (which Phase 2's out-of-scope list had penciled into Phase 3) is deferred until init has actually been used; `[project.scripts]` stays empty |
| Scaffold size | **Full workspace** — everything checkup and the tools expect on day one, not a minimal skeleton the author must repair before the gate passes |
| Drift guard | **Byte-equality drift test** — `data/` holds real copies of the generic files, and a test asserts each is byte-identical to its canonical in-repo source. Chosen over "no guard" (the defect that killed `setup_campaign.py`) and over making the workspace consume `data/` (workspace files as build outputs is wrong for a Dropbox-synced tree agents edit directly) |
| UX | **Flags, non-interactive** — argparse like every other tool; the doctrine skeletons already do the interviewing-the-author job via their embedded prompts (parent's governing principle) |
| Generated `campaign.toml` | **Minimal + commented defaults** — only the keys that must be set are live; every defaultable key appears as a comment showing its default, so the file cannot drift from `_config._DEFAULTS` |

## Measured ground truth

Measured 2026-07-31; re-derive before building on any of it.

- `_Templates/` holds 16 files: 12 entity/brief `.md` templates, `npc.html`,
  `README.md`, and the two doctrine skeletons
  (`style-guide.skeleton.md`, `situation-design.skeleton.md`).
- Campaign-term hits in candidate generic files (pattern: the then-checked
  subset of what is now the derived list): `AGENTS.md` **0**
  (2,332 words — already neutral), `front-burner.md` 0, `situation-design.md` 0,
  `_Templates/npc.md` 0, the sampled per-directory READMEs 0 (3 lines each);
  `style-guide.md` **19**, `compendium.md` **2**. So AGENTS.md and the templates
  ship verbatim; style-guide ships only as skeleton; compendium ships as stub.
- `_config._DEFAULTS` supplies `entity_dirs` (8), `inherit_dirs` (2),
  `compendium_dirs`, `root_docs` (8 files), `exclude_dirs`, `briefs_dir`,
  `sheets_dir`, `perceptions_dir`, `type_dirs`. Only `campaign.namespace` is
  strictly required (`ConfigError` names it); `[names].cultures` is required by
  the generator specifically. No `campaign.toml.in` exists yet.
- Every entity/inherit directory in the campaign repo carries a 3-line
  campaign-neutral `README.md`.
- `reanchor.txt` exists in the campaign repo but is **not** in the default
  `root_docs`.
- `compendium.md` is an index that `review.py` checks (`review.py:230`).

## The design

### Command and behaviour

```
python3 -m ttrpgkit.init PATH --name "My Campaign" [--namespace mycampaign]
```

- `--name` is required. `--namespace` defaults to a slug of the name
  (lowercased, non-alphanumerics stripped); whichever way it arrives it must be
  non-empty after slugging, else a clean error.
- `PATH` must not exist, or must be an empty directory. Anything else — a file,
  a non-empty directory, and in particular an existing `campaign.toml` — is one
  `error:` line on stderr and exit 1. No overwrite semantics, no `--force`.
- **init does not resolve a workspace.** It is the one tool with no
  `--workspace` flag, no `TTRPGKIT_WORKSPACE` lookup, and no marker walk — it
  creates the marker the others walk to. An ancestor workspace does not block
  init: the marker walk always finds the nearest `campaign.toml`, so nesting is
  harmless and refusing it would be policy without a defect.
- Errors follow the house pattern established in Phase 2: caught in `main()`,
  one `error:` line, exit 1, never a traceback.

### What init writes

Full workspace, in one pass over a manifest (below):

1. **`campaign.toml`** — rendered from `data/campaign.toml.in` by plain
   placeholder substitution (no TOML writer, per the parent). Live keys:
   `[campaign] name`, `[campaign] namespace`,
   `[names] cultures = "names/cultures"`. Every defaultable key from
   `_DEFAULTS` appears **as a comment** showing its default value, so the file
   teaches what is overridable without being a second copy of `_DEFAULTS` that
   can drift — comments are not parsed.
2. **Root docs** — all 8 from the default `root_docs`:
   - `AGENTS.md`: the packaged copy, verbatim (it is already neutral).
   - `style-guide.md`, `situation-design.md`: the two skeletons written to
     their **canonical names** — the `.skeleton` suffix exists only inside
     `data/` and `_Templates/`, exactly as the parent specifies.
   - `compendium.md`, `front-burner.md`, `open-questions.md`,
     `out-of-game.md`, `tickets.md`: generic stubs authored for `data/root/`.
     The compendium stub must satisfy `review.py`'s index check on an empty
     workspace — the init-then-checkup gate enforces this.
3. **Directories** — the 8 `entity_dirs` and 2 `inherit_dirs`, each with its
   3-line README (packaged copies of the campaign's, which are already
   neutral).
4. **`_Templates/`** — the full 16-file set, verbatim, including both
   skeletons under their `.skeleton` names.
5. **`names/cultures/vashkand.toml`** — the starting setting the parent already
   decided: sample 1's single culture, `species` left empty, `draws_on` naming
   a real historical tradition, no species-to-tradition mapping asserted. A
   user who wants none deletes the file and the generator reports that no
   cultures are configured.
6. **`.gitignore`** — minimal: `Sheets/`, `Reviews/`, `_Ignore/`,
   `__pycache__/`. init does **not** run `git init`; version control is the
   author's move.

Not written: `reanchor.txt` (campaign state, not a root doc) — unless plan-time
verification finds the packaged AGENTS.md's read order requires it to exist, in
which case an empty one is written and the manifest records why. The
init-then-checkup gate is the arbiter.

### `data/` layout and the manifest

```
src/ttrpgkit/data/
  campaign.toml.in
  doctrine/AGENTS.md
  root/compendium.md  front-burner.md  open-questions.md  out-of-game.md  tickets.md
  templates/           # all 16 _Templates/ files, byte-identical
  dir-readmes/         # the 10 per-directory READMEs
  cultures/vashkand.toml
```

Files are read via `importlib.resources` (the package owns them wherever it is
installed). A single module-level **manifest** in `init.py` maps each packaged
file to its destination path and marks which are verbatim copies of an in-repo
canonical source. init iterates the manifest to write; the drift test iterates
the *same* manifest to verify — adding a file to one automatically covers it in
the other. No enumeration lives in two places.

### The drift guard

`setup_campaign.py` died because it embedded copies of doctrine that drifted
silently from the real files. `data/` is copies again; the difference is that
drift is now a **red test**:

- `data/templates/*` ↔ `_Templates/*` — byte-identical, all 16.
- `data/doctrine/AGENTS.md` ↔ `AGENTS.md` — byte-identical.
- `data/dir-readmes/*` ↔ each live directory README — byte-identical.
- `data/cultures/vashkand.toml` ↔ sample 1's culture file — byte-identical.

Legitimately different, so no guard: the campaign's filled-in
`style-guide.md` and `situation-design.md` versus the skeletons (skeleton vs
filled-in is the parent's governing principle, not drift); the campaign's
live state docs versus the `data/root/` stubs; `campaign.toml` versus
`campaign.toml.in`.

This test is only trivially possible while the package and the campaign share
one repository — the deliberate transitional state Phase 2 created. At Phase 4
the campaign-side copies stop being canonical for the package; the test ships
with the package reduced to what it can still see (manifest-internal
consistency and init output), and the campaign may keep its own copy pointed
the other way. That rework is Phase 4's, recorded here so it is not
rediscovered.

> **It was not rediscovered — it was designed.** See
> `2026-07-31-phase-4-public-cut-design.md`, "The drift guard splits in three". The guard
> becomes: (1) a package-side test that ships public — manifest completeness in both directions,
> init fidelity, and the `vashkand.toml` ↔ sample 1 pairing, which survives intact because both
> ends live in the public repo; (2) a campaign-side `test_campaign_drift.py` that compares
> the campaign's live copies against the **installed** package's `data/` via `importlib.resources`,
> with a per-file allowlist carrying a one-line reason — drift *awareness*, not enforcement;
> (3) this byte-equality test, unchanged, until the switchover actually happens. The canonical
> direction flips at the cut: `data/` inside the package becomes canonical, and the campaign's
> live copies become downstream.

### Testing

Suite floor **373**; checkup 0/0 and portability exit 0 throughout.

1. **init-then-checkup** — the headline regression test the parent demands
   (its Testing item 2, and success criterion 5): init into a temp directory,
   run `review checkup --workspace <tmp>`, assert **0 errors, 0 warnings**.
   The test `setup_campaign.py` never had, and the one that would have caught
   issue #29.
2. **init-then-generate** — `generate_names` against the fresh workspace
   produces a name from the starter culture, proving the `[names]` wiring
   end-to-end.
3. **Config round-trip** — the generated `campaign.toml` loads through
   `_config.load`; every defaultable key equals its `_DEFAULTS` value
   (the comments really are comments), and `name`/`namespace` carry the
   substituted values.
4. **Drift test** — the byte-equality guard above, driven by the manifest.
5. **Refusals and args** — missing `--name`; `PATH` a file; `PATH` a non-empty
   directory; `PATH` containing `campaign.toml`; namespace slugging
   (mixed-case, punctuation, and a name that slugs to empty → error).

### Relationship to open issues

- **#69** (`species`/`draws_on` lack load-time type validation) — adjacent,
  since init scaffolds a culture file, but not a blocker: the starter culture
  ships `species` empty and well-formed. Fixing #69 is generator work,
  independent of init.
- **#29** — already closed as superseded when #51 merged; nothing left here.

## Deviations from the parent spec

- **`setup_campaign.py` is not deleted here** — it was deleted in Phase 2
  Plan 1 (#51), by user decision recorded in the Phase 2 spec. The parent's
  Phase 3 entry and its "headline simplification" table predate that.
- **No dispatcher.** Phase 2's out-of-scope entry read "A unified ttrpgkit CLI
  dispatcher (Phase 3, with init)"; the user decided 2026-07-31 that Phase 3
  ships init only, as a module invocation. The dispatcher waits for evidence
  from actual use — the same reasoning the parent applies to Phases 4–5.
- **`campaign.toml.in` is minimal, not the parent's fully-explicit sketch.**
  The sketch predates `_config._DEFAULTS`; writing every key would be a second
  copy of the defaults that drifts. Defaultable keys appear as comments.
- **The culture ships to `names/cultures/`**, per the Phase 1c per-file layout,
  not the parent's original `names/cultures.toml` single file — the parent's
  own "superseded twice" annotation already requires reading that section as
  current-as-shipped.

## Out of scope

- The `ttrpgkit` console-script dispatcher and any `[project.scripts]` entry.
- Interactive prompts.
- Running `git init` in the new workspace.
- Issue #69's validation. **Now scheduled:** #69 is a Phase 4 cut blocker, fixed in that phase's
  stage 1 hygiene sweep before anything is published.
- ~~Phases 4–5 remain deferred and unauthorised.~~ **Phase 4 was authorised 2026-07-31** and is
  designed in `2026-07-31-phase-4-public-cut-design.md`; **Phase 5 no longer exists**, collapsed
  into it. Two of this document's deferrals are reversed there: the `[project.scripts]`
  dispatcher ships with the cut (a published CLI's invocation style is an interface commitment,
  cheapest to set before anyone depends on it), and `ttrpgkit` is renamed **`bunnyforge`** — so
  every `ttrpgkit` and `TTRPGKIT_WORKSPACE` in this document names the pre-rename tool.

## Success criteria

1. Suite green at every commit, never below 373, the count asserted explicitly.
2. `review checkup` on the campaign repo: 0 errors, 0 warnings throughout.
3. A fresh `init` workspace passes `review checkup` with **no manual fixes**
   (parent success criterion 5, now closable), and `generate_names` runs in it.
4. The campaign-name grep over `src/` stays empty — nothing campaign-flavoured
   moves into the package, including inside `data/` (parent success
   criterion 4; Phase 2 success criterion 5).
5. The drift test fails if any packaged generic file differs from its in-repo
   canonical source by one byte.
6. One plan, one PR, on a branch off current `main`.
