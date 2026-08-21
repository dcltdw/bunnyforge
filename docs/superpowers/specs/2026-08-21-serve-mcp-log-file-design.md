# serve-mcp `--log-file`: access log out of the terminal, into a rotated file

**Issue:** dcltdw/bunnyforge#87
**Date:** 2026-08-21
**Status:** approved in brainstorm; this document is the validated design

## Problem

`bunnyforge serve-mcp --public-host mcp.stardragonenterprises.com` runs in a
background terminal. uvicorn installs its default logging config (nothing in
`serve_mcp.py` configures logging), so every request lands on stderr:

    INFO:     160.79.106.179:0 - "POST /mcp HTTP/1.1" 200 OK

The traffic is benign — claude.ai's own MCP connector, OAuth-authenticated —
but the lines clutter the terminal. They should leave the terminal yet still
be recorded to a file, and the file must prune itself.

## Decision: Python-side rotation (option B)

Three options were surveyed:

- **A. launchd + newsyslog(8):** native to macOS, but `/etc/newsyslog.d/`
  needs sudo, and newsyslog rotates by rename — a process holding the fd
  keeps writing to the renamed inode unless signalled to reopen. Rejected.
- **B. uvicorn `log_config` with a rotating file handler:** no sudo, no
  rename trap (the handler itself does the rollover and reopens), identical
  behavior however the process is launched, cross-platform. **Chosen.**
- **C. logrotate:** Linux-native, Homebrew-only on macOS. Rejected.

A constraint the survey missed, found during brainstorm:
`scripts/mcp-session.py` already redirects the server's stdout+stderr to
`$XDG_STATE_HOME/bunnyforge/server.log` and tails that file in its failure
diagnostics. Any design that silences stderr by default would hollow out that
script's log. This drove two choices below: the flag is **opt-in**, and the
error stream **stays on stderr** even when the flag is active.

## CLI surface

One new flag on `build_parser()`:

    --log-file [PATH]

- **Omitted** (default): behavior is today's, byte-for-byte. No `log_config`
  is passed to `uvicorn.run`; uvicorn installs its stderr default.
  `scripts/mcp-session.py` is unaffected and is not modified.
- **Bare `--log-file`** (`nargs="?"`, `const` = the default path): logs to
  the platform default —
  - macOS (`sys.platform == "darwin"`): `~/Library/Logs/bunnyforge/mcp.log`
  - elsewhere: `$XDG_STATE_HOME/bunnyforge/mcp.log`, falling back to
    `~/.local/state/bunnyforge/mcp.log` when the variable is unset or empty.
- **`--log-file PATH`**: exactly that path.

The default path is computed by a helper (`_default_log_path()`) so the
parser test can assert it without duplicating platform logic. The flag has
no interaction with `--auth-key` / `--no-auth` / `--public-host`; logging is
orthogonal to auth.

When the flag is active, `main()` prints one startup line naming the
resolved path (alongside the existing "serving …" line) so the operator
knows where the access lines went.

## Log routing

A new pure function in `serve_mcp.py`:

    _log_config(path: Path) -> dict

returns a `logging.config.dictConfig`-shaped dict (`version: 1`,
`disable_existing_loggers: False`) passed to `uvicorn.run(...,
log_config=...)`. Shape:

- **Handlers:**
  - `file`: `logging.handlers.TimedRotatingFileHandler`, `filename=path`,
    `when="midnight"`, `backupCount=14`. **Exactly one file handler,
    shared** — two rotating handlers on the same file would both attempt
    the rollover rename and collide.
  - `stderr`: `logging.StreamHandler` on `ext://sys.stderr`.
- **Formatter** (on both handlers): `%(asctime)s %(levelname)s %(message)s`.
  Timestamps are an improvement over uvicorn's timestamp-less default, and
  the format renders access records correctly because uvicorn's access line
  is carried in the record's message/args, not in formatter-specific fields.
- **Loggers:**
  - `uvicorn.access` → `[file]` only, level INFO, `propagate: False`.
  - `uvicorn.error` and `uvicorn` → `[file, stderr]`, level INFO,
    `propagate: False`.

Net effect: access noise goes only to the file; the startup banner, bind
failures, and tracebacks reach both the terminal and the file, so the file
is a complete record of the run and a crashed server still says why in the
terminal.

## Rotation and retention

`when="midnight"`, `backupCount=14`: one file per day, ~two weeks of
history, pruning done by the handler itself. At this server's traffic level
each daily file is tiny. Age-bounded retention was chosen over size-bounded
(`RotatingFileHandler`) for predictability; no tuning flags — the defaults
are the policy until a real need appears.

## Directory creation and errors

Before `uvicorn.run`, `main()` resolves the path and runs
`path.parent.mkdir(parents=True, exist_ok=True)`. Any `OSError` (unwritable
parent, a file where a directory should be, …) becomes the module's existing
error style: one line to stderr, `return 1`, no traceback.

## Testing

Everything tests at the existing seam — no test opens a socket or reaches a
real `uvicorn.run`:

- **Parser:** flag absent → `None`; bare flag → `_default_log_path()`;
  explicit path → that path.
- **`_log_config` wiring:** `uvicorn.access` routes to the file handler
  only; `uvicorn.error` routes to both; rotation params are
  `midnight`/`backupCount=14`.
- **Schema validity:** feed the dict to `logging.config.dictConfig` against
  a tmpdir path — proves the dict is well-formed where a wiring assertion
  alone would not — then close/detach the created handlers so the tmpdir
  can be removed.
- **Refusal path:** `--log-file` pointing into an uncreatable directory
  returns 1 with a one-line stderr message.
- Existing tests in `test_serve_mcp.py`, `test_mcp_auth.py`, `test_cli.py`
  are untouched.

## Documentation and changelog

- `docs/serve-mcp.md`: a short **Logging** section — the flag, the default
  path per platform, midnight/14-day rotation, and a note that
  `scripts/mcp-session.py` keeps its own `server.log` redirect and needs no
  change.
- `CHANGELOG.md`: an `Added` entry under `[Unreleased]`.

## Out of scope

- launchd / newsyslog / logrotate integration.
- A `--no-access-log` (discard entirely) escape hatch.
- Retention/rotation tuning flags.
- Any change to `scripts/mcp-session.py`.
- A config-file key: logging is an operator concern, not a campaign
  concern, so it does not belong in `campaign.toml`.
