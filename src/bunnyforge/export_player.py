#!/usr/bin/env python3
"""
export_player.py — write player-safe copies of content files to Export/.

Direction: workspace -> Export/. This script never writes anywhere else and
never modifies workspace content; Export/ is disposable, generated output
(gitignored — see .gitignore) and safe to delete and regenerate at any time.

Visibility rules (see AGENTS.md -> Player visibility):

- `gm-only` files are skipped entirely — not exported in any form, not even
  their filename appears in Export/.
- `player-visible` files are exported with the standard GM meta-sections
  (## Design intent, ## Balance notes, ## Playtest log) removed, wherever in
  the heading hierarchy they occur.
- `mixed` files are split on the `## GM notes` separator (via
  _common.player_facing); only the portion above the separator is exported,
  then the same meta-section stripping is applied to it. A `mixed` file that
  lacks the separator cannot be split safely and is therefore skipped
  entirely, the same as gm-only — see the note on render_export() below.
- Unknown or invalid `visibility` fails safe to `gm-only` (handled by
  _common.normalize_visibility) and is skipped.

HTML comments (`<!-- ... -->`) are stripped from every exported file — they
are GM scratch space regardless of visibility.

Usage:
    python3 -m bunnyforge.export_player
    python3 -m bunnyforge.export_player --workspace /path/to/campaign
"""

from __future__ import annotations

import argparse
import re
import string
import sys
from collections import namedtuple
from pathlib import Path

from bunnyforge._common import (
    FileRec,
    iter_content_files,
    normalize_visibility,
    player_facing,
)
from bunnyforge._config import ConfigError, Workspace, resolve_workspace
from bunnyforge._workspace import WorkspaceError

# The standard GM-only meta-sections. Matched case-insensitively against a
# heading's text with trailing punctuation/whitespace stripped, so
# "## Design intent", "## Design Intent:", "##   design intent  " all match.
GM_SECTION_NAMES = {"design intent", "balance notes", "playtest log"}

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_TRIM_CHARS = string.punctuation + string.whitespace


def _normalize_heading(text: str) -> str:
    return text.strip().rstrip(_TRIM_CHARS).lower()


def strip_gm_sections(body: str) -> tuple[str, int]:
    """Drop each GM meta-section, heading-level aware.

    A matched heading (e.g. "## Design intent") is dropped along with every
    line until the next heading whose level is the same or shallower (e.g.
    the next `##` or `#`, but not a nested `###` sub-heading, which is
    dropped too as part of the section it belongs to).

    Returns (stripped_body, number_of_sections_dropped).
    """
    lines = body.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    n = len(lines)
    dropped = 0

    while i < n:
        m = _HEADING_RE.match(lines[i].rstrip("\n"))
        if m and _normalize_heading(m.group(2)) in GM_SECTION_NAMES:
            level = len(m.group(1))
            dropped += 1
            i += 1
            while i < n:
                m2 = _HEADING_RE.match(lines[i].rstrip("\n"))
                if m2 and len(m2.group(1)) <= level:
                    break
                i += 1
            continue
        out.append(lines[i])
        i += 1

    return "".join(out), dropped


def strip_html_comments(text: str) -> str:
    return _HTML_COMMENT_RE.sub("", text)


RenderResult = namedtuple("RenderResult", "body sections_stripped skip_reason")
# skip_reason is None when body is exportable; otherwise "gm-only" or
# "mixed-no-separator".


def render_export(rec: FileRec) -> RenderResult:
    """Compute the player-safe body for one content file, or a skip reason.

    Order of application follows the spec: resolve visibility first (fail
    safe to gm-only), then split mixed files on the GM-notes separator, then
    strip the standard meta-sections, then strip HTML comments.
    """
    vis = normalize_visibility(rec.fm)
    if vis == "gm-only":
        return RenderResult(None, 0, "gm-only")

    body = rec.body
    if vis == "mixed":
        facing = player_facing(body)
        if facing is None:
            # A `mixed` file without the `## GM notes` separator cannot be
            # split safely — there is no way to tell where the GM half
            # begins. Fail safe: export nothing, the same as gm-only,
            # rather than guess or fall back to the whole body.
            return RenderResult(None, 0, "mixed-no-separator")
        body = facing

    body, dropped = strip_gm_sections(body)
    body = strip_html_comments(body)
    return RenderResult(body, dropped, None)


ExportResult = namedtuple(
    "ExportResult", "exported skipped_gm_only skipped_unsplittable sections_stripped")


def run_export(ws: Workspace, out_dir: Path) -> tuple[ExportResult, list[str]]:
    """Export every eligible content file under workspace into out_dir.

    Returns (ExportResult, log_lines) — log_lines is plain text, one line per
    file, suitable for printing to stdout/stderr by the caller.
    """
    workspace = ws.root
    exported = skipped_gm_only = skipped_unsplittable = sections_stripped = 0
    log: list[str] = []

    for rec in iter_content_files(ws):
        rel = rec.path.relative_to(workspace).as_posix()
        result = render_export(rec)

        if result.skip_reason == "gm-only":
            skipped_gm_only += 1
            log.append(f"  skip      {rel}  (gm-only)")
            continue

        if result.skip_reason == "mixed-no-separator":
            skipped_unsplittable += 1
            log.append(
                f"  REFUSED   {rel}  (mixed, no GM-notes separator — cannot split safely)")
            continue

        dest = out_dir / rec.path.relative_to(workspace)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(result.body, encoding="utf-8")
        exported += 1
        sections_stripped += result.sections_stripped
        log.append(f"  exported  {rel}  ({result.sections_stripped} section(s) stripped)")

    return (
        ExportResult(exported, skipped_gm_only, skipped_unsplittable, sections_stripped),
        log,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bunnyforge export-player",
        description="Write player-safe copies of content files to Export/.")
    parser.add_argument(
        "--workspace", metavar="PATH",
        help="Campaign workspace root (default: $BUNNYFORGE_WORKSPACE, else "
             "the nearest campaign.toml above the current directory)")
    args = parser.parse_args(argv)

    try:
        ws = resolve_workspace(args.workspace)
    except (WorkspaceError, ConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    result, log = run_export(ws, ws.root / "Export")

    for line in log:
        if "REFUSED" in line:
            print(line, file=sys.stderr)
        else:
            print(line)

    print(
        f"\n{result.exported} exported, {result.skipped_gm_only} skipped (gm-only), "
        f"{result.skipped_unsplittable} skipped (mixed, no separator), "
        f"{result.sections_stripped} GM section(s) stripped."
    )

    if result.skipped_unsplittable:
        print(
            f"\n{result.skipped_unsplittable} mixed file(s) refused; add the `## GM notes` "
            "separator and re-run.",
            file=sys.stderr,
        )

    return 1 if result.skipped_unsplittable else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        sys.stderr.close()
        raise SystemExit(0)
