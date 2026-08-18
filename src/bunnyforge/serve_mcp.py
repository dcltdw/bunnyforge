#!/usr/bin/env python3
"""
serve_mcp.py — `bunnyforge serve-mcp`: serve one campaign workspace to a
remote AI agent over MCP, as a claude.ai custom connector.

Design doc: docs/superpowers/specs/2026-08-16-serve-mcp-design.md.

The `mcp` SDK is this package's only third-party dependency and it is
optional (`pip install 'bunnyforge[mcp]'`), so it is imported only INSIDE
function bodies. cli.py imports every subcommand module unconditionally: a
bare Python must be able to import this one, print its --help, and get a
friendly install hint, with no other subcommand affected.

Everything served here is GM-eyes-only, so auth is default-deny: no GM key
and no explicit --no-auth means the server refuses to start. Auth itself is
delegated to the SDK (design: docs/superpowers/specs/
2026-08-16-serve-mcp-oauth-design.md): bunnyforge runs the smallest OAuth
authorization server that satisfies claude.ai's connector — SDK handlers
for registration, authorize, and token; bunnyforge owns one decision, a
consent page checking a pre-shared GM key (_mcp_auth.py).

Publishing is structurally absent, not merely forbidden: no tool here
touches _Export/ or the wiki, so a remote agent cannot leak GM material to
players even by accident.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import NamedTuple

from bunnyforge import _config
from bunnyforge._config import ConfigError, WorkspaceError
from bunnyforge._store import StoreError, WorkspaceStore

KEY_ENV = "BUNNYFORGE_MCP_KEY"

# Workspace doctrine, offered as MCP resources so a fresh conversation can
# load the house rules before it writes anything. Absent files are simply
# not listed -- which is also what makes campaign-doctrine.md safe to add
# here: a workspace scaffolded before the doctrine split does not have it,
# and gets exactly the three resources it got before.
DOCTRINE_FILES = ("style-guide.md", "situation-design.md", "AGENTS.md",
                  "campaign-doctrine.md")

_INSTALL_HINT = ("serve-mcp needs its optional dependencies:\n"
                 "  pip install 'bunnyforge[mcp]'")


def build_server(store: WorkspaceStore, *, allow_direct_edits: bool = False,
                 oauth=None):
    """Assemble the MCP server over one workspace store.

    Imports the SDK, so a caller without the extra gets ModuleNotFoundError;
    main() translates that into the install hint.

    With `oauth` (a SingleUserOAuthProvider), the SDK mounts the OAuth
    bootstrap routes publicly and guards /mcp — passing the provider alone
    is deliberate: MCPServer refuses a provider AND a token_verifier, and
    wraps the provider in its own ProviderTokenVerifier. With oauth=None
    the app is unauthenticated (--no-auth semantics).

    Tool docstrings are not decoration — they are what the remote agent reads
    to decide whether to call a tool, so they say when to use it, not merely
    what it does.
    """
    from mcp.server import MCPServer

    if oauth is None:
        server = MCPServer("bunnyforge")
    else:
        from mcp.server.auth.settings import (AuthSettings,
                                              ClientRegistrationOptions)
        from bunnyforge._mcp_auth import consent_endpoint

        server = MCPServer(
            "bunnyforge",
            auth_server_provider=oauth,
            auth=AuthSettings(
                issuer_url=oauth.issuer_url,
                resource_server_url=f"{oauth.issuer_url}/mcp",
                client_registration_options=ClientRegistrationOptions(
                    enabled=True),
            ),
        )
        server.custom_route("/consent", methods=["GET", "POST"])(
            consent_endpoint(oauth, store.ws.config.name))

    @server.tool()
    def campaign_overview() -> dict:
        """Get your bearings in one call: the campaign's name, each section
        with how many entities it holds, the current front-burner and
        open-questions documents, and two counts — drafts_pending (your
        own unpromoted drafts; list_drafts to resume them) and
        inbound_pending (files in the GM's inbound queue). If
        inbound_pending is non-zero you may mention it and offer to
        extract; do not list or read the queue unless the GM asks. Call
        this before anything else."""
        return store.overview()

    @server.tool()
    def list_entities(section: str) -> list[dict]:
        """List one section's files with their titles and one-line
        summaries. Use it to see what already exists before inventing
        something new."""
        return store.list_entities(section)

    @server.tool()
    def read_entity(path: str) -> str:
        """Read one workspace file in full, front matter included. Paths
        come from list_entities or search."""
        return store.read_entity(path)

    @server.tool()
    def search(query: str, section: str | None = None) -> list[dict]:
        """Search the workspace for a phrase, returning each file that
        matches and the text around the match. Use it to check what has
        already been established about a name, place, or idea."""
        return store.search(query, section)

    @server.tool()
    def generate_names(culture: str, count: int = 10) -> dict:
        """Generate person and place names appropriate to one of this
        setting's cultures. Call campaign_overview or read a Setting file
        first if you are unsure which cultures exist."""
        return store.generate_names(culture, count)

    @server.tool()
    def save_draft(section: str, name: str, content: str,
                   subdir: str | None = None) -> str:
        """Draft NEW content (a full markdown file, front matter included)
        into your drafts directory for the GM to review and promote. The
        name is slugged to kebab-case (put the display title in front
        matter); subdir nests one level, e.g. section="Briefs",
        subdir="session-015". Never overwrites — revise existing drafts
        with update_draft. Returns the draft's path."""
        return store.save_draft(section, name, content, subdir)

    @server.tool()
    def propose_revision(path: str, content: str) -> str:
        """Propose a full-file revision of an EXISTING canonical file, as
        a shadow copy in your drafts directory; the GM reviews it as a
        diff. One pending proposal per file: if one exists, read_draft it,
        merge, and update_draft instead. Returns the draft's path."""
        return store.propose_revision(path, content)

    @server.tool()
    def update_draft(path: str, content: str) -> str:
        """Overwrite one of your existing drafts with revised content —
        the deliberate way to iterate on a draft across sessions.
        read_draft it first and merge; updating a revision shadow also
        re-baselines it against current canon. Paths come from
        list_drafts."""
        return store.update_draft(path, content)

    @server.tool()
    def list_drafts() -> list[dict]:
        """List your own unpromoted drafts from this and earlier sessions:
        path, kind ("new" content or a "revision" of an existing file),
        title and summary, and for revisions whether canon has changed
        underneath them (stale). Nothing here is canon — it is your
        unreviewed work awaiting the GM. Pick a draft up and merge rather
        than writing it again."""
        return store.list_drafts()

    @server.tool()
    def read_draft(path: str) -> str:
        """Read one of your pending drafts in full. Paths come from
        list_drafts. Draft material is UNREVIEWED and not canon — do not
        treat it as established fact. For canonical files, use
        read_entity."""
        return store.read_draft(path)

    @server.tool()
    def list_inbound() -> list[dict]:
        """The GM's inbound queue: material the GM authored elsewhere,
        awaiting extraction into proper entity files. Call this only when
        the GM asks you to extract — do not act on the queue unbidden.
        (campaign_overview's inbound_pending count is how you may notice
        it is non-empty and offer.) Lists every file with whether
        read_inbound can return it. Nothing here is canon."""
        return store.list_inbound()

    @server.tool()
    def read_inbound(path: str) -> str:
        """Read one file from the GM's inbound queue, only when the GM
        asks you to extract. Paths come from list_inbound. The material
        is unreviewed source, not canon — extract it into drafts, show
        the GM, and confirm before anything else happens with it."""
        return store.read_inbound(path)

    if allow_direct_edits:
        @server.tool()
        def write_entity(path: str, content: str) -> str:
            """Edit a canonical workspace file in place. Each edit is
            auto-committed to git. Available only because this server was
            started with --allow-direct-edits."""
            return store.write_entity(path, content)

        @server.tool()
        def promote_draft(path: str) -> str:
            """Move one draft the GM has just approved in this chat to its
            canonical location (derived from the draft path) and commit
            it. Only call this after the GM's explicit approval of that
            specific draft. A stale revision is refused — merge with
            update_draft first. Available only because this server was
            started with --allow-direct-edits."""
            return store.promote_draft(path)

    def _reader(path):
        def read() -> str:
            return path.read_text(encoding="utf-8")
        return read

    for filename in DOCTRINE_FILES:
        path = store.ws.root / filename
        if path.is_file():
            server.resource(
                f"bunnyforge://doctrine/{filename}",
                name=filename,
                description=f"Workspace doctrine: {filename}. Read this "
                            "before writing content for this campaign.",
            )(_reader(path))

    return server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bunnyforge serve-mcp",
        description="Serve this workspace to a remote AI agent over MCP.")
    parser.add_argument("--workspace",
                        help="path to the campaign workspace")
    parser.add_argument("--host", default="127.0.0.1",
                        help="bind address (default: %(default)s; expose it "
                             "through a tunnel, not by binding wider)")
    parser.add_argument("--port", type=int, default=8765,
                        help="bind port (default: %(default)s)")
    parser.add_argument("--auth-key",
                        help="pre-shared GM key typed on the OAuth consent "
                             f"page, or set {KEY_ENV}; required unless "
                             "--no-auth")
    parser.add_argument("--public-host",
                        help="public hostname the tunnel serves this host "
                             "as; the OAuth issuer becomes https://HOST "
                             "(default: the local bind address)")
    parser.add_argument("--no-auth", action="store_true",
                        help="serve with no authentication — local testing "
                             "only; everything served is GM-only material")
    parser.add_argument("--allow-direct-edits", action="store_true",
                        help="also expose write_entity, which edits "
                             "canonical files in place and commits each edit")
    parser.add_argument("--check", metavar="URL",
                        help="do not serve: probe an already-running "
                             "server at URL (e.g. https://your.tunnel.host) "
                             "and report whether it is ready for a "
                             "claude.ai connector")
    return parser


class Check(NamedTuple):
    ok: bool
    label: str
    detail: str      # on failure, what to DO about it -- not the symptom


PROTECTED_PATH = "/.well-known/oauth-protected-resource/mcp"
METADATA_PATH = "/.well-known/oauth-authorization-server"


def _probe(url: str, method: str = "GET"):
    """One HTTP request, returning (status, headers, body).

    Stdlib only and no `mcp` extra: this is plain HTTP, so the check runs
    from an ordinary interpreter while the server runs in whatever venv
    has the SDK. Injected everywhere so no test opens a socket.
    """
    import urllib.error
    import urllib.request
    request = urllib.request.Request(
        url, method=method, headers={"User-Agent": "bunnyforge"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as exc:
        # A 401 or 421 is an answer, not a failure -- it is most of what
        # this check reads.
        return exc.code, dict(exc.headers or {}), exc.read()


def _header(headers, name: str) -> str:
    """Case-insensitive header lookup.

    HTTP header names are case-insensitive and uvicorn sends them
    lowercased, but urllib hands back an email.message.Message whose
    case-insensitivity is lost the moment it becomes a plain dict. Looking
    up the RFC's casing therefore missed the real header and told a
    correctly configured server it was broken -- caught by smoking the
    live probe, not by the tests, which had used the RFC casing too.
    """
    wanted = name.lower()
    for key, value in (headers or {}).items():
        if key.lower() == wanted:
            return str(value)
    return ""


def preflight(base_url: str, probe=_probe) -> list[Check]:
    """Probe a running server the way a connector will, in that order.

    Every failure names the fix rather than the symptom: the value here is
    entirely diagnostic, and a check that only says "failed" leaves the
    operator exactly where they started -- one browser error covering four
    unrelated causes (#51).
    """
    import json as _json
    base = base_url.rstrip("/").removesuffix("/mcp")
    checks: list[Check] = []

    def get(path, method="GET"):
        return probe(f"{base}{path}", method)

    try:
        status, _, _ = get(PROTECTED_PATH)
    except OSError as exc:
        return [Check(False, "reachable",
                      f"could not reach {base} ({exc}) — is the tunnel "
                      f"running, and pointed at the bind port?")]
    if status == 421:
        return [Check(False, "host accepted",
                      f"the server refused the hostname in {base} with 421 "
                      f"— restart it with --public-host set to exactly that "
                      f"hostname (no scheme, no port)")]
    if status >= 500:
        # The tunnel answered; whatever it points at did not. Found live:
        # a 502 was previously read as "no OAuth routes" and sent the
        # operator off to fix auth on a server that was not running.
        return [Check(False, "origin reachable",
                      f"{base} answered {status} — the tunnel is up but "
                      f"nothing is serving behind it; start `bunnyforge "
                      f"serve-mcp` on the port the tunnel points at, then "
                      f"re-run this check")]
    if status == 404:
        # One cause, one line. Reporting it three times (no routes, no
        # metadata, /mcp open) buries the sentence that names the fix.
        return [Check(False, "oauth discovery",
                      "no OAuth routes — the server is running --no-auth, "
                      "which cannot serve a connector; restart it with "
                      "--auth-key")]
    checks.append(Check(status == 200, "oauth discovery",
                        f"expected 200 from {PROTECTED_PATH}, got {status}"
                        if status != 200 else
                        f"{PROTECTED_PATH} answers"))

    issuer = ""
    try:
        status, _, body = get(METADATA_PATH)
    except OSError as exc:
        status = 0
        checks.append(Check(False, "issuer",
                            f"could not reach {METADATA_PATH} ({exc})"))
    else:
        try:
            issuer = _json.loads(body or b"{}").get("issuer", "").rstrip("/")
        except ValueError:
            # Keep the real status: reporting "got 0" for a body that
            # simply was not JSON sent the reader hunting the wrong layer.
            issuer = ""
    if status == 200 and issuer == base:
        checks.append(Check(True, "issuer", f"advertised as {issuer}"))
    elif status == 200:
        checks.append(Check(
            False, "issuer",
            f"the server advertises its issuer as {issuer or '(none)'}, not "
            f"{base} — a connector follows that and will try to reach it; "
            f"restart with --public-host set to this hostname"))
    elif status != 404:
        checks.append(Check(False, "issuer",
                            f"expected 200 from {METADATA_PATH}, got "
                            f"{status}"))

    try:
        status, headers, _ = get("/mcp", "POST")
    except OSError as exc:
        checks.append(Check(False, "auth", f"could not reach {base}/mcp "
                                           f"({exc})"))
        return checks
    www = _header(headers, "WWW-Authenticate")
    if status == 401 and "resource_metadata" in www:
        checks.append(Check(True, "auth", "/mcp challenges unauthenticated "
                                          "requests and points at its "
                                          "metadata"))
    elif status == 401:
        checks.append(Check(
            False, "auth",
            "/mcp returns 401 but its WWW-Authenticate carries no "
            "resource_metadata pointer, so a connector cannot discover "
            "where to start OAuth"))
    else:
        checks.append(Check(
            False, "auth",
            f"/mcp answered {status} without credentials — the server is "
            f"running --no-auth; a connector needs OAuth, so restart it "
            f"with --auth-key"))
    return checks


def report(checks: list[Check], out=None) -> int:
    """Print one line per check; 0 only when every one passed."""
    stream = sys.stdout if out is None else out
    for check in checks:
        mark = "ok  " if check.ok else "FAIL"
        print(f"  [{mark}] {check.label}: {check.detail}", file=stream)
    if all(c.ok for c in checks):
        print("\nready for a claude.ai custom connector — add it with both "
              "OAuth fields blank", file=stream)
        return 0
    print("\nnot ready: fix the FAIL lines above, then re-run this check",
          file=stream)
    return 1


def build_app(server, public_host: str | None = None):
    """The ASGI app, told which hostname it is served as (#46).

    The SDK enables DNS-rebinding protection by default and, given no
    settings, allows only the bind address. Through a tunnel the `Host`
    header carries the public hostname instead, so every request was
    refused with `421 Invalid Host header` before it reached auth -- and
    a tunnel is the only deployment the design describes.

    The contract is "declare your hostname", not "turn the guard off":
    protection stays ENABLED and only the named host is allowed, so an
    undeclared Host is still refused. Without a public host the safe
    localhost-only default is left exactly as it was.
    """
    if not public_host:
        return server.streamable_http_app(stateless_http=True)
    from mcp.server.transport_security import TransportSecuritySettings
    return server.streamable_http_app(
        stateless_http=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[public_host],
            allowed_origins=[f"https://{public_host}"]))


def main(argv: list[str] | None = None, probe=_probe) -> int:
    args = build_parser().parse_args(argv)

    # --check inspects a REMOTE server, so it short-circuits before
    # workspace resolution: requiring a campaign workspace to check a URL
    # would be wrong, and the operator is often somewhere else entirely.
    if args.check:
        return report(preflight(args.check, probe=probe))

    try:
        ws = _config.resolve_workspace(args.workspace)
    except (ConfigError, WorkspaceError) as exc:
        print(exc, file=sys.stderr)
        return 1

    key = (args.auth_key or os.environ.get(KEY_ENV, "")).strip()
    if key and args.no_auth:
        print(f"--no-auth contradicts --auth-key/{KEY_ENV}; pick one",
              file=sys.stderr)
        return 1
    if not key and not args.no_auth:
        print("refusing to start without auth: pass --auth-key, set "
              f"{KEY_ENV}, or (local testing only) pass --no-auth",
              file=sys.stderr)
        return 1

    # --public-host does double duty: it names the OAuth issuer, and it
    # declares the hostname to DNS-rebinding protection in build_app (#46).
    issuer = (f"https://{args.public_host}" if args.public_host
              else f"http://127.0.0.1:{args.port}")

    try:
        import uvicorn

        oauth = None
        if key:
            from bunnyforge._mcp_auth import (SingleUserOAuthProvider,
                                              default_state_path)
            oauth = SingleUserOAuthProvider(
                gm_key=key, issuer_url=issuer,
                state_path=default_state_path())
        server = build_server(WorkspaceStore(ws),
                              allow_direct_edits=args.allow_direct_edits,
                              oauth=oauth)
    except ModuleNotFoundError:
        print(_INSTALL_HINT, file=sys.stderr)
        return 1

    app = build_app(server, public_host=args.public_host)
    if not key:
        print("WARNING: serving with no authentication", file=sys.stderr)

    print(f"serving {ws.config.name} at http://{args.host}:{args.port}/mcp "
          f"(OAuth issuer: {issuer})" if key else
          f"serving {ws.config.name} at http://{args.host}:{args.port}/mcp")
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
