"""Portable engine tests for generate_names.

Every test builds its own fixtures; nothing reads the enclosing repository.
The rule, enforced by a boundary guard in the campaign-coupled suite: no
golden constant, no named culture, no run_cli against a real inventory.
This file must pass in any checkout of any campaign, and ships with the
engine when it is packaged (Phase 4).

Do not name the campaign or its cultures here, even in comments — the
boundary guard greps this file for them."""

import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from bunnyforge import _config, _workspace, generate_names


def run_cli_in(workspace: Path, *args: str) -> tuple[int, str]:
    """Invoke main() against `workspace` with an explicit argv; return
    (exit code, stdout + stderr concatenated)."""
    buf = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(err):
        code = generate_names.main(["--workspace", str(workspace), *args])
    return code, buf.getvalue() + err.getvalue()


# Two synthetic cultures with distinct species and draws_on, giving resolve()
# an alias to miss (an unknown culture) and a real key/species/draws_on set
# to load and generate from. Every name is invented: the boundary guard in
# the campaign-coupled suite greps this file for the real ones. Alias
# resolution BY species/basis is exercised only in the campaign-coupled
# suite for now (design spec non-goal 3).
_WOLD_CULTURE = (
    'name = "Wold"\nspecies = "Selkie"\ndraws_on = "Wealdish"\n'
    'categories = ["m", "f"]\n'
    'family = ["Ash", "Bern"]\ngiven_m = ["cor", "dun"]\n'
    'given_f = ["eda", "fen"]\n'
    'place = ["Grim"]\nplace_tail = ["holt"]\n'
)
_BRACK_CULTURE = (
    'name = "Brack"\nspecies = "Troll"\ndraws_on = "Marshkin"\n'
    'categories = ["m"]\n'
    'family = ["Moor"]\ngiven_m = ["gof", "hem"]\n'
    'place = ["Sedge"]\nplace_tail = ["mere"]\n'
)


def synthetic_inventory(tc: unittest.TestCase,
                        official_culture: str | None = None):
    """A two-culture Inventory from a throwaway on-disk workspace, loaded
    through the same path a real campaign takes: campaign.toml ->
    open_workspace() -> load_inventory(). `official_culture` is written to
    [names] when given and omitted otherwise — the omitted form is the
    unconfigured case load_inventory resolves to None."""
    d = Path(tc.enterContext(tempfile.TemporaryDirectory())).resolve()
    names = '[names]\ncultures = "cultures"\n'
    if official_culture is not None:
        names += f'official_culture = "{official_culture}"\n'
    (d / "campaign.toml").write_text(
        '[campaign]\nnamespace = "t"\n\n' + names, encoding="utf-8")
    cdir = d / "cultures"
    cdir.mkdir()
    (cdir / "wold.toml").write_text(_WOLD_CULTURE, encoding="utf-8")
    (cdir / "brack.toml").write_text(_BRACK_CULTURE, encoding="utf-8")
    return generate_names.load_inventory(_config.open_workspace(d))


class TestDistribution(unittest.TestCase):
    """Complements the campaign-coupled suite's byte-for-byte goldens: these
    assert the shape of the output (distribution, honoured constraints)
    rather than exact bytes, for behaviour the goldens' fixed seeds don't
    exercise.

    The campaign-coupled half of this class lives in the campaign suite."""

    def test_default_single_to_compound_ratio_holds(self):
        import random as _random
        rng = _random.Random(11)
        spec = {"min": 1, "max": 2, "weights": [0.65, 0.35]}
        counts = [generate_names.syllable_count(rng, spec) for _ in range(20000)]
        singles = counts.count(1) / len(counts)
        self.assertAlmostEqual(singles, 0.65, delta=0.02)

    def test_weights_length_mismatch_is_rejected(self):
        import random as _random
        with self.assertRaises(generate_names.InventoryError):
            generate_names.syllable_count(
                _random.Random(1), {"min": 1, "max": 3, "weights": [1, 1]})

    def test_official_name_is_none_without_a_configured_culture(self):
        import random as _random
        inv = synthetic_inventory(self)   # no [names].official_culture
        self.assertIsNone(inv.official_culture)   # the load path left it unset
        self.assertIsNone(
            generate_names.official_name(_random.Random(1), inv))

    def test_official_name_resolves_the_configured_culture(self):
        # The positive sibling of the test above: with an official culture
        # actually configured, official_name() must return a name built from
        # THAT culture, not the other one and not an unconditional non-None
        # placeholder either.
        #
        # wold's place pool and place_tail pool each hold exactly one entry
        # ("Grim", "holt"), so place_name()'s two rng.choice(pool) calls have
        # nothing to choose between — the result is "Grimholt" regardless of
        # seed. Measured directly (seeds 1-29, plus the module's own default
        # instantiation): always "Grimholt". Asserting the exact string, not
        # just non-None, pins the value AND proves it came from wold's own
        # vocabulary (family/place syllables invented for this fixture)
        # rather than brack's ("Sedge" + "mere" -> "Sedgemere", equally
        # deterministic by the same one-entry-pool argument) — a broken
        # official_name() that always returned some non-empty string, or one
        # that silently reached for the wrong configured culture, would not
        # satisfy this.
        import random as _random
        inv = synthetic_inventory(self, official_culture="wold")
        self.assertEqual(inv.official_culture, "wold")  # the load path resolved it
        for seed in (1, 2, 3):
            with self.subTest(seed=seed):
                self.assertEqual(
                    generate_names.official_name(_random.Random(seed), inv),
                    "Grimholt")


class TestCultureResolution(unittest.TestCase):
    """The campaign-coupled half of this class lives in the campaign suite."""

    def test_resolve_returns_none_for_unknown(self):
        inv = synthetic_inventory(self)
        self.assertIsNone(generate_names.resolve(inv.cultures, "klingon"))


class TestResolveOfficialCulture(unittest.TestCase):
    """resolve_official_culture() normalises and validates campaign.toml's
    [names].official_culture. Called from load_inventory() to build an
    Inventory's official_culture field — see generate_names.py. Covered
    directly here because it is a pure function: the case below calls it
    against a synthetic workspace's cultures dict rather than exercising
    the full CLI.

    The campaign-coupled half of this class lives in the campaign suite."""

    def test_unconfigured_returns_none(self):
        # official_name() treats a falsy Inventory.official_culture as "this
        # setting has no official language"; that must keep working.
        cultures = synthetic_inventory(self).cultures
        self.assertIsNone(
            generate_names.resolve_official_culture(None, cultures))
        self.assertIsNone(
            generate_names.resolve_official_culture("", cultures))


class TestCultureLoading(unittest.TestCase):
    """load_cultures scans a directory; the file IS the culture."""

    # Bare keys only, and no table header, so a fragment appended by _write
    # cannot be swallowed by a preceding table. See the TOML scoping trap.
    _BASE_CULTURE = (
        'name = "X"\nspecies = "S"\ndraws_on = "D"\n'
        'categories = ["m", "f"]\n'
        'family = ["A"]\ngiven_m = ["a"]\ngiven_f = ["b"]\n'
        'place = ["P"]\nplace_tail = ["t"]\n'
    )

    def _tmp(self) -> Path:
        return Path(self.enterContext(tempfile.TemporaryDirectory()))

    def _write(self, d: Path, extra: str = "", stem: str = "x",
               base: str | None = None) -> Path:
        path = d / f"{stem}.toml"
        text = (self._BASE_CULTURE if base is None else base) + extra
        path.write_text(text, encoding="utf-8")
        return path

    def test_missing_directory_names_the_path(self):
        d = self._tmp()
        with self.assertRaises(generate_names.InventoryError) as ctx:
            generate_names.load_cultures(d / "nope")
        self.assertIn("nope", str(ctx.exception))

    def test_empty_directory_is_rejected(self):
        d = self._tmp()
        with self.assertRaises(generate_names.InventoryError) as ctx:
            generate_names.load_cultures(d)
        self.assertIn("no culture files", str(ctx.exception))

    def test_the_key_is_derived_from_the_name(self):
        d = self._tmp()
        self._write(d, base='name = "Wold Mere"\n'
                    + self._BASE_CULTURE.split("\n", 1)[1])
        cultures = generate_names.load_cultures(d)
        self.assertEqual(list(cultures), ["woldmere"])
        self.assertEqual(cultures["woldmere"]["name"], "Wold Mere")

    def test_the_filename_is_not_read(self):
        # A culture file works under any filename; matching the key is
        # convention, not requirement.
        d = self._tmp()
        self._write(d, stem="totally-unrelated")
        self.assertEqual(list(generate_names.load_cultures(d)), ["x"])

    def test_a_file_missing_name_is_rejected_naming_the_file(self):
        d = self._tmp()
        body = self._BASE_CULTURE.split("\n", 1)[1]        # drop the name line
        self._write(d, base=body, stem="nameless")
        with self.assertRaises(generate_names.InventoryError) as ctx:
            generate_names.load_cultures(d)
        self.assertIn("nameless.toml", str(ctx.exception))
        self.assertIn("name", str(ctx.exception))

    def test_colliding_names_are_rejected_naming_both_files(self):
        d = self._tmp()
        self._write(d, stem="one")
        self._write(d, stem="two", base='name = "x"\n'
                    + self._BASE_CULTURE.split("\n", 1)[1])
        with self.assertRaises(generate_names.InventoryError) as ctx:
            generate_names.load_cultures(d)
        msg = str(ctx.exception)
        self.assertIn("one.toml", msg)
        self.assertIn("two.toml", msg)

    def test_species_and_draws_on_are_optional_and_default_to_empty(self):
        d = self._tmp()
        body = "".join(line + "\n" for line in self._BASE_CULTURE.splitlines()
                       if not line.startswith(("species", "draws_on")))
        self._write(d, base=body)
        c = generate_names.load_cultures(d)["x"]
        self.assertEqual(c["species"], "")
        self.assertEqual(c["draws_on"], "")

    def _base_without_species_and_draws_on(self) -> str:
        return "".join(line + "\n" for line in self._BASE_CULTURE.splitlines()
                       if not line.startswith(("species", "draws_on")))

    def test_non_string_species_is_rejected_naming_the_file(self):
        # Issue #69: a quoting typo (`species = 42`, meant "42"?) used to be
        # accepted silently and surface as odd output — or, via resolve(),
        # as an AttributeError traceback.
        d = self._tmp()
        self._write(d, extra="species = 42\n",
                    base=self._base_without_species_and_draws_on(),
                    stem="typo")
        with self.assertRaises(generate_names.InventoryError) as ctx:
            generate_names.load_cultures(d)
        msg = str(ctx.exception)
        self.assertIn("typo.toml", msg)
        self.assertIn("species", msg)
        self.assertIn("42", msg)

    def test_non_string_draws_on_is_rejected_naming_the_file(self):
        d = self._tmp()
        self._write(d, extra="draws_on = true\n",
                    base=self._base_without_species_and_draws_on(),
                    stem="typo")
        with self.assertRaises(generate_names.InventoryError) as ctx:
            generate_names.load_cultures(d)
        msg = str(ctx.exception)
        self.assertIn("typo.toml", msg)
        self.assertIn("draws_on", msg)

    def test_a_list_valued_species_is_rejected(self):
        # The other shape a TOML typo takes. Worth its own case because a
        # list has a .lower()-free failure mode distinct from an int's.
        d = self._tmp()
        self._write(d, extra='species = ["Dwarf"]\n',
                    base=self._base_without_species_and_draws_on())
        with self.assertRaises(generate_names.InventoryError) as ctx:
            generate_names.load_cultures(d)
        self.assertIn("species", str(ctx.exception))

    def test_empty_string_species_and_draws_on_remain_legal(self):
        # "" is a real value a culture may set — the packaged starter culture
        # ships `species = ""` deliberately — and must not be swept up by the
        # new check. The unset case is covered by
        # test_species_and_draws_on_are_optional_and_default_to_empty above.
        d = self._tmp()
        self._write(d, extra='species = ""\ndraws_on = ""\n',
                    base=self._base_without_species_and_draws_on())
        c = generate_names.load_cultures(d)["x"]
        self.assertEqual(c["species"], "")
        self.assertEqual(c["draws_on"], "")

    def test_culture_missing_a_required_key_is_rejected(self):
        d = self._tmp()
        body = "".join(line + "\n" for line in self._BASE_CULTURE.splitlines()
                       if not line.startswith("place_tail"))
        self._write(d, base=body)
        with self.assertRaises(generate_names.InventoryError) as ctx:
            generate_names.load_cultures(d)
        self.assertIn("place_tail", str(ctx.exception))

    def test_malformed_toml_names_the_file(self):
        d = self._tmp()
        (d / "bad.toml").write_text("name = \n", encoding="utf-8")
        with self.assertRaises(generate_names.InventoryError) as ctx:
            generate_names.load_cultures(d)
        self.assertIn("bad.toml", str(ctx.exception))

    def test_non_toml_files_are_ignored(self):
        d = self._tmp()
        self._write(d)
        (d / "README.md").write_text("not a culture\n", encoding="utf-8")
        self.assertEqual(list(generate_names.load_cultures(d)), ["x"])

    def test_invalid_join_style_is_rejected(self):
        d = self._tmp()
        self._write(d, 'join = "hyphn"\n')
        with self.assertRaises(generate_names.InventoryError) as ctx:
            generate_names.load_cultures(d)
        self.assertIn("join", str(ctx.exception))
        self.assertIn("hyphn", str(ctx.exception))

    def test_non_numeric_place_split_is_rejected(self):
        d = self._tmp()
        self._write(d, 'place_split = "yes"\n')
        with self.assertRaises(generate_names.InventoryError) as ctx:
            generate_names.load_cultures(d)
        self.assertIn("place_split", str(ctx.exception))

    def test_out_of_range_place_split_is_rejected(self):
        d = self._tmp()
        self._write(d, "place_split = 1.5\n")
        with self.assertRaises(generate_names.InventoryError) as ctx:
            generate_names.load_cultures(d)
        self.assertIn("place_split", str(ctx.exception))

    def _without_categories(self) -> str:
        # _BASE_CULTURE now bakes in `categories = ["m", "f"]`; tests that
        # need to declare their own value build from this instead, so the
        # replacement doesn't duplicate the TOML key.
        return "".join(line + "\n" for line in self._BASE_CULTURE.splitlines()
                       if not line.startswith("categories"))

    def test_categories_must_be_a_non_empty_list_of_strings(self):
        body = self._without_categories()
        for bad in ('categories = "m"\n', "categories = []\n",
                    "categories = [1, 2]\n"):
            with self.subTest(bad=bad):
                d = self._tmp()
                self._write(d, bad, base=body)
                with self.assertRaises(generate_names.InventoryError) as ctx:
                    generate_names.load_cultures(d)
                self.assertIn("categories", str(ctx.exception))

    def test_every_listed_category_needs_a_non_empty_pool(self):
        d = self._tmp()
        self._write(d, 'categories = ["m", "spark"]\n',
                   base=self._without_categories())
        with self.assertRaises(generate_names.InventoryError) as ctx:
            generate_names.load_cultures(d)
        msg = str(ctx.exception)
        self.assertIn("spark", msg)
        self.assertIn("given_spark", msg)

    def test_a_listed_category_with_an_empty_pool_is_rejected(self):
        # given_m must be overridden to an empty pool, and categories must be
        # overridden too, so neither can come from _BASE_CULTURE unchanged
        # (that would duplicate the key); build a base with both lines
        # removed instead.
        d = self._tmp()
        body = "".join(line + "\n" for line in self._BASE_CULTURE.splitlines()
                       if not line.startswith(("given_m", "categories")))
        self._write(d, 'categories = ["m"]\ngiven_m = []\n', base=body)
        with self.assertRaises(generate_names.InventoryError) as ctx:
            generate_names.load_cultures(d)
        self.assertIn("given_m", str(ctx.exception))

    def test_duplicate_category_names_are_rejected(self):
        # Nothing else catches this: with categories = ["m", "m"] and a
        # single given_m pool, category_pool(c, None) silently concatenates
        # given_m with itself, doubling the pool LENGTH. random.sample draws
        # through _randbelow(n), whose bit consumption is a function of
        # population size, so a copy-pasted category line would silently
        # alter every seeded name from that culture with no diagnostic —
        # exactly the failure mode this check exists to catch at load time.
        d = self._tmp()
        self._write(d, 'categories = ["m", "m"]\n',
                   base=self._without_categories())
        with self.assertRaises(generate_names.InventoryError) as ctx:
            generate_names.load_cultures(d)
        msg = str(ctx.exception)
        self.assertIn("m", msg)
        self.assertIn("repeat", msg)

    def test_a_given_key_naming_no_listed_category_is_rejected(self):
        # Catches the typo a keys-only design cannot: `givne_sparker` and
        # `categories = ["holdre"]` are the same class of mistake, and only
        # cross-checking both directions finds either.
        #
        # given_m/given_f are required here only because _BASE_CULTURE's
        # `categories` declares ["m", "f"], and _validate_categories demands
        # a pool per declared category — they are not in _REQUIRED_KEYS
        # itself. So they cannot simply be dropped from the base — instead
        # both of _BASE_CULTURE's existing pools are declared in
        # `categories`, so given_sprak is the only undeclared given_* key to
        # be reported.
        d = self._tmp()
        self._write(d, 'categories = ["m", "f"]\ngiven_sprak = ["b"]\n',
                   base=self._without_categories())
        with self.assertRaises(generate_names.InventoryError) as ctx:
            generate_names.load_cultures(d)
        self.assertIn("given_sprak", str(ctx.exception))

    def test_given_syllables_min_over_max_is_rejected(self):
        d = self._tmp()
        self._write(d, "given_syllables = { min = 3, max = 1 }\n")
        with self.assertRaises(generate_names.InventoryError) as ctx:
            generate_names.load_cultures(d)
        self.assertIn("given_syllables", str(ctx.exception))

    def test_given_syllables_below_one_is_rejected(self):
        d = self._tmp()
        self._write(d, "given_syllables = { min = 0, max = 1 }\n")
        with self.assertRaises(generate_names.InventoryError) as ctx:
            generate_names.load_cultures(d)
        self.assertIn("given_syllables", str(ctx.exception))

    def test_given_syllables_weights_length_mismatch_is_rejected_at_load(self):
        d = self._tmp()
        self._write(
            d, "given_syllables = { min = 1, max = 3, weights = [1, 1] }\n")
        with self.assertRaises(generate_names.InventoryError) as ctx:
            generate_names.load_cultures(d)
        self.assertIn("given_syllables", str(ctx.exception))

    def test_given_syllables_non_table_is_rejected(self):
        d = self._tmp()
        self._write(d, "given_syllables = 5\n")
        with self.assertRaises(generate_names.InventoryError) as ctx:
            generate_names.load_cultures(d)
        self.assertIn("given_syllables", str(ctx.exception))
        self.assertIn("x", str(ctx.exception))

    def test_given_syllables_non_list_weights_is_rejected(self):
        d = self._tmp()
        self._write(
            d, "given_syllables = { min = 1, max = 2, weights = 5 }\n")
        with self.assertRaises(generate_names.InventoryError) as ctx:
            generate_names.load_cultures(d)
        self.assertIn("weights", str(ctx.exception))
        self.assertIn("x", str(ctx.exception))

    def test_given_syllables_string_weights_is_rejected(self):
        # A string is len()-able and iterable, so without an explicit
        # list/tuple check this would sail past the length check and fail
        # later, mid-generation, inside rng.choices.
        d = self._tmp()
        self._write(
            d, 'given_syllables = { min = 1, max = 2, weights = "ab" }\n')
        with self.assertRaises(generate_names.InventoryError) as ctx:
            generate_names.load_cultures(d)
        self.assertIn("weights", str(ctx.exception))
        self.assertIn("x", str(ctx.exception))

    def test_given_syllables_non_numeric_weight_elements_are_rejected(self):
        d = self._tmp()
        self._write(
            d,
            'given_syllables = { min = 1, max = 2, weights = ["a", "b"] }\n')
        with self.assertRaises(generate_names.InventoryError) as ctx:
            generate_names.load_cultures(d)
        self.assertIn("weights", str(ctx.exception))
        self.assertIn("x", str(ctx.exception))

    def test_given_syllables_negative_weight_is_rejected(self):
        d = self._tmp()
        self._write(
            d, "given_syllables = { min = 1, max = 2, weights = [-1, 2] }\n")
        with self.assertRaises(generate_names.InventoryError) as ctx:
            generate_names.load_cultures(d)
        self.assertIn("weights", str(ctx.exception))
        self.assertIn("x", str(ctx.exception))

    def test_given_syllables_all_zero_weights_are_rejected(self):
        # rng.choices raises ValueError on an all-zero weight list; this must
        # be caught at load time instead, with the file and culture named.
        d = self._tmp()
        self._write(
            d, "given_syllables = { min = 1, max = 2, weights = [0, 0] }\n")
        with self.assertRaises(generate_names.InventoryError) as ctx:
            generate_names.load_cultures(d)
        self.assertIn("weights", str(ctx.exception))
        self.assertIn("x", str(ctx.exception))

    def test_valid_optional_keys_are_accepted(self):
        d = self._tmp()
        self._write(
            d, 'join = "hyphen"\nplace_split = 0.5\n'
            "given_syllables = { min = 1, max = 2, weights = [0.5, 0.5] }\n")
        cultures = generate_names.load_cultures(d)
        self.assertIn("x", cultures)


class TestSpelling(unittest.TestCase):

    def test_default_matches_the_legacy_filter(self):
        p = generate_names._DEFAULT_SPELLING
        self.assertEqual(p.max_length, 12)
        self.assertTrue(p.ascii_only)
        self.assertEqual(p.max_repeat, 2)
        self.assertIn("ng'", p.forbidden)

    def test_rejects_over_max_length(self):
        p = generate_names.Spelling(4, True, 2, (), 9)
        self.assertFalse(generate_names.pronounceable("abcde", p))
        self.assertTrue(generate_names.pronounceable("abcd", p))

    def test_ascii_only_can_be_relaxed(self):
        strict = generate_names.Spelling(12, True, 2, (), 9)
        relaxed = generate_names.Spelling(12, False, 2, (), 9)
        self.assertFalse(generate_names.pronounceable("Ngô", strict))
        self.assertTrue(generate_names.pronounceable("Ngô", relaxed))

    def test_max_repeat_is_honoured(self):
        p = generate_names.Spelling(12, True, 2, (), 9)
        self.assertFalse(generate_names.pronounceable("aaa", p))
        self.assertTrue(generate_names.pronounceable("aab", p))

    def test_forbidden_substrings_are_honoured(self):
        p = generate_names.Spelling(12, True, 9, ("zz",), 9)
        self.assertFalse(generate_names.pronounceable("buzz", p))
        self.assertTrue(generate_names.pronounceable("buz", p))


class TestGenderFlag(unittest.TestCase):
    """--gender takes free-form category names. The engine knows none of them.

    The campaign-coupled half of this class lives in the campaign suite."""

    def test_gender_is_not_restricted_to_a_fixed_choice_list(self):
        # The old --sex had choices=["m","f","n"], which argparse enforced
        # before any culture was consulted. A culture is free to call its
        # categories anything, so the flag must not pre-judge the value.
        for action in generate_names.build_parser()._actions:
            if "--gender" in getattr(action, "option_strings", []):
                self.assertIsNone(action.choices)
                break
        else:
            self.fail("--gender not found")


class TestSpellingResolution(unittest.TestCase):
    """Each layer overrides individual keys of the one beneath."""

    def test_no_overrides_returns_the_base_unchanged(self):
        base = generate_names._DEFAULT_SPELLING
        self.assertIs(generate_names.resolve_spelling(base, {}), base)

    def test_a_single_key_overrides_only_that_key(self):
        base = generate_names._DEFAULT_SPELLING
        got = generate_names.resolve_spelling(base, {"max_join_length": 20})
        self.assertEqual(got.max_join_length, 20)
        self.assertEqual(got.max_length, base.max_length)
        self.assertEqual(got.ascii_only, base.ascii_only)
        self.assertEqual(got.max_repeat, base.max_repeat)
        self.assertEqual(got.forbidden, base.forbidden)

    def test_forbidden_is_normalised_to_a_tuple(self):
        # TOML gives a list; the namedtuple is compared and hashed, so the
        # type must not depend on which layer supplied the value.
        got = generate_names.resolve_spelling(
            generate_names._DEFAULT_SPELLING, {"forbidden": ["zz"]})
        self.assertEqual(got.forbidden, ("zz",))

    def test_layers_compose_left_to_right(self):
        setting = generate_names.resolve_spelling(
            generate_names._DEFAULT_SPELLING, {"ascii_only": False})
        culture = generate_names.resolve_spelling(setting, {"max_length": 30})
        self.assertFalse(culture.ascii_only)      # from the setting layer
        self.assertEqual(culture.max_length, 30)  # from the culture layer
        self.assertEqual(culture.max_repeat,      # from the built-in layer
                         generate_names._DEFAULT_SPELLING.max_repeat)

    def test_an_unknown_key_is_rejected(self):
        # A typo like `max_lenght` must not silently do nothing. Silently
        # ignoring it is exactly the class of bug this phase exists to kill:
        # the culture would generate wrongly and never say so.
        with self.assertRaises(generate_names.InventoryError) as ctx:
            generate_names.resolve_spelling(
                generate_names._DEFAULT_SPELLING, {"max_lenght": 20})
        msg = str(ctx.exception)
        self.assertIn("max_lenght", msg)
        self.assertIn("max_length", msg)   # lists the valid keys


class TestCultureSpelling(unittest.TestCase):
    """Layer 3: a culture carries its own constraints in its own file."""

    # given_syllables is pinned to exactly 2 so the compound path is always
    # taken; the two syllables are 10 characters each, so a join is 20 — well
    # over the default max_join_length of 9.
    _BASE = (
        'name = "Longwind"\n'
        'categories = ["m"]\n'
        'family = ["Aa"]\n'
        'given_m = ["bramblewor", "thistledow"]\n'
        'place = ["Wold"]\nplace_tail = ["mere"]\n'
        'given_syllables = { min = 2, max = 2 }\n'
    )

    # The setting layer used as the base for every resolution below. It
    # deliberately differs from _DEFAULT_SPELLING (max_repeat 3 vs 2) so
    # "inherits the setting layer" is distinguishable from "fell back to
    # the built-in defaults" — with a base equal to the defaults those are
    # the same claim and the tests prove nothing about layering. It must
    # NOT touch max_join_length: test_the_culture_layer_actually_changes_
    # generation depends on the default cap of 9 rejecting a 20-char join.
    @staticmethod
    def _setting():
        return generate_names.resolve_spelling(
            generate_names._DEFAULT_SPELLING, {"max_repeat": 3})

    def _tmp(self) -> Path:
        return Path(self.enterContext(tempfile.TemporaryDirectory()))

    def _write(self, extra: str = "") -> Path:
        d = self._tmp()
        (d / "longwind.toml").write_text(self._BASE + extra, encoding="utf-8")
        return d

    def test_a_culture_without_spelling_inherits_the_setting_layer(self):
        setting = self._setting()
        # The tripwire that keeps this test non-degenerate: if the synthetic
        # base ever equals the defaults again, fail HERE, not silently.
        self.assertNotEqual(setting, generate_names._DEFAULT_SPELLING)
        c = generate_names.load_cultures(self._write())["longwind"]
        self.assertEqual(
            generate_names.resolve_spelling(setting, c.get("spelling", {})),
            setting)

    def test_a_culture_spelling_block_overrides_the_setting(self):
        setting = self._setting()
        d = self._write("\n[spelling]\nmax_length = 30\n")
        c = generate_names.load_cultures(d)["longwind"]
        got = generate_names.resolve_spelling(setting, c["spelling"])
        self.assertEqual(got.max_length, 30)
        # The untouched key holds the SETTING's value, not the built-in
        # default — the distinction the old inventory-based base could not
        # see.
        self.assertEqual(got.max_repeat, 3)

    def test_an_unknown_spelling_key_is_rejected_naming_the_file(self):
        d = self._write("\n[spelling]\nmax_lenght = 30\n")
        with self.assertRaises(generate_names.InventoryError) as ctx:
            generate_names.load_cultures(d)
        msg = str(ctx.exception)
        self.assertIn("longwind.toml", msg)
        self.assertIn("max_lenght", msg)

    def test_spelling_must_be_a_table(self):
        d = self._write('\nspelling = "loose"\n')
        with self.assertRaises(generate_names.InventoryError) as ctx:
            generate_names.load_cultures(d)
        self.assertIn("spelling", str(ctx.exception))

    def test_the_culture_layer_actually_changes_generation(self):
        # The real proof of layer 3, and the replacement for the deleted
        # --profile test. A two-syllable join here is 20 characters, over the
        # default max_join_length of 9, so every one of the ten attempts is
        # rejected and given_name falls back to a SINGLE syllable. Raising the
        # cap in the CULTURE'S OWN FILE lets the compound through.
        #
        # Note the call is deliberately UNFORCED. With forced_syllables=2 both
        # branches return a two-syllable join — the strict path returns the
        # shortest join it found rather than falling back — and with only two
        # syllables in the pool every join is the same length, so the two
        # results come out identical and the test proves nothing. Measured:
        # that version returns 'Thistledowbramblewor' from both.
        import random as _random

        setting = self._setting()   # leaves max_join_length at the default 9
        tight = generate_names.load_cultures(self._write())["longwind"]
        loose = generate_names.load_cultures(
            self._write("\n[spelling]\nmax_join_length = 25\n"))["longwind"]

        s_tight = generate_names.resolve_spelling(
            setting, tight.get("spelling", {}))
        s_loose = generate_names.resolve_spelling(setting, loose["spelling"])

        for seed in (5, 7, 11):
            with self.subTest(seed=seed):
                a = generate_names.given_name(_random.Random(seed), tight,
                                              "m", spelling=s_tight)
                b = generate_names.given_name(_random.Random(seed), loose,
                                              "m", spelling=s_loose)
                self.assertNotEqual(a, b)
                self.assertGreater(len(b), len(a))


class TestLoadErrorsAreClean(unittest.TestCase):
    """A broken workspace must produce `error: <message>` and exit 1 — not a
    traceback. Until this plan, the load ran at import, where nothing could
    catch it (parent spec carry-forward 2)."""

    def _broken_workspace(self, culture_toml: str | None) -> Path:
        d = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        (d / "campaign.toml").write_text(
            '[campaign]\nnamespace = "t"\n\n[names]\n'
            'cultures = "names/cultures"\n', encoding="utf-8")
        cdir = d / "names" / "cultures"
        cdir.mkdir(parents=True)
        if culture_toml is not None:
            (cdir / "bad.toml").write_text(culture_toml, encoding="utf-8")
        return d

    def _malformed_workspace(self) -> Path:
        d = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        (d / "campaign.toml").write_text(
            '[campaign\nnamespace = "t"\n', encoding="utf-8")  # unclosed table header
        return d

    def _run_against(self, root: Path, *args: str) -> tuple[int, str]:
        return run_cli_in(root, *args)

    def test_a_broken_culture_file_is_a_clean_error(self):
        root = self._broken_workspace('name = "Bad"\n')   # missing required keys
        code, out = self._run_against(root, "--list")
        self.assertEqual(code, 1)
        self.assertIn("error:", out)
        self.assertIn("bad.toml", out)
        self.assertNotIn("Traceback", out)

    def test_an_empty_cultures_directory_is_a_clean_error(self):
        root = self._broken_workspace(None)               # dir exists, no files
        code, out = self._run_against(root, "--list")
        self.assertEqual(code, 1)
        self.assertIn("error:", out)
        self.assertNotIn("Traceback", out)

    def test_a_malformed_campaign_toml_is_a_clean_error(self):
        # ConfigError's path: campaign.toml itself fails to parse. Pins that
        # main()'s except tuple must include ConfigError, not just
        # InventoryError -- dropping it left this case uncovered.
        d = self._malformed_workspace()
        code, out = self._run_against(d, "--list")
        self.assertEqual(code, 1)
        self.assertIn("error:", out)
        self.assertNotIn("Traceback", out)

    def test_a_malformed_campaign_toml_is_a_clean_error_end_to_end(self):
        # The caveat this test used to carry is now dead, and this is what
        # killed it. Until Plan 5, the in-process test above only reached
        # main()'s catch because bunnyforge._config had already imported
        # cleanly against the real campaign workspace earlier in the test
        # process; a genuine CLI invocation tracebacked, because _config.py
        # ran `CONFIG = load(WORKSPACE)` at IMPORT, before main() existed to
        # catch anything. A fresh child process is the only thing that can
        # tell those two apart, so the guarantee is asserted in one.
        d = self._malformed_workspace()
        env = {k: v for k, v in os.environ.items()
               if k != "BUNNYFORGE_WORKSPACE"}
        env["BUNNYFORGE_WORKSPACE"] = str(d)
        result = subprocess.run(
            [sys.executable, "-m", "bunnyforge.generate_names", "--list"],
            cwd=d, capture_output=True, text=True, env=env)
        both = result.stdout + result.stderr
        self.assertEqual(result.returncode, 1, both)
        self.assertNotIn("Traceback", both)
        errors = [ln for ln in both.splitlines() if ln.startswith("error:")]
        self.assertEqual(len(errors), 1, both)
        self.assertIn("not valid TOML", errors[0])

    def test_no_workspace_at_all_is_a_clean_error(self):
        # WorkspaceError's path, reachable at last. Until Plan 5 removed the
        # install-repo fallback, _workspace.resolve_root() could not raise,
        # so main()'s except tuple deliberately omitted WorkspaceError and
        # this test could not be written -- a run from nowhere silently
        # generated names out of whatever campaign the package happened to
        # be installed from. With no flag, no BUNNYFORGE_WORKSPACE and no
        # marker above the cwd, there is nothing left to resolve, and the
        # user must be told so rather than shown a traceback (which is what
        # leaving WorkspaceError out of the tuple now produces).
        bare = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        for parent in [bare, *bare.parents]:
            self.assertFalse((parent / "campaign.toml").exists(),
                             f"unexpected campaign.toml at {parent}")
        env = {k: v for k, v in os.environ.items()
               if k != "BUNNYFORGE_WORKSPACE"}
        result = subprocess.run(
            [sys.executable, "-m", "bunnyforge.generate_names", "--list"],
            cwd=bare, capture_output=True, text=True, env=env)
        both = result.stdout + result.stderr
        self.assertEqual(result.returncode, 1, both)
        self.assertNotIn("Traceback", both)
        errors = [ln for ln in both.splitlines() if ln.startswith("error:")]
        self.assertEqual(len(errors), 1, both)
        self.assertIn("no campaign.toml found in", errors[0])
        # The card's remedies sit on lines after the `error:` first line.
        for remedy in ("cd into that folder",
                       'bunnyforge init my-campaign --name "My Campaign"',
                       "--workspace", _workspace.DOCS_URL):
            self.assertIn(remedy, both)

    def test_a_workspace_broken_two_ways_reports_the_cultures_error_first(self):
        # Pins load_inventory's error precedence: the cultures-configured
        # guard runs BEFORE setting-spelling resolution (deliberately
        # reordered from the retired module pipeline -- see load_inventory's
        # docstring), so a workspace broken both ways -- no [names].cultures
        # configured AND an invalid [names.spelling] key -- reports the
        # missing-cultures error, not the spelling one.
        d = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        (d / "campaign.toml").write_text(
            '[campaign]\nnamespace = "t"\n\n'
            '[names.spelling]\nmax_lenght = 30\n', encoding="utf-8")
        code, out = self._run_against(d, "--list")
        self.assertEqual(code, 1)
        self.assertIn("no name cultures configured", out)
        self.assertNotIn("max_lenght", out)


class TestMultiCultureHeader(unittest.TestCase):
    """The header a multi-culture run prints above each culture's names.
    `species` and `draws_on` are both optional, so the header carries only
    the ones a culture actually sets — a fixed `(species, draws_on)`
    template strands the punctuation of whichever is missing."""

    # stem, name, species, draws_on, the whole header line expected for it.
    _CASES = (
        ("corvane", "Corvane", "", "", "Corvane"),
        ("dunmere", "Dunmere", "Naiad", "", "Dunmere  (Naiad)"),
        ("eastholt", "Eastholt", "", "Highfen", "Eastholt  (Highfen)"),
        ("fennow", "Fennow", "Kobold", "Lowmarsh",
         "Fennow  (Kobold, Lowmarsh)"),
    )

    # The required keys, identical for every culture here: nothing in this
    # class asserts a generated name, only the header above one.
    _POOLS = ('categories = ["m"]\n'
              'family = ["Ash"]\ngiven_m = ["cor", "dun"]\n'
              'place = ["Grim"]\nplace_tail = ["holt"]\n')

    def _workspace(self, files: dict) -> Path:
        """A throwaway workspace whose cultures directory holds `files` —
        a culture file stem mapped to that file's whole TOML text."""
        d = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        (d / "campaign.toml").write_text(
            '[campaign]\nnamespace = "t"\n\n[names]\n'
            'cultures = "cultures"\n', encoding="utf-8")
        cdir = d / "cultures"
        cdir.mkdir()
        for stem, text in files.items():
            (cdir / f"{stem}.toml").write_text(text, encoding="utf-8")
        return d

    def _four_case_workspace(self) -> Path:
        """All four cases at once, so one run prints every header form. No
        generated name can contain a culture's own display name — the pools
        are shared and invented — which is what lets the guard test below
        assert a name's absence."""
        files = {}
        for stem, name, species, draws_on, _ in self._CASES:
            optional = "".join(
                f'{key} = "{value}"\n' for key, value
                in (("species", species), ("draws_on", draws_on)) if value)
            files[stem] = f'name = "{name}"\n{optional}' + self._POOLS
        return self._workspace(files)

    def test_the_header_carries_only_the_fields_a_culture_sets(self):
        code, out = run_cli_in(self._four_case_workspace(),
                               "--seed", "1", "-n", "1")
        self.assertEqual(code, 0, out)
        lines = out.splitlines()
        for _, _, species, draws_on, expected in self._CASES:
            with self.subTest(species=species or None,
                              draws_on=draws_on or None):
                self.assertIn(expected, lines)

    def test_a_single_culture_run_prints_no_header(self):
        # The header belongs to multi-culture runs only, so naming a culture
        # must leave nothing but indented names. Guards the opposite failure
        # of the one above: a header reduced to a bare culture name is
        # indistinguishable from a name, so it must not print at all.
        code, out = run_cli_in(self._four_case_workspace(),
                               "--seed", "1", "-n", "1", "fennow")
        self.assertEqual(code, 0, out)
        self.assertNotIn("Fennow", out)
        for line in out.splitlines():
            if line.strip():
                self.assertTrue(line.startswith("  "), line)

    def test_a_non_string_field_is_refused_cleanly_at_the_cli(self):
        # Was test_a_non_string_field_still_prints_instead_of_crashing, which
        # pinned the pre-#69 behaviour: the loader accepted a non-string
        # species and the header coerced it with str() so it printed rather
        # than raising. #69 moved the defence to the loader, so the same
        # workspaces now fail fast instead — but the invariant this test has
        # always really been about is unchanged: a broken workspace gets one
        # error: line and exit 1, never a traceback.
        for literal in ("42", "true", "0"):
            with self.subTest(species=literal):
                root = self._workspace({
                    "vesper": f'name = "Vesper"\nspecies = {literal}\n'
                              + self._POOLS,
                    "marrow": 'name = "Marrow"\ndraws_on = "Marshkin"\n'
                              + self._POOLS,
                })
                code, out = run_cli_in(root, "--seed", "1", "-n", "1")
                self.assertEqual(code, 1, out)
                self.assertNotIn("Traceback", out)
                self.assertIn("species must be a string", out)


if __name__ == "__main__":
    unittest.main()
