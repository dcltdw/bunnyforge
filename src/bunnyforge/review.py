#!/usr/bin/env python3
"""
review.py — run a named suite of workspace checks on demand.

Approach A: a CHECKS registry maps names to check functions, and SUITES maps a
suite name to a list of check names. Each check consumes the enumerated content
files and returns Finding records.

Future expansion (approach B, not built): if checks outgrow this file, migrate
to a checks/ package directory auto-discovered at load. The CHECKS
registry stays the interface; only how it is populated changes.

Usage:
    python3 -m bunnyforge.review checkup
    python3 -m bunnyforge.review checkup --html
    python3 -m bunnyforge.review checkup --workspace /path/to/campaign
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from collections import namedtuple
from pathlib import Path

# Imported as a module as well as by name: tests reach through
# review._common for the enumerator, so this is load-bearing despite no
# `_common.` reference in this file's own code.
from bunnyforge import _common  # noqa: F401
from bunnyforge._common import (
    FileRec,
    content_dir_names,
    is_pass_through_target,
    iter_content_files,
    markdown_links_to_wikilinks,
    normalize_visibility,
    resolve_target,
    strip_yaml_comment,
    target_index,
)
from bunnyforge import _dokuwiki_install as dwi
from bunnyforge._dokuwiki_install import InstallError
from bunnyforge._config import ConfigError, Workspace, resolve_workspace
from bunnyforge._workspace import WorkspaceError

Finding = namedtuple("Finding", "severity check file message")


def _rel(path: Path, workspace: Path) -> str:
    return path.relative_to(workspace).as_posix()


VALID_CANON = {"canon", "draft", "speculative", "perception"}
VALID_VISIBILITY = {"gm-only", "player-visible", "mixed"}


def write_html(suite: str, findings: list[Finding], workspace: Path) -> Path:
    """Write Reviews/<suite>.html under `workspace` and return its path.

    Takes the root rather than a whole Workspace, matching the convention the
    checks below follow: each takes exactly what it needs, and this needs no
    config.
    """
    def esc(s: str) -> str:
        return html.escape(s)

    issues = [f for f in findings if f.check != "visibility-audit"]
    audit = [f for f in findings if f.check == "visibility-audit"]

    issue_rows = "\n".join(
        f"<tr class='{esc(f.severity)}'><td>{esc(f.severity)}</td>"
        f"<td>{esc(f.check)}</td><td>{esc(f.file)}</td><td>{esc(f.message)}</td></tr>"
        for f in sorted(issues, key=lambda x: (x.severity, x.file))
    ) or "<tr><td colspan='4'>No issues.</td></tr>"

    audit_rows = "\n".join(
        f"<tr><td>{esc(f.file)}</td><td>{esc(f.message)}</td></tr>"
        for f in sorted(audit, key=lambda x: x.file)
    ) or "<tr><td colspan='2'>No entity files.</td></tr>"

    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{esc(suite)} review</title>
<style>
 body {{ font: 15px/1.5 system-ui, sans-serif; margin: 2rem; color: #1a1614; }}
 table {{ border-collapse: collapse; margin: 1rem 0; width: 100%; }}
 th, td {{ text-align: left; padding: .35rem .6rem; border-bottom: 1px solid #ddd; }}
 tr.error td {{ color: #7c2d2d; font-weight: 600; }}
 tr.warn td {{ color: #8a6a1c; }}
 h1, h2 {{ font-weight: 600; }}
</style></head><body>
<h1>{esc(suite)} review</h1>
<h2>Issues</h2>
<table><tr><th>severity</th><th>check</th><th>file</th><th>message</th></tr>
{issue_rows}
</table>
<h2>Visibility audit</h2>
<table><tr><th>file</th><th>audience</th></tr>
{audit_rows}
</table>
</body></html>
"""
    out_dir = workspace / "Reviews"
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{suite}.html"
    dest.write_text(doc, encoding="utf-8")
    return dest


def check_front_matter(files: list[FileRec], workspace: Path) -> list[Finding]:
    out: list[Finding] = []
    for rec in files:
        if rec.category != "entity":
            continue
        rel = _rel(rec.path, workspace)
        fm = rec.fm

        if not fm.get("type", "").strip():
            out.append(Finding("error", "front-matter", rel, "missing `type`"))

        canon = strip_yaml_comment(fm.get("canon", "")).lower()
        if not canon:
            out.append(Finding("error", "front-matter", rel, "missing `canon`"))
        elif canon not in VALID_CANON:
            out.append(Finding("error", "front-matter", rel, f"invalid canon: {canon}"))

        vis = strip_yaml_comment(fm.get("visibility", "")).lower()
        if not vis:
            out.append(Finding("error", "front-matter", rel, "missing `visibility`"))
        elif vis not in VALID_VISIBILITY:
            out.append(Finding("error", "front-matter", rel, f"invalid visibility: {vis}"))

        # strip_yaml_comment only trims a ` # comment` suffix (whitespace,
        # then `#`); _common.split_front_matter already strips leading
        # whitespace from every field value, so a comment-only value like
        # `summary: # fill me in` always has `#` as its very first
        # character and strip_yaml_comment's `\s+#` pattern can never match
        # it (verified by probe: strip_yaml_comment is a no-op here). Treat
        # a value beginning with `#` as empty locally, in this check, rather
        # than in strip_yaml_comment/split_front_matter -- those parsers are
        # shared with build_sheets.py, and this is the only place
        # "comment-only counts as missing" matters.
        summary = strip_yaml_comment(fm.get("summary", ""))
        if not summary or summary.startswith("#"):
            out.append(Finding("warn", "front-matter", rel, "missing `summary`"))
    return out


# The checks below deliberately take different things: check_wikilinks and
# check_compendium need a Workspace (for its config's content-directory names
# and compendium_dirs), while check_visibility_audit and check_reveal_when
# need only the workspace root, for `_rel`. Each takes what it needs rather
# than a uniform Workspace everywhere — this asymmetry is intentional, not an
# oversight left over from threading.
def check_visibility_audit(files: list[FileRec], workspace: Path) -> list[Finding]:
    out: list[Finding] = []
    for rec in files:
        if rec.category != "entity":
            continue
        vis = normalize_visibility(rec.fm)
        message = vis
        if vis == "gm-only":
            reveal = strip_yaml_comment(rec.fm.get("reveal_when", ""))
            if reveal:
                message = f"gm-only · reveals: {reveal}"
        elif vis == "mixed":
            message = "mixed"
        out.append(Finding("info", "visibility-audit", _rel(rec.path, workspace), message))
    return out


_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
# This workspace's convention (AGENTS.md) is to write wikilinks inside
# backticks: `[[entity-name]]`. A code span containing nothing but one
# wikilink is unwrapped before the ordinary inline-code strip runs, so the
# link inside it is still extracted; multi-token or prose-bearing spans are
# untouched here and fall to the ordinary strip below.
_WIKILINK_CODE_SPAN_RE = re.compile(r"`(\[\[[^`\n]*\]\])`")


def _unwrap_single_wikilink_span(m: re.Match) -> str:
    raw = m.group(1)
    if raw.count("[[") == 1:
        return raw
    return m.group(0)


def extract_wikilinks(body: str) -> list[str]:
    text = _FENCE_RE.sub("", body)
    text = _WIKILINK_CODE_SPAN_RE.sub(_unwrap_single_wikilink_span, text)
    text = _INLINE_CODE_RE.sub("", text)
    text = _HTML_COMMENT_RE.sub("", text)
    text = markdown_links_to_wikilinks(text)
    targets = []
    for raw in _WIKILINK_RE.findall(text):
        target = raw.split("|", 1)[0].split("#", 1)[0].strip()
        if target:
            targets.append(target)
    return targets




def check_wikilinks(files: list[FileRec], ws: Workspace) -> list[Finding]:
    workspace = ws.root
    content_dirs = content_dir_names(ws.config)
    index = target_index(files)

    out: list[Finding] = []
    for rec in files:
        for target in extract_wikilinks(rec.body):
            t = target.lower()
            # Bare content-directory names ([[Mechanics]]), external URLs and
            # the other non-file link forms are legitimate targets, not broken
            # links. _common owns that notion so deploy_export's link policy
            # applies exactly the same one (its 'pass-through' case).
            resolves = bool(resolve_target(t, index)) \
                or is_pass_through_target(t, content_dirs)
            if not resolves:
                out.append(Finding("warn", "wikilinks", _rel(rec.path, workspace),
                                   f"broken wikilink: [[{target}]]"))
    return out


def check_compendium(files: list[FileRec], ws: Workspace) -> list[Finding]:
    workspace = ws.root
    comp = workspace / "compendium.md"
    index = target_index(files)
    indexed_paths: set[Path] = set()
    if comp.is_file():
        for target in extract_wikilinks(comp.read_text(encoding="utf-8")):
            indexed_paths |= resolve_target(target, index)

    out: list[Finding] = []
    for rec in files:
        if rec.category != "entity":
            continue
        if rec.path.relative_to(workspace).parts[0] not in ws.config.compendium_dirs:
            continue
        if rec.path not in indexed_paths:
            out.append(Finding("warn", "compendium", _rel(rec.path, workspace),
                               "not indexed in compendium.md"))
    return out


def check_reveal_when(files: list[FileRec], workspace: Path) -> list[Finding]:
    out: list[Finding] = []
    for rec in files:
        if rec.category != "entity":
            continue
        reveal = strip_yaml_comment(rec.fm.get("reveal_when", ""))
        if reveal and normalize_visibility(rec.fm) != "gm-only":
            out.append(Finding("warn", "reveal-when", _rel(rec.path, workspace),
                               "reveal_when on a non-gm-only file (meaningless)"))
    return out


# ---------------------------------------------------------------------------
# The wiki suite.
#
# These checks are unlike every other check here: they assert nothing about
# the workspace and everything about a live DokuWiki install, which they take
# as a filesystem path. They exist because the two most severe failures on
# record were both live-config drift that no unit test could have caught, and
# both were found by ad-hoc manual poking rather than by anything that would
# catch a recurrence.
#
# Every invariant below is stated as a universal rule naming no namespace and
# no group, so the suite is portable to any campaign on any wiki. The one
# invariant that cannot be stated that way — that GM namespaces resolve to
# NONE for player groups — needs effective-permission resolution and
# campaign-specific configuration, and is deliberately not built here.
#
# Run this after every DokuWiki upgrade. An upgrade is precisely when this
# drifts.
# ---------------------------------------------------------------------------

# Config files an upgrade will not overwrite. A setting that is correct but
# lives anywhere else is one upgrade away from silently reverting, which is
# exactly how a wiki was left world-readable and world-writable for five days.
_UPGRADE_SAFE_CONF = ("local.php", "local.protected.php")

# The export's wrapper design is composed entirely of this plugin's include
# directives; without it every wrapper page renders as literal markup.
_REQUIRED_PLUGIN = "include"


def check_wiki_conf(files: list[FileRec], wiki_root: Path) -> list[Finding]:
    conf = dwi.read_conf(wiki_root)
    out: list[Finding] = []

    useacl = conf.get("useacl")
    if useacl is None or not useacl.value:
        out.append(Finding("error", "wiki-conf", "conf/",
                           "useacl is not enabled — the wiki is world-readable "
                           "and world-writable"))
    elif useacl.source not in _UPGRADE_SAFE_CONF:
        out.append(Finding("error", "wiki-conf", f"conf/{useacl.source}",
                           f"useacl is enabled but set in {useacl.source}, which "
                           f"DokuWiki upgrades overwrite — move it to "
                           f"conf/local.php"))

    useheading = conf.get("useheading")
    if useheading is None or not useheading.value:
        out.append(Finding("warn", "wiki-conf", "conf/",
                           "useheading is not set — wrapper pages will display "
                           "raw page IDs instead of their included heading"))
    return out


def check_wiki_acl(files: list[FileRec], wiki_root: Path) -> list[Finding]:
    rules = dwi.read_acl(wiki_root)
    # A scope that grants to a group must also say what everyone else gets at
    # that same scope. Otherwise an account outside the group falls through to
    # a broader rule — which is how a GM namespace ended up editable by any
    # logged-in account, while every anonymous spot-check looked clean.
    #
    # Stated as one rule over whatever scopes exist, so a newly added
    # namespace is covered by default rather than needing to be enumerated
    # here. It deliberately does not demand the fall-through rule be level 0:
    # a read-only @user 1 is a legitimate answer, and requiring 0 would be
    # policy. The defect is the silence, not the level.
    granted_to_group = {r.scope for r in rules
                        if r.principal.startswith("@") and r.level > 0}
    has_fallthrough = {r.scope for r in rules
                       if r.principal.lower() in ("@all", "@user")}
    return [
        Finding("error", "wiki-acl", "conf/acl.auth.php",
                f"{scope} grants to a group but sets no @ALL or @user rule of "
                f"its own — accounts outside that group fall through to a "
                f"broader rule")
        for scope in sorted(granted_to_group - has_fallthrough)
    ]


def check_wiki_plugins(files: list[FileRec], wiki_root: Path) -> list[Finding]:
    installed, enabled = dwi.plugin_state(wiki_root, _REQUIRED_PLUGIN)
    if not installed:
        return [Finding("error", "wiki-plugins", "lib/plugins/",
                        f"the {_REQUIRED_PLUGIN} plugin is not installed — "
                        f"every wrapper page depends on it")]
    if not enabled:
        return [Finding("error", "wiki-plugins", "conf/plugins.local.php",
                        f"the {_REQUIRED_PLUGIN} plugin is installed but "
                        f"disabled — every wrapper page depends on it")]
    return []


# remoteuser's stock value is a placeholder DokuWiki treats as
# not-configured; the check must treat it as unset, not as a scoping.
_REMOTEUSER_UNSET = "!!not set!!"


def check_wiki_remote(files: list[FileRec], wiki_root: Path) -> list[Finding]:
    """The deploy transport's preconditions, stated as universal rules.

    A disabled API is a legitimate secure state and yields no finding — the
    deploy's own -32605 translation owns that path. Built on read_conf: no
    network, so the suite stays runnable against a filesystem copy and CI
    never needs a live wiki.
    """
    conf = dwi.read_conf(wiki_root)
    remote = conf.get("remote")
    if remote is None or not remote.value:
        return []
    out: list[Finding] = []
    if remote.source not in _UPGRADE_SAFE_CONF:
        out.append(Finding(
            "error", "wiki-remote", f"conf/{remote.source}",
            f"remote is enabled but set in {remote.source}, which DokuWiki "
            f"upgrades overwrite — move it to conf/local.php"))
    ru = conf.get("remoteuser")
    value = str(ru.value).strip() if ru and ru.value is not None else ""
    if not value or value == _REMOTEUSER_UNSET:
        out.append(Finding(
            "error", "wiki-remote", "conf/",
            "remote is enabled but remoteuser is unset or empty — every "
            "wiki account can call the API; scope it to the deploy user in "
            "conf/local.php"))
    elif ru.source not in _UPGRADE_SAFE_CONF:
        # remoteuser holds the actual security boundary — remote merely
        # turns the API on. A scoped value that lives outside local.php is
        # one upgrade away from reverting to the stock placeholder, at
        # which point every account regains API access, unremarked. Same
        # failure the `remote` provenance rule above exists to prevent, on
        # the more dangerous of the two settings.
        out.append(Finding(
            "error", "wiki-remote", f"conf/{ru.source}",
            f"remoteuser is set but from {ru.source}, which DokuWiki "
            f"upgrades overwrite — move it to conf/local.php"))
    return out


CHECKS = {
    "visibility-audit": check_visibility_audit,
    "front-matter": check_front_matter,
    "wikilinks": check_wikilinks,
    "compendium": check_compendium,
    "reveal-when": check_reveal_when,
    "wiki-conf": check_wiki_conf,
    "wiki-acl": check_wiki_acl,
    "wiki-plugins": check_wiki_plugins,
    "wiki-remote": check_wiki_remote,
}

SUITES = {
    "checkup": ["visibility-audit", "front-matter", "wikilinks",
                "compendium", "reveal-when"],
    # Deliberately not part of checkup: it needs a live install, which CI does
    # not have. Keeping it a separate suite is the whole skippability
    # mechanism — checkup never reaches off the local machine.
    "wiki": ["wiki-conf", "wiki-acl", "wiki-plugins", "wiki-remote"],
}

# Checks that need the full Workspace (its config), rather than just the
# root — see the comment above check_visibility_audit for why the family is
# split this way.
_NEEDS_WORKSPACE = frozenset({"wikilinks", "compendium"})
# Checks taking a DokuWiki install root instead of anything from the
# workspace — a third argument shape, alongside Workspace and workspace root.
_NEEDS_WIKI = frozenset({"wiki-conf", "wiki-acl", "wiki-plugins", "wiki-remote"})


def run_suite(suite: str, ws: Workspace,
              wiki_root: Path | None = None) -> list[Finding]:
    names = SUITES[suite]
    # The wiki checks ignore `files` entirely, so a wiki-only suite must not
    # pay a full content walk it will never read.
    files = [] if all(n in _NEEDS_WIKI for n in names) else iter_content_files(ws)
    findings: list[Finding] = []
    for name in names:
        if name in _NEEDS_WIKI:
            arg = wiki_root
        elif name in _NEEDS_WORKSPACE:
            arg = ws
        else:
            arg = ws.root
        findings.extend(CHECKS[name](files, arg))
    return findings


def format_terminal(findings: list[Finding], suite: str) -> str:
    lines: list[str] = []

    audit = [f for f in findings if f.check == "visibility-audit"]
    if audit:
        lines.append("visibility-audit")
        last_dir = None
        for f in sorted(audit, key=lambda x: x.file):
            d = f.file.rsplit("/", 1)[0] if "/" in f.file else "."
            if d != last_dir:
                lines.append(f"  {d}/")
                last_dir = d
            name = f.file.rsplit("/", 1)[-1]
            lines.append(f"    {name:<28} {f.message}")
        lines.append("")

    issues = [f for f in findings if f.check != "visibility-audit"]
    marks = {"error": "✗", "warn": "!", "info": "·"}
    for name in [n for n in SUITES.get(suite, []) if n != "visibility-audit"]:
        block = [f for f in issues if f.check == name]
        lines.append(f"{name}  ({len(block)} finding(s))")
        for f in sorted(block, key=lambda x: (x.severity, x.file)):
            lines.append(f"  {marks.get(f.severity, '·')} {f.file}: {f.message}")
        lines.append("")

    errs = sum(1 for f in findings if f.severity == "error")
    warns = sum(1 for f in findings if f.severity == "warn")
    lines.append(f"Summary: {errs} error(s), {warns} warning(s).")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bunnyforge review", description="Run a named workspace review suite.")
    parser.add_argument("suite", nargs="?", default="checkup",
                        help=f"Suite to run (default: checkup). Known: {', '.join(SUITES)}")
    parser.add_argument("--html", action="store_true",
                        help="Also write an HTML report to Reviews/<suite>.html")
    parser.add_argument(
        "--workspace", metavar="PATH",
        help="Campaign workspace root (default: $BUNNYFORGE_WORKSPACE, else "
             "the nearest campaign.toml above the current directory)")
    parser.add_argument(
        "--wiki-root", metavar="PATH",
        help="DokuWiki installation root (the directory holding conf/ and "
             "lib/). Required by the 'wiki' suite; ignored by every other.")
    args = parser.parse_args(argv)

    if args.suite not in SUITES:
        parser.error(f"unknown suite: {args.suite}. Known: {', '.join(SUITES)}")

    # Required conditionally rather than globally: making --wiki-root
    # mandatory would break checkup, which never touches a wiki.
    wiki_root = None
    if any(name in _NEEDS_WIKI for name in SUITES[args.suite]):
        if not args.wiki_root:
            print(f"error: the '{args.suite}' suite needs --wiki-root PATH "
                  f"(the DokuWiki installation root, holding conf/ and lib/)",
                  file=sys.stderr)
            return 1
        wiki_root = Path(args.wiki_root).expanduser().resolve()

    try:
        ws = resolve_workspace(args.workspace)
    except (WorkspaceError, ConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:
        findings = run_suite(args.suite, ws, wiki_root)
    except InstallError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(format_terminal(findings, args.suite))

    if args.html:
        dest = write_html(args.suite, findings, ws.root)
        print(f"\nHTML report: {dest.relative_to(ws.root)}")

    return 1 if any(f.severity == "error" for f in findings) else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        sys.stderr.close()
        raise SystemExit(0)
