#!/usr/bin/env python3
"""
import_perceptions.py — one-way export of player-authored DokuWiki pages into
Perceptions/.

Direction: wiki -> workspace. This script never writes to the wiki.

Player pages are a record of what the players BELIEVED at a point in time. They
are not canon and must never be edited here; correcting them destroys the only
thing they are good for. Every file written by this script carries
`canon: perception` in its front matter.

Reads DokuWiki's flat files directly rather than the API, because DokuWiki keeps
every historical revision in data/attic/ as `page.<unixtime>.txt.gz`. That gives
exact session-boundary snapshots for free.

Usage:
    python3 -m bunnyforge.import_perceptions --wiki-data /path/to/dokuwiki/data
    python3 -m bunnyforge.import_perceptions --wiki-data ... --namespace party
    python3 -m bunnyforge.import_perceptions --wiki-data ... --as-of 2026-03-14
    python3 -m bunnyforge.import_perceptions --wiki-data ... --dry-run
    python3 -m bunnyforge.import_perceptions --wiki-data ... --workspace /path/to/campaign
"""

from __future__ import annotations

import argparse
import gzip
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from bunnyforge._config import ConfigError, resolve_workspace
from bunnyforge._workspace import WorkspaceError


# ---------------------------------------------------------------------------
# DokuWiki markup -> Markdown
# ---------------------------------------------------------------------------
# Deliberately conservative. Anything not recognised is passed through
# unchanged rather than mangled; a stray bit of wiki syntax in the output is
# a much smaller problem than silently dropped content.

def convert_markup(text: str) -> str:
    out = []
    in_code = False

    for line in text.splitlines():
        m = re.match(r"^\s*(</?)(?:code|file)\b", line)
        if m:
            # An opening tag enters the block, a closing tag leaves it. The
            # previous form tested for the absence of "/" anywhere on the
            # line, so "</code>" never cleared the flag and every line after
            # the first code block was passed through unconverted.
            in_code = m.group(1) == "<"
            out.append(line)
            continue
        if in_code:
            out.append(line)
            continue

        # Headings: DokuWiki inverts the scale, ====== is h1.
        m = re.match(r"^\s*(={2,6})\s*(.*?)\s*\1\s*$", line)
        if m:
            level = 7 - len(m.group(1))
            out.append(f"{'#' * level} {m.group(2)}")
            continue

        line = re.sub(r"\*\*(.+?)\*\*", r"**\1**", line)
        line = re.sub(r"(?<!:)//(.+?)//", r"*\1*", line)
        line = re.sub(r"__(.+?)__", r"\1", line)
        line = re.sub(r"''(.+?)''", r"`\1`", line)
        line = re.sub(r"<del>(.+?)</del>", r"~~\1~~", line)

        # Lists: DokuWiki uses two spaces per level.
        m = re.match(r"^(\s+)([*-])\s+(.*)$", line)
        if m:
            depth = len(m.group(1)) // 2
            bullet = "-" if m.group(2) == "*" else "1."
            line = f"{'  ' * max(depth - 1, 0)}{bullet} {m.group(3)}"

        # Links: [[target|label]] and [[target]]
        line = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"[\2](\1)", line)
        line = re.sub(r"\[\[([^\]|]+)\]\]", r"[\1](\1)", line)

        line = re.sub(r"\\\\\s*$", "  ", line)
        out.append(line)

    return "\n".join(out)


# ---------------------------------------------------------------------------
# Revision selection
# ---------------------------------------------------------------------------

def attic_revisions(attic_root: Path, page_id: str) -> list[tuple[int, Path]]:
    """All archived revisions of a page, oldest first."""
    rel = Path(*page_id.split(":"))
    pattern = f"{rel.name}.*.txt.gz"
    directory = attic_root / rel.parent
    if not directory.is_dir():
        return []

    revs = []
    for path in directory.glob(pattern):
        m = re.match(rf"^{re.escape(rel.name)}\.(\d+)\.txt\.gz$", path.name)
        if m:
            revs.append((int(m.group(1)), path))
    return sorted(revs)


def read_page(pages_root: Path, attic_root: Path, page_id: str, as_of: int | None) -> tuple[str, int] | None:
    """Return (text, mtime) for a page, at `as_of` if given, else current."""
    rel = Path(*page_id.split(":")).with_suffix(".txt")
    current = pages_root / rel

    if as_of is None:
        if not current.is_file():
            return None
        return current.read_text(encoding="utf-8", errors="replace"), int(current.stat().st_mtime)

    candidates = [(ts, p) for ts, p in attic_revisions(attic_root, page_id) if ts <= as_of]
    if candidates:
        ts, path = candidates[-1]
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
            return fh.read(), ts

    # No archived revision that old; fall back to current only if it predates as_of.
    if current.is_file() and int(current.stat().st_mtime) <= as_of:
        return current.read_text(encoding="utf-8", errors="replace"), int(current.stat().st_mtime)
    return None


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def slugify(page_id: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", page_id.replace(":", "-").lower()).strip("-")


def first_heading(text: str) -> str | None:
    m = re.search(r"^\s*={2,6}\s*(.+?)\s*={2,6}\s*$", text, re.MULTILINE)
    return m.group(1).strip() if m else None


def build_file(page_id: str, raw: str, mtime: int, as_of_label: str | None) -> str:
    title = first_heading(raw) or page_id.split(":")[-1].replace("_", " ").title()
    captured = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%d")
    body = convert_markup(raw)

    summary = (
        f"Player-authored wiki page '{title}' as of {captured}. This records what "
        f"the players believed, not what is true. Source page: {page_id}."
    )

    fm = [
        "---",
        "type: perception",
        f"title: {title}",
        "aliases: []",
        "status: active",
        "canon: perception",
        "tags: []",
        f"updated: {captured}",
        f"summary: >-\n  {summary}",
        f"source_page: {page_id}",
        f"captured: {captured}",
        f"author: players",
    ]
    if as_of_label:
        fm.append(f"as_of: {as_of_label}")
    fm.append("---")

    notice = (
        "<!-- PLAYER-AUTHORED. NOT CANON. NOT GM MATERIAL.\n"
        "     This file records what the players believed at the time of writing.\n"
        "     It may be wrong, incomplete, or deliberately misdirected. Do not treat\n"
        "     any statement here as established fact, and do not use it to resolve a\n"
        "     question about what is actually true — check the GM canon files instead.\n"
        "     It is useful for exactly one thing: knowing what the party thinks.\n"
        "\n"
        "     DO NOT EDIT. This file is regenerated from the wiki. Corrections made\n"
        "     here will be lost, and correcting a player's belief destroys the record\n"
        "     of what they believed. -->\n"
    )

    return "\n".join(fm) + "\n" + notice + "\n" + body.rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bunnyforge import-perceptions",
        description="Export player-authored DokuWiki pages into Perceptions/ (one-way).",
    )
    parser.add_argument(
        "--wiki-data",
        required=True,
        help="Path to DokuWiki's data/ directory (contains pages/ and attic/)",
    )
    parser.add_argument(
        "--namespace",
        default="party",
        help="Wiki namespace holding player-authored pages (default: party)",
    )
    parser.add_argument(
        "--as-of",
        help="Capture each page as it stood on this date (YYYY-MM-DD), using attic revisions",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing files in Perceptions/ (default: skip existing)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would be written")
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

    perceptions_dir = ws.root / ws.config.perceptions_dir

    data = Path(args.wiki_data).expanduser().resolve()
    pages_root = data / "pages"
    attic_root = data / "attic"

    if not pages_root.is_dir():
        print(f"error: {pages_root} not found — is --wiki-data correct?", file=sys.stderr)
        return 1

    as_of_ts = None
    if args.as_of:
        try:
            dt = datetime.strptime(args.as_of, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            print("error: --as-of must be YYYY-MM-DD", file=sys.stderr)
            return 1
        as_of_ts = int(dt.timestamp())
        if not attic_root.is_dir():
            print(f"warning: {attic_root} not found; --as-of will fall back to current pages",
                  file=sys.stderr)

    ns_dir = pages_root / Path(*args.namespace.split(":"))
    if not ns_dir.is_dir():
        print(f"error: namespace '{args.namespace}' not found at {ns_dir}", file=sys.stderr)
        return 1

    page_ids = []
    for path in sorted(ns_dir.rglob("*.txt")):
        rel = path.relative_to(pages_root).with_suffix("")
        page_ids.append(":".join(rel.parts))

    if not page_ids:
        print(f"No pages found in namespace '{args.namespace}'.")
        return 0

    if not args.dry_run:
        perceptions_dir.mkdir(parents=True, exist_ok=True)

    written = skipped = missing = blank = 0
    for page_id in page_ids:
        result = read_page(pages_root, attic_root, page_id, as_of_ts)
        if result is None:
            print(f"  no revision at that date  {page_id}")
            missing += 1
            continue

        raw, mtime = result
        if not raw.strip():
            # Counted and named rather than dropped (#25). A blank page is
            # still not imported — that judgement is unchanged — but a page
            # absent from both the output and the tally is indistinguishable
            # from one that was never in the namespace at all.
            print(f"  blank (not imported)      {page_id}")
            blank += 1
            continue

        name = slugify(page_id)
        if args.as_of:
            name = f"{name}--{args.as_of}"
        dest = perceptions_dir / f"{name}.md"

        if dest.exists() and not args.overwrite:
            print(f"  skip (exists)             {dest.name}")
            skipped += 1
            continue

        content = build_file(page_id, raw, mtime, args.as_of)
        if args.dry_run:
            print(f"  [dry-run] would write     {dest.name}  ({len(content)} bytes)")
        else:
            dest.write_text(content, encoding="utf-8")
            print(f"  wrote                     {dest.name}")
        written += 1

    print(f"\n{written} written, {skipped} skipped, {blank} blank, "
          f"{missing} unavailable.")
    if skipped and not args.overwrite:
        print("Use --overwrite to refresh existing captures.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        sys.stderr.close()
        raise SystemExit(0)
