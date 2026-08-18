"""Tests for run_tests.py's workspace-leak guard.

A test that writes into the real campaign workspace corrupts it silently.
This has happened twice (issue #61): once leaving fixture files in
`Perceptions/` and `_Export/Mechanics/`, which pushed the export gate's
staged tree from 10 files to 16 and changed its checksum, and once during
mutation testing. Neither was caught by a test, a review, or CI -- both
were caught only by someone recomputing a number they had been told was
correct.

`_Export/`, `_Reviews/`, `_Sheets/` and `_Ignore/` are all git-ignored, so
`git status` stays clean after a leak into any of them. That is why this
guard walks the filesystem rather than asking git.
"""

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bunnyforge import run_tests as rt


def _tmp(case):
    return Path(case.enterContext(tempfile.TemporaryDirectory())).resolve()


class TestSnapshotScope(unittest.TestCase):
    """What the snapshot must ignore, and what it must NOT ignore.

    The second half is the one that matters: the bug this guard exists to
    catch landed in git-ignored directories, so a snapshot that skipped
    them would reproduce the original silence exactly.
    """

    def test_build_noise_is_ignored(self):
        root = _tmp(self)
        (root / "real.md").write_text("content", encoding="utf-8")
        base = rt._snapshot(root)

        for rel in ("__pycache__/mod.cpython-313.pyc", "bunnyforge.egg-info/PKG-INFO",
                    ".superpowers/sdd/ledger.md", ".claude/settings.json",
                    ".git/objects/ab/cdef", "stray.pyc", ".DS_Store"):
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("noise", encoding="utf-8")

        self.assertEqual(rt._snapshot(root), base,
                         "build/tooling noise must not register as a change")

    def test_git_ignored_content_directories_are_NOT_ignored(self):
        # The regression guard for issue #61 itself. _Export/ and _Reviews/
        # are in .gitignore; a leak into either is invisible to `git status`.
        root = _tmp(self)
        base = rt._snapshot(root)
        for rel in ("_Export/Mechanics/leaked.md", "_Reviews/checkup.html",
                    "_Ignore/scratch.md"):
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("leaked", encoding="utf-8")

        after = rt._snapshot(root)
        self.assertNotEqual(after, base)
        for rel in ("_Export/Mechanics/leaked.md", "_Reviews/checkup.html",
                    "_Ignore/scratch.md"):
            self.assertIn(rel, after)


class TestChangeDetection(unittest.TestCase):

    def test_added_removed_and_modified_are_each_reported(self):
        before = {"keep.md": "h1", "gone.md": "h2", "edit.md": "h3"}
        after = {"keep.md": "h1", "edit.md": "CHANGED", "new.md": "h4"}
        changes = rt._describe_changes(before, after)
        joined = "\n".join(changes)
        self.assertIn("new.md", joined)
        self.assertIn("gone.md", joined)
        self.assertIn("edit.md", joined)
        self.assertNotIn("keep.md", joined)

    def test_no_changes_reports_nothing(self):
        snap = {"a.md": "h1"}
        self.assertEqual(rt._describe_changes(snap, snap), [])

    def test_an_edit_that_preserves_size_is_still_caught(self):
        # Discrimination: proves the snapshot hashes content rather than
        # recording (size, mtime). A same-length overwrite is exactly what a
        # regenerated file looks like.
        root = _tmp(self)
        f = root / "same-size.md"
        f.write_text("aaaa", encoding="utf-8")
        before = rt._snapshot(root)
        f.write_text("bbbb", encoding="utf-8")
        self.assertNotEqual(rt._snapshot(root), before)


class TestTheGuardFiresEndToEnd(unittest.TestCase):
    """A real child process running a real (tiny) suite.

    In-process tests of the helpers prove the mechanism; only a subprocess
    proves that a passing suite which leaks still fails the run.
    """

    def _workspace_running(self, body: str) -> Path:
        ws = _tmp(self)
        (ws / "campaign.toml").write_text("", encoding="utf-8")
        tests = ws / "tests"
        tests.mkdir()
        (tests / "__init__.py").write_text("", encoding="utf-8")
        (tests / "test_fake.py").write_text(
            "import unittest\n"
            "from pathlib import Path\n"
            # ws is injected directly rather than having the generated
            # fixture rediscover its own location via the dunder
            # module-path attribute: this source is self-contained, and a
            # portable test file must not spell that self-location idiom
            # even inside generated text -- the shipped boundary guard
            # matches on raw text, comments included. ws is already
            # resolved (see _tmp), so this carries the same value the old
            # rediscover-then-resolve-parents approach did.
            f"ROOT = Path({str(ws)!r})\n"
            "class T(unittest.TestCase):\n"
            "    def test_it(self):\n"
            f"{body}\n"
            "        self.assertTrue(True)\n",
            encoding="utf-8")
        return ws

    def _run(self, ws: Path):
        env = {k: v for k, v in os.environ.items() if k != "BUNNYFORGE_WORKSPACE"}
        env["BUNNYFORGE_WORKSPACE"] = str(ws)
        return subprocess.run(
            [sys.executable, "-m", "bunnyforge.run_tests"],
            cwd=str(_tmp(self)), capture_output=True, text=True, env=env)

    def test_a_clean_suite_still_passes(self):
        # Anti-vacuous control. Without this, the two leak tests below could
        # pass because run_tests fails on this fixture for some unrelated
        # reason, proving nothing about the guard.
        r = self._run(self._workspace_running("        pass"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_a_passing_test_that_writes_into_the_workspace_fails_the_run(self):
        ws = self._workspace_running(
            '        (ROOT / "leaked.md").write_text("x", encoding="utf-8")')
        r = self._run(ws)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("leaked.md", r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stdout + r.stderr)

    def test_a_write_into_a_git_ignored_directory_is_caught(self):
        # Incident 2's exact shape: the leak landed in _Export/, where
        # `git status` would never have shown it.
        ws = self._workspace_running(
            '        p = ROOT / "_Export" / "Mechanics" / "leaked.md"\n'
            '        p.parent.mkdir(parents=True, exist_ok=True)\n'
            '        p.write_text("x", encoding="utf-8")')
        r = self._run(ws)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("leaked.md", r.stdout + r.stderr)


class TestMainAcceptsArgv(unittest.TestCase):
    """main(argv) parses the list it is given, not sys.argv.

    Stage 3's dispatcher calls run_tests.main(rest) the way it calls every
    other tool's main. The bogus flag proves the explicit list reaches the
    parser: argparse rejects it before any workspace is resolved or any
    suite is run. BUNNYFORGE_WORKSPACE still points at a throwaway
    workspace as a firebreak -- an implementation that ignored its argv
    would otherwise discover THIS repo's tests and run the real suite
    recursively from inside itself.
    """

    def test_explicit_argv_reaches_the_parser(self):
        ws = _tmp(self)
        (ws / "campaign.toml").write_text("", encoding="utf-8")
        (ws / "tests").mkdir()
        with mock.patch.dict(os.environ, {"BUNNYFORGE_WORKSPACE": str(ws)}):
            with contextlib.redirect_stderr(io.StringIO()) as err:
                with self.assertRaises(SystemExit) as cm:
                    rt.main(["--no-such-flag"])
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("--no-such-flag", err.getvalue())


class TestNoTestsIsGuidanceNotACrash(unittest.TestCase):
    """A workspace with nothing to run must teach, never traceback.

    Before this, a freshly-init'd workspace -- which has no tests/ at all --
    met unittest discovery's raw ImportError. That is the exact failure the
    2026-08-03 instructional-errors ruling names: a beginner shown a stack
    trace instead of a next step.

    Having no tests is a STATE, not a fault, so the first two cases exit 0.
    An unimportable tests/ is different: it may hold real tests nobody can
    see, so it exits 1 -- with the fix spelled out.
    """

    def _workspace(self, tests: dict[str, str] | None) -> Path:
        """A minimal workspace. tests=None means no tests/ directory."""
        ws = _tmp(self)
        (ws / "campaign.toml").write_text("", encoding="utf-8")
        if tests is not None:
            (ws / "tests").mkdir()
            for name, body in tests.items():
                (ws / "tests" / name).write_text(body, encoding="utf-8")
        return ws

    def _run(self, ws: Path):
        """A child process, like TestTheGuardFiresEndToEnd's.

        In-process would be simpler but wrong here: this repo's own `tests`
        package is already in sys.modules, so discovering a fixture
        workspace's `tests` package in-process collides with it and every
        case reports an import error. A child also exercises the real
        invocation path, which is the one users meet.
        """
        env = {k: v for k, v in os.environ.items()
               if k != "BUNNYFORGE_WORKSPACE"}
        env["BUNNYFORGE_WORKSPACE"] = str(ws)
        r = subprocess.run([sys.executable, "-m", "bunnyforge.run_tests"],
                           cwd=str(_tmp(self)), capture_output=True,
                           text=True, env=env)
        return r.returncode, r.stdout, r.stderr

    def test_no_tests_directory_guides_by_url_and_exits_zero(self):
        code, out, err = self._run(self._workspace(None))
        self.assertEqual(code, 0, out + err)
        self.assertIn("No campaign tests yet", out)
        self.assertIn(rt._workspace.DOCS_URL, out)
        self.assertNotIn("Traceback", out + err)
        # Never point at files the user does not have.
        self.assertNotIn("tests/README.md", out)
        self.assertNotIn("tests/test_example.py", out)

    def test_a_scaffolded_but_empty_tests_dir_points_at_its_files(self):
        ws = self._workspace({
            "__init__.py": "",
            "README.md": "# Campaign tests\n",
            "test_example.py": "# every line commented out\n",
        })
        code, out, err = self._run(ws)
        self.assertEqual(code, 0, out + err)
        self.assertIn("No campaign tests yet", out)
        self.assertIn("tests/README.md", out)
        self.assertIn("tests/test_example.py", out)
        self.assertNotIn("Traceback", out + err)

    def test_an_unimportable_tests_dir_names_the_fix(self):
        # tests/ with a real test file but no __init__.py: what unittest
        # discovery cannot import, and what used to raise.
        ws = self._workspace({
            "test_real.py": "import unittest\n"
                            "class T(unittest.TestCase):\n"
                            "    def test_it(self):\n"
                            "        self.assertTrue(True)\n",
        })
        code, out, err = self._run(ws)
        self.assertEqual(code, 1, out + err)
        self.assertIn("__init__.py", err)
        self.assertNotIn("Traceback", out + err)

    def test_a_workspace_with_real_tests_still_runs_them(self):
        # Anti-vacuous control: the classification must not swallow a
        # workspace that DOES have tests.
        ws = self._workspace({
            "__init__.py": "",
            "test_real.py": "import unittest\n"
                            "class T(unittest.TestCase):\n"
                            "    def test_it(self):\n"
                            "        self.assertTrue(True)\n",
        })
        code, out, err = self._run(ws)
        self.assertEqual(code, 0, out + err)
        self.assertIn("Ran 1 test", err)   # unittest reports to stderr
        self.assertNotIn("No campaign tests yet", out)


if __name__ == "__main__":
    unittest.main()
