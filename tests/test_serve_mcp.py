import contextlib
import importlib.util
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bunnyforge import _config, _store, serve_mcp

# The MCP SDK is an optional extra. Everything that does not need it runs on
# a bare Python; the rest skips rather than failing, so the suite stays green
# for anyone who installed bunnyforge without `[mcp]`.
HAVE_MCP = importlib.util.find_spec("mcp") is not None

MINIMAL = '[campaign]\nnamespace = "testwiki"\nname = "Testmere"\n'

NPC = """---
title: Kim Ha-eun
summary: Kim Ha-eun is a ferry captain in Testmere harbor.
---
She knows the tides.
"""


def scaffold(case: unittest.TestCase) -> _store.WorkspaceStore:
    root = Path(case.enterContext(tempfile.TemporaryDirectory()))
    (root / "campaign.toml").write_text(MINIMAL, encoding="utf-8")
    (root / "NPCs").mkdir()
    (root / "NPCs" / "kim-ha-eun.md").write_text(NPC, encoding="utf-8")
    (root / "style-guide.md").write_text("# Style\nSpare prose.\n",
                                         encoding="utf-8")
    return _store.WorkspaceStore(_config.open_workspace(root))


class TestMainGuards(unittest.TestCase):
    """argparse and the refusals — no mcp extra needed for any of these."""

    def _ws(self) -> Path:
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (root / "campaign.toml").write_text(MINIMAL, encoding="utf-8")
        return root

    def test_help_works_without_the_extra(self):
        with self.assertRaises(SystemExit) as ctx:
            serve_mcp.main(["--help"])
        self.assertEqual(ctx.exception.code, 0)

    def test_bad_workspace_is_one_error_line_not_a_traceback(self):
        empty = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.assertEqual(serve_mcp.main(["--workspace", str(empty)]), 1)


class TestStartupContract(unittest.TestCase):
    """Default-deny: the spec's startup matrix, refusal rows.

    These run on bare Python: every refusal fires before the SDK import.
    """

    def setUp(self):
        store = scaffold(self)
        self.ws_args = ["--workspace", str(store.ws.root)]
        self.enterContext(mock.patch.dict(
            os.environ, {"BUNNYFORGE_MCP_KEY": ""}))

    def _main(self, extra):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            rc = serve_mcp.main(self.ws_args + extra)
        return rc, stderr.getvalue()

    def test_refuses_without_key_or_no_auth(self):
        rc, err = self._main([])
        self.assertEqual(rc, 1)
        self.assertIn("--auth-key", err)
        self.assertIn("BUNNYFORGE_MCP_KEY", err)
        self.assertIn("--no-auth", err)

    def test_refuses_key_and_no_auth_together(self):
        rc, err = self._main(["--auth-key", "k", "--no-auth"])
        self.assertEqual(rc, 1)
        self.assertIn("contradict", err)

    def test_env_key_counts_as_key_for_the_contradiction(self):
        with mock.patch.dict(os.environ, {"BUNNYFORGE_MCP_KEY": "k"}):
            rc, err = self._main(["--no-auth"])
        self.assertEqual(rc, 1)
        self.assertIn("contradict", err)

    def test_token_flag_is_gone(self):
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stderr(io.StringIO()):
                serve_mcp.build_parser().parse_args(["--token", "t"])


@unittest.skipUnless(HAVE_MCP, "mcp extra not installed")
class TestBuildServer(unittest.IsolatedAsyncioTestCase):

    async def _text(self, result) -> str:
        return "".join(part.text for part in result.content)

    async def test_read_tools_are_registered(self):
        server = serve_mcp.build_server(scaffold(self))
        names = {t.name for t in await server.list_tools()}
        self.assertLessEqual(
            {"campaign_overview", "list_entities", "read_entity", "search",
             "generate_names"}, names)

    async def test_draft_tools_always_registered(self):
        # The drafts directory is the agent's own outbox: writing to it and
        # reading it back need no flag; nothing here can reach canon.
        server = serve_mcp.build_server(scaffold(self))
        names = {t.name for t in await server.list_tools()}
        self.assertLessEqual(
            {"save_draft", "propose_revision", "list_drafts", "read_draft"},
            names)

    async def test_list_drafts_reports_what_was_drafted(self):
        store = scaffold(self)
        server = serve_mcp.build_server(store)
        await server.call_tool("save_draft", {
            "section": "NPCs", "name": "Cho", "content": "x"})
        payload = await self._text(await server.call_tool("list_drafts", {}))
        self.assertIn("_AgentDrafts/NPCs/cho.md", payload)

    async def test_read_draft_round_trips(self):
        store = scaffold(self)
        server = serve_mcp.build_server(store)
        await server.call_tool("save_draft", {
            "section": "NPCs", "name": "Cho", "content": "draft body"})
        payload = await self._text(await server.call_tool(
            "read_draft", {"path": "_AgentDrafts/NPCs/cho.md"}))
        self.assertIn("draft body", payload)

    async def test_read_draft_refuses_a_canonical_path(self):
        # The two read doors stay separate: read_draft must not become a
        # second way into canon.
        server = serve_mcp.build_server(scaffold(self))
        with self.assertRaises(Exception) as ctx:
            await server.call_tool(
                "read_draft", {"path": "NPCs/kim-ha-eun.md"})
        self.assertIn("read_entity", str(ctx.exception))

    async def test_write_entity_only_with_the_flag(self):
        # The gate is the whole safety story: drafts are always available
        # because they cannot reach canon, and canon is reachable only
        # because someone passed a per-run flag.
        store = scaffold(self)
        off = {t.name for t in await serve_mcp.build_server(store).list_tools()}
        on = {t.name for t in await serve_mcp.build_server(
            store, allow_direct_edits=True).list_tools()}
        self.assertNotIn("write_entity", off)
        self.assertIn("write_entity", on)

    async def test_save_draft_lands_in_the_drafts_dir(self):
        store = scaffold(self)
        server = serve_mcp.build_server(store)
        await server.call_tool("save_draft", {
            "section": "NPCs", "name": "Cho", "content": "x"})
        self.assertTrue(
            (store.ws.root / "_AgentDrafts/NPCs/cho.md").is_file())

    async def test_every_tool_carries_a_description(self):
        # The description is how the remote agent decides to call a tool at
        # all; an undocumented tool is an unused one.
        server = serve_mcp.build_server(scaffold(self))
        for tool in await server.list_tools():
            self.assertTrue((tool.description or "").strip(), tool.name)

    async def test_campaign_overview_answers(self):
        server = serve_mcp.build_server(scaffold(self))
        payload = await self._text(
            await server.call_tool("campaign_overview", {}))
        self.assertIn("Testmere", payload)
        self.assertIn("NPCs", payload)

    async def test_read_entity_round_trips(self):
        server = serve_mcp.build_server(scaffold(self))
        payload = await self._text(await server.call_tool(
            "read_entity", {"path": "NPCs/kim-ha-eun.md"}))
        self.assertIn("ferry captain", payload)

    async def test_search_accepts_an_omitted_section(self):
        server = serve_mcp.build_server(scaffold(self))
        payload = await self._text(
            await server.call_tool("search", {"query": "tides"}))
        self.assertIn("kim-ha-eun", payload)

    async def test_a_refusal_carries_its_reason_to_the_caller(self):
        # A StoreError must reach the agent as an actionable message rather
        # than a silent empty answer. Two layers are involved and only the
        # first is exercised here: call_tool() -- the convenience API --
        # raises, while the SDK's protocol handler (_handle_call_tool)
        # catches that and returns CallToolResult(is_error=True) with
        # str(exc) as the content, which is what a real client receives.
        # What both layers depend on, and what this pins, is that the
        # reason survives into the exception's message.
        server = serve_mcp.build_server(scaffold(self))
        with self.assertRaises(Exception) as ctx:
            await server.call_tool("read_entity", {"path": "../escape.md"})
        self.assertIn("escapes the workspace", str(ctx.exception))
        self.assertIn("read_entity", str(ctx.exception))

    async def test_doctrine_resource_lists_and_reads(self):
        server = serve_mcp.build_server(scaffold(self))
        uris = {str(r.uri) for r in await server.list_resources()}
        self.assertIn("bunnyforge://doctrine/style-guide.md", uris)
        parts = list(await server.read_resource(
            "bunnyforge://doctrine/style-guide.md"))
        self.assertIn("Spare prose", "".join(p.content for p in parts))

    async def test_absent_doctrine_file_is_not_listed(self):
        server = serve_mcp.build_server(scaffold(self))
        uris = {str(r.uri) for r in await server.list_resources()}
        self.assertNotIn("bunnyforge://doctrine/situation-design.md", uris)

    async def test_streamable_app_is_asgi(self):
        server = serve_mcp.build_server(scaffold(self))
        self.assertTrue(callable(serve_mcp.build_app(server)))



@unittest.skipUnless(HAVE_MCP, "mcp extra not installed")
class TestTunnelHost(unittest.TestCase):
    """Issue #46: the only deployment the design describes is through a
    tunnel, and through one the `Host` header carries the public hostname
    rather than the bind address. The SDK enables DNS-rebinding protection
    by default and, given no settings, allows only the bind address -- so
    every tunnelled request was rejected with 421 before it reached auth.

    The contract is "declare your hostname", not "turn the guard off":
    an undeclared host must still be refused.
    """

    HOST = "campaign.example.com"

    def _client(self, **kwargs):
        from starlette.testclient import TestClient
        server = serve_mcp.build_server(scaffold(self))
        app = serve_mcp.build_app(server, **kwargs)
        return self.enterContext(
            TestClient(app, base_url=f"https://{self.HOST}",
                       follow_redirects=False))

    def test_a_declared_public_host_is_served(self):
        response = self._client(public_host=self.HOST).post("/mcp", json={})
        self.assertNotEqual(
            response.status_code, 421,
            "a tunnel hostname passed as --public-host was still refused by "
            "DNS-rebinding protection")

    def test_an_undeclared_host_is_still_refused(self):
        # The guard stays ON. If this ever passes, the fix has been
        # implemented by disabling the protection rather than declaring
        # the hostname, which would accept any Host on the public internet.
        self.assertEqual(self._client().post("/mcp", json={}).status_code,
                         421)


def _probe_map(**by_path):
    """A fake HTTP seam: {path -> (status, headers, body)} or an OSError
    instance to raise. Nothing here touches the network."""
    def probe(url, method="GET"):
        from urllib.parse import urlsplit
        answer = by_path[urlsplit(url).path]
        if isinstance(answer, OSError):
            raise answer
        return answer
    return probe


def _healthy(issuer="https://campaign.example.com", header="www-authenticate"):
    """What a correctly configured server behind a tunnel answers.

    The header name defaults to LOWERCASE because that is what uvicorn
    actually puts on the wire. An earlier version of this fixture used the
    RFC's casing, every test passed, and the real probe still failed --
    urllib hands back an email.message.Message whose case-insensitivity is
    lost the moment it becomes a plain dict.
    """
    meta_url = f"{issuer}/.well-known/oauth-protected-resource/mcp"
    return _probe_map(**{
        "/.well-known/oauth-protected-resource/mcp": (
            200, {}, b'{"resource": "x"}'),
        "/.well-known/oauth-authorization-server": (
            200, {}, ('{"issuer": "%s"}' % issuer).encode()),
        "/mcp": (401, {header: f'Bearer resource_metadata="{meta_url}"'},
                 b""),
    })


class TestPreflight(unittest.TestCase):
    """Issue #51: prove the public URL is connector-ready before claude.ai
    is involved, so a failed connect stops being one opaque browser error
    covering four unrelated causes.

    Every probe is injected; no test opens a socket.
    """

    URL = "https://campaign.example.com"

    def _run(self, probe):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = serve_mcp.main(["--check", self.URL], probe=probe)
        return rc, out.getvalue()

    def test_a_correctly_configured_server_passes(self):
        rc, out = self._run(_healthy())
        self.assertEqual(rc, 0, out)
        self.assertIn("ready", out.lower())

    def test_a_public_host_mismatch_is_named_not_just_reported(self):
        # 421 has exactly one cause, so the check must say so rather than
        # leaving the operator to work it out.
        probe = _healthy()
        broken = _probe_map(**{
            "/.well-known/oauth-protected-resource/mcp": (421, {}, b""),
            "/.well-known/oauth-authorization-server": (421, {}, b""),
            "/mcp": (421, {}, b""),
        })
        rc, out = self._run(broken)
        self.assertEqual(rc, 1)
        self.assertIn("--public-host", out)

    def test_an_issuer_pointing_at_localhost_is_caught(self):
        # The documents serve fine; every endpoint in them is unreachable.
        rc, out = self._run(_healthy(issuer="http://127.0.0.1:8765"))
        self.assertEqual(rc, 1)
        self.assertIn("127.0.0.1", out)
        self.assertIn("issuer", out.lower())

    def test_an_open_server_is_reported_as_no_auth(self):
        probe = _probe_map(**{
            "/.well-known/oauth-protected-resource/mcp": (404, {}, b""),
            "/.well-known/oauth-authorization-server": (404, {}, b""),
            "/mcp": (200, {}, b"{}"),
        })
        rc, out = self._run(probe)
        self.assertEqual(rc, 1)
        self.assertIn("--no-auth", out)

    def test_an_unreachable_host_says_so(self):
        probe = _probe_map(**{
            "/.well-known/oauth-protected-resource/mcp":
                OSError("nodename nor servname provided"),
            "/.well-known/oauth-authorization-server": (200, {}, b"{}"),
            "/mcp": (401, {}, b""),
        })
        rc, out = self._run(probe)
        self.assertEqual(rc, 1)
        self.assertIn("could not reach", out.lower())

    def test_a_401_without_a_metadata_pointer_is_flagged(self):
        # The connector needs that pointer to start OAuth at all.
        probe = _probe_map(**{
            "/.well-known/oauth-protected-resource/mcp": (200, {}, b"{}"),
            "/.well-known/oauth-authorization-server": (
                200, {}, b'{"issuer": "https://campaign.example.com"}'),
            "/mcp": (401, {}, b""),
        })
        rc, out = self._run(probe)
        self.assertEqual(rc, 1)
        self.assertIn("resource_metadata", out)

    def test_check_needs_no_workspace(self):
        # It inspects a remote server; requiring a campaign workspace to
        # check a URL would be wrong, and the operator may well run it
        # from another directory entirely.
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        with mock.patch.object(Path, "cwd", return_value=tmp):
            rc, _ = self._run(_healthy())
        self.assertEqual(rc, 0)

    def test_the_metadata_pointer_is_found_whatever_the_header_casing(self):
        # Found by smoking the real probe: uvicorn sends
        # `www-authenticate`, urllib's Message is case-insensitive, and
        # dict(Message) is not -- so the RFC-cased lookup missed it and
        # the check told a correctly configured server it was broken.
        for casing in ("www-authenticate", "WWW-Authenticate",
                       "Www-Authenticate"):
            with self.subTest(header=casing):
                rc, out = self._run(_healthy(header=casing))
                self.assertEqual(rc, 0, out)

    def test_no_auth_is_diagnosed_once_not_three_times(self):
        # One cause should read as one problem. Three lines for one
        # misconfiguration buries the sentence that names the fix.
        probe = _probe_map(**{
            "/.well-known/oauth-protected-resource/mcp": (404, {}, b""),
            "/.well-known/oauth-authorization-server": (404, {}, b"<html>"),
            "/mcp": (400, {}, b""),
        })
        rc, out = self._run(probe)
        self.assertEqual(rc, 1)
        # The marker, not the bare word: the closing summary says "fix the
        # FAIL lines above", which is guidance rather than a finding.
        self.assertEqual(out.count("[FAIL]"), 1, out)
        self.assertIn("--no-auth", out)


    def test_a_tunnel_with_no_server_behind_it_is_not_blamed_on_auth(self):
        # Found live: the tunnel answered 502 because nothing was
        # listening on the bind port, and the check told the operator to
        # restart with --auth-key. Sending someone to fix auth when the
        # server is not running is precisely the misdiagnosis this
        # command exists to prevent.
        for status in (502, 503, 504):
            with self.subTest(status=status):
                probe = _probe_map(**{
                    "/.well-known/oauth-protected-resource/mcp":
                        (status, {}, b""),
                    "/.well-known/oauth-authorization-server":
                        (status, {}, b""),
                    "/mcp": (status, {}, b""),
                })
                rc, out = self._run(probe)
                self.assertEqual(rc, 1)
                self.assertEqual(out.count("[FAIL]"), 1, out)
                self.assertNotIn("--auth-key", out)
                self.assertNotIn("--no-auth", out)
                self.assertIn("serve-mcp", out)


if __name__ == "__main__":
    unittest.main()
