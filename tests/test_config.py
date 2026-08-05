import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path
from unittest import mock

from bunnyforge import _config

MINIMAL = '[campaign]\nnamespace = "testwiki"\n'


class TestConfigLoad(unittest.TestCase):

    def _ws(self, text: str | None) -> Path:
        """A temp workspace, optionally containing campaign.toml."""
        d = Path(self.enterContext(tempfile.TemporaryDirectory()))
        if text is not None:
            (d / "campaign.toml").write_text(text, encoding="utf-8")
        return d

    def test_reads_namespace(self):
        cfg = _config.load(self._ws(MINIMAL))
        self.assertEqual(cfg.namespace, "testwiki")

    def test_name_defaults_to_namespace(self):
        cfg = _config.load(self._ws(MINIMAL))
        self.assertEqual(cfg.name, "testwiki")

    def test_reads_explicit_name(self):
        cfg = _config.load(self._ws('[campaign]\nname = "Barrowmere"\nnamespace = "bm"\n'))
        self.assertEqual(cfg.name, "Barrowmere")

    def test_missing_file_raises_with_the_filename(self):
        with self.assertRaises(_config.ConfigError) as ctx:
            _config.load(self._ws(None))
        self.assertIn("campaign.toml", str(ctx.exception))

    def test_missing_namespace_raises(self):
        with self.assertRaises(_config.ConfigError) as ctx:
            _config.load(self._ws('[campaign]\nname = "No Namespace"\n'))
        self.assertIn("namespace", str(ctx.exception))

    def test_malformed_toml_raises(self):
        with self.assertRaises(_config.ConfigError) as ctx:
            _config.load(self._ws("[campaign\nnamespace = broken"))
        self.assertIn("valid TOML", str(ctx.exception))

    def test_optional_keys_fall_back_to_defaults(self):
        cfg = _config.load(self._ws(MINIMAL))
        self.assertIn("NPCs", cfg.entity_dirs)
        self.assertIn("Briefs", cfg.inherit_dirs)
        self.assertIn("AGENTS.md", cfg.root_docs)

    def test_exclude_dirs_always_include_git(self):
        cfg = _config.load(self._ws(MINIMAL + '\n[workspace]\nexclude_dirs = ["OnlyThis"]\n'))
        self.assertIn("OnlyThis", cfg.exclude_dirs)
        self.assertIn(".git", cfg.exclude_dirs)
        self.assertIn(".github", cfg.exclude_dirs)

    def test_compendium_dirs_is_explicit_not_derived(self):
        # The old code derived this as ENTITY_DIRS - {Sessions, Handouts}.
        # Config must be able to state something that derivation cannot produce.
        cfg = _config.load(self._ws(
            MINIMAL + '\n[workspace]\n'
            'entity_dirs = ["NPCs", "Sessions"]\n'
            'compendium_dirs = ["Sessions"]\n'))
        self.assertEqual(cfg.compendium_dirs, ("Sessions",))

    def test_entity_dir_absent_from_disk_is_tolerated(self):
        # load() validates shape, not the filesystem; walking skips what is
        # not there. A fresh workspace has not created every directory yet.
        cfg = _config.load(self._ws(MINIMAL + '\n[workspace]\nentity_dirs = ["Nope"]\n'))
        self.assertEqual(cfg.entity_dirs, ("Nope",))

    def test_wrong_type_raises(self):
        with self.assertRaises(_config.ConfigError) as ctx:
            _config.load(self._ws(MINIMAL + '\n[workspace]\nentity_dirs = "NPCs"\n'))
        self.assertIn("entity_dirs", str(ctx.exception))

    def test_entity_and_inherit_dir_overlap_raises_naming_the_dir(self):
        # iter_content_files walks entity_dirs then inherit_dirs, so a
        # directory listed in both is enumerated twice and every file under
        # it is checked, exported and counted twice. The message must name
        # the offending directory: "Briefs" is the fix, "your config is
        # wrong" is not. Two overlapping directories are supplied and only
        # one non-overlapping decoy, so a message that simply echoed the
        # whole entity_dirs list would fail this assertion's converse below.
        cfg = self._ws(
            MINIMAL + '\n[workspace]\n'
            'entity_dirs = ["NPCs", "Briefs", "Perceptions"]\n'
            'inherit_dirs = ["Briefs", "Perceptions"]\n')
        with self.assertRaises(_config.ConfigError) as ctx:
            _config.load(cfg)
        message = str(ctx.exception)
        self.assertIn("Briefs", message)
        self.assertIn("Perceptions", message)
        self.assertNotIn("NPCs", message)

    def test_disjoint_entity_and_inherit_dirs_load(self):
        # The converse: the check must reject an intersection, not the mere
        # presence of both keys. Without this, "raise whenever inherit_dirs
        # is set" would pass the test above.
        cfg = _config.load(self._ws(
            MINIMAL + '\n[workspace]\n'
            'entity_dirs = ["NPCs", "Sessions"]\n'
            'inherit_dirs = ["Briefs"]\n'))
        self.assertEqual(cfg.entity_dirs, ("NPCs", "Sessions"))
        self.assertEqual(cfg.inherit_dirs, ("Briefs",))

    def test_names_cultures_defaults_to_none(self):
        cfg = self._ws(MINIMAL)
        self.assertIsNone(_config.load(cfg).names_cultures)

    def test_reads_names_block(self):
        cfg = self._ws(
            MINIMAL + '\n[names]\n'
            'cultures = "names/cultures"\n')
        loaded = _config.load(cfg)
        self.assertEqual(loaded.names_cultures, "names/cultures")

    def test_names_section_must_be_a_table(self):
        # Ordering matters here: MINIMAL opens a [campaign] table, and in TOML
        # every bare key after a table header belongs to that table until the
        # next header. `MINIMAL + 'names = ...'` would make `names` a member
        # of [campaign], not a top-level key — the isinstance guard would
        # then pass vacuously against the {} default, and this test would
        # assert nothing. Prepending the bare key keeps it at the top level,
        # ahead of any table header, so it is genuinely `names`, not
        # `campaign.names`.
        with self.assertRaises(_config.ConfigError) as ctx:
            _config.load(self._ws('names = "names/cultures"\n' + MINIMAL))
        self.assertIn("[names]", str(ctx.exception))

    def test_names_official_culture_defaults_to_none(self):
        cfg = self._ws(MINIMAL)
        self.assertIsNone(_config.load(cfg).names_official_culture)

    def test_names_official_culture_is_read(self):
        cfg = self._ws(MINIMAL + '\n[names]\nofficial_culture = "vashkand"\n')
        self.assertEqual(_config.load(cfg).names_official_culture, "vashkand")

    def test_names_spelling_defaults_to_empty(self):
        self.assertEqual(_config.load(self._ws(MINIMAL)).names_spelling, {})

    def test_names_spelling_is_read_as_a_table(self):
        # Bare [names] keys first, then the sub-table: a bare key after a
        # table header would be swallowed by that table.
        cfg = self._ws(MINIMAL + '\n[names]\ncultures = "names/cultures"\n'
                       '\n[names.spelling]\nmax_length = 20\n')
        loaded = _config.load(cfg)
        self.assertEqual(loaded.names_spelling["max_length"], 20)

    def test_names_spelling_must_be_a_table(self):
        # A string is an easy typo for someone who expects named
        # pronounceability profiles to still exist (they don't — see the
        # module docstring's three-layer resolution). Bare [names] keys
        # must come before the offending key, same TOML-scoping trap as
        # test_names_spelling_is_read_as_a_table above.
        cfg = self._ws(MINIMAL + '\n[names]\ncultures = "names/cultures"\n'
                       'spelling = "strict"\n')
        with self.assertRaises(_config.ConfigError) as ctx:
            _config.load(cfg)
        self.assertIn("[names.spelling]", str(ctx.exception))

    def test_names_spelling_array_of_tables_raises_config_error(self):
        # [[names.spelling]] is a natural TOML slip and parses to a *list*
        # of dicts. Without the shape guard this reaches resolve_spelling's
        # set(overrides) and blows up with a raw, unhandled TypeError that
        # names neither campaign.toml nor [names.spelling].
        cfg = self._ws(MINIMAL + '\n[names]\ncultures = "names/cultures"\n'
                       '\n[[names.spelling]]\nmax_length = 20\n')
        with self.assertRaises(_config.ConfigError) as ctx:
            _config.load(cfg)
        self.assertIn("[names.spelling]", str(ctx.exception))

    def test_briefs_sheets_perceptions_dirs_default_to_the_conventional_names(self):
        cfg = _config.load(self._ws(MINIMAL))
        self.assertEqual(cfg.briefs_dir, "Briefs")
        self.assertEqual(cfg.sheets_dir, "Sheets")
        self.assertEqual(cfg.perceptions_dir, "Perceptions")

    def test_briefs_sheets_perceptions_dirs_honour_explicit_overrides(self):
        cfg = _config.load(self._ws(
            MINIMAL + '\n[workspace]\n'
            'briefs_dir = "SessionBriefs"\n'
            'sheets_dir = "OutputSheets"\n'
            'perceptions_dir = "PlayerPerceptions"\n'))
        self.assertEqual(cfg.briefs_dir, "SessionBriefs")
        self.assertEqual(cfg.sheets_dir, "OutputSheets")
        self.assertEqual(cfg.perceptions_dir, "PlayerPerceptions")

    def test_type_dirs_defaults_to_the_conventional_mapping(self):
        cfg = _config.load(self._ws(MINIMAL))
        self.assertEqual(
            cfg.type_dirs,
            {"npc": "NPCs", "faction": "Factions", "place": "Setting"})

    def test_type_dirs_honours_explicit_override(self):
        cfg = _config.load(self._ws(
            MINIMAL + '\n[workspace.type_dirs]\n'
            'npc = "Persons"\nfaction = "Groups"\nplace = "Locations"\n'))
        self.assertEqual(
            cfg.type_dirs,
            {"npc": "Persons", "faction": "Groups", "place": "Locations"})

    def test_type_dirs_misspelled_key_raises_naming_it(self):
        # A misspelled key ("npcs" for "npc") must not silently fall back —
        # that is the defect class this whole phase exists to remove.
        cfg = self._ws(
            MINIMAL + '\n[workspace.type_dirs]\n'
            'npcs = "NPCs"\nfaction = "Factions"\nplace = "Setting"\n')
        with self.assertRaises(_config.ConfigError) as ctx:
            _config.load(cfg)
        self.assertIn("npcs", str(ctx.exception))

    def test_type_dirs_missing_key_raises_naming_it(self):
        cfg = self._ws(
            MINIMAL + '\n[workspace.type_dirs]\n'
            'npc = "NPCs"\nfaction = "Factions"\n')
        with self.assertRaises(_config.ConfigError) as ctx:
            _config.load(cfg)
        self.assertIn("place", str(ctx.exception))

    def test_type_dirs_wrong_value_type_raises(self):
        cfg = self._ws(
            MINIMAL + '\n[workspace.type_dirs]\n'
            'npc = 1\nfaction = "Factions"\nplace = "Setting"\n')
        with self.assertRaises(_config.ConfigError) as ctx:
            _config.load(cfg)
        self.assertIn("type_dirs", str(ctx.exception))

    def test_type_dirs_wrong_container_type_raises(self):
        # A list containing exactly the three correct key *strings* is the
        # discriminating input, not an arbitrary wrong type: set(raw) over
        # this particular list equals TYPE_DIR_KEYS, so without the
        # isinstance(dict) guard the key-set check passes silently and the
        # very next line (raw.values()) throws a bare AttributeError instead
        # of ConfigError — a list has no .values(). A generic "type_dirs"
        # substring check on the message can't tell that mutant from correct
        # behaviour (both the container-type message and the key-mismatch
        # message contain the word); asserting the specific container-type
        # wording, with this input, pins the guard itself.
        cfg = self._ws(MINIMAL + '\n[workspace]\ntype_dirs = ["npc", "faction", "place"]\n')
        with self.assertRaises(_config.ConfigError) as ctx:
            _config.load(cfg)
        self.assertIn("must be a table of strings", str(ctx.exception))


class TestWorkspace(unittest.TestCase):
    """Workspace bundles a root with the config loaded from it, so callers
    take one argument instead of two that could disagree."""

    def _ws(self, text: str) -> Path:
        d = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        (d / "campaign.toml").write_text(text, encoding="utf-8")
        return d

    def test_open_workspace_bundles_root_and_config(self):
        root = self._ws(MINIMAL)
        ws = _config.open_workspace(root)
        self.assertEqual(ws.root, root)
        self.assertEqual(ws.config.namespace, "testwiki")

    def test_open_workspace_config_matches_load(self):
        # The bundle must carry exactly what load() would return, not a
        # separately-derived or defaulted config.
        root = self._ws('[campaign]\nnamespace = "bm"\n\n[workspace]\n'
                        'entity_dirs = ["Places"]\n')
        self.assertEqual(_config.open_workspace(root).config,
                         _config.load(root))
        self.assertEqual(_config.open_workspace(root).config.entity_dirs,
                         ("Places",))

    def test_open_workspace_propagates_config_errors(self):
        d = Path(self.enterContext(tempfile.TemporaryDirectory()))
        with self.assertRaises(_config.ConfigError):
            _config.open_workspace(d)

    def test_open_workspace_with_no_argument_resolves_afresh(self):
        # The inverse of the identity test this replaces. That test pinned
        # the None branch to the module globals WORKSPACE/CONFIG, computed
        # once at import; those are gone, and the branch must now re-run
        # resolution on EVERY call.
        #
        # Two calls under two different environments, not one: a single call
        # cannot tell "resolves" from "caches". A cache built on first use —
        # an lru_cache, a module-level _CACHED, a default argument evaluated
        # at def time — is populated by this test's own first call and then
        # answers the second with the first workspace, and a one-call test
        # sees nothing wrong. (Verified: a caching implementation passes the
        # one-call form and fails this one.)
        first = self._ws('[campaign]\nnamespace = "first-workspace"\n')
        second = self._ws('[campaign]\nnamespace = "second-workspace"\n')
        with mock.patch.dict(os.environ, {"BUNNYFORGE_WORKSPACE": str(first)}):
            a = _config.open_workspace()
        with mock.patch.dict(os.environ, {"BUNNYFORGE_WORKSPACE": str(second)}):
            b = _config.open_workspace()
        self.assertEqual((a.root, a.config.namespace),
                         (first, "first-workspace"))
        self.assertEqual((b.root, b.config.namespace),
                         (second, "second-workspace"))

    def test_workspace_is_a_plain_value(self):
        # Two opens of the same root compare equal, so callers may pass it
        # around freely without identity surprises.
        root = self._ws(MINIMAL)
        self.assertEqual(_config.open_workspace(root),
                         _config.open_workspace(root))

    def test_open_workspace_resolves_a_relative_root(self):
        # This is the property resolve_workspace's docstring promises
        # ("explicit is used as given ... no walk", but still ends up
        # absolute) — proven here, at the level that actually performs it,
        # rather than at resolve_workspace, which merely delegates.
        root = self._ws(MINIMAL)
        # Build a deliberately-relative form the same way resolve_root's own
        # tests do, by relpath-ing from cwd.
        relpath = os.path.relpath(root, Path.cwd())
        self.assertFalse(Path(relpath).is_absolute())  # the input really is relative
        ws = _config.open_workspace(relpath)
        self.assertEqual(ws.root, root)
        self.assertTrue(ws.root.is_absolute())


class TestResolveWorkspace(unittest.TestCase):
    """The shared --workspace resolution helper every main() calls."""

    def _ws(self, text: str) -> Path:
        d = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        (d / "campaign.toml").write_text(text, encoding="utf-8")
        return d

    def test_explicit_path_wins_and_is_used_as_given(self):
        root = self._ws(MINIMAL)
        ws = _config.resolve_workspace(str(root))
        self.assertEqual(ws.root, root)
        self.assertEqual(ws.config.namespace, "testwiki")

    # NOTE: there is deliberately no
    # "resolve_workspace resolves a relative explicit path" test here.
    # resolve_workspace(explicit) hands `explicit` straight to
    # open_workspace(), which is the thing that actually resolves it
    # (Path(root).resolve() unconditionally, in open_workspace itself). A
    # test asserting resolve_workspace's *output* is absolute for a relative
    # input can't tell "resolve_workspace resolves" from "resolve_workspace
    # delegates to something that resolves" — mutating away a (redundant)
    # .resolve() call that used to live here left the whole suite green,
    # because open_workspace's own resolve() covers the same ground either
    # way. The property is real; it's just proven in the right place —
    # see TestWorkspace.test_open_workspace_resolves_a_relative_root below.

    def test_explicit_path_with_no_campaign_toml_is_an_error_not_a_search_hint(self):
        # Pointing --workspace at a directory with no campaign.toml must
        # raise, not walk up to find one above it.
        outer = self._ws(MINIMAL)
        empty_sub = outer / "no-marker-here"
        empty_sub.mkdir()
        with self.assertRaises(_config.ConfigError):
            _config.resolve_workspace(str(empty_sub))

    def test_no_explicit_argument_falls_back_to_resolve_root(self):
        root = self._ws(MINIMAL)
        with mock.patch.object(_config._workspace, "resolve_root",
                               return_value=root) as mocked:
            ws = _config.resolve_workspace(None)
        mocked.assert_called_once_with()
        self.assertEqual(ws.root, root)

    def test_empty_string_argument_also_falls_back_to_resolve_root(self):
        # Falsy, not just None, so an empty --workspace value behaves the
        # same as omitting the flag rather than resolving to cwd.
        root = self._ws(MINIMAL)
        with mock.patch.object(_config._workspace, "resolve_root",
                               return_value=root):
            ws = _config.resolve_workspace("")
        self.assertEqual(ws.root, root)


class TestWikiConfig(unittest.TestCase):
    def _load(self, toml_text):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "campaign.toml").write_text(toml_text, encoding="utf-8")
            return _config.load(root)

    def test_wiki_url_parsed(self):
        cfg = self._load('[campaign]\nnamespace = "test"\n'
                         '[wiki]\nurl = "https://wiki.example"\n')
        self.assertEqual(cfg.wiki_url, "https://wiki.example")

    def test_wiki_table_absent_is_none(self):
        cfg = self._load('[campaign]\nnamespace = "test"\n')
        self.assertIsNone(cfg.wiki_url)

    def test_wiki_url_non_string_refused(self):
        with self.assertRaises(_config.ConfigError):
            self._load('[campaign]\nnamespace = "test"\n[wiki]\nurl = 7\n')

    def test_wiki_non_table_refused(self):
        # `wiki = "x"` must precede any table header, same TOML-scoping trap
        # noted in TestConfigLoad.test_names_section_must_be_a_table: a bare
        # key after [campaign] would be swallowed into campaign.wiki rather
        # than staying a top-level `wiki` key, and this test would then
        # assert nothing.
        with self.assertRaises(_config.ConfigError):
            self._load('wiki = "x"\n[campaign]\nnamespace = "test"\n')


class TestWikiToken(unittest.TestCase):
    def _token_file(self, root: Path, text, mode=0o600):
        path = root / ".bunnyforge" / "wiki-token"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        path.chmod(mode)
        return path

    def test_env_wins(self):
        with tempfile.TemporaryDirectory() as d:
            self._token_file(Path(d), "filetoken\n")
            with unittest.mock.patch.dict(
                    os.environ, {"BUNNYFORGE_WIKI_TOKEN": "envtoken"}):
                self.assertEqual(_config.resolve_wiki_token(Path(d)), "envtoken")

    def test_file_fallback_strips_trailing_whitespace(self):
        with tempfile.TemporaryDirectory() as d:
            self._token_file(Path(d), "tok123\n")
            with unittest.mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("BUNNYFORGE_WIKI_TOKEN", None)
                self.assertEqual(_config.resolve_wiki_token(Path(d)), "tok123")

    def test_group_readable_file_refused_with_chmod_instruction(self):
        with tempfile.TemporaryDirectory() as d:
            self._token_file(Path(d), "tok123\n", mode=0o644)
            # Wrapped in patch.dict so the pop below is undone on exit
            # regardless of ambient state or test outcome — a bare pop with
            # no restore would permanently delete a pre-existing
            # BUNNYFORGE_WIKI_TOKEN from the test process for every test
            # that runs after this one.
            with unittest.mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("BUNNYFORGE_WIKI_TOKEN", None)
                with self.assertRaises(_config.ConfigError) as ctx:
                    _config.resolve_wiki_token(Path(d))
                self.assertIn("chmod 600", str(ctx.exception))

    def test_missing_both_names_both_sources(self):
        with tempfile.TemporaryDirectory() as d:
            # See test_group_readable_file_refused_with_chmod_instruction
            # above for why the pop is wrapped rather than bare.
            with unittest.mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("BUNNYFORGE_WIKI_TOKEN", None)
                with self.assertRaises(_config.ConfigError) as ctx:
                    _config.resolve_wiki_token(Path(d))
                msg = str(ctx.exception)
                self.assertIn("BUNNYFORGE_WIKI_TOKEN", msg)
                self.assertIn(".bunnyforge/wiki-token", msg)
                self.assertIn("API token", msg)  # says where a token comes from


if __name__ == "__main__":
    unittest.main()
