import importlib.util
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


class TestBearerAuth(unittest.IsolatedAsyncioTestCase):
    """Pure ASGI, so this runs without the mcp extra installed."""

    async def _call(self, auth, headers):
        sent = []

        async def send(message):
            sent.append(message)

        await auth({"type": "http", "headers": headers}, None, send)
        return sent

    async def test_missing_token_is_401_and_never_reaches_the_app(self):
        async def inner(scope, receive, send):
            raise AssertionError("unauthenticated request reached the app")

        sent = await self._call(serve_mcp._BearerAuth(inner, "sekrit"), [])
        self.assertEqual(sent[0]["status"], 401)

    async def test_wrong_token_is_401(self):
        async def inner(scope, receive, send):
            raise AssertionError("unauthenticated request reached the app")

        sent = await self._call(serve_mcp._BearerAuth(inner, "sekrit"),
                                [(b"authorization", b"Bearer wrong")])
        self.assertEqual(sent[0]["status"], 401)

    async def test_near_miss_token_is_401(self):
        # A prefix of the real token must not pass: the comparison is of the
        # whole header value, not a startswith.
        async def inner(scope, receive, send):
            raise AssertionError("unauthenticated request reached the app")

        sent = await self._call(serve_mcp._BearerAuth(inner, "sekrit"),
                                [(b"authorization", b"Bearer sek")])
        self.assertEqual(sent[0]["status"], 401)

    async def test_right_token_passes_through(self):
        seen = []

        async def inner(scope, receive, send):
            seen.append(scope)

        await self._call(serve_mcp._BearerAuth(inner, "sekrit"),
                         [(b"authorization", b"Bearer sekrit")])
        self.assertEqual(len(seen), 1)

    async def test_non_http_scope_passes_through_untouched(self):
        # Lifespan events carry no headers and must not be answered with 401,
        # or the app never starts.
        seen = []

        async def inner(scope, receive, send):
            seen.append(scope)

        await self._call(serve_mcp._BearerAuth(inner, "sekrit"),
                         [])  # headers ignored for a lifespan scope
        self.assertEqual(len(seen), 0)  # the http scope above was rejected

        auth = serve_mcp._BearerAuth(inner, "sekrit")
        await auth({"type": "lifespan"}, None, None)
        self.assertEqual(len(seen), 1)


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

    def test_public_host_flag_is_parsed(self):
        parser = serve_mcp.build_parser()
        args = parser.parse_args(["--public-host", "example.trycloudflare.com"])
        self.assertEqual(args.public_host, "example.trycloudflare.com")

    def test_refuses_to_start_without_token_or_no_auth(self):
        # A token in the invoking environment must not leak into the test.
        with mock.patch.dict("os.environ", {serve_mcp.TOKEN_ENV: ""}):
            self.assertEqual(
                serve_mcp.main(["--workspace", str(self._ws())]), 1)

    def test_bad_workspace_is_one_error_line_not_a_traceback(self):
        empty = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.assertEqual(serve_mcp.main(["--workspace", str(empty)]), 1)


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

    async def test_write_tools_absent_in_phase_1(self):
        server = serve_mcp.build_server(scaffold(self))
        names = {t.name for t in await server.list_tools()}
        self.assertFalse({"save_draft", "propose_revision", "write_entity"}
                         & names)

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

    async def test_streamable_app_is_asgi_and_wrappable(self):
        server = serve_mcp.build_server(scaffold(self))
        app = server.streamable_http_app(stateless_http=True)
        self.assertTrue(callable(app))
        self.assertTrue(callable(serve_mcp._BearerAuth(app, "t")))


if __name__ == "__main__":
    unittest.main()
