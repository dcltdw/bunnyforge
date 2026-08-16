# serve-mcp: connecting claude.ai to a campaign workspace

`bunnyforge serve-mcp` serves one campaign workspace to a remote AI agent
over MCP. Everything it serves is GM-eyes-only; the server refuses to
start without an auth mechanism.

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

A **named tunnel** (free with a Cloudflare-managed domain) is the
recommended recipe: the hostname — and therefore the connector URL in
claude.ai and the OAuth trust it anchors — survives restarts. A quick
tunnel (`cloudflared tunnel --url http://127.0.0.1:8765`) also works, but
its hostname changes every run: pass the new hostname to `--public-host`
and update the connector URL in claude.ai each time.

Local testing needs no tunnel: `--no-auth` (unauthenticated, loud
warning) or `--auth-key` with the default localhost issuer.

## Add the connector in claude.ai

Settings → Connectors → Add custom connector:

- **URL:** `https://<public-host>/mcp`
- **OAuth Client ID / Client Secret:** leave **both blank**. claude.ai
  registers itself (Dynamic Client Registration) against the server's
  built-in single-user authorization server.

On connect, your browser lands on the server's consent page; type the GM
key. Tokens refresh silently for up to 30 days before the page reappears.

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
  does not know your public hostname — issue #46 tracks the
  `--public-host` transport fix.
- **"Couldn't register with sign-in service":** the server is not
  reachable at the connector URL, or it was started `--no-auth` (no OAuth
  routes exist in that mode).
