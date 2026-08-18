"""Tests for bunnyforge.init — scaffolding a new campaign workspace.

The headline test is init-then-checkup (TestFreshWorkspacePassesTheGate):
scaffold into a temp directory and assert `review checkup` reports 0 errors
and 0 warnings with no manual fixes. setup_campaign.py never had that test,
and it is the one that would have caught issue #29.

Every test writes only into a temporary directory: run_tests snapshots the
workspace either side of the suite and fails the run on any difference.
"""

import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from importlib import resources
from unittest import mock
from pathlib import Path

from bunnyforge import _config, init, review
from bunnyforge._workspace import CONFIG_NAME

REPO = Path(__file__).resolve().parent.parent


def _root_doc_only_workspace(case: unittest.TestCase) -> Path:
    """A workspace holding the 8 default root docs and nothing else.

    The shape a fresh `init` produces before any entity file exists, and so
    the shape every wikilink in the packaged doctrine has to resolve against.
    The packaged AGENTS.md is written in — the copy `init` actually ships;
    the other seven root docs are one-line stubs, because all this needs of
    them is that they be link targets.
    """
    tmp = Path(case.enterContext(tempfile.TemporaryDirectory())).resolve()
    (tmp / CONFIG_NAME).write_text(
        '[campaign]\nnamespace = "probe"\n', encoding="utf-8")
    (tmp / "AGENTS.md").write_bytes(init.packaged_bytes("doctrine/AGENTS.md"))
    for doc in _config._DEFAULTS["root_docs"]:
        dest = tmp / doc
        if not dest.exists():
            dest.write_text(f"# {dest.stem}\n", encoding="utf-8")
    return tmp


class TestPackagedDoctrineIsPortable(unittest.TestCase):
    """AGENTS.md ships verbatim into every new workspace, so every wikilink in
    it must resolve in a workspace that has only root docs — no entity files
    at all.

    Measured, not assumed. Before this test AGENTS.md carried two example
    links to the private campaign's own Mechanics files, and a workspace
    built from it reported `0 error(s), 2 warning(s)` — failing the 0/0 gate
    this whole phase exists to pass, while the campaign-name grep stayed
    clean, because neither link spells the campaign's name. A campaign-term
    grep cannot catch this class of coupling; only running the check can.

    An example link is portable if it names a root doc, names a content
    directory (review.py treats a bare directory name as a pass-through
    target), or is not a wikilink at all.
    """

    def test_agents_md_wikilinks_resolve_with_only_root_docs(self):
        ws = _config.open_workspace(_root_doc_only_workspace(self))
        broken = [f.message for f in review.run_suite("checkup", ws)
                  if f.check == "wikilinks"]
        self.assertEqual(
            broken, [],
            "AGENTS.md links to something a fresh workspace does not have, "
            "so `init` cannot ship it verbatim and still pass the gate")


def _packaged_data_root() -> Path:
    """The data/ tree as a real directory.

    Filesystem-backed by construction here: the suite runs against the source
    tree or an editable install, never out of a zipimport. init itself uses
    the Traversable API and so has no such assumption.
    """
    return Path(str(resources.files("bunnyforge").joinpath("data")))


class TestPackagedDataMatchesItsCanonical(unittest.TestCase):
    """The drift guard.

    setup_campaign.py died because it embedded copies of doctrine that drifted
    silently from the real files. data/ is copies again; the difference is
    that drift is now a red test.

    Checked in BOTH directions, because either alone can pass vacuously: every
    manifest entry must name a real packaged file (a typo would otherwise
    raise FileNotFoundError instead of reporting drift), and every packaged
    file must be named by the manifest (a file added to data/ and forgotten
    is one init never writes and no test ever checks).

    PRESENT-CANONICAL SEMANTICS. The canonicals are campaign-side files
    (AGENTS.md, _Templates/, the directory READMEs) that do not travel to
    the public repository — the cut severs the filesystem relationship and
    flips the canonical direction, so data/ becomes the source of truth
    (see the phase 4 spec, "The drift guard splits in three"). Rather than
    fork this file, each canonical is guarded IF PRESENT: in this repo all
    of them are, so coverage is unchanged; in the public repo only the
    shipped sample pairing is, and the rest are legitimately absent. What
    carries the load there instead is init fidelity, below — what init
    writes IS data/, byte for byte — which needs no canonical at all.
    """

    def _canonical_entries(self):
        return [e for e in init.MANIFEST if e.canonical is not None]

    def test_every_present_canonical_is_byte_identical(self):
        checked = 0
        for entry in self._canonical_entries():
            live = REPO / entry.canonical
            if not live.exists():
                continue  # campaign-side canonical, absent post-cut
            checked += 1
            with self.subTest(resource=entry.resource):
                self.assertEqual(
                    init.packaged_bytes(entry.resource),
                    live.read_bytes(),
                    f"data/{entry.resource} has drifted from "
                    f"{entry.canonical} — re-copy it; never edit the copy")
        # Never zero: even in the public repo the sample pairing is present,
        # so a manifest that lost its verbatim entries cannot pass by
        # checking nothing at all.
        self.assertGreater(checked, 0,
                           "no canonical present anywhere — even the shipped "
                           "sample pairing is missing")

    def test_the_shipped_sample_pairing_is_always_present(self):
        # The one canonical that ships with the package rather than staying
        # with the campaign, so its absence is a defect in ANY repo. Without
        # this, the present-if-present rule above could go vacuous in the
        # public repo and nobody would notice.
        shipped = [e for e in self._canonical_entries()
                   if e.canonical.startswith("samples/")]
        self.assertEqual(len(shipped), 1, shipped)
        self.assertTrue((REPO / shipped[0].canonical).is_file(),
                        shipped[0].canonical)

    def test_init_output_is_byte_identical_to_its_data_sources(self):
        # Init fidelity: the guard that carries the load once the campaign
        # canonicals are gone. Every non-render entry must arrive in a fresh
        # workspace exactly as it sits in data/ -- which catches a writer
        # that transforms, truncates, or re-encodes on the way through.
        target = _scaffold(self)
        checked = 0
        for entry in init.MANIFEST:
            if entry.render:
                continue
            checked += 1
            with self.subTest(dest=entry.dest):
                self.assertEqual(
                    (target / entry.dest).read_bytes(),
                    init.packaged_bytes(entry.resource),
                    f"init wrote {entry.dest} differently from "
                    f"data/{entry.resource}")
        self.assertGreater(checked, 0)

    def test_every_manifest_resource_is_a_real_packaged_file(self):
        for entry in init.MANIFEST:
            with self.subTest(resource=entry.resource):
                self.assertTrue(
                    resources.files("bunnyforge")
                    .joinpath("data", entry.resource).is_file(),
                    f"MANIFEST names data/{entry.resource}, which is not "
                    f"packaged")

    def test_every_packaged_file_is_named_by_the_manifest(self):
        # Two exclusions, neither tolerated by accident. Both are artefacts
        # that appear in the tree for reasons having nothing to do with drift,
        # which is the only thing this test is meant to catch.
        #
        # .DS_Store: the repo lives in a Dropbox tree on macOS, so the Finder
        # drops one into any directory that gets browsed.
        #
        # __pycache__: data/tests/ ships sample test files, and running them --
        # which is exactly what `bunnyforge run-tests` does in a real workspace
        # -- leaves .pyc beside them, inside the INSTALLED package. That makes
        # it a slow trap rather than a visible break: the failure surfaces some
        # time after the run that caused it, names MANIFEST drift, and the
        # obvious first move (clearing __pycache__ from the repo) changes
        # nothing, because the caches are in site-packages. It also cannot fail
        # in CI, which installs fresh -- so it only ever fires on a working
        # machine, where a green suite matters most.
        packaged = {p.relative_to(_packaged_data_root()).as_posix()
                    for p in _packaged_data_root().rglob("*")
                    if p.is_file() and p.name != ".DS_Store"
                    and "__pycache__" not in p.parts}
        self.assertEqual(packaged, {e.resource for e in init.MANIFEST})

    def test_the_exclusions_do_not_blind_the_drift_check(self):
        """Both halves of the filter, against a stand-in data root.

        The risk an exclusion carries is that it grows broad enough to hide a
        real packaged file MANIFEST forgot -- at which point the check above
        passes for the wrong reason and nothing says so. So: a tree mirroring
        MANIFEST exactly must pass *with* both artefacts present, and must
        fail the moment a genuine file appears.

        Built in a temp directory rather than by writing into the installed
        package: site-packages is shared, and may not even be writable.
        """
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        for resource in {e.resource for e in init.MANIFEST}:
            dest = tmp / resource
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"stand-in\n")
        # Exactly the two artefacts the exclusions exist for.
        (tmp / ".DS_Store").write_bytes(b"")
        cache = tmp / "tests" / "__pycache__"
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "example.cpython-313.pyc").write_bytes(b"")

        with mock.patch(f"{__name__}._packaged_data_root", return_value=tmp):
            # Positive control: the artefacts alone must not fail the check,
            # or this test would pass even with the filters removed.
            self.test_every_packaged_file_is_named_by_the_manifest()

            (tmp / "unmanifested-sample.md").write_text("x", encoding="utf-8")
            with self.assertRaises(AssertionError):
                self.test_every_packaged_file_is_named_by_the_manifest()

    def test_manifest_destinations_are_unique(self):
        # Two entries share a resource (each skeleton lands twice), which is
        # intended; two sharing a DESTINATION would mean one silently
        # overwrites the other.
        dests = [e.dest for e in init.MANIFEST]
        self.assertEqual(sorted(dests), sorted(set(dests)))

    def test_the_readme_inventory_matches_the_manifest(self):
        # The package README states what init writes as a count, and prose
        # about the packaged files is embedded doctrine in miniature -- the
        # exact thing this module's docstring says the manifest exists to
        # stop drifting silently. It drifted twice before anyone noticed:
        # it claimed all 16 _Templates/ files when init had written 12 since
        # the skeletons stopped landing there, and it named neither the
        # tests/ nor the .vscode/ scaffold. Discipline has now failed on this
        # one sentence twice, which is the argument for a test rather than
        # for trying harder (issue #37).
        #
        # The TOTAL only, deliberately: the per-group figures are woven
        # through a prose sentence, so pinning each would tax every rewording
        # while adding nothing -- the total is what a forgotten MANIFEST
        # entry moves.
        #
        # Asserted unconditionally rather than if-present like the canonicals
        # above: those are campaign-side files that do not survive the public
        # cut, whereas this README ships in every repo, so its absence is a
        # defect anywhere rather than an artefact of the cut.
        readme = REPO / "src" / "bunnyforge" / "README.md"
        stated = re.search(r"What it writes — (\d+) files",
                           readme.read_text(encoding="utf-8"))
        self.assertIsNotNone(
            stated,
            "src/bunnyforge/README.md's inventory sentence has been reworded "
            "past the pattern this test reads -- restate the count or update "
            "the pattern, because an unmatched regex would pass vacuously "
            "and silently retire the guard")
        self.assertEqual(
            int(stated.group(1)), len(init.MANIFEST),
            f"src/bunnyforge/README.md says init writes {stated.group(1)} "
            f"files; MANIFEST has {len(init.MANIFEST)} entries")


class TestSlugify(unittest.TestCase):

    def test_lowercases_and_strips_non_alphanumerics(self):
        self.assertEqual(init.slugify("My Campaign"), "mycampaign")
        self.assertEqual(init.slugify("Ash & Ember: Book I"), "ashemberbooki")

    def test_a_name_with_no_alphanumerics_has_no_slug(self):
        self.assertEqual(init.slugify("!!! ???"), "")


class TestRefusals(unittest.TestCase):
    """One `error:` line on stderr and exit 1, never a traceback — the house
    pattern Phase 2 established. PATH must not exist, or be an empty
    directory: no overwrite semantics and no --force, because init writes a
    whole workspace and the cost of getting that wrong is somebody's campaign.
    """

    def _tmp(self) -> Path:
        return Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()

    def _refused(self, *argv: str) -> str:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = init.main(list(argv))
        self.assertEqual(code, 1, stderr.getvalue())
        lines = stderr.getvalue().splitlines()
        self.assertEqual(len(lines), 1, stderr.getvalue())
        self.assertTrue(lines[0].startswith("error: "), lines[0])
        self.assertNotIn("Traceback", stderr.getvalue())
        return lines[0]

    def test_refuses_a_path_that_is_a_file(self):
        target = self._tmp() / "afile"
        target.write_text("", encoding="utf-8")
        self.assertIn("is not a directory",
                      self._refused(str(target), "--name", "X"))

    def test_refuses_a_non_empty_directory(self):
        target = self._tmp()
        (target / "junk").write_text("", encoding="utf-8")
        self.assertIn("is not empty", self._refused(str(target), "--name", "X"))

    def test_refuses_a_directory_that_is_already_a_workspace(self):
        # More specific than "not empty", and the one that actually matters:
        # this is somebody's campaign, so it gets its own message.
        target = self._tmp()
        (target / CONFIG_NAME).write_text(
            '[campaign]\nnamespace = "probe"\n', encoding="utf-8")
        message = self._refused(str(target), "--name", "X")
        self.assertIn(CONFIG_NAME, message)
        self.assertIn("already a campaign workspace", message)

    def test_refuses_a_name_that_slugs_to_nothing(self):
        message = self._refused(str(self._tmp() / "new"), "--name", "!!!")
        self.assertIn("--name", message)
        self.assertIn("pass --namespace explicitly", message)

    def test_refuses_an_explicit_namespace_that_slugs_to_nothing(self):
        # An explicit --namespace is slugged too, so it cannot smuggle in a
        # character the default path would have stripped.
        message = self._refused(str(self._tmp() / "new"), "--name", "Fine",
                                "--namespace", "###")
        self.assertIn("--namespace", message)

    def test_refuses_a_missing_name_through_argparse(self):
        # argparse's own exit 2, not init's exit 1: a usage error is not a
        # runtime error and the two must not be conflated.
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                init.main([str(self._tmp() / "new")])
        self.assertEqual(ctx.exception.code, 2)

    def test_a_refusal_writes_nothing_at_all(self):
        # A refusal that had already written half a workspace would leave a
        # directory that looks initialised and is not.
        target = self._tmp() / "new"
        self._refused(str(target), "--name", "!!!")
        self.assertFalse(target.exists())


def _scaffold(case: unittest.TestCase, *extra: str,
              name: str = "My Campaign") -> Path:
    """init into a fresh temp directory, in-process. Returns the workspace."""
    tmp = Path(case.enterContext(tempfile.TemporaryDirectory())).resolve()
    target = tmp / "new-campaign"
    with contextlib.redirect_stdout(io.StringIO()):
        case.assertEqual(init.main([str(target), "--name", name, *extra]), 0)
    return target


class TestWhatInitWrites(unittest.TestCase):

    def test_writes_every_manifest_destination_and_nothing_else(self):
        target = _scaffold(self)
        written = {p.relative_to(target).as_posix()
                   for p in target.rglob("*") if p.is_file()}
        self.assertEqual(written, {e.dest for e in init.MANIFEST})

    def test_the_two_skeletons_land_under_their_canonical_names(self):
        # The .skeleton suffix exists only inside data/ and this repo's own
        # _Templates/. A root doc named style-guide.skeleton.md is not in
        # root_docs and would never be read, so the packaged bytes land at
        # the plain name instead -- and, since the prompts now survive being
        # filled in, they land there ONLY. A second pristine copy under
        # _Templates/ would just be a file whose purpose a user cannot tell.
        target = _scaffold(self)
        for name in ("style-guide.md", "situation-design.md"):
            with self.subTest(name=name):
                resource = f"templates/{name.replace('.md', '.skeleton.md')}"
                self.assertTrue((target / name).is_file())
                self.assertEqual((target / name).read_bytes(),
                                 init.packaged_bytes(resource))
                self.assertFalse(
                    (target / "_Templates" / Path(resource).name).exists(),
                    "the skeleton copy under _Templates/ should no longer be "
                    "written into a workspace")

    def test_scaffolds_a_tests_directory(self):
        # The doctrine-skeleton pattern applied to tests: a folder that
        # explains what belongs in it. __init__.py is load-bearing -- without
        # it unittest discovery cannot import the directory at all, which is
        # the ImportError run_tests used to surface as a stack trace.
        target = _scaffold(self)
        self.assertTrue((target / "tests" / "__init__.py").is_file())
        self.assertEqual((target / "tests" / "__init__.py").read_bytes(), b"")
        self.assertTrue((target / "tests" / "README.md").is_file())
        self.assertTrue((target / "tests" / "test_example.py").is_file())

    def test_the_example_test_ships_fully_commented_out(self):
        # It must be inert on arrival: a scaffolded workspace reports "no
        # campaign tests yet", and enabling the example is the user's
        # deliberate act. One uncommented line would also make `bunnyforge
        # test` run it before anyone has read it.
        body = (_scaffold(self) / "tests" / "test_example.py").read_text(
            encoding="utf-8")
        for n, line in enumerate(body.splitlines(), 1):
            if line.strip():
                self.assertTrue(line.lstrip().startswith("#"),
                                f"line {n} is live code: {line!r}")

    def test_gitignore_covers_wiki_token_and_drift(self):
        # The wiki credential and the tool-owned drift copies must never be
        # committed. The ignores must be two specific entries, never a
        # whole-directory ignore that would silently swallow the deploy
        # manifest too.
        target = _scaffold(self)
        text = (target / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".bunnyforge/wiki-token", text)
        self.assertIn(".bunnyforge/wiki-drift/", text)
        self.assertNotIn(".bunnyforge/\n", text)

    def test_a_scaffolded_workspace_reports_no_tests_rather_than_crashing(self):
        # The whole feature, end to end: init a workspace, then run the very
        # command a new user runs first. Before the scaffold this printed an
        # ImportError traceback. A child process because this repo's own
        # `tests` package is already imported here, and in-process discovery
        # of the fixture's `tests` would collide with it.
        target = _scaffold(self)
        env = {k: v for k, v in os.environ.items()
               if k != "BUNNYFORGE_WORKSPACE"}
        env["BUNNYFORGE_WORKSPACE"] = str(target)
        result = subprocess.run(
            [sys.executable, "-m", "bunnyforge.run_tests"],
            cwd=str(target), capture_output=True, text=True, env=env)
        both = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, both)
        self.assertNotIn("Traceback", both)
        self.assertIn("No campaign tests yet", result.stdout)
        # The scaffolded variant: it must point at the files init just wrote.
        for pointer in ("tests/README.md", "tests/test_example.py"):
            self.assertIn(pointer, result.stdout)
            self.assertTrue((target / pointer).is_file())

    def test_points_at_the_vscode_command_once(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(
                init.main([str(tmp / "new"), "--name", "X"]), 0)
        pointing = [l for l in out.getvalue().splitlines()
                    if "bunnyforge vscode" in l]
        self.assertEqual(len(pointing), 1, out.getvalue())

    def test_does_not_write_reanchor_txt(self):
        # Measured at plan time: AGENTS.md's read order never mentions it, and
        # the checkup gate passes without it. It is campaign state, not a root
        # doc, so init leaves it to the author.
        self.assertFalse((_scaffold(self) / "reanchor.txt").exists())

    def test_writes_the_campaign_doctrine_stub(self):
        # The GM-owned half of the doctrine split (#32). It lands like the
        # other root stubs -- authored, canonical=None -- because no packaged
        # version of it may ever overwrite what a campaign writes there. That
        # is the whole point: AGENTS.md becomes replaceable only once there is
        # somewhere else for campaign-specific rules to live.
        stub = _scaffold(self) / "campaign-doctrine.md"
        self.assertTrue(stub.is_file())
        self.assertEqual(stub.read_bytes(),
                         init.packaged_bytes("root/campaign-doctrine.md"))


class TestGeneratedConfig(unittest.TestCase):
    """The generated campaign.toml round-trips through _config.load, and every
    defaultable key really is only a comment — proving the file teaches what
    is overridable without being a second copy of _DEFAULTS that can drift.
    """

    def _config_of(self, *extra: str, name: str = "My Campaign"):
        return _config.load(_scaffold(self, *extra, name=name))

    def test_every_defaultable_key_equals_its_default(self):
        cfg = self._config_of()
        for key in ("entity_dirs", "inherit_dirs", "compendium_dirs",
                    "root_docs"):
            with self.subTest(key=key):
                self.assertEqual(getattr(cfg, key),
                                 tuple(_config._DEFAULTS[key]))
        for key in ("briefs_dir", "sheets_dir", "perceptions_dir",
                    "type_dirs"):
            with self.subTest(key=key):
                self.assertEqual(getattr(cfg, key), _config._DEFAULTS[key])
        self.assertEqual(
            cfg.exclude_dirs,
            frozenset(_config._DEFAULTS["exclude_dirs"])
            | _config.MANDATORY_EXCLUDES
            | {_config._DEFAULTS["inbound_dir"], _config._DEFAULTS["drafts_dir"]})

    def test_name_and_namespace_carry_the_substituted_values(self):
        cfg = self._config_of()
        self.assertEqual(cfg.name, "My Campaign")
        self.assertEqual(cfg.namespace, "mycampaign")

    def test_an_explicit_namespace_wins_over_the_slug_of_the_name(self):
        cfg = self._config_of("--namespace", "Elsewhere")
        self.assertEqual(cfg.namespace, "elsewhere")
        self.assertEqual(cfg.name, "My Campaign")

    def test_the_names_section_points_at_the_starter_culture(self):
        cfg = self._config_of()
        self.assertEqual(cfg.names_cultures, "names/cultures")
        self.assertIsNone(cfg.names_official_culture)

    def test_a_name_containing_a_quote_still_produces_readable_toml(self):
        # Substitution, not a TOML writer: an unescaped quote or backslash
        # closes the string early and leaves a campaign.toml that no tool in
        # the package can read — a workspace that init reports as created and
        # every other command then refuses.
        cfg = self._config_of(name='My "Great" Campaign\\Two')
        self.assertEqual(cfg.name, 'My "Great" Campaign\\Two')
        self.assertEqual(cfg.namespace, "mygreatcampaigntwo")


def _scrubbed_env(**extra: str) -> dict[str, str]:
    """The environment minus BUNNYFORGE_WORKSPACE, so a variable set in the
    developer's shell cannot point a child at the wrong campaign."""
    env = {k: v for k, v in os.environ.items() if k != "BUNNYFORGE_WORKSPACE"}
    env.update(extra)
    return env


class TestFreshWorkspacePassesTheGate(unittest.TestCase):
    """The headline regression test: a workspace init just created passes
    `review checkup` with 0 errors and 0 warnings, and runs the name
    generator — with no manual fixes. This is the parent spec's Testing item 2
    and its success criterion 5, and the test setup_campaign.py never had.

    Run as real child processes rather than in-process, because the claim
    being made is about what a person gets after typing two commands: only a
    subprocess covers the whole path from `python3 -m bunnyforge.init` through
    argparse, resource loading, and exit codes.
    """

    def _init_child(self) -> Path:
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        target = tmp / "fresh"
        result = subprocess.run(
            [sys.executable, "-m", "bunnyforge.init", str(target),
             "--name", "My Campaign"],
            cwd=tmp, capture_output=True, text=True, env=_scrubbed_env())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return target

    def test_checkup_reports_no_errors_and_no_warnings(self):
        target = self._init_child()
        result = subprocess.run(
            [sys.executable, "-m", "bunnyforge.review", "checkup",
             "--workspace", str(target)],
            cwd=target.parent, capture_output=True, text=True,
            env=_scrubbed_env())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Summary: 0 error(s), 0 warning(s).", result.stdout)

    def test_the_name_generator_runs_in_a_fresh_workspace(self):
        # Proves the [names] wiring end to end: the generated campaign.toml
        # points at names/cultures, and the starter culture packaged there is
        # loadable and usable.
        target = self._init_child()
        result = subprocess.run(
            [sys.executable, "-m", "bunnyforge.generate_names",
             "--workspace", str(target), "-n", "3", "--seed", "1"],
            cwd=target.parent, capture_output=True, text=True,
            env=_scrubbed_env())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        names = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
        self.assertEqual(len(names), 3, result.stdout)
        self.assertTrue(all(names), result.stdout)


# The cross-ticket contract with the `bunnyforge vscode` command (#33):
# these strings are frozen — that command parses them. Hardcoded rather
# than imported from vscode.py, which holds the same constants; the drift
# test in tests/test_vscode.py (TestPackagedContract) binds those to these
# packaged bytes, so neither side can move alone.
VSCODE_MARKER_BEGIN = "// bunnyforge:begin visibility-colouring"
VSCODE_MARKER_END = "// bunnyforge:end visibility-colouring"
VSCODE_OFF_PREFIX = "//- "


class TestVscodeScaffold(unittest.TestCase):
    """The packaged .vscode/ files: inert on arrival, valid JSONC in both
    toggle states, and never recommending an extension that cannot resolve.

    These tests deliberately do NOT pin the comment prose — #33 reworded
    the headers to name the `bunnyforge vscode` command, and further
    rewording must not break this suite.
    """

    def _settings_lines(self) -> list[str]:
        return (init.packaged_bytes("vscode/settings.json")
                .decode("utf-8").split("\n"))

    def test_settings_carries_exactly_one_marker_pair_in_order(self):
        stripped = [l.strip() for l in self._settings_lines()]
        self.assertEqual(stripped.count(VSCODE_MARKER_BEGIN), 1)
        self.assertEqual(stripped.count(VSCODE_MARKER_END), 1)
        self.assertLess(stripped.index(VSCODE_MARKER_BEGIN),
                        stripped.index(VSCODE_MARKER_END))

    def test_the_managed_region_ships_fully_inert(self):
        stripped = [l.strip() for l in self._settings_lines()]
        begin = stripped.index(VSCODE_MARKER_BEGIN)
        end = stripped.index(VSCODE_MARKER_END)
        region = [l for l in stripped[begin + 1:end] if l]
        self.assertTrue(region, "managed region is empty")
        for line in region:
            self.assertTrue(line.startswith("//"),
                            f"live line inside the shipped region: {line!r}")
        self.assertTrue(
            any(l.startswith(VSCODE_OFF_PREFIX) for l in region),
            "no //-  disabled block — nothing for `vscode on` to enable")

    def _as_json(self, *, enabled: bool):
        """The file as strict JSON: comments dropped, //-  lines optionally
        re-enabled first — simulating exactly what the `bunnyforge vscode`
        toggle does."""
        kept = []
        for raw in self._settings_lines():
            indent = raw[:len(raw) - len(raw.lstrip())]
            body = raw.strip()
            if enabled and body.startswith(VSCODE_OFF_PREFIX):
                kept.append(indent + body[len(VSCODE_OFF_PREFIX):])
            elif not body.startswith("//"):
                kept.append(raw)
        return json.loads("\n".join(kept))

    def test_settings_is_strict_json_with_the_block_off(self):
        self.assertEqual(self._as_json(enabled=False),
                         {"markdown.preview.frontMatter": "table"})

    def test_settings_is_strict_json_with_the_block_enabled(self):
        data = self._as_json(enabled=True)
        self.assertEqual(data["markdown.preview.frontMatter"], "table")
        self.assertEqual(set(data["highlight.regexes"]), {
            r"^(visibility:\s*gm-only\s*)$",
            r"^(visibility:\s*player-visible\s*)$",
            r"^(visibility:\s*mixed\s*)$",
            r"^(## GM notes\s*)$",
            r"^(reveal_when:.*)$",
        })
        for rule in data["highlight.regexes"].values():
            self.assertEqual(rule["filterLanguageRegex"], "markdown")

    def test_extensions_recommends_only_the_marketplace_extension(self):
        lines = (init.packaged_bytes("vscode/extensions.json")
                 .decode("utf-8").split("\n"))
        data = json.loads("\n".join(
            l for l in lines if not l.strip().startswith("//")))
        self.assertEqual(
            data, {"recommendations": ["fabiospampinato.vscode-highlight"]})

    def test_the_preview_extension_appears_only_in_comments(self):
        # It is not on the Marketplace; a recommendation entry could never
        # resolve, so its id must never appear on a live line.
        for resource in ("vscode/settings.json", "vscode/extensions.json"):
            for line in (init.packaged_bytes(resource)
                         .decode("utf-8").split("\n")):
                if "bunnyforge-visibility-preview" in line:
                    self.assertTrue(
                        line.strip().startswith("//"),
                        f"{resource}: live reference to the unlisted "
                        f"extension: {line!r}")
