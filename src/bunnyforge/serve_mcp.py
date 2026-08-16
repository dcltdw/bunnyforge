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
touches Export/ or the wiki, so a remote agent cannot leak GM material to
players even by accident.
"""

from __future__ import annotations

import argparse
import os
import sys

from bunnyforge import _config
from bunnyforge._config import ConfigError, WorkspaceError
from bunnyforge._store import StoreError, WorkspaceStore

KEY_ENV = "BUNNYFORGE_MCP_KEY"

# Workspace doctrine, offered as MCP resources so a fresh conversation can
# load the house rules before it writes anything. Absent files are simply
# not listed.
DOCTRINE_FILES = ("style-guide.md", "situation-design.md", "AGENTS.md")

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
        with how many entities it holds, and the current front-burner and
        open-questions documents. Call this before anything else."""
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
    return parser


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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

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
