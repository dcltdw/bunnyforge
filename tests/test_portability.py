"""The portability check, run in-process.

Until Phase 2 Plan 4 this ran as a subprocess, because the check installed
synthetic settings by swapping generate_names' module globals — an unrestored
swap would have corrupted the three golden constants for every test sorting
after this one. Settings are plain values passed as arguments now; there is
no module state to corrupt and nothing to isolate.

stdout is still captured here, but for suite hygiene, not for isolation:
check_portability's report is ~38 lines across the two seeds below, and
printing all of it on every green run drowned out the rest of the suite's
output. Capturing it and passing it as the assertion's `msg` reproduces the
one part of the retired subprocess's behaviour that still matters — silent
on green, full diagnostic attached on red.
"""

import contextlib
import io
import re
import unittest
from pathlib import Path

from tests import check_portability


def _run(*argv: str) -> tuple[int, str]:
    """Run the check with stdout captured.

    The report is ~38 lines. Captured rather than printed so a green suite
    stays quiet, and surfaced in the assertion message so a red one shows
    the full diagnostic — the contract the retired subprocess had.
    """
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = check_portability.main(list(argv))
    return code, buf.getvalue()


class TestPortabilityCheck(unittest.TestCase):

    def test_the_portability_check_passes(self):
        code, out = _run()
        self.assertEqual(code, 0, out)

    def test_an_explicit_seed_is_accepted(self):
        # A seed verified to pass during implementation. Do NOT pick one at
        # random here: the suite must be deterministic. Exploratory fuzzing
        # belongs at the command line, not in the suite.
        code, out = _run("--seed", "7")
        self.assertEqual(code, 0, out)


# ---------------------------------------------------------------------------
# The suite-wide portable boundary (stage 4).

TESTS_DIR = Path(__file__).resolve().parent

# Campaign test files: excluded from the walk by the naming convention the
# split established. The prefix is also what CI's isolation job deletes.
_CAMPAIGN_PREFIX = "test_campaign_"

# Portable files allowed the __file__-reaching idiom, each with its reason.
# The ban is a proxy for "builds every fixture itself" (see the per-file
# guard in test_campaign_names.py for the fuller argument); these files
# reach ONLY into trees that ship with the package, so the reach survives
# the cut.
_FILE_IDIOM_ALLOWED = {
    "test_cli.py": "reads pyproject.toml, which ships",
    "test_init.py": "drift guard reads in-repo canonicals until stage 8",
    "test_mcp_session.py": "loads scripts/mcp-session.py, its subject",
    "test_portability.py": "this guard locates its sibling files",
    "test_samples.py": "reads samples/, which ships",
    "test_workspace.py": "copies sample cultures from samples/, which ships",
}


def _portable_test_files():
    """Every test file that ships: test_*.py minus the campaign prefix."""
    return sorted(p for p in TESTS_DIR.glob("test_*.py")
                  if not p.name.startswith(_CAMPAIGN_PREFIX))


class TestPortableBoundary(unittest.TestCase):
    """The Plan 6 boundary, generalised from one file to the suite.

    This class SHIPS: after the cut it is what keeps the public suite
    public, when no human is comparing. It bans the structural markers only
    -- the campaign's name and the __file__ idiom. The full derived
    campaign vocabulary is enforced campaign-side (test_campaign_terms.py),
    where the term source lives; post-cut there is no inventory left to
    leak from, so nothing is lost by its absence here.
    """

    def test_the_walk_finds_the_suite(self):
        names = [p.name for p in _portable_test_files()]
        # A floor, so an empty or misdirected glob cannot pass vacuously.
        self.assertGreaterEqual(len(names), 15, names)
        for name in names:
            self.assertFalse(name.startswith(_CAMPAIGN_PREFIX), name)

    def test_no_portable_file_names_the_campaign(self):
        for path in _portable_test_files():
            if path.name == Path(__file__).name:
                continue  # this file spells the banned token in order to ban it
            with self.subTest(file=path.name):
                text = path.read_text(encoding="utf-8").lower()
                self.assertNotIn(
                    "anjeong", text,
                    f"{path.name} names the campaign; portable tests ship")

    def test_file_reach_is_allowlisted(self):
        pattern = re.compile(r"\b__file__\b")
        for path in _portable_test_files():
            if path.name in _FILE_IDIOM_ALLOWED:
                continue
            with self.subTest(file=path.name):
                self.assertIsNone(
                    pattern.search(path.read_text(encoding="utf-8")),
                    f"{path.name} reaches for __file__; a portable test "
                    f"builds every fixture itself, or earns an allowlist "
                    f"entry with a reason")

    def test_the_allowlist_is_live(self):
        # An allowlist entry for a deleted or renamed file is a hole that
        # would hide the next violation; every entry must name a real,
        # currently-portable file.
        for name in _FILE_IDIOM_ALLOWED:
            with self.subTest(file=name):
                self.assertTrue((TESTS_DIR / name).is_file(), name)
                self.assertFalse(name.startswith(_CAMPAIGN_PREFIX), name)


if __name__ == "__main__":
    unittest.main()
