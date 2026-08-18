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

## Run behind a tunnel

    export BUNNYFORGE_MCP_KEY=<your key>
    cloudflared tunnel run <name>           # named tunnel, stable hostname
    bunnyforge serve-mcp --public-host <name>.example.com

`--public-host` does two jobs, and behind a tunnel it is not optional:
it anchors the OAuth issuer, and it declares the hostname to the
server's DNS-rebinding protection. Omit it and every tunnelled request
is refused with `421` before it reaches authentication.

A **named tunnel** (free with a Cloudflare-managed domain) is the
recommended recipe: the hostname — and therefore the connector URL in
claude.ai and the OAuth trust it anchors — survives restarts. A quick
tunnel (`cloudflared tunnel --url http://127.0.0.1:8765`) also works, but
its hostname changes every run: pass the new hostname to `--public-host`
and update the connector URL in claude.ai each time.

Local testing needs no tunnel: `--no-auth` (unauthenticated, loud
warning) or `--auth-key` with the default localhost issuer.

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
`situation-design.md`, `AGENTS.md`) is served as MCP *resources* — tell
the agent to load them before it writes anything for this campaign.

**Write back, into staging:**

| tool | writes to |
|---|---|
| `save_draft(section, name, content)` | `<staging_dir>/<section>/<name>.md` — new content only, never overwrites |
| `propose_revision(path, content)` | `<staging_dir>/<path>`, mirroring the canonical path, so you review it as a diff |

Both land in the workspace's staging directory (`staging_dir`, default
`_ExtractInbound`) and go no further. That directory is one of
`exclude_dirs`, so staged material stays invisible to the canon read tools
above and to every other bunnyforge command until you promote it by hand —
it flows through whatever extraction workflow your `AGENTS.md` already
defines. **In the default configuration the agent cannot alter canon at
all.** The server stages; deciding what becomes canon stays yours.

**Read back its own staging:** `list_staged()` gives every staged file with
its kind (`draft` or `revision`); `read_staged(path)` returns one in full.
They are the one deliberate window into the staging directory, and they say
so — their tool descriptions tell the agent the material is unreviewed and
not canon. They exist so it can pick up its own drafts from an earlier
session and merge them rather than write them again; without them it could
write into staging and never see the result, not even its own work. They
reach nothing else: a canonical path handed to `read_staged` is refused.
Promotion is unchanged — still manual, still yours.

**Write back, into canon — only if you ask for it:**

    bunnyforge serve-mcp --allow-direct-edits ...

registers a third tool, `write_entity(path, content)`, which edits a
canonical file in place and commits each edit with a
`serve-mcp: edit <path>` message. It refuses outside a git repository:
without history there is no review and no undo, and that is the only
thing that makes editing canon defensible. It is a per-run flag rather
than a config key on purpose — trading the staging boundary for git
history should be a decision you make when starting the server, not a
setting that quietly persists.

Publishing is structurally absent in every mode: no tool here can reach
`Export/` or the wiki, so a remote agent cannot leak GM-only material to
players even by accident.

## Resetting access

Delete the token state file and restart the server:

    rm ~/.local/state/bunnyforge/mcp-oauth-state.json

(`$XDG_STATE_HOME/bunnyforge/mcp-oauth-state.json` if you set
`XDG_STATE_HOME`.) Every issued token dies with it; claude.ai will run
the consent flow again. Changing the GM key invalidates future grants
but not already-issued tokens — delete the state file for that.

## Troubleshooting

- **401 from `/mcp`:** no or expired token — reconnect from claude.ai.
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
local edit in `git status` forever. Other flags: `--fresh` (drop every registered client and
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
