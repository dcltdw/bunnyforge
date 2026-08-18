import subprocess
import tempfile
import unittest
from pathlib import Path

from bunnyforge import _config, _store

MINIMAL = '[campaign]\nnamespace = "testwiki"\nname = "Testmere"\n'

NPC = """---
title: Kim Ha-eun
summary: Kim Ha-eun is a ferry captain in Testmere harbor.
visibility: gm-only
---
She knows the tides and owes the Harbormasters a debt.
"""


class StoreCase(unittest.TestCase):
    """A scaffolded temp workspace shared by the store tests."""

    def make_ws(self, toml_extra: str = "") -> _config.Workspace:
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (root / "campaign.toml").write_text(
            MINIMAL + toml_extra, encoding="utf-8")
        (root / "NPCs").mkdir()
        (root / "NPCs" / "kim-ha-eun.md").write_text(NPC, encoding="utf-8")
        (root / "front-burner.md").write_text(
            "- resolve the ferry plot\n", encoding="utf-8")
        return _config.open_workspace(root)


class TestOverview(StoreCase):

    def test_reports_name_sections_and_burner(self):
        store = _store.WorkspaceStore(self.make_ws())
        ov = store.overview()
        self.assertEqual(ov["name"], "Testmere")
        self.assertEqual(ov["sections"]["NPCs"], 1)
        self.assertIn("ferry plot", ov["front_burner"])
        self.assertIsNone(ov["open_questions"])

    def test_counts_agree_with_list_entities(self):
        # An overview count and the list it promises must never disagree.
        # A bare rglob would count a file inside an excluded subdirectory
        # that list_entities then omits, so the two are derived from one
        # walk rather than from two that can drift.
        ws = self.make_ws()
        archived = ws.root / "NPCs" / "_Archive"
        archived.mkdir()
        (archived / "old.md").write_text(NPC, encoding="utf-8")
        store = _store.WorkspaceStore(ws)
        self.assertEqual(store.overview()["sections"]["NPCs"], 1)
        self.assertEqual(len(store.list_entities("NPCs")), 1)

    def test_existing_but_empty_section_reports_zero(self):
        ws = self.make_ws()
        (ws.root / "Factions").mkdir()
        store = _store.WorkspaceStore(ws)
        self.assertEqual(store.overview()["sections"]["Factions"], 0)

    def test_absent_section_is_omitted_not_zero(self):
        # A directory the campaign has not created yet is not a section with
        # nothing in it; saying "Factions: 0" would invite the agent to treat
        # an unused part of the layout as an empty one.
        store = _store.WorkspaceStore(self.make_ws())
        self.assertNotIn("Factions", store.overview()["sections"])


class TestListEntities(StoreCase):

    def test_lists_title_and_summary(self):
        store = _store.WorkspaceStore(self.make_ws())
        self.assertEqual(store.list_entities("NPCs"), [{
            "path": "NPCs/kim-ha-eun.md",
            "title": "Kim Ha-eun",
            "summary": "Kim Ha-eun is a ferry captain in Testmere harbor.",
        }])

    def test_title_falls_back_to_the_stem(self):
        ws = self.make_ws()
        (ws.root / "NPCs" / "no-front-matter.md").write_text(
            "just a body\n", encoding="utf-8")
        store = _store.WorkspaceStore(ws)
        found = {e["path"]: e for e in store.list_entities("NPCs")}
        self.assertEqual(found["NPCs/no-front-matter.md"]["title"],
                         "no-front-matter")
        self.assertEqual(found["NPCs/no-front-matter.md"]["summary"], "")

    def test_unknown_section_raises_listing_the_valid_ones(self):
        store = _store.WorkspaceStore(self.make_ws())
        with self.assertRaises(_store.StoreError) as ctx:
            store.list_entities("Nope")
        self.assertIn("NPCs", str(ctx.exception))


class TestReadEntity(StoreCase):

    def test_reads_full_file_including_front_matter(self):
        store = _store.WorkspaceStore(self.make_ws())
        text = store.read_entity("NPCs/kim-ha-eun.md")
        self.assertIn("title: Kim Ha-eun", text)
        self.assertIn("owes the Harbormasters", text)

    def test_escape_is_refused(self):
        store = _store.WorkspaceStore(self.make_ws())
        with self.assertRaises(_store.StoreError):
            store.read_entity("../outside.md")

    def test_absolute_path_outside_the_workspace_is_refused(self):
        store = _store.WorkspaceStore(self.make_ws())
        with self.assertRaises(_store.StoreError):
            store.read_entity("/etc/hosts")

    def test_excluded_dir_is_refused(self):
        # The staging directory is excluded by default, so drafts written
        # there are not readable back through read_entity: it serves canon.
        # Staging is reached through read_staged instead (TestStagingReads).
        ws = self.make_ws()
        staged = ws.root / "_ExtractInbound"
        staged.mkdir()
        (staged / "secret.md").write_text("staged", encoding="utf-8")
        store = _store.WorkspaceStore(ws)
        with self.assertRaises(_store.StoreError):
            store.read_entity("_ExtractInbound/secret.md")

    def test_missing_file_is_refused(self):
        store = _store.WorkspaceStore(self.make_ws())
        with self.assertRaises(_store.StoreError):
            store.read_entity("NPCs/nobody.md")


class TestSearch(StoreCase):

    def test_hit_returns_path_and_snippet(self):
        store = _store.WorkspaceStore(self.make_ws())
        hits = store.search("harbormasters")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["path"], "NPCs/kim-ha-eun.md")
        self.assertIn("owes the Harbormasters", hits[0]["snippet"])

    def test_search_is_case_insensitive_and_spans_root_docs(self):
        store = _store.WorkspaceStore(self.make_ws())
        paths = {h["path"] for h in store.search("FERRY")}
        self.assertEqual(paths, {"NPCs/kim-ha-eun.md", "front-burner.md"})

    def test_section_filter_narrows_to_that_directory(self):
        store = _store.WorkspaceStore(self.make_ws())
        hits = store.search("ferry", section="NPCs")
        self.assertEqual([h["path"] for h in hits], ["NPCs/kim-ha-eun.md"])

    def test_bad_section_raises(self):
        store = _store.WorkspaceStore(self.make_ws())
        with self.assertRaises(_store.StoreError):
            store.search("ferry", section="Nope")

    def test_empty_query_raises(self):
        store = _store.WorkspaceStore(self.make_ws())
        with self.assertRaises(_store.StoreError):
            store.search("   ")

    def test_no_match_is_an_empty_list_not_an_error(self):
        store = _store.WorkspaceStore(self.make_ws())
        self.assertEqual(store.search("nothing here says this"), [])



# A self-contained culture, built here rather than copied from the shipped
# inventories: a portable test builds its own fixtures, and this one then
# cannot break when the packaged cultures change. Minimal but valid --
# `name` plus the four required keys, plus given_<category> for the one
# declared category.
CULTURE = """
name            = "Testland"
categories      = ["personal"]
family          = ["Alba", "Bern", "Cass", "Dorn"]
given_personal  = ["ka", "lo", "mi", "ru", "ta"]
place           = ["Ash", "Bel", "Cor", "Dun"]
place_tail      = ["ford", "mere", "wick", "holm"]
"""


class TestGenerateNames(StoreCase):

    def make_names_ws(self) -> _config.Workspace:
        ws = self.make_ws('\n[names]\ncultures = "cultures"\n')
        cultures = ws.root / "cultures"
        cultures.mkdir()
        (cultures / "testland.toml").write_text(CULTURE, encoding="utf-8")
        return ws

    def test_generates_people_and_places(self):
        store = _store.WorkspaceStore(self.make_names_ws())
        out = store.generate_names("Testland", 5)
        self.assertEqual(out["culture"], "testland")
        self.assertEqual(len(out["people"]), 5)
        self.assertEqual(len(out["places"]), 5)
        self.assertTrue(all(isinstance(n, str) and n.strip()
                            for n in out["people"] + out["places"]))

    def test_names_are_drawn_from_this_culture_only(self):
        # The generator's whole promise is that a name belongs to its
        # culture; a family name from nowhere in the inventory would mean
        # the wrong culture was resolved.
        store = _store.WorkspaceStore(self.make_names_ws())
        out = store.generate_names("Testland", 10)
        for person in out["people"]:
            self.assertIn(person.split()[0],
                          ["Alba", "Bern", "Cass", "Dorn"], person)

    def test_unknown_culture_raises_listing_the_available_ones(self):
        store = _store.WorkspaceStore(self.make_names_ws())
        with self.assertRaises(_store.StoreError) as ctx:
            store.generate_names("martian", 3)
        self.assertIn("testland", str(ctx.exception))

    def test_unconfigured_names_is_a_store_error_not_a_crash(self):
        # No [names] at all: the remote agent must get an explainable
        # refusal, not an InventoryError leaking through the tool layer.
        store = _store.WorkspaceStore(self.make_ws())
        with self.assertRaises(_store.StoreError):
            store.generate_names("testland", 3)

    def test_count_is_clamped_at_both_ends(self):
        store = _store.WorkspaceStore(self.make_names_ws())
        self.assertEqual(len(store.generate_names("Testland", 999)["people"]),
                         _store.NAME_COUNT_CAP)
        self.assertEqual(len(store.generate_names("Testland", 0)["people"]), 1)


if __name__ == "__main__":
    unittest.main()


class TestStageDraft(StoreCase):
    def test_writes_into_staging_and_creates_dirs(self):
        ws = self.make_ws()
        store = _store.WorkspaceStore(ws)
        rel = store.stage_draft("NPCs", "Old Man Cho", "---\ntitle: Cho\n---\n")
        self.assertEqual(rel, "_ExtractInbound/NPCs/Old Man Cho.md")
        self.assertTrue((ws.root / rel).is_file())

    def test_refuses_overwrite(self):
        store = _store.WorkspaceStore(self.make_ws())
        store.stage_draft("NPCs", "Cho", "x")
        with self.assertRaises(_store.StoreError) as ctx:
            store.stage_draft("NPCs", "Cho", "y")
        self.assertIn("another name", str(ctx.exception))

    def test_refuses_unknown_section_and_bad_names(self):
        store = _store.WorkspaceStore(self.make_ws())
        with self.assertRaises(_store.StoreError):
            store.stage_draft("Nope", "Cho", "x")
        for bad in ("../escape", "a/b", ".hidden", "_underscore"):
            with self.assertRaises(_store.StoreError):
                store.stage_draft("NPCs", bad, "x")

    def test_honors_configured_staging_dir(self):
        ws = self.make_ws('\n[workspace]\ninbound_dir = "_Inbox"\n')
        rel = _store.WorkspaceStore(ws).stage_draft("NPCs", "Cho", "x")
        self.assertEqual(rel, "_Inbox/NPCs/Cho.md")


class TestStageRevision(StoreCase):
    def test_shadow_mirrors_the_canonical_path(self):
        ws = self.make_ws()
        store = _store.WorkspaceStore(ws)
        rel = store.stage_revision("NPCs/kim-ha-eun.md", "new text")
        self.assertEqual(rel, "_ExtractInbound/NPCs/kim-ha-eun.md")
        self.assertEqual((ws.root / rel).read_text(encoding="utf-8"),
                         "new text")

    def test_latest_proposal_wins(self):
        ws = self.make_ws()
        store = _store.WorkspaceStore(ws)
        store.stage_revision("NPCs/kim-ha-eun.md", "first")
        rel = store.stage_revision("NPCs/kim-ha-eun.md", "second")
        self.assertEqual((ws.root / rel).read_text(encoding="utf-8"),
                         "second")

    def test_requires_an_existing_target(self):
        store = _store.WorkspaceStore(self.make_ws())
        with self.assertRaises(_store.StoreError) as ctx:
            store.stage_revision("NPCs/nobody.md", "x")
        self.assertIn("stage_draft", str(ctx.exception))  # points at the fix

    def test_refuses_escapes(self):
        store = _store.WorkspaceStore(self.make_ws())
        with self.assertRaises(_store.StoreError):
            store.stage_revision("../outside.md", "x")


class TestStagingReads(StoreCase):
    """The agent's own inbox. Staging stays invisible to the canon read
    tools; these two methods are the one labelled way back in, so that a
    draft written last session can be revisited rather than re-invented.
    """

    def test_listing_distinguishes_a_draft_from_a_revision(self):
        store = _store.WorkspaceStore(self.make_ws())
        store.stage_draft("NPCs", "Cho", "x")
        store.stage_revision("NPCs/kim-ha-eun.md", "y")
        found = {e["path"]: e["kind"] for e in store.list_staging()}
        self.assertEqual(found, {
            "_ExtractInbound/NPCs/Cho.md": "draft",
            "_ExtractInbound/NPCs/kim-ha-eun.md": "revision",
        })

    def test_nothing_staged_is_an_empty_list_not_an_error(self):
        # The staging directory does not exist until something is staged.
        store = _store.WorkspaceStore(self.make_ws())
        self.assertEqual(store.list_staging(), [])

    def test_listing_ignores_non_markdown(self):
        ws = self.make_ws()
        store = _store.WorkspaceStore(ws)
        store.stage_draft("NPCs", "Cho", "x")
        (ws.root / "_ExtractInbound" / "notes.txt").write_text(
            "scratch", encoding="utf-8")
        self.assertEqual([e["path"] for e in store.list_staging()],
                         ["_ExtractInbound/NPCs/Cho.md"])

    def test_listing_honors_a_configured_staging_dir(self):
        ws = self.make_ws('\n[workspace]\ninbound_dir = "_Inbox"\n')
        store = _store.WorkspaceStore(ws)
        store.stage_draft("NPCs", "Cho", "x")
        self.assertEqual([e["path"] for e in store.list_staging()],
                         ["_Inbox/NPCs/Cho.md"])

    def test_read_round_trips_a_staged_file(self):
        store = _store.WorkspaceStore(self.make_ws())
        rel = store.stage_draft("NPCs", "Cho", "---\ntitle: Cho\n---\nbody\n")
        self.assertEqual(store.read_staged(rel),
                         "---\ntitle: Cho\n---\nbody\n")

    def test_escape_is_refused(self):
        store = _store.WorkspaceStore(self.make_ws())
        with self.assertRaises(_store.StoreError):
            store.read_staged("_ExtractInbound/../../outside.md")

    def test_absolute_path_outside_the_workspace_is_refused(self):
        store = _store.WorkspaceStore(self.make_ws())
        with self.assertRaises(_store.StoreError):
            store.read_staged("/etc/hosts")

    def test_a_canonical_path_is_refused_and_points_at_read_entity(self):
        # The inverse guard: read_staged serves staging and nothing else, so
        # canon reaches the agent through one method only.
        store = _store.WorkspaceStore(self.make_ws())
        with self.assertRaises(_store.StoreError) as ctx:
            store.read_staged("NPCs/kim-ha-eun.md")
        self.assertIn("read_entity", str(ctx.exception))

    def test_missing_file_is_refused_pointing_at_the_listing(self):
        store = _store.WorkspaceStore(self.make_ws())
        with self.assertRaises(_store.StoreError) as ctx:
            store.read_staged("_ExtractInbound/NPCs/nobody.md")
        self.assertIn("list_staged", str(ctx.exception))

    def test_a_non_markdown_staged_file_is_refused(self):
        ws = self.make_ws()
        (ws.root / "_ExtractInbound").mkdir()
        (ws.root / "_ExtractInbound" / "notes.txt").write_text(
            "scratch", encoding="utf-8")
        with self.assertRaises(_store.StoreError):
            _store.WorkspaceStore(ws).read_staged("_ExtractInbound/notes.txt")


class TestWriteEntity(StoreCase):
    def make_git_ws(self):
        ws = self.make_ws()
        for cmd in (["init", "-q"], ["config", "user.email", "t@t"],
                    ["config", "user.name", "t"], ["add", "-A"],
                    ["commit", "-qm", "seed"]):
            subprocess.run(["git", "-C", str(ws.root)] + cmd, check=True)
        return ws

    def test_edits_and_commits(self):
        ws = self.make_git_ws()
        store = _store.WorkspaceStore(ws)
        store.write_entity("NPCs/kim-ha-eun.md", "---\ntitle: X\n---\nnew\n")
        self.assertIn("new", (ws.root / "NPCs/kim-ha-eun.md").read_text(
            encoding="utf-8"))
        log = subprocess.run(
            ["git", "-C", str(ws.root), "log", "-1", "--format=%s"],
            capture_output=True, text=True, check=True).stdout
        self.assertIn("serve-mcp: edit NPCs/kim-ha-eun.md", log)
        status = subprocess.run(
            ["git", "-C", str(ws.root), "status", "--porcelain"],
            capture_output=True, text=True, check=True).stdout
        self.assertEqual(status.strip(), "")  # nothing left uncommitted

    def test_identical_content_is_a_quiet_no_op(self):
        ws = self.make_git_ws()
        store = _store.WorkspaceStore(ws)
        original = (ws.root / "NPCs/kim-ha-eun.md").read_text(encoding="utf-8")
        store.write_entity("NPCs/kim-ha-eun.md", original)  # must not raise

    def test_refuses_outside_a_git_repo(self):
        store = _store.WorkspaceStore(self.make_ws())  # no git init
        with self.assertRaises(_store.StoreError) as ctx:
            store.write_entity("NPCs/kim-ha-eun.md", "x")
        self.assertIn("git", str(ctx.exception))

    def test_refuses_missing_target_and_escapes(self):
        store = _store.WorkspaceStore(self.make_git_ws())
        with self.assertRaises(_store.StoreError):
            store.write_entity("NPCs/nobody.md", "x")
        with self.assertRaises(_store.StoreError):
            store.write_entity("../outside.md", "x")
