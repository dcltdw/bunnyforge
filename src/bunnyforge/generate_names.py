#!/usr/bin/env python3
"""
generate_names.py — culture-aware name generator.

However many cultures the configured cultures directory supplies, each its
own file with a hand-tuned syllable inventory reflecting the real-world
tradition it draws on. Names are assembled from those inventories rather
than drawn from lists of real names, so output is unbounded and does not
recycle actual people's names.

Every generated name is checked against a set of orthographic constraints —
a maximum length, an optional ASCII-only rule, a cap on repeated letters, a
list of forbidden substrings, and a cap on a joined given name's length —
resolved in three layers: built-in defaults, then campaign.toml's
[names.spelling] for the whole setting, then a culture's own [spelling]
table for just that culture. Each layer overrides only the keys it sets; a
culture with no [spelling] table simply inherits the setting's. A name a
player cannot say aloud is a name nobody uses.

Usage:
    python3 -m bunnyforge.generate_names                          # one of each culture
    python3 -m bunnyforge.generate_names <culture> -n 10           # ten names
    python3 -m bunnyforge.generate_names <culture> --gender f -n 5
    python3 -m bunnyforge.generate_names --list                    # show cultures
    python3 -m bunnyforge.generate_names <culture> --place -n 8
    python3 -m bunnyforge.generate_names --seed 42 -n 3            # reproducible
    python3 -m bunnyforge.generate_names <culture> --syllables 2 -n 5
    python3 -m bunnyforge.generate_names --workspace /path/to/campaign --list
"""

from __future__ import annotations

import argparse
import random
import sys
import tomllib
from collections import namedtuple
from pathlib import Path
from typing import NamedTuple

from bunnyforge._config import ConfigError, Workspace, resolve_workspace
from bunnyforge._workspace import WorkspaceError

# ---------------------------------------------------------------------------
# Culture definitions
# ---------------------------------------------------------------------------
# Each culture supplies:
#   name            — display name
#   family          — syllables used for family names
#   categories      — the name categories this culture defines, e.g.
#                      ["m", "f"] or ["clan", "given"]. Any names you like;
#                      the engine knows none of them.
#   given_<category> — one syllable pool per declared category, self-contained
#   place           — syllables for settlement names
#   place_tail      — syllables that end a settlement name
#
# and, optionally:
#   species         — the fantasy species this culture is used for;
#                      defaults to ""
#   draws_on        — the real-world tradition the inventory reflects;
#                      defaults to ""
#   join            — "concat" (default) or "hyphen", how given-name
#                      syllables are joined
#   place_split     — 0..1, probability a place name is rendered as two
#                      words instead of one
#   given_syllables — { min, max, weights } controlling how many syllables
#                      a given name draws
#   spelling        — this culture's own orthographic constraints, layered
#                      on top of the setting's. MUST COME LAST: in TOML a
#                      table header swallows every bare key that follows it,
#                      so a [spelling] block placed any earlier would
#                      swallow the rest of the culture's own keys.
#
# Inventories are deliberately small and distinctive. The goal is that a
# reader can tell one culture's names from another's without being told which
# is which. Each culture is its own file in the directory named by
# campaign.toml's [names].cultures.

_REQUIRED_KEYS = ("categories", "family", "place", "place_tail")

_VALID_JOIN_STYLES = ("concat", "hyphen")

# How many syllables a given name draws when a culture omits
# `given_syllables`. Read by both the loader's validation of an explicit
# table (which defaults each half independently, so a culture may state only
# one of the two) and by syllable_count() at generation time. The two sites
# must agree: a culture whose table the loader accepted must not then be
# generated against a different range.
GIVEN_SYLLABLES_MIN_DEFAULT = 1
GIVEN_SYLLABLES_MAX_DEFAULT = 2

# Retry budgets. Both are generous rather than tuned, and both are here
# rather than inline because a budget tuned against one setting's inventory
# silently constrains every other setting's — the hazard is invisible while
# the number is a literal in a loop header.
#
# What exhaustion does TODAY, in both cases, is fall back rather than fail:
#   GIVEN_JOIN_ATTEMPTS — given_name() drops to a single syllable (or, when
#     the caller forced a syllable count, returns the shortest join it saw).
#   NAME_ATTEMPTS — person_name() returns a deterministic fallback built from
#     the culture's first family syllable and first category's first
#     syllable; place_name() returns the culture's display name.
#
# The phase-2 design (item 5) calls for exhaustion to RAISE instead, naming
# the culture and the budget. That is deliberately deferred, not forgotten:
# check_portability.py's property-one converse depends on person_name's
# deterministic fallback being a reachable outcome — it asserts that not
# every generated name IS that fallback, which is only meaningful while the
# fallback exists. Making exhaustion raise means reworking that converse, so
# it is out of scope here and recorded as such in the phase-2 design.
GIVEN_JOIN_ATTEMPTS = 10
NAME_ATTEMPTS = 50


class InventoryError(Exception):
    """The configured cultures directory is missing, malformed, or incomplete."""


def _validate_optional_keys(path: Path, key: str, c: dict) -> None:
    """Check the optional per-culture keys (species, draws_on, join,
    place_split, given_syllables) well enough that an authoring mistake fails
    loudly here — naming the file and the culture — rather than surfacing
    mid-generation as a bare IndexError, ValueError or AttributeError with no
    indication of which culture or file caused it.

    species and draws_on are plain strings, so their check is only a type
    check; the rest are structural. This docstring used to say those two
    "need no validation beyond defaulting", which #69 retired: resolve()
    calls .lower() on both, so a non-string value was a traceback rather than
    the error-and-exit-1 a broken workspace is owed."""
    for name in ("species", "draws_on"):
        value = c.get(name)
        # `is not None` rather than truthiness: an explicit "" is a legal
        # value the starter culture ships, while None means the key is
        # absent, which is what optional means. The defaults are applied by
        # load_cultures after this runs.
        if value is not None and not isinstance(value, str):
            raise InventoryError(
                f"{path}: culture '{key}': {name} must be a string, "
                f"got {value!r}")

    join = c.get("join")
    if join is not None and join not in _VALID_JOIN_STYLES:
        raise InventoryError(
            f"{path}: culture '{key}': join must be one of "
            f"{', '.join(_VALID_JOIN_STYLES)}, got {join!r}")

    if "place_split" in c:
        try:
            split = float(c["place_split"])
        except (TypeError, ValueError):
            raise InventoryError(
                f"{path}: culture '{key}': place_split must be a number "
                f"between 0 and 1, got {c['place_split']!r}")
        if not 0 <= split <= 1:
            raise InventoryError(
                f"{path}: culture '{key}': place_split must be between 0 "
                f"and 1, got {split}")

    gs = c.get("given_syllables")
    if gs is not None:
        if not isinstance(gs, dict):
            raise InventoryError(
                f"{path}: culture '{key}': given_syllables must be a table, "
                f"got {gs!r}")
        try:
            lo = int(gs.get("min", GIVEN_SYLLABLES_MIN_DEFAULT))
            hi = int(gs.get("max", GIVEN_SYLLABLES_MAX_DEFAULT))
        except (TypeError, ValueError):
            raise InventoryError(
                f"{path}: culture '{key}': given_syllables min and max "
                f"must be integers")
        if lo < 1 or hi < 1:
            raise InventoryError(
                f"{path}: culture '{key}': given_syllables min and max "
                f"must each be >= 1, got min={lo}, max={hi}")
        if lo > hi:
            raise InventoryError(
                f"{path}: culture '{key}': given_syllables min ({lo}) must "
                f"be <= max ({hi})")
        weights = gs.get("weights")
        if weights is not None:
            # A bare `isinstance(weights, (list, tuple))` check is required
            # here, not just a len() check: a string is len()-able (and
            # iterable of one-character strings), so without this a
            # `weights = "ab"` would sail past the length check below and
            # fail later inside rng.choices with no mention of the file,
            # culture, or "weights".
            if not isinstance(weights, (list, tuple)):
                raise InventoryError(
                    f"{path}: culture '{key}': given_syllables weights must "
                    f"be a list, got {weights!r}")
            for w in weights:
                # bool is a subclass of int in Python, but True/False are
                # never a sane authoring choice for a weight, so they are
                # excluded explicitly rather than silently accepted as 1/0.
                if isinstance(w, bool) or not isinstance(w, (int, float)):
                    raise InventoryError(
                        f"{path}: culture '{key}': given_syllables weights "
                        f"must all be numbers, got {w!r}")
                if w < 0:
                    raise InventoryError(
                        f"{path}: culture '{key}': given_syllables weights "
                        f"must not be negative, got {w!r}")
            if len(weights) != hi - lo + 1:
                raise InventoryError(
                    f"{path}: culture '{key}': given_syllables has "
                    f"{hi - lo + 1} values in range {lo}..{hi} but "
                    f"{len(weights)} weights")
            if sum(weights) <= 0:
                # rng.choices raises ValueError("Total of weights must be
                # greater than zero") for all-zero weights — a crash with no
                # indication of file or culture, exactly the failure mode
                # this function exists to prevent.
                raise InventoryError(
                    f"{path}: culture '{key}': given_syllables weights must "
                    f"not all be zero")


def _validate_categories(path: Path, key: str, c: dict) -> None:
    """Check a culture's `categories` list and its `given_<category>` pools.

    Cross-checks both directions: every listed category must have a pool, and
    every `given_*` key must name a listed category. A keys-only design would
    catch neither a misspelled key nor a misspelled category, because each
    looks like a deliberate choice from the other's point of view.

    `categories` is required — _REQUIRED_KEYS has already rejected a culture
    missing it before this runs."""
    cats = c.get("categories")
    if (not isinstance(cats, list) or not cats
            or not all(isinstance(x, str) and x for x in cats)):
        raise InventoryError(
            f"{path}: culture '{key}': categories must be a non-empty list "
            f"of strings, got {cats!r}")

    seen: set[str] = set()
    dupes: list[str] = []
    for cat in cats:
        if cat in seen and cat not in dupes:
            dupes.append(cat)
        seen.add(cat)
    if dupes:
        # A copy-pasted category line loads silently otherwise: the pool
        # LENGTH doubles (category_pool's None branch concatenates every
        # declared category, duplicates included), and random.sample's bit
        # consumption is a function of population size — so seeded output
        # from this culture silently changes with no diagnostic at all.
        raise InventoryError(
            f"{path}: culture '{key}': categories has repeated name(s): "
            f"{', '.join(dupes)}")

    for cat in cats:
        pool = c.get(f"given_{cat}")
        if not isinstance(pool, list) or not pool:
            raise InventoryError(
                f"{path}: culture '{key}': category '{cat}' needs a non-empty "
                f"given_{cat} list, got {pool!r}")
        for elem in pool:
            if not isinstance(elem, str) or not elem:
                raise InventoryError(
                    f"{path}: culture '{key}': given_{cat} must contain "
                    f"only non-empty strings, got {elem!r}")

    declared = {f"given_{cat}" for cat in cats}
    for k in c:
        # given_syllables is a `given_`-prefixed key that names no category —
        # it is the unrelated optional syllable-count table (see the module
        # docstring) — so it is excluded here rather than misread as an
        # undeclared category pool.
        if (k.startswith("given_") and k != "given_syllables"
                and k not in declared):
            raise InventoryError(
                f"{path}: culture '{key}': {k} names no category in "
                f"{sorted(cats)}")


def _validate_spelling(path: Path, key: str, c: dict) -> None:
    """Check a culture's optional [spelling] table, naming the file.

    Delegates the key check to resolve_spelling so the valid-key list has
    exactly one definition."""
    block = c.get("spelling")
    if block is None:
        return
    if not isinstance(block, dict):
        raise InventoryError(
            f"{path}: culture '{key}': spelling must be a table, got {block!r}")
    try:
        resolve_spelling(_DEFAULT_SPELLING, block)
    except InventoryError as exc:
        raise InventoryError(f"{path}: culture '{key}': {exc}") from exc


Spelling = namedtuple(
    "Spelling",
    "max_length ascii_only max_repeat forbidden max_join_length")
Spelling.__doc__ = """A culture's orthographic constraints, resolved from three layers.

Applied by pronounceable() to every candidate word, and by given_name() to
its join-length retry loop.

Fields:
    max_length      — reject any word longer than this many characters.
    ascii_only      — if True, reject any word containing a non-ASCII
                       character.
    max_repeat      — longest allowed run of one repeated letter, as a run
                       *length*: max_repeat=2 permits "aa" but rejects "aaa".
    forbidden       — substrings that disqualify a word if present; matched
                       against the word lowercased. Always a tuple, whichever
                       layer supplied it.
    max_join_length — cap, in characters, on a joined given name's syllable
                       material (the joined parts with any "-" separators
                       removed) before given_name() retries the join.

Every one of these constrains WRITTEN form, not sound. The intent is a name a
player can say aloud; the checks are orthographic.
"""

_DEFAULT_SPELLING = Spelling(max_length=12, ascii_only=True, max_repeat=2,
                             forbidden=("ng'", "''", "--"), max_join_length=9)


def resolve_spelling(base: Spelling, overrides: dict) -> Spelling:
    """Layer `overrides` onto `base`, one key at a time.

    Unknown keys are an error rather than a no-op. A misspelled constraint
    that silently does nothing is the exact failure this phase exists to
    prevent: the culture would generate against the wrong rules and never
    say so."""
    if not overrides:
        return base
    unknown = sorted(set(overrides) - set(Spelling._fields))
    if unknown:
        raise InventoryError(
            f"unknown spelling key(s): {', '.join(unknown)}. "
            f"Valid keys: {', '.join(Spelling._fields)}")
    values = dict(overrides)
    if "forbidden" in values:
        values["forbidden"] = tuple(values["forbidden"])
    return base._replace(**values)


def culture_key(name: str) -> str:
    """A culture's key, derived from its display name: lowercased with spaces
    and hyphens removed. This is exactly the normalisation resolve() already
    applies to user input, which is why "Wold Mere", "wold mere" and
    "WOLDMERE" all reach the same culture."""
    return name.lower().replace(" ", "").replace("-", "")


def load_cultures(directory: Path) -> dict:
    """Scan a directory of one-file-per-culture inventories. The file IS the
    culture: no [culture.X] wrapper, and its key is derived from its `name`.

    The filename is convention only — it is never read, so a culture file
    works under any name. Matching the key is good manners."""
    if not directory.is_dir():
        raise InventoryError(f"cultures directory not found: {directory}")

    cultures: dict = {}
    origin: dict = {}
    for path in sorted(directory.glob("*.toml")):
        try:
            with path.open("rb") as fh:
                raw = tomllib.load(fh)
        except tomllib.TOMLDecodeError as exc:
            raise InventoryError(f"{path} is not valid TOML: {exc}") from exc

        name = raw.get("name")
        if not isinstance(name, str) or not name.strip():
            # A [spelling] or other table header placed above the bare keys
            # swallows them, and a missing `name` is what that mistake looks
            # like from here — so say so rather than just "missing name".
            raise InventoryError(
                f"{path}: missing a non-empty `name`. Bare keys must come "
                f"before any table header, or the table swallows them.")
        key = culture_key(name)
        if not key:
            raise InventoryError(
                f"{path}: name {name!r} normalises to an empty key")
        if key in cultures:
            raise InventoryError(
                f"two culture files both define '{key}': "
                f"{origin[key]} and {path}")

        missing = [k for k in _REQUIRED_KEYS if k not in raw]
        if missing:
            raise InventoryError(
                f"{path}: culture '{key}' is missing {', '.join(missing)}")
        _validate_optional_keys(path, key, raw)
        _validate_categories(path, key, raw)
        _validate_spelling(path, key, raw)

        # Defaulted here so every downstream reader — resolve(), --list, the
        # run header — can keep indexing them directly.
        raw.setdefault("species", "")
        raw.setdefault("draws_on", "")

        cultures[key] = raw
        origin[key] = path

    if not cultures:
        raise InventoryError(f"no culture files (*.toml) in {directory}")
    return cultures


# ---------------------------------------------------------------------------
# Pronounceability filter
# ---------------------------------------------------------------------------

def pronounceable(word: str, spelling: Spelling | None = None) -> bool:
    """Reject anything that fails the resolved spelling's constraints — the
    checks are orthographic, not phonetic: they look at the written form
    (length, ASCII-ness, repeated letters, forbidden substrings), not at how
    the word actually sounds. `spelling` is data, layered from three
    sources; see resolve_spelling(). `None` falls back to the built-in
    defaults — callers operating inside a setting pass the inventory's
    resolved spelling instead."""
    p = spelling or _DEFAULT_SPELLING
    w = word.lower()
    if any(bad in w for bad in p.forbidden):
        return False
    if len(w) > p.max_length:
        return False
    if p.ascii_only and not all(c.isascii() for c in w):
        return False
    run = 1
    for i in range(1, len(w)):
        run = run + 1 if w[i] == w[i - 1] else 1
        if run > p.max_repeat:
            return False
    return True


def titlecase(word: str) -> str:
    return word[:1].upper() + word[1:]


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def syllable_count(rng: random.Random, spec: dict) -> int:
    """How many inventory elements this given name draws. `spec` is a culture's
    given_syllables table: min, max, and a weight per value in that range."""
    lo = int(spec.get("min", GIVEN_SYLLABLES_MIN_DEFAULT))
    hi = int(spec.get("max", GIVEN_SYLLABLES_MAX_DEFAULT))
    counts = list(range(lo, hi + 1))
    weights = spec.get("weights") or [1] * len(counts)
    if len(weights) != len(counts):
        raise InventoryError(
            f"given_syllables: {len(counts)} values in range {lo}..{hi} but "
            f"{len(weights)} weights")
    return rng.choices(counts, weights=weights, k=1)[0]


def category_pool(culture: dict, category: str | None) -> list[str]:
    """The syllable pool for one category, or every category concatenated in
    declared order when `category` is None ("any").

    Pools are self-contained: nothing is merged in from a sibling category.
    The concatenation is deliberately literal and ordered — de-duplicating or
    sorting here would change the pool's LENGTH, and random.sample consumes a
    number of random bits derived from the population size, so it would
    silently alter seeded output."""
    if category is None:
        pool = []
        for cat in culture["categories"]:
            pool += culture[f"given_{cat}"]
        return pool
    return list(culture[f"given_{category}"])


def given_name(rng: random.Random, culture: dict, category: str | None,
               forced_syllables: int | None = None,
               spelling: Spelling | None = None) -> str:
    """A single given name, titlecased, drawn from `culture`'s pool for
    `category` (or every category's pool when `category` is None). `spelling`
    is data, layered from three sources; see resolve_spelling(). `None` falls
    back to the built-in defaults — callers operating inside a setting pass
    the inventory's resolved spelling instead."""
    pool = category_pool(culture, category)

    n = forced_syllables or syllable_count(
        rng, culture.get("given_syllables", {}))
    n = max(1, min(n, len(pool)))
    if n == 1:
        return titlecase(rng.choice(pool))

    p = spelling or _DEFAULT_SPELLING
    sep = "-" if culture.get("join") == "hyphen" else ""
    shortest = None
    # Up to GIVEN_JOIN_ATTEMPTS tries to find a join that reads comfortably
    # under the resolved spelling. The budget is arbitrary but generous:
    # with a small pool and n <= 3, most draws satisfy the length cap well
    # before it is exhausted, and unforced calls fall back to a single
    # syllable below rather than spend more attempts chasing one.
    for _ in range(GIVEN_JOIN_ATTEMPTS):
        parts = rng.sample(pool, n)
        joined = sep.join(parts)
        # Rejected if the result gets too long to say comfortably — this is
        # the resolved spelling's max_join_length, not max_length: max_length
        # bounds each individual word (family or given) after joining, while
        # this bounds the given name's syllable material before any
        # separator is counted, so a hyphenated join isn't penalised for its
        # hyphens.
        if len(joined.replace("-", "")) <= p.max_join_length:
            return titlecase(joined)
        if shortest is None or len(joined) < len(shortest):
            shortest = joined
    if forced_syllables:
        # An explicit count is a promise. When nothing fits the length
        # preference, return the shortest join we found rather than silently
        # dropping to one syllable — length is a preference, the count is not.
        return titlecase(shortest)
    return titlecase(rng.choice(pool))


def person_name(rng: random.Random, inv: Inventory, key: str,
                category: str | None,
                forced_syllables: int | None = None,
                spelling: Spelling | None = None) -> str:
    culture = inv.cultures[key]
    p = spelling or inv.spelling[key]
    for _ in range(NAME_ATTEMPTS):
        fam = rng.choice(culture["family"])
        giv = given_name(rng, culture, category, forced_syllables, p)
        full = f"{fam} {giv}"
        if pronounceable(fam, p) and pronounceable(giv, p):
            return full
    # Category-agnostic fallback: the first declared category's first
    # syllable.
    first = culture["categories"][0]
    return f"{culture['family'][0]} {culture[f'given_{first}'][0].title()}"


def place_name(rng: random.Random, inv: Inventory, key: str,
               spelling: Spelling | None = None) -> str:
    culture = inv.cultures[key]
    p = spelling or inv.spelling[key]
    # Some cultures often split their place names into two words. Hoisted
    # out of the loop below: it is invariant across every attempt, and
    # load_cultures() has already validated it is a number in 0..1.
    split = float(culture.get("place_split", 0.0))
    for _ in range(NAME_ATTEMPTS):
        head = rng.choice(culture["place"])
        tail = rng.choice(culture["place_tail"])
        # Reject doubled syllables: "Sansan", "Wolwol".
        if head.lower() == tail.lower() or head.lower().endswith(tail.lower()):
            continue
        name = f"{head}{tail}"
        if pronounceable(name, p):
            if split and rng.random() < split:
                return f"{head} {titlecase(tail)}"
            return name
    return culture["name"]


def resolve_official_culture(configured: str | None, cultures: dict) -> str | None:
    """Normalise and validate campaign.toml's [names].official_culture.

    Returns None when unconfigured — official_name() already treats a falsy
    value as "this setting has no official language", and that must keep
    working. Otherwise normalises `configured` through culture_key() (so a
    display-name spelling like "Wold Mere" resolves the same as its key,
    "woldmere") and raises InventoryError if the result names no culture in
    `cultures`, rather than letting a bare KeyError surface later out of
    place_name()."""
    if not configured:
        return None
    key = culture_key(configured)
    if key not in cultures:
        raise InventoryError(
            f"[names].official_culture in campaign.toml names no culture: "
            f"{configured!r}. Available: {', '.join(sorted(cultures))}")
    return key


class Inventory(NamedTuple):
    """Everything the generator knows about one setting's cultures, loaded
    once and passed explicitly — so two settings can coexist in one process
    and no function ever reads ambient module state."""
    cultures: dict
    spelling: dict
    setting_spelling: Spelling
    official_culture: str | None


def load_inventory(ws: Workspace) -> Inventory:
    """Load and validate a workspace's name inventory.

    Order does NOT replicate the retired module-level pipeline: on `main`,
    setting spelling (layers 1+2) resolved before the cultures-configured
    guard ran. Here the guard is deliberately hoisted first, so a workspace
    with no [names].cultures reports THAT rather than an unrelated spelling
    complaint. The one observable consequence: a workspace broken both ways
    at once — no cultures configured AND an invalid [names.spelling] key —
    now reports the missing-cultures error, where it used to report the
    spelling error. After the guard: setting spelling, then the cultures
    scan, then per-culture resolution (layer 3), then the official
    culture."""
    if not ws.config.names_cultures:
        raise InventoryError(
            "no name cultures configured — set [names].cultures in "
            "campaign.toml to a cultures directory")
    setting_spelling = resolve_spelling(_DEFAULT_SPELLING, ws.config.names_spelling)
    cultures = load_cultures(ws.root / ws.config.names_cultures)
    # This dict's keyset must stay in lockstep with `cultures`: person_name()
    # and place_name() do inv.spelling[key], so a key present in `cultures`
    # but absent here is a bare KeyError. With both built here, in one
    # function, from the same `cultures` dict, the lockstep is structural —
    # there is no separate mutation path for either to drift out of sync.
    spelling = {k: resolve_spelling(setting_spelling, c.get("spelling", {}))
                for k, c in cultures.items()}
    official = resolve_official_culture(ws.config.names_official_culture, cultures)
    return Inventory(cultures, spelling, setting_spelling, official)


def official_name(rng: random.Random, inv: Inventory,
                  spelling: Spelling | None = None) -> str | None:
    """The administrative name a settlement also carries, in the language of
    the configured official culture. None when no such culture is configured —
    that a setting has an imperial language at all is a setting decision."""
    if not inv.official_culture:
        return None
    return place_name(rng, inv, inv.official_culture, spelling)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def resolve(cultures: dict, name: str) -> str | list[str] | None:
    """A culture key, a list of candidates when the alias is ambiguous, or
    None. User-defined inventories may give two cultures the same species or
    real-world basis; guessing between them would be worse than refusing."""
    n = name.lower().replace(" ", "").replace("-", "")
    if n in cultures:
        return n
    hits = [
        key for key, c in cultures.items()
        if c["species"].lower().replace(" ", "") == n
        or c["draws_on"].lower().replace(" ", "") == n
    ]
    if len(hits) == 1:
        return hits[0]
    return sorted(hits) if hits else None


def cultures_with(cultures: dict, category: str) -> list[str]:
    """Culture keys declaring `category`, alphabetical."""
    return sorted(k for k, c in cultures.items()
                  if category in c["categories"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate culture-appropriate names.",
    )
    parser.add_argument("culture", nargs="?", help="Culture, species, or real-world basis")
    parser.add_argument("-n", "--count", type=int, default=1, help="How many to generate")
    parser.add_argument("--gender",
                        help="Name category to draw from; omit for all of "
                             "them. Cultures define their own category names")
    parser.add_argument("--place", action="store_true", help="Generate settlement names")
    parser.add_argument("--seed", type=int, help="Seed for reproducible output")
    parser.add_argument("--list", action="store_true", help="List cultures and exit")
    parser.add_argument("--syllables", type=int,
                        help="Force an exact syllable count per given name")
    parser.add_argument(
        "--workspace", metavar="PATH",
        help="Campaign workspace root (default: $BUNNYFORGE_WORKSPACE, else "
             "the nearest campaign.toml above the current directory)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.syllables is not None and args.syllables < 1:
        print(f"error: --syllables must be >= 1, got {args.syllables}",
              file=sys.stderr)
        return 1

    try:
        # WorkspaceError is in the tuple at last, and is reachable: with the
        # install-repo fallback gone, resolve_root raises when no flag, no
        # BUNNYFORGE_WORKSPACE and no marker above the cwd name a workspace.
        # Covered end-to-end by test_no_workspace_at_all_is_a_clean_error,
        # which is the test the two earlier revisions of this comment were
        # waiting on; without WorkspaceError here it sees a traceback.
        inv = load_inventory(resolve_workspace(args.workspace))
    except (InventoryError, ConfigError, WorkspaceError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.list:
        print(f"{'Culture':<12} {'Species':<12} {'Draws on':<20} Categories")
        print("-" * 62)
        for key in sorted(inv.cultures):
            c = inv.cultures[key]
            cats = ", ".join(c["categories"])
            print(f"{c['name']:<12} {c['species']:<12} "
                  f"{c['draws_on']:<20} {cats}")
        return 0

    rng = random.Random(args.seed)

    if args.culture:
        key = resolve(inv.cultures, args.culture)
        if key is None:
            print(f"error: unknown culture '{args.culture}'. Try --list.",
                  file=sys.stderr)
            return 1
        if isinstance(key, list):
            print(f"error: '{args.culture}' is ambiguous — matches "
                  f"{', '.join(key)}. Name one directly.", file=sys.stderr)
            return 1
        keys = [key]
    else:
        keys = sorted(inv.cultures)

    if args.gender is not None:
        if args.culture:
            cats = inv.cultures[keys[0]]["categories"]
            if args.gender not in cats:
                print(f"error: culture '{keys[0]}' has no category "
                      f"'{args.gender}'. It defines: {', '.join(cats)}",
                      file=sys.stderr)
                return 1
        else:
            keys = cultures_with(inv.cultures, args.gender)
            if not keys:
                available = sorted({c for cu in inv.cultures.values()
                                    for c in cu["categories"]})
                print(f"error: no culture has a category '{args.gender}'. "
                      f"Categories in use: {', '.join(available)}",
                      file=sys.stderr)
                return 1

    for key in keys:
        c = inv.cultures[key]
        if len(keys) > 1:
            # Both keys are validated as strings at load
            # (_validate_optional_keys), so no coercion is needed here. "" is
            # the loader's default for an unset key and is the only value
            # omitted — a culture that explicitly set "" gets nothing printed.
            bits = [b for b in (c["species"], c["draws_on"]) if b != ""]
            suffix = f"  ({', '.join(bits)})" if bits else ""
            print(f"\n{c['name']}{suffix}")
        for _ in range(args.count):
            if args.place:
                local = place_name(rng, inv, key)
                official = official_name(rng, inv)
                if official is None or key == inv.official_culture:
                    print(f"  {local}")
                else:
                    print(f"  {local:<16} official: {official}")
            else:
                print(f"  {person_name(rng, inv, key, args.gender, args.syllables)}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        sys.stderr.close()
        raise SystemExit(0)
