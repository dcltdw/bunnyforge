import importlib.util
import json
import os
import stat
import tempfile
import time
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


def auth_params():
    from mcp.server.auth.provider import AuthorizationParams
    return AuthorizationParams(
        state="st8", scopes=[], code_challenge="chal",
        redirect_uri="http://localhost:9999/cb",
        redirect_uri_provided_explicitly=True)


@unittest.skipUnless(HAVE_MCP, "requires bunnyforge[mcp]")
class TestConsentAndTokens(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.provider = SingleUserOAuthProvider(
            gm_key="sekrit", issuer_url="http://127.0.0.1:8000",
            state_path=root / "state.json")

    async def _register(self, cid="c1"):
        record = client_record(cid)
        await self.provider.register_client(record)
        return record

    async def test_authorize_parks_txn_and_points_at_consent(self):
        client = await self._register()
        url = await self.provider.authorize(client, auth_params())
        self.assertTrue(
            url.startswith("http://127.0.0.1:8000/consent?txn="), url)
        txn = url.split("txn=")[1]
        self.assertEqual(self.provider.consent_context(txn),
                         {"client_name": "Claude"})

    async def test_consent_context_unknown_or_expired_is_none(self):
        client = await self._register()
        url = await self.provider.authorize(client, auth_params())
        txn = url.split("txn=")[1]
        self.assertIsNone(self.provider.consent_context("bogus"))
        future = time.time() + _mcp_auth.TXN_TTL + 1
        with mock.patch("bunnyforge._mcp_auth.time.time",
                        return_value=future):
            self.assertIsNone(self.provider.consent_context(txn))

    def test_check_key_right_wrong_and_near_miss(self):
        self.assertTrue(self.provider.check_key("sekrit"))
        self.assertFalse(self.provider.check_key("wrong"))
        self.assertFalse(self.provider.check_key("sek"))
        self.assertFalse(self.provider.check_key(""))

    async def test_grant_consumes_txn_and_mints_single_use_code(self):
        client = await self._register()
        url = await self.provider.authorize(client, auth_params())
        txn = url.split("txn=")[1]
        redirect = self.provider.grant(txn)
        self.assertIn("code=", redirect)
        self.assertIn("state=st8", redirect)
        self.assertTrue(redirect.startswith("http://localhost:9999/cb?"))
        self.assertIsNone(self.provider.grant(txn))  # consumed

    async def _grant_code(self, client):
        url = await self.provider.authorize(client, auth_params())
        redirect = self.provider.grant(url.split("txn=")[1])
        code = redirect.split("code=")[1].split("&")[0]
        return await self.provider.load_authorization_code(client, code)

    async def test_code_exchange_and_replay(self):
        from mcp.server.auth.provider import TokenError
        client = await self._register()
        auth_code = await self._grant_code(client)
        self.assertEqual(auth_code.code_challenge, "chal")
        tokens = await self.provider.exchange_authorization_code(
            client, auth_code)
        self.assertEqual(tokens.token_type, "Bearer")
        self.assertEqual(tokens.expires_in, _mcp_auth.ACCESS_TTL)
        with self.assertRaises(TokenError):
            await self.provider.exchange_authorization_code(client, auth_code)

    async def test_code_expires(self):
        client = await self._register()
        auth_code = await self._grant_code(client)
        future = time.time() + _mcp_auth.CODE_TTL + 1
        with mock.patch("bunnyforge._mcp_auth.time.time",
                        return_value=future):
            self.assertIsNone(await self.provider.load_authorization_code(
                client, auth_code.code))

    async def test_wrong_client_cannot_load_anothers_code(self):
        client = await self._register()
        other = await self._register("c2")
        auth_code = await self._grant_code(client)
        self.assertIsNone(await self.provider.load_authorization_code(
            other, auth_code.code))

    async def test_access_token_verifies_then_expires(self):
        client = await self._register()
        auth_code = await self._grant_code(client)
        tokens = await self.provider.exchange_authorization_code(
            client, auth_code)
        at = await self.provider.load_access_token(tokens.access_token)
        self.assertEqual(at.client_id, "c1")
        future = time.time() + _mcp_auth.ACCESS_TTL + 1
        with mock.patch("bunnyforge._mcp_auth.time.time",
                        return_value=future):
            self.assertIsNone(await self.provider.load_access_token(
                tokens.access_token))

    async def test_refresh_rotates(self):
        from mcp.server.auth.provider import TokenError
        client = await self._register()
        auth_code = await self._grant_code(client)
        first = await self.provider.exchange_authorization_code(
            client, auth_code)
        rt = await self.provider.load_refresh_token(
            client, first.refresh_token)
        second = await self.provider.exchange_refresh_token(client, rt, [])
        self.assertNotEqual(first.refresh_token, second.refresh_token)
        # the old refresh token died with the rotation
        self.assertIsNone(await self.provider.load_refresh_token(
            client, first.refresh_token))
        with self.assertRaises(TokenError):
            await self.provider.exchange_refresh_token(client, rt, [])

    async def test_tokens_survive_restart_but_txns_do_not(self):
        client = await self._register()
        url = await self.provider.authorize(client, auth_params())
        txn = url.split("txn=")[1]
        auth_code = await self._grant_code(client)
        tokens = await self.provider.exchange_authorization_code(
            client, auth_code)
        reborn = SingleUserOAuthProvider(
            gm_key="sekrit", issuer_url="http://127.0.0.1:8000",
            state_path=self.provider._state_path)
        self.assertIsNotNone(
            await reborn.load_access_token(tokens.access_token))
        self.assertIsNone(reborn.consent_context(txn))

    async def test_revoke_deletes(self):
        client = await self._register()
        auth_code = await self._grant_code(client)
        tokens = await self.provider.exchange_authorization_code(
            client, auth_code)
        at = await self.provider.load_access_token(tokens.access_token)
        await self.provider.revoke_token(at)
        self.assertIsNone(
            await self.provider.load_access_token(tokens.access_token))
