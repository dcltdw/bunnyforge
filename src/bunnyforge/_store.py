#!/usr/bin/env python3
"""
_store.py — the workspace-access layer behind `bunnyforge serve-mcp`.

Every MCP tool call touches the workspace through WorkspaceStore, so the
path guards and the drafts/inbound/canonical boundaries have exactly one
home. A remote agent's request is untrusted input: it names a path, and
refusing the ones that escape the workspace or reach into excluded
directories is this module's job, not the tool layer's.

Stdlib only, deliberately: the MCP SDK belongs to serve_mcp.py, and even
there only inside function bodies — this module must import cleanly on a
bare Python.

The class is also the phase-3 seam. A hosted deployment swaps in a
git-clone-backed implementation with the same method surface, so behaviour
belongs on the class, never in free functions serve_mcp.py calls directly.
"""

from __future__ import annotations

import hashlib
import json
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
SCOPES = ("live", "archive", "both")  # exactly two trees exist (#62), so
                                      # "both" is the honest union token

# Draft names become filenames. No path separators, no leading dot or
# underscore (dot-files hide; the _-prefix is the workspace's own marker
# for machinery directories).
_DRAFT_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _'-]*")

BASES_NAME = ".proposal-bases.json"

INBOUND_SUFFIXES = frozenset({".md", ".txt", ".html", ".htm"})


def _slug(name: str) -> str:
    """A _DRAFT_NAME_RE-validated name, as a canon-style filename stem:
    lowercase, separators to single hyphens, apostrophes dropped. Canon
    files are kebab-case, and slugs are what let the drafts tree mirror
    canon — which is what lets promotion derive its destination."""
    s = name.lower().replace("'", "")
    s = re.sub(r"[\s_]+", "-", s)
    return re.sub(r"-+", "-", s).strip("-")


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
        return cfg.entity_dirs + cfg.inherit_dirs + (cfg.archive_dir,)

    def _check_section(self, section: str) -> None:
        if section not in self._sections():
            raise StoreError(f"unknown section {section!r} — one of: "
                             + ", ".join(self._sections()))

    def _check_retrieval(self, section: str | None, scope: str) -> None:
        """Validate a search/list_entities filter pair before any walk.

        scope names which tree(s) to read. One combination is a
        contradiction rather than an empty answer -- the archive
        section under a scope that excludes archived files -- and a
        contradiction is refused, not served (#66).
        """
        if scope not in SCOPES:
            raise StoreError(f"unknown scope {scope!r} — one of: "
                             + ", ".join(SCOPES))
        if section is not None:
            self._check_section(section)
            if scope == "live" and section == self.ws.config.archive_dir:
                raise StoreError(
                    f"section {section!r} contradicts scope 'live': "
                    "archived files are exactly what it excludes — drop "
                    "the section, or use scope 'archive'")

    def _in_scope(self, parts: tuple[str, ...], section: str | None,
                  scope: str) -> bool:
        """One walked file's membership under a validated filter (#66).

        A file is archived iff its first component is the archive dir.
        section names the CONTENT section and resolves inside the
        scope's tree(s): live files match on parts[0], archived files
        on their mirror (parts[1]); the archive dir's own name denotes
        the archive tree. A stray directly at Archive/*.md has no
        mirror, so it matches whole-archive queries and no section.
        """
        archive = self.ws.config.archive_dir
        archived = parts[0] == archive
        if (scope == "live" and archived) or \
                (scope == "archive" and not archived):
            return False
        if section is None:
            return True
        if section == archive:
            return archived
        if archived:
            return len(parts) > 2 and parts[1] == section
        return parts[0] == section

    def _canonical(self, path: str) -> Path:
        """Resolve a workspace-relative path, refusing what is not canon.

        Two refusals, one meaning (#62): a _- or .-prefixed component is
        not canon by the naming convention — which is also what keeps the
        drafts and inbound directories out; each of those has its own
        labelled door (read_draft, read_inbound) guarding the inverse
        condition. An exclude_dirs component is repo infrastructure the
        config enumerates (docs/, scripts/, tests/).
        """
        root = self.ws.root
        p = (root / path).resolve()
        if not p.is_relative_to(root):
            raise StoreError(f"path escapes the workspace: {path}")
        parts = p.relative_to(root).parts
        if any(_common.is_machinery(part) for part in parts):
            raise StoreError(
                f"{path} has a _- or .-prefixed component, so it is not "
                "canon (the workspace naming convention); the canon tools "
                "serve canon only — drafts are read with read_draft, the "
                "inbound queue with read_inbound")
        excluded = self.ws.config.exclude_dirs & set(parts)
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
        # Counts, not contents: the agent may notice the GM's queue is
        # non-empty and offer to extract, without reading it unbidden.
        out["inbound_pending"] = len(self.list_inbound())
        out["drafts_pending"] = len(self.list_drafts())
        return out

    def list_entities(self, section: str, scope: str = "both") -> list[dict]:
        """One section's files: workspace path, title, one-line summary,
        and whether the file is archived.

        Summaries come from front matter, where this workspace's convention
        puts a retrievable one-sentence description — which is what makes a
        listing useful to an agent that has not read the files.

        section resolves inside the scope's tree(s) (#66): the default
        "both" lists live and mirrored archived members together, each
        row labelled, because archived names are still taken (#62's
        collision check) and a listing that hides them invites reuse.
        """
        self._check_retrieval(section, scope)
        archive = self.ws.config.archive_dir
        out = []
        for rec in _common.iter_content_files(self.ws):
            rel = rec.path.relative_to(self.ws.root)
            if not self._in_scope(rel.parts, section, scope):
                continue
            out.append({"path": rel.as_posix(),
                        "title": rec.fm.get("title") or rec.path.stem,
                        "summary": rec.fm.get("summary", ""),
                        "archived": rel.parts[0] == archive})
        return out

    def read_entity(self, path: str) -> str:
        """Full text of one workspace file, front matter included."""
        p = self._canonical(path)
        if not p.is_file():
            raise StoreError(f"no such file: {path}")
        return p.read_text(encoding="utf-8")

    def search(self, query: str, section: str | None = None,
               scope: str = "both") -> list[dict]:
        """Case-insensitive substring search across content files.

        Deliberately literal rather than clever: an agent that can see the
        matched text decides relevance better than a ranking heuristic
        would, and a substring match is explainable when it surprises.

        scope and section resolve per _in_scope (#66); every hit says
        whether it is archived, so the caller buckets hits without
        parsing paths.
        """
        q = query.strip().lower()
        if not q:
            raise StoreError("empty search query")
        self._check_retrieval(section, scope)

        archive = self.ws.config.archive_dir
        hits: list[dict] = []
        for rec in _common.iter_content_files(self.ws):
            rel = rec.path.relative_to(self.ws.root)
            if not self._in_scope(rel.parts, section, scope):
                continue
            text = rec.path.read_text(encoding="utf-8")
            i = text.lower().find(q)
            if i == -1:
                continue
            lo = max(0, i - SNIPPET_RADIUS)
            hi = min(len(text), i + len(q) + SNIPPET_RADIUS)
            hits.append({"path": rel.as_posix(), "snippet": text[lo:hi],
                         "archived": rel.parts[0] == archive})
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

    # -- agent drafts -------------------------------------------------------
    # The agents' outbox: drafts and proposed revisions awaiting GM review.
    # Excluded from the canon reads BY DESIGN (config auto-excludes it), so
    # it has its own labelled doors. _draft_path guards the inverse of
    # _canonical() — inside the drafts directory rather than outside it —
    # so these methods cannot be talked into serving canon. Underscore
    # components are machinery (the workspace's own convention): a draft
    # the GM moves to _Rejected/ is never listed or read again.

    def _drafts(self) -> Path:
        return self.ws.root / self.ws.config.drafts_dir

    def _draftable_sections(self) -> tuple[str, ...]:
        # The perception record is by contract never agent-authored, and
        # new material never lands retired: archiving is a GM act.
        cfg = self.ws.config
        return tuple(s for s in self._sections()
                     if s not in (cfg.perceptions_dir, cfg.archive_dir))

    def _slugged(self, raw: str, label: str) -> str:
        if not _DRAFT_NAME_RE.fullmatch(raw):
            raise StoreError(
                f"bad {label} name {raw!r} — letters, digits, spaces, "
                "- _ ' only, starting with a letter or digit")
        slug = _slug(raw)
        if not slug:
            raise StoreError(
                f"{label} name {raw!r} slugs to empty — use a name with "
                "at least one letter or digit that survives lowercasing")
        return slug

    def _draft_path(self, path: str) -> Path:
        root = self.ws.root
        drafts = self._drafts()
        p = (root / path).resolve()
        if not p.is_relative_to(root):
            raise StoreError(f"path escapes the workspace: {path}")
        if not p.is_relative_to(drafts):
            raise StoreError(
                f"not a draft path: {path} — this tool serves "
                f"{self.ws.config.drafts_dir}/ only; canonical files are "
                "read with read_entity")
        if any(_common.is_machinery(part)
               for part in p.relative_to(drafts).parts):
            raise StoreError(
                f"{path} is in a _- or .-prefixed area of the drafts "
                "directory (the GM's machinery, e.g. _Rejected/, or hidden "
                "files) and is never served")
        if p.suffix != ".md":
            raise StoreError(
                f"not a draft markdown file: {path} — drafts are .md only")
        return p

    # The base manifest: workspace-relative shadow path -> SHA-256 of the
    # canonical file at proposal time. A provenance cache, not a lock file:
    # missing or unparseable reads as empty, and every save prunes entries
    # whose shadow is gone.

    def _bases_file(self) -> Path:
        return self._drafts() / BASES_NAME

    def _load_bases(self) -> dict[str, str]:
        try:
            raw = json.loads(self._bases_file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return {k: v for k, v in raw.items()
                if isinstance(k, str) and isinstance(v, str)}

    def _save_bases(self, bases: dict[str, str]) -> None:
        live = {k: v for k, v in bases.items()
                if (self.ws.root / k).is_file()}
        f = self._bases_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(live, indent=2, sort_keys=True) + "\n",
                     encoding="utf-8")

    def _set_base(self, shadow_rel: str, canon: Path) -> None:
        bases = self._load_bases()
        bases[shadow_rel] = hashlib.sha256(canon.read_bytes()).hexdigest()
        self._save_bases(bases)

    def save_draft(self, section: str, name: str, content: str,
                   subdir: str | None = None) -> str:
        if section not in self._draftable_sections():
            raise StoreError(
                f"unknown or undraftable section {section!r} — one of: "
                + ", ".join(self._draftable_sections()))
        rel = Path(section)
        if subdir is not None:
            rel = rel / self._slugged(subdir, "subdir")
        rel = rel / f"{self._slugged(name, 'draft')}.md"
        if (self.ws.root / rel).is_file():
            raise StoreError(
                f"{rel.as_posix()} already exists in canon — use "
                "propose_revision to suggest changes to it, or pick "
                "another name")
        dest = self._drafts() / rel
        if dest.exists():
            drel = dest.relative_to(self.ws.root).as_posix()
            raise StoreError(
                f"{drel} already exists — read_draft it and revise with "
                "update_draft, or pick another name")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        return dest.relative_to(self.ws.root).as_posix()

    def propose_revision(self, path: str, content: str) -> str:
        target = self._canonical(path)
        if not target.is_file() or target.suffix != ".md":
            raise StoreError(
                f"no such content file: {path} — propose_revision proposes "
                "changes to an existing file; use save_draft for new "
                "content")
        inner = target.relative_to(self.ws.root)
        dest = self._drafts() / inner
        rel = dest.relative_to(self.ws.root).as_posix()
        if dest.exists():
            raise StoreError(
                f"a pending proposal already exists at {rel} — read_draft "
                "it, merge your changes into it, then update_draft")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        self._set_base(rel, target)
        return rel

    def update_draft(self, path: str, content: str) -> str:
        """Overwrite one existing draft — the only overwrite door, so
        clobbering is always deliberate: the path must already exist,
        which means it came from list_drafts or read_draft."""
        p = self._draft_path(path)
        if not p.is_file():
            raise StoreError(
                f"no such draft: {path} — save_draft creates new drafts; "
                "list_drafts shows what exists")
        p.write_text(content, encoding="utf-8")
        rel = p.relative_to(self.ws.root).as_posix()
        mirrored = self.ws.root / p.relative_to(self._drafts())
        if mirrored.is_file():
            self._set_base(rel, mirrored)
        return rel

    def list_drafts(self) -> list[dict]:
        """Every pending draft: path, kind ("new" content or a "revision"
        of an existing file), title and summary from front matter, and —
        for revisions — whether canon changed since it was proposed.
        Sorted, so two calls agree."""
        drafts = self._drafts()
        bases = self._load_bases()
        out = []
        for p in sorted(drafts.rglob("*.md")):
            if not p.is_file():
                continue
            inner = p.relative_to(drafts)
            if any(_common.is_machinery(part) for part in inner.parts):
                continue
            rel = p.relative_to(self.ws.root).as_posix()
            fm, _body = _common.split_front_matter(
                p.read_text(encoding="utf-8"))
            mirrored = self.ws.root / inner
            row = {"path": rel,
                   "kind": "revision" if mirrored.is_file() else "new",
                   "title": fm.get("title") or p.stem,
                   "summary": fm.get("summary", "")}
            if row["kind"] == "revision":
                base = bases.get(rel)
                row["stale"] = (None if base is None else
                                hashlib.sha256(mirrored.read_bytes())
                                .hexdigest() != base)
            out.append(row)
        return out

    def read_draft(self, path: str) -> str:
        """Full text of one pending draft — unreviewed material, not
        canon."""
        p = self._draft_path(path)
        if not p.is_file():
            raise StoreError(
                f"no such draft: {path} — list_drafts shows what is "
                "pending")
        return p.read_text(encoding="utf-8")

    def promote_draft(self, path: str) -> str:
        """Move one approved draft to its canonical location and commit.

        The destination is derived by stripping the drafts prefix — slugs
        made the two trees mirror. Order matters: every refusal fires
        before the filesystem changes, so a refused promotion leaves the
        draft exactly where it was."""
        p = self._draft_path(path)
        if not p.is_file():
            raise StoreError(
                f"no such draft: {path} — list_drafts shows what is "
                "pending")
        rel = p.relative_to(self.ws.root).as_posix()
        inner = p.relative_to(self._drafts())
        target = self.ws.root / inner
        target_rel = inner.as_posix()
        if target.is_file():
            # A revision: its recorded base must still match canon. None
            # (unrecorded) never equals a hash, so unverifiable shadows
            # are refused too rather than silently applied.
            base = self._load_bases().get(rel)
            if base != hashlib.sha256(target.read_bytes()).hexdigest():
                raise StoreError(
                    f"{target_rel} changed since this revision was "
                    "proposed (or its base is unrecorded) — read_entity "
                    "the current file, merge with update_draft, then "
                    "promote again")
        probe = subprocess.run(
            ["git", "-C", str(self.ws.root), "rev-parse",
             "--is-inside-work-tree"], capture_output=True, text=True)
        if probe.returncode != 0:
            raise StoreError(
                "promotion requires the workspace to be a git repository "
                "— refusing to change canon without history")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
        p.unlink()
        # Only rewrite the manifest when there is something to write: a
        # genuine prune (removing this entry, or dropping other stale
        # entries) when the file already exists, or removing this entry
        # when it was actually present. A NEW draft in a workspace with no
        # prior proposals has no manifest and no entry — rewriting then
        # would *create* .proposal-bases.json containing "{}", a file that
        # never existed, and the pathspec logic below would add it to a
        # commit whose own contract is "exactly what promotion touched".
        bases = self._load_bases()
        had_entry = rel in bases
        bases.pop(rel, None)
        if had_entry or self._bases_file().is_file():
            self._save_bases(bases)
        # Add exactly what promotion touched to the index: the target,
        # plus the removed draft and the manifest when git can see them
        # (a never-tracked deleted path would fail `git add` as an
        # unmatched pathspec).
        bases_rel = self._bases_file().relative_to(self.ws.root).as_posix()
        spec = [target_rel]
        for cand in (rel, bases_rel):
            tracked = subprocess.run(
                ["git", "-C", str(self.ws.root), "ls-files", "--", cand],
                capture_output=True, text=True).stdout.strip()
            if tracked or (self.ws.root / cand).exists():
                spec.append(cand)
        for sub in (["add", "-A", "--"] + spec,
                    ["commit", "-m", f"serve-mcp: promote {target_rel}"]):
            done = subprocess.run(["git", "-C", str(self.ws.root)] + sub,
                                  capture_output=True, text=True)
            if done.returncode != 0:
                raise StoreError(
                    f"git {sub[0]} failed: "
                    f"{done.stderr.strip() or done.stdout.strip()} — "
                    f"{target_rel} holds the promoted content, written but "
                    "NOT committed, and the draft was removed; commit or "
                    "inspect it by hand (do not discard it) before "
                    "retrying")
        return target_rel

    # -- inbound queue ------------------------------------------------------
    # The GM's inbound queue: material authored elsewhere, awaiting
    # extraction into proper entity files. Read-only here, and the tool
    # descriptions add "only when the GM asks". _inbound_path is the shared
    # resolver a future mark_extracted() reuses — a move tool is one new
    # method, not a rewrite (its _Done/ destination would be constructed
    # internally, not through this reader's resolver, which refuses _- and
    # .-prefixed components).

    def _inbound(self) -> Path:
        return self.ws.root / self.ws.config.inbound_dir

    def _inbound_path(self, path: str) -> Path:
        root = self.ws.root
        inbound = self._inbound()
        p = (root / path).resolve()
        if not p.is_relative_to(root):
            raise StoreError(f"path escapes the workspace: {path}")
        if not p.is_relative_to(inbound):
            raise StoreError(
                f"not an inbound path: {path} — read_inbound serves "
                f"{self.ws.config.inbound_dir}/ only; canonical files are "
                "read with read_entity")
        if any(_common.is_machinery(part)
               for part in p.relative_to(inbound).parts):
            raise StoreError(
                f"{path} is in a processed or private area of the inbound "
                "queue (_- or .-prefixed) and is never read — _Done/ holds "
                "spent source awaiting the GM's cleanup")
        return p

    def list_inbound(self) -> list[dict]:
        """Every live file in the GM's inbound queue, whatever its type:
        workspace path, and whether read_inbound can return it. Sorted,
        so two calls agree."""
        inbound = self._inbound()
        if not inbound.is_dir():
            return []
        out = []
        for p in sorted(inbound.rglob("*")):
            if not p.is_file():
                continue
            if any(_common.is_machinery(part)
                   for part in p.relative_to(inbound).parts):
                continue
            out.append({
                "path": p.relative_to(self.ws.root).as_posix(),
                "readable": p.suffix.lower() in INBOUND_SUFFIXES})
        return out

    def read_inbound(self, path: str) -> str:
        """Full text of one inbound file — the GM's unreviewed source
        material, not canon. Decoding is forgiving (errors="replace"):
        this material was generated outside the workspace."""
        p = self._inbound_path(path)
        if p.suffix.lower() not in INBOUND_SUFFIXES:
            raise StoreError(
                f"{path} is not a text format serve-mcp can return "
                f"({', '.join(sorted(INBOUND_SUFFIXES))}) — ask the GM to "
                "convert or summarize it")
        if not p.is_file():
            raise StoreError(
                f"no such inbound file: {path} — list_inbound shows the "
                "queue")
        return p.read_text(encoding="utf-8", errors="replace")

    # -- write side ---------------------------------------------------------

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
