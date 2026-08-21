# serve-mcp: connecting claude.ai to a campaign workspace

`bunnyforge serve-mcp` serves one campaign workspace to a remote AI agent
over MCP. Everything it serves is GM-eyes-only; the server refuses to
start without an auth mechanism.

Doing it by hand once is worth it — the steps below are the whole
picture. After that, `scripts/mcp-session.py` runs all of them in one
command; see "One command" at the end.

## Install

    pip install 'bunnyforge[mcp]'

## Generate a GM key (once)

    python3 -c "import secrets; print(secrets.token_urlsafe(24))"

Keep it out of git. You will type it exactly once per grant, on the
consent page in your own browser — it is never stored by claude.ai.
For unattended starts, `--auth-key-file` reads it from a private
file — the launch agent recipe below leans on that.

## Run behind a tunnel

    export BUNNYFORGE_MCP_KEY=<your key>
    cloudflared tunnel run <name>           # named tunnel, stable hostname
    bunnyforge serve-mcp --public-host <name>.example.com

`--public-host` does two jobs, and behind a tunnel it is not optional:
it anchors the OAuth issuer, and it declares the hostname to the
server's DNS-rebinding protection. Omit it and every tunnelled request
is refused with `421` before it reaches authentication.

Note what the command above does *not* say: which campaign to serve.
`serve-mcp` takes `--workspace`, else `$BUNNYFORGE_WORKSPACE`, else the
nearest `campaign.toml` at or above the current directory — so run from
inside the campaign, or name it. **`$BUNNYFORGE_MCP_WORKSPACE` is a
different variable**, read only by `scripts/mcp-session.py` (below);
setting it does nothing for `serve-mcp` itself, which then refuses to
start unless you happen to be standing in a campaign folder.

A **named tunnel** (free with a Cloudflare-managed domain) is the
recommended recipe: the hostname — and therefore the connector URL in
claude.ai and the OAuth trust it anchors — survives restarts. Creating
one is six commands, once: see the next section. A quick tunnel
(`cloudflared tunnel --url http://127.0.0.1:8765`) also works and needs
no domain, but its hostname changes every run: pass the new hostname to
`--public-host` and update the connector URL in claude.ai each time.

Local testing needs no tunnel: `--no-auth` (unauthenticated, loud
warning) or `--auth-key` with the default localhost issuer.

## Set up a named tunnel (once)

Needs a domain whose nameservers are Cloudflare's. Everything below is
free, and once it is done the hostname is permanent.

1. **Authorise `cloudflared` against your zone.**

        cloudflared tunnel login

   Opens a browser, asks which zone, and writes
   `~/.cloudflared/cert.pem`. That certificate is what lets the next two
   commands create tunnels and edit DNS on your account — treat it as a
   credential.

2. **Create the tunnel.**

        cloudflared tunnel create bunnyforge-mcp

   Prints a UUID and writes `~/.cloudflared/<UUID>.json`. The tunnel
   exists at this point but routes nothing and runs nowhere.

3. **Point a hostname at it.**

        cloudflared tunnel route dns bunnyforge-mcp mcp.example.com

   Creates a proxied `CNAME` to `<UUID>.cfargotunnel.com`. This is the
   step that needs Cloudflare as your DNS authority, and it is why the
   hostname is permanent: the record belongs to the tunnel rather than
   to a session. If the record already exists and points elsewhere, the
   command refuses rather than clobbering it.

4. **Say where traffic goes** — `~/.cloudflared/config.yml`:

        tunnel: bunnyforge-mcp
        credentials-file: /Users/you/.cloudflared/<UUID>.json

        ingress:
          - hostname: mcp.example.com
            service: http://127.0.0.1:8765
          - service: http_status:404

   `8765` is `serve-mcp`'s default port; move one and move the other.
   The trailing `http_status:404` is the catch-all rule, and it is
   required — cloudflared refuses to start without one. Give
   `credentials-file` an absolute path: the launch agent in step 6 does
   not expand `~`.

5. **Run it by hand once,** and prove the whole path before trusting it:

        cloudflared tunnel run bunnyforge-mcp
        bunnyforge serve-mcp --public-host mcp.example.com
        bunnyforge serve-mcp --check https://mcp.example.com

6. **Make the tunnel start on its own.**

        cloudflared service install

   On macOS this is a *user launch agent* and takes no `sudo`; it reads
   the `config.yml` from step 4. On Linux the same command installs a
   system service and does need `sudo`. Note what a launch agent does
   not do: it starts **at login, not at boot**, so a machine that
   reboots with nobody logging in comes back without a tunnel.

7. **Check that it actually starts.** Do not skip this — the way it
   fails is silent.

        launchctl list | grep cloudflared
        cloudflared tunnel list

   You want a real PID in the first column and a populated CONNECTIONS
   column. A `-` with status `1` means the agent is failing: cloudflared
   2026.8.2 has been seen generating a plist whose `ProgramArguments`
   is the bare binary with no subcommand, which prints usage, exits 1,
   and — with the `KeepAlive` the same command generates — retries
   every five seconds forever.
   `~/Library/Logs/com.cloudflare.cloudflared.err.log` says so:
   ``use `cloudflared tunnel run` to start tunnel <name>``.

   The repair is to supply the arguments yourself, in
   `~/Library/LaunchAgents/com.cloudflare.cloudflared.plist`:

        <key>ProgramArguments</key>
        <array>
            <string>/usr/local/bin/cloudflared</string>
            <string>--config</string>
            <string>/absolute/path/to/.cloudflared/config.yml</string>
            <string>--no-autoupdate</string>
            <string>tunnel</string>
            <string>run</string>
            <string>bunnyforge-mcp</string>
        </array>

   Then `launchctl unload` the plist and `launchctl load` it again, and
   re-run the two checks. Two traps on the way: `unload` can report
   `Input/output error` having nonetheless succeeded — confirm with
   `launchctl print gui/$(id -u)/com.cloudflare.cloudflared`, which
   should then say the service is not found — and `sudo` is wrong here,
   because it addresses the system domain and cannot see a user launch
   agent.

Two things this deliberately does not do.

**Starting the tunnel does not start `serve-mcp`.** The tunnel is the
route; the server is still yours to run. Until it is up the hostname
answers `502`, which is the correct answer rather than a fault. The
next section closes the asymmetry.

**Do not put Cloudflare Access in front of the hostname.** The instinct
is a good one — everything served is GM-only — but the mechanism is
wrong: claude.ai has to complete this server's own OAuth flow against
that URL, and it cannot log through an Access challenge to get there.
The authentication is already present in the GM key and the OAuth
grant, without which the server refuses to start.

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
   OAuth state file that "Resetting access" already covers. The
   `umask` matters here: a bare redirect creates the file under your
   shell's default mode (often `644`) and it sits world-readable until
   `chmod` runs a line later — exactly the condition `--auth-key-file`
   refuses.

        mkdir -p ~/.local/state/bunnyforge
        (umask 077; printf '%s\n' '<your key>' > ~/.local/state/bunnyforge/mcp-key)
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
   cannot: the one-line refusals printed before any logging exists,
   and crash tracebacks. It is unrotated, but it receives no access
   lines, so it stays small. The startup banner itself is not among
   these — it is a plain `print()` to stdout, launchd redirects
   stdout to this same file, and a file (unlike a terminal) makes
   Python block-buffer it; the process then blocks inside
   `uvicorn.run()` indefinitely, so that buffer never flushes and the
   banner never lands here at all. Uvicorn's own `Uvicorn running
   on …` line does — it goes to stderr, which is line-buffered — and
   is the signal a healthy start actually leaves behind.

4. **Quit any by-hand `serve-mcp` first, then load it.** The agent
   binds the same port 8765; while a hand-run server — from "Run
   behind a tunnel," or from proving the path by hand when setting up
   the tunnel — still holds it, the agent's own start fails, and the
   next step's `--check` still *passes*, because the hand-run server
   is the one answering it.

        launchctl load ~/Library/LaunchAgents/com.bunnyforge.serve-mcp.plist

5. **Check that it actually starts** — step 7's discipline, unchanged:

        launchctl list | grep com.bunnyforge.serve-mcp
        bunnyforge serve-mcp --check https://mcp.example.com

   A real PID in the first column and a passing check means done. A
   `-` with `78` beside it is a **refusal**: the configuration is
   wrong, restarting will not help, and
   `~/Library/Logs/bunnyforge/serve-mcp.launchd.log` names the fix — a
   bad workspace path, a key file that is missing or too open, a
   `bunnyforge` without the `[mcp]` extra. Any other nonzero status is
   usually a crash, but the likeliest one here is not: something else
   — most often a hand-run `serve-mcp` you forgot to quit — already
   holds port 8765, and the agent exits 1 trying to bind it.
   `KeepAlive` restarts crashes within a minute; refusals it retries
   at most once a minute (`ThrottleInterval`), so a broken config
   surfaces here and in the log instead of spinning every five
   seconds — the loop step 7 warns about.

   After editing the plist, `launchctl unload` then `load` again.
   Step 7's two traps apply verbatim: `unload` can report
   `Input/output error` having succeeded, and `sudo` addresses the
   wrong domain entirely.

One conflict worth knowing, and it is sharper than it looks: the
agent and `scripts/mcp-session.py` both default to port 8765. The
mcp-session does not politely fail to bind — it stops whatever
`serve-mcp` is holding the port, which is your agent's server, and
says so in one line. Worse, that stop is a SIGTERM, so the exit is a
clean `0`, and `KeepAlive` is `{SuccessfulExit: false}` precisely so
clean exits stay down. Your agent is then off with nothing in the
launchd log to say why — a graceful shutdown is not a refusal.

Give the mcp-session its own port instead, which `--port` passes to
both the quick tunnel and the server:

    scripts/mcp-session.py --port 8766 --verify

That leaves the agent untouched. If you would rather have the port
back, `launchctl unload` the agent first — deliberate, and equally
fine. To restore an agent an mcp-session already stopped:

    launchctl kickstart -k gui/$(id -u)/com.bunnyforge.serve-mcp

## Check it before adding the connector

With the server and the tunnel both running, from anywhere:

    bunnyforge serve-mcp --check https://<public-host>

It probes the public URL the way a connector will, reports one line per
finding, and exits non-zero if anything is wrong. It needs no workspace
and no `[mcp]` extra — this is plain HTTP, so it runs from your ordinary
Python while the server runs in whatever environment has the SDK.

Worth doing first: a connector that cannot connect gives you one opaque
error in the browser, and it looks the same whether the tunnel is not
routing, `--public-host` does not match the hostname, the advertised OAuth
issuer points at `127.0.0.1`, or the server was started `--no-auth`. The
check separates those from the one cause worth your attention.

## Add the connector in claude.ai

Settings → Connectors → Add custom connector:

- **URL:** `https://<public-host>/mcp`
- **OAuth Client ID / Client Secret:** leave **both blank**. claude.ai
  registers itself (Dynamic Client Registration) against the server's
  built-in single-user authorization server.

On connect, your browser lands on the server's consent page; type the GM
key. Only do that on a consent page you reached by clicking Connect in
claude.ai yourself — never one that arrived by link from someone else, since
anyone who learns your public hostname can register their own client and
generate a working-looking consent link. Refresh tokens rotate and each new
one gets a fresh 30-day TTL, so silent refresh continues indefinitely as
long as the connector is used at least once a month; the consent page
reappears only after 30 days of disuse.

### Then grant the tools — adding the connector is not the last step

Once it is connected, claude.ai still asks before letting the agent call
anything. In the connector's window, click **Always Allow** for its
tools, and then **return to your chat from that window**. Going back some
other way — a new tab, or the chat you already had open — did not carry
the grant through when this was last tested.

Worth knowing because the symptom is silent: the server is running,
`--check` says ready, the connector shows as added, and the agent simply
never calls a tool. Nothing appears in the server log either, because
nothing reaches it. If that is what you are seeing, this is the step you
are missing.

## What the agent can do

**Read canon:** `campaign_overview`, `list_entities`, `read_entity`,
`search`, `generate_names`. Workspace doctrine (`style-guide.md`,
`situation-design.md`, `AGENTS.md`, `campaign-doctrine.md`) is served as
MCP *resources* — tell the agent to load them before it writes anything
for this campaign. `campaign-doctrine.md` carries the rules specific to
this campaign, and overrides `AGENTS.md` where the two disagree; a
workspace that predates it simply serves the other three.

**Write drafts:**

| tool | writes to |
|---|---|
| `save_draft(section, name, content, subdir=None)` | `<drafts_dir>/<section>/[<subdir>/]<slug>.md` — new content; names are slugged to kebab-case; never overwrites |
| `propose_revision(path, content)` | `<drafts_dir>/<path>`, mirroring the canonical path, so you review it as a diff; one pending proposal per file |
| `update_draft(path, content)` | an existing draft — the one deliberate overwrite door, for iterating across sessions |

All of it lands in the agents' drafts directory (`drafts_dir`, default
`_AgentDrafts`) and goes no further. That directory is always excluded
from the canon read tools — whatever `exclude_dirs` says — so drafts stay
invisible to every other bunnyforge command until you promote them.
**In the default configuration the agent cannot alter canon at all** —
promotion is manual and yours, done by hand outside any tool, unless you
start the server with `--allow-direct-edits`.

**Read drafts back:** `list_drafts()` gives every pending draft with its
kind (`new` or `revision`), title, summary, and — for revisions — whether
canon changed underneath the proposal (`stale`). `read_draft(path)`
returns one in full. They exist so the agent picks up its own earlier
work and merges rather than re-writing; a `_`- or `.`-prefixed
subdirectory (say, `_AgentDrafts/_Rejected/`, if you use
rejection-by-moving) is never listed or read, so rejected material
stays rejected.
`campaign_overview`'s `drafts_pending` count is the discovery hook for
this — it tells the agent there is earlier work worth resuming before it
calls `list_drafts()`.

**The inbound queue — read only when you ask:** `_ExtractInbound/`
(`inbound_dir`, also always excluded from the canon read tools regardless
of `exclude_dirs`) is yours: material you authored elsewhere, awaiting
extraction. `list_inbound()` lists every live file — all formats, each
marked `readable` or not — and `read_inbound(path)` returns text formats
(`.md`, `.txt`, `.html`, `.htm`; anything else is listed but refused
with a convert-it hint, and undecodable bytes are replaced rather than
crashing). Both tools' descriptions carry your AGENTS.md contract: the
agent calls them **only when you ask it to extract**. It learns the
queue is non-empty from `campaign_overview`'s `inbound_pending` count —
which permits noticing and offering, never unbidden reading.
`_ExtractInbound/_Done/` and any other `_`- or `.`-prefixed area are
invisible to both tools, exactly like `_Ignore/`.

**Write back, into canon — only if you ask for it:**

    bunnyforge serve-mcp --allow-direct-edits ...

registers two more tools. `write_entity(path, content)` edits a
canonical file in place and commits each edit with a
`serve-mcp: edit <path>` message. `promote_draft(path)` moves a draft
you have just approved in chat to its canonical location (derived from
the draft path — slugged drafts mirror canon) and commits it as
`serve-mcp: promote <path>`; a revision whose base no longer matches
canon is refused, never silently applied over your interim edits.
Promotion deliberately does not touch `compendium.md` or
`front-burner.md` — index updates flow through `propose_revision` as
ever. Both tools refuse outside a git repository: without history there
is no review and no undo, and that is the only thing that makes
changing canon defensible. It is a per-run flag rather than a config
key on purpose — trading the review boundary for git history should be
a decision you make when starting the server, not a setting that
quietly persists.

Publishing is structurally absent in every mode: no tool here can reach
`_Export/` or the wiki, so a remote agent cannot leak GM-only material to
players even by accident.

## Resetting access

Delete the token state file and restart the server (as a launch agent:
`launchctl kickstart -k gui/$(id -u)/com.bunnyforge.serve-mcp`, or
unload then load):

    rm ~/.local/state/bunnyforge/mcp-oauth-state.json

(`$XDG_STATE_HOME/bunnyforge/mcp-oauth-state.json` if you set
`XDG_STATE_HOME`.) Every issued token dies with it; claude.ai will run
the consent flow again. Changing the GM key invalidates future grants
but not already-issued tokens — delete the state file for that.

## Logging

By default uvicorn writes every request to the terminal — run in a
background terminal, that clutters it with access lines. `--log-file`
moves them to a self-pruning file instead:

    bunnyforge serve-mcp --public-host mcp.example.com --log-file

With no value the log goes to `~/Library/Logs/bunnyforge/mcp.log` on
macOS and `$XDG_STATE_HOME/bunnyforge/mcp.log` (default
`~/.local/state/bunnyforge/mcp.log`) elsewhere; pass a path to choose.
The resolved path is printed at startup. The file rotates at midnight
and 14 rotated days are kept alongside the live one — the server
prunes its own logs, nothing else to configure. If the file can't be
written, `serve-mcp` refuses with one line and exits 78 (`EX_CONFIG`)
rather than starting up and failing later.

Access lines go only to the file. Errors — the startup banner, bind
failures, tracebacks — still reach stderr as well, so a crashed server
says why in the terminal and the file keeps the same errors alongside
the access lines.

`scripts/mcp-session.py` already captures the whole stdout/stderr stream
to its own `server.log`; it needs no flag and is unchanged.

## Troubleshooting

- **401 from `/mcp`:** no or expired token — reconnect from claude.ai.
- **502 from the public hostname:** the tunnel is up and the server is
  not, or the server is on a port the `ingress` rule does not name. Start
  `serve-mcp`; check the port in `~/.cloudflared/config.yml` matches.
  Running it as a launch agent instead? Don't start it by hand — see
  "Make the server start on its own" above: `launchctl list`, a `78`
  exit, and the launchd log are the first three things to check.
- **421 Invalid Host header through a tunnel:** DNS-rebinding protection
  does not know your public hostname. Pass `--public-host <hostname>` —
  the same hostname the tunnel serves, with no scheme and no port. The
  protection stays on and allows exactly that host, so a mismatch here
  still shows as 421 rather than opening the server to any `Host`.
- **"Couldn't register with sign-in service":** the server is not
  reachable at the connector URL, or it was started `--no-auth` (no OAuth
  routes exist in that mode).
- **The connector is added, but the agent never calls a tool** — and the
  server log shows nothing arriving: the tools have not been granted. See
  "Then grant the tools" above.

## One command

`scripts/mcp-session.py` does everything above in one go: reuses a live
tunnel or starts a fresh one, waits for its hostname to reach DNS, starts
`serve-mcp` bound to that hostname, and holds until the pre-flight check
passes. It then prints the URL and key to paste.

    scripts/mcp-session.py --workspace ~/campaigns/my-campaign --verify

Export `BUNNYFORGE_MCP_WORKSPACE` from your shell profile and it needs no
arguments at all — the workspace comes from `--workspace`, else that
variable, else the `DEFAULT_WORKSPACE` constant near the top of the
script. Prefer the variable: it survives `git pull` without leaving a
local edit in `git status` forever. This variable belongs to *this
script only*; `bunnyforge serve-mcp` run directly does not read it and
wants `$BUNNYFORGE_WORKSPACE` instead. Setting both, to the same
path, is the arrangement that behaves the way you expect from either
entry point. Other flags: `--fresh` (drop every registered client and
token first), `--status`, `--down`, `--port`, `--bunnyforge` (the console
script that has the `[mcp]` extra, if it is not on your PATH).

`--verify` is the part worth knowing about. It drives the entire OAuth
sequence itself — register, authorize, consent with your key, token — and
finishes with a real authenticated MCP `initialize`. That last step is
what claude.ai reports as *"no MCP server was found at the provided URL"*,
and it is indistinguishable from three other failures until something
tries it. If `--verify` passes and the connector still refuses, the
problem is not on this side.

The script is stdlib-only and lives in the repository rather than the
package, so `pip install bunnyforge` does not bring it; copy it out if you
want it on your PATH. It shells out to `cloudflared`, which quick tunnels
need anyway.

What it cannot do is add the connector to your claude.ai account — there
is no public API for that, so the final paste stays manual.
