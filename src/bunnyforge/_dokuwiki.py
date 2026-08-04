#!/usr/bin/env python3
"""
_dokuwiki.py — DokuWiki-specific helpers shared by the wiki-facing scripts.

Everything that knows about DokuWiki markup, page IDs, or page composition
lives here, so `_common.py` stays a general-purpose workspace helper module.
"""

from __future__ import annotations

import re
from collections import namedtuple
from pathlib import Path, PurePosixPath

from bunnyforge._common import (
    is_pass_through_target,
    markdown_links_to_wikilinks,
    resolve_target,
)


def strip_leading_heading(text: str) -> str:
    """Drop the file's H1; used where the page gets its own title heading."""
    return re.sub(r"\A\s*#\s+.*?\n", "", text, count=1)


def to_dokuwiki(text: str, title: str | None = None) -> str:
    out: list[str] = []
    if title is not None:
        out = [f"====== {title} ======", ""]

    for line in text.splitlines():
        m = re.match(r"^(#{1,5})\s+(.*)$", line)
        if m:
            eq = "=" * (7 - len(m.group(1)))
            out.append(f"{eq} {m.group(2)} {eq}")
            continue

        line = re.sub(r"\*\*(.+?)\*\*", r"**\1**", line)
        line = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"//\1//", line)
        line = re.sub(r"~~(.+?)~~", r"<del>\1</del>", line)
        line = re.sub(r"`([^`\n]+?)`", r"''\1''", line)
        line = markdown_links_to_wikilinks(line)

        m = re.match(r"^(\s*)([-*])\s+(.*)$", line)
        if m:
            depth = len(m.group(1)) // 2
            line = f"{'  ' * (depth + 1)}* {m.group(3)}"
        else:
            m = re.match(r"^(\s*)\d+\.\s+(.*)$", line)
            if m:
                depth = len(m.group(1)) // 2
                line = f"{'  ' * (depth + 1)}- {m.group(2)}"

        if re.match(r"^\s*---+\s*$", line):
            line = "----"

        out.append(line)

    return "\n".join(out).rstrip() + "\n"


# Sub-namespaces of the base namespace that this pipeline owns. A content
# directory with either name would collide, so deployment refuses.
RESERVED_SUBNAMESPACES = ("export", "players")


def page_id(rel_path: str, prefix: str = "") -> str:
    """Map a workspace-relative .md path to a DokuWiki page ID.

    'Mechanics/species-house-rule.md' -> 'mechanics:species-house-rule'
    DokuWiki lower-cases page IDs and accepts hyphens, so kebab-case stems
    carry over unchanged.
    """
    p = PurePosixPath(rel_path)
    parts = [seg.lower() for seg in p.with_suffix("").parts]
    pid = ":".join(parts)
    return f"{prefix}:{pid}" if prefix else pid


def page_path(page_id: str, pages_root: Path) -> Path:
    """Filesystem path of a page ID under a DokuWiki data/pages root."""
    parts = page_id.split(":")
    return pages_root.joinpath(*parts[:-1], parts[-1] + ".txt")


def reserved_dir_collisions(rel_paths: list[str]) -> list[str]:
    """Reserved-namespace names colliding as a top-level directory or file.

    'export/b.md' collides via its top-level directory; a bare top-level file
    'players.md' collides via its own stem, because it would otherwise render
    straight to <base>:players — the start page of a namespace this pipeline
    documents itself as never writing.
    """
    hits = set()
    for rel in rel_paths:
        p = PurePosixPath(rel)
        parts = p.parts
        name = parts[0].lower() if len(parts) > 1 else p.stem.lower()
        if name in RESERVED_SUBNAMESPACES:
            hits.add(name)
    return sorted(hits)


def wrapper_text(export_id: str, players_id: str) -> str:
    """The reader-facing page: exported content, then player annotations.

    Deliberately carries no heading of its own. The page title comes from the
    exported content's H1, so a title change is an ordinary content change
    rather than a separate wrapper edit.
    """
    return f"{{{{page>{export_id}}}}}\n{{{{page>{players_id}}}}}\n"


LinkRef = namedtuple("LinkRef", "target anchor label")


def parse_wikilink(raw: str) -> LinkRef:
    """Split the text between [[ and ]] into target, #anchor and |label.

    The form is `target#anchor|label`; both anchor and label are optional.
    Matches how review.py's extract_wikilinks reads the same syntax.
    """
    target_part, _, label = raw.partition("|")
    target, _, anchor = target_part.partition("#")
    # `str.partition` already yields "" for a missing separator, and only the
    # first `|` separates: a label may itself contain `|` or `#`.
    return LinkRef(target.strip(), anchor.strip(), label.strip())


def format_wikilink(page_id: str, anchor: str, label: str) -> str:
    inner = page_id
    if anchor:
        inner = f"{inner}#{anchor}"
    if label:
        inner = f"{inner}|{label}"
    return f"[[{inner}]]"


TargetVerdict = namedtuple("TargetVerdict", "case path")


def classify_target(target: str, index: dict[str, set[Path]],
                    content_dirs: frozenset[str]) -> TargetVerdict:
    """Resolve one link target against the workspace index.

    'resolved'     -> exactly one file; `path` is it
    'ambiguous'    -> several files share that stem/alias; refuse rather than
                      guess
    'pass-through' -> a valid link that names no workspace file at all: an
                      external URL, an interwiki shortcut, an anchor-only or
                      empty target, or a bare content-directory name. Left
                      exactly as written, never a refusal — the same verdict
                      review.py's wikilink check reaches, via the shared
                      `is_pass_through_target`.
    'unresolved'   -> nothing; a typo or a deleted file
    """
    paths = resolve_target(target, index)
    if not paths:
        if is_pass_through_target(target, content_dirs):
            return TargetVerdict("pass-through", None)
        return TargetVerdict("unresolved", None)
    if len(paths) > 1:
        return TargetVerdict("ambiguous", None)
    return TargetVerdict("resolved", next(iter(paths)))


_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")

LinkSite = namedtuple("LinkSite", "target case line")


def rewrite_wikilinks(body: str, resolve) -> tuple[str, list[LinkSite]]:
    """Rewrite every [[link]] in `body` via `resolve`.

    Every link is subject to the policy — there is no code exemption. Markup
    does not protect a link: `to_dokuwiki` passes ``` fences through verbatim
    and DokuWiki has no fence syntax, so the markers render as literal text in
    an ordinary paragraph and DokuWiki linkifies the `[[...]]` inside them. An
    exemption would therefore be a silent bypass of the whole link policy, not
    a way to show a link as sample text.

    `resolve(target)` returns `(new_page_id, case)`. When new_page_id is None
    the link text is left exactly as-is; the case is still reported so the
    caller can refuse.

    Returns (rewritten_body, [LinkSite(target, case, line), ...]) in document
    order; `line` is the 1-based line of `body` the link starts on.
    """
    seen: list[LinkSite] = []

    def _sub(m: re.Match) -> str:
        ref = parse_wikilink(m.group(1))
        new_id, case = resolve(ref.target)
        seen.append(LinkSite(ref.target, case, body.count("\n", 0, m.start()) + 1))
        if new_id is None:
            return m.group(0)
        return format_wikilink(new_id, ref.anchor, ref.label or ref.target)

    return _WIKILINK_RE.sub(_sub, body), seen
