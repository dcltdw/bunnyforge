#!/usr/bin/env python3
"""
_store.py — the workspace-access layer behind `bunnyforge serve-mcp`.

Every MCP tool call touches the workspace through WorkspaceStore, so the
path guards and the staging/canonical boundary have exactly one home. A
remote agent's request is untrusted input: it names a path, and refusing
the ones that escape the workspace or reach into excluded directories is
this module's job, not the tool layer's.

Stdlib only, deliberately: the MCP SDK belongs to serve_mcp.py, and even
there only inside function bodies — this module must import cleanly on a
bare Python.

The class is also the phase-3 seam. A hosted deployment swaps in a
git-clone-backed implementation with the same method surface, so behaviour
belongs on the class, never in free functions serve_mcp.py calls directly.
"""

from __future__ import annotations

import random
import re
import subprocess
from pathlib import Path

from bunnyforge import _common
from bunnyforge import generate_names as _names
from bunnyforge._config import Workspace

SEARCH_CAP = 50       # hits per search reply; the reply says when it truncated
SNIPPET_RADIUS = 80   # characters of context on each side of a match
NAME_COUNT_CAP = 50   # names per request; a brainstorm needs a handful, not a page

# Draft names become filenames. No path separators, no leading dot or
# underscore (dot-files hide; the _-prefix is the workspace's own marker
# for machinery directories).
_DRAFT_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _'-]*")


class StoreError(Exception):
    """A refusal the remote agent will see verbatim: unknown section, bad
    path, missing file. The message text is the API — write it to be acted
    on, naming the valid alternatives rather than merely saying no."""


class WorkspaceStore:

    def __init__(self, ws: Workspace):
        self.ws = ws

    # -- guards -------------------------------------------------------------

    def _sections(self) -> tuple[str, ...]:
        cfg = self.ws.config
        return cfg.entity_dirs + cfg.inherit_dirs

    def _check_section(self, section: str) -> None:
        if section not in self._sections():
            raise StoreError(f"unknown section {section!r} — one of: "
                             + ", ".join(self._sections()))

    def _canonical(self, path: str) -> Path:
        """Resolve a workspace-relative path, refusing escapes and excluded
        directories.

        The staging directory is one of the excluded ones, so a draft written
        there is not readable back through this method: the canon read tools
        serve canon, and staged material is not canon until a human promotes
        it. Staging has its own labelled door — read_staged, below — which
        guards the inverse condition and reaches nothing else.
        """
        root = self.ws.root
        p = (root / path).resolve()
        if not p.is_relative_to(root):
            raise StoreError(f"path escapes the workspace: {path}")
        excluded = self.ws.config.exclude_dirs & set(p.relative_to(root).parts)
        if excluded:
            raise StoreError(
                f"path is in an excluded directory ({', '.join(sorted(excluded))}): "
                f"{path}")
        return p

    # -- read side ----------------------------------------------------------

    def overview(self) -> dict:
        """One call to orient a fresh conversation: what this campaign is,
        what it holds, and what is currently live."""
        cfg = self.ws.config
        # Counted from the same walk list_entities uses, so a count here and
        # the list it promises cannot disagree. A bare rglob would include
        # files inside excluded subdirectories that list_entities omits.
        counts: dict[str, int] = {}
        for rec in _common.iter_content_files(self.ws):
            parts = rec.path.relative_to(self.ws.root).parts
            if len(parts) > 1:
                counts[parts[0]] = counts.get(parts[0], 0) + 1
        # Only directories that exist: a section the campaign has not created
        # yet is absent, not empty. Reporting it as 0 would present an unused
        # part of the layout as an emptied one.
        sections = {d: counts.get(d, 0) for d in self._sections()
                    if (self.ws.root / d).is_dir()}

        out: dict = {"name": cfg.name, "sections": sections}
        for key, fname in (("front_burner", "front-burner.md"),
                           ("open_questions", "open-questions.md")):
            p = self.ws.root / fname
            out[key] = p.read_text(encoding="utf-8") if p.is_file() else None
        return out

    def list_entities(self, section: str) -> list[dict]:
        """One section's files: workspace path, title, one-line summary.

        Summaries come from front matter, where this workspace's convention
        puts a retrievable one-sentence description — which is what makes a
        listing useful to an agent that has not read the files.
        """
        self._check_section(section)
        out = []
        for rec in _common.iter_content_files(self.ws):
            rel = rec.path.relative_to(self.ws.root)
            if rel.parts[0] != section:
                continue
            out.append({"path": rel.as_posix(),
                        "title": rec.fm.get("title") or rec.path.stem,
                        "summary": rec.fm.get("summary", "")})
        return out

    def read_entity(self, path: str) -> str:
        """Full text of one workspace file, front matter included."""
        p = self._canonical(path)
        if not p.is_file():
            raise StoreError(f"no such file: {path}")
        return p.read_text(encoding="utf-8")

    def search(self, query: str, section: str | None = None) -> list[dict]:
        """Case-insensitive substring search across content files.

        Deliberately literal rather than clever: an agent that can see the
        matched text decides relevance better than a ranking heuristic
        would, and a substring match is explainable when it surprises.
        """
        q = query.strip().lower()
        if not q:
            raise StoreError("empty search query")
        if section is not None:
            self._check_section(section)

        hits: list[dict] = []
        for rec in _common.iter_content_files(self.ws):
            rel = rec.path.relative_to(self.ws.root).as_posix()
            if section is not None and not rel.startswith(section + "/"):
                continue
            text = rec.path.read_text(encoding="utf-8")
            i = text.lower().find(q)
            if i == -1:
                continue
            lo = max(0, i - SNIPPET_RADIUS)
            hi = min(len(text), i + len(q) + SNIPPET_RADIUS)
            hits.append({"path": rel, "snippet": text[lo:hi]})
            if len(hits) >= SEARCH_CAP:
                # Say so rather than truncating silently: a capped reply that
                # looks complete is worse than a short one that admits it.
                hits.append({"path": "", "snippet":
                             f"(truncated at {SEARCH_CAP} hits — "
                             "narrow the query)"})
                break
        return hits

    # -- generators ---------------------------------------------------------

    def generate_names(self, culture: str, count: int) -> dict:
        """Culture-appropriate person and place names for this setting.

        A thin wrapper over the existing generator, which already owns every
        rule about how a culture's names are built. Its exceptions are
        translated to StoreError here: an InventoryError reaching the tool
        layer would surface to the remote agent as a crash rather than as
        something it could act on.
        """
        count = max(1, min(int(count), NAME_COUNT_CAP))
        try:
            inv = _names.load_inventory(self.ws)
        except _names.InventoryError as exc:
            raise StoreError(str(exc)) from exc

        # resolve() answers a key, a list of candidates when an alias is
        # ambiguous, or None. Only the first is usable — guessing between
        # two cultures would be worse than refusing.
        key = _names.resolve(inv.cultures, culture)
        if not isinstance(key, str):
            available = ", ".join(sorted(inv.cultures))
            hint = ("ambiguous" if isinstance(key, list) else "unknown")
            raise StoreError(
                f"{hint} culture {culture!r} — available: {available}")

        rng = random.Random()
        return {"culture": key,
                "people": [_names.person_name(rng, inv, key, None)
                           for _ in range(count)],
                "places": [_names.place_name(rng, inv, key)
                           for _ in range(count)]}

    # -- staging ------------------------------------------------------------

    def _staging(self) -> Path:
        return self.ws.root / self.ws.config.staging_dir

    # Reading staging back is the agent's own inbox, not a second door into
    # canon: these two are the only way in, they reach nothing else, and the
    # tool docstrings say the material is unreviewed. read_staged's guard is
    # the exact inverse of _canonical() -- inside the staging directory
    # rather than outside it -- so it cannot be talked into serving canon.
    # Its messages name the TOOL the agent can call next, which is what it
    # can act on; list_staging is what the tool layer registers as that.

    def list_staging(self) -> list[dict]:
        """Every staged markdown file: its workspace path and what it is.

        "revision" means the mirrored canonical file exists, so the GM reads
        it as a diff; "draft" means new content with nothing to compare
        against. Sorted, so two calls agree.
        """
        staging = self._staging()
        out = []
        for p in sorted(staging.rglob("*.md")):
            if not p.is_file():
                continue
            mirrored = self.ws.root / p.relative_to(staging)
            out.append({"path": p.relative_to(self.ws.root).as_posix(),
                        "kind": "revision" if mirrored.is_file() else "draft"})
        return out

    def read_staged(self, path: str) -> str:
        """Full text of one staged file — unreviewed material, not canon."""
        root = self.ws.root
        staging = self._staging()
        p = (root / path).resolve()
        if not p.is_relative_to(root):
            raise StoreError(f"path escapes the workspace: {path}")
        if not p.is_relative_to(staging):
            raise StoreError(
                f"not a staged path: {path} — read_staged serves "
                f"{self.ws.config.staging_dir}/ only; canonical files are "
                "read with read_entity")
        if p.suffix != ".md":
            raise StoreError(
                f"not a staged markdown file: {path} — staging holds .md "
                "drafts and revisions")
        if not p.is_file():
            raise StoreError(
                f"no such staged file: {path} — list_staged shows what is "
                "currently staged")
        return p.read_text(encoding="utf-8")

    # -- write side ---------------------------------------------------------
    # Staging paths are built directly rather than through _canonical: the
    # staging directory is excluded from the canon reads BY DESIGN, and these
    # two methods are the only writers. Traversal is impossible by
    # construction -- section is validated against config, and _DRAFT_NAME_RE
    # admits no separator.

    def stage_draft(self, section: str, name: str, content: str) -> str:
        self._check_section(section)
        if not _DRAFT_NAME_RE.fullmatch(name):
            raise StoreError(
                f"bad draft name {name!r} — letters, digits, spaces, "
                "- _ ' only, starting with a letter or digit")
        dest = self._staging() / section / f"{name}.md"
        if dest.exists():
            rel = dest.relative_to(self.ws.root).as_posix()
            raise StoreError(f"{rel} already exists — pick another name")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        return dest.relative_to(self.ws.root).as_posix()

    def stage_revision(self, path: str, content: str) -> str:
        target = self._canonical(path)
        if not target.is_file() or target.suffix != ".md":
            raise StoreError(
                f"no such content file: {path} — stage_revision proposes "
                "changes to an existing file; use stage_draft for new "
                "content")
        dest = self._staging() / target.relative_to(self.ws.root)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")  # latest proposal wins
        return dest.relative_to(self.ws.root).as_posix()

    def write_entity(self, path: str, content: str) -> str:
        target = self._canonical(path)
        if not target.is_file() or target.suffix != ".md":
            raise StoreError(f"no such content file: {path}")
        rel = target.relative_to(self.ws.root).as_posix()
        if target.read_text(encoding="utf-8") == content:
            return rel  # nothing to change, nothing to commit
        probe = subprocess.run(
            ["git", "-C", str(self.ws.root), "rev-parse",
             "--is-inside-work-tree"], capture_output=True, text=True)
        if probe.returncode != 0:
            raise StoreError(
                "direct edits require the workspace to be a git repository "
                "— refusing to edit canon without history")
        target.write_text(content, encoding="utf-8")
        for sub in (["add", "--", rel],
                    ["commit", "-m", f"serve-mcp: edit {rel}"]):
            done = subprocess.run(["git", "-C", str(self.ws.root)] + sub,
                                  capture_output=True, text=True)
            if done.returncode != 0:
                raise StoreError(f"git {sub[0]} failed: "
                                 f"{done.stderr.strip() or done.stdout.strip()}")
        return rel
