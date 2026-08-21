# serve-mcp `--log-file` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An opt-in `--log-file [PATH]` flag on `bunnyforge serve-mcp` that routes uvicorn's access log to a self-rotating file (midnight, 14 kept) while errors still reach stderr; without the flag, behavior is unchanged byte-for-byte.

**Architecture:** Two pure helpers in `serve_mcp.py` — `_default_log_path()` (platform default location) and `_log_config(path)` (a `dictConfig` dict for uvicorn with ONE shared `TimedRotatingFileHandler`) — plus a small `main()` integration: create the log directory, refuse with one stderr line on `OSError`, pass `log_config=` to `uvicorn.run` only when the flag is present. No new modules, no new dependencies.

**Tech Stack:** Python stdlib (`argparse`, `logging.handlers`, `pathlib`), uvicorn's `log_config=` parameter, `unittest` (this repo does not use pytest).

**Spec:** `docs/superpowers/specs/2026-08-21-serve-mcp-log-file-design.md` — read it first; the plan argues from it.

## Global Constraints

- Issue: dcltdw/bunnyforge#87. Every commit message body carries `Refs #87` (the PR will carry `Closes #87`).
- Work happens on branch `worktree-serve-mcp-log-file` in the worktree at `.claude/worktrees/serve-mcp-log-file` (already created; the spec is already committed there).
- Test runner: `python3 -m unittest <module> -v` for one module, `python3 -m unittest discover -s tests` for the suite. Baseline is green: 935 tests, OK (skipped=58).
- The `mcp` SDK (and uvicorn, which ships with the `[mcp]` extra) is optional: `serve_mcp.py` must stay importable on bare Python, so never import uvicorn at module top level. Tests needing it are guarded with `@unittest.skipUnless(HAVE_MCP, ...)` (the `HAVE_MCP` constant already exists in `tests/test_serve_mcp.py`).
- No test opens a socket or reaches a real `uvicorn.run` — the run is mocked where needed.
- With `--log-file` absent, `uvicorn.run` must be called WITHOUT a `log_config` kwarg at all (not `log_config=None`), so today's default logging is untouched.
- Rotation values are fixed: `when="midnight"`, `backupCount=14`. No tuning flags.
- Exactly ONE file handler shared by all uvicorn loggers (two rotating handlers on one file collide on the rollover rename).
- `scripts/mcp-session.py` is NOT modified.
- Code style: follow the file's existing look — 4-space indent, lowercase one-line error messages to stderr, comments only for non-obvious constraints.
- Commit trailer: `Co-Authored-By:` the current AI model, per repo convention.

---

### Task 1: `_default_log_path()` and the `--log-file` parser flag

**Files:**
- Modify: `src/bunnyforge/serve_mcp.py` (imports at ~line 29; new helper just above `def build_parser()` at ~line 250; new argument inside `build_parser()` after the `--no-auth` argument)
- Test: `tests/test_serve_mcp.py` (new test class after `TestMainGuards`)

**Interfaces:**
- Consumes: nothing new.
- Produces: `_default_log_path() -> pathlib.Path` (module-level, underscore-private), and `build_parser()` gaining `--log-file` with `nargs="?"`; parsed value `args.log_file` is `None` when absent, `str(_default_log_path())` when bare, or the given string. Task 3 consumes `args.log_file`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_serve_mcp.py`, directly after the `TestMainGuards` class, add:

```python
class TestLogFileFlag(unittest.TestCase):
    """--log-file parsing and the platform default path — bare Python."""

    def parse(self, argv):
        return serve_mcp.build_parser().parse_args(argv)

    def test_absent_means_none(self):
        self.assertIsNone(self.parse([]).log_file)

    def test_bare_flag_uses_platform_default(self):
        self.assertEqual(self.parse(["--log-file"]).log_file,
                         str(serve_mcp._default_log_path()))

    def test_explicit_path_wins(self):
        self.assertEqual(self.parse(["--log-file", "/tmp/x.log"]).log_file,
                         "/tmp/x.log")

    def test_default_path_on_macos(self):
        with mock.patch("sys.platform", "darwin"):
            self.assertEqual(
                serve_mcp._default_log_path(),
                Path.home() / "Library" / "Logs" / "bunnyforge" / "mcp.log")

    def test_default_path_honors_xdg_state_home(self):
        with mock.patch("sys.platform", "linux"), \
             mock.patch.dict(os.environ, {"XDG_STATE_HOME": "/var/state"}):
            self.assertEqual(serve_mcp._default_log_path(),
                             Path("/var/state/bunnyforge/mcp.log"))

    def test_default_path_falls_back_without_xdg(self):
        with mock.patch("sys.platform", "linux"), \
             mock.patch.dict(os.environ, {"XDG_STATE_HOME": ""}):
            self.assertEqual(
                serve_mcp._default_log_path(),
                Path.home() / ".local" / "state" / "bunnyforge" / "mcp.log")
```

(`unittest`, `mock`, `os`, and `Path` are already imported at the top of the test file.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_serve_mcp.TestLogFileFlag -v`
Expected: errors — `AttributeError: module 'bunnyforge.serve_mcp' has no attribute '_default_log_path'` and `'Namespace' object has no attribute 'log_file'`.

- [ ] **Step 3: Implement**

In `src/bunnyforge/serve_mcp.py`:

(a) Add to the stdlib imports (after `import sys`):

```python
from pathlib import Path
```

(b) Immediately above `def build_parser()`, add:

```python
def _default_log_path() -> Path:
    """Where --log-file logs when given no value.

    macOS gets ~/Library/Logs (where log viewers look); everywhere else
    follows the XDG state convention, matching scripts/mcp-session.py's
    own state directory.
    """
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "bunnyforge" / "mcp.log"
    state = os.environ.get("XDG_STATE_HOME", "").strip()
    base = Path(state) if state else Path.home() / ".local" / "state"
    return base / "bunnyforge" / "mcp.log"
```

(c) Inside `build_parser()`, after the `--no-auth` `add_argument` call (before `--allow-direct-edits`), add:

```python
    parser.add_argument("--log-file", nargs="?", metavar="PATH",
                        const=str(_default_log_path()),
                        help="write uvicorn's logs to PATH instead of "
                             "cluttering stderr with access lines; rotated "
                             "at midnight, 14 days kept. Bare --log-file "
                             "uses %(const)s")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_serve_mcp.TestLogFileFlag -v`
Expected: 6 tests, OK.

- [ ] **Step 5: Commit**

```bash
git add src/bunnyforge/serve_mcp.py tests/test_serve_mcp.py
git commit -m "feat: --log-file flag and its platform default path

Refs #87"
```

(Plus the model `Co-Authored-By:` trailer.)

---

### Task 2: `_log_config()` — the uvicorn logging dict

**Files:**
- Modify: `src/bunnyforge/serve_mcp.py` (new function directly below `_default_log_path()`)
- Test: `tests/test_serve_mcp.py` (new test class after `TestLogFileFlag`)

**Interfaces:**
- Consumes: nothing from other tasks (pure function).
- Produces: `_log_config(path: Path) -> dict`, a `logging.config.dictConfig`-shaped dict for `uvicorn.run(log_config=...)`. Task 3 consumes it.

- [ ] **Step 1: Write the failing tests**

In `tests/test_serve_mcp.py`, after `TestLogFileFlag`, add:

```python
class TestLogConfig(unittest.TestCase):
    """The dict handed to uvicorn: access to file only, errors to both."""

    def setUp(self):
        self.cfg = serve_mcp._log_config(Path("/tmp/mcp.log"))

    def test_access_goes_to_file_only(self):
        self.assertEqual(self.cfg["loggers"]["uvicorn.access"]["handlers"],
                         ["file"])

    def test_errors_go_to_file_and_stderr(self):
        self.assertEqual(self.cfg["loggers"]["uvicorn.error"]["handlers"],
                         ["file", "stderr"])
        self.assertEqual(self.cfg["loggers"]["uvicorn"]["handlers"],
                         ["file", "stderr"])

    def test_one_rotating_file_handler_midnight_keep_14(self):
        # ONE file handler on purpose: two rotating handlers on the same
        # file would both attempt the rollover rename and collide.
        handlers = self.cfg["handlers"]
        file_handlers = [h for h in handlers.values()
                         if "filename" in h]
        self.assertEqual(len(file_handlers), 1)
        h = handlers["file"]
        self.assertEqual(
            h["class"], "logging.handlers.TimedRotatingFileHandler")
        self.assertEqual(h["when"], "midnight")
        self.assertEqual(h["backupCount"], 14)
        self.assertEqual(h["filename"], "/tmp/mcp.log")

    def test_dict_is_valid_dictconfig(self):
        # A wiring assertion can pass on a malformed dict; only
        # dictConfig itself proves the schema. Built against a tmpdir
        # because the rotating handler opens its file eagerly.
        import logging
        import logging.config
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        logging.config.dictConfig(serve_mcp._log_config(root / "mcp.log"))
        try:
            self.assertTrue(logging.getLogger("uvicorn.access").handlers)
            self.assertTrue((root / "mcp.log").exists())
        finally:
            for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
                logger = logging.getLogger(name)
                for handler in list(logger.handlers):
                    handler.close()
                    logger.removeHandler(handler)
                logger.propagate = True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_serve_mcp.TestLogConfig -v`
Expected: 4 errors — `AttributeError: module 'bunnyforge.serve_mcp' has no attribute '_log_config'`.

- [ ] **Step 3: Implement**

In `src/bunnyforge/serve_mcp.py`, directly below `_default_log_path()`, add:

```python
def _log_config(path: Path) -> dict:
    """uvicorn log_config: access lines to a rotated file, errors to both.

    One TimedRotatingFileHandler shared by every uvicorn logger — two
    rotating handlers on the same file would both attempt the rollover
    rename and collide. The formatter adds timestamps, which uvicorn's
    stderr default lacks; access lines render fine through it because
    the request line lives in the record's message/args.
    """
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "timestamped": {
                "format": "%(asctime)s %(levelname)s %(message)s"}},
        "handlers": {
            "file": {
                "class": "logging.handlers.TimedRotatingFileHandler",
                "filename": str(path),
                "when": "midnight",
                "backupCount": 14,
                "formatter": "timestamped"},
            "stderr": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stderr",
                "formatter": "timestamped"}},
        "loggers": {
            "uvicorn": {"handlers": ["file", "stderr"],
                        "level": "INFO", "propagate": False},
            "uvicorn.error": {"handlers": ["file", "stderr"],
                              "level": "INFO", "propagate": False},
            "uvicorn.access": {"handlers": ["file"],
                               "level": "INFO", "propagate": False}},
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_serve_mcp.TestLogConfig -v`
Expected: 4 tests, OK.

- [ ] **Step 5: Commit**

```bash
git add src/bunnyforge/serve_mcp.py tests/test_serve_mcp.py
git commit -m "feat: the log_config dict that splits access from errors

Refs #87"
```

---

### Task 3: `main()` integration — mkdir, refusal, and the uvicorn.run wiring

**Files:**
- Modify: `src/bunnyforge/serve_mcp.py` (two spots inside `main()`: after the auth checks, and the `uvicorn.run` call at the end)
- Test: `tests/test_serve_mcp.py` (one test added to `TestStartupContract`; one new class after `TestLogConfig`)

**Interfaces:**
- Consumes: `args.log_file` (Task 1), `_log_config(path)` (Task 2).
- Produces: the user-visible behavior; nothing downstream.

- [ ] **Step 1: Write the failing tests**

(a) Inside the existing `TestStartupContract` class (it already has the `_main` helper and clears `BUNNYFORGE_MCP_KEY`), add:

```python
    def test_log_file_refuses_uncreatable_directory(self):
        # A file where a directory is needed: mkdir(parents=True) fails
        # with NotADirectoryError, an OSError — deterministically, on
        # bare Python, before any uvicorn import. uvicorn is stubbed so
        # that a MISSING refusal fails fast (rc 0 from the mock) rather
        # than falling through to a real uvicorn.run and serving.
        blocker = self.enterContext(tempfile.NamedTemporaryFile())
        target = Path(blocker.name) / "sub" / "mcp.log"
        with mock.patch.dict("sys.modules",
                             {"uvicorn": mock.MagicMock()}):
            rc, err = self._main(["--no-auth", "--log-file", str(target)])
        self.assertEqual(rc, 1)
        self.assertIn("log directory", err)
        self.assertNotIn("Traceback", err)
```

(b) After `TestLogConfig`, add a new class:

```python
@unittest.skipUnless(HAVE_MCP, "needs the mcp extra")
class TestLogFileWiring(unittest.TestCase):
    """main() hands uvicorn the log_config — run mocked, no socket."""

    def _main(self, extra):
        store = scaffold(self)
        import uvicorn
        with mock.patch.object(uvicorn, "run") as run, \
             mock.patch.dict(os.environ, {"BUNNYFORGE_MCP_KEY": ""}), \
             contextlib.redirect_stdout(io.StringIO()) as out, \
             contextlib.redirect_stderr(io.StringIO()):
            rc = serve_mcp.main(["--workspace", str(store.ws.root),
                                 "--no-auth"] + extra)
        return rc, run, out.getvalue()

    def test_flag_passes_log_config_and_creates_directory(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        target = root / "logs" / "mcp.log"
        rc, run, out = self._main(["--log-file", str(target)])
        self.assertEqual(rc, 0)
        self.assertTrue(target.parent.is_dir())
        cfg = run.call_args.kwargs["log_config"]
        self.assertEqual(cfg["handlers"]["file"]["filename"], str(target))
        self.assertIn(str(target), out)   # startup line names the path

    def test_no_flag_passes_no_log_config_kwarg(self):
        rc, run, _ = self._main([])
        self.assertEqual(rc, 0)
        self.assertNotIn("log_config", run.call_args.kwargs)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_serve_mcp.TestStartupContract.test_log_file_refuses_uncreatable_directory tests.test_serve_mcp.TestLogFileWiring -v`
Expected: the refusal test FAILS — today `main` ignores the flag, sails past the missing mkdir guard, and hits the stubbed `uvicorn.run`, so rc is 0, not 1 (on a bare Python without `mcp` it instead returns 1 with the install hint and fails on the missing "log directory" message — either way a fast, deterministic failure, no server started). `test_flag_passes_log_config_and_creates_directory` FAILS with `KeyError: 'log_config'`; `test_no_flag_passes_no_log_config_kwarg` PASSES already (that is fine — it pins today's behavior against regression).

- [ ] **Step 3: Implement**

In `main()` in `src/bunnyforge/serve_mcp.py`:

(a) After the auth-check block (the one ending `return 1` under `refusing to start without auth`), and BEFORE the `# --public-host does double duty` comment, insert:

```python
    log_path = None
    if args.log_file is not None:
        log_path = Path(args.log_file).expanduser()
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            print(f"cannot create log directory {log_path.parent}: {exc}",
                  file=sys.stderr)
            return 1
```

(This sits before the `import uvicorn` block on purpose: the refusal must fire on bare Python.)

(b) Replace the final run call:

```python
    uvicorn.run(app, host=args.host, port=args.port)
```

with:

```python
    if log_path:
        print(f"access log: {log_path} (rotated at midnight, 14 kept)")
        uvicorn.run(app, host=args.host, port=args.port,
                    log_config=_log_config(log_path))
    else:
        uvicorn.run(app, host=args.host, port=args.port)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_serve_mcp -v 2>&1 | tail -5`
Expected: whole module OK (the new tests plus every pre-existing one).

- [ ] **Step 5: Commit**

```bash
git add src/bunnyforge/serve_mcp.py tests/test_serve_mcp.py
git commit -m "feat: serve-mcp --log-file routes access noise to a rotated file

Refs #87"
```

---

### Task 4: Documentation, changelog, full-suite verification

**Files:**
- Modify: `docs/serve-mcp.md` (new `## Logging` section immediately before `## Troubleshooting`, ~line 256)
- Modify: `CHANGELOG.md` (new `### Added` subsection at the top of `[Unreleased]`, before the existing `### Changed`)

**Interfaces:**
- Consumes: the flag's final behavior from Tasks 1–3 (doc text below matches it exactly).
- Produces: nothing downstream.

- [ ] **Step 1: Add the Logging section to docs/serve-mcp.md**

Insert immediately before the `## Troubleshooting` heading:

```markdown
## Logging

By default uvicorn writes every request to stderr — run in a background
terminal, that clutters it with access lines. `--log-file` moves them to
a self-pruning file instead:

    bunnyforge serve-mcp --public-host mcp.example.com --log-file

With no value the log goes to `~/Library/Logs/bunnyforge/mcp.log` on
macOS and `$XDG_STATE_HOME/bunnyforge/mcp.log` (default
`~/.local/state/bunnyforge/mcp.log`) elsewhere; pass a path to choose.
The file rotates at midnight and 14 days are kept — the server prunes
its own logs, nothing else to configure.

Access lines go only to the file. Errors — the startup banner, bind
failures, tracebacks — still reach stderr as well, so a crashed server
says why in the terminal while the file stays a complete record of the
run.

`scripts/mcp-session.py` already captures the whole stdout/stderr stream
to its own `server.log`; it needs no flag and is unchanged.
```

- [ ] **Step 2: Add the changelog entry**

In `CHANGELOG.md`, directly under the `## [Unreleased]` heading and before the existing `### Changed`, insert:

```markdown
### Added

- `bunnyforge serve-mcp --log-file [PATH]` routes uvicorn's logs to a
  self-pruning file (rotated at midnight, 14 days kept) instead of
  cluttering the terminal with access lines; errors still reach stderr
  too. Bare `--log-file` picks a platform default:
  `~/Library/Logs/bunnyforge/mcp.log` on macOS,
  `$XDG_STATE_HOME/bunnyforge/mcp.log` elsewhere. (#87)
```

- [ ] **Step 3: Run the full suite**

Run: `python3 -m unittest discover -s tests 2>&1 | grep -E "^(OK|FAILED|Ran )"`
Expected: `Ran 948 tests` (935 baseline + 13 new; trust the OK line over the exact count if other PRs landed meanwhile), `OK (skipped=58)` — skips rise if the `mcp` extra is absent.

- [ ] **Step 4: Commit**

```bash
git add docs/serve-mcp.md CHANGELOG.md
git commit -m "docs: the Logging section and changelog entry for --log-file

Refs #87"
```

---

## After the tasks

Use `superpowers:finishing-a-development-branch`. The PR closes #87 (`Closes #87` in the body), is opened with the `dcltdw:opening-a-pr` skill, and waits for review — no self-merge. The board card for #87 moves per the PR skills.
