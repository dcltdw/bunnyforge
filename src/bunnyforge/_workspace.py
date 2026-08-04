#!/usr/bin/env python3
"""
_workspace.py — find the campaign workspace.

The workspace is the directory holding campaign.toml. Until Phase 2 the tool
derived it from its own file location, which stops meaning anything once the
code is an installed package. Resolution order, first hit wins:

    1. the --workspace flag
    2. the BUNNYFORGE_WORKSPACE environment variable
    3. the nearest campaign.toml walking up from the current directory

Step 1 belongs to the callers: every main() takes the flag and hands it to
_config.resolve_workspace, which falls through to resolve_root() here for
steps 2 and 3. run_tests is the one exception — it has no flag, so it calls
resolve_root() directly with suggest_flag=False and its card omits the
bullet it cannot honour. When none of the three yields a
workspace, that is an error —
there is no fourth step. There used to be one, the repository this package
was installed (editable) from, and it was a trap: a published package has no
install repo, and while it existed a tool run from the wrong directory
silently operated on whatever campaign happened to be next to the code.

Nothing here resolves at import. Resolution happens inside main(), once,
into a Workspace that is then threaded explicitly.

Stdlib only.
"""

from __future__ import annotations

import os
from pathlib import Path

CONFIG_NAME = "campaign.toml"

# The one place the public documentation pointer lives; run_tests imports it
# too, so a moved README is a one-line change rather than a grep.
DOCS_URL = "https://github.com/dcltdw/bunnyforge#readme"


class WorkspaceError(Exception):
    """No campaign workspace could be found. The message is user-facing."""


def _card(first_line: str, suggest_flag: bool) -> str:
    """The full "no workspace" instruction card.

    One composition point for every failure path (the reason the older
    _remedies() existed), but instructional per the 2026-08-03 ruling:
    state the fault, then the user's real options, then somewhere to go.
    The card IS the exception message; callers add the "error: " prefix
    when they print it, so it must not start with one itself.

    BUNNYFORGE_WORKSPACE is deliberately absent. It is an operator
    convenience, documented in --help and the README, and burying a
    beginner's two real options under three is the failure mode the ruling
    names.

    `suggest_flag` adds the --workspace bullet only for callers whose
    argparse actually accepts it. Advertising a flag argparse then rejects
    with exit 2 sends the user from one error into a second; run_tests has
    no such flag and passes False. The two variants differ by that bullet
    and nothing else.
    """
    bullets = [
        "  * Already have a campaign?  cd into that folder and re-run.",
        '  * Starting fresh?           bunnyforge init my-campaign'
        ' --name "My Campaign"',
    ]
    if suggest_flag:
        bullets.append(
            "  * Or point at it:           --workspace /path/to/campaign")
    return (
        f"{first_line}\n"
        "\n"
        "bunnyforge commands run inside a campaign workspace (the folder"
        " holding\n"
        f"{CONFIG_NAME}).\n"
        "\n"
        + "\n".join(bullets) + "\n"
        "\n"
        f"Guided start: {DOCS_URL}"
    )


def discover(start: Path | None = None) -> Path:
    """Return the nearest directory at or above `start` holding campaign.toml.

    `start` defaults to the current directory. Raises WorkspaceError if no
    marker exists anywhere up to the filesystem root.
    """
    here = Path(start) if start is not None else Path.cwd()
    here = here.resolve()
    for candidate in (here, *here.parents):
        if (candidate / CONFIG_NAME).is_file():
            return candidate
    raise WorkspaceError(
        f"no {CONFIG_NAME} found in {here} or any folder above it.")


def resolve_root(start: Path | None = None, *,
                 suggest_flag: bool = True) -> Path:
    """BUNNYFORGE_WORKSPACE, else the nearest campaign.toml at or above
    `start` (default: the current directory). Raises WorkspaceError when
    neither yields a workspace — including when the current directory is
    unusable (deleted from under the process): that is reported as "not
    inside a campaign workspace", never as a crash.

    Both failure paths build the same card, from the same _card() call, so
    they cannot drift. discover()'s own message locates the failure and
    stops there, which is right for a filesystem walk but leaves a user who
    typed a command with nowhere to go; the card wraps it here, where the
    resolution order actually lives.

    Pass suggest_flag=False from a caller with no --workspace flag, so its
    card does not advertise one; see _card().
    """
    env = os.environ.get("BUNNYFORGE_WORKSPACE")
    if env:
        return Path(env).resolve()
    try:
        return discover(start)
    except WorkspaceError as exc:
        raise WorkspaceError(_card(str(exc), suggest_flag)) from exc
    except OSError as exc:
        raise WorkspaceError(_card(
            f"no {CONFIG_NAME} found — the current directory is unusable "
            f"({exc}).", suggest_flag)) from exc
