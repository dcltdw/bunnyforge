import hashlib
import json
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
        # The inbound directory is excluded by default, so material dropped
        # there is not readable back through read_entity: it serves canon.
        # (The drafts directory has the same boundary; see TestDraftReads.)
        ws = self.make_ws()
        dropped = ws.root / "_ExtractInbound"
        dropped.mkdir()
        (dropped / "secret.md").write_text("dropped", encoding="utf-8")
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


class TestSaveDraft(StoreCase):
    def test_writes_into_drafts_and_slugs_the_name(self):
        ws = self.make_ws()
        store = _store.WorkspaceStore(ws)
        rel = store.save_draft("NPCs", "Old Man Cho", "---\ntitle: Cho\n---\n")
        self.assertEqual(rel, "_AgentDrafts/NPCs/old-man-cho.md")
        self.assertTrue((ws.root / rel).is_file())

    def test_slug_drops_apostrophes_and_collapses_separators(self):
        store = _store.WorkspaceStore(self.make_ws())
        rel = store.save_draft("NPCs", "Mara's  Old_Friend", "x")
        self.assertEqual(rel, "_AgentDrafts/NPCs/maras-old-friend.md")

    def test_subdir_nests_one_level_and_is_slugged(self):
        # Briefs live at Briefs/session-NNN/<name>.md; a draft brief must be
        # able to take its canonical shape, or every promotion re-nests by
        # hand.
        ws = self.make_ws()
        rel = _store.WorkspaceStore(ws).save_draft(
            "Briefs", "Kim Ha-eun", "x", subdir="Session 15")
        self.assertEqual(rel, "_AgentDrafts/Briefs/session-15/kim-ha-eun.md")

    def test_existing_draft_refusal_names_update_draft(self):
        store = _store.WorkspaceStore(self.make_ws())
        store.save_draft("NPCs", "Cho", "x")
        with self.assertRaises(_store.StoreError) as ctx:
            store.save_draft("NPCs", "Cho", "y")
        self.assertIn("update_draft", str(ctx.exception))

    def test_canonical_collision_refusal_names_propose_revision(self):
        # A new draft shadowing an existing canonical file would be
        # misreported as a revision and reviewed as a diff against the
        # wrong entity.
        store = _store.WorkspaceStore(self.make_ws())
        with self.assertRaises(_store.StoreError) as ctx:
            store.save_draft("NPCs", "Kim Ha-eun", "x")  # slug: kim-ha-eun
        self.assertIn("propose_revision", str(ctx.exception))

    def test_refuses_unknown_section_and_bad_names(self):
        store = _store.WorkspaceStore(self.make_ws())
        with self.assertRaises(_store.StoreError):
            store.save_draft("Nope", "Cho", "x")
        for bad in ("../escape", "a/b", ".hidden", "_underscore"):
            with self.assertRaises(_store.StoreError):
                store.save_draft("NPCs", bad, "x")
            with self.assertRaises(_store.StoreError):
                store.save_draft("NPCs", "Cho", "x", subdir=bad)

    def test_perceptions_are_not_draftable(self):
        # The perception record is by contract never agent-authored.
        store = _store.WorkspaceStore(self.make_ws())
        with self.assertRaises(_store.StoreError) as ctx:
            store.save_draft("Perceptions", "Cho", "x")
        listed = str(ctx.exception).split("one of:")[1]
        self.assertNotIn("Perceptions", listed)
        self.assertIn("Briefs", listed)

    def test_honours_configured_drafts_dir(self):
        ws = self.make_ws('\n[workspace]\ndrafts_dir = "_Outbox"\n')
        rel = _store.WorkspaceStore(ws).save_draft("NPCs", "Cho", "x")
        self.assertEqual(rel, "_Outbox/NPCs/cho.md")


class TestProposeRevision(StoreCase):
    def test_shadow_mirrors_the_canonical_path_and_records_a_base(self):
        ws = self.make_ws()
        store = _store.WorkspaceStore(ws)
        rel = store.propose_revision("NPCs/kim-ha-eun.md", "new text")
        self.assertEqual(rel, "_AgentDrafts/NPCs/kim-ha-eun.md")
        self.assertEqual((ws.root / rel).read_text(encoding="utf-8"),
                         "new text")
        bases = json.loads(
            (ws.root / "_AgentDrafts" / ".proposal-bases.json")
            .read_text(encoding="utf-8"))
        canon_hash = hashlib.sha256(
            (ws.root / "NPCs/kim-ha-eun.md").read_bytes()).hexdigest()
        self.assertEqual(bases[rel], canon_hash)

    def test_second_proposal_is_refused_and_the_first_survives(self):
        # The old latest-wins rule silently destroyed pending proposals —
        # routine, not rare: the end-of-session ritual proposes front-burner
        # updates every session.
        ws = self.make_ws()
        store = _store.WorkspaceStore(ws)
        store.propose_revision("NPCs/kim-ha-eun.md", "first")
        with self.assertRaises(_store.StoreError) as ctx:
            store.propose_revision("NPCs/kim-ha-eun.md", "second")
        self.assertIn("update_draft", str(ctx.exception))
        self.assertEqual(
            (ws.root / "_AgentDrafts/NPCs/kim-ha-eun.md")
            .read_text(encoding="utf-8"), "first")

    def test_requires_an_existing_target_naming_save_draft(self):
        store = _store.WorkspaceStore(self.make_ws())
        with self.assertRaises(_store.StoreError) as ctx:
            store.propose_revision("NPCs/nobody.md", "x")
        self.assertIn("save_draft", str(ctx.exception))

    def test_refuses_escapes(self):
        store = _store.WorkspaceStore(self.make_ws())
        with self.assertRaises(_store.StoreError):
            store.propose_revision("../outside.md", "x")


class TestDraftReads(StoreCase):
    """The agents' own outbox: freely readable, so a draft written last
    session is revisited rather than re-invented."""

    def test_listing_reports_kind_title_and_summary(self):
        ws = self.make_ws()
        store = _store.WorkspaceStore(ws)
        store.save_draft("NPCs", "Cho",
                         "---\ntitle: Old Man Cho\n"
                         "summary: A dockside fixer.\n---\nbody\n")
        store.propose_revision("NPCs/kim-ha-eun.md", "y")
        rows = {r["path"]: r for r in store.list_drafts()}
        cho = rows["_AgentDrafts/NPCs/cho.md"]
        self.assertEqual(cho["kind"], "new")
        self.assertEqual(cho["title"], "Old Man Cho")
        self.assertEqual(cho["summary"], "A dockside fixer.")
        self.assertNotIn("stale", cho)          # stale is revision-only
        rev = rows["_AgentDrafts/NPCs/kim-ha-eun.md"]
        self.assertEqual(rev["kind"], "revision")
        self.assertIs(rev["stale"], False)

    def test_title_falls_back_to_the_stem(self):
        store = _store.WorkspaceStore(self.make_ws())
        store.save_draft("NPCs", "Cho", "no front matter\n")
        [row] = store.list_drafts()
        self.assertEqual(row["title"], "cho")
        self.assertEqual(row["summary"], "")

    def test_revision_goes_stale_when_canon_moves(self):
        # A pending shadow must not silently revert the GM's interim edits;
        # stale is how the listing warns, and promote_draft later refuses.
        ws = self.make_ws()
        store = _store.WorkspaceStore(ws)
        store.propose_revision("NPCs/kim-ha-eun.md", "proposal")
        (ws.root / "NPCs/kim-ha-eun.md").write_text("GM edit",
                                                    encoding="utf-8")
        [row] = store.list_drafts()
        self.assertIs(row["stale"], True)

    def test_unrecorded_base_reports_stale_none(self):
        ws = self.make_ws()
        shadow = ws.root / "_AgentDrafts" / "NPCs"
        shadow.mkdir(parents=True)
        (shadow / "kim-ha-eun.md").write_text("hand-made", encoding="utf-8")
        [row] = _store.WorkspaceStore(ws).list_drafts()
        self.assertIsNone(row["stale"])

    def test_corrupt_manifest_reads_as_empty_not_an_error(self):
        # The manifest is a provenance cache, not a lock file.
        ws = self.make_ws()
        store = _store.WorkspaceStore(ws)
        store.propose_revision("NPCs/kim-ha-eun.md", "proposal")
        (ws.root / "_AgentDrafts" / ".proposal-bases.json").write_text(
            "not json", encoding="utf-8")
        [row] = store.list_drafts()
        self.assertIsNone(row["stale"])

    def test_listing_skips_underscore_components(self):
        # _AgentDrafts/_Rejected/ is the GM's rejection signal — never
        # listed, so rejected material cannot be resurrected by resume.
        ws = self.make_ws()
        store = _store.WorkspaceStore(ws)
        store.save_draft("NPCs", "Cho", "x")
        rejected = ws.root / "_AgentDrafts" / "_Rejected"
        rejected.mkdir(parents=True)
        (rejected / "dead.md").write_text("x", encoding="utf-8")
        self.assertEqual([r["path"] for r in store.list_drafts()],
                         ["_AgentDrafts/NPCs/cho.md"])

    def test_nothing_drafted_is_an_empty_list_not_an_error(self):
        store = _store.WorkspaceStore(self.make_ws())
        self.assertEqual(store.list_drafts(), [])

    def test_read_round_trips_a_draft(self):
        store = _store.WorkspaceStore(self.make_ws())
        rel = store.save_draft("NPCs", "Cho", "---\ntitle: Cho\n---\nbody\n")
        self.assertEqual(store.read_draft(rel), "---\ntitle: Cho\n---\nbody\n")

    def test_escape_and_absolute_paths_are_refused(self):
        store = _store.WorkspaceStore(self.make_ws())
        with self.assertRaises(_store.StoreError):
            store.read_draft("_AgentDrafts/../../outside.md")
        with self.assertRaises(_store.StoreError):
            store.read_draft("/etc/hosts")

    def test_a_canonical_path_is_refused_and_points_at_read_entity(self):
        store = _store.WorkspaceStore(self.make_ws())
        with self.assertRaises(_store.StoreError) as ctx:
            store.read_draft("NPCs/kim-ha-eun.md")
        self.assertIn("read_entity", str(ctx.exception))

    def test_an_underscore_component_is_refused(self):
        ws = self.make_ws()
        rejected = ws.root / "_AgentDrafts" / "_Rejected"
        rejected.mkdir(parents=True)
        (rejected / "dead.md").write_text("x", encoding="utf-8")
        with self.assertRaises(_store.StoreError):
            _store.WorkspaceStore(ws).read_draft(
                "_AgentDrafts/_Rejected/dead.md")

    def test_missing_draft_is_refused_pointing_at_the_listing(self):
        store = _store.WorkspaceStore(self.make_ws())
        with self.assertRaises(_store.StoreError) as ctx:
            store.read_draft("_AgentDrafts/NPCs/nobody.md")
        self.assertIn("list_drafts", str(ctx.exception))

    def test_canon_tools_refuse_draft_paths(self):
        # The inverse boundary: _AgentDrafts is auto-excluded, so the
        # canon read door must refuse it exactly as it refuses _Ignore/.
        store = _store.WorkspaceStore(self.make_ws())
        rel = store.save_draft("NPCs", "Cho", "x")
        with self.assertRaises(_store.StoreError):
            store.read_entity(rel)


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
