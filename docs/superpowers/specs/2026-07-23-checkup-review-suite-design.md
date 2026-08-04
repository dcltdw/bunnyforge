# Checkup — workspace review suite (design)

> **Provenance:** a scrubbed copy of a development record from the
> private campaign repository where this tool was first built. Campaign
> identifiers are neutralised throughout; the verbatim original stays in
> that private repo. Staged for publication 2026-08-02.

**Date:** 2026-07-23
**Status:** approved, pre-implementation

## Purpose

A named, on-demand "stop-and-check" review of the campaign workspace. The user
invokes it by name ("run the checkup") when convenient. It is extensible: a
suite of checks that grows over time.

Two layers under one name:

- **Mechanical layer** — a deterministic script that scans the files and
  reports its findings. No judgment.
- **Agent-judgment layer** — a markdown checklist the agent walks after the
  mechanical run, covering checks a script cannot make.

"Run the checkup" = run the script, report its findings, then walk the
judgment checklist and report those, as one combined summary.

This is distinct from `tests/` (which tests the scripts themselves) and from
`[[open-questions]]` / GitHub Issues (undecided questions / deferred work).

## Architecture (approach A: registry in one script)

```
scripts/review.py        the runner: CHECKS registry + SUITES map + output
scripts/_common.py       gains a content-file enumerator
checks/checkup.md        the agent-judgment checklist for the checkup suite
Reviews/                 output dir for --html reports (gitignored)
tests/test_review.py     one unit test per check over temp fixtures
```

`review.py`:

```python
CHECKS = {"visibility-audit": fn, "front-matter": fn, "wikilinks": fn,
          "compendium": fn, "reveal-when": fn}     # name -> check function
SUITES = {"checkup": ["visibility-audit", "front-matter", "wikilinks",
                      "compendium", "reveal-when"]} # suite name -> check names
```

Each check is a function taking the parsed workspace and returning a list of
`Finding(severity, check, file, message)`, where `severity` is
`error | warn | info`. Adding a check: write a function, register it in
`CHECKS`, add its name to a suite in `SUITES`.

**Future expansion (approach B), documented in a comment, not built now:** if
checks outgrow one file, migrate to a plugin directory `scripts/checks/*.py`
auto-discovered at load. The registry stays the interface; only its population
changes. B is deferred until the file is uncomfortably large.

### Content-file enumeration

A shared helper in `_common.py` yields `(path, front_matter, body, category)`
for content files. It walks the content directories and **excludes entirely**:
`_Ignore/`, `_Archive/`, `_ExtractInbound/` (and `_Done/`), `_Templates/`,
`Sheets/` (generated), `Reviews/` (generated), `scripts/`, `tests/`,
`docs/`, `.github/`, `.git/`, and every `README.md`.

Enumerated files fall into three categories, which the checks treat
differently:

- **entity** — `NPCs/`, `Factions/`, `Setting/`, `Mechanics/`, `PCs/`,
  `Ideas/`, `Sessions/`, `Handouts/`. Carry full entity front matter and are
  **required to carry `visibility`**.
- **inherit** — `Briefs/` (inherit visibility from their writeup) and
  `Perceptions/` (player-authored, `canon: perception`). Enumerated for
  wikilink scanning but **exempt from the `visibility` requirement** and from
  the visibility audit's listing.
- **root** — the root docs `compendium.md`, `front-burner.md`,
  `open-questions.md`, `out-of-game.md`, `style-guide.md`,
  `situation-design.md`, `tickets.md`, `AGENTS.md`. Workspace infrastructure;
  they do **not** carry entity front matter and are **exempt** from the
  front-matter and visibility checks. They remain valid `[[wikilink]]` targets.

## The five mechanical checks

1. **visibility-audit** *(info)* — lists every **entity**-category file with its
   resolved visibility as plain text, grouped by directory. Never fails; it
   shows. `mixed` files (handouts) are listed with a `(mixed)` tag — the
   GM-vs-player axis does not apply to them; they are governed by the publish
   separator/gate. `inherit`- and `root`-category files are not listed.

2. **front-matter** *(error / warn)* — per **entity**-category file:
   - `type`, `canon`, `visibility` present.
   - `canon` ∈ {canon, draft, speculative, perception}; else **error**.
   - `visibility` ∈ {gm-only, player-visible, mixed}; missing or invalid →
     **error** (otherwise it silently fail-safes to gm-only).
   - `summary` present and non-empty; else **warn**.
   - `inherit`- and `root`-category files are exempt from these requirements.

3. **wikilinks** *(warn)* — every `[[name]]` in a body resolves to: a content
   file stem, a root doc name, or an `aliases` entry (an alias index is built
   across all front matter first). Unresolved → **warn**. Links inside fenced
   code blocks and HTML comments are ignored. Inline code spans are stripped
   too, *except* a span containing nothing but a single wikilink (e.g.
   `` `[[table-rules]]` ``) — this workspace's convention for writing
   wikilinks, per `AGENTS.md` — which is unwrapped first so the link inside it
   is still checked; multi-link or prose-bearing spans are stripped as
   ordinary code.

   *Amended 2026-07-25: corrected to describe the shipped behavior. The
   original wording ("links inside code spans ... are ignored") would have
   ignored every wikilink written in this workspace's own backtick
   convention, leaving only 16 of the workspace's 99 wikilinks checked and
   making the check nearly inert. `scripts/review.py`'s `extract_wikilinks`
   deliberately unwraps single-wikilink code spans before stripping the rest
   (see `_WIKILINK_CODE_SPAN_RE` and the `raw.count("[[") == 1` guard), so 91
   of 99 are checked; the remaining 8 are inside HTML comments.*

4. **compendium** *(warn)* — every entity file in `NPCs/`, `Factions/`,
   `Setting/`, `Mechanics/`, `PCs/`, `Ideas/` appears as a `[[stem]]` link in
   `compendium.md`. Missing → **warn**. Sessions, Briefs, Handouts, and
   Perceptions are exempt (not individually indexed).

5. **reveal-when** *(warn)* — `reveal_when` appears only on `gm-only` files
   (meaningless on player-visible/mixed). Misplaced → **warn**. Validating that
   the named event *exists* is out of scope for v1 (events are not enumerated
   anywhere yet); noted as a future tightening.

## Output

Plain text — no colour. Visibility-based colouring is a separate, all-docs
concern deferred to a future feature (see Out of scope).

### Terminal

Each check prints a titled block. `visibility-audit` lists files grouped by
directory with their visibility as plain text (e.g.
`riverbend.md   player-visible`). The other four print findings as `! warn` /
`✗ error` lines with the file path. Footer: counts per severity. Exit code is
non-zero if any `error`-level finding (so the suite is CI-able later, though it
is on-demand now).

### HTML (`--html`)

Writes `Reviews/checkup.html`, styled like the generated sheets: a findings
table at the top (severity, check, file, message), then the visibility audit as
a table (file, audience). `Reviews/` is gitignored.

## Agent-judgment layer

`checks/checkup.md` — a markdown checklist the agent walks after reporting the
mechanical results. Seeded with two judgment checks a script cannot make:

- **front-burner consistency** — does each claim in `front-burner.md` still
  match the entity files that own it?
- **speculative leak** — does any `canon: canon` / `canon: draft` file cite
  `speculative` or `Ideas/` material as though settled?

Extensible: add a bullet to grow the checklist. The file opens with a one-line
note that it is walked as part of `checkup` and is not itself canon.

## Testing

`tests/test_review.py` — one unit test per check, each over a temporary fixture
workspace containing one file that should flag and one that should pass. Also a
test that the content-file enumerator honors the exclude list. These are picked
up automatically by the existing `python3 -m unittest discover -s tests` CI
job, so the checkup checks are themselves gated by CI.

## Out of scope for v1

- Section-level visibility / a player-facing export (tracked: GitHub issue #1).
- Validating that a `reveal_when` event name refers to a real event.
- Additional suites (pre-session, pre-publish). The framework supports them via
  `SUITES`; only `checkup` is defined now.
- Auto-running the checkup on a schedule or as a required CI gate; it is
  on-demand by design.
- **Visibility-based colour rendering across all `.md` docs** (reverse video:
  gm-only vs player-visible) when a doc is viewed/rendered — a separate
  editor/rendering concern, not the review script. Tracked: GitHub issue #5.

## Invocation summary

```
python3 scripts/review.py checkup           # mechanical, terminal (plain text)
python3 scripts/review.py checkup --html    # also writes Reviews/checkup.html
```
"Run the checkup" → the agent runs the script, reports findings, walks
`checks/checkup.md`, and reports those in one combined summary.
