#!/usr/bin/env python3
"""
_common.py — shared helpers for the campaign workspace scripts.

Stdlib only, on purpose: the scripts and their tests must run under a bare
Python 3 with nothing installed (see .github/workflows and tests/).

Consolidated here so the front-matter parser has one definition, not one copy
per script that can drift.
"""

from __future__ import annotations

import re
from collections import namedtuple
from pathlib import Path

from bunnyforge._config import Config, Workspace

# The three audiences a content file can address. See AGENTS.md -> Player
# visibility. `gm-only` is the fail-safe: an unset or unrecognised value is
# treated as gm-only so nothing leaks to players by accident.
VISIBILITY_VALUES = ("gm-only", "player-visible", "mixed")
DEFAULT_VISIBILITY = "gm-only"


def split_front_matter(text: str) -> tuple[dict[str, str], str]:
    """Split a leading YAML-ish front-matter block from the body.

    A deliberately small parser: one level of `key: value`, with indented
    continuation lines folded onto the previous key. Duplicate keys take the
    last value, matching YAML. It does not model nested mappings or lists
    beyond their raw string form, which is all this workspace's front matter
    needs.
    """
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    block, body = text[3:end], text[end + 4:]
    fm: dict[str, str] = {}
    key = None
    for line in block.splitlines():
        if not line.strip():
            continue
        m = re.match(r"^([A-Za-z_][\w]*):\s*(.*)$", line)
        if m:
            key = m.group(1)
            val = m.group(2).strip()
            # A YAML block-scalar indicator (>- | |- >+ ...) introduces a folded
            # value on the following indented lines; the indicator itself is not
            # part of the value.
            if val in (">", ">-", ">+", "|", "|-", "|+"):
                val = ""
            fm[key] = val
        elif key and line.startswith((" ", "\t")):
            fm[key] = (fm[key] + " " + line.strip()).strip()
    return fm, body


def strip_yaml_comment(value: str) -> str:
    """Drop a trailing ` # ...` comment. Templates ship hints inline."""
    return re.split(r"\s+#", value, maxsplit=1)[0].strip()


def normalize_visibility(fm: dict[str, str],
                         default: str = DEFAULT_VISIBILITY) -> str:
    """Resolve a file's `visibility` to one of VISIBILITY_VALUES.

    Unset -> `default`. An unrecognised value -> `gm-only`, deliberately: a
    typo must never widen the audience.
    """
    raw = strip_yaml_comment(fm.get("visibility", "")).lower()
    if not raw:
        return default
    if raw not in VISIBILITY_VALUES:
        return "gm-only"
    return raw


# The GM-notes separator used by `mixed`-visibility files (handouts, and any
# other content file split with the same convention). `GM` is current; `DM`
# is accepted for any older handout not yet updated, so a rename never
# silently exposes GM notes. Defined here rather than in export_player.py so
# any future consumer inherits the same boundary.
GM_MARKER = re.compile(r"^---\s*$\n^##\s*(?:GM|DM) notes", re.MULTILINE)


def player_facing(body: str) -> str | None:
    """Everything above the GM-notes rule. None if the marker is absent.

    A `mixed`-visibility body without the separator cannot be split safely —
    callers must treat None as "nothing here is safe to expose", not fall
    back to the whole body.
    """
    m = GM_MARKER.search(body)
    if not m:
        return None
    return body[: m.start()]


FileRec = namedtuple("FileRec", "path fm body category")

# The workspace's shape is configured in campaign.toml, not hardcoded here,
# and arrives as an argument rather than as module state — so a caller can
# operate on any workspace, not only the one this process resolved at import.
#   config.entity_dirs      .md files carrying full entity front matter
#   config.inherit_dirs     scanned for wikilinks, exempt from `visibility`
#   config.compendium_dirs  subject to the compendium check
#   config.root_docs        no entity front matter, but valid wikilink targets
#   config.exclude_dirs     never walked


def iter_content_files(ws: Workspace) -> list[FileRec]:
    """Enumerate content files as FileRec, sorted by path.

    Skips excluded directories and every README.md. Category is 'entity',
    'inherit', or 'root'.
    """
    recs: list[FileRec] = []
    workspace, config = ws.root, ws.config

    for name in config.root_docs:
        p = workspace / name
        if p.is_file():
            fm, body = split_front_matter(p.read_text(encoding="utf-8"))
            recs.append(FileRec(p, fm, body, "root"))

    for category, dirs in (("entity", config.entity_dirs),
                           ("inherit", config.inherit_dirs)):
        for d in dirs:
            base = workspace / d
            if not base.is_dir():
                continue
            for p in base.rglob("*.md"):
                if p.name.lower() == "readme.md":
                    continue
                parts = p.relative_to(workspace).parts
                if config.exclude_dirs & set(parts):
                    continue
                if any(is_machinery(part) for part in parts):
                    continue
                fm, body = split_front_matter(p.read_text(encoding="utf-8"))
                recs.append(FileRec(p, fm, body, category))

    # The archive walks as canon (#62): mirrored top-level layout,
    # Archive/<Section>/<file>.md. Category follows the mirror so archived
    # briefs stay brief-shaped to every check; unknown mirrors and files
    # directly at the archive root default to "entity" -- visible and
    # validated rather than silently skipped.
    inherit_names = set(config.inherit_dirs)
    base = workspace / config.archive_dir
    if base.is_dir():
        for p in base.rglob("*.md"):
            if p.name.lower() == "readme.md":
                continue
            parts = p.relative_to(workspace).parts
            if config.exclude_dirs & set(parts):
                continue
            if any(is_machinery(part) for part in parts):
                continue
            mirror = parts[1] if len(parts) > 2 else None
            category = "inherit" if mirror in inherit_names else "entity"
            fm, body = split_front_matter(p.read_text(encoding="utf-8"))
            recs.append(FileRec(p, fm, body, category))

    return sorted(recs, key=lambda r: r.path.as_posix())


_ALIAS_ITEM_RE = re.compile(r"(?:^|\s)-\s+")


def split_aliases(raw: str) -> list[str]:
    """Split one file's raw `aliases` front-matter value into its items.

    Two forms reach here from `split_front_matter`:

    - Inline: `aliases: [The Ghost, Old Man]` -- bracketed, comma-separated.
    - Block style, which split_front_matter folds onto one line, arriving as
      `- The Ghost - Old Man`. Each item keeps its own `- ` introducer, so
      that is what we split on.
    """
    raw = raw.strip()
    if not raw:
        return []
    if raw.startswith("[") and raw.endswith("]"):
        parts = raw[1:-1].split(",")
    else:
        parts = _ALIAS_ITEM_RE.split(raw)
    return [p.strip().strip("'\"") for p in parts if p.strip().strip("'\"")]


def is_machinery(part: str) -> bool:
    """True if one path component is machinery by naming convention (#62):
    _-prefixed (not canon -- _Ignore/, _Templates/, _AgentDrafts/, _Done/)
    or .-prefixed (hidden machine files -- .git, .DS_Store,
    .proposal-bases.json).

    One definition, honoured by iter_content_files, the store's canon
    resolver and both agent-facing families, and review's checks, so no
    two surfaces can disagree about what counts. _config.py's archive_dir
    validation inlines the same one-line test: _common imports _config,
    so importing this from there would be circular.
    """
    return part.startswith(("_", "."))


def aliases_for(rec: FileRec) -> set[str]:
    return {a.lower() for a in split_aliases(rec.fm.get("aliases", ""))}


def target_index(files: list[FileRec]) -> dict[str, set[Path]]:
    """Map every string a `[[wikilink]]` can spell a file as -- its stem and
    any declared aliases -- to the set of paths it resolves to.

    Shared by review.py's wikilink and compendium checks and by the wiki
    exporter, so all three share one definition of "refers to a file" and
    cannot drift apart (#8, #17).
    """
    index: dict[str, set[Path]] = {}
    for rec in files:
        index.setdefault(rec.path.stem.lower(), set()).add(rec.path)
        for alias in aliases_for(rec):
            index.setdefault(alias, set()).add(rec.path)
    return index


def resolve_target(target: str, index: dict[str, set[Path]]) -> set[Path]:
    """Resolve one `[[target]]` string to the file(s) it points at.

    Path-form targets (e.g. `Mechanics/species-house-rule`) resolve by their
    last path segment, since `index` holds bare stems/aliases.
    """
    t = target.strip().lower()
    paths = index.get(t)
    if paths:
        return paths
    return index.get(t.split("/")[-1], set())


def content_dir_names(config: Config) -> frozenset[str]:
    """Every directory a bare `[[Mechanics]]`-style link can name.

    Derived here rather than in either caller so review.py's wikilink check
    and the wiki exporter share one notion of "names a content directory"
    and cannot drift (#8, #17).
    """
    return frozenset(d.lower() for d in
                     config.entity_dirs + config.inherit_dirs
                     + (config.archive_dir,))


def is_pass_through_target(target: str, content_dirs: frozenset[str]) -> bool:
    """True when a `[[target]]` does not name a workspace file at all.

    External URLs, interwiki shortcuts (`wp>Seoul`), anchor-only links, empty
    targets, and bare content-directory names are all valid link forms that
    simply are not file references. Callers that resolve links to files must
    treat them as "leave exactly as written" rather than as broken: the
    exporter passes them through untouched, review.py does not flag them.

    Takes the directory names rather than a whole Workspace: they are all it
    needs, and callers in the link-checking hot path compute them once.
    """
    t = target.strip().lower()
    if not t or "://" in t or t.startswith("#") or ">" in t:
        return True
    return t in content_dirs or t.split("/")[-1] in content_dirs


# Both character classes are bounded to a single line ([^\]\n], [^)\n]) so an
# unbalanced `[` cannot swallow a following line when this runs over a whole
# document body rather than one line at a time (render_tree does the former,
# to_dokuwiki the latter -- they must agree). `(?<!!)` excludes the markdown
# image form `![alt](src)`: an image names an asset, not a workspace document,
# so it is not a link the wikilink policy should judge.
#
# Known limitation, unchanged from before this policy existed: a nested
# bracket in the label, e.g. `[a [nested] label](target)`, matches nothing at
# all rather than mis-parsing, so it publishes as literal text. This is not
# full markdown link parsing.
_MD_LINK_RE = re.compile(r"(?<!!)\[([^\]\n]+)\]\(([^)\n]+)\)")


def markdown_links_to_wikilinks(text: str) -> str:
    """Rewrite `[label](target)` as `[[target|label]]`.

    Lives here rather than in _dokuwiki because wikilinks are the workspace's
    own link format -- review.py has always scanned for them -- and DokuWiki
    merely shares the syntax. Both the exporter and the checkup need this, and
    neither should have to import the other's module to get it.

    The export pipeline applies it *before* the wikilink policy runs.
    Converting afterwards, as to_dokuwiki does, would publish a live link the
    policy never inspected -- including one naming a gm-only document (#21).
    """
    return _MD_LINK_RE.sub(r"[[\2|\1]]", text)
