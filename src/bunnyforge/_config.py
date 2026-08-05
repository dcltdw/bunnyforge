#!/usr/bin/env python3
"""
_config.py — campaign configuration, read from campaign.toml.

The workspace's identity and shape are data, not constants: which wiki
namespace it publishes to, which directories hold entities, which are never
walked. Each main() resolves one Workspace (resolve_workspace) and threads it;
tests call load() or open_workspace() directly against a temporary workspace.
Nothing is loaded at import — importing this module must not touch the disk.

Every [workspace] key is optional and falls back to a conventional TTRPG
workspace shape (see _DEFAULTS) when omitted.

Stdlib only. tomllib requires Python 3.11+.
"""

from __future__ import annotations

import os
import stat
import tomllib
from collections import namedtuple
from pathlib import Path
from typing import NamedTuple

from bunnyforge import _workspace
from bunnyforge._workspace import (  # noqa: F401
    CONFIG_NAME, DOCS_URL, WorkspaceError)

# Never walked, whatever the config says. Without this floor, a campaign that
# omitted them from exclude_dirs would treat its own git internals as content.
MANDATORY_EXCLUDES = frozenset({".git", ".github"})

Config = namedtuple(
    "Config",
    "name namespace entity_dirs inherit_dirs compendium_dirs root_docs "
    "exclude_dirs names_cultures names_official_culture names_spelling "
    "briefs_dir sheets_dir perceptions_dir type_dirs wiki_url",
    defaults=[None])  # wiki_url only — [wiki] is optional and network-only


class ConfigError(Exception):
    """campaign.toml is missing, malformed, or incomplete."""


TOKEN_ENV = "BUNNYFORGE_WIKI_TOKEN"
TOKEN_FILE = ".bunnyforge/wiki-token"


def resolve_wiki_token(workspace_root: Path) -> str:
    """The deploy credential, in resolution order: env var, then token file.

    A DokuWiki API token, never a password — scopable, revocable without a
    password change. A rejected credential is a server-side answer and is
    translated by the RPC error table, not here.
    """
    env = os.environ.get(TOKEN_ENV, "").strip()
    if env:
        return env
    path = workspace_root / TOKEN_FILE
    if path.is_file():
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            raise ConfigError(
                f"{path} is readable by group or world (mode {mode:03o}) — "
                f"a wiki credential must be private:\n  chmod 600 {path}")
        token = path.read_text(encoding="utf-8").strip()
        if token:
            return token
    raise ConfigError(
        "no wiki API token found. Provide one via either:\n"
        f"  - the {TOKEN_ENV} environment variable, or\n"
        f"  - a single line in <workspace>/{TOKEN_FILE} (chmod 600)\n"
        "Create one on the wiki: log in as the deploy user, open its "
        "profile, and generate an API token.")


# The three entity types build_sheets understands, and nothing else — an
# unrecognised or missing key here is a defect, never a fallback.
TYPE_DIR_KEYS = frozenset({"npc", "faction", "place"})

_DEFAULTS = {
    "entity_dirs": ["NPCs", "Factions", "Setting", "Mechanics", "PCs", "Ideas",
                    "Sessions", "Handouts"],
    "inherit_dirs": ["Briefs", "Perceptions"],
    "compendium_dirs": ["NPCs", "Factions", "Setting", "Mechanics", "PCs", "Ideas"],
    "root_docs": ["AGENTS.md", "compendium.md", "front-burner.md",
                  "open-questions.md", "out-of-game.md", "situation-design.md",
                  "style-guide.md", "tickets.md"],
    "exclude_dirs": ["_Ignore", "_Archive", "_ExtractInbound", "_Templates",
                     "Sheets", "Reviews", "docs", "scripts", "tests"],
    "briefs_dir": "Briefs",
    "sheets_dir": "Sheets",
    "perceptions_dir": "Perceptions",
    "type_dirs": {"npc": "NPCs", "faction": "Factions", "place": "Setting"},
}


def _str_tuple(section: dict, key: str) -> tuple[str, ...]:
    raw = section.get(key, _DEFAULTS[key])
    if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
        raise ConfigError(f"workspace.{key} must be a list of strings")
    return tuple(raw)


def _str(section: dict, key: str) -> str:
    raw = section.get(key, _DEFAULTS[key])
    if not isinstance(raw, str):
        raise ConfigError(f"workspace.{key} must be a string")
    return raw


def _type_dirs(section: dict) -> dict[str, str]:
    """Validate workspace.type_dirs: a table of strings keyed by exactly
    {"npc", "faction", "place"} — no more, no fewer. A misspelled or missing
    key must raise, not silently fall back to the default for that key; that
    silent-fallback defect is the whole reason this phase exists.
    """
    raw = section.get("type_dirs", _DEFAULTS["type_dirs"])
    if not isinstance(raw, dict):
        raise ConfigError("workspace.type_dirs must be a table of strings")
    bad = sorted(set(raw) ^ TYPE_DIR_KEYS)
    if bad:
        raise ConfigError(
            "workspace.type_dirs must have exactly the keys "
            f"{sorted(TYPE_DIR_KEYS)} — offending key(s): {', '.join(bad)}")
    if not all(isinstance(v, str) for v in raw.values()):
        raise ConfigError("workspace.type_dirs values must be strings")
    return dict(raw)


def load(workspace: Path) -> Config:
    """Read campaign.toml from `workspace`. Raises ConfigError on any problem.

    Validates shape, not the filesystem: a directory named here that does not
    exist on disk is tolerated, because walking skips what is not there and a
    fresh workspace has not created everything yet.
    """
    path = workspace / CONFIG_NAME
    if not path.is_file():
        # A named directory that is not a workspace. Deliberately NOT the
        # _workspace card: that card's "cd into that folder" advice is wrong
        # here -- the user already pointed at a folder, and the fault is
        # which one. Instructional all the same, per the same ruling.
        raise ConfigError(
            f"no {CONFIG_NAME} in {workspace} — that folder is not a campaign"
            f" workspace.\n"
            f"Check the path, or create a campaign there first:\n"
            f'  bunnyforge init {workspace} --name "My Campaign"\n'
            f"Guided start: {DOCS_URL}")
    try:
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from exc

    campaign = raw.get("campaign", {})
    if not isinstance(campaign, dict):
        raise ConfigError(f"{path}: [campaign] must be a table")
    namespace = campaign.get("namespace")
    if not namespace:
        raise ConfigError(
            f"{path} is missing required key campaign.namespace — it has no "
            "safe default")

    ws = raw.get("workspace", {})
    if not isinstance(ws, dict):
        raise ConfigError(f"{path}: [workspace] must be a table")

    names = raw.get("names", {})
    if not isinstance(names, dict):
        raise ConfigError(f"{path}: [names] must be a table")

    spelling = names.get("spelling", {})
    if not isinstance(spelling, dict):
        raise ConfigError(f"{path}: [names.spelling] must be a table")

    wiki = raw.get("wiki", {})
    if not isinstance(wiki, dict):
        raise ConfigError(f"{path}: [wiki] must be a table")
    wiki_url = wiki.get("url")
    if wiki_url is not None and not isinstance(wiki_url, str):
        raise ConfigError(f"{path}: wiki.url must be a string")

    entity_dirs = _str_tuple(ws, "entity_dirs")
    inherit_dirs = _str_tuple(ws, "inherit_dirs")
    # iter_content_files walks entity_dirs and then inherit_dirs, so a
    # directory named in both is enumerated twice: every file under it is
    # checked twice by the checkup, exported twice, and counted twice in
    # every summary. Nothing downstream de-duplicates, so this has to be
    # refused here, naming the directory to fix rather than the fact of a
    # conflict.
    both = sorted(set(entity_dirs) & set(inherit_dirs))
    if both:
        raise ConfigError(
            f"{path}: workspace.entity_dirs and workspace.inherit_dirs must "
            "not overlap — each would be walked twice; offending "
            f"director{'ies' if len(both) > 1 else 'y'}: {', '.join(both)}")

    return Config(
        name=campaign.get("name", namespace),
        namespace=namespace,
        entity_dirs=entity_dirs,
        inherit_dirs=inherit_dirs,
        compendium_dirs=_str_tuple(ws, "compendium_dirs"),
        root_docs=_str_tuple(ws, "root_docs"),
        exclude_dirs=frozenset(_str_tuple(ws, "exclude_dirs")) | MANDATORY_EXCLUDES,
        names_cultures=names.get("cultures"),
        names_official_culture=names.get("official_culture"),
        names_spelling=spelling,
        briefs_dir=_str(ws, "briefs_dir"),
        sheets_dir=_str(ws, "sheets_dir"),
        perceptions_dir=_str(ws, "perceptions_dir"),
        type_dirs=_type_dirs(ws),
        wiki_url=wiki_url,
    )


class Workspace(NamedTuple):
    """A campaign workspace: where it is, and what its campaign.toml says.

    Passed as one value so a root and a config cannot drift apart in a call
    chain. Lives here rather than in _workspace because loading config is
    this module's job — _workspace imports nothing from the package, which
    is what keeps the two free of a cycle.
    """
    root: Path
    config: Config


def open_workspace(root: Path | str | None = None) -> Workspace:
    """Load the workspace at `root`, or resolve one when `root` is None.

    The None branch re-runs resolution on every call rather than answering
    from anything computed earlier: there is no import-time workspace to
    answer from any more, and caching one would resurrect the bug this phase
    exists to kill — a long-lived process, or a test, silently reading a
    workspace the environment no longer names.

    Raises WorkspaceError if no workspace can be resolved, ConfigError if
    campaign.toml is missing or malformed.
    """
    resolved = _workspace.resolve_root() if root is None else Path(root).resolve()
    return Workspace(resolved, load(resolved))


def resolve_workspace(explicit: str | None) -> Workspace:
    """The CLI resolution order: --workspace, then BUNNYFORGE_WORKSPACE, then
    the marker walk from the current directory. Raises ConfigError or
    WorkspaceError with a user-facing message; callers catch both and exit 1.

    `explicit` is used as given (no walk) — pointing --workspace at a
    directory with no campaign.toml is an error, not a search hint.
    Resolving a relative `explicit` to an absolute path is open_workspace's
    job (it calls Path(root).resolve() unconditionally); doing it again here
    would be redundant, not additionally correct, since resolve() is
    idempotent on an already-resolved path.
    """
    if explicit:
        return open_workspace(explicit)
    return open_workspace(_workspace.resolve_root())
