#!/usr/bin/env python3
"""check_portability.py — proves a culture file is a portable unit.

Manufactures two cultures with randomised parameters and disjoint alphabets,
builds synthetic settings as plain values, and asserts two properties:

  1. A culture whose [spelling] fully specifies every key produces
     byte-identical output in two different settings — and the converse, that
     one omitting spelling keys produces DIFFERENT output in settings whose
     [names.spelling] differ.
  2. A generated name contains only the data its own culture specified.

Each synthetic setting is a plain `Setting(name, directory, inv)` value —
an `Inventory` built the same way `load_inventory()` builds one for a real
workspace. Nothing is swapped or restored: `inv` is passed explicitly to
every generator call, so there is no module state for one setting's check to
leak into another's, and this file can (and does) run in-process.
"""

import argparse
import random
import shutil
import sys
import tempfile
from collections import namedtuple
from pathlib import Path

from bunnyforge import generate_names as g

# Two character sets with NO overlap -- the lowercase alphabet split in half.
# This is what makes contamination decisive rather than inferential: any
# character from B's alphabet in an A name is contamination, with no need to
# parse joins or reason about pool membership. ASCII only, so a generated
# ascii_only spelling never rejects.
#
# Thirteen characters each is not arbitrary. Up to five categories need
# DISJOINT sub-alphabets carved from the same set, so a six-character alphabet
# would leave one character per category and every syllable would be a run of
# the same letter -- technically decisive, but degenerate enough to hide bugs.
ALPHABET_A = "abcdefghijklm"
ALPHABET_B = "nopqrstuvwxyz"
assert not (set(ALPHABET_A) & set(ALPHABET_B)), "alphabets must be disjoint"
DISJOINT_ALPHABETS = (ALPHABET_A, ALPHABET_B)

Setting = namedtuple("Setting", "name directory inv")


def build_setting(tmp: Path, name: str, cultures: dict, setting_spelling: dict,
                  official: str | None = None) -> Setting:
    """Write culture files into tmp/<name>/ and resolve the setting's layers
    into an Inventory.

    `cultures` maps a filename stem to that file's full TOML text. The
    directory is a real one on disk, so load_cultures() exercises the same
    scan-and-validate path a real setting takes."""
    directory = tmp / name
    directory.mkdir(parents=True)
    for stem, text in cultures.items():
        (directory / f"{stem}.toml").write_text(text, encoding="utf-8")

    loaded = g.load_cultures(directory)
    # Layer 2, then layer 3 per culture — exactly what load_inventory() does
    # for a real workspace.
    base = g.resolve_spelling(g._DEFAULT_SPELLING, setting_spelling)
    spelling = {k: g.resolve_spelling(base, c.get("spelling", {}))
                for k, c in loaded.items()}
    inv = g.Inventory(cultures=loaded, spelling=spelling,
                      setting_spelling=base, official_culture=official)
    return Setting(name, directory, inv)


# Candidate category names. Deliberately nothing like "m"/"f"/"n" -- the
# retired two-and-three-category convention -- so a bug that silently falls
# back to those defaults is visible rather than blending in. Eight entries
# comfortably covers the 1-5 category count generate_culture() picks.
CATEGORY_NAME_POOL = (
    "clan", "kin", "line", "sept", "house", "tribe", "branch", "folk",
)
# Both properties are load-bearing, so they are asserted here rather than
# left as a hand-checked property of a hardcoded tuple. A category named
# "syllables" would generate a `given_syllables` key that collides with the
# real given_syllables config line, producing a TOML file with a duplicate
# key; a category resembling m/f/n would defeat the whole point of this
# pool (see the comment above).
assert "syllables" not in CATEGORY_NAME_POOL, \
    "a category named 'syllables' would collide with the given_syllables key"
assert not ({"m", "f", "n"} & set(CATEGORY_NAME_POOL)), \
    "category name pool must not resemble the retired m/f/n"


def _format_list(items) -> str:
    """Render a Python list of strings as a TOML array literal."""
    return "[" + ", ".join(f'"{item}"' for item in items) + "]"


def _make_pool(rng: random.Random, alphabet: str, size: int,
               min_len: int, max_len: int) -> list[str]:
    """`size` distinct random syllables drawn from `alphabet`, each of length
    in [min_len, max_len]. Bounded by an attempt budget rather than looping
    forever: a one- or two-character sub-alphabet at length 1 can only supply
    that many distinct strings, so falling short and returning whatever was
    found is the correct behaviour, not a bug. Callers that need a minimum
    pool size read the pool's actual length back rather than assuming `size`
    was met."""
    seen: set[str] = set()
    pool: list[str] = []
    attempts = 0
    budget = size * 30 + 100
    while len(pool) < size and attempts < budget:
        length = rng.randint(min_len, max_len)
        word = "".join(rng.choice(alphabet) for _ in range(length))
        attempts += 1
        if word in seen:
            continue
        seen.add(word)
        pool.append(word)
    if not pool:
        # Only reachable if even one distinct syllable couldn't be found in
        # the attempt budget -- doesn't happen for any alphabet/length
        # combination this generator actually produces, but a non-empty pool
        # is a hard requirement downstream (load_cultures() rejects an empty
        # given_<cat>/family/place/place_tail), so guarantee one.
        pool = [rng.choice(alphabet) * min_len]
    return pool


def generate_culture(rng: random.Random, name: str, alphabet: str, *,
                     fully_specified: bool,
                     given_len_override: tuple | None = None,
                     given_syllables_override: dict | None = None
                     ) -> tuple[str, dict]:
    """Manufacture one culture's TOML text, plus a description dict recording
    what was generated (category names, per-category sub-alphabets, pool
    sizes, knobs) so both the report and later assertions can read it without
    re-parsing the TOML.

    Randomises category count (1-5), category names, pool sizes, syllable
    lengths, join style, place_split, and the given_syllables range/weights.

    Partitioning -- see the module docstring for why the split is drawn this
    way: each category's given_<cat> pool is drawn from a disjoint
    sub-alphabet carved out of `alphabet`, so "categories are honoured" is a
    character check. family, place, and place_tail draw from the FULL
    alphabet rather than a further reserved partition: cross-culture
    contamination is checked against the OTHER culture's alphabet, so sharing
    characters within one culture is harmless, and reserving them a partition
    too would leave one or two characters per category over an already
    thirteen-character alphabet -- near-degenerate.

    `given_len_override` and `given_syllables_override` are both None for
    every caller in this file except property_one()'s converse half, which
    needs DETERMINISTIC syllable geometry (a fixed length, a pinned
    syllable count) rather than the usual randomised ranges, so that a
    join's length relative to a max_join_length threshold is guaranteed
    rather than merely likely. Leaving both at their default of None
    reproduces the exact prior randomised behaviour byte-for-byte -- no
    existing caller (check_generator, check_generated_culture, or
    property_one's own forward half) passes either, so this is additive.
    """
    count = rng.randint(1, 5)
    categories = list(rng.sample(CATEGORY_NAME_POOL, count))
    assert not ({"m", "f", "n"} & set(categories))

    letters = list(alphabet)
    n = len(letters)
    base, rem = divmod(n, count)
    sizes = [base + (1 if i < rem else 0) for i in range(count)]
    sub_alphabets: dict[str, str] = {}
    idx = 0
    for cat, size in zip(categories, sizes):
        sub_alphabets[cat] = "".join(letters[idx:idx + size])
        idx += size

    given_pools: dict[str, list[str]] = {}
    pool_sizes: dict[str, int] = {}
    for cat in categories:
        size = rng.randint(3, 6)
        if given_len_override is not None:
            min_len, max_len = given_len_override
        else:
            min_len = rng.randint(1, 2)
            max_len = min_len + rng.randint(0, 2)
        pool = _make_pool(rng, sub_alphabets[cat], size, min_len, max_len)
        given_pools[cat] = pool
        pool_sizes[f"given_{cat}"] = len(pool)

    family_pool = _make_pool(rng, alphabet, rng.randint(3, 6), 2, 4)
    place_pool = _make_pool(rng, alphabet, rng.randint(3, 6), 2, 4)
    place_tail_pool = _make_pool(rng, alphabet, rng.randint(3, 6), 2, 4)
    pool_sizes["family"] = len(family_pool)
    pool_sizes["place"] = len(place_pool)
    pool_sizes["place_tail"] = len(place_tail_pool)

    join_style = rng.choice(("concat", "hyphen"))
    place_split = round(rng.uniform(0.0, 1.0), 2)

    # given_syllables must be satisfiable by the pool it draws from: whichever
    # category is requested (or the concatenation of all of them, for "any"),
    # rng.sample(pool, n) needs n <= len(pool). Bounding hi by the SMALLEST
    # per-category pool -- computed from actual pool lengths, not the `size`
    # requested from _make_pool, which may have fallen short -- keeps every
    # category satisfiable, and the concatenated "any" pool is only ever
    # larger.
    smallest_pool = min(len(p) for p in given_pools.values())
    if given_syllables_override is not None:
        lo = given_syllables_override["min"]
        hi = given_syllables_override["max"]
        weights = list(given_syllables_override["weights"])
        assert hi <= smallest_pool, (
            "given_syllables_override.max must not exceed the smallest "
            "generated pool, or rng.sample(pool, n) can't be satisfied")
    else:
        hi = rng.randint(1, min(3, smallest_pool))
        lo = rng.randint(1, hi)
        weights = [rng.randint(1, 5) for _ in range(hi - lo + 1)]
    weights_literal = "[" + ", ".join(str(w) for w in weights) + "]"

    lines = [
        f'name = "{name}"',
        f'categories = {_format_list(categories)}',
        f'family = {_format_list(family_pool)}',
    ]
    for cat in categories:
        lines.append(f'given_{cat} = {_format_list(given_pools[cat])}')
    lines.append(f'place = {_format_list(place_pool)}')
    lines.append(f'place_tail = {_format_list(place_tail_pool)}')
    lines.append(f'join = "{join_style}"')
    lines.append(f'place_split = {place_split}')
    lines.append(
        f'given_syllables = {{ min = {lo}, max = {hi}, '
        f'weights = {weights_literal} }}'
    )

    if fully_specified:
        # Permissive on purpose. A restrictive generated spelling would make
        # pronounceable() reject the generated syllables, pushing generation
        # into person_name()'s deterministic fallback -- and a check
        # comparing two fallback strings would prove nothing about
        # portability. max_repeat is high because random syllables over a
        # thirteen-character alphabet produce repeated-letter runs freely.
        #
        # MUST COME LAST: in TOML a table header swallows every bare key that
        # follows it, so [spelling] any earlier would swallow the rest of
        # this culture's own keys -- exactly the mistake load_cultures()'s
        # missing-`name` error message calls out.
        lines.append("")
        lines.append("[spelling]")
        lines.append("max_length = 99")
        lines.append("ascii_only = true")
        lines.append("max_repeat = 99")
        lines.append("forbidden = []")
        lines.append("max_join_length = 99")
    # When fully_specified is False, NO [spelling] table is emitted at all --
    # that culture is the converse property's subject in Task 3.

    text = "\n".join(lines) + "\n"

    desc = {
        "categories": categories,
        "sub_alphabets": sub_alphabets,
        "pool_sizes": pool_sizes,
        "join": join_style,
        "place_split": place_split,
        "given_syllables": {"min": lo, "max": hi, "weights": weights},
        "fully_specified": fully_specified,
    }
    return text, desc


def _assert_pairwise_disjoint(subs: list) -> int:
    """Assert every pair of sets in `subs` is disjoint; return how many pairs
    were actually compared.

    The return value matters as much as the assertion: a `subs` of length 0
    or 1 makes the loop below compare zero pairs and return 0 without ever
    asserting anything. A caller that needs the disjointness property
    genuinely exercised must check the count, not just the absence of an
    AssertionError -- an assert that never ran is not evidence of anything."""
    comparisons = 0
    for i, a in enumerate(subs):
        for b in subs[i + 1:]:
            assert not (a & b), "per-category sub-alphabets must be disjoint"
            comparisons += 1
    return comparisons


def check_generator(rng) -> int:
    """The generator's contract, checked before anything relies on it.

    Returns the total number of pairwise sub-alphabet comparisons performed,
    so a caller (or this file's own verification) can confirm the
    disjointness property was genuinely exercised rather than vacuously
    satisfied.

    Loops, regenerating from the same `rng`, until a multi-category culture
    appears. A single-category culture makes _assert_pairwise_disjoint()
    compare zero pairs -- a "pass" that checked nothing. This is not
    hypothetical: random.Random(seed).randint(1, 5) draws count == 1 for
    seeds 2, 14, and 19 of the first twenty, so calling this function once
    per seed without the loop would silently skip disjointness on three of
    every twenty seeds. The trailing assert makes it impossible for this
    function to return without having compared at least one pair -- do not
    remove it or the loop above it; that reintroduces exactly this bug."""
    comparisons = 0
    for _ in range(50):  # generous: P(count >= 2) = 4/5 per draw
        text, desc = generate_culture(rng, "Ka", ALPHABET_A, fully_specified=True)
        assert 1 <= len(desc["categories"]) <= 5
        assert not ({"m", "f", "n"} & set(desc["categories"])), \
            "category names must not resemble the retired m/f/n"
        subs = [set(v) for v in desc["sub_alphabets"].values()]
        comparisons += _assert_pairwise_disjoint(subs)
        assert set("".join(desc["sub_alphabets"].values())) <= set(ALPHABET_A)
        if len(desc["categories"]) >= 2:
            break
    assert comparisons > 0, (
        "no multi-category culture appeared within the attempt budget -- "
        "the disjointness property was never exercised")
    return comparisons


def check_generated_culture(tmp: Path) -> None:
    """Generator smoke test: a culture built by generate_culture() must not
    just parse as TOML -- it must actually load through load_cultures() and
    produce names through person_name()/place_name(). This catches a
    generator that emits syntactically valid but semantically unusable TOML
    (an empty pool, a given_syllables range no pool can satisfy, and so on)
    that check_generator()'s own-invariant check cannot see, because it never
    installs the culture or generates from it.

    Also re-confirms containment on real generated output: every character
    in the generated names (case-folded, minus the space and hyphen
    separators the generator itself can insert) must belong to the culture's
    own alphabet -- the same character check later tasks use to detect
    cross-culture contamination, run here against a single culture as a
    sanity check on the check itself."""
    rng = random.Random(20260729)
    text, desc = generate_culture(rng, "Ka", ALPHABET_A, fully_specified=True)
    setting = build_setting(tmp, "generator-smoke", {"ka": text}, {}, None)
    person = g.person_name(rng, setting.inv, "ka", None)
    place = g.place_name(rng, setting.inv, "ka")
    print(f"check_generated_culture: categories={desc['categories']!r}")
    print(f"check_generated_culture: person={person!r} place={place!r}")
    for label, value in (("person", person), ("place", place)):
        stripped = value.lower().replace(" ", "").replace("-", "")
        bad = set(stripped) - set(ALPHABET_A)
        assert not bad, (
            f"{label} name {value!r} used characters outside ALPHABET_A: "
            f"{sorted(bad)}")


# ---------------------------------------------------------------------------
# Property 1: a culture is fully contained in its own file
# ---------------------------------------------------------------------------

def _collect_samples(rng: random.Random, inv: g.Inventory, key: str,
                     categories: list) -> list:
    """Person names across EVERY category (plus "any"), and several place
    names -- not one name each. One generated name can coincide with another
    by chance (a one-character syllable carries almost no signal, and
    generate_culture() can produce those -- see check_generated_culture's
    given_house=["k","l","m"] example); twenty samples spanning every
    category's own sub-alphabet cannot coincide by chance the way one can.

    Deliberately does NOT take a forced_syllables argument -- see the "why
    forced_syllables was rejected" comment in property_one()'s converse half.
    person_name() must be free to draw its own (culture-controlled) syllable
    count, because the converse's divergence depends on which BRANCH
    given_name() takes (single-syllable fallback vs. multi-syllable
    compound), not on forcing a count and hoping the retry counts differ."""
    out = []
    for cat in categories:
        for _ in range(6):
            out.append(g.person_name(rng, inv, key, cat))
    for _ in range(6):
        out.append(g.person_name(rng, inv, key, None))
    for _ in range(8):
        out.append(g.place_name(rng, inv, key))
    return out


def property_one(rng: random.Random, tmp: Path) -> list:
    """Property 1: a culture is fully contained in its own file.

    FORWARD HALF: a culture whose [spelling] table specifies every one of
    Spelling's five fields produces byte-identical output no matter what
    setting it is installed into -- a different directory, a different
    sibling culture (from the disjoint ALPHABET_B, so it couldn't leak into
    A's output even if consulted), a different setting-wide
    [names.spelling], and a different (or entirely absent) official_culture.
    None of that can leak into a fully-specified culture's generated names,
    because resolve_spelling() layers the culture's own table last -- every
    field it supplies wins regardless of what came before it.

    given_name() only consults `spelling` at all inside its multi-syllable
    join-length retry loop -- when the drawn syllable count is exactly 1, it
    returns titlecase(rng.choice(pool)) without reading spelling, correctly.
    An UNPINNED given_syllables therefore makes this half's guarantee about
    max_join_length seed-dependent: measured at 133/400 draws where the join
    branch is never taken, the byte-identical assertion below would pass
    having exercised only four of Spelling's five fields. The forward
    culture's given_syllables and given_<cat> pool entry length are pinned
    below (via the existing given_syllables_override / given_len_override)
    so every draw takes the join branch, and a positive control after the
    byte-identical assertion proves it actually did -- so what this half
    mechanically guarantees is now all five fields, on every seed, not four
    guaranteed and a fifth guaranteed only when luck cooperates.

    CONVERSE HALF: a culture that OMITS [spelling] has nothing of its own to
    override those fields with, so it must inherit the SETTING's
    [names.spelling] instead. Installed into two settings whose spelling
    differs, it must therefore produce DIFFERENT output.

    Returns report lines; raises AssertionError on failure.
    """
    lines = []

    # Independent child RNGs per concern, each seeded with a fixed, small
    # number of draws from the caller's `rng`. check_generator draws a
    # VARIABLE number of times (1-50 attempts depending on when it first
    # sees a multi-category culture); sharing one rng between it and this
    # property would shift every one of this property's draws depending on
    # how many attempts check_generator happened to need first. Giving each
    # concern its own random.Random(...), seeded once from `rng`, keeps
    # property_one's own draw count from the caller's `rng` fixed at four
    # regardless of what runs before or after it.
    culture_rng = random.Random(rng.randrange(1 << 30))
    sibling_rng = random.Random(rng.randrange(1 << 30))
    sample_seed = rng.randrange(1 << 30)
    converse_seed = rng.randrange(1 << 30)

    # ---- Forward half ------------------------------------------------

    name_a = "Aone"
    # given_len_override/given_syllables_override pin every given_<cat> pool
    # entry to exactly 2 characters and every draw to exactly 2 syllables.
    # Without this, given_syllables is randomised by generate_culture() and
    # a drawn count of 1 (measured at 133/400 unpinned draws) skips
    # given_name()'s join-length retry loop entirely -- the only place
    # `spelling` is consulted for a multi-syllable draw -- making the
    # byte-identical assertion below pass without proving max_join_length is
    # culture-supplied. Pinning to exactly 2 (only 2, not a range, so the
    # smallest per-category pool -- as few as 4 entries when count == 5 --
    # is always satisfiable; see generate_culture()'s own assertion)
    # guarantees the join branch runs on every single draw. See the
    # positive control below, which proves it did.
    text_a, desc_a = generate_culture(
        culture_rng, name_a, ALPHABET_A, fully_specified=True,
        given_len_override=(2, 2),
        given_syllables_override={"min": 2, "max": 2, "weights": [1]})
    key_a = g.culture_key(name_a)

    name_b1 = "Btwo1"
    text_b1, _ = generate_culture(sibling_rng, name_b1, ALPHABET_B,
                                  fully_specified=True)
    key_b1 = g.culture_key(name_b1)
    # sibling_rng is CONTINUED, not reseeded, for B2 -- its draws pick up
    # wherever B1's left off, which is what makes B2 genuinely "a different
    # one from ALPHABET_B" per the brief's table, not a duplicate of B1.
    name_b2 = "Btwo2"
    text_b2, _ = generate_culture(sibling_rng, name_b2, ALPHABET_B,
                                  fully_specified=True)
    assert text_b1 != text_b2, "the two sibling cultures must actually differ"

    setting_x = build_setting(
        tmp, "p1-x", {"a": text_a, "b1": text_b1}, {}, official=key_b1)
    setting_y = build_setting(
        tmp, "p1-y", {"a": text_a, "b2": text_b2},
        {"max_length": 4, "max_join_length": 3, "max_repeat": 1},
        official=None)

    categories_a = desc_a["categories"]
    out_x = _collect_samples(random.Random(sample_seed), setting_x.inv,
                             key_a, categories_a)
    out_y = _collect_samples(random.Random(sample_seed), setting_y.inv,
                             key_a, categories_a)

    assert out_x == out_y, (
        "PROPERTY 1 (forward) FAILED: a fully-specified culture's output "
        f"diverged across settings that differ in directory, sibling "
        f"culture, [names.spelling], and official_culture.\nX={out_x!r}"
        f"\nY={out_y!r}")

    # Positive control. Mirrors check_generator's `assert comparisons > 0`
    # and property_two case 4's join control: the byte-identical assertion
    # above proves nothing about max_join_length unless the join branch it
    # guards was actually taken. Every given_<cat> pool entry is pinned to
    # exactly 2 characters and every draw to exactly 2 syllables (see the
    # overrides above), so a genuine join is a 4-character concatenation
    # (after stripping any hyphen separator) -- strictly longer than any
    # single pool entry could ever be. Checked against the person-name
    # samples only (the first `person_count` entries of out_x; the
    # remainder are place names, which given_syllables/given_name never
    # touch), split on the first space to isolate the given portion from
    # the family name that precedes it.
    person_count = len(categories_a) * 6 + 6
    givens_x = [s.split(" ", 1)[1].replace("-", "")
               for s in out_x[:person_count]]
    max_single_entry = max(
        len(e) for cat in categories_a
        for e in setting_x.inv.cultures[key_a][f"given_{cat}"])
    assert any(len(giv) > max_single_entry for giv in givens_x), (
        "PROPERTY 1 (forward) positive control FAILED: not one of the "
        f"{person_count} person-name samples was longer than the longest "
        f"single given-pool entry ({max_single_entry} chars) -- the join "
        "branch (and therefore max_join_length) was never actually "
        f"exercised, so the byte-identical assertion above proved nothing "
        f"about it. Givens: {givens_x!r}")

    lines.append(
        f"property_one forward: {len(out_x)} names across "
        f"{len(categories_a)} categories (+ \"any\" + place) byte-identical "
        f"between settings X ({setting_x.directory.name}, official="
        f"{key_b1!r}) and Y ({setting_y.directory.name}, official=None); "
        f"given_syllables pinned to exactly 2 (max entry "
        f"{max_single_entry} chars) so every one of the {person_count} "
        f"person-name draws took the join branch -- confirmed, not merely "
        f"assumed, by at least one join-length sample exceeding "
        f"{max_single_entry} chars")

    # ---- Converse half -------------------------------------------------

    # The converse is not redundant. A check that only asserted "identical
    # across settings" would also pass if the spelling layers were ignored
    # entirely -- the culture's own values would win by default because
    # nothing else was ever consulted. Proving that an OMITTED key DOES
    # inherit is what distinguishes a working three-layer resolution from a
    # one-layer one.
    #
    # THE TRAP: if both settings are restrictive enough to force
    # person_name's deterministic fallback (family[0] + the first declared
    # category's given[0]), both sides return that SAME fixed string and
    # the "must differ" assertion fails -- while resolve_spelling() is
    # working correctly. This bit Plan 3: a proof test using
    # forced_syllables=2 returned identical strings from both branches and
    # proved nothing.
    #
    # WHY forced_syllables IS NOT THE FIX (a mistake made and corrected in
    # this file's history): given_name()'s STRICT path, when
    # forced_syllables is truthy, returns `titlecase(shortest)` -- the
    # shortest of its (up to 10) sampled joins -- never a single-syllable
    # fallback. Under the SAME rng consumed in the SAME order, both a tight
    # and a loose max_join_length therefore produce an n-part join; if the
    # very first sampled join already satisfies BOTH thresholds (true
    # whenever the culture's own syllables happen to run short), both
    # settings return on their first attempt, consuming identical rng draws
    # and producing IDENTICAL output. Measured directly: forced_syllables=3
    # against a fixture with uniform-length syllables produced identical
    # output on 40/40 seeds. An earlier version of this file "passed" 200
    # seeds with forced_syllables=3 only because its retry loop kept
    # regenerating cultures until it happened to draw one whose VARIED
    # syllable lengths made `shortest` differ between the two settings --
    # the divergence was an accident of which random culture got drawn, not
    # a structural consequence of the two max_join_length values. That is
    # the same trap as forced_syllables=2 above, one layer deeper.
    #
    # THE ACTUAL FIX: pin the converse culture's OWN given_syllables to a
    # fixed count of exactly 2 (given_syllables_override), and its
    # given_<cat> pools to a FIXED syllable length of 6
    # (given_len_override) -- long enough that ANY two-syllable join is
    # 2*6=12 characters, which exceeds the tight setting's
    # max_join_length=9 for every possible pair (not just the one that
    # happens to be sampled) while staying comfortably under the loose
    # setting's 25. Then call given_name() (via person_name(), through
    # _collect_samples()) UNFORCED. Under the tight setting, EVERY one of
    # its (up to 10) sampled joins is guaranteed too long, so it exhausts
    # its budget and -- because forced_syllables is falsy here -- falls
    # through to `titlecase(rng.choice(pool))`, a genuine SINGLE syllable.
    # Under the loose setting, the very first sampled pair already fits
    # (12 <= 25), so it returns the two-syllable compound immediately. This
    # is a STRUCTURAL difference (single syllable vs. compound) that holds
    # for every possible sample the rng could have drawn, not a coincidence
    # that depends on which one it did draw -- so, unlike the
    # forced_syllables attempt, this needs no retry loop: it diverges on
    # the first (and only) construction, every time. A single build-and-
    # compare is kept below rather than a loop; if it ever needed a second
    # attempt, that would itself be a red flag that the construction (not
    # the check) had broken.
    converse_rng = random.Random(converse_seed)
    name_ap = "Aprime"
    text_ap, desc_ap = generate_culture(
        converse_rng, name_ap, ALPHABET_A, fully_specified=False,
        given_len_override=(6, 6),
        given_syllables_override={"min": 2, "max": 2, "weights": [1]})
    key_ap = g.culture_key(name_ap)

    setting_xp = build_setting(
        tmp, "p1-xp", {"ap": text_ap},
        {"max_length": 40, "max_repeat": 10, "forbidden": [],
         "max_join_length": 9},
        official=None)
    setting_yp = build_setting(
        tmp, "p1-yp", {"ap": text_ap},
        {"max_length": 40, "max_repeat": 10, "forbidden": [],
         "max_join_length": 25},
        official=None)

    categories_ap = desc_ap["categories"]
    sample_seed_2 = converse_rng.randrange(1 << 30)
    out_xp = _collect_samples(random.Random(sample_seed_2), setting_xp.inv,
                              key_ap, categories_ap)
    out_yp = _collect_samples(random.Random(sample_seed_2), setting_yp.inv,
                              key_ap, categories_ap)

    assert out_xp != out_yp, (
        "PROPERTY 1 (converse) FAILED: an omitted-[spelling] culture "
        "produced IDENTICAL output across settings whose [names.spelling] "
        "differ (max_join_length 9 vs 25), despite given_syllables pinned "
        "to exactly 2 and every given syllable a fixed 6 characters (so "
        "every 2-join is 12 characters -- always > 9, always <= 25) -- the "
        "setting's spelling is not being inherited into this culture.")

    # The actual differing pair, for the report. With the construction
    # above, this is expected to be the FIRST person_name call (category
    # index 0, sample 0) -- a single 6-character syllable under the tight
    # setting vs. a 12-13 character compound under the loose one -- not
    # merely "some index eventually differs".
    diff_idx = next(i for i in range(len(out_xp)) if out_xp[i] != out_yp[i])

    # Evidence this "differs" is not two colliding FALLBACK strings.
    # person_name's fallback is
    # `f"{family[0]} {given_<categories[0]>[0].title()}"` -- identical every
    # time regardless of setting or which category was actually requested,
    # because it consults neither `p` nor the `category` argument. Checking
    # only index 0 would miss a degenerate case where, say, EVERY entry in
    # out_xp is that fallback while out_yp differs elsewhere -- `out_xp !=
    # out_yp` would still hold, but for a reason unrelated to spelling
    # inheritance. Checking that neither side is ALL fallback rules that
    # out, by name, so a future change to person_name's fallback string
    # can't silently defeat this guard.
    culture_ap = setting_xp.inv.cultures[key_ap]
    first_cat = culture_ap["categories"][0]
    fallback_ap = (f"{culture_ap['family'][0]} "
                  f"{culture_ap[f'given_{first_cat}'][0].title()}")
    assert not all(v == fallback_ap for v in out_xp), (
        "converse comparison is contaminated: every name from the "
        "max_join_length=9 setting was person_name's deterministic "
        "fallback, which does not depend on spelling at all")
    assert not all(v == fallback_ap for v in out_yp), (
        "converse comparison is contaminated: every name from the "
        "max_join_length=25 setting was person_name's deterministic "
        "fallback, which does not depend on spelling at all")

    lines.append(
        f"property_one converse: {len(out_xp)} names across "
        f"{len(categories_ap)} categories (+ \"any\" + place), pinned to "
        f"given_syllables=2 and fixed 6-char syllables, DIFFERED between "
        f"max_join_length=9 and =25 on the first (only) construction "
        f"(no retry needed) -- first mismatch at index {diff_idx}: "
        f"{out_xp[diff_idx]!r} (single syllable) vs {out_yp[diff_idx]!r} "
        f"(compound); fallback would have been {fallback_ap!r}, seen on "
        f"neither side in full")
    return lines


# ---------------------------------------------------------------------------
# Property 2: a generated name contains only the data its own culture
# specified
# ---------------------------------------------------------------------------

SEPARATORS = {" ", "-"}


def _contamination(name: str, allowed: str) -> set:
    """Characters in `name` that `allowed` does not explain.

    Lowercased first: titlecase() capitalises the first character, so a
    naive check reports every name as contaminated. Measured -- 'Nam Jin'
    against a lowercase alphabet yields {' ', 'J', 'N'} before lowering and
    {' '} after. Separators are permitted because join and place_split
    introduce them."""
    return set(name.lower()) - set(allowed) - SEPARATORS


def _hand_built_culture(name: str, categories: list, given_pools: dict, *,
                        family: list, place: list, place_tail: list,
                        join: str | None = None,
                        place_split: float | None = None,
                        given_syllables: dict | None = None,
                        species: str | None = None,
                        draws_on: str | None = None) -> str:
    """Assemble one culture's TOML text by hand, with every optional key
    OMITTED unless explicitly passed -- the opposite of generate_culture(),
    which always emits every optional key it knows about. Step 3 needs
    precise control over what is and is not present in the file, one key at
    a time, so the engine's own default (not the generator's habit of always
    emitting every key) is what is actually under test.

    This is the "dedicated deterministic-culture builder" flagged as the
    right move rather than growing generate_culture()'s override kwargs a
    third time -- a separate, purpose-built function for exactly this need."""
    lines = [
        f'name = "{name}"',
        f'categories = {_format_list(categories)}',
        f'family = {_format_list(family)}',
    ]
    for cat in categories:
        lines.append(f'given_{cat} = {_format_list(given_pools[cat])}')
    lines.append(f'place = {_format_list(place)}')
    lines.append(f'place_tail = {_format_list(place_tail)}')
    if join is not None:
        lines.append(f'join = "{join}"')
    if place_split is not None:
        lines.append(f'place_split = {place_split}')
    if given_syllables is not None:
        weights_literal = "[" + ", ".join(
            str(w) for w in given_syllables["weights"]) + "]"
        lines.append(
            f'given_syllables = {{ min = {given_syllables["min"]}, '
            f'max = {given_syllables["max"]}, weights = {weights_literal} }}')
    if species is not None:
        lines.append(f'species = "{species}"')
    if draws_on is not None:
        lines.append(f'draws_on = "{draws_on}"')
    return "\n".join(lines) + "\n"


def property_two(rng: random.Random, tmp: Path) -> list:
    """Property 2: a generated name contains only the data its own culture
    specified.

    STEP 1 (cross-culture contamination) installs two cultures built from
    the disjoint ALPHABET_A/ALPHABET_B (the same construction property_one
    uses) into one setting, then draws family names, given names for every
    category (+ "any"), and place names from BOTH and asserts none contains
    a character the OTHER alphabet supplies. Checked with person_name(),
    where the culture's FULL alphabet is the right allowance -- its family
    pool legitimately draws from the whole alphabet, not a category's
    sub-alphabet. Because ALPHABET_A and ALPHABET_B partition the entire
    lowercase alphabet between them (13 letters each, a-m / n-z), asserting
    "no character outside my own alphabet" is exactly equivalent to
    asserting "no character from the sibling's alphabet" -- there is nowhere
    else a leaked character could come from.

    STEP 2 (categories are honoured) asserts every character of a name drawn
    for category C comes from C's own sub-alphabet -- checked with
    given_name() DIRECTLY, not person_name(): person_name() prepends a
    family name drawn from the culture's full alphabet, so a real category
    leak would be indistinguishable from a legitimate family character if
    person_name()'s output were checked instead. given_name() returns only
    the given portion, making the check exact.

    STEP 3 asserts eight "no generator assumptions leak" cases against
    hand-built cultures (via _hand_built_culture(), which omits every
    optional key unless told to include it) so the engine's real default
    is what gets exercised, not merely what generate_culture() happens to
    always emit.

    Returns report lines; raises AssertionError on failure.
    """
    lines = []

    # ---- Steps 1 & 2 setup: two cultures, disjoint alphabets --------------
    culture_rng = random.Random(rng.randrange(1 << 30))
    sibling_rng = random.Random(rng.randrange(1 << 30))

    name_a = "Ptwoa"
    text_a, desc_a = generate_culture(culture_rng, name_a, ALPHABET_A,
                                      fully_specified=True)
    key_a = g.culture_key(name_a)

    name_b = "Ptwob"
    text_b, desc_b = generate_culture(sibling_rng, name_b, ALPHABET_B,
                                      fully_specified=True)
    key_b = g.culture_key(name_b)

    setting = build_setting(tmp, "p2", {"a": text_a, "b": text_b}, {},
                            official=None)

    cross_checked = 0
    category_checked = 0
    inv = setting.inv
    # ---- Step 1: cross-culture contamination -----------------------
    cross_rng = random.Random(rng.randrange(1 << 30))
    for key, desc, allowed in ((key_a, desc_a, ALPHABET_A),
                               (key_b, desc_b, ALPHABET_B)):
        samples = []
        for cat in desc["categories"]:
            for _ in range(30):
                samples.append(g.person_name(cross_rng, inv, key, cat))
        for _ in range(30):
            samples.append(g.person_name(cross_rng, inv, key, None))
        for _ in range(30):
            samples.append(g.place_name(cross_rng, inv, key))
        for name in samples:
            bad = _contamination(name, allowed)
            assert not bad, (
                f"PROPERTY 2 (cross-culture) FAILED: culture {key!r}'s "
                f"name {name!r} used character(s) {sorted(bad)} outside "
                f"its own alphabet {allowed!r} -- indistinguishable "
                f"from a leak of the sibling culture's alphabet, since "
                f"the two partition the entire lowercase alphabet "
                f"between them")
            cross_checked += 1

    # ---- Step 2: categories are honoured -----------------------------
    given_rng = random.Random(rng.randrange(1 << 30))
    for key, desc in ((key_a, desc_a), (key_b, desc_b)):
        culture = inv.cultures[key]
        spelling = inv.spelling[key]
        for cat in desc["categories"]:
            for _ in range(200):
                name = g.given_name(
                    random.Random(given_rng.randrange(1 << 30)),
                    culture, cat, spelling=spelling)
                bad = _contamination(name, desc["sub_alphabets"][cat])
                assert not bad, (
                    f"PROPERTY 2 (category) FAILED: category {cat!r} of "
                    f"culture {key!r} leaked {sorted(bad)} into "
                    f"{name!r}")
                category_checked += 1

    lines.append(
        f"property_two step 1 (cross-culture): {cross_checked} names "
        f"checked across 2 cultures ({len(desc_a['categories'])} + "
        f"{len(desc_b['categories'])} categories, + \"any\" + place); none "
        f"used a character outside its own culture's alphabet")
    lines.append(
        f"property_two step 2 (categories honoured): {category_checked} "
        f"given_name() draws (200 per category) across "
        f"{len(desc_a['categories']) + len(desc_b['categories'])} total "
        f"categories; none leaked outside its own sub-alphabet")

    # ---- Step 3: no generator assumptions leak -----------------------------
    case_lines = []
    step3_rng = random.Random(rng.randrange(1 << 30))

    # Case 1: a culture with ONE category.
    text_one = _hand_built_culture(
        "Solo", ["clan"], {"clan": ["qa", "qb", "qc"]},
        family=["fa", "fb"], place=["pa", "pb"], place_tail=["ta", "tb"])
    setting_one = build_setting(tmp, "p2-one-cat", {"solo": text_one}, {},
                                official=None)
    for _ in range(10):
        g.person_name(step3_rng, setting_one.inv, "solo", "clan")
        g.person_name(step3_rng, setting_one.inv, "solo", None)
        g.place_name(step3_rng, setting_one.inv, "solo")
    case_lines.append(
        "1. one category ('Solo', categories=['clan']): 10 person names "
        "(category + \"any\") and 10 place names generated without error")

    # Case 2: a culture with FIVE categories.
    five_cats = ["clan", "kin", "line", "sept", "house"]
    five_pools = {
        "clan": ["ca", "cb", "cc"], "kin": ["ka", "kb", "kc"],
        "line": ["la", "lb", "lc"], "sept": ["sa", "sb", "sc"],
        "house": ["ha", "hb", "hc"],
    }
    text_five = _hand_built_culture(
        "Fivecat", five_cats, five_pools,
        family=["fa", "fb"], place=["pa", "pb"], place_tail=["ta", "tb"])
    setting_five = build_setting(tmp, "p2-five-cat", {"five": text_five}, {},
                                 official=None)
    for cat in five_cats:
        for _ in range(5):
            g.person_name(step3_rng, setting_five.inv, "fivecat", cat)
    for _ in range(10):
        g.person_name(step3_rng, setting_five.inv, "fivecat", None)
    case_lines.append(
        "2. five categories ('Fivecat', categories="
        f"{five_cats!r}): 5 person names per category + 10 \"any\" "
        "generated without error")

    # Case 3: category names bearing NO resemblance to m/f/n.
    assert "wibblefloop" not in {"m", "f", "n"}
    text_weird = _hand_built_culture(
        "Weirdcat", ["wibblefloop"], {"wibblefloop": ["wa", "wb", "wc"]},
        family=["fa", "fb"], place=["pa", "pb"], place_tail=["ta", "tb"])
    setting_weird = build_setting(tmp, "p2-weird-cat", {"weird": text_weird},
                                  {}, official=None)
    for _ in range(10):
        g.person_name(step3_rng, setting_weird.inv, "weirdcat", "wibblefloop")
    case_lines.append(
        "3. category name resembling nothing like m/f/n ('wibblefloop'): "
        "10 person names generated without error")

    # Case 4: OMITTING `join` concatenates (no '-' in output).
    #
    # Checked with given_name() directly (not person_name()) so the sample
    # is exactly the given-name portion -- each pool entry is 2 characters
    # and given_syllables is pinned to exactly 2, so a genuine two-part
    # concatenation is exactly 4 characters, while a single-syllable draw
    # (the given_name() branch taken when n == 1) is exactly 2.
    text_nojoin = _hand_built_culture(
        "Nojoin", ["clan"],
        {"clan": ["ab", "bc", "cd", "de", "ef", "fg"]},
        family=["fa", "fb"], place=["pa", "pb"], place_tail=["ta", "tb"],
        given_syllables={"min": 2, "max": 2, "weights": [1]})
    setting_nojoin = build_setting(tmp, "p2-no-join", {"nj": text_nojoin},
                                   {}, official=None)
    culture_nj = setting_nojoin.inv.cultures["nojoin"]
    spelling_nj = setting_nojoin.inv.spelling["nojoin"]
    no_join_givens = [
        g.given_name(step3_rng, culture_nj, "clan", spelling=spelling_nj)
        for _ in range(30)]
    assert not any("-" in n for n in no_join_givens), (
        f"omitting join must concatenate (no '-'), got {no_join_givens!r}")
    # Positive control. Without this, a regression that made
    # syllable_count() (or the `n = forced_syllables or syllable_count(...)`
    # line in given_name()) always return 1 would route every draw through
    # the n == 1 single-syllable branch -- which has no separator of any
    # kind either -- and the no-hyphen assertion above would pass without a
    # join ever having happened. Asserting a genuine 4-character
    # concatenation actually occurred closes that gap.
    assert any(len(n) == 4 for n in no_join_givens), (
        f"expected at least one genuine 2-syllable concatenation (4 "
        f"characters, no separator) -- omitting join was never actually "
        f"exercised. Lengths seen: {sorted(len(n) for n in no_join_givens)}, "
        f"names: {no_join_givens!r}")
    case_lines.append(
        "4. omitting `join`: 30 given names (given_syllables pinned to "
        "exactly 2) generated via given_name() directly; none contained "
        "'-', and at least one was a genuine 4-character 2-syllable "
        "concatenation (ruling out a silent fall-back to 1 syllable)")

    # Case 5: OMITTING `place_split` never splits (no ' ' in a place name).
    #
    # Audited for the same vacuous-capable shape as case 4 and found NOT
    # vacuous: place_name()'s `split = float(culture.get("place_split",
    # 0.0))` is read once per call, and `if split and rng.random() < split:`
    # is evaluated on every one of the (up to 50) attempts -- there is no
    # branch that only executes when a key is present. A regression that
    # changed the default to, say, 1.0 would make that guard fire on
    # essentially every attempt (rng.random() < 1.0 for all but an
    # astronomically unlikely draw), and the no-space assertion below would
    # then fail loudly -- so, unlike case 4's original form, there is no
    # code path here that makes "no split happened" indistinguishable from
    # "no split was ever possible". No positive control needed.
    text_nosplit = _hand_built_culture(
        "Nosplit", ["clan"], {"clan": ["aa", "bb"]},
        family=["fa", "fb"], place=["ka", "ko", "ku"],
        place_tail=["ra", "ro", "ru"])
    setting_nosplit = build_setting(tmp, "p2-no-split", {"ns": text_nosplit},
                                    {}, official=None)
    no_split_places = [g.place_name(step3_rng, setting_nosplit.inv, "nosplit")
                       for _ in range(30)]
    assert not any(" " in p for p in no_split_places), (
        f"omitting place_split must never split, got {no_split_places!r}")
    case_lines.append(
        "5. omitting `place_split`: 30 place names generated, none "
        "contained ' '")

    # Case 6: OMITTING `given_syllables` uses 1-2 syllables.
    #
    # Audited for the same vacuous-capable shape as case 4. The upper bound
    # alone (`syllable_counts <= {1, 2}`) would NOT have caught a regression
    # that silently narrowed the default max from 2 to 1: syllable_count()'s
    # `hi = int(spec.get("max", 2))` returning 1 instead would make every
    # draw exactly 1, and `{1} <= {1, 2}` is still true -- the omitted key
    # would then only ever produce a single syllable, and nothing here would
    # say so. Asserting equality (both 1 and 2 actually observed) closes
    # that gap; with the real default weights ([1, 1], equal probability),
    # the chance of missing either value across 200 draws is astronomically
    # small (~2 * 0.5**200), so this is not a flaky assertion.
    syllable_rng = random.Random(rng.randrange(1 << 30))
    syllable_counts = {g.syllable_count(syllable_rng, {}) for _ in range(200)}
    assert syllable_counts == {1, 2}, (
        f"omitting given_syllables should draw both 1 and 2 syllables "
        f"(never more, and not stuck at just one), got "
        f"{sorted(syllable_counts)}")
    text_nogs = _hand_built_culture(
        "Nogs", ["clan"], {"clan": ["ab", "bc", "cd", "de", "ef", "fg"]},
        family=["fa", "fb"], place=["pa", "pb"], place_tail=["ta", "tb"])
    setting_nogs = build_setting(tmp, "p2-no-given-syllables",
                                 {"nogs": text_nogs}, {}, official=None)
    for _ in range(10):
        g.person_name(step3_rng, setting_nogs.inv, "nogs", "clan")
    case_lines.append(
        "6. omitting `given_syllables`: syllable_count(rng, {}) sampled "
        f"200 times, all results in {{1, 2}} (observed {sorted(syllable_counts)}); "
        "a culture omitting the key also loaded and generated 10 names "
        "without error")

    # Case 7: OMITTING `species` and `draws_on` loads and generates.
    text_nosd = _hand_built_culture(
        "Nospeciesdraws", ["clan"], {"clan": ["aa", "bb"]},
        family=["fa", "fb"], place=["pa", "pb"], place_tail=["ta", "tb"])
    setting_nosd = build_setting(tmp, "p2-no-species-draws",
                                 {"nosd": text_nosd}, {}, official=None)
    culture_nosd = setting_nosd.inv.cultures["nospeciesdraws"]
    assert culture_nosd["species"] == "", (
        "omitted species must default to '', got "
        f"{culture_nosd['species']!r}")
    assert culture_nosd["draws_on"] == "", (
        "omitted draws_on must default to '', got "
        f"{culture_nosd['draws_on']!r}")
    for _ in range(5):
        g.person_name(step3_rng, setting_nosd.inv, "nospeciesdraws", "clan")
        g.place_name(step3_rng, setting_nosd.inv, "nospeciesdraws")
    case_lines.append(
        "7. omitting `species` and `draws_on`: both defaulted to '' after "
        "load_cultures(), and 5 person + 5 place names generated without "
        "error")

    # Case 8: with NO official_culture configured, official_name() returns
    # None every time. A contrasting setting with official_culture pointing
    # at a REAL sibling key (never a non-existent one, which KeyErrors
    # inside place_name()) confirms the None case is not simply vacuous --
    # that official_name() genuinely branches on inv.official_culture rather
    # than always returning None regardless of configuration.
    text_no_official_c = _hand_built_culture(
        "Noofficial", ["clan"], {"clan": ["aa", "bb"]},
        family=["fa", "fb"], place=["pa", "pb"], place_tail=["ta", "tb"])
    setting_no_official = build_setting(
        tmp, "p2-no-official", {"c": text_no_official_c}, {}, official=None)
    official_results = [g.official_name(step3_rng, setting_no_official.inv)
                       for _ in range(20)]
    assert all(r is None for r in official_results), (
        "with no official_culture configured, official_name() must return "
        f"None every time, got {official_results!r}")

    text_official_target = _hand_built_culture(
        "Officialtarget", ["clan"], {"clan": ["aa", "bb"]},
        family=["fa", "fb"], place=["pa", "pb"], place_tail=["ta", "tb"])
    key_target = g.culture_key("Officialtarget")
    setting_with_official = build_setting(
        tmp, "p2-with-official",
        {"c": text_no_official_c, "t": text_official_target}, {},
        official=key_target)
    contrast_results = [g.official_name(step3_rng, setting_with_official.inv)
                       for _ in range(10)]
    assert all(r is not None for r in contrast_results), (
        "sanity check failed: with official_culture pointing at a real "
        f"sibling key, official_name() must not return None, got "
        f"{contrast_results!r}")
    case_lines.append(
        "8. no official_culture configured: official_name() returned None "
        "on all 20 draws; contrast check with official_culture pointing "
        "at a real sibling key returned a non-None name on all 10 draws "
        "(rules out a vacuously-always-None official_name())")

    lines.append("property_two step 3 (no generator assumptions leak):")
    lines.extend(f"  {line}" for line in case_lines)

    return lines


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prove a culture file is a portable unit.")
    parser.add_argument("--seed", type=int, default=20260729,
                        help="Randomisation seed (default: fixed, so the "
                             "suite is deterministic)")
    args = parser.parse_args(argv)
    rng = random.Random(args.seed)

    # Each concern gets its OWN random.Random(...), seeded once from this
    # top-level `rng` in a FIXED order. check_generator consumes a VARIABLE
    # number of draws from whatever rng it is given (1-50 attempts,
    # depending on when it first sees a multi-category culture). If
    # check_generator, property_one, and property_two all drew from the
    # SAME rng instance, property_one's and property_two's results would
    # shift depending on how many attempts check_generator happened to need
    # -- making the report depend on call order rather than on --seed alone.
    # Deriving three independent child seeds from `rng` here, always in this
    # order, keeps every concern's behaviour a pure function of --seed
    # regardless of how many draws any other concern makes internally.
    generator_rng = random.Random(rng.randrange(1 << 30))
    property_one_rng = random.Random(rng.randrange(1 << 30))
    property_two_rng = random.Random(rng.randrange(1 << 30))

    # Everything below is created under `tmp` and nothing outside it is ever
    # touched, so teardown must run even when a check raises -- the
    # workspace is never left written to.
    tmp = Path(tempfile.mkdtemp(prefix="portability-"))
    try:
        print(f"check_portability: seed={args.seed}")

        comparisons = check_generator(generator_rng)
        print(f"check_generator: generator's own invariants hold "
              f"({comparisons} disjoint sub-alphabet pair(s) compared)")

        check_generated_culture(tmp)

        report_lines = []
        report_lines.extend(property_one(property_one_rng, tmp))
        report_lines.extend(property_two(property_two_rng, tmp))
        print("\n".join(report_lines))

        print(f"\nPASSED (seed={args.seed})")
        return 0
    except AssertionError as exc:
        print(f"\nFAILED: {exc}")
        print(f"Reproduce with: python3 tests/check_portability.py "
              f"--seed {args.seed}")
        return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
