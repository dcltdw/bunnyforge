#!/usr/bin/env python3
"""
run_tests.py — the single entry point for this workspace's test suite.

CI and humans both invoke this, so the two cannot drift. If discovery settings
ever need to change they change here, and every caller follows.

Usage:
    python3 -m bunnyforge.run_tests
    python3 -m bunnyforge.run_tests -v
    bunnyforge test [-v]        (once stage 3's dispatcher is installed)
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import unittest
from pathlib import Path

from bunnyforge import _workspace

# Directories and files that change as a side effect of running Python or the
# local agent tooling, rather than as a side effect of a test writing where it
# should not. Everything else in the workspace is content -- including the
# git-ignored Export/, Reviews/ and _Ignore/, which is the whole point: a leak
# into any of those leaves `git status` clean, which is how two of them went
# unnoticed (issue #61).
_IGNORED_DIRS = frozenset({".git", "__pycache__", ".superpowers", ".claude"})
_IGNORED_NAMES = frozenset({".DS_Store"})


def _is_ignored(rel: Path) -> bool:
    for part in rel.parts[:-1]:
        if part in _IGNORED_DIRS or part.endswith(".egg-info"):
            return True
    return (rel.name in _IGNORED_NAMES
            or rel.name in _IGNORED_DIRS
            or rel.suffix == ".pyc")


def _snapshot(root: Path) -> dict[str, str]:
    """Map workspace-relative path -> content hash, for every content file.

    Hashes contents rather than recording (size, mtime): a regenerated file
    is often the same length as the one it replaced, and mtime granularity
    is coarse enough to miss a fast rewrite.
    """
    snap: dict[str, str] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if _is_ignored(rel):
            continue
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            # Vanished or unreadable mid-walk. Record the fact rather than
            # crashing: if it differs between the two snapshots, that IS the
            # change we are looking for.
            digest = "<unreadable>"
        snap[rel.as_posix()] = digest
    return snap


def _describe_changes(before: dict[str, str],
                      after: dict[str, str]) -> list[str]:
    """Human-readable lines, one per changed path. Empty when nothing moved."""
    lines = [f"  added:    {p}" for p in sorted(set(after) - set(before))]
    lines += [f"  removed:  {p}" for p in sorted(set(before) - set(after))]
    lines += [f"  modified: {p}" for p in sorted(
        p for p in set(before) & set(after) if before[p] != after[p])]
    return lines


def _no_tests_card(*, scaffolded: bool) -> str:
    """Guidance for a workspace with nothing to run.

    Not an error: it goes to stdout and the caller exits 0. The file
    bullets appear only when those files exist to be pointed at -- a
    workspace created before init scaffolded tests/ gets the URL alone,
    because pointing someone at a file they do not have is worse than the
    terseness this replaced.
    """
    lines = [
        "No campaign tests yet — nothing to run.",
        "",
        "Campaign tests check the things `bunnyforge review checkup` can't"
        " know",
        "about your setting: \"every NPC's faction actually exists\", \"no"
        " session",
        'refers to a later session".',
        "",
    ]
    if scaffolded:
        lines += [
            "  * What they are and how to write them:  tests/README.md",
            "  * A worked example to uncomment:        tests/test_example.py",
            "",
        ]
    lines.append(f"Guided start: {_workspace.DOCS_URL}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bunnyforge test", description="Run the workspace test suite.")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Print each test as it runs")
    args = parser.parse_args(argv)

    # No --workspace flag here, deliberately: you run a workspace's suite by
    # being in it (or naming it in the environment), the way CI does. The
    # resolution is otherwise the same as every other tool's, and so is the
    # failure — one error: line, not a traceback.
    #
    # suggest_flag=False follows from that: the shared message would
    # otherwise end "or pass --workspace", and passing it here is an
    # argparse error with exit 2. The two remedies that do apply are still
    # named.
    try:
        workspace = _workspace.resolve_root(suggest_flag=False)
    except _workspace.WorkspaceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # Having no tests is a state, not a fault: a workspace is perfectly
    # valid without them, and a beginner meeting discovery's raw
    # ImportError here learns nothing. Classify first, so every outcome is
    # a sentence the user can act on.
    tests_dir = workspace / "tests"
    if not tests_dir.is_dir():
        print(_no_tests_card(scaffolded=False))
        return 0
    try:
        suite = unittest.TestLoader().discover(
            str(tests_dir), top_level_dir=str(workspace))
    except ImportError:
        # Unlike the two cases above this IS a fault -- the directory may
        # hold real tests that nobody can see -- so it exits 1. The cause
        # is almost always the missing package marker.
        print(f"error: {tests_dir} exists, but Python cannot read it as a "
              f"test folder.\n"
              f"\n"
              f"Fix: create an empty file named __init__.py inside "
              f"{tests_dir}\n"
              f"Then re-run: bunnyforge test",
              file=sys.stderr)
        return 1
    if suite.countTestCases() == 0:
        print(_no_tests_card(
            scaffolded=(tests_dir / "README.md").is_file()))
        return 0

    # Bracket the run: a test that writes into the workspace it is testing
    # corrupts real campaign content and, worse, does it quietly. Snapshot
    # either side and fail the run on any difference, so the suite cannot
    # pass while having damaged the thing it ran against.
    before = _snapshot(workspace)
    result = unittest.TextTestRunner(
        verbosity=2 if args.verbose else 1).run(suite)
    changes = _describe_changes(before, _snapshot(workspace))

    if changes:
        print(f"\nerror: the test run modified its own workspace "
              f"({workspace}). Tests must write only into temporary "
              f"directories.", file=sys.stderr)
        print("\n".join(changes), file=sys.stderr)
        print("\nNote: Export/, Reviews/ and _Ignore/ are git-ignored, so "
              "`git status` will not show writes there.", file=sys.stderr)
        return 1

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        sys.stderr.close()
        raise SystemExit(0)
