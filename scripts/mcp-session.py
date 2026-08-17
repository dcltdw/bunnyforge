#!/usr/bin/env python3
"""
bunnyforge-mcp-session — bring up a claude.ai-ready MCP session in one command.

Starts (or reuses) a cloudflared quick tunnel, starts `bunnyforge serve-mcp`
bound to it, waits until the pre-flight check passes, and prints the exact
URL to paste into claude.ai. Optionally drives the whole OAuth flow and a
real MCP `initialize` itself, so you know the server works before claude.ai
is involved at all.

Stdlib only, so it runs on any Python. The server it launches needs the
`[mcp]` extra; point --bunnyforge at that environment's console script.

WHAT THIS CANNOT DO: add the connector to your claude.ai account. There is
no public API for that -- connectors are added through Settings in the web
UI. Everything up to that point is automated, and --verify proves the
server is genuinely working, so the manual step is reduced to one paste.

Pass --workspace, or edit DEFAULT_WORKSPACE below to your own campaign and
then run it with no arguments at all.

Usage:
    scripts/mcp-session.py --workspace ~/campaigns/my-campaign --verify
    scripts/mcp-session.py --status
    scripts/mcp-session.py --down
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Set this to your own campaign and the script needs no arguments at all.
# Left unset here because it ships for everyone; --workspace always works.
#
#   DEFAULT_WORKSPACE = str(Path.home() / "campaigns" / "my-campaign")
#
DEFAULT_WORKSPACE = None

STATE = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
SESSION_FILE = STATE / "bunnyforge" / "mcp-session.json"
TUNNEL_LOG = STATE / "bunnyforge" / "tunnel.log"
SERVER_LOG = STATE / "bunnyforge" / "server.log"
OAUTH_STATE = STATE / "bunnyforge" / "mcp-oauth-state.json"
TUNNEL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
KEY_ENV = "BUNNYFORGE_MCP_KEY"


# ── session memory ──────────────────────────────────────────────────────

def load_session() -> dict:
    try:
        return json.loads(SESSION_FILE.read_text())
    except (OSError, ValueError):
        return {}


def save_session(**fields) -> None:
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = load_session()
    data.update(fields)
    SESSION_FILE.write_text(json.dumps(data, indent=2))
    SESSION_FILE.chmod(0o600)          # it remembers the GM key


# ── HTTP ────────────────────────────────────────────────────────────────

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Return the 3xx itself instead of chasing it."""

    def redirect_request(self, *args, **kwargs):
        return None


def http(url, method="GET", body=None, headers=None, timeout=15,
         follow=True):
    """(status, headers, bytes). Never raises for an HTTP status.

    `follow=False` matters more than it looks: urlopen chases redirects by
    default, so an OAuth /authorize came back as 200 with the consent page
    and no Location header, and the code in the /consent redirect was lost
    entirely. curl does not follow by default, which is why the same
    sequence worked by hand and failed here.
    """
    data = None
    head = dict(headers or {})
    if isinstance(body, (bytes, bytearray)):
        data = bytes(body)
    elif body is not None:
        data = json.dumps(body).encode()
        head.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(url, data=data, method=method,
                                     headers={"User-Agent": "bunnyforge-session",
                                              **head})
    opener = (urllib.request.build_opener()
              if follow else urllib.request.build_opener(_NoRedirect))
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers or {}), exc.read()


def _location(headers: dict) -> str:
    """Header names are case-insensitive; dict lookups are not."""
    return next((str(v) for k, v in headers.items()
                 if k.lower() == "location"), "")


def tunnel_alive(url: str) -> bool:
    """A quick tunnel that is up answers *something* other than Cloudflare's
    own 52x/53x family, which is what it returns when the tunnel is gone."""
    if not url:
        return False
    try:
        status, _, _ = http(f"{url}/.well-known/oauth-authorization-server",
                            timeout=8)
    except OSError:
        return False
    return status < 520


# ── processes ───────────────────────────────────────────────────────────

def _resolves_public(host: str) -> bool:
    """Ask a public resolver directly, bypassing the local cache.

    Never ask the SYSTEM resolver while waiting for a brand-new tunnel
    name. macOS caches the NXDOMAIN from the first lookup -- which lands
    before Cloudflare has published the name -- and then serves that
    cached failure for minutes. Measured: a fresh hostname resolved via
    1.1.1.1 in 5.3s while getaddrinfo still failed 90s later. Polling for
    the name was itself what stopped it being found.
    """
    for resolver in ("1.1.1.1", "8.8.8.8"):
        try:
            out = subprocess.run(["dig", "+short", f"@{resolver}", host],
                                 capture_output=True, text=True,
                                 timeout=5).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            continue
        if out:
            return True
    return False


def start_tunnel(port: int) -> tuple[subprocess.Popen, str]:
    """Start a quick tunnel and wait until its hostname actually resolves.

    Output goes to a LOG FILE, never a pipe. A pipe nobody drains fills at
    64KB and blocks the child mid-write -- cloudflared then stops
    registering the tunnel and its hostname never enters DNS, which
    surfaces as `[Errno 8] nodename nor servname provided` forever. Run by
    hand it writes to a terminal, so the bug only appears under this
    script. The server gets the same treatment for the same reason.
    """
    print("starting a cloudflared quick tunnel...")
    TUNNEL_LOG.parent.mkdir(parents=True, exist_ok=True)
    log = TUNNEL_LOG.open("w")
    proc = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", f"http://127.0.0.1:{port}"],
        stdout=log, stderr=subprocess.STDOUT)

    url = ""
    deadline = time.time() + 60
    while time.time() < deadline:
        if proc.poll() is not None:
            raise SystemExit(f"cloudflared exited; see {TUNNEL_LOG}")
        found = TUNNEL_RE.search(TUNNEL_LOG.read_text(errors="replace"))
        if found:
            url = found.group(0)
            print(f"  tunnel: {url}")
            break
        time.sleep(1)
    if not url:
        raise SystemExit(f"timed out waiting for a hostname; see {TUNNEL_LOG}")

    # The banner appears before the name is in DNS; without this wait the
    # first checks fail on resolution and look like a server problem.
    host = urllib.parse.urlsplit(url).netloc
    print("  waiting for DNS...", end="", flush=True)
    for _ in range(90):
        if _resolves_public(host):
            print(" published")
            # Only now is it safe to let anything use the system resolver:
            # the first local lookup will cache a positive answer instead
            # of an NXDOMAIN that outlives the wait.
            time.sleep(2)
            return proc, url
        time.sleep(1)
    print()
    raise SystemExit(f"{host} never published; see {TUNNEL_LOG}")


def port_holder(port: int) -> tuple[int, str] | None:
    """(pid, command) of whatever is LISTENing on the port, if anything."""
    try:
        out = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN",
                              "-t"], capture_output=True, text=True).stdout
    except OSError:
        return None
    pid = next((int(line) for line in out.split() if line.isdigit()), None)
    if pid is None:
        return None
    cmd = subprocess.run(["ps", "-o", "command=", "-p", str(pid)],
                         capture_output=True, text=True).stdout.strip()
    return pid, cmd


def clear_port(port: int) -> None:
    """Stop a previous serve-mcp still holding the port.

    Without this the server dies on `[Errno 48] address already in use`,
    buried under a page of uvicorn startup noise that reads like the new
    server is fine -- and the stale one is invariably still advertising a
    tunnel hostname that died hours ago. Anything that is NOT a serve-mcp
    is left alone and reported, since that is not ours to kill.
    """
    held = port_holder(port)
    if held is None:
        return
    pid, cmd = held
    if "serve-mcp" not in cmd and "serve_mcp" not in cmd:
        raise SystemExit(f"port {port} is held by pid {pid}, which is not a "
                         f"serve-mcp:\n  {cmd}\nstop it yourself, or pass "
                         f"--port")
    print(f"stopping a previous serve-mcp on :{port} (pid {pid})")
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        raise SystemExit(f"could not stop pid {pid}: {exc}")
    for _ in range(20):
        time.sleep(0.5)
        if port_holder(port) is None:
            return
    raise SystemExit(f"pid {pid} still holds port {port}")


def start_server(bunnyforge: str, workspace: str, port: int, host: str,
                 key: str) -> subprocess.Popen:
    print(f"starting serve-mcp on :{port} as {host}...")
    env = {**os.environ, KEY_ENV: key}
    SERVER_LOG.parent.mkdir(parents=True, exist_ok=True)
    log = SERVER_LOG.open("w")           # a file, not a pipe -- see start_tunnel
    return subprocess.Popen(
        [bunnyforge, "serve-mcp", "--workspace", workspace,
         "--port", str(port), "--public-host", host],
        env=env, stdout=log, stderr=subprocess.STDOUT)


# ── the check, reusing bunnyforge's own implementation when importable ──

def _tail(path: Path, lines: int = 15) -> str:
    try:
        return "\n".join(path.read_text(errors="replace").splitlines()[-lines:])
    except OSError:
        return f"(no {path})"


def quiet_ready(url: str) -> bool:
    """The same checks, without printing -- polled once every 2s."""
    try:
        from bunnyforge.serve_mcp import preflight as run
        return all(c.ok for c in run(url))
    except ImportError:
        return preflight(url)


def preflight(url: str) -> bool:
    try:
        from bunnyforge.serve_mcp import preflight as run, report
    except ImportError:
        return _preflight_fallback(url)
    return report(run(url)) == 0


def _preflight_fallback(url: str) -> bool:
    """If bunnyforge is not importable here, shell out to it instead --
    the check is a supported command, not an internal API."""
    proc = subprocess.run([sys.argv[0].replace("bunnyforge-mcp-session.py",
                                               "") or "bunnyforge",
                           "serve-mcp", "--check", url],
                          capture_output=True, text=True)
    print(proc.stdout or proc.stderr)
    return proc.returncode == 0


# ── the end-to-end proof (what claude.ai will do) ───────────────────────

def verify(url: str, key: str) -> bool:
    """Drive the whole OAuth flow and a real MCP initialize.

    This is the step that distinguishes "the server is configured right"
    from "the server actually serves MCP to an authenticated client" --
    the two failures look identical from claude.ai's error messages.
    """
    print("\nverifying end to end (registration -> consent -> token -> MCP)")
    status, _, body = http(f"{url}/register", "POST", {
        "client_name": "bunnyforge-session-selftest",
        "redirect_uris": ["http://localhost:9999/cb"],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "client_secret_post",
    })
    if status != 201:
        print(f"  FAIL register: HTTP {status} {body[:200]!r}")
        return False
    client = json.loads(body)
    print("  ok   register")

    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    query = urllib.parse.urlencode({
        "client_id": client["client_id"], "response_type": "code",
        "redirect_uri": "http://localhost:9999/cb",
        "code_challenge": challenge, "code_challenge_method": "S256",
        "state": "selftest"})
    form_type = {"Content-Type": "application/x-www-form-urlencoded"}
    status, headers, _ = http(f"{url}/authorize?{query}", follow=False)
    location = _location(headers)
    if status != 302 or "/consent?txn=" not in location:
        print(f"  FAIL authorize: HTTP {status} location={location!r}")
        return False
    print("  ok   authorize")

    txn = location.split("txn=")[1]
    status, headers, _ = http(
        f"{url}/consent", "POST",
        urllib.parse.urlencode({"txn": txn, "key": key}).encode(),
        headers=form_type, follow=False)
    location = _location(headers)
    if "code=" not in location:
        print(f"  FAIL consent: HTTP {status} — wrong GM key?")
        return False
    print("  ok   consent")

    code = location.split("code=")[1].split("&")[0]
    status, _, body = http(
        f"{url}/token", "POST",
        urllib.parse.urlencode({
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": "http://localhost:9999/cb",
            "client_id": client["client_id"],
            "client_secret": client["client_secret"],
            "code_verifier": verifier}).encode(),
        headers=form_type)
    if status != 200:
        print(f"  FAIL token: HTTP {status} {body[:200]!r}")
        return False
    tokens = json.loads(body)
    print("  ok   token")

    # The step claude.ai's "no MCP server was found" error is about: an
    # authenticated MCP initialize against the /mcp endpoint itself.
    status, _, body = http(
        f"{url}/mcp", "POST",
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "selftest", "version": "0"}}},
        headers={"Authorization": f"Bearer {tokens['access_token']}",
                 "Accept": "application/json, text/event-stream"})
    if status >= 400:
        print(f"  FAIL initialize: HTTP {status} {body[:300]!r}")
        print("       ^ this is what claude.ai reports as 'no MCP server "
              "was found at the provided URL'")
        return False
    print(f"  ok   MCP initialize (HTTP {status})")
    return True


# ── main ────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bring up a claude.ai-ready bunnyforge MCP session.")
    parser.add_argument("--workspace", default=DEFAULT_WORKSPACE,
                        help="campaign workspace path"
                             + (" (default: %(default)s)"
                                if DEFAULT_WORKSPACE else ""))
    parser.add_argument("--bunnyforge",
                        default=str(Path.home() / ".venvs" / "bunnyforge-mcp"
                                    / "bin" / "bunnyforge"),
                        help="bunnyforge console script WITH the [mcp] extra "
                             "(default: %(default)s)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--verify", action="store_true",
                        help="also drive OAuth + a real MCP initialize")
    parser.add_argument("--fresh", action="store_true",
                        help="delete the OAuth state file first, dropping "
                             "every previously registered client and token")
    parser.add_argument("--status", action="store_true",
                        help="report the remembered tunnel and exit")
    parser.add_argument("--down", action="store_true",
                        help="stop the remembered tunnel/server and exit")
    args = parser.parse_args()

    session = load_session()

    if args.status:
        url = session.get("url", "")
        print(f"remembered tunnel: {url or '(none)'}")
        print(f"alive: {tunnel_alive(url)}")
        return 0

    if args.down:
        for name in ("tunnel_pid", "server_pid"):
            pid = session.get(name)
            if pid:
                try:
                    os.kill(pid, signal.SIGTERM)
                    print(f"stopped {name} {pid}")
                except OSError:
                    pass
        # Also catch a serve-mcp started by hand, which no remembered pid
        # knows about -- that is exactly what blocked the port last time.
        held = port_holder(args.port)
        if held and ("serve-mcp" in held[1] or "serve_mcp" in held[1]):
            os.kill(held[0], signal.SIGTERM)
            print(f"stopped untracked serve-mcp {held[0]} on :{args.port}")
        save_session(tunnel_pid=None, server_pid=None)
        return 0

    if not args.workspace:
        parser.error("--workspace is required (or set DEFAULT_WORKSPACE "
                     "near the top of this script)")
    workspace = str(Path(args.workspace).expanduser().resolve())
    if not (Path(workspace) / "campaign.toml").is_file():
        parser.error(f"{workspace} is not a campaign workspace "
                     f"(no campaign.toml) — pass --workspace")

    if args.fresh and OAUTH_STATE.exists():
        OAUTH_STATE.unlink()
        print(f"removed {OAUTH_STATE}")

    key = os.environ.get(KEY_ENV) or session.get("key")
    if not key:
        key = secrets.token_urlsafe(24)
        print(f"generated a GM key: {key}")
    save_session(key=key)

    url = session.get("url", "")
    tunnel = None
    if tunnel_alive(url):
        print(f"reusing the live tunnel: {url}")
    else:
        if url:
            print(f"remembered tunnel {url} is down")
        tunnel, url = start_tunnel(args.port)
        save_session(url=url, tunnel_pid=tunnel.pid)

    host = urllib.parse.urlsplit(url).netloc
    clear_port(args.port)
    server = start_server(args.bunnyforge, workspace, args.port, host, key)
    save_session(server_pid=server.pid)

    # Every exit past here goes through the finally, because a bare
    # `return 1` used to leak this run's tunnel -- leaving a cloudflared
    # alive with a hostname nothing was serving behind it.
    try:
        return _run_session(args, url, key, server)
    finally:
        for proc in (server, tunnel):
            if proc is not None:
                proc.terminate()
        save_session(server_pid=None)


def _run_session(args, url, key, server) -> int:
    print("waiting for the server to answer...", end="", flush=True)
    for _ in range(30):
        time.sleep(2)
        if server.poll() is not None:
            print("\nserver exited:")
            print(_tail(SERVER_LOG))
            return 1
        if quiet_ready(url):
            print(" ready")
            break
        print(".", end="", flush=True)
    else:
        print("\n\nthe server never became ready; the check says:\n")
        preflight(url)
        print(f"\nserver log tail:\n{_tail(SERVER_LOG)}")
        return 1

    if args.verify and not verify(url, key):
        return 1

    print(f"""
================================================================
  Add this in claude.ai -> Settings -> Connectors -> Add custom
  connector, leaving BOTH OAuth fields blank:

      {url}/mcp

  GM key to type on the consent page:

      {key}

  Then click ALWAYS ALLOW for the tools, and go back to your chat
  FROM THAT WINDOW. Skip it and the agent never calls a tool —
  with nothing in the server log, because nothing reaches it.

  Leave this terminal running. The hostname dies with the tunnel,
  and the connector must be re-added if it changes.
================================================================""")
    try:
        signal.pause()
    except KeyboardInterrupt:
        print("\nshutting down")
    return 0


if __name__ == "__main__":
    sys.exit(main())
