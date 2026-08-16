"""Tests for the `bunnyforge` dispatcher (cli.py, __main__.py, the
console script).

The dispatcher's contract is deliberately thin: the first token picks a
module, everything after it reaches that module's main(argv) verbatim, and
argparse owns --help and the unknown-command error path. These tests pin
that contract at three boundaries -- in-process here and in TestDispatch,
`python3 -m bunnyforge` in TestModuleDoor, and the installed console script
in TestConsoleScript.
"""

import contextlib
import io
import shutil
import subprocess
import sys
import sysconfig
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from bunnyforge import (
    build_sheets,
    cli,
    deploy_export,
    export_player,
    generate_names,
    import_perceptions,
    init,
    review,
    run_tests,
    serve_mcp,
    vscode,
)

REPO = Path(__file__).resolve().parent.parent


class TestDispatchTable(unittest.TestCase):

    def test_every_subcommand_maps_to_its_modules_main(self):
        self.assertEqual(cli._COMMANDS, {
            "init": init.main,
            "review": review.main,
            "export-player": export_player.main,
            "deploy-export": deploy_export.main,
            "import-perceptions": import_perceptions.main,
            "build-sheets": build_sheets.main,
            "names": generate_names.main,
            "vscode": vscode.main,
            "serve-mcp": serve_mcp.main,
            "test": run_tests.main,
        })


class TestDispatch(unittest.TestCase):

    def test_arguments_after_the_subcommand_pass_through_verbatim(self):
        seen = {}

        def stub(argv):
            seen["argv"] = argv
            return 0

        with mock.patch.dict(cli._COMMANDS, {"review": stub}):
            rc = cli.main(["review", "--workspace", "X", "checkup", "--html"])
        self.assertEqual(rc, 0)
        self.assertEqual(seen["argv"],
                         ["--workspace", "X", "checkup", "--html"])

    def test_the_exit_code_of_the_target_main_is_returned_unchanged(self):
        with mock.patch.dict(cli._COMMANDS, {"names": lambda argv: 7}):
            self.assertEqual(cli.main(["names"]), 7)

    def test_help_lists_every_subcommand(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            with self.assertRaises(SystemExit) as cm:
                cli.main(["--help"])
        self.assertEqual(cm.exception.code, 0)
        for name in cli._COMMANDS:
            self.assertIn(name, out.getvalue())

    def test_unknown_subcommand_is_one_error_line_and_exit_2(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            with self.assertRaises(SystemExit) as cm:
                cli.main(["frobnicate"])
        self.assertEqual(cm.exception.code, 2)
        text = err.getvalue()
        self.assertEqual(
            len([l for l in text.splitlines() if "error:" in l]), 1, text)
        self.assertNotIn("Traceback", text)

    def test_no_arguments_is_an_error_line_not_a_traceback(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            with self.assertRaises(SystemExit) as cm:
                cli.main([])
        self.assertEqual(cm.exception.code, 2)
        text = err.getvalue()
        self.assertEqual(
            len([l for l in text.splitlines() if "error:" in l]), 1, text)
        self.assertNotIn("Traceback", text)


class TestModuleDoor(unittest.TestCase):
    """`python3 -m bunnyforge` -- the door that needs no install wiring.

    Subprocess on purpose: "never a traceback" is a claim about the real
    process boundary, and only a child process can prove it.
    """

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "bunnyforge", *args],
            capture_output=True, text=True)

    def test_python_dash_m_bunnyforge_answers_help(self):
        r = self._run("--help")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for name in cli._COMMANDS:
            self.assertIn(name, r.stdout)

    def test_unknown_subcommand_never_shows_a_traceback(self):
        r = self._run("frobnicate")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(
            len([l for l in r.stderr.splitlines() if "error:" in l]), 1,
            r.stderr)
        self.assertNotIn("Traceback", r.stdout + r.stderr)


class TestConsoleScript(unittest.TestCase):
    """The installed `bunnyforge` command.

    Two layers on purpose. The tomllib assertion pins the wiring string
    in-repo; but the script wrapper is generated at install time, so only
    running it proves the [project.scripts] entry end-to-end. The suite
    already requires the package installed (every test imports
    bunnyforge), so a missing script is a stale install, not an optional
    extra -- the smoke test fails with the remedy rather than skipping
    into silence.
    """

    def test_pyproject_declares_the_console_script(self):
        data = tomllib.loads((REPO / "pyproject.toml").read_text("utf-8"))
        self.assertEqual(data["project"]["scripts"],
                         {"bunnyforge": "bunnyforge.cli:main"})

    def test_the_installed_script_answers_help(self):
        script = Path(sysconfig.get_path("scripts")) / "bunnyforge"
        if not script.exists():
            found = shutil.which("bunnyforge")
            self.assertIsNotNone(
                found, "no installed `bunnyforge` script — the "
                       "[project.scripts] entry only materialises at "
                       "install time; run `python3 -m pip install -e .` "
                       "and re-run")
            script = Path(found)
        r = subprocess.run([str(script), "--help"],
                          capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("bunnyforge", r.stdout)


if __name__ == "__main__":
    unittest.main()
