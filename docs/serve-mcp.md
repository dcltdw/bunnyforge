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

## One command

`scripts/mcp-session.py` does everything above in one go: reuses a live
tunnel or starts a fresh one, waits for its hostname to reach DNS, starts
`serve-mcp` bound to that hostname, and holds until the pre-flight check
passes. It then prints the URL and key to paste.

    scripts/mcp-session.py --workspace ~/campaigns/my-campaign --verify

Set `DEFAULT_WORKSPACE` near the top of the script and it needs no
arguments at all. Other flags: `--fresh` (drop every registered client and
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
