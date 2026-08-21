# serve-mcp launch agent: the server survives closing its terminal

**Issue:** dcltdw/bunnyforge#93
**Date:** 2026-08-21
**Status:** designed autonomously per the #93 brief; this document is the
validated design pending dcltdw's review

## Problem

`docs/serve-mcp.md` step 6 gets the *tunnel* starting on its own, but the
server it routes to is still a foreground process in whatever terminal
launched it. Closing that window silently takes the MCP endpoint down and
leaves the hostname answering 502 with a healthy tunnel in front of it —
exactly how the outage after #88 started. The doc even names the asymmetry:
"Starting the tunnel does not start `serve-mcp`."

The design question the issue poses is not "how do I write a plist" but six
coupled decisions: where the GM key lives, how the workspace is named, how
the recipe is delivered, how launchd's logging interacts with `--log-file`
(#87), what `KeepAlive` should be given that `main()` legitimately exits
nonzero on refusals, and whether the scope is launchd only or launchd plus
systemd. The secret decision shapes the rest, so it comes first.

## Decision 1 — the GM key: a new `--auth-key-file` flag

`BUNNYFORGE_MCP_KEY` is the pre-shared GM key; everything served is GM-only
campaign material, and `~/Library/LaunchAgents` is not a secrets store.
Four options were surveyed:

- **A. `EnvironmentVariables` in the plist, with a caveat.** The key would
  sit in plaintext in a plist that is casually readable, shows up in
  `launchctl print`, and is the first file anyone pastes into a bug report
  when the agent misbehaves (#90's diagnosis flow is exactly "open the
  plist"). Rejected.
- **B. A mode-0600 env file the agent sources.** launchd runs no shell, so
  "sourcing" means `ProgramArguments` becomes
  `/bin/sh -c '. file && exec …'` — a quoting-sensitive shell layer inside
  a plist, which is the same class of silent argument bug #90 documents.
  Rejected.
- **C. macOS Keychain.** Sound storage, but reading it non-interactively
  means either a shell wrapper around `security(1)` (option B's problem
  again) or bunnyforge shelling out to a macOS-only tool. It also makes the
  launchd and any future systemd recipes diverge at the most
  security-sensitive step. Rejected for now; nothing below precludes
  layering it later.
- **D. A first-party `--auth-key-file PATH` flag.** The plist then carries
  only a path — the same trust class as the cloudflared config path the
  tunnel's plist already carries — and bunnyforge itself owns the safety
  checks. Shell-free `ProgramArguments`, identical semantics on any init
  system, refusals surface through `main()`'s existing one-line-and-exit
  discipline, and it is testable without launchd. **Chosen.**

(The issue sketches the name as `--auth-key-from-file`; `--auth-key-file`
says the same thing shorter and reads as the sibling of `--auth-key`.)

### Flag semantics

`--auth-key-file PATH` reads the key from `PATH` (`~` expanded), strips
surrounding whitespace (so a trailing newline from `echo` is harmless), and
then behaves exactly as if that key had been passed to `--auth-key`.
Refusals, each one line on stderr then exit (see Decision 5 for the code):

- the file is missing or unreadable;
- the file is empty after stripping;
- on POSIX, the file is group- or other-accessible
  (`stat.S_IMODE(mode) & 0o077`) — the message names the fix,
  `chmod 600`. The check is skipped on non-POSIX platforms, where those
  mode bits are fiction.

Precedence and conflicts keep today's shape (explicit flag beats
environment):

- `--auth-key` > `--auth-key-file` > `$BUNNYFORGE_MCP_KEY` — except that
  passing **both flags** is refused as ambiguous rather than silently
  ordered.
- `--auth-key-file` with `--no-auth` is refused, exactly like
  `--auth-key` with `--no-auth` today. A key file that exists but loses to
  a set `$BUNNYFORGE_MCP_KEY`? It doesn't — the file, being an explicit
  flag, wins, matching how `--auth-key` already outranks the variable.

The recommended location in the docs is
`~/.local/state/bunnyforge/mcp-key`, alongside `mcp-oauth-state.json` —
serve-mcp's secrets then live in one directory that "Resetting access"
already teaches. Any path works; the flag does not special-case it.

## Decision 2 — the workspace: `--workspace` in `ProgramArguments`

A launchd job inherits no shell profile, which is the #89 class of
surprise (`BUNNYFORGE_WORKSPACE` vs `BUNNYFORGE_MCP_WORKSPACE`). The plist
therefore names the workspace as an explicit absolute `--workspace`
argument, and the recipe's plist has **no `EnvironmentVariables` key at
all** — with both the key and the workspace in argv there is nothing left
to put there, and its absence removes the one tempting place to paste the
GM key. Everything the job needs is visible in `launchctl print`'s argv,
none of it secret.

## Decision 3 — delivery: a doc recipe with the full plist inline

- **A doc recipe** mirroring the tunnel section: complete plist inline,
  followed by a mandatory verification step. **Chosen.**
- **A template plist committed to the repo:** still needs the same five
  hand edits (bunnyforge path, workspace, hostname, key path, log dir),
  and a copy in `docs/examples/` drifts from the prose that explains it.
  Rejected.
- **A `serve-mcp --install-service` subcommand:** #90 is the cautionary
  tale about *generated* services being silently wrong — first-party
  generation could be done right, but it would need flags for all five
  machine-specific values anyway (it can discover none of them), so it
  saves only the XML syntax while adding a platform-detection and
  idempotency surface to own. Disproportionate for a one-operator project.
  Rejected; revisit only if the recipe demonstrably keeps going wrong.

The recipe is one new section in `docs/serve-mcp.md`, "Make the server
start on its own (macOS)", placed after "Set up a named tunnel (once)" so
the two autostart recipes sit together. The existing "Starting the tunnel
does not start `serve-mcp`" paragraph gains a pointer to it. #90's lesson
is encoded the same way step 7 encodes it for the tunnel: install is not
done until `launchctl list` shows a real PID **and**
`bunnyforge serve-mcp --check https://<public-host>` passes.

## Decision 4 — logging: `--log-file` and `Standard*Path` split the work

They are complementary, not rivals, because they capture different streams:

- `--log-file` (bare, so it resolves to
  `~/Library/Logs/bunnyforge/mcp.log`) carries the request volume —
  rotated at midnight, 14 days kept, self-pruning. This is what would
  otherwise bloat an unrotated launchd log.
- `StandardOutPath` and `StandardErrorPath`, both pointed at
  `~/Library/Logs/bunnyforge/serve-mcp.launchd.log`, carry what
  `--log-file` structurally cannot: `main()`'s refusal lines and the
  startup banner are `print()`s emitted before uvicorn's logging exists,
  and a crash traceback bypasses logging entirely. Without these keys a
  refusing agent is invisible — precisely #90's failure shape.

The launchd file is unrotated but effectively bounded: it receives no
access lines, only startup banners, refusals, tracebacks, and uvicorn's
error stream (which `_log_config` sends to stderr as well as the file, by
design). launchd does not create parent directories for `Standard*Path`,
so the recipe includes the `mkdir -p`.

`--log-file` appears bare and last in `ProgramArguments`; with
`nargs="?"` a following `--flag` would not be consumed either way, but
last means nobody has to know that.

## Decision 5 — restart policy: `KeepAlive` on failure, refusals exit 78

The tension: a crashed server should restart itself (an unattended
endpoint is the whole point), but `main()` legitimately exits nonzero on
refusals — no auth, unresolvable workspace, unwritable log file, missing
`[mcp]` extra — and restarting a refusal forever is the #90 loop. launchd
cannot branch on exit codes, so the design makes the loop *slow, cheap,
and diagnosable* instead of pretending it away:

- `KeepAlive` = `{SuccessfulExit: false}` with `ThrottleInterval` = `60`.
  A crash restarts within a minute; a clean shutdown (SIGTERM →
  uvicorn's graceful exit 0, or `launchctl unload`) stays down; a refusal
  retries at most once a minute, each attempt one line in the launchd log.
- **Refusals now exit 78** (`EX_CONFIG` from sysexits(3), a new
  `EXIT_CONFIG = 78` constant in `serve_mcp.py`) instead of 1. Every
  pre-serve refusal path in `main()` changes: workspace resolution, the
  auth conflicts and the no-auth refusal, the new key-file refusals, the
  unwritable log file, and the `[mcp]` install hint. `launchctl list`
  shows the last exit status, so `78` in that column says "fix the
  configuration, restarting won't help" while `1` still means a crash.
  `--check` keeps its documented 0-or-nonzero contract and continues to
  exit 1: it reports on a remote server, it does not refuse to start this
  one.

Nothing couples to the old value: `scripts/mcp-session.py` tests only
zero/nonzero, and the handful of `assertEqual(rc, 1)`-shaped tests are
updated to 78 as part of the change. The alternative — `KeepAlive: false`,
no restart ever — was rejected because it re-creates the outage class this
issue exists to close, just with "crash" substituted for "closed
terminal". Install-time verification (Decision 3) means a refusal loop can
only arise later, from config rot, and then it is visible in two places
and bounded to one process a minute.

## Decision 6 — scope: macOS/launchd now, systemd deferred deliberately

The tunnel doc's Linux coverage is one sentence; every verified deployment
of serve-mcp is the macOS one, and a systemd unit written here could not
be verified against a real system ("verify, don't assert"). launchd-only
now — but the portable decisions are made portable on purpose:
`--auth-key-file` maps directly onto a systemd credential or root-owned
file, and exit 78 is chosen so a future unit can say
`RestartPreventExitStatus=78` and get the refusal/crash branching launchd
cannot express. A follow-up issue (labelled `deferred`) records the
systemd recipe as real work parked until there is a Linux deployment to
verify it on.

## The recipe itself (shape, not final prose)

1. Put the key in a file: `mkdir -p`, write the key, `chmod 600` —
   recommended path `~/.local/state/bunnyforge/mcp-key`. Note that
   serve-mcp refuses a group/other-readable key file.
2. `mkdir -p ~/Library/Logs/bunnyforge` (launchd will not create it).
3. Write `~/Library/LaunchAgents/com.bunnyforge.serve-mcp.plist`:

   - `Label`: `com.bunnyforge.serve-mcp`
   - `ProgramArguments`: absolute path to the `bunnyforge` console script
     **from the environment that has the `[mcp]` extra** (`which
     bunnyforge` in the shell where serve-mcp already runs), then
     `serve-mcp`, `--workspace /abs/path`, `--public-host mcp.example.com`,
     `--auth-key-file /abs/path/mcp-key`, `--log-file`
   - `RunAtLoad`: true; `KeepAlive`: `{SuccessfulExit: false}`;
     `ThrottleInterval`: 60
   - `StandardOutPath` / `StandardErrorPath`: both
     `~/Library/Logs/bunnyforge/serve-mcp.launchd.log` (absolute — launchd
     does not expand `~`)
4. `launchctl load ~/Library/LaunchAgents/com.bunnyforge.serve-mcp.plist`
   (matching the tunnel section's load/unload vocabulary).
5. **Verify — do not skip** (the tunnel section's step-7 discipline):
   `launchctl list | grep bunnyforge` wants a real PID; then
   `bunnyforge serve-mcp --check https://<public-host>` from anywhere. A
   `-` with `78` means a refusal — read
   `~/Library/Logs/bunnyforge/serve-mcp.launchd.log`, which names the
   fix; `1` means a crash. After editing the plist:
   `launchctl unload` + `load` again (the existing "unload reports
   Input/output error but succeeded" trap is cross-referenced, not
   repeated).

Prose notes the recipe carries: a launch agent starts **at login, not at
boot** (same trap the tunnel section names); the plist deliberately has no
`EnvironmentVariables` (launchd inherits no shell profile — the #89 note
covers why explicitness wins); and the agent and `scripts/mcp-session.py`
both want port 8765, so unload the agent before running an mcp-session, or
the session's server will fail to bind.

## Code changes, in one place

- `serve_mcp.py`: `--auth-key-file` in `build_parser()`; a small
  `_read_key_file()` helper enforcing the semantics above; `EXIT_CONFIG =
  78` and every refusal path in `main()` switched to it. No behavior
  change for any invocation that exists today except the exit code of a
  refusal.
- `tests/test_serve_mcp.py`: new tests for the key-file flag (reads and
  strips, missing, empty, lax permissions, both-flags conflict,
  `--no-auth` conflict, flag-beats-env precedence) and the updated
  refusal-code assertions. All of these run bare — refusals happen before
  the SDK import, so no `[mcp]` extra is needed.
- `docs/serve-mcp.md`: the new section, the asymmetry-paragraph pointer,
  and a `--auth-key-file` mention where `--auth-key`/`$BUNNYFORGE_MCP_KEY`
  are introduced.
- `CHANGELOG.md`: `### Added` (the flag, the recipe) and `### Changed`
  (refusals exit 78) under `[Unreleased]`.

## Out of scope

- A systemd unit (deferred issue, Decision 6).
- Keychain integration (Decision 1C; nothing here precludes it).
- `--install-service` generation (Decision 3; revisit on recurrence).
- Any change to `scripts/mcp-session.py` — it remains the interactive,
  by-hand alternative and reads only zero/nonzero from the server.

## Verification story

Unit tests cover every new refusal and the precedence rules; `plutil
-lint` proves the doc's plist parses; the full suite runs in both CI
shapes (bare, and with the `[mcp]` extra in a throwaway venv). The live
`launchctl` behavior cannot be exercised from a worktree without mutating
`~/Library/LaunchAgents` on the working machine, so — like the tunnel
recipe in #84/#90 — the end-to-end pass happens when dcltdw runs the
recipe once, with step 5 existing precisely to make that run
self-verifying.
