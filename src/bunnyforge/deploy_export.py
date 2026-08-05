#!/usr/bin/env python3
"""
deploy_export.py — render Export/ into a DokuWiki staging tree.

Direction: Export/ -> staging tree. This script never writes to the workspace
and never reads the wiki.

Each exported Markdown file produces two staged pages:

  <ns>:export:<dir>:<stem>   the converted content, title from its own H1
  <ns>:<dir>:<stem>          a wrapper of two Include directives

where <ns> is campaign.namespace from campaign.toml.

The player half, <ns>:players:<dir>:<stem>, is never written here — it
belongs to the players, and the wrapper's include renders a create-link while
it does not exist.

This is the render half of the pipeline. Transport, the content manifest, and
drift detection arrive in a later change; --render-only is currently the only
supported mode.

Usage:
    python3 -m bunnyforge.deploy_export --render-only --staging /tmp/stage
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import shutil
import sys
from collections import namedtuple
from pathlib import Path

from bunnyforge._dokuwiki import (
    classify_target,
    page_id,
    page_path,
    reserved_dir_collisions,
    rewrite_wikilinks,
    to_dokuwiki,
    wrapper_text,
)
from bunnyforge._common import (
    content_dir_names,
    iter_content_files,
    markdown_links_to_wikilinks,
    target_index,
)
from bunnyforge._config import ConfigError, Workspace, resolve_workspace
from bunnyforge._dokuwiki_rpc import RpcError, translate_error
from bunnyforge._workspace import WorkspaceError

# Hand-written on the wiki and owned by nobody in this repo. Never wrapped,
# never overwritten. These are *names*, not page IDs: a page ID is
# namespace-relative, and the namespace is a per-run value (main() reads it
# from the resolved workspace's config), so render_tree derives the protected
# set from its own `base` argument — f"{base}:{name}" for name in
# PROTECTED_PAGE_NAMES — rather than from anything fixed at import.
PROTECTED_PAGE_NAMES = ("main",)

LinkIssue = namedtuple("LinkIssue", "rel line target case")

RenderResult = namedtuple(
    "RenderResult",
    "pages wrappers skipped collisions link_issues placeholder_ids")

# Link cases that are never a problem: the link either points at an exported
# page or is not a workspace-file reference at all.
ACCEPTED_CASES = ("exported", "pass-through")


def build_link_resolver(ws: Workspace, exported_rels: list[str], base: str,
                        placeholders: bool):
    """Return a `resolve` implementing the spec's link policy.

    resolve(target) -> (new_page_id | None, case), where case is one of
    'exported', 'pass-through', 'unexported', 'unresolved', 'ambiguous'.

    'unresolved' and 'ambiguous' never produce a placeholder: minting a page
    for a typo would turn a detectable error into a permanent empty page.
    'pass-through' links are left exactly as written and are not refusals.

    The resolver deliberately does not track which placeholders it decided on:
    render_tree is the single owner of that set, since it is what actually
    writes the pages (RenderResult.placeholder_ids).
    """
    workspace = ws.root
    files = iter_content_files(ws)
    content_dirs = content_dir_names(ws.config)
    index = target_index(files)
    exported = {(workspace / rel).resolve(): page_id(rel, base)
                for rel in exported_rels}

    def resolve(target: str):
        verdict = classify_target(target, index, content_dirs)
        if verdict.case != "resolved":
            return None, verdict.case
        path = verdict.path.resolve()
        wrapper_id = exported.get(path)
        if wrapper_id:
            return wrapper_id, "exported"
        if not placeholders:
            return None, "unexported"
        rel = path.relative_to(workspace.resolve()).as_posix()
        return page_id(rel, base), "unexported"

    return resolve


def render_tree(export_dir: Path, staging: Path, base: str,
                link_resolver=None) -> tuple[RenderResult, list[str]]:
    """Render every .md under export_dir into a DokuWiki page tree at staging.

    `base` is explicit and required: the namespace belongs to the workspace
    being rendered, so a default read at import time could only ever be the
    install repo's.

    Returns (RenderResult, log_lines).
    """
    rels = sorted(
        p.relative_to(export_dir).as_posix()
        for p in export_dir.rglob("*.md")
    )

    collisions = reserved_dir_collisions(rels)
    if collisions:
        return (
            RenderResult(0, 0, 0, collisions, [], set()),
            [f"  REFUSED   content directory '{c}' collides with the reserved "
             f"{base}:{c} namespace" for c in collisions],
        )

    protected_ids = frozenset(f"{base}:{name}" for name in PROTECTED_PAGE_NAMES)

    pages = wrappers = skipped = 0
    link_issues: list[LinkIssue] = []
    # Page IDs for which a zero-byte placeholder has already been written,
    # deduped across the whole tree: two exported files can both link to the
    # same unexported target, and it must be written only once.
    placeholders_written: set[str] = set()
    # Targets that a placeholder was minted for, so the log can say
    # "placeholder" for a link this run accepted rather than "REFUSED".
    placeholdered_targets: set[str] = set()
    log: list[str] = []

    def _resolve(target: str):
        # Wraps the caller's resolver so the placeholder page is written the
        # moment it is decided on, right here where `staging` is in scope —
        # build_link_resolver only knows the workspace, never the staging
        # root, so it cannot write pages itself.
        new_id, case = link_resolver(target)
        if case == "unexported" and new_id is not None:
            placeholdered_targets.add(target)
            if new_id not in placeholders_written:
                dest = page_path(new_id, staging)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(b"")
                placeholders_written.add(new_id)
        return new_id, case

    for rel in rels:
        wrapper_id = page_id(rel, base)
        content_id = page_id(rel, f"{base}:export")
        players_id = page_id(rel, f"{base}:players")

        if wrapper_id in protected_ids:
            skipped += 1
            log.append(f"  skip      {rel}  ({wrapper_id} is hand-written)")
            continue

        # The exported body may still carry the leading blank line that
        # _common.split_front_matter's body slice leaves behind; strip it so
        # a content page's H1 lands on the first line.
        body = (export_dir / rel).read_text(encoding="utf-8").lstrip()
        # Normalise `[label](target)` to `[[target|label]]` first, so markdown
        # links are subject to the same policy as wikilinks. to_dokuwiki would
        # otherwise convert them *after* the policy ran, publishing a live link
        # nothing had inspected (#21).
        body = markdown_links_to_wikilinks(body)
        if link_resolver is not None:
            body, seen = rewrite_wikilinks(body, _resolve)
            for site in seen:
                if site.case in ACCEPTED_CASES:
                    continue
                link_issues.append(
                    LinkIssue(rel, site.line, site.target, site.case))
                # Only a link this run actually rejected may say REFUSED — a
                # placeholdered link was accepted, and the run will exit 0.
                word = ("placeholder" if site.target in placeholdered_targets
                        else "REFUSED  ")
                detail = f"[[{site.target}]] ({site.case})"
                # A `.md`-suffixed target is a common mistake carried over
                # from writing a plain markdown link: the index holds bare
                # stems/aliases, so `open.md` never resolves even though
                # `open` would. Say so rather than leaving the reader to
                # guess why an apparently-real filename came back unresolved.
                if site.case == "unresolved" and site.target.lower().endswith(".md"):
                    stem = Path(site.target).stem
                    detail += (f" — target should be a bare stem or alias, "
                              f"e.g. '{stem}' rather than '{site.target}'")
                log.append(f"  {word} {rel}:{site.line}  {detail}")
        dest = page_path(content_id, staging)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(to_dokuwiki(body), encoding="utf-8")
        pages += 1

        wdest = page_path(wrapper_id, staging)
        wdest.parent.mkdir(parents=True, exist_ok=True)
        wdest.write_text(wrapper_text(content_id, players_id), encoding="utf-8")
        wrappers += 1

        log.append(f"  rendered  {rel}  -> {content_id}")

    return (RenderResult(pages, wrappers, skipped, [], link_issues,
                         placeholders_written),
            log)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bunnyforge deploy-export",
        description="Render Export/ into a DokuWiki staging tree.")
    parser.add_argument("--render-only", action="store_true",
                        help="Render to --staging and stop (currently required)")
    parser.add_argument("--staging", required=True,
                        help="Directory to write the staged page tree into")
    parser.add_argument("--export-dir", default=None,
                        help="Source directory (default: the resolved "
                             "workspace's Export/, so it follows --workspace)")
    parser.add_argument("--create-empty-placeholders", action="store_true",
                        help="Write a zero-byte page for links to workspace files "
                             "that were not exported, so the link resolves. The "
                             "page is empty, but its ID comes from the "
                             "unexported file's path, so a gm-only filename "
                             "becomes visible in the player wiki's index and "
                             "search. The run summary lists every placeholder "
                             "ID — read it before publishing.")
    parser.add_argument(
        "--workspace", metavar="PATH",
        help="Campaign workspace root (default: $BUNNYFORGE_WORKSPACE, else "
             "the nearest campaign.toml above the current directory)")
    args = parser.parse_args(argv)

    if not args.render_only:
        print("error: only --render-only is implemented; transport lands in a "
              "later change", file=sys.stderr)
        return 1

    try:
        ws = resolve_workspace(args.workspace)
    except (WorkspaceError, ConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    base = ws.config.namespace

    # Resolved here rather than as an argparse default: a default is computed
    # when the parser is built, before --workspace has been read, so it could
    # only ever name the install repo's Export/.
    export_dir = (Path(args.export_dir).expanduser().resolve()
                  if args.export_dir else ws.root / "Export")
    if not export_dir.is_dir():
        print(f"error: {export_dir} not found — run export_player.py first",
              file=sys.stderr)
        return 1

    staging = Path(args.staging).expanduser().resolve()
    if staging.exists():
        if not staging.is_dir():
            print(f"error: --staging {staging} exists and is not a directory",
                  file=sys.stderr)
            return 1
        if any(staging.iterdir()):
            print(
                f"error: --staging {staging} already exists and is not empty. "
                "Rendering into it could leave a retired page on disk from a "
                "prior run while this run still reports success — remove the "
                "directory or pick a fresh one and re-run.",
                file=sys.stderr)
            return 1

    rels = sorted(p.relative_to(export_dir).as_posix()
                  for p in export_dir.rglob("*.md"))
    # render_tree writes any placeholder pages itself (it holds `staging`);
    # build_link_resolver only ever sees the workspace, so it cannot write.
    resolver = build_link_resolver(
        ws, rels, base, args.create_empty_placeholders)
    result, log = render_tree(export_dir, staging, base, link_resolver=resolver)

    fatal = [i for i in result.link_issues
             if i.case in ("unresolved", "ambiguous")
             or (i.case == "unexported" and not args.create_empty_placeholders)]

    for line in log:
        print(line, file=sys.stderr if "REFUSED" in line else sys.stdout)

    if result.collisions:
        print(f"\nRefused: {len(result.collisions)} reserved-namespace "
              f"collision(s).", file=sys.stderr)
        return 1

    if fatal:
        print(f"\n{len(fatal)} link(s) refused. Fix the source text, or pass "
              "--create-empty-placeholders for links to real but unexported "
              "files (typos and ambiguous targets are never placeholdered).",
              file=sys.stderr)
        return 1

    print(f"\n{result.pages} page(s), {result.wrappers} wrapper(s), "
          f"{result.skipped} skipped, "
          f"{len(result.placeholder_ids)} placeholder(s).")

    if result.placeholder_ids:
        # A placeholder page is empty, but its ID is not: it spells out the
        # unexported file's path, which for a gm-only doc means publishing
        # that filename to the player wiki's index and search. Name them all,
        # so the operator sees exactly what is about to become visible.
        print("\nPlaceholder page IDs — these names become visible in the "
              "player wiki's index and search:")
        for pid in sorted(result.placeholder_ids):
            print(f"  {pid}")
    return 0


# ---------------------------------------------------------------------------
# Transport half: manifest, classification, plan/apply. The render code above
# is untouched — a deploy always uploads what it just rendered.
# ---------------------------------------------------------------------------

MANIFEST_VERSION = 1
MANIFEST_FILE = ".bunnyforge/wiki-manifest.json"
DRIFT_DIR = ".bunnyforge/wiki-drift"


class DeployError(Exception):
    """The deploy phase cannot proceed; message is user-facing."""


def page_hash(text: str) -> str:
    """Hash of what the wiki returns from get_page after a save — never of
    the bytes we sent: DokuWiki normalizes on save, and hashing our own
    bytes would make every page look self-drifted on the next run."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def classify_page(target_text: str, wiki_text: str | None,
                  manifest_hash: str | None) -> str:
    """The spec's eight-row state matrix as a pure function.

    (staged target text, current wiki text or None, manifest hash or None)
    -> one of: new, deleted-on-wiki, unchanged, update, adopt, drift,
    drift-manual-era. 'adopt' covers both resume-after-crash and the
    manual-era exact match; the two drift labels differ only in how the
    report explains them.
    """
    if wiki_text is None:
        return "new" if manifest_hash is None else "deleted-on-wiki"
    if manifest_hash is None:
        return "adopt" if target_text == wiki_text else "drift-manual-era"
    if page_hash(wiki_text) == manifest_hash:
        return "unchanged" if target_text == wiki_text else "update"
    return "adopt" if target_text == wiki_text else "drift"


def load_manifest(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise DeployError(
            f"{path} is not valid JSON: {exc}. It is the deploy baseline — "
            "restore it from git rather than deleting it.") from exc
    if not isinstance(raw, dict):
        raise DeployError(
            f"{path} is not a JSON object — it is the deploy baseline. "
            "Restore it from git rather than deleting it.")
    if raw.get("version") != MANIFEST_VERSION:
        raise DeployError(
            f"{path} has manifest version {raw.get('version')!r}; this "
            f"bunnyforge understands version {MANIFEST_VERSION}. Upgrade "
            "bunnyforge, or restore the manifest from git.")
    pages = raw.get("pages", {})
    if not isinstance(pages, dict):
        # dict() of a non-dict iterable doesn't reliably fail loudly: a list
        # of two-character strings (e.g. ["ab", "cd"]) silently becomes
        # {"a": "b", "c": "d"} instead of raising, which would corrupt the
        # manifest read rather than refuse it. Reject the shape outright.
        raise DeployError(
            f"{path} has a non-object 'pages' field "
            f"({type(pages).__name__}) — it is the deploy baseline. "
            "Restore it from git rather than deleting it.")
    return dict(pages)


def save_manifest(path: Path, pages: dict[str, str]) -> None:
    """Sorted keys so the committed manifest diffs cleanly in git."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps({"version": MANIFEST_VERSION,
                       "pages": dict(sorted(pages.items()))}, indent=1)
    path.write_text(body + "\n", encoding="utf-8")


# core.savePage refuses to create an empty page (error 132), so the render
# half's zero-byte placeholder cannot cross RPC as-is. ~~NOTOC~~ renders
# nothing, so the page displays blank while being non-empty and existing —
# which is all a placeholder is for. The one place staged bytes are not sent
# verbatim, and it carries no content.
PLACEHOLDER_BODY = "~~NOTOC~~\n"

PagePlan = namedtuple("PagePlan", "action wiki_text")
DeployPlan = namedtuple("DeployPlan", "pages orphans resolved_orphans refused")


def staged_pages(staging: Path) -> dict[str, str]:
    """Page ID -> text for every staged page, placeholder translation applied."""
    out: dict[str, str] = {}
    for path in sorted(staging.rglob("*.txt")):
        rel = path.relative_to(staging)
        pid = ":".join((*rel.parts[:-1], rel.stem))
        text = path.read_text(encoding="utf-8")
        out[pid] = text if text else PLACEHOLDER_BODY
    return out


def _protected(staged_ids, base: str) -> list[str]:
    """Belt and braces: the render half never generates these, but a render
    bug must not become a wiki write. Never fetched, never written."""
    names = {f"{base}:{name}" for name in PROTECTED_PAGE_NAMES}
    prefix = f"{base}:players:"
    return sorted(pid for pid in staged_ids
                  if pid in names or pid.startswith(prefix))


def plan_deploy(staged: dict[str, str], manifest: dict[str, str],
                fetch, base: str) -> DeployPlan:
    refused = _protected(staged, base)
    pages: dict[str, PagePlan] = {}
    for pid in sorted(staged):
        if pid in refused:
            continue
        wiki_text = fetch(pid)
        pages[pid] = PagePlan(
            classify_page(staged[pid], wiki_text, manifest.get(pid)),
            wiki_text)
    orphans: list[str] = []
    resolved: list[str] = []
    for pid in sorted(set(manifest) - set(staged)):
        # An orphan whose wiki page a human has since deleted resolves
        # itself: it drops from the manifest (in --go) instead of being
        # reported forever.
        (orphans if fetch(pid) is not None else resolved).append(pid)
    return DeployPlan(pages, orphans, resolved, refused)


def write_order(page_ids, base: str) -> list[str]:
    """Sorted page order, except each content page lands immediately before
    its wrapper — so a wrapper never points at a not-yet-written include for
    longer than one call."""
    # Dedupe up front: `present` is a set regardless, but the loop below
    # drives off `ids` — an un-deduped list would re-trigger "mate present ->
    # emit mate + self" once per repeat, breaking the exactly-once guarantee
    # this function exists to provide.
    ids = sorted(set(page_ids))
    present = set(ids)
    export_prefix = f"{base}:export:"

    def wrapper_of(pid: str) -> str:
        return f"{base}:{pid[len(export_prefix):]}"

    order: list[str] = []
    for pid in ids:
        if pid.startswith(export_prefix) and wrapper_of(pid) in present:
            continue  # emitted just before its wrapper below
        mate = f"{export_prefix}{pid[len(base) + 1:]}"
        if mate in present:
            order.append(mate)
        order.append(pid)
    return order


ApplyResult = namedtuple("ApplyResult", "written adopted failure remaining")

# Held-back actions: written only when named in --overwrite, and always
# re-baselined when written.
_HELD = ("drift", "drift-manual-era", "deleted-on-wiki")


def apply_deploy(plan: DeployPlan, staged: dict[str, str], client,
                 manifest: dict[str, str], manifest_path: Path,
                 overwrite: set[str], base: str, wiki_url: str) -> ApplyResult:
    """Perform the writes a plan calls for. Mutates `manifest` and writes it
    through to disk after each successful save, so a run that dies mid-way
    needs no resume machinery — re-running converges (unchanged / adopt).
    """
    held = {pid for pid, p in plan.pages.items() if p.action in _HELD}
    unknown = sorted(overwrite - held)
    if unknown:
        raise DeployError(
            f"--overwrite names page(s) not held back this run: "
            f"{', '.join(unknown)} — nothing to clobber.")

    to_write = [pid for pid, p in plan.pages.items()
                if p.action in ("new", "update") or pid in overwrite]
    written: list[str] = []
    adopted: list[str] = []

    for pid, p in plan.pages.items():
        if p.action == "adopt":
            manifest[pid] = page_hash(p.wiki_text)
            adopted.append(pid)
    for pid in plan.resolved_orphans:
        manifest.pop(pid, None)
    if adopted or plan.resolved_orphans:
        save_manifest(manifest_path, manifest)

    for pid in write_order(to_write, base):
        try:
            client.save_page(pid, staged[pid])
            readback = client.get_page(pid)
        except RpcError as exc:
            remaining = [i for i in write_order(to_write, base)
                         if i not in written]
            return ApplyResult(
                written, sorted(adopted),
                f"{pid}: {translate_error(exc, wiki_url)}", remaining)
        manifest[pid] = page_hash(readback or "")
        save_manifest(manifest_path, manifest)
        written.append(pid)

    return ApplyResult(written, sorted(adopted), None, [])


_HELD_REASONS = {
    "drift": "changed on the wiki since the last deploy",
    "drift-manual-era": "no baseline for it — could be hand-edits from the "
                        "manual era",
    "deleted-on-wiki": "a human deleted it on the wiki; recreating it would "
                       "clobber that decision",
}


def write_drift_copies(held: dict[str, str], drift_dir: Path) -> None:
    """Each drifted page's current wiki text, laid out like data/pages/, for
    manual merge. The tool owns this directory outright: recreated from empty
    every planning run, so a page that stops drifting leaves no stale copy."""
    if drift_dir.exists():
        shutil.rmtree(drift_dir)
    drift_dir.mkdir(parents=True)
    for pid, wiki_text in held.items():
        dest = page_path(pid, drift_dir)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(wiki_text, encoding="utf-8")


def format_deploy_report(plan: DeployPlan, staged: dict[str, str],
                         overwrite: set[str], go: bool) -> tuple[list[str], bool]:
    lines: list[str] = []
    held_pages = []
    for pid in sorted(plan.pages):
        p = plan.pages[pid]
        if p.action in _HELD and pid not in overwrite:
            held_pages.append(pid)
            continue
        word = "overwrite" if pid in overwrite else p.action
        lines.append(f"  {word:<12} {pid}")
    for pid in plan.refused:
        lines.append(f"  refused      {pid}  (protected page — never written)")

    for pid in held_pages:
        p = plan.pages[pid]
        lines.append(f"\n  HELD  {pid} — {_HELD_REASONS[p.action]}")
        if p.wiki_text is not None:
            diff = difflib.unified_diff(
                p.wiki_text.splitlines(keepends=True),
                staged[pid].splitlines(keepends=True),
                fromfile="wiki (current)", tofile="deploy (target)")
            lines.extend("    " + line.rstrip("\n") for line in diff)
    if held_pages:
        lines.append(
            "\nHeld-back pages: pull the wiki edit into the workspace source "
            "(the next render then matches and the drift disappears), or "
            "re-run with --overwrite <page-id> --go to clobber that page "
            "and re-baseline it. Current wiki text saved under "
            f"{DRIFT_DIR}/ for manual merge.")

    for pid in plan.orphans:
        lines.append(
            f"  orphan       {pid} — in the manifest but no longer staged; "
            "removing the wiki page is a manual act, this tool never "
            "deletes.")
    for pid in plan.resolved_orphans:
        lines.append(
            f"  resolved     {pid} — deleted on the wiki; "
            + ("dropped from the manifest." if go else
               "will drop from the manifest on --go."))

    held_or_orphaned = bool(held_pages or plan.orphans)
    return lines, held_or_orphaned


def run_deploy(ws, staging: Path, client, go: bool, overwrite: set[str],
               wiki_url: str) -> int:
    """Plan, report, copy drift, and (with go) apply. Exit-code contract:
    non-zero if anything was held back or any orphan was reported, in both
    modes — matching the render half's fail-loudly posture."""
    base = ws.config.namespace
    manifest_path = ws.root / MANIFEST_FILE
    manifest = load_manifest(manifest_path)
    staged = staged_pages(staging)

    try:
        plan = plan_deploy(staged, manifest, client.get_page, base)
    except RpcError as exc:
        print(f"error: {translate_error(exc, wiki_url)}", file=sys.stderr)
        return 1

    held = {pid: p.wiki_text for pid, p in plan.pages.items()
            if p.action in _HELD and pid not in overwrite
            and p.wiki_text is not None}
    # Copies are part of reporting, not deployment: written in both modes.
    write_drift_copies(held, ws.root / DRIFT_DIR)

    lines, held_or_orphaned = format_deploy_report(plan, staged, overwrite, go)
    print("\n".join(lines))

    if go:
        result = apply_deploy(plan, staged, client, manifest, manifest_path,
                              overwrite, base, wiki_url)
        for pid in result.written:
            print(f"  saved        {pid}")
        if result.failure:
            print(f"\nerror: {result.failure}", file=sys.stderr)
            print(f"Written before the failure: "
                  f"{', '.join(result.written) or 'nothing'}.\n"
                  f"Not yet written: {', '.join(result.remaining)}.\n"
                  "Re-run to converge — already-written pages classify as "
                  "unchanged or adopt.", file=sys.stderr)
            return 1
        print(f"\nDeployed {len(result.written)} page(s), "
              f"adopted {len(result.adopted)}.")
    else:
        writes = sum(1 for pid, p in plan.pages.items()
                     if p.action in ("new", "update") or pid in overwrite)
        print(f"\nDry run: {writes} page(s) would be written. "
              "Re-run with --go to deploy.")

    return 1 if held_or_orphaned else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        sys.stderr.close()
        raise SystemExit(0)
