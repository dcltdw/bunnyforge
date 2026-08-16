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
