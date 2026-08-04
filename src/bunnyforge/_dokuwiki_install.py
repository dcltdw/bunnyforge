#!/usr/bin/env python3
"""
_dokuwiki_install.py — read a DokuWiki *installation's* configuration.

Sibling to _dokuwiki.py, which knows about DokuWiki *markup* and page IDs.
This module knows about an install on disk: its conf/ PHP files, its ACL
table, and which plugins are present and enabled.

Deliberately a set of pure parsers returning plain data. Every judgement
about whether a configuration is *correct* lives in review.py's checks, so
this module has no notion of a Finding and no policy of its own.

The PHP is read with regexes, not parsed. That is a deliberate limit: real
conf files are sequences of `$conf['key'] = value;` assignments, and an
assignment this cannot read is reported as absent rather than guessed at.
Anything needing real PHP semantics is out of scope for a stdlib-only tool.
"""

from __future__ import annotations

import re
from collections import namedtuple
from pathlib import Path
from urllib.parse import unquote


class InstallError(Exception):
    """The given path is not a readable DokuWiki installation."""


ConfValue = namedtuple("ConfValue", "value source")
AclRule = namedtuple("AclRule", "scope principal level")

# Config files in load order; each overrides the ones before it. Only
# dokuwiki.php is guaranteed to exist.
_CONF_FILES = ("dokuwiki.php", "local.php", "local.protected.php")

# $conf['key'] = value;  — with no array subscript after the first key, so
# `$conf['plugin']['include']['x']` is skipped rather than landing under a
# bare 'plugin' key and shadowing a real scalar.
_CONF_RE = re.compile(
    r"^\s*\$conf\[\s*['\"](?P<key>[^'\"]+)['\"]\s*\]\s*=\s*(?P<value>[^;]+);")
_PLUGIN_RE = re.compile(
    r"^\s*\$plugins\[\s*['\"](?P<name>[^'\"]+)['\"]\s*\]\s*=\s*(?P<value>[^;]+);")


def _php_literal(raw: str):
    """Decode the handful of PHP literal forms a conf value takes."""
    text = raw.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        return text[1:-1]
    low = text.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low == "null":
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def _assignments(path: Path, pattern: re.Pattern, key_group: str) -> dict:
    """Every uncommented assignment in `path`, last occurrence winning."""
    if not path.is_file():
        return {}
    found: dict = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        # Commented-out assignments are skipped by the anchoring alone: the
        # patterns start at `^\s*\$conf` / `^\s*\$plugins`, so a line whose
        # first non-space character is `#` or `//` cannot match. That matters
        # because stock dokuwiki.php is full of them, and treating one as live
        # would report a value the wiki is not actually using. Block comments
        # are not handled — see the module docstring.
        m = pattern.match(line)
        if m:
            found[m.group(key_group)] = _php_literal(m.group("value"))
    return found


def check_root(root: Path) -> None:
    """Raise InstallError unless `root` looks like a DokuWiki installation."""
    if not root.is_dir():
        raise InstallError(f"{root} is not a directory")
    if not (root / "conf").is_dir():
        raise InstallError(
            f"{root} has no conf/ directory — is it a DokuWiki install root? "
            f"(the install root holds conf/ and lib/, and is the parent of "
            f"the data/ directory import_perceptions takes)")


def read_conf(root: Path) -> dict[str, ConfValue]:
    """Merged $conf across the config files, later files winning.

    Each value carries the filename it won from: the useacl invariant is about
    provenance, not just value, because a setting made in dokuwiki.php is
    reverted by the next upgrade.
    """
    check_root(root)
    merged: dict[str, ConfValue] = {}
    for name in _CONF_FILES:
        for key, value in _assignments(root / "conf" / name, _CONF_RE, "key").items():
            merged[key] = ConfValue(value, name)
    return merged


def read_acl(root: Path) -> list[AclRule]:
    """Every rule in conf/acl.auth.php, in file order.

    A missing file is no rules rather than an error: ACLs are off by default,
    and `useacl` is what says whether that matters.
    """
    check_root(root)
    path = root / "conf" / "acl.auth.php"
    if not path.is_file():
        return []
    rules: list[AclRule] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("<?"):
            continue
        parts = stripped.split()
        if len(parts) != 3:
            continue
        scope, principal, level = parts
        try:
            rules.append(AclRule(unquote(scope), unquote(principal), int(level)))
        except ValueError:
            continue
    return rules


def plugin_state(root: Path, name: str) -> tuple[bool, bool]:
    """(installed, enabled) for one plugin.

    Installed means lib/plugins/<name>/ exists. Enabled means nothing turned
    it off: DokuWiki's plugin list is opt-out, so absence from the disable
    files is the enabled state. A plugin that is not installed is not
    enabled either, whatever the conf says.
    """
    check_root(root)
    installed = (root / "lib" / "plugins" / name).is_dir()
    if not installed:
        return False, False
    state = {}
    for conf_name in ("plugins.php", "plugins.local.php"):
        state.update(_assignments(root / "conf" / conf_name, _PLUGIN_RE, "name"))
    return True, bool(state.get(name, True))
