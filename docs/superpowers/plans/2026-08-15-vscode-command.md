# The `bunnyforge vscode` Command (#33) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development to implement this plan
> **task-by-task with a fresh subagent per task and review between tasks** —
> the components have clean seams and each task is TDD-able in isolation.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `bunnyforge vscode` subcommand family that installs/updates the
markdown-preview extension (sideloaded `.vsix` from GitHub releases) and
toggles the source-view colouring block that #34 scaffolds inert.

**Architecture:** One new module `src/bunnyforge/vscode.py` with `main(argv)`,
wired into `cli.py`'s `_COMMANDS`/`_SUMMARIES`. Internally: a pure-text
marker-region engine over `.vscode/settings.json` (Python has no stdlib JSONC
round-tripper, and the file's comments carry real documentation — so the tool
edits lines between markers and refuses when markers are broken); a pinned
GitHub-releases client with a digest-verified `.vsix` cache; cross-platform
editor-CLI discovery; and subcommands whose workspace requirement differs
per-subcommand. Uses argparse subparsers — `cli.py`'s no-subparsers rule is
about forwarding argv verbatim to other modules, which does not apply inside
a module that owns all its subcommands.

**Tech Stack:** Python ≥3.11 stdlib only (`urllib.request`, `hashlib`,
`subprocess`, `shutil.which`, `argparse`, `json`); `unittest` + `unittest.mock`.

**Spec:** https://github.com/dcltdw/bunnyforge/issues/33 — the body plus all
three comments (decisions 1–6, dated 2026-08-16, and the duplicate-key
hazard). The settled decisions are restated below so the executor never needs
GitHub. Prerequisite: **#34 merged to `main` first** — this plan reads the
packaged `data/vscode/settings.json` it ships.

## Global Constraints

- **Stdlib only**, Python ≥3.11.
- **Prerequisite:** branch only after #34 is merged; `git checkout main &&
  git pull` and confirm `src/bunnyforge/data/vscode/settings.json` exists.
- **House error pattern:** user-facing failures are one `error: <msg>` line on
  stderr, exit 1, never a traceback (see `init.py:main` for the shape).
- **Campaign-neutral:** no private campaign's name anywhere; portability tests
  stay green.
- **Pinned source:** the extension repo/URL are module constants; never read
  from config. Print exactly what will be installed and from where; confirm
  interactively; `--yes` for automation.
- **Rewrite only between the markers.** The one sanctioned exception: when
  *creating* the managed block in an existing file, a comma may be appended to
  the preceding property line. Refuse rather than guess on unbalanced markers.
- Branch off `main`, PR to `main` (say so explicitly), AGENTS.md PR body
  (files changed annotated, work breakdown, provenance), `Co-Authored-By:`
  trailer on every commit.
- Tests: `python3 -m unittest tests.test_vscode -v` per module; full:
  `python3 -m unittest discover -s tests -t . -v`.

## Settled decisions (2026-08-16 — do not re-litigate)

1. `on`/`setup` detect a missing `fabiospampinato.vscode-highlight` and offer
   to install it (Marketplace: `code --install-extension` works directly).
2. Always the **newest** release of the preview extension. No pinning.
3. Discovery also finds VS Code Insiders, VSCodium, Cursor and will install
   into them — stated plainly as **untested/unsupported** in output and docs.
4. `vscode on` **creates** the managed block when missing (existing
   workspaces never receive scaffolded files).
5. Workspace requirement is **per-subcommand**: `install`/`update`/`uninstall`
   never resolve a workspace; `on`/`off` always; `status` (and `setup`)
   optionally — report the machine half unconditionally, the workspace half
   only when one is found, and say plainly when there is not. Worth a sentence
   in `--help`.
6. Existing top-level `"highlight.regexes"` outside the markers → never
   append (silent duplicate key), never overwrite unasked. Prompt:
   **adopt** (recommended, bracket the user's rules — minimum span: the key
   through its closing brace), **replace** (packaged rules), **cancel**
   (nothing, exit non-zero). No TTY → fail naming `--adopt`/`--replace`.
7. (This design, approved 2026-08-15:) `on --replace` doubles as the
   **region-level reset**: with markers present it rewrites the region from
   the packaged bytes, discarding local tuning — explicit flag only, never
   prompted for, one code path with decision 6's replace arm.

The cross-ticket contract #34 froze (markers, `//- ` off-prefix after the
indent, region-first, pin outside region) is in
`docs/superpowers/plans/2026-08-15-vscode-scaffold-files.md` — read it before
Task 1.

## File structure

- `src/bunnyforge/vscode.py` — everything: constants, region engine,
  structural edits, discovery, release client, cache, subcommands. One module
  per command is the house pattern (`review.py`, `deploy_export.py` are
  larger); internal sections keep it navigable.
- `tests/test_vscode.py` — all new tests; network, subprocess, TTY and prompt
  are injected/mocked, nothing touches a real editor or GitHub.
- Small edits: `cli.py`, `init.py`, the two `data/vscode/*.json` headers,
  `README.md`, `tests/test_cli.py`, `tests/test_init.py`.

---

### Task 1: Module skeleton, constants, and the packaged-contract drift tests

**Files:**
- Create: `src/bunnyforge/vscode.py`
- Create: `tests/test_vscode.py`

**Interfaces:**
- Produces (consumed by every later task):
  `VscodeError(Exception)`; constants `EXTENSION_ID: str`,
  `EXTENSION_REPO: str`, `RELEASES_URL: str`, `HIGHLIGHT_ID: str`,
  `MARKER_BEGIN: str`, `MARKER_END: str`, `OFF_PREFIX: str`,
  `SETTINGS_REL: str`.

- [ ] **Step 1: Branch**

```bash
cd ~/Github/bunnyforge
git checkout main && git pull
test -f src/bunnyforge/data/vscode/settings.json || echo "STOP: #34 not merged"
git checkout -b feat/33-vscode-command
```

- [ ] **Step 2: Write the failing drift tests**

`tests/test_vscode.py`:

```python
"""Tests for bunnyforge.vscode — the editor-integration command.

Everything external is injected or mocked: `_fetch` (network), `_run`
(subprocess), `_interactive`/`_ask` (TTY). No test touches GitHub or a
real editor.
"""

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bunnyforge import init, vscode


class TestPackagedContract(unittest.TestCase):
    """vscode.py's constants and data/vscode/settings.json are two halves
    of one contract (#34 froze it); drift between them is a red test."""

    def _lines(self) -> list[str]:
        return (init.packaged_bytes("vscode/settings.json")
                .decode("utf-8").split("\n"))

    def test_the_packaged_markers_match_the_constants(self):
        stripped = [l.strip() for l in self._lines()]
        self.assertEqual(stripped.count(vscode.MARKER_BEGIN), 1)
        self.assertEqual(stripped.count(vscode.MARKER_END), 1)

    def test_the_packaged_region_round_trips_through_the_toggle(self):
        # disable(enable(x)) == x proves the packaged off-form is exactly
        # what disable_region produces — the byte-level half of the contract.
        lines = self._lines()
        begin, end = vscode.maybe_region(lines)
        self.assertEqual(vscode.region_state(lines, begin, end), "off")
        on = vscode.enable_region(lines, begin, end)
        self.assertEqual(vscode.region_state(on, begin, end), "on")
        self.assertEqual(vscode.disable_region(on, begin, end), lines)
```

(The second test also exercises Task 2's engine; it goes red now and fully
green at the end of Task 2.)

- [ ] **Step 3: Run to verify failure**

Run: `python3 -m unittest tests.test_vscode -v`
Expected: ERROR — `ImportError`/`AttributeError` (module and names missing).

- [ ] **Step 4: Create the skeleton**

`src/bunnyforge/vscode.py`:

```python
#!/usr/bin/env python3
"""
vscode.py — install/update the visibility-preview extension and toggle the
source-view colouring.

The extension (dcltdw.bunnyforge-visibility-preview) is not on the VS Code
Marketplace and will not be (publishing needs an Azure DevOps org linked to
an active Azure subscription); it sideloads as a .vsix from GitHub releases,
and sideloaded extensions never auto-update — which is why version detection
is the feature here rather than a nicety. It also has no runtime on/off
switch and cannot be given one (static preview contributions cannot read
extension configuration): for the preview half, "off" means "not installed".

The source-view half is a "highlight.regexes" block in the workspace's
.vscode/settings.json, delimited by marker comments that `bunnyforge init`
ships (inert) since #34. Python has no stdlib JSONC round-tripper and the
file's comments carry real documentation, so this module never parses the
file as JSON: it rewrites lines between the markers and refuses when the
markers are missing where required, or unbalanced anywhere.

Workspace requirements differ per subcommand (the first command in the
package where that is true): install/update/uninstall act on the machine's
editor and never resolve a workspace; on/off always do; status and setup
resolve one opportunistically and say plainly when there is none.

Stdlib only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import NamedTuple

from bunnyforge import _config, _workspace, init


class VscodeError(Exception):
    """The command cannot proceed. The message is user-facing."""


# The extension and its pinned source. Never read from config: this module
# downloads and installs code, so the source is a constant an auditor can
# read, not a value a workspace can redirect.
EXTENSION_ID = "dcltdw.bunnyforge-visibility-preview"
EXTENSION_REPO = "dcltdw/bunnyforge-visibility-preview"
RELEASES_URL = ("https://api.github.com/repos/"
                + EXTENSION_REPO + "/releases/latest")
HIGHLIGHT_ID = "fabiospampinato.vscode-highlight"

# The managed-region contract, frozen by #34: data/vscode/settings.json
# ships these exact marker lines, and the disabled form of a line is
# indent + OFF_PREFIX + body. tests/test_vscode.py pins the packaged file
# to these constants so neither can drift alone.
MARKER_BEGIN = "// bunnyforge:begin visibility-colouring"
MARKER_END = "// bunnyforge:end visibility-colouring"
OFF_PREFIX = "//- "

SETTINGS_REL = ".vscode/settings.json"
TIMEOUT = 10  # seconds, every network call
```

- [ ] **Step 5: Run the first test**

Run: `python3 -m unittest tests.test_vscode.TestPackagedContract.test_the_packaged_markers_match_the_constants -v`
Expected: PASS (the round-trip test still errors until Task 2 — fine).

- [ ] **Step 6: Commit**

```bash
git add src/bunnyforge/vscode.py tests/test_vscode.py
git commit -m "feat: vscode module skeleton and the packaged-contract constants (#33)"
```

---

### Task 2: The marker-region engine

**Files:**
- Modify: `src/bunnyforge/vscode.py`
- Test: `tests/test_vscode.py`

**Interfaces:**
- Produces:
  - `maybe_region(lines: list[str]) -> tuple[int, int] | None` — begin/end
    marker line indices; `None` when *neither* marker exists; `VscodeError`
    when markers are duplicated, lone, or out of order.
  - `region_state(lines, begin, end) -> str` — `"off"` (any `OFF_PREFIX`
    line), else `"on"` (any live line), else `"empty"`.
  - `enable_region(lines, begin, end) -> list[str]` /
    `disable_region(lines, begin, end) -> list[str]` — pure, non-mutating.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_vscode.py`:

```python
SAMPLE_OFF = """\
{
  // prose above the marker — never load-bearing
  // bunnyforge:begin visibility-colouring
  //- "highlight.regexes": {
    //- "^x$": { "a": 1 }
  //- },
  // ── ALTERNATE ──
  // "highlight.regexes": { "alt": true }
  // bunnyforge:end visibility-colouring
  "markdown.preview.frontMatter": "table"
}
""".split("\n")


class TestRegionEngine(unittest.TestCase):

    def test_finds_the_marker_pair(self):
        self.assertEqual(vscode.maybe_region(SAMPLE_OFF), (2, 8))

    def test_no_markers_at_all_is_none_not_an_error(self):
        self.assertIsNone(vscode.maybe_region(["{", "}"]))

    def test_a_lone_or_duplicated_marker_is_a_refusal(self):
        lone = [l for l in SAMPLE_OFF if l.strip() != vscode.MARKER_END]
        with self.assertRaises(vscode.VscodeError):
            vscode.maybe_region(lone)
        doubled = SAMPLE_OFF + ["  " + vscode.MARKER_BEGIN]
        with self.assertRaises(vscode.VscodeError):
            vscode.maybe_region(doubled)

    def test_end_before_begin_is_a_refusal(self):
        swapped = ["  " + vscode.MARKER_END, "x", "  " + vscode.MARKER_BEGIN]
        with self.assertRaises(vscode.VscodeError):
            vscode.maybe_region(swapped)

    def test_state_off_then_on(self):
        begin, end = vscode.maybe_region(SAMPLE_OFF)
        self.assertEqual(vscode.region_state(SAMPLE_OFF, begin, end), "off")
        on = vscode.enable_region(SAMPLE_OFF, begin, end)
        self.assertEqual(vscode.region_state(on, begin, end), "on")

    def test_enable_preserves_indentation_and_plain_comments(self):
        begin, end = vscode.maybe_region(SAMPLE_OFF)
        on = vscode.enable_region(SAMPLE_OFF, begin, end)
        self.assertEqual(on[3], '  "highlight.regexes": {')
        self.assertEqual(on[4], '    "^x$": { "a": 1 }')
        self.assertEqual(on[6], "  // ── ALTERNATE ──")   # untouched
        self.assertEqual(on[7], '  // "highlight.regexes": { "alt": true }')
        self.assertEqual(on[9], '  "markdown.preview.frontMatter": "table"')

    def test_disable_prefixes_only_live_lines(self):
        begin, end = vscode.maybe_region(SAMPLE_OFF)
        on = vscode.enable_region(SAMPLE_OFF, begin, end)
        self.assertEqual(vscode.disable_region(on, begin, end), SAMPLE_OFF)

    def test_both_transforms_are_idempotent(self):
        begin, end = vscode.maybe_region(SAMPLE_OFF)
        off2 = vscode.disable_region(SAMPLE_OFF, begin, end)
        self.assertEqual(off2, SAMPLE_OFF)
        on = vscode.enable_region(SAMPLE_OFF, begin, end)
        self.assertEqual(vscode.enable_region(on, begin, end), on)

    def test_transforms_do_not_mutate_their_input(self):
        begin, end = vscode.maybe_region(SAMPLE_OFF)
        copy = list(SAMPLE_OFF)
        vscode.enable_region(SAMPLE_OFF, begin, end)
        self.assertEqual(SAMPLE_OFF, copy)
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest tests.test_vscode.TestRegionEngine -v`
Expected: ERROR — names not defined.

- [ ] **Step 3: Implement**

Append to `src/bunnyforge/vscode.py`:

```python
# ── The marker-region engine ────────────────────────────────────────────
# Pure text -> text. State is always DERIVED from the region's content,
# never stored anywhere it could disagree with reality.

def _split_indent(line: str) -> tuple[str, str]:
    body = line.lstrip(" \t")
    return line[:len(line) - len(body)], body


def maybe_region(lines: list[str]) -> tuple[int, int] | None:
    """The (begin, end) marker line indices, or None when neither marker
    exists (the create-the-block case). A lone, duplicated, or reversed
    marker raises: rewriting between markers that cannot be trusted would
    destroy a file the user hand-edited, so refuse and say why.
    """
    begins = [i for i, l in enumerate(lines) if l.strip() == MARKER_BEGIN]
    ends = [i for i, l in enumerate(lines) if l.strip() == MARKER_END]
    if not begins and not ends:
        return None
    if len(begins) != 1 or len(ends) != 1 or ends[0] < begins[0]:
        raise VscodeError(
            f"the managed markers in {SETTINGS_REL} are unbalanced "
            f"({len(begins)} begin, {len(ends)} end) — refusing to guess "
            f"which lines are managed; restore the single marker pair by "
            f"hand, then re-run")
    return begins[0], ends[0]


def region_state(lines: list[str], begin: int, end: int) -> str:
    """"off" outranks "on": a region holding both disabled and live lines
    was hand-mangled, and reporting it off lets `on` heal it (enabling
    strips every prefix, converging the region to fully live)."""
    live = False
    for line in lines[begin + 1:end]:
        body = line.strip()
        if body.startswith(OFF_PREFIX):
            return "off"
        if body and not body.startswith("//"):
            live = True
    return "on" if live else "empty"


def enable_region(lines: list[str], begin: int, end: int) -> list[str]:
    out = list(lines)
    for i in range(begin + 1, end):
        indent, body = _split_indent(out[i])
        if body.startswith(OFF_PREFIX):
            out[i] = indent + body[len(OFF_PREFIX):]
    return out


def disable_region(lines: list[str], begin: int, end: int) -> list[str]:
    out = list(lines)
    for i in range(begin + 1, end):
        indent, body = _split_indent(out[i])
        if body and not body.startswith("//"):
            out[i] = indent + OFF_PREFIX + body
    return out
```

- [ ] **Step 4: Run to verify green**

Run: `python3 -m unittest tests.test_vscode -v`
Expected: PASS — including Task 1's round-trip contract test.

- [ ] **Step 5: Commit**

```bash
git add src/bunnyforge/vscode.py tests/test_vscode.py
git commit -m "feat: marker-region engine — find, state, enable, disable (#33)"
```

---

### Task 3: Structural edits — create, adopt, replace

**Files:**
- Modify: `src/bunnyforge/vscode.py`
- Test: `tests/test_vscode.py`

**Interfaces:**
- Consumes: Task 2's engine; `init.packaged_bytes("vscode/settings.json")`.
- Produces:
  - `key_span(lines, start: int) -> int` — last line index of the value
    opened on `lines[start]`; `VscodeError` if braces never balance.
  - `find_unmanaged_key(lines, region: tuple[int, int] | None) -> int | None`
    — line index of a live top-level `"highlight.regexes"` outside `region`.
  - `packaged_region_lines() -> list[str]` — markers inclusive, from the
    packaged settings file.
  - `splice_region(lines) -> list[str]` — insert the packaged region before
    the final `}`, comma-fixing the preceding property (the one sanctioned
    outside-the-markers edit).
  - `adopt_key(lines, key_idx: int) -> list[str]` — bracket the minimum span
    (key line through closing brace) with the markers.
  - `replace_region(lines, begin, end) -> list[str]` — region content :=
    packaged region content.

- [ ] **Step 1: Write the failing tests**

```python
UNMANAGED = """\
{
  "editor.rulers": [80],
  "highlight.regexes": {
    "^(## GM notes{2}\\\\s*)$": {
      "decorations": [{ "quote": "}" }]
    }
  },
  "markdown.preview.frontMatter": "table"
}
""".split("\n")


class TestStructuralEdits(unittest.TestCase):

    def test_key_span_ignores_braces_in_strings_and_comments(self):
        # The value spans lines 2..6; "{2}" and the "}" string literal and
        # any // comment must not confuse the scan.
        self.assertEqual(vscode.key_span(UNMANAGED, 2), 6)

    def test_key_span_on_a_single_line_value(self):
        doc = ['{', '  "highlight.regexes": {},', '}']
        self.assertEqual(vscode.key_span(doc, 1), 1)

    def test_key_span_refuses_unbalanced_braces(self):
        with self.assertRaises(vscode.VscodeError):
            vscode.key_span(['{', '  "highlight.regexes": {', ''], 1)

    def test_finds_the_unmanaged_key_and_skips_comments(self):
        self.assertEqual(vscode.find_unmanaged_key(UNMANAGED, None), 2)
        commented = ['{', '  // "highlight.regexes": {}', '}']
        self.assertIsNone(vscode.find_unmanaged_key(commented, None))

    def test_the_managed_region_is_not_reported_as_unmanaged(self):
        begin, end = vscode.maybe_region(SAMPLE_OFF)
        on = vscode.enable_region(SAMPLE_OFF, begin, end)
        self.assertIsNone(vscode.find_unmanaged_key(on, (begin, end)))

    def test_packaged_region_lines_are_marker_delimited(self):
        region = vscode.packaged_region_lines()
        self.assertEqual(region[0].strip(), vscode.MARKER_BEGIN)
        self.assertEqual(region[-1].strip(), vscode.MARKER_END)

    def test_splice_adds_the_region_and_a_comma(self):
        doc = ['{', '  // a comment', '  "editor.rulers": [80]', '}', '']
        out = vscode.splice_region(doc)
        self.assertEqual(out[2], '  "editor.rulers": [80],')
        begin, end = vscode.maybe_region(out)
        self.assertEqual(out[-2].strip(), "}")
        # enabled result must be strict JSON once comments drop
        enabled = vscode.enable_region(out, begin, end)
        data = json.loads("\n".join(
            l for l in enabled if not l.strip().startswith("//")))
        self.assertIn("highlight.regexes", data)
        self.assertEqual(data["editor.rulers"], [80])

    def test_splice_into_an_empty_object_needs_no_comma(self):
        out = vscode.splice_region(['{', '}'])
        begin, end = vscode.maybe_region(out)
        enabled = vscode.enable_region(out, begin, end)
        json.loads("\n".join(
            l for l in enabled if not l.strip().startswith("//")))

    def test_splice_refuses_a_file_with_no_closing_brace(self):
        with self.assertRaises(vscode.VscodeError):
            vscode.splice_region(['not a settings object'])

    def test_adopt_brackets_the_minimum_span(self):
        out = vscode.adopt_key(UNMANAGED, 2)
        begin, end = vscode.maybe_region(out)
        self.assertEqual(out[begin].strip(), vscode.MARKER_BEGIN)
        self.assertEqual(out[begin + 1], UNMANAGED[2])   # content untouched
        self.assertEqual(out[end - 1], UNMANAGED[6])
        self.assertEqual(vscode.region_state(out, begin, end), "on")
        # everything outside the span is byte-identical
        self.assertEqual(out[:begin], UNMANAGED[:2])
        self.assertEqual(out[end + 1:], UNMANAGED[7:])

    def test_replace_swaps_region_content_for_packaged(self):
        begin, end = vscode.maybe_region(SAMPLE_OFF)
        out = vscode.replace_region(SAMPLE_OFF, begin, end)
        nbegin, nend = vscode.maybe_region(out)
        self.assertEqual(out[nbegin:nend + 1], vscode.packaged_region_lines())
        self.assertEqual(out[:nbegin], SAMPLE_OFF[:begin])   # outside kept
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest tests.test_vscode.TestStructuralEdits -v`
Expected: ERROR — names not defined.

- [ ] **Step 3: Implement**

```python
# ── Structural edits: create, adopt, replace ────────────────────────────

def key_span(lines: list[str], start: int) -> int:
    """Last line index of the JSON value opened on lines[start].

    A character scan tracking string state (so braces inside regex keys
    and string values don't count) and line comments, balancing {}/[].
    """
    depth = 0
    opened = False
    for i in range(start, len(lines)):
        line = lines[i]
        in_string = False
        j = 0
        while j < len(line):
            ch = line[j]
            if in_string:
                if ch == "\\":
                    j += 1
                elif ch == '"':
                    in_string = False
            elif ch == '"':
                in_string = True
            elif line[j:j + 2] == "//":
                break
            elif ch in "{[":
                depth += 1
                opened = True
            elif ch in "}]":
                depth -= 1
            j += 1
        if opened and depth <= 0:
            return i
    raise VscodeError(
        f'the "highlight.regexes" value in {SETTINGS_REL} never closes '
        f"its braces — fix the file by hand, then re-run")


def find_unmanaged_key(lines: list[str],
                       region: tuple[int, int] | None) -> int | None:
    """A live top-level "highlight.regexes" outside the managed region —
    the duplicate-key hazard: appending a second copy would be a silent
    last-one-wins that clobbers whatever the user tuned."""
    for i, line in enumerate(lines):
        if region and region[0] <= i <= region[1]:
            continue
        if line.strip().startswith('"highlight.regexes"'):
            return i
    return None


def packaged_region_lines() -> list[str]:
    lines = (init.packaged_bytes("vscode/settings.json")
             .decode("utf-8").split("\n"))
    begin, end = maybe_region(lines)  # never None: the drift test pins it
    return lines[begin:end + 1]


def splice_region(lines: list[str]) -> list[str]:
    """Insert the packaged managed region before the final closing brace.

    The comma appended to the preceding property is the one sanctioned
    edit outside the markers, and it happens only here, at creation.
    """
    close = next((i for i in range(len(lines) - 1, -1, -1)
                  if lines[i].strip() == "}"), None)
    if close is None:
        raise VscodeError(
            f"{SETTINGS_REL} does not end with a closing brace — not a "
            f"settings object this tool can edit; fix or remove the file, "
            f"then re-run")
    out = list(lines)
    last = next((i for i in range(close - 1, -1, -1)
                 if out[i].strip() and not out[i].strip().startswith("//")),
                None)
    if last is not None and not out[last].rstrip().endswith(("{", ",")):
        out[last] = out[last].rstrip() + ","
    return out[:close] + packaged_region_lines() + out[close:]


def adopt_key(lines: list[str], key_idx: int) -> list[str]:
    """Bracket the existing rules with the markers, content untouched —
    the minimum span, key line through its closing brace. Nearby
    commented-out blocks stay outside: they are comments, and `off` never
    needs to touch them."""
    end = key_span(lines, key_idx)
    indent = _split_indent(lines[key_idx])[0]
    out = list(lines)
    out.insert(end + 1, indent + MARKER_END)
    out.insert(key_idx, indent + MARKER_BEGIN)
    return out


def replace_region(lines: list[str], begin: int, end: int) -> list[str]:
    return lines[:begin] + packaged_region_lines() + lines[end + 1:]
```

- [ ] **Step 4: Run to verify green, then commit**

Run: `python3 -m unittest tests.test_vscode -v` — Expected: PASS.

```bash
git add src/bunnyforge/vscode.py tests/test_vscode.py
git commit -m "feat: managed-block create, adopt, and replace edits (#33)"
```

---

### Task 4: Editor discovery and version handling

**Files:**
- Modify: `src/bunnyforge/vscode.py`
- Test: `tests/test_vscode.py`

**Interfaces:**
- Produces:
  - `class Editor(NamedTuple): cli_id: str; label: str; path: str;
    supported: bool`
  - `discover_editors(which=shutil.which, platform=sys.platform,
    exists=<Path.is_file>) -> list[Editor]`
  - `pick_editor(editors: list[Editor], wanted: str | None) -> Editor`
  - `parse_version(text: str) -> tuple[int, ...]`
  - `installed_version(editor: Editor, extension_id: str = EXTENSION_ID)
    -> tuple[int, ...] | None`
  - `_run(argv: list[str]) -> subprocess.CompletedProcess` (the subprocess
    seam every test mocks), `_interactive() -> bool`, `_ask(prompt) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
def _proc(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


class TestEditorDiscovery(unittest.TestCase):

    def test_finds_editors_on_path_in_stable_first_order(self):
        which = {"code": "/usr/bin/code", "cursor": "/usr/bin/cursor"}.get
        found = vscode.discover_editors(which=which, platform="linux")
        self.assertEqual([(e.cli_id, e.supported) for e in found],
                         [("code", True), ("cursor", False)])

    def test_falls_back_to_the_mac_app_bundle(self):
        mac = ("/Applications/Visual Studio Code.app/Contents/Resources"
               "/app/bin/code")
        found = vscode.discover_editors(
            which=lambda _: None, platform="darwin",
            exists=lambda p: p == mac)
        self.assertEqual([e.path for e in found], [mac])

    def test_pick_honours_the_flag_and_rejects_unknown(self):
        editors = [vscode.Editor("code", "Visual Studio Code",
                                 "/usr/bin/code", True)]
        self.assertEqual(vscode.pick_editor(editors, "code"), editors[0])
        with self.assertRaises(vscode.VscodeError):
            vscode.pick_editor(editors, "codium")

    def test_pick_with_none_found_names_the_command_palette(self):
        with self.assertRaises(vscode.VscodeError) as ctx:
            vscode.pick_editor([], None)
        self.assertIn("Shell Command", str(ctx.exception))

    def test_pick_defaults_to_stable_without_a_tty(self):
        editors = [
            vscode.Editor("code", "Visual Studio Code", "/u/code", True),
            vscode.Editor("cursor", "Cursor", "/u/cursor", False),
        ]
        with mock.patch.object(vscode, "_interactive", return_value=False):
            self.assertEqual(vscode.pick_editor(editors, None).cli_id, "code")

    def test_pick_without_stable_and_no_tty_names_the_flag(self):
        editors = [vscode.Editor("cursor", "Cursor", "/u/cursor", False),
                   vscode.Editor("codium", "VSCodium", "/u/codium", False)]
        with mock.patch.object(vscode, "_interactive", return_value=False):
            with self.assertRaises(vscode.VscodeError) as ctx:
                vscode.pick_editor(editors, None)
        self.assertIn("--editor", str(ctx.exception))


class TestVersions(unittest.TestCase):

    def test_parse_version_accepts_v_prefix(self):
        self.assertEqual(vscode.parse_version("v0.1.0"), (0, 1, 0))
        self.assertEqual(vscode.parse_version("0.10.2"), (0, 10, 2))

    def test_parse_version_refuses_garbage(self):
        with self.assertRaises(vscode.VscodeError):
            vscode.parse_version("latest")

    def test_installed_version_parses_the_listing(self):
        editor = vscode.Editor("code", "VS Code", "/u/code", True)
        listing = ("other.extension@9.9.9\n"
                   "dcltdw.bunnyforge-visibility-preview@0.1.0\n")
        with mock.patch.object(vscode, "_run",
                               return_value=_proc(listing)) as run:
            self.assertEqual(vscode.installed_version(editor), (0, 1, 0))
        run.assert_called_once_with(
            ["/u/code", "--list-extensions", "--show-versions"])

    def test_installed_version_none_when_absent(self):
        editor = vscode.Editor("code", "VS Code", "/u/code", True)
        with mock.patch.object(vscode, "_run", return_value=_proc("a@1\n")):
            self.assertIsNone(vscode.installed_version(editor))

    def test_installed_version_surfaces_a_failing_cli(self):
        editor = vscode.Editor("code", "VS Code", "/u/code", True)
        with mock.patch.object(vscode, "_run",
                               return_value=_proc("", 1, "boom")):
            with self.assertRaises(vscode.VscodeError):
                vscode.installed_version(editor)
```

- [ ] **Step 2: Run to verify failure**, then **Step 3: Implement**

```python
# ── Editors ─────────────────────────────────────────────────────────────
# Stable first: it is the tested editor and every default resolves to it.
# The rest are offered because sideloading a .vsix is exactly how the
# non-Marketplace editors install things (decision 3) — but they are
# untested, and every mention of them says so.
_EDITORS = (
    ("code", "Visual Studio Code", True),
    ("code-insiders", "VS Code Insiders", False),
    ("codium", "VSCodium", False),
    ("cursor", "Cursor", False),
)

# PATH is searched first everywhere; these app-bundle paths cover the one
# platform whose installer does NOT put the CLI on PATH (macOS — the
# machine this was developed on had `which code` fail with the binary at
# this exact path). Windows and Linux installers put the CLI on PATH by
# default, so PATH is their discovery.
_MAC_APPS = {
    "code": ("/Applications/Visual Studio Code.app"
             "/Contents/Resources/app/bin/code"),
    "code-insiders": ("/Applications/Visual Studio Code - Insiders.app"
                      "/Contents/Resources/app/bin/code-insiders"),
    "codium": "/Applications/VSCodium.app/Contents/Resources/app/bin/codium",
    "cursor": "/Applications/Cursor.app/Contents/Resources/app/bin/cursor",
}


class Editor(NamedTuple):
    cli_id: str
    label: str
    path: str
    supported: bool


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True)


def _interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _ask(prompt: str) -> str:
    return input(prompt)


def discover_editors(which=shutil.which, platform=sys.platform,
                     exists=lambda p: Path(p).is_file()) -> list[Editor]:
    found = []
    for cli_id, label, supported in _EDITORS:
        path = which(cli_id)
        if path is None and platform == "darwin" and exists(_MAC_APPS[cli_id]):
            path = _MAC_APPS[cli_id]
        if path:
            found.append(Editor(cli_id, label, path, supported))
    return found


def pick_editor(editors: list[Editor], wanted: str | None) -> Editor:
    if wanted:
        match = next((e for e in editors if e.cli_id == wanted), None)
        if match is None:
            raise VscodeError(
                f"--editor {wanted}: not found (found: "
                f"{', '.join(e.cli_id for e in editors) or 'none'})")
        return match
    if not editors:
        raise VscodeError(
            "no editor CLI found on PATH or in known locations — in VS "
            "Code, run \"Shell Command: Install 'code' command in PATH\" "
            "from the Command Palette, then re-run")
    if len(editors) == 1:
        return editors[0]
    stable = next((e for e in editors if e.cli_id == "code"), None)
    if not _interactive():
        if stable:
            return stable
        raise VscodeError(
            "several editors found and no terminal to ask — pass "
            "--editor " + "|".join(e.cli_id for e in editors))
    print("several editors found:")
    for n, e in enumerate(editors, 1):
        note = "" if e.supported else "  (untested — may have bugs)"
        print(f"  [{n}] {e.label}{note}")
    default = editors.index(stable) + 1 if stable else 1
    answer = _ask(f"install into [{default}]: ").strip()
    if answer.isdigit() and 1 <= int(answer) <= len(editors):
        return editors[int(answer) - 1]
    return editors[default - 1]


# ── Versions ────────────────────────────────────────────────────────────

def parse_version(text: str) -> tuple[int, ...]:
    body = text.strip().removeprefix("v")
    try:
        return tuple(int(part) for part in body.split("."))
    except ValueError:
        raise VscodeError(f"unparseable version {text!r}") from None


def installed_version(editor: Editor,
                      extension_id: str = EXTENSION_ID
                      ) -> tuple[int, ...] | None:
    proc = _run([editor.path, "--list-extensions", "--show-versions"])
    if proc.returncode != 0:
        raise VscodeError(
            f"{editor.cli_id} --list-extensions failed: "
            f"{proc.stderr.strip() or proc.returncode}")
    for line in proc.stdout.splitlines():
        name, _, version = line.partition("@")
        if name.strip().lower() == extension_id:
            return parse_version(version)
    return None
```

- [ ] **Step 4: Run to verify green, then commit**

Run: `python3 -m unittest tests.test_vscode -v` — Expected: PASS.

```bash
git add src/bunnyforge/vscode.py tests/test_vscode.py
git commit -m "feat: editor discovery and installed-version detection (#33)"
```

---

### Task 5: Release client, cache, and verified download

**Files:**
- Modify: `src/bunnyforge/vscode.py`
- Test: `tests/test_vscode.py`

**Interfaces:**
- Produces:
  - `class Release(NamedTuple): version: tuple[int, ...]; tag: str;
    vsix_name: str; url: str; size: int; sha256: str | None`
  - `_fetch(url: str) -> bytes` (the network seam; urllib +
    `User-Agent: bunnyforge`, `TIMEOUT`)
  - `latest_release(fetch=_fetch) -> Release` — `VscodeError` with an
    offline-flavoured message on any `OSError`.
  - `cache_dir(platform=sys.platform, environ=os.environ) -> Path`
  - `obtain_vsix(release: Release, fetch=_fetch) -> Path` — cache hit
    (verified) or download+verify+store; never returns an unverified file.

- [ ] **Step 1: Write the failing tests**

```python
RELEASE_JSON = json.dumps({
    "tag_name": "v0.2.0",
    "assets": [
        {"name": "notes.txt", "browser_download_url": "u1", "size": 1},
        {"name": "bunnyforge-visibility-preview-0.2.0.vsix",
         "browser_download_url": "https://example.invalid/x.vsix",
         "size": 4,
         "digest": "sha256:" + __import__("hashlib")
             .sha256(b"vsix").hexdigest()},
    ],
}).encode("utf-8")


class TestReleaseClient(unittest.TestCase):

    def test_parses_tag_asset_size_and_digest(self):
        release = vscode.latest_release(fetch=lambda url: RELEASE_JSON)
        self.assertEqual(release.version, (0, 2, 0))
        self.assertEqual(release.tag, "v0.2.0")
        self.assertEqual(release.vsix_name,
                         "bunnyforge-visibility-preview-0.2.0.vsix")
        self.assertEqual(release.size, 4)
        self.assertEqual(len(release.sha256), 64)

    def test_a_missing_digest_is_tolerated(self):
        data = json.loads(RELEASE_JSON)
        del data["assets"][1]["digest"]
        release = vscode.latest_release(
            fetch=lambda url: json.dumps(data).encode())
        self.assertIsNone(release.sha256)

    def test_no_vsix_asset_is_an_error(self):
        data = json.loads(RELEASE_JSON)
        data["assets"] = data["assets"][:1]
        with self.assertRaises(vscode.VscodeError):
            vscode.latest_release(fetch=lambda url: json.dumps(data).encode())

    def test_network_failure_degrades_to_a_named_error(self):
        def down(url):
            raise OSError("no route to host")
        with self.assertRaises(vscode.VscodeError) as ctx:
            vscode.latest_release(fetch=down)
        self.assertIn("GitHub", str(ctx.exception))


class TestCache(unittest.TestCase):

    def test_cache_dir_per_platform(self):
        home = Path.home()
        self.assertEqual(
            vscode.cache_dir(platform="darwin", environ={}),
            home / "Library" / "Caches" / "bunnyforge" / "vsix")
        self.assertEqual(
            vscode.cache_dir(platform="linux",
                             environ={"XDG_CACHE_HOME": "/xdg"}),
            Path("/xdg") / "bunnyforge" / "vsix")
        self.assertEqual(
            vscode.cache_dir(platform="linux", environ={}),
            home / ".cache" / "bunnyforge" / "vsix")
        self.assertEqual(
            vscode.cache_dir(platform="win32",
                             environ={"LOCALAPPDATA": r"C:\U\l"}),
            Path(r"C:\U\l") / "bunnyforge" / "vsix")

    def _release(self):
        return vscode.latest_release(fetch=lambda url: RELEASE_JSON)

    def test_downloads_verifies_and_caches(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        calls = []

        def fetch(url):
            calls.append(url)
            return b"vsix"

        with mock.patch.object(vscode, "cache_dir", return_value=tmp):
            path = vscode.obtain_vsix(self._release(), fetch=fetch)
            self.assertEqual(path.read_bytes(), b"vsix")
            # second run: cache hit, no re-download
            vscode.obtain_vsix(self._release(), fetch=fetch)
        self.assertEqual(calls, ["https://example.invalid/x.vsix"])

    def test_a_truncated_download_never_lands_in_the_cache(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        with mock.patch.object(vscode, "cache_dir", return_value=tmp):
            with self.assertRaises(vscode.VscodeError):
                vscode.obtain_vsix(self._release(), fetch=lambda url: b"vs")
        self.assertEqual(list(tmp.iterdir()), [])

    def test_a_digest_mismatch_never_lands_in_the_cache(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        with mock.patch.object(vscode, "cache_dir", return_value=tmp):
            with self.assertRaises(vscode.VscodeError):
                vscode.obtain_vsix(self._release(), fetch=lambda url: b"eviL")
        self.assertEqual(list(tmp.iterdir()), [])

    def test_a_corrupt_cached_file_is_re_downloaded(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        release = self._release()
        stale = tmp / f"{release.tag}-{release.vsix_name}"
        stale.write_bytes(b"junk-of-wrong-size")
        with mock.patch.object(vscode, "cache_dir", return_value=tmp):
            path = vscode.obtain_vsix(release, fetch=lambda url: b"vsix")
        self.assertEqual(path.read_bytes(), b"vsix")
```

- [ ] **Step 2: Run to verify failure**, then **Step 3: Implement**

```python
# ── The release feed and the .vsix cache ────────────────────────────────

class Release(NamedTuple):
    version: tuple[int, ...]
    tag: str
    vsix_name: str
    url: str
    size: int
    sha256: str | None      # release assets predating GitHub digests: None


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={
        "User-Agent": "bunnyforge",
        "Accept": "application/vnd.github+json",
    })
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read()


def latest_release(fetch=_fetch) -> Release:
    """The newest release (decision 2: no pinning) from the pinned repo.

    Unauthenticated: 60 requests/hour is ample for a human-driven command,
    but offline or rate-limited must degrade to a clear error the caller
    can choose to swallow (status) or surface (install)."""
    try:
        raw = fetch(RELEASES_URL)
    except OSError as exc:
        raise VscodeError(
            f"couldn't reach GitHub for the latest release ({exc}) — "
            f"check the network and retry") from exc
    data = json.loads(raw)
    asset = next((a for a in data.get("assets", [])
                  if a.get("name", "").endswith(".vsix")), None)
    if asset is None:
        raise VscodeError(
            f"release {data.get('tag_name', '?')} of {EXTENSION_REPO} has "
            f"no .vsix asset — report it at "
            f"https://github.com/{EXTENSION_REPO}/issues")
    digest = asset.get("digest") or ""
    return Release(
        version=parse_version(data["tag_name"]),
        tag=data["tag_name"],
        vsix_name=asset["name"],
        url=asset["browser_download_url"],
        size=asset["size"],
        sha256=digest.removeprefix("sha256:") if digest.startswith("sha256:")
               else None)


def cache_dir(platform=sys.platform, environ=os.environ) -> Path:
    if platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    elif platform.startswith("win"):
        base = Path(environ.get("LOCALAPPDATA")
                    or Path.home() / "AppData" / "Local")
    else:
        base = Path(environ.get("XDG_CACHE_HOME")
                    or Path.home() / ".cache")
    return base / "bunnyforge" / "vsix"


def _matches(data: bytes, release: Release) -> bool:
    if len(data) != release.size:
        return False
    if release.sha256 is None:
        return True
    return hashlib.sha256(data).hexdigest() == release.sha256


def obtain_vsix(release: Release, fetch=_fetch) -> Path:
    """A verified .vsix on disk: the cache if it checks out, else a fresh
    download — verified BEFORE it lands in the cache, so a truncated or
    tampered file is never present to be installed later."""
    dest = cache_dir() / f"{release.tag}-{release.vsix_name}"
    if dest.is_file() and _matches(dest.read_bytes(), release):
        return dest
    try:
        data = fetch(release.url)
    except OSError as exc:
        raise VscodeError(
            f"downloading {release.vsix_name} failed ({exc}) — check the "
            f"network and retry") from exc
    if len(data) != release.size:
        raise VscodeError(
            f"download of {release.vsix_name} is {len(data)} bytes; the "
            f"release says {release.size} — truncated, not installing")
    if release.sha256 and hashlib.sha256(data).hexdigest() != release.sha256:
        raise VscodeError(
            f"download of {release.vsix_name} does not match the release "
            f"digest — not installing")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest
```

- [ ] **Step 4: Run to verify green, then commit**

Run: `python3 -m unittest tests.test_vscode -v` — Expected: PASS.

```bash
git add src/bunnyforge/vscode.py tests/test_vscode.py
git commit -m "feat: pinned release client and digest-verified vsix cache (#33)"
```

---

### Task 6: The machine-half subcommands and the argparse front door

**Files:**
- Modify: `src/bunnyforge/vscode.py`
- Test: `tests/test_vscode.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `main(argv: list[str] | None = None) -> int`; `_parser()`;
  `_confirm(question: str, assume_yes: bool) -> bool`;
  `cmd_status`, `cmd_install`, `cmd_update`, `cmd_uninstall` (each
  `(args) -> int`); `_dotted(version: tuple[int, ...]) -> str`.
  Subcommand grammar (also consumed by Task 7):
  `status|setup|on [--workspace] [--editor] [--yes] [--adopt|--replace]`,
  `off [--workspace]`, `install|update|uninstall [--editor] [--yes]`
  (`status` takes `--workspace`/`--editor` but not `--yes`; `on` and
  `setup` take all five; exact wiring in the code below).

- [ ] **Step 1: Write the failing tests**

```python
def _machine_env(case, installed=None, listing=""):
    """Patch discovery + subprocess + network for machine-half tests.
    Returns the mock recording _run calls."""
    editor = vscode.Editor("code", "Visual Studio Code", "/u/code", True)
    case.enterContext(mock.patch.object(
        vscode, "discover_editors", return_value=[editor]))
    shown = (f"{vscode.EXTENSION_ID}@{installed}\n" if installed else "")
    run = case.enterContext(mock.patch.object(
        vscode, "_run",
        return_value=_proc(shown + listing)))
    case.enterContext(mock.patch.object(
        vscode, "latest_release",
        return_value=vscode.latest_release(fetch=lambda url: RELEASE_JSON)))
    tmp = Path(case.enterContext(tempfile.TemporaryDirectory()))
    case.enterContext(mock.patch.object(
        vscode, "obtain_vsix",
        return_value=tmp / "v0.2.0-x.vsix"))
    return run


class TestInstallUpdate(unittest.TestCase):

    def test_install_refuses_without_yes_when_not_a_tty(self):
        _machine_env(self)
        with mock.patch.object(vscode, "_interactive", return_value=False):
            with contextlib.redirect_stdout(io.StringIO()), \
                 contextlib.redirect_stderr(io.StringIO()) as err:
                rc = vscode.main(["install"])
        self.assertEqual(rc, 1)
        self.assertIn("--yes", err.getvalue())

    def test_install_prints_provenance_and_installs(self):
        run = _machine_env(self)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = vscode.main(["install", "--yes"])
        self.assertEqual(rc, 0)
        text = out.getvalue()
        self.assertIn(vscode.EXTENSION_REPO, text)   # pinned source, shown
        self.assertIn("v0.2.0", text)
        install_call = run.call_args_list[-1].args[0]
        self.assertEqual(install_call[:2], ["/u/code", "--install-extension"])
        self.assertIn("--force", install_call)

    def test_install_is_idempotent_at_the_current_version(self):
        run = _machine_env(self, installed="0.2.0")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = vscode.main(["install", "--yes"])
        self.assertEqual(rc, 0)
        self.assertIn("nothing to do", out.getvalue())
        for call in run.call_args_list:
            self.assertNotIn("--install-extension", call.args[0])

    def test_update_requires_an_existing_install(self):
        _machine_env(self)   # nothing installed
        with contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(io.StringIO()) as err:
            rc = vscode.main(["update", "--yes"])
        self.assertEqual(rc, 1)
        self.assertIn("vscode install", err.getvalue())

    def test_update_upgrades_an_older_install(self):
        run = _machine_env(self, installed="0.1.0")
        with contextlib.redirect_stdout(io.StringIO()):
            rc = vscode.main(["update", "--yes"])
        self.assertEqual(rc, 0)
        self.assertIn("--install-extension",
                      run.call_args_list[-1].args[0])


class TestUninstall(unittest.TestCase):

    def test_uninstall_runs_the_editor_cli(self):
        run = _machine_env(self, installed="0.2.0")
        with contextlib.redirect_stdout(io.StringIO()):
            rc = vscode.main(["uninstall", "--yes"])
        self.assertEqual(rc, 0)
        self.assertEqual(run.call_args_list[-1].args[0],
                         ["/u/code", "--uninstall-extension",
                          vscode.EXTENSION_ID])

    def test_uninstall_when_absent_is_a_no_op(self):
        run = _machine_env(self)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = vscode.main(["uninstall", "--yes"])
        self.assertEqual(rc, 0)
        self.assertIn("nothing to do", out.getvalue())
        for call in run.call_args_list:
            self.assertNotIn("--uninstall-extension", call.args[0])


class TestStatus(unittest.TestCase):

    def test_status_without_a_workspace_says_so_and_exits_zero(self):
        _machine_env(self, installed="0.1.0")
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        env = {k: v for k, v in os.environ.items()
               if k != "BUNNYFORGE_WORKSPACE"}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(Path, "cwd", return_value=tmp), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            rc = vscode.main(["status"])
        self.assertEqual(rc, 0)
        text = out.getvalue()
        self.assertIn("0.1.0", text)          # installed
        self.assertIn("0.2.0", text)          # available
        self.assertIn("none found", text)     # the workspace half, plainly

    def test_status_reports_colouring_state_in_a_workspace(self):
        _machine_env(self, installed="0.2.0")
        ws = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        (ws / "campaign.toml").write_text(
            '[campaign]\nnamespace = "probe"\n', encoding="utf-8")
        (ws / ".vscode").mkdir()
        (ws / ".vscode" / "settings.json").write_bytes(
            init.packaged_bytes("vscode/settings.json"))
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = vscode.main(["status", "--workspace", str(ws)])
        self.assertEqual(rc, 0)
        self.assertIn("off", out.getvalue())

    def test_status_degrades_when_github_is_unreachable(self):
        editor = vscode.Editor("code", "Visual Studio Code", "/u/code", True)
        self.enterContext(mock.patch.object(
            vscode, "discover_editors", return_value=[editor]))
        self.enterContext(mock.patch.object(vscode, "_run",
                                            return_value=_proc("")))
        self.enterContext(mock.patch.object(
            vscode, "latest_release",
            side_effect=vscode.VscodeError("couldn't reach GitHub")))
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        env = {k: v for k, v in os.environ.items()
               if k != "BUNNYFORGE_WORKSPACE"}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(Path, "cwd", return_value=tmp), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            rc = vscode.main(["status"])
        self.assertEqual(rc, 0)               # status reports; never fails
        self.assertIn("unknown", out.getvalue())
```

Also add `import os` to the test module's imports.

- [ ] **Step 2: Run to verify failure**, then **Step 3: Implement**

```python
# ── Confirmation ────────────────────────────────────────────────────────

def _confirm(question: str, assume_yes: bool) -> bool:
    """The trust gate: this command installs code into the user's editor,
    so the interactive path confirms and automation opts in explicitly."""
    if assume_yes:
        return True
    if not _interactive():
        raise VscodeError(
            "standard input is not a terminal — pass --yes to confirm "
            "non-interactively")
    return _ask(f"{question} [y/N] ").strip().lower() in ("y", "yes")


def _dotted(version: tuple[int, ...]) -> str:
    return ".".join(str(part) for part in version)


# ── Machine-half subcommands ────────────────────────────────────────────

def cmd_install(args) -> int:
    return _ensure(args, update_only=False)


def cmd_update(args) -> int:
    return _ensure(args, update_only=True)


def _ensure(args, update_only: bool) -> int:
    editor = pick_editor(discover_editors(), args.editor)
    installed = installed_version(editor)
    if update_only and installed is None:
        raise VscodeError(
            f"{EXTENSION_ID} is not installed in {editor.label} — run: "
            f"bunnyforge vscode install")
    release = latest_release()
    if installed == release.version:
        print(f"{EXTENSION_ID} {_dotted(installed)} is current in "
              f"{editor.label} — nothing to do")
        return 0
    if installed and installed > release.version:
        print(f"installed {_dotted(installed)} is newer than the latest "
              f"release {release.tag} — nothing to do")
        return 0
    vsix = obtain_vsix(release)
    print(f"about to install {EXTENSION_ID} {release.tag}")
    print(f"  from  https://github.com/{EXTENSION_REPO} (pinned source)")
    print(f"  file  {vsix}")
    print(f"  into  {editor.label} ({editor.path})")
    if not editor.supported:
        print("  note  only Visual Studio Code is tested; this editor is "
              "offered unsupported and may have bugs")
    if not _confirm("proceed?", args.yes):
        print("cancelled — nothing installed")
        return 1
    proc = _run([editor.path, "--install-extension", str(vsix), "--force"])
    if proc.returncode != 0:
        raise VscodeError(
            f"{editor.cli_id} --install-extension failed: "
            f"{proc.stderr.strip() or proc.returncode}")
    verb = "updated to" if installed else "installed at"
    print(f"{EXTENSION_ID} {verb} {release.tag} in {editor.label}")
    print("note: sideloaded extensions never auto-update — run "
          "`bunnyforge vscode update` when a release lands")
    return 0


def cmd_uninstall(args) -> int:
    editor = pick_editor(discover_editors(), args.editor)
    if installed_version(editor) is None:
        print(f"{EXTENSION_ID} is not installed in {editor.label} — "
              f"nothing to do")
        return 0
    if not _confirm(f"remove {EXTENSION_ID} from {editor.label}?", args.yes):
        print("cancelled")
        return 1
    proc = _run([editor.path, "--uninstall-extension", EXTENSION_ID])
    if proc.returncode != 0:
        raise VscodeError(
            f"{editor.cli_id} --uninstall-extension failed: "
            f"{proc.stderr.strip() or proc.returncode}")
    print(f"removed {EXTENSION_ID} from {editor.label}")
    return 0


def _has_extension(editor: Editor, extension_id: str) -> bool:
    proc = _run([editor.path, "--list-extensions"])
    return proc.returncode == 0 and extension_id in proc.stdout.split()


def cmd_status(args) -> int:
    # Machine half: unconditional (decision 5).
    editors = discover_editors()
    if not editors:
        print("editor         none found (searched PATH and known "
              "locations)")
    else:
        try:
            editor = pick_editor(editors, args.editor)
        except VscodeError:
            editor = editors[0]
        print(f"editor         {editor.label} ({editor.path})")
        installed = installed_version(editor)
        try:
            release = latest_release()
            available = f"{_dotted(release.version)} available"
        except VscodeError as exc:
            release = None
            available = f"latest unknown ({exc})"
        if installed is None:
            print(f"preview ext    not installed; {available}")
        elif release and installed < release.version:
            print(f"preview ext    {_dotted(installed)} installed; "
                  f"{available} — run: bunnyforge vscode update")
        else:
            print(f"preview ext    {_dotted(installed)} installed; "
                  f"{available}")
        if _has_extension(editor, HIGHLIGHT_ID):
            print("highlight ext  installed")
        else:
            print("highlight ext  not installed — source-view rules will "
                  "not render")
    # Workspace half: only when one is found; say plainly when not.
    try:
        root = _config.resolve_workspace(args.workspace).root
    except (_config.ConfigError, _workspace.WorkspaceError):
        print("workspace      none found — `on`/`off` need one")
        return 0
    print(f"workspace      {root}")
    path = root / SETTINGS_REL
    if not path.is_file():
        print(f"colouring      no {SETTINGS_REL} — `bunnyforge vscode on` "
              f"creates it")
        return 0
    lines = path.read_text(encoding="utf-8").split("\n")
    try:
        region = maybe_region(lines)
    except VscodeError:
        print("colouring      managed markers unbalanced — restore the "
              "marker pair by hand")
        return 0
    if region is None:
        print("colouring      no managed block — `bunnyforge vscode on` "
              "adds one")
    else:
        print(f"colouring      {region_state(lines, *region)}")
    if not any(l.strip().startswith('"markdown.preview.frontMatter"')
               for l in lines):
        print('frontMatter    not pinned — add '
              '"markdown.preview.frontMatter": "table" so the preview '
              'renders the table the extension decorates')
    return 0


# ── The front door ──────────────────────────────────────────────────────

def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bunnyforge vscode",
        description=(
            "Install the bunnyforge-visibility-preview extension and "
            "toggle the source-view colouring. Subcommands differ in what "
            "they need: install/update/uninstall act on this machine's "
            "editor and need no workspace; on/off edit the workspace's "
            ".vscode/settings.json and require one; status and setup "
            "cover the workspace half only when a workspace is found."))
    sub = parser.add_subparsers(dest="subcommand", required=True,
                                metavar="subcommand")

    def add(name, func, help_text, *, workspace=False, editor=True,
            yes=True, conflict=False):
        p = sub.add_parser(name, help=help_text)
        p.set_defaults(func=func)
        if workspace:
            p.add_argument("--workspace", metavar="PATH",
                           help="campaign workspace (default: search "
                                "upward from the current directory)")
        if editor:
            p.add_argument("--editor", metavar="CLI",
                           help="editor CLI to target: "
                                "code|code-insiders|codium|cursor "
                                "(only code is tested)")
        if yes:
            p.add_argument("--yes", action="store_true",
                           help="answer yes to every confirmation "
                                "(for automation)")
        if conflict:
            group = p.add_mutually_exclusive_group()
            group.add_argument("--adopt", action="store_true",
                               help="bring an existing highlight.regexes "
                                    "under management, content untouched")
            group.add_argument("--replace", action="store_true",
                               help="reset the managed block to the "
                                    "packaged rules, discarding tuning")
        return p

    add("status", cmd_status, "report both halves and their versions",
        workspace=True, yes=False)
    add("setup", cmd_setup, "install or update, then offer to turn "
        "colouring on", workspace=True, conflict=True)
    add("install", cmd_install, "install the preview extension into the "
        "editor")
    add("update", cmd_update, "update an installed preview extension")
    add("uninstall", cmd_uninstall, "remove the preview extension — the "
        "only real off for the preview half")
    add("on", cmd_on, "enable source-view colouring in the workspace",
        workspace=True, conflict=True)
    add("off", cmd_off, "disable source-view colouring in the workspace",
        workspace=True, editor=False, yes=False)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return args.func(args)
    except (VscodeError, _config.ConfigError,
            _workspace.WorkspaceError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        sys.stderr.close()
        raise SystemExit(0)
```

`cmd_setup`, `cmd_on`, `cmd_off` do not exist yet — add placeholders so the
module imports (they are Task 7's deliverable, TDD'd there):

```python
def cmd_setup(args) -> int:
    raise VscodeError("not implemented yet")  # Task 7


def cmd_on(args) -> int:
    raise VscodeError("not implemented yet")  # Task 7


def cmd_off(args) -> int:
    raise VscodeError("not implemented yet")  # Task 7
```

(Define them ABOVE `_parser`. These three placeholders are the one sanctioned
deviation from no-placeholders: the parser references the names, Task 7
replaces the bodies, and the suite stays green in between because no Task 6
test calls them.)

- [ ] **Step 4: Run to verify green, then commit**

Run: `python3 -m unittest tests.test_vscode -v` — Expected: PASS.

```bash
git add src/bunnyforge/vscode.py tests/test_vscode.py
git commit -m "feat: vscode status/install/update/uninstall and the front door (#33)"
```

---

### Task 7: `on`, `off`, and `setup`

**Files:**
- Modify: `src/bunnyforge/vscode.py` (replace the three placeholders; add
  helpers)
- Test: `tests/test_vscode.py`

**Interfaces:**
- Consumes: everything above.
- Produces: real `cmd_on`, `cmd_off`, `cmd_setup`;
  `_resolve_conflict(args) -> str` (`"adopt" | "replace" | "cancel"`);
  `_offer_highlight(args) -> None`;
  `_read_lines(path) -> list[str]`, `_write_lines(path, lines) -> None`,
  `_packaged_settings_lines() -> list[str]`.

- [ ] **Step 1: Write the failing tests**

```python
def _ws(case) -> Path:
    ws = Path(case.enterContext(tempfile.TemporaryDirectory())).resolve()
    (ws / "campaign.toml").write_text(
        '[campaign]\nnamespace = "probe"\n', encoding="utf-8")
    return ws


def _settings_of(ws: Path) -> list[str]:
    return (ws / ".vscode" / "settings.json").read_text("utf-8").split("\n")


class TestOnOff(unittest.TestCase):

    def _on(self, ws, *flags):
        with mock.patch.object(vscode, "_offer_highlight"), \
             contextlib.redirect_stdout(io.StringIO()) as out, \
             contextlib.redirect_stderr(io.StringIO()) as err:
            rc = vscode.main(["on", "--workspace", str(ws), *flags])
        return rc, out.getvalue(), err.getvalue()

    def test_on_creates_the_file_enabled_when_absent(self):
        ws = _ws(self)
        rc, _, _ = self._on(ws)
        self.assertEqual(rc, 0)
        lines = _settings_of(ws)
        begin, end = vscode.maybe_region(lines)
        self.assertEqual(vscode.region_state(lines, begin, end), "on")
        # strict JSON once comments drop — the whole point of the layout
        json.loads("\n".join(
            l for l in lines if not l.strip().startswith("//")))

    def test_on_enables_a_scaffolded_off_file(self):
        ws = _ws(self)
        (ws / ".vscode").mkdir()
        (ws / ".vscode" / "settings.json").write_bytes(
            init.packaged_bytes("vscode/settings.json"))
        rc, _, _ = self._on(ws)
        self.assertEqual(rc, 0)
        lines = _settings_of(ws)
        begin, end = vscode.maybe_region(lines)
        self.assertEqual(vscode.region_state(lines, begin, end), "on")

    def test_on_is_idempotent(self):
        ws = _ws(self)
        self._on(ws)
        before = _settings_of(ws)
        rc, out, _ = self._on(ws)
        self.assertEqual(rc, 0)
        self.assertIn("already on", out)
        self.assertEqual(_settings_of(ws), before)

    def test_on_replace_resets_hand_tuning(self):
        ws = _ws(self)
        self._on(ws)
        lines = _settings_of(ws)
        begin, _ = vscode.maybe_region(lines)
        # hand-tune a colour inside the region
        idx = next(i for i, l in enumerate(lines) if "#ff3333" in l)
        lines[idx] = lines[idx].replace("#ff3333", "#123456")
        (ws / ".vscode" / "settings.json").write_text(
            "\n".join(lines), encoding="utf-8")
        rc, _, _ = self._on(ws, "--replace")
        self.assertEqual(rc, 0)
        text = "\n".join(_settings_of(ws))
        self.assertNotIn("#123456", text)
        self.assertIn("#ff3333", text)

    def test_on_without_replace_preserves_hand_tuning(self):
        ws = _ws(self)
        self._on(ws)
        lines = _settings_of(ws)
        idx = next(i for i, l in enumerate(lines) if "#ff3333" in l)
        lines[idx] = lines[idx].replace("#ff3333", "#123456")
        (ws / ".vscode" / "settings.json").write_text(
            "\n".join(lines), encoding="utf-8")
        rc, _, _ = self._on(ws)   # already on; must not touch content
        self.assertEqual(rc, 0)
        self.assertIn("#123456", "\n".join(_settings_of(ws)))

    def test_off_disables_and_hints_at_uninstall(self):
        ws = _ws(self)
        self._on(ws)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = vscode.main(["off", "--workspace", str(ws)])
        self.assertEqual(rc, 0)
        lines = _settings_of(ws)
        begin, end = vscode.maybe_region(lines)
        self.assertEqual(vscode.region_state(lines, begin, end), "off")
        self.assertIn("bunnyforge vscode uninstall", out.getvalue())
        # the pin survives off — it belongs to the preview half
        self.assertIn('"markdown.preview.frontMatter": "table"',
                      "\n".join(lines))

    def test_off_with_no_file_is_a_named_error(self):
        ws = _ws(self)
        with contextlib.redirect_stderr(io.StringIO()) as err:
            rc = vscode.main(["off", "--workspace", str(ws)])
        self.assertEqual(rc, 1)
        self.assertIn("error: ", err.getvalue())

    def test_on_refuses_unbalanced_markers(self):
        ws = _ws(self)
        (ws / ".vscode").mkdir()
        broken = [l for l in init.packaged_bytes("vscode/settings.json")
                  .decode("utf-8").split("\n")
                  if l.strip() != vscode.MARKER_END]
        (ws / ".vscode" / "settings.json").write_text(
            "\n".join(broken), encoding="utf-8")
        rc, _, err = self._on(ws)
        self.assertEqual(rc, 1)
        self.assertIn("unbalanced", err)


class TestOnConflict(unittest.TestCase):
    """The duplicate-key hazard: a hand-rolled highlight.regexes outside
    any markers. Never append; ask, recommending adopt (decision 6)."""

    def _handrolled(self) -> Path:
        ws = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        (ws / "campaign.toml").write_text(
            '[campaign]\nnamespace = "probe"\n', encoding="utf-8")
        (ws / ".vscode").mkdir()
        (ws / ".vscode" / "settings.json").write_text(
            '{\n'
            '  // tuned by hand, years of care\n'
            '  "highlight.regexes": {\n'
            '    "^tuned$": { "regexFlags": "gm" }\n'
            '  },\n'
            '  "editor.rulers": [80]\n'
            '}\n', encoding="utf-8")
        return ws

    def _on(self, ws, *flags):
        with mock.patch.object(vscode, "_offer_highlight"), \
             contextlib.redirect_stdout(io.StringIO()) as out, \
             contextlib.redirect_stderr(io.StringIO()) as err:
            rc = vscode.main(["on", "--workspace", str(ws), *flags])
        return rc, out.getvalue(), err.getvalue()

    def test_no_tty_and_no_flag_fails_naming_both_flags(self):
        ws = self._handrolled()
        with mock.patch.object(vscode, "_interactive", return_value=False):
            rc, _, err = self._on(ws)
        self.assertEqual(rc, 1)
        self.assertIn("--adopt", err)
        self.assertIn("--replace", err)
        self.assertIn("tuned", (ws / ".vscode" / "settings.json")
                      .read_text("utf-8"))   # untouched

    def test_adopt_brackets_the_users_rules_untouched(self):
        ws = self._handrolled()
        rc, _, _ = self._on(ws, "--adopt")
        self.assertEqual(rc, 0)
        lines = _settings_of(ws)
        begin, end = vscode.maybe_region(lines)
        self.assertEqual(vscode.region_state(lines, begin, end), "on")
        self.assertIn("^tuned$", "\n".join(lines[begin:end]))
        self.assertIn("years of care", "\n".join(lines))   # comment kept

    def test_replace_discards_the_users_rules_for_packaged(self):
        ws = self._handrolled()
        rc, _, _ = self._on(ws, "--replace")
        self.assertEqual(rc, 0)
        text = "\n".join(_settings_of(ws))
        self.assertNotIn("^tuned$", text)
        self.assertIn("visibility:", text)
        self.assertIn('"editor.rulers": [80]', text)   # rest of file kept

    def test_interactive_cancel_changes_nothing_and_exits_nonzero(self):
        ws = self._handrolled()
        before = (ws / ".vscode" / "settings.json").read_text("utf-8")
        with mock.patch.object(vscode, "_interactive", return_value=True), \
             mock.patch.object(vscode, "_ask", return_value="c"):
            rc, _, _ = self._on(ws)
        self.assertEqual(rc, 1)
        self.assertEqual((ws / ".vscode" / "settings.json")
                         .read_text("utf-8"), before)


class TestOfferHighlight(unittest.TestCase):

    def test_on_offers_the_highlight_extension_when_missing(self):
        ws = _ws(self)
        editor = vscode.Editor("code", "Visual Studio Code", "/u/code", True)
        self.enterContext(mock.patch.object(
            vscode, "discover_editors", return_value=[editor]))
        run = self.enterContext(mock.patch.object(
            vscode, "_run", return_value=_proc("")))
        self.enterContext(mock.patch.object(
            vscode, "_interactive", return_value=True))
        self.enterContext(mock.patch.object(
            vscode, "_ask", return_value="y"))
        with contextlib.redirect_stdout(io.StringIO()):
            rc = vscode.main(["on", "--workspace", str(ws)])
        self.assertEqual(rc, 0)
        self.assertIn(
            ["/u/code", "--install-extension", vscode.HIGHLIGHT_ID],
            [c.args[0] for c in run.call_args_list])

    def test_non_interactive_on_prints_a_hint_instead(self):
        ws = _ws(self)
        editor = vscode.Editor("code", "Visual Studio Code", "/u/code", True)
        self.enterContext(mock.patch.object(
            vscode, "discover_editors", return_value=[editor]))
        run = self.enterContext(mock.patch.object(
            vscode, "_run", return_value=_proc("")))
        self.enterContext(mock.patch.object(
            vscode, "_interactive", return_value=False))
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = vscode.main(["on", "--workspace", str(ws)])
        self.assertEqual(rc, 0)               # the toggle itself succeeded
        self.assertIn(vscode.HIGHLIGHT_ID, out.getvalue())
        self.assertNotIn(
            ["/u/code", "--install-extension", vscode.HIGHLIGHT_ID],
            [c.args[0] for c in run.call_args_list])


class TestSetup(unittest.TestCase):

    def test_setup_installs_then_offers_on_in_a_workspace(self):
        ws = _ws(self)
        _machine_env(self)
        self.enterContext(mock.patch.object(
            vscode, "_offer_highlight"))
        with contextlib.redirect_stdout(io.StringIO()):
            rc = vscode.main(["setup", "--workspace", str(ws), "--yes"])
        self.assertEqual(rc, 0)
        self.assertTrue((ws / ".vscode" / "settings.json").is_file())

    def test_setup_without_a_workspace_still_installs(self):
        _machine_env(self)
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        env = {k: v for k, v in os.environ.items()
               if k != "BUNNYFORGE_WORKSPACE"}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(Path, "cwd", return_value=tmp), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            rc = vscode.main(["setup", "--yes"])
        self.assertEqual(rc, 0)
        self.assertIn("no campaign workspace", out.getvalue())
```

- [ ] **Step 2: Run to verify failure**, then **Step 3: Implement**

Replace the three placeholders with:

```python
# ── Workspace-half subcommands ──────────────────────────────────────────

def _read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").split("\n")


def _write_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _packaged_settings_lines() -> list[str]:
    return (init.packaged_bytes("vscode/settings.json")
            .decode("utf-8").split("\n"))


def _resolve_conflict(args) -> str:
    """Decision 6: an unmanaged highlight.regexes is never appended to and
    never overwritten unasked. Adopt is the recommendation: rules already
    in a workspace almost certainly came from this colour language, so
    what differs is more likely deliberate tuning than drift."""
    if args.adopt:
        return "adopt"
    if args.replace:
        return "replace"
    if not _interactive():
        raise VscodeError(
            f'{SETTINGS_REL} already defines "highlight.regexes" outside '
            f"the managed markers — pass --adopt to bring it under "
            f"management, content untouched (recommended), or --replace "
            f"to overwrite it with the packaged rules")
    print(f'{SETTINGS_REL} already defines "highlight.regexes" outside '
          f"the managed markers.")
    print("  [a] adopt (recommended) — bracket the existing rules with "
          "the markers, content untouched")
    print("  [r] replace — discard them and write the packaged rules")
    print("  [c] cancel — change nothing")
    answer = _ask("choice [a/r/c]: ").strip().lower()
    return {"a": "adopt", "r": "replace"}.get(answer, "cancel")


def _offer_highlight(args) -> None:
    """Decision 1: the rules are inert without the highlight extension,
    so detect and offer — but the toggle already succeeded, so nothing
    here may fail the command."""
    try:
        editor = pick_editor(discover_editors(), args.editor)
    except VscodeError as exc:
        print(f"note: {exc}")
        print(f"note: the rules render only once {HIGHLIGHT_ID} is "
              f"installed")
        return
    if _has_extension(editor, HIGHLIGHT_ID):
        return
    if not args.yes and not _interactive():
        print(f"note: {HIGHLIGHT_ID} is not installed in {editor.label}; "
              f"the rules render only once it is — install it with: "
              f"{editor.cli_id} --install-extension {HIGHLIGHT_ID}")
        return
    if not _confirm(f"install {HIGHLIGHT_ID} into {editor.label} "
                    f"(it renders these rules)?", args.yes):
        return
    proc = _run([editor.path, "--install-extension", HIGHLIGHT_ID])
    if proc.returncode != 0:
        raise VscodeError(
            f"{editor.cli_id} --install-extension {HIGHLIGHT_ID} failed: "
            f"{proc.stderr.strip() or proc.returncode}")
    print(f"installed {HIGHLIGHT_ID} (newest release) into {editor.label}")


def cmd_on(args) -> int:
    root = _config.resolve_workspace(args.workspace).root
    path = root / SETTINGS_REL
    if not path.is_file():
        # Decision 4's easy case: absent — write the packaged file (the
        # scaffold and this path can never drift apart) and enable it.
        lines = _packaged_settings_lines()
        begin, end = maybe_region(lines)
        _write_lines(path, enable_region(lines, begin, end))
        print(f"created {SETTINGS_REL} with source-view colouring on")
    else:
        lines = _read_lines(path)
        region = maybe_region(lines)          # raises on unbalanced
        if region is None:
            key = find_unmanaged_key(lines, None)
            if key is None:
                lines = splice_region(lines)
            else:
                choice = _resolve_conflict(args)
                if choice == "cancel":
                    print("cancelled — nothing written")
                    return 1
                if choice == "adopt":
                    lines = adopt_key(lines, key)
                else:
                    end_idx = key_span(lines, key)
                    lines = splice_region(lines[:key]
                                          + lines[end_idx + 1:])
            begin, end = maybe_region(lines)
            _write_lines(path, enable_region(lines, begin, end))
            print(f"source-view colouring on ({SETTINGS_REL})")
        elif args.replace:
            # The region-level reset: packaged rules, enabled — the one
            # deliberate way local tuning is discarded.
            lines = replace_region(lines, *region)
            begin, end = maybe_region(lines)
            _write_lines(path, enable_region(lines, begin, end))
            print("managed block reset to the packaged rules and enabled")
        else:
            state = region_state(lines, *region)
            if state == "on":
                print("source-view colouring is already on")
            elif state == "empty":
                raise VscodeError(
                    "the managed block has nothing to enable — re-run "
                    "with --replace to restore the packaged rules")
            else:
                _write_lines(path, enable_region(lines, *region))
                print(f"source-view colouring on ({SETTINGS_REL})")
    _offer_highlight(args)
    return 0


def cmd_off(args) -> int:
    root = _config.resolve_workspace(args.workspace).root
    path = root / SETTINGS_REL
    if not path.is_file():
        raise VscodeError(
            f"no {SETTINGS_REL} in this workspace — nothing to turn off")
    lines = _read_lines(path)
    region = maybe_region(lines)
    if region is None:
        raise VscodeError(
            f"no managed block in {SETTINGS_REL} — nothing this tool "
            f"turned on; if colouring is enabled outside bunnyforge's "
            f"markers, edit the file by hand (or run `bunnyforge vscode "
            f"on` first to bring it under management)")
    if region_state(lines, *region) == "off":
        print("source-view colouring is already off")
    else:
        _write_lines(path, disable_region(lines, *region))
        print(f"source-view colouring off ({SETTINGS_REL})")
    # Toggling the setting is what was asked; uninstalling is a bigger
    # action reached for deliberately, so hint rather than infer.
    print("the markdown-preview half is a separate extension — to remove "
          "it too: bunnyforge vscode uninstall")
    return 0


def cmd_setup(args) -> int:
    rc = _ensure(args, update_only=False)
    if rc != 0:
        return rc
    try:
        _config.resolve_workspace(args.workspace)
    except (_config.ConfigError, _workspace.WorkspaceError):
        print("no campaign workspace here — run `bunnyforge vscode on` "
              "inside one to enable source-view colouring")
        return 0
    if not args.yes and not _interactive():
        print("hint: `bunnyforge vscode on` enables source-view "
              "colouring in this workspace")
        return 0
    if _confirm("turn source-view colouring on in this workspace?",
                args.yes):
        return cmd_on(args)
    return 0
```

Delete the three placeholder definitions.

- [ ] **Step 4: Run to verify green, then commit**

Run: `python3 -m unittest tests.test_vscode -v` — Expected: PASS (all tasks').

```bash
git add src/bunnyforge/vscode.py tests/test_vscode.py
git commit -m "feat: vscode on/off/setup with adopt-replace-cancel (#33)"
```

---

### Task 8: Wire into the CLI; name the command in the scaffold; README

**Files:**
- Modify: `src/bunnyforge/cli.py` (import, `_COMMANDS`, `_SUMMARIES`)
- Modify: `tests/test_cli.py` (the exact-dict assertion)
- Modify: `src/bunnyforge/init.py` (the Optional line)
- Modify: `src/bunnyforge/data/vscode/settings.json` (header prose only)
- Modify: `src/bunnyforge/data/vscode/extensions.json` (comment prose only)
- Modify: `tests/test_init.py` (the Optional-line test)
- Modify: `README.md`

**Interfaces:**
- Consumes: `vscode.main`. #34 deliberately shipped command-neutral wording;
  this task is where the command gets named, everywhere at once.

- [ ] **Step 1: Update the failing dispatcher test first**

In `tests/test_cli.py`: add `vscode` to the `from bunnyforge import (…)`
list and add `"vscode": vscode.main,` to the expected dict in
`test_every_subcommand_maps_to_its_modules_main` (after `"names"`, before
`"test"`, mirroring the table order below).

Run: `python3 -m unittest tests.test_cli.TestDispatchTable -v`
Expected: FAIL — cli does not know `vscode` yet.

- [ ] **Step 2: Wire `cli.py`**

Add `vscode` to `cli.py`'s `from bunnyforge import (…)` import list. In
`_COMMANDS`, after `"names"`: `"vscode": vscode.main,`. In `_SUMMARIES`:
`"vscode": "install the preview extension and toggle editor colouring",`.

Run: `python3 -m unittest tests.test_cli -v` — Expected: PASS.

- [ ] **Step 3: Name the command in init's output**

In `src/bunnyforge/init.py` replace the #34 line:

```python
    print("Optional: VS Code colouring by visibility ships off — "
          "run 'bunnyforge vscode setup'.")
```

In `tests/test_init.py`, `test_points_at_the_inert_vscode_scaffold_once`
becomes:

```python
    def test_points_at_the_vscode_command_once(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(
                init.main([str(tmp / "new"), "--name", "X"]), 0)
        pointing = [l for l in out.getvalue().splitlines()
                    if "bunnyforge vscode" in l]
        self.assertEqual(len(pointing), 1, out.getvalue())
```

- [ ] **Step 4: Name the command in the two data files (prose only)**

In `data/vscode/settings.json`, change only the header sentence
`// on, delete every "//- " prefix. ACTIVE LEVEL: high; to` (and its
neighbours) so the paragraph reads:

```jsonc
  // reserved for the toggle; ordinary comments use plain "//". Turn
  // colouring on with `bunnyforge vscode on` (or delete every "//- "
  // prefix by hand); `bunnyforge vscode off` re-disables it. ACTIVE
  // LEVEL: high; to switch, re-disable the high block and enable one
  // alternate below.
```

In `data/vscode/extensions.json`, change
`// Install it from its GitHub releases instead —` to
`// Install it with \`bunnyforge vscode setup\`, or by hand —`.

Do **not** touch marker lines, `//- ` lines, or any live JSON — the
contract tests prove it: run
`python3 -m unittest tests.test_init.TestVscodeScaffold tests.test_vscode.TestPackagedContract -v`
Expected: PASS unchanged.

- [ ] **Step 5: README section**

Add to `README.md`, after the existing command documentation:

```markdown
## VS Code integration

`bunnyforge init` scaffolds `.vscode/settings.json` and
`.vscode/extensions.json` with a visibility colour language for the editor —
every `.md` file coloured by its front-matter `visibility`, the `## GM notes`
boundary marked. It ships off; `bunnyforge vscode` manages it:

    bunnyforge vscode status      # both halves: installed, available, on/off
    bunnyforge vscode setup       # install/update, then offer to enable
    bunnyforge vscode on|off      # toggle the source-view block
    bunnyforge vscode install|update|uninstall   # the preview extension

The source-view half is rendered by the Marketplace extension
`fabiospampinato.vscode-highlight`. The markdown-preview half,
[`dcltdw.bunnyforge-visibility-preview`](https://github.com/dcltdw/bunnyforge-visibility-preview),
is not on the Marketplace; it sideloads as a `.vsix` from GitHub releases,
and sideloaded extensions never auto-update — `bunnyforge vscode update`
checks the release feed. Only Visual Studio Code is tested; VS Code
Insiders, VSCodium and Cursor are offered but unsupported. `on`/`off`
rewrite only the marked managed block in `.vscode/settings.json`; the rest
of the file — including its comments — is yours.
```

- [ ] **Step 6: Run everything, then commit**

Run: `python3 -m unittest discover -s tests -t . -v` — Expected: PASS.

```bash
git add src/bunnyforge/cli.py src/bunnyforge/init.py \
        src/bunnyforge/data/vscode/ tests/ README.md
git commit -m "feat: wire bunnyforge vscode into the CLI and name it in the scaffold (#33)"
```

---

### Task 9: Verification and PR

- [ ] **Step 1: Full suite, fresh**

Run: `python3 -m unittest discover -s tests -t . -v`
Expected: PASS, portability checks included. Report real counts.

- [ ] **Step 2: End-to-end smoke against the real release (network, no install)**

```bash
python3 -m bunnyforge.vscode status || true
```
Expected: machine-half lines print; available version resolves to the real
v0.1.0 release (or a clean "latest unknown" line if offline). This is the
one deliberate live-network check; it installs nothing.

- [ ] **Step 3: Help surfaces**

```bash
python3 -m bunnyforge --help          # lists vscode with its summary
python3 -m bunnyforge vscode --help   # per-subcommand workspace sentence
```

- [ ] **Step 4: Push and open the PR**

```bash
git push -u origin feat/33-vscode-command
```

PR **based on `main`** (state this explicitly). Title: `Add bunnyforge
vscode: install/update the preview extension, toggle colouring (#33)`.
Body per AGENTS.md: **Files changed** (`src/bunnyforge/vscode.py` new;
`tests/test_vscode.py` new; `cli.py`, `init.py`, both `data/vscode/*.json`,
`tests/test_cli.py`, `tests/test_init.py`, `README.md` modified; this plan
new), **Work breakdown** (region engine / trust path / per-subcommand
workspace rules / the settled decisions honoured), **Test expectations**
(none expected to fail), **Provenance** (`Agent:`, `Model / version:`).

Then **stop and wait for review** — do not merge.

## Out of scope (resist)

- Touching existing workspaces' `extensions.json`, or adding the
  `frontMatter` pin to a pre-existing settings file (`status` advises
  instead — approved design call).
- Windows/Linux app-bundle path tables (PATH covers them; macOS is the
  exception and is covered).
- Any second managed region; #32's doctrine-adopt problem.
- Marketplace publication, Open VSX, auto-update.
- Version bump/release timing — the maintainer's call.
