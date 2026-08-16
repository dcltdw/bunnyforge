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
import tempfile
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

def _is_live(line: str) -> bool:
    """A line carrying JSON the parser sees — not blank, not a comment."""
    body = line.strip()
    return bool(body) and not body.startswith("//")


def _drop_comma(line: str) -> str:
    """The same line without its trailing comma, indent, OFF_PREFIX and
    any line-ending kept exactly as they were."""
    indent, body = _split_indent(line)
    prefix = ""
    if body.startswith(OFF_PREFIX):
        prefix, body = OFF_PREFIX, body[len(OFF_PREFIX):]
    stripped = body.rstrip()
    if stripped.endswith(","):
        body = stripped[:-1] + body[len(stripped):]
    return indent + prefix + body


def _last_member_line(lines: list[str], begin: int, end: int) -> int | None:
    """The region's last line that is a JSON member in SOME toggle state —
    live or OFF_PREFIX-disabled. Plain `//` prose (the alternates) is not a
    member and never carries the region's separator."""
    for i in range(end - 1, begin, -1):
        body = lines[i].strip()
        if body.startswith(OFF_PREFIX) or _is_live(lines[i]):
            return i
    return None


def _object_bounds(lines: list[str]) -> tuple[int, int] | None:
    """(opening, closing) line indices of the settings object, or None.

    The opener is the first NON-COMMENT line ending in `{`: a file headed
    by a `// {`-shaped comment would otherwise have the region spliced
    outside the object entirely.
    """
    opens = next((i for i, l in enumerate(lines)
                  if _is_live(l) and l.strip().endswith("{")), None)
    close = next((i for i in range(len(lines) - 1, -1, -1)
                  if lines[i].strip() == "}"), None)
    if opens is None or close is None or close <= opens:
        return None
    return opens, close


def normalise_commas(lines: list[str]) -> list[str]:
    """Repair the commas either side of the managed region so the file is
    valid JSON in BOTH toggle states — the one sanctioned edit outside the
    markers, made only by the structural edits, never by the toggle.

    The region's separator has to live INSIDE the markers, because a comma
    outside them is a separator in one state and a dangling comma in the
    other. Region-first (splice's placement) gets that for free: the
    region's last member line carries the trailing comma, commented out
    along with everything else when `off` runs. A region that ends up LAST
    instead — `adopt` of a last-member key — needs the mirror image: the
    member before it gives up the comma it can no longer justify once the
    region is commented out, and the separator moves inside the markers on
    a line of its own.
    """
    region = maybe_region(lines)
    bounds = _object_bounds(lines)
    if region is None or bounds is None:
        return lines
    begin, end = region
    opens, close = bounds
    if not opens < begin or not end < close:
        return lines
    out = list(lines)
    following = [i for i in range(end + 1, close) if _is_live(out[i])]
    if following:
        out[following[-1]] = _drop_comma(out[following[-1]])
        return out
    last = _last_member_line(out, begin, end)
    if last is not None:
        out[last] = _drop_comma(out[last])
    preceding = [i for i in range(opens + 1, begin) if _is_live(out[i])]
    if preceding:
        out[preceding[-1]] = _drop_comma(out[preceding[-1]])
        indent = _split_indent(out[begin])[0]
        off = region_state(out, begin, end) == "off"
        separator = indent + (OFF_PREFIX if off else "") + ","
        out.insert(begin + 1, _with_endings_of([separator], out)[0])
    return out


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


def _with_endings_of(new: list[str], model: list[str]) -> list[str]:
    """`new` lines given the line ending `model` uses. Lines read with
    newline="" keep their own terminator, so inserting package lines (LF)
    into a CRLF file would leave it half-translated."""
    if not any(l.endswith("\r") for l in model):
        return new
    return [l if l.endswith("\r") else l + "\r" for l in new]


def packaged_region_lines() -> list[str]:
    lines = (init.packaged_bytes("vscode/settings.json")
             .decode("utf-8").split("\n"))
    begin, end = maybe_region(lines)  # never None: the drift test pins it
    return lines[begin:end + 1]


def splice_region(lines: list[str]) -> list[str]:
    """Insert the packaged managed region as the object's FIRST member.

    Region-first is the contract's own placement (#34 item 3): the packaged
    region ends `//- },` because a member follows it there, so splicing it
    last would leave a trailing comma and invalid JSON. `normalise_commas`
    then repairs the joins either side of it.
    """
    bounds = _object_bounds(lines)
    if bounds is None:
        raise VscodeError(
            f"{SETTINGS_REL} is not a settings object this tool can edit "
            f"(no opening or closing brace on a line of its own) — fix or "
            f"remove the file, then re-run")
    opens, _ = bounds
    region = _with_endings_of(packaged_region_lines(), lines)
    return normalise_commas(lines[:opens + 1] + region + lines[opens + 1:])


def adopt_key(lines: list[str], key_idx: int) -> list[str]:
    """Bracket the existing rules with the markers, content untouched —
    the minimum span, key line through its closing brace. Nearby
    commented-out blocks stay outside: they are comments, and `off` never
    needs to touch them. Only the commas either side are normalised —
    without that, adopting the object's LAST member leaves the member
    before it with a comma that dangles as soon as `off` runs."""
    end = key_span(lines, key_idx)
    indent = _split_indent(lines[key_idx])[0]
    begin_line, end_line = _with_endings_of(
        [indent + MARKER_BEGIN, indent + MARKER_END], lines)
    out = list(lines)
    out.insert(end + 1, end_line)
    out.insert(key_idx, begin_line)
    return normalise_commas(out)


def replace_region(lines: list[str], begin: int, end: int) -> list[str]:
    """The packaged region in place of the current one, commas normalised:
    the packaged region ends `//- },`, which is a dangling comma when the
    region is the object's last (or only) member."""
    region = _with_endings_of(packaged_region_lines(), lines)
    return normalise_commas(lines[:begin] + region + lines[end + 1:])


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


def pick_editor(editors: list[Editor], wanted: str | None, *,
                prompt: bool = True) -> Editor:
    """The editor to act on. `prompt=False` is for read-only callers
    (status): resolve stable-else-first and never ask — "install into"
    is both a block and a lie in a command that installs nothing."""
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
    if not prompt:
        return stable or editors[0]
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
            editor = pick_editor(editors, args.editor, prompt=False)
        except VscodeError as exc:
            # An unmatched --editor must not silently become a report
            # about a different editor.
            editor = editors[0]
            print(f"note           {exc}; reporting on {editor.cli_id}")
        print(f"editor         {editor.label} ({editor.path})")
        try:
            installed = installed_version(editor)
            installed_error = None
        except VscodeError as exc:
            installed = None
            installed_error = exc
        try:
            release = latest_release()
            available = f"{_dotted(release.version)} available"
        except VscodeError as exc:
            release = None
            available = f"latest unknown ({exc})"
        if installed_error is not None:
            print(f"preview ext    unknown ({installed_error}); {available}")
        elif installed is None:
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


# ── Workspace-half subcommands ──────────────────────────────────────────

def _read_lines(path: Path) -> list[str]:
    # newline="" keeps the file's own line endings inside the strings.
    # Translating them would rewrite every line of a file this tool
    # promises to touch only between the markers.
    with path.open("r", encoding="utf-8", newline="") as handle:
        return handle.read().split("\n")


def _write_lines(path: Path, lines: list[str]) -> None:
    """Write through a temp file in the SAME directory, then os.replace.

    A truncating write that dies partway — full disk, SIGINT, crash —
    would leave the user's hand-edited, hand-commented settings.json
    empty, and there is no backup. os.replace is atomic only within one
    filesystem, hence the sibling temp file rather than /tmp.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent,
                                prefix=path.name + ".", suffix=".tmp")
    tmp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write("\n".join(lines))
        # mkstemp is 0600; the file the user had (or a plain new one)
        # should not silently change mode.
        if path.exists():
            shutil.copymode(path, tmp)
        else:
            tmp.chmod(0o644)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


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
        # A note, not an error: the toggle is already on disk, and failing
        # the command here would report the write as unsuccessful.
        print(f"note: {editor.cli_id} --install-extension {HIGHLIGHT_ID} "
              f"failed: {proc.stderr.strip() or proc.returncode}")
        print(f"note: the rules render only once {HIGHLIGHT_ID} is "
              f"installed")
        return
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
