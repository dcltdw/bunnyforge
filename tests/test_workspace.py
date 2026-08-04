"""Tests for bunnyforge._workspace — the first coverage this repo has had for
workspace derivation, which was a one-line constant until Phase 2.

Every in-process test drives discover()/resolve_root() with an explicit
`start`, so none depends on the process's actual working directory. The
subprocess tests at the bottom are the exception on purpose: cwd and env are
exactly what they exist to exercise, and they do it in a child so this
process's own state is never touched.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bunnyforge import _workspace

REPO = Path(__file__).resolve().parent.parent

# Set in the child of test_run_tests_outside_any_workspace, so that if that
# child ever succeeds in resolving a workspace it runs the suite exactly once
# instead of recursing forever. Never set in a normal run.
_NO_RECURSE = "BUNNYFORGE_TEST_NO_RECURSE"


def _campaign(root: Path) -> Path:
    """Mark `root` as a workspace and return it."""
    (root / _workspace.CONFIG_NAME).write_text(
        '[campaign]\nnamespace = "probe"\n', encoding="utf-8")
    return root


class TestDiscover(unittest.TestCase):

    def _tmp(self) -> Path:
        # resolve() so comparisons survive /var -> /private/var on macOS.
        return Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()

    def test_finds_the_marker_in_the_starting_directory(self):
        root = _campaign(self._tmp())
        self.assertEqual(_workspace.discover(root), root)

    def test_walks_up_from_a_nested_directory(self):
        root = _campaign(self._tmp())
        deep = root / "NPCs" / "minor" / "deeper"
        deep.mkdir(parents=True)
        self.assertEqual(_workspace.discover(deep), root)

    def test_returns_the_nearest_marker_not_the_outermost(self):
        # A campaign nested inside another must resolve to the inner one.
        # Without this, the walk could "work" by finding any marker at all.
        outer = _campaign(self._tmp())
        sub = outer / "sub"
        sub.mkdir()
        inner = _campaign(sub)
        self.assertEqual(_workspace.discover(inner / "NPCs"), inner)
        self.assertNotEqual(_workspace.discover(inner / "NPCs"), outer)

    def test_raises_when_no_marker_exists_anywhere_above(self):
        # A temp dir has no campaign.toml above it up to the filesystem root
        # (asserted, not assumed, so the test cannot pass vacuously).
        bare = self._tmp()
        for parent in [bare, *bare.parents]:
            self.assertFalse((parent / _workspace.CONFIG_NAME).exists(),
                             f"unexpected {_workspace.CONFIG_NAME} at {parent}")
        with self.assertRaises(_workspace.WorkspaceError) as ctx:
            _workspace.discover(bare)
        self.assertIn(_workspace.CONFIG_NAME, str(ctx.exception))

    def test_a_directory_named_campaign_toml_is_not_a_marker(self):
        root = self._tmp()
        (root / _workspace.CONFIG_NAME).mkdir()
        with self.assertRaises(_workspace.WorkspaceError):
            _workspace.discover(root)

    def test_discover_resolves_a_symlink_to_the_real_path(self):
        # Both .resolve() calls in _workspace.py went untested: a prior
        # review mutated each away and all 299 tests still passed, because
        # every path this suite fed discover() was already resolved. A
        # symlinked start is the one input where resolved and unresolved
        # actually differ, so it is the only input that can catch a removed
        # discover()-level .resolve() call.
        root = _campaign(self._tmp())
        link_dir = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        link = link_dir / "link-to-campaign"
        link.symlink_to(root)
        self.assertNotEqual(link, root)  # the input really is unresolved
        self.assertEqual(_workspace.discover(link), root)


class TestResolveRoot(unittest.TestCase):
    """The two-step order — env, then the walk — and the error that ends it.

    Each step is proven to WIN over the next, which is the only way to show
    the precedence is real rather than incidental. There is no third step any
    more: the install-repo fallback died with this plan, because a published
    package has no install repo and silently resolving to one was how a tool
    run in the wrong directory quietly edited the wrong campaign.
    """

    def _tmp(self) -> Path:
        return Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()

    def test_env_var_wins_over_the_walk(self):
        env_ws = _campaign(self._tmp())
        cwd_ws = _campaign(self._tmp())
        with mock.patch.dict(os.environ, {"BUNNYFORGE_WORKSPACE": str(env_ws)}):
            self.assertEqual(_workspace.resolve_root(cwd_ws), env_ws)

    def test_the_walk_wins_over_the_error(self):
        # The inverse of the deleted install-fallback test: with no env var,
        # a marked start still resolves to itself rather than raising.
        cwd_ws = _campaign(self._tmp())
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BUNNYFORGE_WORKSPACE", None)
            got = _workspace.resolve_root(cwd_ws)
        self.assertEqual(got, cwd_ws)

    def test_raises_outside_any_workspace(self):
        # Was test_falls_back_to_the_install_root_outside_any_workspace.
        # The temp dir really has no marker above it, asserted rather than
        # assumed so the test cannot pass for the wrong reason.
        #
        # The message must both LOCATE the failure (which directory was
        # searched) and say what to do about it. This is the ordinary
        # failure — a tool run in the wrong directory — and it is the one a
        # user actually meets, so it carries the same three remedies as the
        # deleted-cwd branch below. Asserting only the locating text would
        # not notice them going missing.
        bare = self._tmp()
        for parent in [bare, *bare.parents]:
            self.assertFalse((parent / _workspace.CONFIG_NAME).exists(),
                             f"unexpected {_workspace.CONFIG_NAME} at {parent}")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BUNNYFORGE_WORKSPACE", None)
            with self.assertRaises(_workspace.WorkspaceError) as ctx:
                _workspace.resolve_root(bare)
        message = str(ctx.exception)
        self.assertIn(_workspace.CONFIG_NAME, message)
        self.assertIn(str(bare), message)
        self.assertIn("no campaign.toml found in", message)
        # The card's two beginner remedies plus the flag bullet, and
        # somewhere to go. BUNNYFORGE_WORKSPACE is deliberately NOT here:
        # it is an operator convenience, and burying a beginner's two real
        # options under three is the failure the instructional-errors
        # ruling names. It stays documented in --help and the README.
        for remedy in ("cd into that folder",
                       'bunnyforge init my-campaign --name "My Campaign"',
                       "--workspace"):
            self.assertIn(remedy, message)
        self.assertIn(_workspace.DOCS_URL, message)
        # The "error: " prefix belongs to the callers' print, not to the
        # exception -- otherwise it doubles up.
        self.assertFalse(message.startswith("error:"), message)

    def test_the_card_variants_differ_only_by_the_flag_bullet(self):
        # The suggest_flag seam is the one thing that varies between
        # callers. Asserting the difference is exactly the flag bullet
        # stops the two paths drifting into two separately-worded cards.
        bare = self._tmp()
        messages = {}
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BUNNYFORGE_WORKSPACE", None)
            for suggest in (True, False):
                with self.assertRaises(_workspace.WorkspaceError) as ctx:
                    _workspace.resolve_root(bare, suggest_flag=suggest)
                messages[suggest] = str(ctx.exception)
        self.assertIn("--workspace", messages[True])
        self.assertNotIn("--workspace", messages[False])
        without_bullet = "\n".join(
            ln for ln in messages[True].splitlines()
            if "--workspace" not in ln)
        self.assertEqual(without_bullet, messages[False])

    def test_resolve_root_resolves_a_relative_env_var(self):
        # The other untested .resolve() call: Path(env).resolve() in
        # resolve_root(). A relative BUNNYFORGE_WORKSPACE is the one input
        # that can tell a resolved result apart from an unresolved one.
        root = _campaign(self._tmp())
        rel = os.path.relpath(root, Path.cwd())
        self.assertFalse(Path(rel).is_absolute())  # the input really is relative
        with mock.patch.dict(os.environ, {"BUNNYFORGE_WORKSPACE": rel}):
            got = _workspace.resolve_root()
        self.assertTrue(got.is_absolute())
        self.assertEqual(got, root)

    def test_a_deleted_cwd_is_a_clean_workspace_error_not_a_crash(self):
        """A deleted current working directory is process-global state — it
        cannot be simulated in-process without corrupting every other test
        in this suite, which all assume a live cwd. So this spawns a child
        that deletes its OWN cwd out from under itself (no race: the child
        captures the path while it still exists, then removes exactly that
        path, then imports bunnyforge._workspace fresh) and reports what
        resolve_root() did.

        Two failure modes are being excluded at once, and this is the only
        input that can tell them apart from correct behaviour: propagating
        the FileNotFoundError that Path.cwd() raises here (a crash, which is
        what narrowing resolve_root's except to WorkspaceError alone would
        produce), and the pre-Plan-5 behaviour of silently answering with
        the install repo (a wrong workspace, quietly). The right answer is
        WorkspaceError, whose message must name all three remedies so the
        user has somewhere to go.
        """
        script = (
            "import os\n"
            "here = os.getcwd()\n"
            "os.rmdir(here)\n"
            "import bunnyforge._workspace as w\n"
            "try:\n"
            "    print('RESOLVED', w.resolve_root())\n"
            "except w.WorkspaceError as exc:\n"
            "    print('WorkspaceError', exc)\n"
        )
        cwd = tempfile.mkdtemp()
        try:
            env = {k: v for k, v in os.environ.items()
                   if k != "BUNNYFORGE_WORKSPACE"}
            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=cwd, capture_output=True, text=True, env=env,
            )
        finally:
            shutil.rmtree(cwd, ignore_errors=True)  # child already removed it
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertTrue(result.stdout.startswith("WorkspaceError "),
                        f"expected a clean WorkspaceError, got {result.stdout!r}")
        self.assertIn("the current directory is unusable", result.stdout)
        for remedy in ("cd into that folder",
                       'bunnyforge init my-campaign --name "My Campaign"',
                       "--workspace", _workspace.DOCS_URL):
            self.assertIn(remedy, result.stdout)


def _bare_dir(case: unittest.TestCase) -> Path:
    """A temp directory with no campaign.toml at or above it."""
    d = Path(case.enterContext(tempfile.TemporaryDirectory())).resolve()
    for parent in [d, *d.parents]:
        case.assertFalse((parent / _workspace.CONFIG_NAME).exists(),
                         f"unexpected {_workspace.CONFIG_NAME} at {parent}")
    return d


def _scrubbed_env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "BUNNYFORGE_WORKSPACE"}
    env.update(extra)
    return env


class TestOutsideAnyWorkspaceIsACleanError(unittest.TestCase):
    """End-to-end, in a real child process: the thing a user actually sees.

    In-process tests of resolve_root prove the exception; only a subprocess
    proves the whole path from `python3 -m bunnyforge.<tool>` to one `error:`
    line on stderr and exit 1. Before this plan the same invocation resolved
    to the install repo and ran a full checkup against somebody else's
    campaign, exiting 0.
    """

    def _run_outside(self, *argv: str,
                     **env_extra: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-m", *argv],
                              cwd=_bare_dir(self), capture_output=True,
                              text=True, env=_scrubbed_env(**env_extra))

    def _assert_one_clean_error(self, result: subprocess.CompletedProcess,
                                *, has_flag: bool = True):
        both = result.stdout + result.stderr
        self.assertEqual(result.returncode, 1, both)
        self.assertNotIn("Traceback", both)
        errors = [ln for ln in both.splitlines() if ln.startswith("error:")]
        # Still exactly one `error:` line: the card is multi-line, but only
        # its first line carries the prefix the caller prints.
        self.assertEqual(len(errors), 1, both)
        self.assertIn("no campaign.toml found in", errors[0])
        # The remedies must survive the trip from resolve_root through
        # main()'s `print(f"error: {exc}")`. A message that only reaches the
        # exception is no help to the person who typed the command. They sit
        # on the card's later lines, so assert against the whole output.
        for remedy in ("cd into that folder",
                       'bunnyforge init my-campaign --name "My Campaign"',
                       _workspace.DOCS_URL):
            self.assertIn(remedy, both)
        # A tool may only advertise --workspace if it actually accepts it.
        # For a tool that does not, the advice is worse than silence: acting
        # on it produces argparse's `unrecognized arguments` and exit 2, so
        # the one message meant to give the user somewhere to go sends them
        # into a second error. Asserted both ways, because the failure that
        # matters here is a remedy that is present and should not be.
        if has_flag:
            self.assertIn("--workspace", both)
        else:
            self.assertNotIn("--workspace", both)

    def test_review_checkup_outside_any_workspace(self):
        self._assert_one_clean_error(
            self._run_outside("bunnyforge.review", "checkup"))

    # The next four tools reach this path only through the WorkspaceError
    # half of their `except (WorkspaceError, ConfigError)` tuple, and until
    # now nothing exercised it: their test_missing_workspace_* tests all pass
    # --workspace at a directory with no campaign.toml, which is ConfigError
    # from load(). Narrowing any of those four tuples to (ConfigError,) left
    # the whole suite green, so each tool would have printed a traceback
    # instead of one error: line and nobody would have noticed. Each of these
    # runs with NO flag, NO BUNNYFORGE_WORKSPACE and a cwd with no marker above
    # it, which is the only combination that raises WorkspaceError at all.
    # Every extra argument below is only there to get past argparse and the
    # pre-resolution guards; none of them can succeed.

    def test_build_sheets_outside_any_workspace(self):
        self._assert_one_clean_error(
            self._run_outside("bunnyforge.build_sheets", "--list-briefs"))

    def test_import_perceptions_outside_any_workspace(self):
        # --wiki-data is required by argparse; the directory it names is
        # never read, because resolution fails first.
        self._assert_one_clean_error(
            self._run_outside("bunnyforge.import_perceptions",
                              "--wiki-data", str(_bare_dir(self))))

    def test_export_player_outside_any_workspace(self):
        self._assert_one_clean_error(
            self._run_outside("bunnyforge.export_player"))

    def test_deploy_export_outside_any_workspace(self):
        # --staging is required and --render-only is checked before
        # resolution, so both must be present to reach the workspace error.
        self._assert_one_clean_error(
            self._run_outside("bunnyforge.deploy_export", "--render-only",
                              "--staging", str(_bare_dir(self))))

    def test_run_tests_outside_any_workspace(self):
        # run_tests takes no --workspace flag (you run a workspace's suite by
        # being in it), which makes it the tool most likely to be launched
        # from nowhere — and the one whose resolution is easiest to leave
        # bare, since it used to be a module-level constant assigned at
        # import. Without its try/except this prints a traceback; with the
        # pre-Plan-5 fallback it silently ran THIS repo's whole suite from a
        # temp directory and exited 0.
        #
        # That second failure mode is why the child is marked: a regression
        # to the fallback makes the child run this very test again, and
        # again, without a depth bound. Marked, the grandchild skips, the
        # child exits 0 with suite output, and the assertion below fails —
        # a failure rather than a fork bomb.
        if os.environ.get(_NO_RECURSE):
            self.skipTest("running inside this test's own child process")
        # has_flag=False: this is the one entry point without --workspace, so
        # its error must not name it. See _assert_one_clean_error.
        self._assert_one_clean_error(
            self._run_outside("bunnyforge.run_tests", **{_NO_RECURSE: "1"}),
            has_flag=False)

    def test_run_tests_really_does_reject_the_flag_it_no_longer_advertises(self):
        # The control for the assertion above: it is only worth withholding
        # the remedy because acting on it fails, and fails differently (exit
        # 2, argparse, no `error:` line). If run_tests ever grew the flag,
        # this test fails and the withheld remedy should be given back.
        result = self._run_outside("bunnyforge.run_tests", "--workspace", "/tmp",
                                   **{_NO_RECURSE: "1"})
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("unrecognized arguments: --workspace", result.stderr)


class TestTheFlagSteersARealRun(unittest.TestCase):
    """The spec's positive control.

    Every other --workspace test either runs in-process or runs somewhere
    that would resolve correctly anyway. These run a real child from a
    directory that is not a workspace, with BUNNYFORGE_WORKSPACE scrubbed, so
    the flag is the ONLY thing that can be pointing the tool at a campaign —
    and the campaign is a copied sample, not this repo, so a run that
    silently fell back to the install repo would produce different names or
    no culture at all rather than passing by accident.
    """

    def _campaign_from(self, sample: str) -> Path:
        d = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        (d / _workspace.CONFIG_NAME).write_text(
            '[campaign]\nnamespace = "probe"\n\n[names]\n'
            'cultures = "cultures"\n', encoding="utf-8")
        shutil.copytree(REPO / "samples" / sample / "cultures", d / "cultures")
        return d

    def _generate(self, *args: str, env_workspace: Path | None = None):
        extra = {} if env_workspace is None else {
            "BUNNYFORGE_WORKSPACE": str(env_workspace)}
        return subprocess.run(
            [sys.executable, "-m", "bunnyforge.generate_names", *args],
            cwd=_bare_dir(self), capture_output=True, text=True,
            env=_scrubbed_env(**extra))

    def test_the_flag_alone_drives_a_real_generation(self):
        ws = self._campaign_from("4-genders")
        result = self._generate("--workspace", str(ws), "shaqirreth",
                                "-n", "2", "--seed", "1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        names = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
        self.assertEqual(len(names), 2, result.stdout)
        self.assertTrue(all(names), result.stdout)

    def test_the_flag_beats_the_environment_variable(self):
        flag_ws = self._campaign_from("4-genders")      # has shaqirreth
        env_ws = self._campaign_from("1-one-people")    # has only vashkand
        # Control: the env workspace really does lack the culture, so the
        # test below cannot pass by accidentally reading the env workspace.
        control = self._generate("shaqirreth", "-n", "2", "--seed", "1",
                                 env_workspace=env_ws)
        self.assertEqual(control.returncode, 1,
                         control.stdout + control.stderr)
        self.assertIn("unknown culture", control.stdout + control.stderr)

        result = self._generate("--workspace", str(flag_ws), "shaqirreth",
                                "-n", "2", "--seed", "1",
                                env_workspace=env_ws)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        names = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
        self.assertEqual(len(names), 2, result.stdout)


if __name__ == "__main__":
    unittest.main()
