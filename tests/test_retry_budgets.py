"""Coverage for generate_names.NAME_ATTEMPTS, owned by no other test file.

Issue #62: setting NAME_ATTEMPTS to 1 left all 82 tests in
test_generate_names.py green -- a count measured 2026-07-31, before Plan 6
split that file into portable and campaign-coupled suites; it now holds 55
portable tests. Its only guard in the whole repo was the sample-6 test in
test_samples.py -- the one file this plan's coupled/portable split
deliberately leaves in place (the design spec's non-goal 2: released !=
relocated) -- so losing that single test would have dropped the coverage
silently.

Re-measured 2026-07-31 against the post-split files -- test_generate_names.py
(portable, 55 tests), test_campaign_names.py (coupled, 28 tests),
test_samples.py, and this file -- so the boundary is on record rather than
assumed:

    GIVEN_JOIN_ATTEMPTS = 1  ->  test_generate_names.py passes; the guard
                                 that used to live there moved with the
                                 coupled tests -- test_campaign_names.py
                                 FAILS; test_samples.py and this file pass
    NAME_ATTEMPTS = 1        ->  test_generate_names.py and
                                 test_campaign_names.py both pass;
                                 test_samples.py and this file FAIL

So this file exists for NAME_ATTEMPTS alone; its sibling budget still needs
nothing here -- GIVEN_JOIN_ATTEMPTS remains caught, just by
test_campaign_names.py now rather than test_generate_names.py. But
test_campaign_names.py is the campaign-coupled half: it stays behind with the
campaign at Phase 4, while test_generate_names.py ships with the engine. So
that catch does not travel with the packaged engine suite -- the portable
half has no GIVEN_JOIN_ATTEMPTS guard of its own, a gap now recorded as a
non-goal in the Plan 6 design spec (`docs/superpowers/specs/
2026-07-31-phase-2-plan-6-test-split-design.md`) for Phase 4 to close. For
THIS repo, today, coverage is intact -- nothing above is a live bug -- but
it is a Phase 4 packaging concern, not a closed one.

Deliberately its own file rather than an addition to test_generate_names.py:
at the time of issue #62 that module was the file about to be reorganised by
Plan 6's coupled/portable split -- it is now the portable half, and the
campaign-coupled half is tests/test_campaign_names.py -- so parking the
replacement coverage inside it would have repeated exactly the mistake #62
describes. Everything here builds its own fixtures -- no golden constant, no
named culture, no real inventory -- so it is portable by the phase-2 spec's
own rule and has no stake in that split.
"""

import random
import unittest

from bunnyforge import generate_names as g

# A spelling whose only rule is one forbidden pair, so a candidate's fate is
# decided by whether it contains "qq" and nothing else. Keeps these fixtures
# independent of the default spelling's lengths and repeat limits.
SPELLING = g.Spelling(max_length=12, ascii_only=True, max_repeat=2,
                      forbidden=("qq",), max_join_length=9)

REJECTED = [f"{c}qq" for c in "ABCDEFGHI"]   # nine candidates that never pass
ACCEPTED = "Ma"                              # the one that does


def _inventory(culture: dict) -> g.Inventory:
    return g.Inventory(cultures={"probe": culture}, spelling={"probe": SPELLING},
                       setting_spelling=SPELLING, official_culture=None)


def _culture(place: list[str], family: list[str]) -> dict:
    # Single-element given/tail lists are load-bearing for the counting tests
    # below: given_name() clamps its syllable count to len(pool), so a
    # one-syllable pool forces exactly one rng.choice() per call and makes
    # the call count stable rather than dependent on syllable_count()'s draw.
    return {"name": "Fallbackia", "place": place, "place_tail": ["ta"],
            "family": family, "categories": ["personal"],
            "given_personal": ["Ta"]}


NOTHING_PASSES = _culture(place=REJECTED, family=REJECTED)
SOMETHING_PASSES = _culture(place=REJECTED + [ACCEPTED],
                            family=REJECTED + [ACCEPTED])

# The documented fallbacks, spelled out here rather than computed, so a
# change to either fallback expression fails these tests instead of being
# silently mirrored by them.
PLACE_FALLBACK = "Fallbackia"                       # culture["name"]
PERSON_FALLBACK = "Aqq Ta"                          # family[0] + given[0]


class _CountingRandom(random.Random):
    """Counts choice() calls, so a test can observe how many attempts the
    generator actually made. Note the attribute is NOT named `choices`:
    that would shadow random.Random.choices, which syllable_count() calls."""

    def __init__(self, seed):
        super().__init__(seed)
        self.n_choice = 0

    def choice(self, seq):
        self.n_choice += 1
        return super().choice(seq)


class TestTheLoopsHonourTheBudget(unittest.TestCase):
    """Exhausting the budget must take exactly NAME_ATTEMPTS attempts.

    Compared against the constant rather than against 50, so retuning the
    budget stays a one-line change -- but hardcoding the loop (`range(1)`)
    or deleting the retry entirely fails here.

    Both fixtures make one rng.choice() per attempt in each of two places
    (place head + tail; family + given syllable), hence 2 x NAME_ATTEMPTS.
    """

    def test_place_name_exhausts_the_budget(self):
        rng = _CountingRandom(0)
        self.assertEqual(g.place_name(rng, _inventory(NOTHING_PASSES), "probe"),
                         PLACE_FALLBACK)
        self.assertEqual(rng.n_choice, 2 * g.NAME_ATTEMPTS)

    def test_person_name_exhausts_the_budget(self):
        rng = _CountingRandom(0)
        self.assertEqual(
            g.person_name(rng, _inventory(NOTHING_PASSES), "probe", None),
            PERSON_FALLBACK)
        self.assertEqual(rng.n_choice, 2 * g.NAME_ATTEMPTS)


class TestTheFallbacksAreReachable(unittest.TestCase):
    """When nothing can pass, each generator returns its documented
    deterministic fallback.

    This is also what stops the retry tests below from being vacuous: it
    proves the fallback is a real, reachable outcome, so "the result is not
    the fallback" is a claim with something behind it.
    """

    def test_place_name_falls_back_to_the_culture_name(self):
        for seed in (0, 1, 2):
            with self.subTest(seed=seed):
                self.assertEqual(
                    g.place_name(random.Random(seed),
                                 _inventory(NOTHING_PASSES), "probe"),
                    PLACE_FALLBACK)

    def test_person_name_falls_back_to_the_first_declared_entries(self):
        for seed in (0, 1, 2):
            with self.subTest(seed=seed):
                self.assertEqual(
                    g.person_name(random.Random(seed),
                                  _inventory(NOTHING_PASSES), "probe", None),
                    PERSON_FALLBACK)


class TestRetryingIsWhatFindsAName(unittest.TestCase):
    """The budget must be big enough to do its job, not merely honoured.

    One candidate in ten passes, and seed 2's first draws are all rejects,
    so a single attempt yields the fallback. Measured at this seed: the
    smallest budget that still finds a name is 5 for place_name and 4 for
    person_name, against a shipped NAME_ATTEMPTS of 50. Any cut below those
    fails here -- including the cut to 1 that issue #62 was filed about.
    """

    SEED = 2

    def test_place_name_finds_a_name_a_single_attempt_would_miss(self):
        got = g.place_name(random.Random(self.SEED),
                           _inventory(SOMETHING_PASSES), "probe")
        self.assertNotEqual(got, PLACE_FALLBACK)
        self.assertEqual(got, "Mata")

    def test_person_name_finds_a_name_a_single_attempt_would_miss(self):
        got = g.person_name(random.Random(self.SEED),
                            _inventory(SOMETHING_PASSES), "probe", None)
        self.assertNotEqual(got, PERSON_FALLBACK)
        self.assertEqual(got, "Ma Ta")


if __name__ == "__main__":
    unittest.main()
