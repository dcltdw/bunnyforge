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

from pathlib import Path

from bunnyforge import _common
from bunnyforge._config import Workspace

SEARCH_CAP = 50       # hits per search reply; the reply says when it truncated
SNIPPET_RADIUS = 80   # characters of context on each side of a match


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
        there is not readable back through this method: the read tools serve
        canon, and staged material is not canon until a human promotes it.
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
