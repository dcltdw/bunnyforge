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
    """Insert the packaged managed region as the object's FIRST member.

    Region-first is the contract's own placement (#34 item 3): the packaged
    region ends `//- },` because a member follows it there, so splicing it
    last would leave a trailing comma and invalid JSON. Comma normalisation
    either side of the region is the one sanctioned edit outside the markers,
    and it happens only here, at creation.
    """
    opens = next((i for i, l in enumerate(lines)
                  if l.strip().endswith("{")), None)
    close = next((i for i in range(len(lines) - 1, -1, -1)
                  if lines[i].strip() == "}"), None)
    if opens is None or close is None or close <= opens:
        raise VscodeError(
            f"{SETTINGS_REL} is not a settings object this tool can edit "
            f"(no opening or closing brace on a line of its own) — fix or "
            f"remove the file, then re-run")
    region = packaged_region_lines()
    out = lines[:opens + 1] + region + lines[opens + 1:]
    region_end = opens + len(region)
    close += len(region)
    following = [i for i in range(region_end + 1, close)
                 if out[i].strip() and not out[i].strip().startswith("//")]
    if following:
        last = following[-1]
        if out[last].rstrip().endswith(","):
            out[last] = out[last].rstrip()[:-1]
    else:
        for i in range(region_end - 1, opens, -1):
            indent, body = _split_indent(out[i])
            if body.startswith(OFF_PREFIX) and body.rstrip().endswith(","):
                out[i] = indent + body.rstrip()[:-1]
                break
    return out


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
