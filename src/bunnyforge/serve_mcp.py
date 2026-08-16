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

Everything served here is GM-eyes-only, so auth is default-deny: no token
and no explicit --no-auth means the server refuses to start. _BearerAuth is
deliberately pure ASGI rather than starlette middleware — it must work
whatever the SDK builds its app from, and it is short enough to read in one
sitting, which is what you want of the only thing between a tunnel and the
campaign's secrets.

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

TOKEN_ENV = "BUNNYFORGE_MCP_TOKEN"

# Workspace doctrine, offered as MCP resources so a fresh conversation can
# load the house rules before it writes anything. Absent files are simply
# not listed.
DOCTRINE_FILES = ("style-guide.md", "situation-design.md", "AGENTS.md")

_INSTALL_HINT = ("serve-mcp needs its optional dependencies:\n"
                 "  pip install 'bunnyforge[mcp]'")


class _BearerAuth:
    """Require `Authorization: Bearer <token>` on every HTTP request.

    Non-HTTP scopes (lifespan) pass through untouched: they carry no headers,
    and answering them with 401 would stop the app from starting.
    """

    def __init__(self, app, token: str):
        self._app = app
        self._expected = f"Bearer {token}".encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = {k.lower(): v for k, v in scope.get("headers") or []}
            if headers.get(b"authorization") != self._expected:
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"text/plain"),
                                        (b"www-authenticate", b"Bearer")]})
                await send({"type": "http.response.body",
                            "body": b"unauthorized"})
                return
        await self._app(scope, receive, send)


def build_server(store: WorkspaceStore, *, allow_direct_edits: bool = False):
    """Assemble the MCP server over one workspace store.

    Imports the SDK, so a caller without the extra gets ModuleNotFoundError;
    main() translates that into the install hint.

    Tool docstrings are not decoration — they are what the remote agent reads
    to decide whether to call a tool, so they say when to use it, not merely
    what it does.
    """
    from mcp.server import MCPServer

    server = MCPServer("bunnyforge")

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
    parser.add_argument("--token",
                        help=f"bearer token, or set {TOKEN_ENV}; required "
                             "unless --no-auth")
    parser.add_argument("--no-auth", action="store_true",
                        help="serve with no authentication — local testing "
                             "only; everything served is GM-only material")
    parser.add_argument("--public-host",
                        help="public hostname for DNS-rebinding protection "
                             "when served through a tunnel (e.g. cloudflared)")
    parser.add_argument("--allow-direct-edits", action="store_true",
                        help="also expose write_entity, which edits "
                             "canonical files in place and commits each edit")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        ws = _config.resolve_workspace(args.workspace)
    except (ConfigError, WorkspaceError) as exc:
        print(exc, file=sys.stderr)
        return 1

    token = (args.token or os.environ.get(TOKEN_ENV, "")).strip()
    if not token and not args.no_auth:
        print("refusing to start without auth: pass --token, set "
              f"{TOKEN_ENV}, or (local testing only) pass --no-auth",
              file=sys.stderr)
        return 1

    try:
        import uvicorn
        server = build_server(WorkspaceStore(ws),
                              allow_direct_edits=args.allow_direct_edits)
    except ModuleNotFoundError:
        print(_INSTALL_HINT, file=sys.stderr)
        return 1

    transport_security = None
    if args.public_host:
        try:
            from mcp.server.transport_security import TransportSecuritySettings
            transport_security = TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=[args.public_host],
                allowed_origins=[f"https://{args.public_host}", f"http://{args.public_host}"],
            )
        except ImportError:
            pass

    app = server.streamable_http_app(
        stateless_http=True,
        transport_security=transport_security,
    )
    if token:
        app = _BearerAuth(app, token)
    else:
        print("WARNING: serving with no authentication", file=sys.stderr)

    print(f"serving {ws.config.name} at http://{args.host}:{args.port}/mcp")
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
