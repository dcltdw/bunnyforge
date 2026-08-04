#!/usr/bin/env python3
"""
cli.py — the `bunnyforge` front door: one command, eight subcommands.

Only the first token is parsed here; everything after it passes to the
target module's main(argv) verbatim. This parser never mirrors a tool's
flags, so it cannot drift from them, and `bunnyforge review --help` is
answered by review itself. Module invocations (`python3 -m
bunnyforge.review`) keep working unchanged: the dispatcher adds a front
door, it does not move the house.

The `bunnyforge` command itself is not a file in this package. pyproject's
`[project.scripts]` entry tells pip to generate a small launcher in the
environment's bin/ at install time, whose whole body is `from bunnyforge.cli
import main; sys.exit(main())`. That is why `bunnyforge <cmd>` and `python3
-m bunnyforge <cmd>` reach this function by different routes, and why
grepping the source for the command name finds nothing.

Deliberately NOT argparse subparsers + nargs=REMAINDER: measured on Python
3.13, a leading option-like token (`bunnyforge review --help`) is never
handed to REMAINDER and dies as "unrecognized arguments" — the exact case
the contract requires to work.
"""

from __future__ import annotations

import argparse
import sys

from bunnyforge import (
    build_sheets,
    deploy_export,
    export_player,
    generate_names,
    import_perceptions,
    init,
    review,
    run_tests,
)

# Subcommand -> the module main(argv) it forwards to, in the order --help
# lists them.
_COMMANDS = {
    "init": init.main,
    "review": review.main,
    "export-player": export_player.main,
    "deploy-export": deploy_export.main,
    "import-perceptions": import_perceptions.main,
    "build-sheets": build_sheets.main,
    "names": generate_names.main,
    "test": run_tests.main,
}

# One neutral line per command, shown by --help. Kept next to _COMMANDS so
# adding a subcommand without describing it is a visible omission.
_SUMMARIES = {
    "init": "scaffold a new campaign workspace",
    "review": "run a named workspace review suite",
    "export-player": "write player-safe copies of content files to Export/",
    "deploy-export": "render Export/ into a DokuWiki staging tree",
    "import-perceptions": "import player-authored wiki pages into Perceptions/",
    "build-sheets": "build one-page HTML reference sheets for a session",
    "names": "generate culture-appropriate names",
    "test": "run the workspace test suite",
}


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    # RawDescriptionHelpFormatter so the epilog lists one command per line:
    # the default formatter re-wraps prose and splits hyphenated names like
    # import-perceptions across lines, which breaks searching help output.
    parser = argparse.ArgumentParser(
        prog="bunnyforge",
        description="Tools for running a TTRPG campaign workspace.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="commands:\n" + "\n".join(
            f"  {name:<20} {_SUMMARIES[name]}" for name in _COMMANDS)
        + "\n\nRun 'bunnyforge <command> --help' for a command's own options.")
    parser.add_argument("command", choices=_COMMANDS, metavar="command",
                        help="one of the commands listed below")

    try:
        # Parse only the first token. Everything after it belongs to the
        # tool — including --help, which the tool must answer, not this
        # parser.
        args = parser.parse_args(argv[:1])
        return _COMMANDS[args.command](argv[1:])
    except BrokenPipeError:
        # Same contract as every module's __main__ block: a closed pipe
        # (e.g. `| head`) is a normal end, not an error.
        sys.stderr.close()
        return 0
