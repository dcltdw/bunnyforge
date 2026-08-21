# serve-mcp Launch Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `bunnyforge serve-mcp` survives closing its terminal: a
`--auth-key-file` flag so the GM key never sits in a plist, refusals that
exit 78 so a service manager can tell configuration from crash, and a
documented macOS launch agent recipe with mandatory verification.

**Architecture:** All code lands in `src/bunnyforge/serve_mcp.py` — a new
key-resolution helper pair (`_read_key_file`, `_resolve_key`), one parser
flag, and an `EXIT_CONFIG = 78` constant applied to every startup refusal.
The launch agent itself is delivered as a doc recipe in
`docs/serve-mcp.md` mirroring the cloudflared section, not as generated
code. Design rationale: the spec (below) — read it first.

**Tech Stack:** Python stdlib only (argparse, stat, pathlib); unittest;
macOS launchd (documented, not executed).

**Spec:** `docs/superpowers/specs/2026-08-21-serve-mcp-launch-agent-design.md`
(committed on this branch). Issue: dcltdw/bunnyforge#93.

## Global Constraints

- **Workspace:** the branch `serve-mcp-launch-agent` in the worktree
  `/Users/dcltdw/Github/bunnyforge/.claude/worktrees/serve-mcp-launch-agent`
  already exists with the spec committed. Work there. Never commit to
  `main`, never touch the other worktrees.
- **Test command (bare shape):** the shared `.venv` python is an editable
  install pointing at the MAIN checkout, so from the worktree always run:
  `export PYTHONPATH=/Users/dcltdw/Github/bunnyforge/.claude/worktrees/serve-mcp-launch-agent/src`
  then `/Users/dcltdw/Github/bunnyforge/.venv/bin/python3 -m unittest discover -s tests`.
  Expected shape: `Ran 950 tests … OK (skipped=60)` (counts grow as tasks
  add tests). Neither `mcp` nor `uvicorn` is installed there; the
  `@skipUnless(HAVE_MCP)` tests only skip — that is normal, not a failure.
- **Full shape (`[mcp]` extra):** only Task 5 needs it; it builds a
  throwaway venv (instructions there), matching CI's `mcp-suite` job.
- **No new dependencies.** Everything added is stdlib.
- **Every new refusal must fire before any SDK import** so it runs (and
  is tested) on bare Python — the existing `main()` ordering already
  guarantees this; keep the new code above the `import uvicorn` line.
- **Style:** match `serve_mcp.py` as it is — 4-space indent, ~75-column
  wrap, double quotes, comments that state constraints rather than
  narrate. Doc code blocks in `docs/serve-mcp.md` are indented (4 spaces,
  8 inside list items), not fenced.
- **Exit codes are the contract:** startup refusals exit
  `EXIT_CONFIG = 78` (sysexits `EX_CONFIG`); `--check` keeps its
  documented `0` / `1`. Do not "clean up" the check path to 78.
- **Commits:** confirm `git branch --show-current` says
  `serve-mcp-launch-agent` before each commit. Trailer every commit with
  the model line the session's harness specifies
  (`Co-Authored-By: Claude <model> <noreply@anthropic.com>`).

---

### Task 1: Prerequisite gate and baseline

PR #94 (open at plan time) rewrites the exact `docs/serve-mcp.md`
passages Task 4 anchors to (the tunnel's step 7 verification, the
workspace-variables note). The code tasks don't need it; the doc task
does.

**Files:** none modified.

**Interfaces:**
- Consumes: nothing.
- Produces: a rebased branch whose `docs/serve-mcp.md` contains
  `7. **Check that it actually starts.**` — the anchor Task 4 inserts
  after.

- [ ] **Step 1: Check #94's state**

Run: `gh pr view 94 --repo dcltdw/bunnyforge --json state --jq .state`

- `MERGED`: continue to Step 2.
- Anything else: do Tasks 2 and 3 now, then **stop before Task 4 and
  report** that the doc task is waiting on #94 — do not hand-merge #94's
  text yourself.

- [ ] **Step 2: Rebase onto current main**

```bash
git fetch origin
git rebase origin/main
```

Expected: clean rebase (the spec commit touches only a new file). Verify
the anchor exists: `grep -n "Check that it actually starts" docs/serve-mcp.md`
→ one hit.

- [ ] **Step 3: Baseline suite**

Run the bare-shape test command from Global Constraints.
Expected: `OK (skipped=60)`. If not green, stop and report — do not build
on a red baseline.

---

### Task 2: Refusals exit 78 (`EXIT_CONFIG`)

Every pre-serve refusal in `main()` — bad workspace, auth contradictions,
missing auth, unwritable log file, missing `[mcp]` extra — currently
returns 1, indistinguishable in `launchctl list` from a crash. They
become 78 (`EX_CONFIG`). `--check`'s report stays 0/1.

**Files:**
- Modify: `src/bunnyforge/serve_mcp.py` (constant near `KEY_ENV`; five
  `return 1` sites in `main()`)
- Test: `tests/test_serve_mcp.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `serve_mcp.EXIT_CONFIG: int = 78`, used by Task 3's tests and
  named in Task 4's docs and Task 5's changelog. Refusal `return` sites
  in `main()` all use it.

- [ ] **Step 1: Update the refusal assertions to fail first (TDD)**

In `tests/test_serve_mcp.py`, change the expected exit code from `1` to
`serve_mcp.EXIT_CONFIG` in exactly these six tests (find them by name,
not line number):

- `TestMainGuards.test_bad_workspace_is_one_error_line_not_a_traceback`
- `TestStartupContract.test_refuses_without_key_or_no_auth`
- `TestStartupContract.test_refuses_key_and_no_auth_together`
- `TestStartupContract.test_env_key_counts_as_key_for_the_contradiction`
- `TestStartupContract.test_log_file_refuses_uncreatable_directory`
- `TestStartupContract.test_log_file_refuses_a_directory_as_the_target`

e.g. the first becomes:

```python
    def test_bad_workspace_is_one_error_line_not_a_traceback(self):
        empty = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.assertEqual(serve_mcp.main(["--workspace", str(empty)]),
                         serve_mcp.EXIT_CONFIG)
```

Add one new test to `TestStartupContract` pinning the number itself (78
is an external contract — a future systemd unit's
`RestartPreventExitStatus=78` depends on it):

```python
    def test_refusal_exit_code_is_ex_config(self):
        # sysexits(3) EX_CONFIG; a service manager keys on the number.
        self.assertEqual(serve_mcp.EXIT_CONFIG, 78)
```

Leave every `--check`/`report` test alone — `TestCheck`-side assertions
of `rc == 1` are the documented contract for a failing report.

- [ ] **Step 2: Run to verify the seven fail**

Run (with the Global Constraints PYTHONPATH exported):
`/Users/dcltdw/Github/bunnyforge/.venv/bin/python3 -m unittest tests.test_serve_mcp -v 2>&1 | tail -20`
Expected: 6 failures (`1 != 78`-shaped... actually `AttributeError:
EXIT_CONFIG` until the constant exists) plus the new pin test erroring
the same way. Either failure mode is the "red" this step wants.

- [ ] **Step 3: Implement**

In `src/bunnyforge/serve_mcp.py`, directly under the `KEY_ENV` line:

```python
KEY_ENV = "BUNNYFORGE_MCP_KEY"

# sysexits(3) EX_CONFIG: a startup refusal. The configuration is wrong
# and restarting cannot fix it, so a service manager (or a human reading
# `launchctl list`) can tell it from a crash, which stays exit 1 (#93).
EXIT_CONFIG = 78
```

Then in `main()`, change these five refusal returns from `return 1` to
`return EXIT_CONFIG` (and no others — in particular NOT
`return report(preflight(...))`):

1. the `except (ConfigError, WorkspaceError)` workspace block
2. the `--no-auth contradicts` block
3. the `refusing to start without auth` block
4. the `cannot write log file` block
5. the `except ModuleNotFoundError` install-hint block

- [ ] **Step 4: Run to verify green**

Same command as Step 2. Expected: `OK (skipped=…)`, zero failures. Then
the full bare suite: `… -m unittest discover -s tests` → `OK`.

- [ ] **Step 5: Commit**

```bash
git add src/bunnyforge/serve_mcp.py tests/test_serve_mcp.py
git commit -m "serve-mcp: startup refusals exit 78 (EX_CONFIG), not 1 (#93)"
```

---

### Task 3: The `--auth-key-file` flag

The plist carries a path, not the key. `--auth-key-file PATH` reads the
key from a private file: stripped, refused when missing/empty/too open.
Precedence: `--auth-key` and `--auth-key-file` together are ambiguous
(refused); either flag outranks `$BUNNYFORGE_MCP_KEY`.

**Files:**
- Modify: `src/bunnyforge/serve_mcp.py` (imports; two helpers before
  `build_parser`; one `add_argument`; the key-resolution block in
  `main()`)
- Test: `tests/test_serve_mcp.py` (new `TestAuthKeyFile` class)

**Interfaces:**
- Consumes: `EXIT_CONFIG` from Task 2.
- Produces:
  - `_read_key_file(path_str: str) -> str` — returns the stripped key;
    raises `ValueError` (message is the refusal line) on unreadable,
    group/other-accessible (POSIX only), or empty file.
  - `_resolve_key(args: argparse.Namespace) -> str` — full precedence;
    raises `ValueError` on flag conflict or via `_read_key_file`; returns
    `""` when no key anywhere (the existing no-auth refusal handles
    that case downstream, unchanged).
  - Parser accepts `--auth-key-file PATH` (`args.auth_key_file`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_serve_mcp.py` (after `TestStartupContract`):

```python
class TestAuthKeyFile(unittest.TestCase):
    """--auth-key-file: the key a plist can point at (#93).

    Bare Python throughout: resolution and every refusal fire before
    any SDK import.
    """

    def setUp(self):
        self.enterContext(mock.patch.dict(
            os.environ, {"BUNNYFORGE_MCP_KEY": ""}))

    def _keyfile(self, content="sekrit\n", mode=0o600) -> Path:
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        path = root / "mcp-key"
        path.write_text(content, encoding="utf-8")
        path.chmod(mode)
        return path

    def _resolve(self, argv):
        args = serve_mcp.build_parser().parse_args(argv)
        return serve_mcp._resolve_key(args)

    def _ws(self) -> Path:
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (root / "campaign.toml").write_text(MINIMAL, encoding="utf-8")
        return root

    def test_reads_and_strips_the_key(self):
        path = self._keyfile("  sekrit\n")
        self.assertEqual(
            self._resolve(["--auth-key-file", str(path)]), "sekrit")

    def test_missing_file_is_a_refusal(self):
        with self.assertRaisesRegex(ValueError, "cannot read"):
            self._resolve(["--auth-key-file", "/nonexistent/mcp-key"])

    def test_empty_file_is_a_refusal(self):
        path = self._keyfile("   \n")
        with self.assertRaisesRegex(ValueError, "empty"):
            self._resolve(["--auth-key-file", str(path)])

    @unittest.skipUnless(os.name == "posix", "POSIX file modes")
    def test_group_or_other_readable_is_a_refusal(self):
        path = self._keyfile(mode=0o644)
        with self.assertRaisesRegex(ValueError, "chmod 600"):
            self._resolve(["--auth-key-file", str(path)])

    def test_both_key_flags_together_are_ambiguous(self):
        path = self._keyfile()
        with self.assertRaisesRegex(ValueError, "contradicts"):
            self._resolve(["--auth-key", "k", "--auth-key-file", str(path)])

    def test_auth_key_flag_wins_without_reading_the_file(self):
        self.assertEqual(self._resolve(["--auth-key", "k"]), "k")

    def test_file_outranks_the_environment(self):
        path = self._keyfile("filekey\n")
        with mock.patch.dict(os.environ, {"BUNNYFORGE_MCP_KEY": "envkey"}):
            self.assertEqual(
                self._resolve(["--auth-key-file", str(path)]), "filekey")

    def test_environment_still_answers_when_no_flag(self):
        with mock.patch.dict(os.environ, {"BUNNYFORGE_MCP_KEY": "envkey"}):
            self.assertEqual(self._resolve([]), "envkey")

    def test_no_auth_conflict_through_main(self):
        # Same default-deny contradiction as --auth-key + --no-auth.
        path = self._keyfile()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            rc = serve_mcp.main(["--workspace", str(self._ws()),
                                 "--auth-key-file", str(path), "--no-auth"])
        self.assertEqual(rc, serve_mcp.EXIT_CONFIG)
        self.assertIn("contradict", stderr.getvalue())

    def test_bad_key_file_through_main_is_one_line_exit_78(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            rc = serve_mcp.main(["--workspace", str(self._ws()),
                                 "--auth-key-file", "/nonexistent/mcp-key"])
        self.assertEqual(rc, serve_mcp.EXIT_CONFIG)
        self.assertIn("cannot read auth key file", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())
```

- [ ] **Step 2: Run to verify they fail**

Run: `… -m unittest tests.test_serve_mcp.TestAuthKeyFile -v`
Expected: every test errors — `unrecognized arguments: --auth-key-file`
(SystemExit from argparse) or `AttributeError: _resolve_key`.

- [ ] **Step 3: Implement**

In `src/bunnyforge/serve_mcp.py`:

(a) Add `import stat` to the stdlib imports (alphabetical: between `os`
and `sys`).

(b) Immediately before `def build_parser()`:

```python
def _read_key_file(path_str: str) -> str:
    """The GM key from a file a plist can safely point at (#93).

    Stripped, so a trailing newline from echo is harmless. Refused when
    unreadable, empty, or -- on POSIX -- accessible to group or other:
    the file stands in for a secret typed by hand, and a lax mode is a
    misconfiguration to fix, not to serve through.
    """
    path = Path(path_str).expanduser()
    try:
        if os.name == "posix":
            mode = stat.S_IMODE(path.stat().st_mode)
            if mode & 0o077:
                raise ValueError(
                    f"auth key file {path} is group- or other-accessible "
                    f"(mode {mode:03o}) -- chmod 600 it")
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot read auth key file: {exc}") from None
    key = raw.strip()
    if not key:
        raise ValueError(f"auth key file {path} is empty")
    return key


def _resolve_key(args) -> str:
    """--auth-key, else --auth-key-file, else $BUNNYFORGE_MCP_KEY.

    The two flags together are refused as ambiguous rather than
    silently ordered; either flag outranks the environment variable,
    which is how --auth-key has always behaved. Raises ValueError
    carrying the one-line refusal; "" means no key anywhere, and the
    default-deny check in main() owns that refusal.
    """
    if args.auth_key and args.auth_key_file:
        raise ValueError("--auth-key contradicts --auth-key-file; "
                         "pick one")
    if args.auth_key:
        return args.auth_key.strip()
    if args.auth_key_file:
        return _read_key_file(args.auth_key_file)
    return os.environ.get(KEY_ENV, "").strip()
```

(c) In `build_parser()`, directly after the `--auth-key` argument:

```python
    parser.add_argument("--auth-key-file", metavar="PATH",
                        help="read the GM key from PATH -- for launchers "
                             "that run no shell (a launchd agent); the "
                             "file must not be group- or other-readable")
```

(d) In `main()`, replace the single line
`key = (args.auth_key or os.environ.get(KEY_ENV, "")).strip()` with:

```python
    try:
        key = _resolve_key(args)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return EXIT_CONFIG
```

(e) Widen the contradiction message on the next block so it names the
new flag (its `"contradict"` substring, which tests assert, is
unchanged):

```python
    if key and args.no_auth:
        print(f"--no-auth contradicts --auth-key/--auth-key-file/"
              f"{KEY_ENV}; pick one", file=sys.stderr)
        return EXIT_CONFIG
```

- [ ] **Step 4: Run to verify green**

`… -m unittest tests.test_serve_mcp.TestAuthKeyFile -v` → OK, then the
full bare suite → `OK (skipped=60)` with the test count up by 11.

- [ ] **Step 5: Commit**

```bash
git add src/bunnyforge/serve_mcp.py tests/test_serve_mcp.py
git commit -m "serve-mcp: --auth-key-file reads the GM key from a private file (#93)"
```

---

### Task 4: The launch agent recipe in `docs/serve-mcp.md`

Requires Task 1's #94 gate passed. Three edits, one file.

**Files:**
- Modify: `docs/serve-mcp.md`

**Interfaces:**
- Consumes: flag and exit-code behavior exactly as Tasks 2–3 shipped
  them (`--auth-key-file`, refusal exit 78, bare `--log-file` default
  `~/Library/Logs/bunnyforge/mcp.log`).
- Produces: the section heading `## Make the server start on its own
  (macOS)`, referenced by Task 5's changelog entry.

- [ ] **Step 1: Add the key-file pointer where the key is introduced**

In the `## Generate a GM key (once)` section, after "…it is never stored
by claude.ai.", append to the same paragraph:

```
For unattended starts, `--auth-key-file` reads it from a private file —
the launch agent recipe below leans on that.
```

- [ ] **Step 2: Point the asymmetry paragraph at the fix**

The paragraph beginning `**Starting the tunnel does not start
`serve-mcp`.**` ends with "…the correct answer rather than a fault."
Append one sentence:

```
The next section closes the asymmetry.
```

- [ ] **Step 3: Insert the new section**

Between the end of the `## Set up a named tunnel (once)` section (after
the "Do not put Cloudflare Access…" paragraph) and `## Check it before
adding the connector`, insert:

````markdown
## Make the server start on its own (macOS)

Step 6 got the tunnel a launch agent; this section gives `serve-mcp`
one of its own, so neither end of the route depends on a terminal
window staying open. The same trap applies: a launch agent starts **at
login, not at boot**.

One decision shapes the recipe: the GM key. A plist is not a secrets
store — it is readable by every process running as you, echoed by
`launchctl print`, and the first file you paste somewhere when
debugging — so the key goes in a private file and the plist carries
only its path, the same trust class as the `config.yml` path in the
tunnel's plist. `--auth-key-file` reads it, strips a trailing newline,
and refuses an empty or group/other-readable file.

1. **Put the key in a file.** Any path works; this one sits beside the
   OAuth state file that "Resetting access" already covers:

        mkdir -p ~/.local/state/bunnyforge
        printf '%s\n' '<your key>' > ~/.local/state/bunnyforge/mcp-key
        chmod 600 ~/.local/state/bunnyforge/mcp-key

2. **Create the log directory** — launchd does not create the parents
   of its log paths:

        mkdir -p ~/Library/Logs/bunnyforge

3. **Write `~/Library/LaunchAgents/com.bunnyforge.serve-mcp.plist`.**
   Every path must be absolute: launchd expands no `~` and reads no
   shell profile — which is also why the workspace travels as
   `--workspace` rather than `$BUNNYFORGE_WORKSPACE`, and why there is
   no `EnvironmentVariables` block at all. The first string is the
   `bunnyforge` that has the `[mcp]` extra: `which bunnyforge` from
   the shell where `serve-mcp` already runs by hand.

        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
          "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
            <key>Label</key>
            <string>com.bunnyforge.serve-mcp</string>
            <key>ProgramArguments</key>
            <array>
                <string>/absolute/path/to/bunnyforge</string>
                <string>serve-mcp</string>
                <string>--workspace</string>
                <string>/absolute/path/to/campaign</string>
                <string>--public-host</string>
                <string>mcp.example.com</string>
                <string>--auth-key-file</string>
                <string>/Users/you/.local/state/bunnyforge/mcp-key</string>
                <string>--log-file</string>
            </array>
            <key>RunAtLoad</key>
            <true/>
            <key>KeepAlive</key>
            <dict>
                <key>SuccessfulExit</key>
                <false/>
            </dict>
            <key>ThrottleInterval</key>
            <integer>60</integer>
            <key>StandardOutPath</key>
            <string>/Users/you/Library/Logs/bunnyforge/serve-mcp.launchd.log</string>
            <key>StandardErrorPath</key>
            <string>/Users/you/Library/Logs/bunnyforge/serve-mcp.launchd.log</string>
        </dict>
        </plist>

   Two log destinations on purpose, doing different work. Bare
   `--log-file` carries the request volume to
   `~/Library/Logs/bunnyforge/mcp.log`, rotated at midnight, 14 days
   kept. The launchd log carries only what that file structurally
   cannot: the startup banner, the one-line refusals printed before
   any logging exists, and crash tracebacks. It is unrotated, but it
   receives no access lines, so it stays small.

4. **Load it:**

        launchctl load ~/Library/LaunchAgents/com.bunnyforge.serve-mcp.plist

5. **Check that it actually starts** — step 7's discipline, unchanged:

        launchctl list | grep com.bunnyforge.serve-mcp
        bunnyforge serve-mcp --check https://mcp.example.com

   A real PID in the first column and a passing check means done. A
   `-` with `78` beside it is a **refusal**: the configuration is
   wrong, restarting will not help, and the last line of
   `~/Library/Logs/bunnyforge/serve-mcp.launchd.log` names the fix — a
   bad workspace path, a key file that is missing or too open, a
   `bunnyforge` without the `[mcp]` extra. Any other nonzero status is
   a crash. `KeepAlive` restarts crashes within a minute; refusals it
   retries at most once a minute (`ThrottleInterval`), so a broken
   config surfaces here and in the log instead of spinning every five
   seconds — the loop step 7 warns about.

   After editing the plist, `launchctl unload` then `load` again.
   Step 7's two traps apply verbatim: `unload` can report
   `Input/output error` having succeeded, and `sudo` addresses the
   wrong domain entirely.

One conflict worth knowing: the agent and `scripts/mcp-session.py`
both want port 8765. While the agent is loaded, an mcp-session's
server cannot bind — `launchctl unload` the agent first when you want
the interactive route back.
````

(Convert the ```` ```` fence content as-is; the inner code blocks are
already in the doc's indented style.)

- [ ] **Step 4: Lint the plist**

Extract exactly the XML block (from `<?xml` through `</plist>`) into
the session scratchpad as `serve-mcp.plist`, unindented, and run:

```bash
plutil -lint <scratchpad>/serve-mcp.plist
```

Expected: `serve-mcp.plist: OK`. If plutil objects, fix the doc's block
to match what lints.

- [ ] **Step 5: Read the section once in place**

Re-read the full `docs/serve-mcp.md` from "Set up a named tunnel" to
"Check it before adding the connector" and confirm: numbering is
consistent, the step-7 references point at an existing step 7, and no
paragraph contradicts the flag semantics Tasks 2–3 shipped.

- [ ] **Step 6: Commit**

```bash
git add docs/serve-mcp.md
git commit -m "docs: launch agent recipe -- serve-mcp survives closing its terminal (#93)"
```

---

### Task 5: Changelog, full-suite verification, deferred systemd issue

**Files:**
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: everything shipped above.
- Produces: the branch ready for `dcltdw:opening-a-pr`.

- [ ] **Step 1: Changelog entries**

Under `## [Unreleased]`, append to the existing `### Added` list:

```markdown
- `bunnyforge serve-mcp --auth-key-file PATH` reads the GM key from a
  private file (refused unless it is mode 600-tight), so launchers
  that run no shell — launchd above all — never hold the key
  themselves. (#93)
- `docs/serve-mcp.md`: "Make the server start on its own (macOS)" — a
  launch agent recipe with a key file and a mandatory verification
  step, closing the tunnel-starts-but-server-doesn't asymmetry. (#93)
```

and to the existing `### Changed` list:

```markdown
- `serve-mcp` startup refusals (no auth, bad workspace, unwritable log
  file, missing `[mcp]` extra) exit `78` (sysexits `EX_CONFIG`) rather
  than `1`, so `launchctl list` — and any service manager that can
  branch on exit codes — can tell "fix the configuration" from a
  crash. `--check` still exits `1` on a failing report. (#93)
```

- [ ] **Step 2: Bare-shape suite**

Run the Global Constraints test command.
Expected: `OK (skipped=60)`, total 962 (950 baseline + 1 from Task 2 +
11 from Task 3; trust the OK line over this arithmetic if #94 or a
rebase moved the count).

- [ ] **Step 3: Full shape, throwaway venv (CI's mcp-suite job locally)**

```bash
cd /Users/dcltdw/Github/bunnyforge/.claude/worktrees/serve-mcp-launch-agent
python3 -m venv "$SCRATCHPAD/venv-mcp"
"$SCRATCHPAD/venv-mcp/bin/pip" install -q -e '.[mcp]'
unset PYTHONPATH
"$SCRATCHPAD/venv-mcp/bin/python3" -m unittest discover -s tests
```

(`$SCRATCHPAD` = the session's scratchpad directory; the editable
install targets THIS worktree, so no PYTHONPATH.)
Expected: `OK` with zero skips of the mcp variety (`skipped=0` or only
non-mcp skips). Both shapes green is the done-bar; report the two
summary lines verbatim.

- [ ] **Step 4: File the deferred systemd follow-up**

First confirm the label exists:
`gh label list --repo dcltdw/bunnyforge --search deferred`
(if missing, create it first:
`gh label create deferred --repo dcltdw/bunnyforge --description "Real work, deliberately parked — revisit when the need is live (not wontfix)"`).

```bash
gh issue create --repo dcltdw/bunnyforge \
  --title "serve-mcp: systemd unit recipe, the Linux half of the launch agent design" \
  --label deferred --label mcp --label documentation \
  --body "The #93 design (docs/superpowers/specs/2026-08-21-serve-mcp-launch-agent-design.md, Decision 6) shipped macOS/launchd only, because no Linux deployment exists to verify a unit against — but it made the portable choices on purpose: \`--auth-key-file\` maps onto a systemd credential or a root-owned file, and startup refusals exit 78 precisely so a unit can say \`RestartPreventExitStatus=78\` and get the refusal-vs-crash branching launchd cannot express.

Parked until there is a Linux deployment to verify on (\"verify, don't assert\"). When picked up: a \`[Service]\` recipe in docs/serve-mcp.md beside the macOS one — \`Restart=on-failure\`, \`RestartPreventExitStatus=78\`, \`RestartSec=60\`, the key via \`LoadCredential\` or an 0600 file, \`--workspace\` explicit in \`ExecStart\`.

Refs #93."
```

Add the new issue to the board (project 7, "bunnyforge split") if
`gh issue view <n> --json projectItems` shows it was not auto-added.

- [ ] **Step 5: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: changelog for the launch agent recipe and its two flags (#93)"
```

- [ ] **Step 6: Open the PR**

Use the `dcltdw:opening-a-pr` skill (mandatory per AGENTS.md). Body
must carry `Closes #93`, the verification evidence from Steps 2–3, and
note that the launchd behavior itself is doc-verified by design — the
spec's "Verification story" section says why, and the operator's first
run of the recipe (its step 5) is the live end-to-end.
