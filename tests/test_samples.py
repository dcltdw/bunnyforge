import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

from bunnyforge import generate_names as g

REPO = Path(__file__).resolve().parent.parent
SAMPLES = REPO / "samples"


def discovered():
    """Sample directories, sorted. A sample is a directory with a cultures/."""
    return sorted(p for p in SAMPLES.iterdir()
                  if p.is_dir() and (p / "cultures").is_dir())


def _flatten(mapping, prefix=()):
    """Yield (path-tuple, leaf-value) for every non-table key in a parsed
    TOML dict, recursing into nested tables. Used to compare "what the
    additions file declared" against "what the merge actually produced"
    key-by-key rather than just checking the merged text still parses."""
    for key, value in mapping.items():
        path = prefix + (key,)
        if isinstance(value, dict):
            yield from _flatten(value, path)
        else:
            yield path, value


def _get_path(mapping, path):
    node = mapping
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None, False
        node = node[key]
    return node, True


def merge_additions(campaign_text, additions_text):
    """Merge a sample's campaign-additions.toml into a host campaign.toml.

    PRECONDITION: if `additions_text` sets `official_culture`, `campaign_text`
    must already have its own `official_culture` line stripped before being
    passed in. This function only inserts; it does not overwrite. Calling it
    with a raw campaign.toml that still sets `official_culture` raises
    `tomllib.TOMLDecodeError: Cannot overwrite a value` -- correct, but it
    names the symptom, not this precondition, so it is spelled out here too.

    Appending the additions file wholesale is NOT safe: samples 7 and 8 ship
    their own explicit `[names]` header (a rule their READMEs impose, so the
    file is self-contained about scoping rather than depending on whatever
    table the host happens to leave open last), and `campaign.toml` already
    declares `[names]`. Two `[names]` headers in one TOML file is invalid --
    `tomllib.TOMLDecodeError: Cannot declare ('names',) twice`.

    So merge the way each sample's own README tells a human to: bare keys
    that the additions file places directly under `[names]` are inserted
    immediately after the HOST's existing `[names]` header line; any
    subtable (e.g. `[names.spelling]`) is appended verbatim at the end, since
    the host does not already declare it.

    Comments are dropped -- they exist to instruct a human doing this by
    hand, not to be re-parsed. This includes this repo's own
    commented-out-key convention (`# [names.spelling]` / `# ascii_only =
    true`): a future additions file relying on a reader to uncomment such a
    block would have that instruction silently discarded here. Nothing today
    does this.

    A bare key that precedes no header at all -- violating the very
    convention samples 7 and 8's READMEs establish -- is neither a "bare key
    under [names]" nor part of any other table, by this function's line
    scan, and would otherwise vanish from the merge with no error: the
    result is still well-formed TOML, just incomplete, so `tomllib.loads`
    alone cannot catch it. The positive control below does: every key
    `additions_text` declares, parsed on its own, must appear in the merged
    result with the same value, or this raises naming exactly which key was
    lost.
    """
    bare_keys = []
    tables = []
    in_names = False
    in_other_table = False
    for line in additions_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("["):
            if stripped == "[names]":
                in_names, in_other_table = True, False
            else:
                in_names, in_other_table = False, True
                tables.append(line)
            continue
        if in_other_table:
            tables.append(line)
        elif in_names:
            bare_keys.append(line)

    out = []
    inserted = not bare_keys
    for line in campaign_text.splitlines():
        out.append(line)
        if not inserted and line.strip() == "[names]":
            out.extend(bare_keys)
            inserted = True
    assert inserted, "host campaign.toml has no [names] header to merge under"

    merged = "\n".join(out) + "\n"
    if tables:
        merged += "\n" + "\n".join(tables) + "\n"

    # Assert validity here, at the merge, rather than confusingly at the
    # subprocess's own import time -- a future additions file that breaks
    # this helper's assumptions should fail loudly and close to the cause.
    merged_parsed = tomllib.loads(merged)

    # Positive control: every key the additions file itself declares must
    # have actually landed in the merge, unchanged. tomllib.loads succeeding
    # only proves the merged text is well-formed -- it says nothing about
    # whether a key silently fell on the floor (exactly what happens to a
    # bare key with no preceding [names] header, per the docstring above).
    for path, declared_value in _flatten(tomllib.loads(additions_text)):
        actual_value, present = _get_path(merged_parsed, path)
        dotted = ".".join(path)
        assert present and actual_value == declared_value, (
            f"campaign-additions.toml declares {dotted} = {declared_value!r} "
            f"but the merged campaign.toml has {dotted} = "
            f"{actual_value!r} ({'present' if present else 'missing'}) -- "
            "check the additions file follows the [names]-header convention"
        )

    return merged


class TestSampleDiscovery(unittest.TestCase):
    """Every sample must load through the shipping loader, so none can rot.

    Discovery-based on purpose: a ninth sample added later gets coverage
    automatically rather than silently going untested."""

    def test_at_least_one_sample_is_discovered(self):
        # Anti-vacuous guard. Every other test here iterates discovered(),
        # so if discovery returned nothing they would all pass having
        # checked nothing. This is the assertion that makes the rest mean
        # something.
        self.assertGreater(len(discovered()), 0)

    def test_the_full_sample_ladder_is_discovered(self):
        # discovered() matches by STRUCTURE (any samples/* with a cultures/
        # subdirectory), so a sample built wrong -- e.g. culture files left
        # at its root instead of under cultures/ -- is silently invisible to
        # every test in this module, all of which iterate discovered(). The
        # guard above only catches ALL samples vanishing at once; it cannot
        # catch just one going missing while the rest still pass. Assert the
        # specific expected directory names, rather than a bare count of 8,
        # so a ninth sample added later (which the design wants to gain
        # coverage automatically) does not fail this test -- only a missing
        # or misbuilt one of the current eight does.
        expected = {
            "1-one-people", "2-many-peoples", "3-name-shape", "4-genders",
            "5-name-registers", "6-spelling", "7-official-language",
            "8-capstone",
        }
        found = {p.name for p in discovered()}
        self.assertTrue(expected <= found, f"missing: {expected - found}")

    def test_every_sample_loads(self):
        for sample in discovered():
            with self.subTest(sample=sample.name):
                cultures = g.load_cultures(sample / "cultures")
                self.assertGreater(len(cultures), 0)

    def test_every_sample_culture_declares_no_species(self):
        # The project ships no species-to-real-world-tradition mappings.
        # A sample that filled in `species` would assert one.
        for sample in discovered():
            for key, culture in g.load_cultures(sample / "cultures").items():
                with self.subTest(sample=sample.name, culture=key):
                    self.assertEqual(culture["species"], "")

    def test_no_toml_sits_directly_in_a_sample_root_except_additions(self):
        # The loader's glob is non-recursive, which is why cultures live in
        # cultures/. A stray .toml in a sample root would be scanned as a
        # culture if [names].cultures ever pointed at the root.
        for sample in discovered():
            for path in sample.glob("*.toml"):
                with self.subTest(sample=sample.name, file=path.name):
                    self.assertEqual(path.name, "campaign-additions.toml")

    def test_sample_5_categories_are_not_gendered(self):
        # Sample 5's whole lesson is that `categories` was never about
        # gender. If a future edit slipped an "m"/"f"/"n" key back in, the
        # sample would still load fine -- only this asserts the lesson.
        sample = SAMPLES / "5-name-registers"
        for key, culture in g.load_cultures(sample / "cultures").items():
            with self.subTest(sample=sample.name, culture=key):
                self.assertTrue(
                    set(culture["categories"]).isdisjoint({"m", "f", "n"}))

    def test_sample_6_cultures_resolve_to_different_max_join_length(self):
        # Static half of the design's property 3: wertisand's own
        # [spelling] must actually change the resolved max_join_length
        # relative to huttanmesh, which carries none. Computed by calling
        # the shipping resolve_spelling() against each culture's own
        # `[spelling]` table layered on the built-in default -- the bare
        # state, with no campaign-additions.toml setting layer involved --
        # rather than hardcoding "12 vs 9".
        sample = SAMPLES / "6-spelling"
        cultures = g.load_cultures(sample / "cultures")
        resolved = {
            key: g.resolve_spelling(g._DEFAULT_SPELLING, culture.get("spelling", {}))
            for key, culture in cultures.items()
        }
        self.assertNotEqual(
            resolved["wertisand"].max_join_length,
            resolved["huttanmesh"].max_join_length)


class TestSamplesAreCopyAndGo(unittest.TestCase):
    """Copying a sample into a fresh campaign must immediately produce names.

    Runs the CLI as a SUBPROCESS against a TEMP workspace, deliberately.
    CULTURES and SPELLING bind at import, so an in-process test would never
    see the copied files. And copying into the real names/cultures/ would
    change the no-argument iteration order, breaking the campaign suite's
    golden constants while present."""

    # Samples whose README says the merge is NOT optional -- copy-and-go
    # without campaign-additions.toml does not hold for these. Every other
    # sample's advertised copy-and-go state is bare, even when it ships an
    # additions file: sample 6's own README is explicit that it is
    # "copy-and-go WITHOUT campaign-additions.toml", and that file exists
    # only to additionally demonstrate the middle spelling layer.
    REQUIRES_MERGE = {"7-official-language", "8-capstone"}

    # A fresh campaign's identity, built here rather than read from the live
    # workspace: everything the loader requires and nothing optional. No
    # official_culture -- a fresh campaign does not set one, which is also
    # merge_additions' precondition.
    CAMPAIGN_TOML = (
        "[campaign]\n"
        'name = "Probe"\n'
        'namespace = "probe"\n'
        "\n"
        "[names]\n"
        'cultures = "names/cultures"\n'
    )

    def _workspace(self, sample, merge=None):
        """A fresh campaign: a minimal campaign.toml with no
        official_culture, and names/cultures/ holding only this sample.

        `merge` controls whether campaign-additions.toml (if the sample
        ships one) is merged into campaign.toml. Default (None) exercises
        each sample in the state ITS OWN README advertises as copy-and-go:
        bare for every sample except those in REQUIRES_MERGE. Pass an
        explicit True/False to override -- e.g. to also exercise sample 6's
        optional additions file in a dedicated test."""
        if merge is None:
            merge = sample.name in self.REQUIRES_MERGE
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        text = self.CAMPAIGN_TOML
        additions = sample / "campaign-additions.toml"
        if merge and additions.is_file():
            text = merge_additions(text, additions.read_text(encoding="utf-8"))
        (tmp / "campaign.toml").write_text(text, encoding="utf-8")
        cultures = tmp / "names" / "cultures"
        cultures.mkdir(parents=True)
        for toml in (sample / "cultures").glob("*.toml"):
            shutil.copy(toml, cultures)
        return tmp

    def _run(self, tmp, *args):
        # The tool resolves its workspace from BUNNYFORGE_WORKSPACE, which
        # wins over the marker walk. (It once also won over an install-repo
        # fallback; Phase 2 Plan 5 deleted that, so there is nothing below
        # the walk now but a clean error.) Passed via env= only — mutating
        # os.environ would leak into every other test.
        env = {**os.environ, "BUNNYFORGE_WORKSPACE": str(tmp)}
        return subprocess.run(
            [sys.executable, "-m", "bunnyforge.generate_names", *args],
            capture_output=True, text=True, env=env)

    def test_every_sample_generates_after_being_copied_into_place(self):
        for sample in discovered():
            with self.subTest(sample=sample.name):
                tmp = self._workspace(sample)
                r = self._run(tmp, "--seed", "1", "-n", "2")
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertTrue(r.stdout.strip(), "no names produced")

    def test_every_sample_lists_its_cultures(self):
        # "Categories" alone has no discriminating power: it is the
        # --list branch's static column header, printed before any
        # per-culture row regardless of how many cultures loaded -- proven
        # by a workspace holding only 1 of sample 2's 3 culture files still
        # passing that assertion. Assert every culture the sample declares
        # appears BY NAME in the output, so a partial copy or a dropped
        # culture file actually fails this test.
        for sample in discovered():
            with self.subTest(sample=sample.name):
                tmp = self._workspace(sample)
                r = self._run(tmp, "--list")
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertIn("Categories", r.stdout)
                names = [c["name"] for c in
                         g.load_cultures(sample / "cultures").values()]
                self.assertTrue(names, "sample declares no cultures")
                for name in names:
                    with self.subTest(sample=sample.name, culture=name):
                        self.assertIn(name, r.stdout)

    def test_sample_6_bare_is_copy_and_go_and_shows_the_spelling_contrast(self):
        # Finding 1: sample 6's own README says it is copy-and-go WITHOUT
        # campaign-additions.toml, and the bare state is the ONLY state
        # where its lesson (wertisand reaches 12-char joins that
        # huttanmesh structurally cannot) is even visible -- merging
        # campaign-additions.toml's max_length = 8 suppresses every
        # two-syllable join for BOTH cultures, so a test that always merges
        # would pass even if wertisand's own [spelling] override went
        # completely inert. Proven: setting wertisand.toml's
        # max_join_length from 12 down to 9 (making the override inert)
        # left every existing test green before this one was added.
        sample = SAMPLES / "6-spelling"
        cultures = g.load_cultures(sample / "cultures")
        max_syllable = {
            key: max(len(s) for s in culture["given_personal"])
            for key, culture in cultures.items()
        }
        tmp = self._workspace(sample, merge=False)

        r = self._run(tmp, "wertisand", "-n", "20", "--seed", "7")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        wertisand_givens = [line.split()[-1] for line in r.stdout.splitlines()
                            if line.strip()]
        self.assertTrue(wertisand_givens, "no names produced")
        self.assertTrue(
            any(len(giv) > max_syllable["wertisand"] for giv in wertisand_givens),
            "wertisand never produced a compound given name longer than any "
            "single syllable in its pool -- its own [spelling] override may "
            "be inert")

        r = self._run(tmp, "huttanmesh", "-n", "20", "--seed", "7")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        huttanmesh_givens = [line.split()[-1] for line in r.stdout.splitlines()
                             if line.strip()]
        self.assertTrue(huttanmesh_givens, "no names produced")
        self.assertTrue(
            all(len(giv) <= max_syllable["huttanmesh"] for giv in huttanmesh_givens),
            "huttanmesh produced a compound given name -- it has no own "
            "[spelling], so it should be structurally unable to under the "
            "built-in floor")

    def test_sample_6_merged_additions_file_still_suppresses_both_cultures(self):
        # Sample 6's campaign-additions.toml is optional and so never
        # exercised by the copy-and-go tests above, which run bare. It
        # still ships and can rot, so exercise it here: merged in, its
        # max_length = 8 setting-wide layer should suppress every
        # two-syllable join for BOTH cultures, including wertisand, whose
        # own [spelling] sets only max_join_length and never max_length.
        #
        # This also happens to exercise generate_names.NAME_ATTEMPTS -- the
        # retries are what find a join clearing the tightened max_length
        # instead of exhausting and falling back. It was once the repo's
        # ONLY guard on that budget, which made it quietly load-bearing for
        # Plan 6's coupled/portable split (issue #62). It no longer is:
        # tests/test_retry_budgets.py now covers the budget directly, from
        # its own fixtures, and catches a cut to 1 without any help from
        # this file. Relocate or rewrite this test freely.
        sample = SAMPLES / "6-spelling"
        cultures = g.load_cultures(sample / "cultures")
        max_syllable = max(len(s) for s in
                            cultures["wertisand"]["given_personal"])
        tmp = self._workspace(sample, merge=True)

        r = self._run(tmp, "wertisand", "-n", "30", "--seed", "7")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        givens = [line.split()[-1] for line in r.stdout.splitlines()
                  if line.strip()]
        self.assertTrue(givens, "no names produced")
        self.assertTrue(
            all(len(giv) <= max_syllable for giv in givens),
            "wertisand produced a compound given name even with "
            "campaign-additions.toml's max_length = 8 merged in")
        # The design's own worked example: a family name 10 characters long
        # (Yakweshtar) should never survive pronounceable()'s max_length
        # check once the merge tightens it to 8.
        family_names = [line.split()[0] for line in r.stdout.splitlines()
                        if line.strip()]
        self.assertNotIn("Yakweshtar", family_names)

    def test_sample_4_categories_are_the_four_genders_and_gender_filter_works(self):
        sample = SAMPLES / "4-genders"
        culture = g.load_cultures(sample / "cultures")["shaqirreth"]
        self.assertEqual(
            culture["categories"], ["nexus", "steward", "wildheart", "shaper"])

        tmp = self._workspace(sample)
        r = self._run(tmp, "shaqirreth", "--gender", "nexus", "--syllables", "1",
                      "-n", "20", "--seed", "1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        pool = set(culture["given_nexus"])
        givens = [line.split()[-1].lower() for line in r.stdout.splitlines()
                  if line.strip()]
        self.assertTrue(givens, "no names produced")
        for giv in givens:
            with self.subTest(given=giv):
                self.assertIn(giv, pool)

    def test_sample_7_place_prints_official(self):
        sample = SAMPLES / "7-official-language"
        tmp = self._workspace(sample)  # merge required, per REQUIRES_MERGE
        r = self._run(tmp, "byblashar", "--place", "-n", "5", "--seed", "3")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("official:", r.stdout)
