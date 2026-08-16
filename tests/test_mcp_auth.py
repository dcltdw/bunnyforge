import importlib.util
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# The MCP SDK is an optional extra; _mcp_auth imports it at module top, so
# every test here skips on a bare Python, matching test_serve_mcp.py.
HAVE_MCP = importlib.util.find_spec("mcp") is not None
if HAVE_MCP:
    from bunnyforge import _mcp_auth
    from bunnyforge._mcp_auth import SingleUserOAuthProvider


def client_record(client_id: str):
    from mcp.shared.auth import OAuthClientInformationFull
    return OAuthClientInformationFull(
        client_id=client_id,
        client_secret="s3cret",
        client_name="Claude",
        redirect_uris=["http://localhost:9999/cb"],
    )


@unittest.skipUnless(HAVE_MCP, "requires bunnyforge[mcp]")
class TestClientRegistry(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.state = root / "state" / "mcp-oauth-state.json"
        self.provider = SingleUserOAuthProvider(
            gm_key="k", issuer_url="http://127.0.0.1:8000/",
            state_path=self.state)

    def test_issuer_url_is_rstripped(self):
        self.assertEqual(self.provider.issuer_url, "http://127.0.0.1:8000")

    async def test_register_then_get_roundtrips(self):
        await self.provider.register_client(client_record("c1"))
        got = await self.provider.get_client("c1")
        self.assertEqual(got.client_name, "Claude")
        self.assertIsNone(await self.provider.get_client("nope"))

    async def test_registration_capped_evicts_oldest(self):
        for i in range(_mcp_auth.MAX_CLIENTS + 1):
            await self.provider.register_client(client_record(f"c{i}"))
        self.assertIsNone(await self.provider.get_client("c0"))
        self.assertIsNotNone(await self.provider.get_client("c1"))
        self.assertEqual(len(self.provider._clients), _mcp_auth.MAX_CLIENTS)

    async def test_state_file_is_0600_and_survives_restart(self):
        await self.provider.register_client(client_record("c1"))
        mode = stat.S_IMODE(os.stat(self.state).st_mode)
        self.assertEqual(mode, 0o600)
        reborn = SingleUserOAuthProvider(
            gm_key="k", issuer_url="http://127.0.0.1:8000",
            state_path=self.state)
        got = await reborn.get_client("c1")
        self.assertEqual(got.client_secret, "s3cret")

    async def test_corrupt_state_file_starts_empty_not_crashed(self):
        self.state.parent.mkdir(parents=True)
        self.state.write_text("{not json", encoding="utf-8")
        with mock.patch("sys.stderr"):
            provider = SingleUserOAuthProvider(
                gm_key="k", issuer_url="http://127.0.0.1:8000",
                state_path=self.state)
        self.assertIsNone(await provider.get_client("c1"))
        # first successful save replaces the corrupt file
        await provider.register_client(client_record("c1"))
        json.loads(self.state.read_text(encoding="utf-8"))


@unittest.skipUnless(HAVE_MCP, "requires bunnyforge[mcp]")
class TestDefaultStatePath(unittest.TestCase):

    def test_honours_xdg_state_home(self):
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": "/x/state"}):
            self.assertEqual(_mcp_auth.default_state_path(),
                             Path("/x/state/bunnyforge/mcp-oauth-state.json"))

    def test_defaults_under_home(self):
        with mock.patch.dict(os.environ, clear=False) as env:
            os.environ.pop("XDG_STATE_HOME", None)
            self.assertEqual(
                _mcp_auth.default_state_path(),
                Path.home() / ".local/state/bunnyforge/mcp-oauth-state.json")
