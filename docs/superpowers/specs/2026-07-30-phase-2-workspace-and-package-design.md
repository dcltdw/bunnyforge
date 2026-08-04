# Phase 2 — Workspace Resolution and Package Layout: Design

> **Provenance:** a scrubbed copy of a development record from the
> private campaign repository where this tool was first built. Campaign
> identifiers are neutralised throughout; the verbatim original stays in
> that private repo. Staged for publication 2026-08-02.

**Parent:** `2026-07-28-tool-campaign-split-design.md`, section "Phase 2 — workspace
resolution and package layout". This document turns that section into a buildable
design. Where the two disagree, this one governs; every deviation is listed in
"Deviations from the parent spec" below.

**Goal:** the tool code becomes an installable package (`ttrpgkit`) that finds its
campaign workspace by resolution — flag, environment, or marker walk — instead of
by its own file location, with nothing loading at import time.

**State when written:** `main` at PR #48 (sample settings). 288 tests, checkup
clean, `check_portability.py` exit 0. Phases 1, 1b, and 1c are done.

## Decisions taken with the user (2026-07-30)

| decision | choice |
|---|---|
| Decomposition | **Six plans, six PRs** — the parent's single-plan shape rejected for the same reason Phase 1c became four |
| Package name | **`ttrpgkit`** — a working name; Phase 4 may rename it (parent records that rename as mechanical) |
| Layout and invocation | `src/ttrpgkit/` + `pyproject.toml`, installed editable; tools run as `python3 -m ttrpgkit.<tool>`; **no unified CLI dispatcher** — that is Phase 3's work, when `init` needs it |
| `setup_campaign.py` | **Deleted in Plan 1**, pulling Phase 3's deletion forward. 2,204 lines, zero tests, the only file with campaign-name references (11), and its embedded payload describes a layout this phase destroys. Acceptable because the workspace is already scaffolded; no scaffolder exists again until Phase 3 ships `init`. Issue #29 should be closed as superseded when Plan 1 merges |
| Binding mechanism | **Thread a `Workspace` object** — no module globals. Chosen over deferred `bind()` and accessor functions, accepting the largest diff for the cleanest end state |
| Campaign-coupled test split | **Plan 6** of this phase (carry-forward item 4) |

## Measured ground truth

Everything below was measured on 2026-07-30, not carried forward from prose.
Counts drift; re-derive any number before building on it.

- **8** `WORKSPACE = Path(__file__).resolve().parent.parent` sites — every module
  with a `main()` plus `_config.py`.
- **7** `sys.path.insert` hacks in `scripts/`, **10** in `tests/` (including
  `check_portability.py:26`).
- **No packaging exists.** No `pyproject.toml`, `setup.py`, or `setup.cfg`.
- **Editable installs work in this environment** — probed, not assumed:
  python.org framework Python 3.13.2, pip 25.3, no PEP 668 `EXTERNALLY-MANAGED`
  marker; `pip install -e . --dry-run` on a `src/`-layout probe package succeeded.
- **Import-time bindings, eleven across four modules:** `_config.py`'s
  `CONFIG = load(WORKSPACE)`; `_common.py`'s five re-exports (`ENTITY_DIRS`,
  `INHERIT_DIRS`, `COMPENDIUM_DIRS`, `ROOT_DOCS`, `_EXCLUDE_DIRS`);
  `deploy_export.py`'s `BASE_NAMESPACE`; and the generator's four
  (`SETTING_SPELLING` at line 301, `CULTURES` at 373, `SPELLING` at 385,
  `OFFICIAL_CULTURE` at 553 — note these interleave with function definitions,
  so the generator's module body *executes a load pipeline*, not just constants).
- **Read sites of those names: 46 in `scripts/`, 88 in `tests/`.**
  `check_portability.py` alone holds 42 — the global-swap harness.
- **Exactly one def-time default captures a binding:** `render_tree(...,
  base: str = BASE_NAMESPACE)` at `deploy_export.py:112`. Verified by AST walk
  over every function default in `scripts/`, because the signature spans two
  lines and grep misses it.
- **Module `__getattr__` was probed and rejected**, closing the tempting
  zero-call-site-change design: it does not fire for bare global reads inside
  the defining module (a `NameError`, measured), and `from mod import NAME`
  forces eager resolution at import (measured). Both defeat it here — 3 modules
  do `from _config import CONFIG` and the generator reads its own globals 26
  times.
- **The content walk is an allow-list**, not a deny-list: `iter_content_files`
  visits `ROOT_DOCS` + `ENTITY_DIRS` + `INHERIT_DIRS` only, with `exclude_dirs`
  filtering nested paths inside those. Proven by positive control: a stray
  `src/ttrpgkit/probe.md` with an invalid `visibility:` left the checkup at
  0/0. **`src/` therefore needs no `exclude_dirs` entry.**
- **The copy-and-go tests derive the workspace from the script's file
  location.** `test_samples.py:275` runs `tmp/scripts/generate_names.py` — a
  *copy* of the script placed inside the temp workspace, so `parent.parent`
  resolves to `tmp`. The package move deletes this mechanism (a module has one
  canonical location), which is why a replacement resolution layer must exist
  in Plan 1, not Plan 2.
- **Campaign-coupled tests: 22 of 76** in `test_generate_names.py` (29%; the
  parent predicted "near a third"). Classification: 4 golden-constant tests,
  13 `run_cli` tests coupled only because the CLI reads the real inventory,
  5 tests reaching into named cultures (`CULTURES` lookups by culture key).
  Re-derive at Plan 6; the rule is: coupled if it touches a golden constant,
  a named culture, or a `run_cli` call against the real inventory.
  **Re-derived** (26 coupled / 7 gray / 49 portable of 82) — see the Plan 6
  section below
  and the Plan 6 design spec (2026-07-31) for the landed numbers; this
  bullet's 22-of-76 is the pre-Plan-6 measurement, kept as history rather
  than corrected in place.

## The design

### Workspace resolution

A new module, `ttrpgkit/_workspace.py`:

```python
class WorkspaceError(Exception):
    """No campaign workspace could be resolved. Message is user-facing."""

class Workspace(NamedTuple):
    root: Path          # directory containing campaign.toml
    config: Config      # the loaded campaign.toml

def discover(start: Path | None = None) -> Path:
    """Walk from `start` (default cwd) upward to the filesystem root; return
    the first directory containing campaign.toml. Raises WorkspaceError."""

def open_workspace(root: Path | str | None = None) -> Workspace:
    """Resolve and load. `root=None` applies the resolution order below;
    an explicit root is used as given (no walk). ConfigError from load()
    propagates — callers catch both it and WorkspaceError in main()."""
```

**The marker is `campaign.toml` itself.** No new marker file: it is already the
one file that defines "this is a campaign workspace," and `_config.CONFIG_NAME`
already names it.

**Resolution order** (first hit wins), the same shape git uses:

1. `--workspace PATH` — explicit flag, used as given, error if no
   `campaign.toml` there.
2. `TTRPGKIT_WORKSPACE` — environment variable, same semantics as the flag.
   This layer is not scaffolding: it exists so subprocess tests (copy-and-go,
   and anything else that launches a tool against a temp workspace) can point
   the tool without argv surgery, and it arrives in **Plan 1** because the
   package move strips the script-location mechanism those tests rely on
   today.
3. Marker walk from cwd.
4. Nothing found — a single `error:` line on stderr and exit 1.

Failure of the first three produces the parent spec's required behaviour: *a
clear "not inside a campaign workspace" message on stderr, exit 1, no
traceback* — achieved structurally, because resolution happens inside `main()`
where it can be caught, not at import where it cannot.

**As shipped (Plan 5).** The order above is now the whole of it: flag, then
environment, then walk, then a clean error. The transitional fourth step that
existed between Plans 1 and 5 — falling back to the repository the package was
installed from, first as a file-derived `WORKSPACE` default (Plan 1) and then
as `_workspace.INSTALL_ROOT` (Plans 2–4) — is deleted, so a tool run outside
any workspace can no longer silently operate on the install repo's campaign.
Two naming deviations from the sketch above, both settled during
implementation: the walk is `_workspace.resolve_root()`, not `discover()`, and
`Workspace` lives in `_config.py` rather than `_workspace.py`, because loading
the config is `_config`'s job and `_workspace` imports nothing from the
package — which is what keeps the two free of an import cycle. `run_tests` is
the one entry point without the flag: it resolves by environment or walk only
(a test runner invoked from outside its own workspace has no use case worth a
flag).

### Threading

Every function that today reads a config global takes what it needs as a
parameter — usually the `Workspace`, sometimes just a field. `main()` in each
entry point becomes:

```python
def main() -> int:
    args = parse_args()
    try:
        ws = open_workspace(getattr(args, "workspace", None))
    except (WorkspaceError, ConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    ...
```

**The generator gets an `Inventory`** bundling what its four globals hold now:

```python
class Inventory(NamedTuple):
    cultures: dict[str, dict]        # today's CULTURES
    spelling: dict[str, Spelling]    # today's SPELLING (per-culture, resolved)
    setting_spelling: Spelling       # today's SETTING_SPELLING
    official_culture: str | None     # today's OFFICIAL_CULTURE

def load_inventory(ws: Workspace) -> Inventory: ...
```

`person_name` / `place_name` / `official_name` take an `Inventory` instead of
reading module state. `given_name` is already pure and does not change.
Exact signatures are plan-level detail; the constraint that is design-level:
**threading changes how data reaches a function, never what is loaded, in what
order, or when the RNG is consulted.** `load_cultures`' sorted-glob order is
load-bearing (RNG bit consumption depends on pool sizes and iteration order)
and must be preserved exactly.

**Strangler discipline across plans.** The module-level bindings cannot all die
at once — 46 script-side read sites span five modules landing in different
plans. So: the bindings survive as-is while their consumers migrate; each plan
deletes the bindings its modules owned once nothing reads them; Plan 5 deletes
the last (`_config.CONFIG` and the `_common` re-exports, which everything
consumes). Until Plan 5, importing a tool module inside a directory that is
not a workspace still raises — the transitional window keeps today's defect,
it does not widen it. The suite stays green at every plan boundary.

### What this dissolves

- **Carry-forward 2** (import-time tracebacks, both loaders): nothing loads at
  import, so neither failure site exists. Not fixed — removed.
- **Carry-forward 3** (lazy binding so `--workspace` can work): threading is
  the strong form of that requirement.
- **`render_tree`'s def-time default**: the `base` parameter loses its default
  and is passed explicitly; the only def-time capture in the codebase dies.
- **`check_portability.py`'s global swap and subprocess wrapper**: with no
  globals, "install setting X" becomes "construct `Inventory` X" — the 42 swap
  sites become constructor arguments, and `test_portability.py`'s subprocess
  isolation (which exists solely so a failed global restore cannot corrupt the
  goldens) has nothing left to protect against. Plan 4 retires it.

## The six plans

Suite floor: each plan ends at or above the count the previous one ended on,
starting from 288.

### Plan 1 — the package move — **shipped, PR #51**

`scripts/*.py` → `src/ttrpgkit/` via `git mv` — 10 modules move; the 11th,
`setup_campaign.py`, is deleted instead, closing success criterion 4 on day
one. New
`pyproject.toml` (`requires-python = ">=3.11"` for tomllib, stdlib-only, no
dependencies), editable install, `[project.scripts]` **empty** — module
invocation only. All 7 script-side `sys.path` hacks deleted; intra-package
imports become `from ttrpgkit import ...`; all 10 test-side `sys.path` hacks
deleted and test imports rewritten. CI gains `pip install -e .` and invokes
`python3 -m ttrpgkit.run_tests -v`. `scripts/README.md` moves to
`src/ttrpgkit/README.md` with invocations updated; live-document references to
`python3 scripts/<x>.py` are updated (`docs/superpowers/` history is not).

Two knowingly-temporary seams, both dying in Plan 2:

- The 8 `WORKSPACE` constants become
  `Path(os.environ.get("TTRPGKIT_WORKSPACE", <file-derived default>))` where
  the file-derived default gains one `.parent` (the tree is one level deeper).
- Subprocess tests (`test_samples.py`, and `check_portability.py`'s reproduce
  command) switch from copying scripts to
  `[sys.executable, "-m", "ttrpgkit.generate_names", ...]` with
  `TTRPGKIT_WORKSPACE` in the environment.

Done when: suite ≥ 288 green, checkup 0/0, portability exit 0,
`grep -rn "sys.path.insert"` over `src/` and `tests/` returns nothing,
the campaign-name grep over `src/` returns nothing, and the tools run from an
arbitrary cwd via `python3 -m ttrpgkit.<tool>`.

### Plan 2 — the Workspace object — **shipped, PR #54**

`_workspace.py` lands: `Workspace`, `WorkspaceError`, `discover()`,
`open_workspace()`, with **the first tests of workspace derivation this repo
has ever had** (the parent's risk list calls this the untested one-line
constant). Resolution order implemented in full minus the flag (env → walk).
Adopted by the two lowest-level modules only: `_config.py` (whose
`WORKSPACE`/`CONFIG` globals survive as shims for downstream consumers) and
`_common.py` (`iter_content_files` already takes a workspace argument; its
re-exports survive as shims). The 8 file-derived `WORKSPACE` defaults die;
every entry point resolves via `open_workspace()` at `main()` — though most
still read shimmed globals for everything else.

### Plan 3 — thread the export pipeline — **shipped, PR #56**

`export_player.py`, `deploy_export.py`, `_dokuwiki.py`. `render_tree` loses
its `BASE_NAMESPACE` default; `BASE_NAMESPACE` and the export pipeline's use
of the `_common` re-exports die. Gate: success criterion 3 — `export_player`
and `deploy_export --render-only` produce **byte-identical output** to their
pre-plan runs (same 5 exported / 9 skipped, same seven link refusals),
verified by capturing both trees before and after.

### Plan 4 — thread the generator, rebuild the portability check — **shipped, PR #58**

The highest-risk plan, deliberately isolated. `generate_names.py`'s module-body
load pipeline (lines 301–553) becomes `load_inventory(ws)`; `main()` builds the
`Inventory` once; the four globals die. `check_portability.py` is rebuilt on
`Inventory` construction — no global swap, no `installed()` context manager —
and `test_portability.py`'s subprocess wrapper is retired for a direct import.

Two positive controls are mandatory, both already proven to discriminate:

- The three goldens byte-for-byte. Any golden that moves means the refactor
  changed generation; the plan stops rather than regenerates.
- The injected-regression experiment from PR #46 is **re-run against the
  rebuilt check**: inject the ambient-spelling leak into a scratch copy and
  confirm the rebuilt check catches it across the same 12 seeds, 12/12. A
  rebuild that passes on healthy code has proven nothing about its teeth.

### Plan 5 — the remaining modules and `--workspace` — **shipped, PR #60**

`review.py`, `build_sheets.py`, `import_perceptions.py`, `run_tests.py`
threaded; the last shims (`_config.CONFIG`, the `_common` re-exports) die;
`--workspace PATH` lands on all six user-facing entry points, completing the
resolution order (`run_tests.py` resolves via env/walk only — a test runner
run from outside its workspace has no use case worth a flag). Includes the two remaining carry-forwards:

- **Item 1:** `build_sheets.py` and `import_perceptions.py` stop binding the
  five directory-name literals and read `ws.config` like everyone else.
- **Item 5:** the retry budgets (`range(10)`, `range(50)`) become named module
  constants in one place, and the `given_syllables` default (`min=1, max=2`),
  hardcoded in two places, collapses to constants both sites read. The naming
  shipped; the second half — exhausting a budget **raising** (naming the
  culture and budget) instead of silently returning a short result — is
  **deferred**, for the reason recorded under the carry-forward table. The
  recorded hazard ("a constant tuned for the campaign silently overrides
  another setting's configuration") is therefore documented at the constants
  rather than converted into a loud failure.

Positive control for the flag: at least one test runs a tool via `--workspace`
pointed at a copied sample and asserts sample-derived output — a flag no test
exercises is the defect shape this project has hit seven times.

### Plan 6 — split the campaign-coupled tests — **done**

`tests/test_generate_names.py` splits: portable tests (54 at last measure)
keep the filename and ship with the engine at Phase 4; coupled tests (22 —
the goldens, the real-inventory `run_cli` tests, the named-culture tests) move
to `tests/test_campaign_names.py`, which stays with the campaign. Re-derive the
classification; do not trust this paragraph's numbers. Done when the portable
file contains no golden constant, no named culture, and no `run_cli` against
the real inventory (each grep-able), and the total count is unchanged — a
split that loses a test has deleted coverage.

Landed 2026-07-31: re-derived 26 coupled / 7 gray (INV-reading) / 49 portable
of 82; six gray tests rewrote onto synthetic fixtures, one recoupled; 27
tests moved to tests/test_campaign_names.py; TestPortableBoundary greps the
portable file continuously. Suite 368 -> 369. See the Plan 6 design spec
(2026-07-31) for the decisions.

Follow-up, same PR, after final review: closing an `official_name()`
coverage gap the review found added one more portable test. Suite 369 ->
**370**. See the Plan 6 design spec's own follow-up note.

## Carry-forward mapping

| parent item | fate |
|---|---|
| 1 — de-campaign `build_sheets`/`import_perceptions` literals | **closed, Plan 5** — the five literals became the `briefs_dir`, `sheets_dir`, `perceptions_dir` and `type_dirs` config keys, each defaulting to today's value; both modules read `ws.config` |
| 2 — import-time tracebacks in both loaders | **closed, Plan 5** — nothing loads at import in either loader; the last shim (`_config.CONFIG`) died with the rest of the import-time layer. Not fixed, removed: neither failure site exists |
| 3 — lazy binding so `--workspace` can work | **superseded by threading** (Plans 3–5) — every tool takes a `Workspace` parameter, which is the strong form of the requirement; no binding, lazy or otherwise, remains to defer |
| 4 — campaign-coupled generator tests | **closed, Plan 6** — the split landed with a boundary guard; see the Plan 6 design spec |
| 5 — untunable retry/syllable constants | **partially closed, Plan 5** — the constants landed (`GIVEN_JOIN_ATTEMPTS`, `NAME_ATTEMPTS`, `GIVEN_SYLLABLES_MIN_DEFAULT`, `GIVEN_SYLLABLES_MAX_DEFAULT`, each read by every site that used to hold a literal). **The raise on exhaustion is deferred**, see below |

**Why item 5's raise is deferred.** Making an exhausted budget raise instead of
falling back would break `check_portability.py`'s property-one converse.
That converse reconstructs `person_name`'s deterministic fallback string at
`check_portability.py:632` and then asserts that *not every* generated name
equals it — a guard against a contaminated comparison, and one that is only
meaningful while the fallback is a reachable outcome. If exhaustion raised,
the fallback string would no longer exist to reconstruct and the guard would
have to be redesigned around whatever replaced it. That is a rework of the
repo's most delicate harness for no behaviour the plan needed, so the budgets
are named here and the failure mode is left as-is, documented at their
definition in `generate_names.py`. Reopen with the converse redesign in scope.

## Success criteria

1. Suite green at every commit, never below the previous plan's count,
   starting from 288; the count asserted explicitly.
2. `review checkup`: 0 errors, 0 warnings throughout.
3. Export byte-identical after Plan 3 and again at phase end (5/9, seven
   refusals).
4. The three goldens byte-for-byte at every plan boundary. Regenerating them
   is prohibited; a moved golden stops the plan.
5. The campaign-name grep over `src/` returns nothing from Plan 1 onward.
6. `grep -rn "sys.path.insert"` over `src/` and `tests/` returns nothing from
   Plan 1 onward. (Not repo-wide: historical plans under `docs/superpowers/`
   quote the hack in code samples and are not rewritten.)
7. After Plan 5: every tool runs from any directory; a directory that is not
   a workspace produces the clean message and exit 1, no traceback (asserted
   by test); `--workspace` against a copied sample is exercised by test.
8. After Plan 6: the portable/coupled split holds by grep, total test count
   unchanged by the split.

## Risks and trade-offs

- **The editable install is per-machine and the repo lives in Dropbox.** The
  install writes to the machine's `site-packages`; syncing the repo does not
  carry it. Every machine (and every fresh CI job) needs `pip install -e .`
  once. Mitigation: CI does it explicitly; the README states it; a tool run
  without the install fails at import with `ModuleNotFoundError: ttrpgkit`,
  which is at least unambiguous.
- **The strangler window (Plans 2–4)** keeps import-time loading alive in
  not-yet-threaded modules. Accepted: the window preserves today's behaviour
  rather than adding risk, and each plan's boundary is green.
- **Plan 4 touches the most delicate harness in the repo.** Mitigated by
  isolation (nothing else in that plan) and the two mandatory positive
  controls above.
- **`__pycache__` under `src/`** — ensure `.gitignore` covers the new tree
  before the first Plan 1 commit.

## Deviations from the parent spec

- **Six plans, not one.** User decision, recorded above.
- **`setup_campaign.py` dies in Phase 2, not Phase 3.** User decision; Phase
  3's remaining scope is building `init`, not deleting its predecessor.
- **The runner is `python3 -m ttrpgkit.run_tests`**, not the parent's literal
  `python3 src/<pkg>/run_tests.py` — the module form is what a package
  supports; the parent's phrasing predates the invocation decision.
- **An environment variable joins the resolution order.** The parent named
  only the flag and the walk. `TTRPGKIT_WORKSPACE` is added, arriving in
  Plan 1, for the reasons given under "Workspace resolution".

## Out of scope

- A unified `ttrpgkit` CLI dispatcher (Phase 3, with `init`).
- Renaming the package (Phase 4).
- Phases 4–5 remain deferred and unauthorised.
- A `ttrpgkit.testing` fixtures module (parent: revisit after the first real
  campaign test exists).
- Migrating `_Ignore/`.
