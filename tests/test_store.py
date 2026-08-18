import hashlib
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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

    def make_archived_ws(self, toml_extra: str = "") -> _config.Workspace:
        """make_ws plus a mirrored archive: one archived NPC, and one
        stray file directly at the archive root (no mirror section)."""
        ws = self.make_ws(toml_extra)
        arch = ws.root / "Archive" / "NPCs"
        arch.mkdir(parents=True)
        (arch / "old-hag.md").write_text(
            "---\ntitle: The Old Hag\nsummary: Retired rival on the "
            "ferry route.\nstatus: retired\n---\n"
            "She haunted the ferry route.\n", encoding="utf-8")
        (ws.root / "Archive" / "stray.md").write_text(
            "---\ntitle: Stray\nsummary: A stray archived note.\n---\n"
            "ferry flotsam\n", encoding="utf-8")
        return ws


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

    def test_counts_pending_inbound_and_drafts(self):
        # Defined as exactly len(list_inbound()) / len(list_drafts()), so
        # a count and the listing it advertises cannot disagree. 0 when
        # the directory is absent: a count is always present, and
        # "nothing pending" is the true answer either way.
        ws = self.make_ws()
        store = _store.WorkspaceStore(ws)
        self.assertEqual(store.overview()["inbound_pending"], 0)
        self.assertEqual(store.overview()["drafts_pending"], 0)
        store.save_draft("NPCs", "Cho", "x")
        q = ws.root / "_ExtractInbound"
        (q / "_Done").mkdir(parents=True)
        (q / "idea.txt").write_text("x", encoding="utf-8")
        (q / "scan.pdf").write_bytes(b"%PDF")
        (q / "_Done" / "spent.txt").write_text("x", encoding="utf-8")
        ov = store.overview()
        self.assertEqual(ov["inbound_pending"], 2)  # pdf counted, _Done not
        self.assertEqual(ov["drafts_pending"], 1)

    def test_archive_is_a_section_of_its_own(self):
        # #62 fixed a latent contradiction: doctrine said "read the archive
        # freely" while the MCP surface refused it entirely. Now it lists,
        # reads, counts, and searches like any canon -- as its own section,
        # so live counts stay uninflated.
        ws = self.make_ws()
        arch = ws.root / "Archive" / "NPCs"
        arch.mkdir(parents=True)
        (arch / "old-hag.md").write_text(
            "---\ntitle: The Old Hag\nsummary: Retired rival of the ferry.\n"
            "visibility: gm-only\nstatus: retired\n---\ngone but recorded\n",
            encoding="utf-8")
        store = _store.WorkspaceStore(ws)
        ov = store.overview()
        self.assertEqual(ov["sections"]["NPCs"], 1)
        self.assertEqual(ov["sections"]["Archive"], 1)
        [row] = store.list_entities("Archive")
        self.assertEqual(row["path"], "Archive/NPCs/old-hag.md")
        self.assertEqual(row["title"], "The Old Hag")
        self.assertIn("recorded", store.read_entity("Archive/NPCs/old-hag.md"))
        hits = store.search("recorded", section="Archive")
        self.assertEqual(hits[0]["path"], "Archive/NPCs/old-hag.md")


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

    def test_machinery_paths_are_refused_as_not_canon(self):
        # #62: _-prefixed means not canon, and the canon tools serve canon.
        # This is the general rule that absorbed PR #61's propose_revision
        # guard -- refusal now happens at _canonical, one door for all.
        ws = self.make_ws()
        (ws.root / "NPCs" / "_notes.md").write_text("x", encoding="utf-8")
        store = _store.WorkspaceStore(ws)
        with self.assertRaises(_store.StoreError) as ctx:
            store.read_entity("NPCs/_notes.md")
        self.assertIn("not canon", str(ctx.exception))


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


class TestScopedSearch(StoreCase):
    """#66: scope: live | archive | both, section resolving inside the
    scope's tree(s), every hit labelled archived."""

    def test_default_scope_is_both_and_labels_every_hit(self):
        store = _store.WorkspaceStore(self.make_archived_ws())
        by_path = {h["path"]: h["archived"] for h in store.search("ferry")}
        self.assertEqual(by_path, {
            "NPCs/kim-ha-eun.md": False,
            "front-burner.md": False,
            "Archive/NPCs/old-hag.md": True,
            "Archive/stray.md": True,
        })

    def test_scope_live_excludes_archived_hits_keeps_root_docs(self):
        store = _store.WorkspaceStore(self.make_archived_ws())
        paths = {h["path"] for h in store.search("ferry", scope="live")}
        self.assertEqual(paths, {"NPCs/kim-ha-eun.md", "front-burner.md"})

    def test_scope_archive_returns_only_archived_hits(self):
        store = _store.WorkspaceStore(self.make_archived_ws())
        paths = {h["path"] for h in store.search("ferry", scope="archive")}
        self.assertEqual(paths,
                         {"Archive/NPCs/old-hag.md", "Archive/stray.md"})

    def test_sectioned_both_is_the_union_of_the_trees(self):
        # section="NPCs" covers NPCs/ AND Archive/NPCs/ under the default.
        store = _store.WorkspaceStore(self.make_archived_ws())
        paths = {h["path"] for h in store.search("ferry", section="NPCs")}
        self.assertEqual(paths,
                         {"NPCs/kim-ha-eun.md", "Archive/NPCs/old-hag.md"})

    def test_sectioned_archive_scope_resolves_the_mirror(self):
        store = _store.WorkspaceStore(self.make_archived_ws())
        hits = store.search("ferry", section="NPCs", scope="archive")
        self.assertEqual([h["path"] for h in hits],
                         ["Archive/NPCs/old-hag.md"])

    def test_sectioned_live_scope_stays_pure_live(self):
        store = _store.WorkspaceStore(self.make_archived_ws())
        hits = store.search("ferry", section="NPCs", scope="live")
        self.assertEqual([h["path"] for h in hits], ["NPCs/kim-ha-eun.md"])

    def test_section_archive_means_the_whole_archive(self):
        # Under "both" and "archive" alike; strays included.
        store = _store.WorkspaceStore(self.make_archived_ws())
        for scope in ("both", "archive"):
            paths = {h["path"] for h in
                     store.search("ferry", section="Archive", scope=scope)}
            self.assertEqual(
                paths, {"Archive/NPCs/old-hag.md", "Archive/stray.md"},
                scope)

    def test_a_stray_archive_file_is_in_no_mirror_section(self):
        # "flotsam" appears only in Archive/stray.md, which has no mirror.
        store = _store.WorkspaceStore(self.make_archived_ws())
        self.assertEqual(store.search("flotsam", section="NPCs"), [])
        self.assertEqual(
            [h["path"] for h in store.search("flotsam")],
            ["Archive/stray.md"])

    def test_scope_live_with_section_archive_is_a_refused_contradiction(self):
        store = _store.WorkspaceStore(self.make_archived_ws())
        with self.assertRaises(_store.StoreError) as ctx:
            store.search("ferry", section="Archive", scope="live")
        self.assertIn("contradicts", str(ctx.exception))
        self.assertIn("archive", str(ctx.exception).lower())

    def test_unknown_scope_is_refused_naming_the_valid_ones(self):
        store = _store.WorkspaceStore(self.make_archived_ws())
        with self.assertRaises(_store.StoreError) as ctx:
            store.search("ferry", scope="everything")
        for token in ("live", "archive", "both"):
            self.assertIn(token, str(ctx.exception))


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

    def test_slugged_refuses_an_empty_slug(self):
        # _DRAFT_NAME_RE's required leading alphanumeric is the only thing
        # that currently makes an empty slug impossible — nothing in _slug
        # or _slugged itself states or guards that invariant. Relax the
        # regex later (say, to admit non-ASCII names) and this would
        # silently start writing files named plain ".md". _slugged must
        # guard the invariant itself, not rely on the regex accidentally
        # holding it up.
        #
        # No input can both pass today's _DRAFT_NAME_RE and slug to empty
        # (the leading alnum char always survives _slug's substitutions),
        # so this test relaxes the regex the way a future change might, to
        # reach the guard through the real _slugged code path rather than
        # reimplementing its logic.
        store = _store.WorkspaceStore(self.make_ws())
        with mock.patch.object(_store, "_DRAFT_NAME_RE", re.compile(r".*")):
            with self.assertRaises(_store.StoreError) as ctx:
                store._slugged("___", "draft")
        self.assertIn("draft", str(ctx.exception))

    def test_archive_is_not_a_draftable_section(self):
        # New material never lands retired; archiving is a GM act. The
        # perceptions record has the same one-way property.
        store = _store.WorkspaceStore(self.make_ws())
        with self.assertRaises(_store.StoreError) as ctx:
            store.save_draft("Archive", "Old Thing", "x")
        self.assertIn("Archive", str(ctx.exception))


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

    def test_refuses_a_target_with_an_underscore_component(self):
        # The refusal moved from a bespoke guard into _canonical (#62):
        # a machinery-named path is not canon, so there is nothing to
        # propose against. The old lockout (a shadow stranded in the
        # drafts machinery area) is structurally impossible now.
        ws = self.make_ws()
        (ws.root / "NPCs" / "_notes.md").write_text("secret", encoding="utf-8")
        store = _store.WorkspaceStore(ws)
        with self.assertRaises(_store.StoreError) as ctx:
            store.propose_revision("NPCs/_notes.md", "x")
        self.assertIn("NPCs/_notes.md", str(ctx.exception))
        self.assertFalse((ws.root / "_AgentDrafts").exists())

    def test_refuses_a_target_with_a_dot_component(self):
        ws = self.make_ws()
        hidden = ws.root / "NPCs" / ".hidden"
        hidden.mkdir()
        (hidden / "notes.md").write_text("secret", encoding="utf-8")
        store = _store.WorkspaceStore(ws)
        with self.assertRaises(_store.StoreError) as ctx:
            store.propose_revision("NPCs/.hidden/notes.md", "x")
        self.assertIn("NPCs/.hidden/notes.md", str(ctx.exception))
        self.assertFalse((ws.root / "_AgentDrafts").exists())

    def test_archive_targets_are_ordinary_canon(self):
        # Spec decision: no write carve-out. A revision to an archived file
        # mirrors into the drafts tree like any canon target; the doctrine,
        # not the tools, governs when editing history is appropriate.
        ws = self.make_ws()
        arch = ws.root / "Archive" / "NPCs"
        arch.mkdir(parents=True)
        (arch / "old-hag.md").write_text(
            "---\ntitle: Old Hag\n---\nx", encoding="utf-8")
        store = _store.WorkspaceStore(ws)
        rel = store.propose_revision("Archive/NPCs/old-hag.md", "y")
        self.assertEqual(rel, "_AgentDrafts/Archive/NPCs/old-hag.md")


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

    def test_listing_skips_dot_components(self):
        ws = self.make_ws()
        store = _store.WorkspaceStore(ws)
        store.save_draft("NPCs", "Cho", "x")
        hidden = ws.root / "_AgentDrafts" / ".trash"
        hidden.mkdir(parents=True)
        (hidden / "old.md").write_text("x", encoding="utf-8")
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

    def test_a_dot_component_is_refused_like_an_underscore(self):
        # The two families disagreed: inbound skipped .-prefixed
        # components, drafts did not (#62). Unified: one predicate.
        ws = self.make_ws()
        hidden = ws.root / "_AgentDrafts" / ".obsidian"
        hidden.mkdir(parents=True)
        (hidden / "stray.md").write_text("x", encoding="utf-8")
        with self.assertRaises(_store.StoreError):
            _store.WorkspaceStore(ws).read_draft(
                "_AgentDrafts/.obsidian/stray.md")

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


class TestUpdateDraft(StoreCase):
    def test_overwrites_an_existing_draft(self):
        ws = self.make_ws()
        store = _store.WorkspaceStore(ws)
        rel = store.save_draft("NPCs", "Cho", "old")
        self.assertEqual(store.update_draft(rel, "new"), rel)
        self.assertEqual((ws.root / rel).read_text(encoding="utf-8"), "new")

    def test_missing_draft_is_refused_naming_save_draft(self):
        store = _store.WorkspaceStore(self.make_ws())
        with self.assertRaises(_store.StoreError) as ctx:
            store.update_draft("_AgentDrafts/NPCs/nobody.md", "x")
        self.assertIn("save_draft", str(ctx.exception))

    def test_canonical_and_escape_paths_are_refused(self):
        store = _store.WorkspaceStore(self.make_ws())
        with self.assertRaises(_store.StoreError):
            store.update_draft("NPCs/kim-ha-eun.md", "x")
        with self.assertRaises(_store.StoreError):
            store.update_draft("../outside.md", "x")

    def test_rebaselines_a_revision_shadow(self):
        # The refusal flow that leads here forced a read-and-merge, so the
        # agent has seen current canon: updating a shadow re-records its
        # base, and the revision stops being stale.
        ws = self.make_ws()
        store = _store.WorkspaceStore(ws)
        store.propose_revision("NPCs/kim-ha-eun.md", "first")
        (ws.root / "NPCs/kim-ha-eun.md").write_text("GM edit",
                                                    encoding="utf-8")
        self.assertIs(store.list_drafts()[0]["stale"], True)
        store.update_draft("_AgentDrafts/NPCs/kim-ha-eun.md", "merged")
        self.assertIs(store.list_drafts()[0]["stale"], False)

    def test_underscore_component_is_refused(self):
        ws = self.make_ws()
        rejected = ws.root / "_AgentDrafts" / "_Rejected"
        rejected.mkdir(parents=True)
        (rejected / "dead.md").write_text("x", encoding="utf-8")
        with self.assertRaises(_store.StoreError):
            _store.WorkspaceStore(ws).update_draft(
                "_AgentDrafts/_Rejected/dead.md", "resurrect")


class TestInbound(StoreCase):
    """The GM's inbound queue. Read-only, and only when the GM asks: the
    tool descriptions carry that contract; the store's job is that _Done/
    (and any _-prefixed area) is unreachable and every live file is
    honestly listed."""

    def seed_queue(self, ws) -> Path:
        q = ws.root / "_ExtractInbound"
        (q / "notes").mkdir(parents=True)
        (q / "notes" / "idea.txt").write_text(
            "a harbor heist", encoding="utf-8")
        (q / "page.html").write_text("<p>hi</p>", encoding="utf-8")
        (q / "README.md").write_text("readme", encoding="utf-8")
        (q / "scan.pdf").write_bytes(b"%PDF-1.4 not text")
        done = q / "_Done"
        done.mkdir()
        (done / "spent.txt").write_text("processed", encoding="utf-8")
        return q

    def test_lists_every_live_file_marking_readability(self):
        # ALL extensions are listed — a listing that hides files is the
        # defect this redesign fixes (17 of 18 files were invisible). A
        # PDF appears, honestly marked unreadable.
        ws = self.make_ws()
        self.seed_queue(ws)
        self.assertEqual(_store.WorkspaceStore(ws).list_inbound(), [
            {"path": "_ExtractInbound/README.md", "readable": True},
            {"path": "_ExtractInbound/notes/idea.txt", "readable": True},
            {"path": "_ExtractInbound/page.html", "readable": True},
            {"path": "_ExtractInbound/scan.pdf", "readable": False},
        ])

    def test_done_is_never_listed(self):
        # _Done/ holds processed source awaiting the GM's manual cleanup —
        # never read, exactly like _Ignore/. Tested before _Done/ exists
        # anywhere in the wild: this was the trap in the old rglob.
        ws = self.make_ws()
        self.seed_queue(ws)
        paths = [r["path"] for r in _store.WorkspaceStore(ws).list_inbound()]
        self.assertFalse(any("_Done" in p for p in paths))

    def test_hidden_dot_files_are_skipped(self):
        # .DS_Store and friends are machinery, not GM material; listing
        # them would inflate inbound_pending and clutter every offer.
        ws = self.make_ws()
        q = self.seed_queue(ws)
        (q / ".DS_Store").write_bytes(b"\x00")
        paths = [r["path"] for r in _store.WorkspaceStore(ws).list_inbound()]
        self.assertFalse(any(".DS_Store" in p for p in paths))

    def test_no_queue_is_an_empty_list_not_an_error(self):
        store = _store.WorkspaceStore(self.make_ws())
        self.assertEqual(store.list_inbound(), [])

    def test_read_round_trips_text(self):
        ws = self.make_ws()
        self.seed_queue(ws)
        store = _store.WorkspaceStore(ws)
        self.assertEqual(
            store.read_inbound("_ExtractInbound/notes/idea.txt"),
            "a harbor heist")

    def test_undecodable_bytes_are_replaced_not_a_crash(self):
        # Inbound material is generated elsewhere; one stray latin-1 byte
        # in a GM's .txt must not crash the tool.
        ws = self.make_ws()
        q = ws.root / "_ExtractInbound"
        q.mkdir()
        (q / "weird.txt").write_bytes(b"caf\xe9")
        out = _store.WorkspaceStore(ws).read_inbound(
            "_ExtractInbound/weird.txt")
        self.assertEqual(out, "caf�")

    def test_non_text_read_is_refused_with_the_convert_hint(self):
        ws = self.make_ws()
        self.seed_queue(ws)
        with self.assertRaises(_store.StoreError) as ctx:
            _store.WorkspaceStore(ws).read_inbound(
                "_ExtractInbound/scan.pdf")
        self.assertIn("convert", str(ctx.exception))

    def test_done_read_is_refused(self):
        ws = self.make_ws()
        self.seed_queue(ws)
        with self.assertRaises(_store.StoreError):
            _store.WorkspaceStore(ws).read_inbound(
                "_ExtractInbound/_Done/spent.txt")

    def test_canonical_path_is_refused_naming_read_entity(self):
        store = _store.WorkspaceStore(self.make_ws())
        with self.assertRaises(_store.StoreError) as ctx:
            store.read_inbound("NPCs/kim-ha-eun.md")
        self.assertIn("read_entity", str(ctx.exception))

    def test_escape_is_refused(self):
        store = _store.WorkspaceStore(self.make_ws())
        with self.assertRaises(_store.StoreError):
            store.read_inbound("_ExtractInbound/../../outside.md")

    def test_missing_file_is_refused_naming_the_listing(self):
        ws = self.make_ws()
        (ws.root / "_ExtractInbound").mkdir()
        with self.assertRaises(_store.StoreError) as ctx:
            _store.WorkspaceStore(ws).read_inbound(
                "_ExtractInbound/nothing.txt")
        self.assertIn("list_inbound", str(ctx.exception))

    def test_honours_configured_inbound_dir(self):
        ws = self.make_ws('\n[workspace]\ninbound_dir = "_Inbox"\n')
        q = ws.root / "_Inbox"
        q.mkdir()
        (q / "idea.txt").write_text("x", encoding="utf-8")
        rows = _store.WorkspaceStore(ws).list_inbound()
        self.assertEqual(rows, [{"path": "_Inbox/idea.txt",
                                 "readable": True}])


class TestPromoteDraft(StoreCase):
    """The GM's in-chat approval is the gate; the flag gates the
    capability per-run. The destination is derived — slugs made the
    drafts tree mirror canon — so there is no dest parameter to get
    wrong."""

    def make_git_ws(self):
        ws = self.make_ws()
        for cmd in (["init", "-q"], ["config", "user.email", "t@t"],
                    ["config", "user.name", "t"], ["add", "-A"],
                    ["commit", "-qm", "seed"]):
            subprocess.run(["git", "-C", str(ws.root)] + cmd, check=True)
        return ws

    def _git(self, ws, *args) -> str:
        return subprocess.run(["git", "-C", str(ws.root), *args],
                              capture_output=True, text=True,
                              check=True).stdout

    def test_promotes_a_new_draft_and_commits(self):
        ws = self.make_git_ws()
        store = _store.WorkspaceStore(ws)
        rel = store.save_draft("Ideas", "Harbor Heist",
                               "---\ntitle: Harbor Heist\n---\nplot\n")
        out = store.promote_draft(rel)
        self.assertEqual(out, "Ideas/harbor-heist.md")
        self.assertIn("plot", (ws.root / out).read_text(encoding="utf-8"))
        self.assertFalse((ws.root / rel).exists())
        self.assertIn("serve-mcp: promote Ideas/harbor-heist.md",
                      self._git(ws, "log", "-1", "--format=%s"))
        self.assertEqual(self._git(ws, "status", "--porcelain").strip(), "")

    def test_promotes_a_fresh_revision_and_clears_its_base(self):
        ws = self.make_git_ws()
        store = _store.WorkspaceStore(ws)
        rel = store.propose_revision("NPCs/kim-ha-eun.md", "improved text")
        out = store.promote_draft(rel)
        self.assertEqual(out, "NPCs/kim-ha-eun.md")
        self.assertEqual((ws.root / out).read_text(encoding="utf-8"),
                         "improved text")
        self.assertFalse((ws.root / rel).exists())
        bases = json.loads(
            (ws.root / "_AgentDrafts" / ".proposal-bases.json")
            .read_text(encoding="utf-8"))
        self.assertEqual(bases, {})
        self.assertEqual(self._git(ws, "status", "--porcelain").strip(), "")

    def test_stale_revision_is_refused_not_applied(self):
        # Promoting a stale shadow would revert the GM's interim edits,
        # disguised inside an intended diff.
        ws = self.make_git_ws()
        store = _store.WorkspaceStore(ws)
        rel = store.propose_revision("NPCs/kim-ha-eun.md", "proposal")
        (ws.root / "NPCs/kim-ha-eun.md").write_text("GM edit",
                                                    encoding="utf-8")
        with self.assertRaises(_store.StoreError) as ctx:
            store.promote_draft(rel)
        self.assertIn("update_draft", str(ctx.exception))
        self.assertEqual(
            (ws.root / "NPCs/kim-ha-eun.md").read_text(encoding="utf-8"),
            "GM edit")  # canon untouched

    def test_unrecorded_base_is_refused(self):
        # Covers a hand-authored shadow AND a draft whose canonical
        # counterpart appeared after it was saved: target exists, no base
        # on record, so promotion cannot verify and refuses.
        ws = self.make_git_ws()
        store = _store.WorkspaceStore(ws)
        shadow = ws.root / "_AgentDrafts" / "NPCs"
        shadow.mkdir(parents=True)
        (shadow / "kim-ha-eun.md").write_text("hand-made", encoding="utf-8")
        with self.assertRaises(_store.StoreError):
            store.promote_draft("_AgentDrafts/NPCs/kim-ha-eun.md")

    def test_refuses_outside_a_git_repo_before_touching_anything(self):
        ws = self.make_ws()  # no git init
        store = _store.WorkspaceStore(ws)
        rel = store.save_draft("Ideas", "Heist", "plot")
        with self.assertRaises(_store.StoreError) as ctx:
            store.promote_draft(rel)
        self.assertIn("git", str(ctx.exception))
        self.assertTrue((ws.root / rel).is_file())   # draft still there
        self.assertFalse((ws.root / "Ideas/heist.md").exists())

    def test_missing_draft_is_refused(self):
        store = _store.WorkspaceStore(self.make_git_ws())
        with self.assertRaises(_store.StoreError) as ctx:
            store.promote_draft("_AgentDrafts/Ideas/nothing.md")
        self.assertIn("list_drafts", str(ctx.exception))

    def test_promoting_a_new_draft_never_creates_a_manifest(self):
        # In a workspace where no revision was ever proposed, _load_bases()
        # returns {}, the pop is a no-op, and an unconditional _save_bases
        # would still *create* .proposal-bases.json containing "{}" — a
        # file that never existed before, committed into a promotion whose
        # own comment says it adds "exactly what promotion touched".
        ws = self.make_git_ws()
        store = _store.WorkspaceStore(ws)
        rel = store.save_draft("Ideas", "Harbor Heist",
                               "---\ntitle: Harbor Heist\n---\nplot\n")
        store.promote_draft(rel)
        self.assertFalse(
            (ws.root / "_AgentDrafts" / ".proposal-bases.json").exists())
        self.assertEqual(self._git(ws, "status", "--porcelain").strip(), "")
