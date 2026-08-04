"""Parser tests for _dokuwiki_install, against fabricated install trees.

Every test builds its own DokuWiki-shaped directory in a temp dir. Nothing
here reads a real install, and nothing names a real campaign's namespaces or
groups — these parsers are generic by design.
"""

import tempfile
import unittest
from pathlib import Path

from bunnyforge import _dokuwiki_install as dwi


def make_install(root: Path, *, dokuwiki_php: str = "", local_php: str | None = None,
                 protected_php: str | None = None, acl: str | None = None,
                 plugins: tuple[str, ...] = (),
                 plugins_local_php: str | None = None) -> Path:
    """Fabricate a DokuWiki install tree. Only what a test names is written."""
    conf = root / "conf"
    conf.mkdir(parents=True, exist_ok=True)
    (root / "lib" / "plugins").mkdir(parents=True, exist_ok=True)
    (conf / "dokuwiki.php").write_text("<?php\n" + dokuwiki_php, encoding="utf-8")
    if local_php is not None:
        (conf / "local.php").write_text("<?php\n" + local_php, encoding="utf-8")
    if protected_php is not None:
        (conf / "local.protected.php").write_text(
            "<?php\n" + protected_php, encoding="utf-8")
    if acl is not None:
        (conf / "acl.auth.php").write_text(acl, encoding="utf-8")
    for name in plugins:
        (root / "lib" / "plugins" / name).mkdir(parents=True, exist_ok=True)
    if plugins_local_php is not None:
        (conf / "plugins.local.php").write_text(
            "<?php\n" + plugins_local_php, encoding="utf-8")
    return root


class TestCheckRoot(unittest.TestCase):
    def test_a_directory_without_conf_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(dwi.InstallError) as ctx:
                dwi.check_root(Path(d))
            self.assertIn("conf", str(ctx.exception))

    def test_a_real_looking_install_is_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            dwi.check_root(make_install(Path(d)))


class TestReadConf(unittest.TestCase):
    def test_local_php_overrides_dokuwiki_php_and_records_provenance(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_install(Path(d),
                                dokuwiki_php="$conf['useacl'] = 0;\n",
                                local_php="$conf['useacl'] = 1;\n")
            conf = dwi.read_conf(root)
            self.assertEqual(conf["useacl"].value, 1)
            self.assertEqual(conf["useacl"].source, "local.php")

    def test_a_value_only_in_dokuwiki_php_is_sourced_there(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_install(Path(d), dokuwiki_php="$conf['useacl'] = 1;\n")
            conf = dwi.read_conf(root)
            self.assertEqual(conf["useacl"].value, 1)
            self.assertEqual(conf["useacl"].source, "dokuwiki.php")

    def test_local_protected_php_wins_over_local_php(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_install(Path(d), local_php="$conf['useacl'] = 1;\n",
                                protected_php="$conf['useacl'] = 0;\n")
            self.assertEqual(dwi.read_conf(root)["useacl"].source,
                             "local.protected.php")

    def test_quoted_string_values_are_unquoted(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_install(Path(d),
                                local_php="$conf['useheading'] = 'navigation';\n")
            self.assertEqual(dwi.read_conf(root)["useheading"].value, "navigation")

    def test_commented_out_assignments_are_ignored(self):
        # The stock dokuwiki.php is full of these; treating one as live would
        # report a value the wiki is not actually using.
        with tempfile.TemporaryDirectory() as d:
            root = make_install(Path(d),
                                dokuwiki_php="$conf['useacl'] = 1;\n",
                                local_php="#$conf['useacl'] = 0;\n"
                                          "// $conf['useacl'] = 0;\n")
            self.assertEqual(dwi.read_conf(root)["useacl"].source, "dokuwiki.php")

    def test_array_subkeys_do_not_collide_with_plain_keys(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_install(
                Path(d),
                local_php="$conf['plugin']['include']['noheader'] = 1;\n"
                          "$conf['useacl'] = 1;\n")
            conf = dwi.read_conf(root)
            self.assertEqual(conf["useacl"].value, 1)
            self.assertNotIn("plugin", conf)


class TestReadAcl(unittest.TestCase):
    def test_rules_are_parsed_with_levels_as_ints(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_install(Path(d), acl="# comment\n*\t@ALL\t0\nns:*\t@team\t2\n")
            rules = dwi.read_acl(root)
            self.assertIn(dwi.AclRule("*", "@ALL", 0), rules)
            self.assertIn(dwi.AclRule("ns:*", "@team", 2), rules)

    def test_comments_and_blank_lines_are_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_install(Path(d),
                                acl="# acl.auth.php\n\n#ns:* @x 1\nns:* @y 1\n")
            self.assertEqual(dwi.read_acl(root), [dwi.AclRule("ns:*", "@y", 1)])

    def test_urlencoded_principals_are_decoded(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_install(Path(d), acl="ns:*\t@a%20team\t1\n")
            self.assertEqual(dwi.read_acl(root)[0].principal, "@a team")

    def test_a_missing_acl_file_reads_as_no_rules(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(dwi.read_acl(make_install(Path(d))), [])


class TestPluginState(unittest.TestCase):
    def test_installed_and_enabled_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_install(Path(d), plugins=("include",))
            self.assertEqual(dwi.plugin_state(root, "include"), (True, True))

    def test_absent_plugin_is_neither(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(dwi.plugin_state(make_install(Path(d)), "include"),
                             (False, False))

    def test_installed_but_explicitly_disabled(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_install(Path(d), plugins=("include",),
                                plugins_local_php="$plugins['include'] = 0;\n")
            self.assertEqual(dwi.plugin_state(root, "include"), (True, False))

    def test_explicitly_enabled_stays_enabled(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_install(Path(d), plugins=("include",),
                                plugins_local_php="$plugins['include'] = 1;\n")
            self.assertEqual(dwi.plugin_state(root, "include"), (True, True))


if __name__ == "__main__":
    unittest.main()
