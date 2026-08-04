# A worked campaign test: every NPC's faction exists as a file.
#
# It ships switched off. To enable it, delete the leading "# " from every
# line below this header, then run:  bunnyforge test
#
# It passes on an empty campaign -- it checks whatever NPCs exist, and an
# NPC that names no faction is skipped -- so turning it on is always safe.
#
# To write your own, copy this file to test_<something>.py and change what
# the assert checks. See README.md in this folder.
#
# import re
# import unittest
# from pathlib import Path
#
# # This file lives in <campaign>/tests/, so the campaign is one level up.
# CAMPAIGN = Path(__file__).resolve().parent.parent
#
#
# def front_matter_field(path, field):
#     """The value of `field:` in a file's front matter, or None."""
#     lines = path.read_text(encoding="utf-8").splitlines()
#     if not lines or lines[0].strip() != "---":
#         return None
#     for line in lines[1:]:
#         if line.strip() == "---":
#             return None
#         match = re.match(rf"{field}:\s*(.+)", line.strip())
#         if match:
#             return match.group(1).strip()
#     return None
#
#
# class TestEveryNPCFactionExists(unittest.TestCase):
#
#     def test_named_factions_have_a_file(self):
#         for npc in sorted((CAMPAIGN / "NPCs").glob("*.md")):
#             if npc.name == "README.md":
#                 continue
#             faction = front_matter_field(npc, "faction")
#             if faction is None:
#                 continue  # this NPC claims no faction; nothing to check
#             expected = CAMPAIGN / "Factions" / f"{faction}.md"
#             self.assertTrue(
#                 expected.is_file(),
#                 f"{npc.name} names faction {faction!r}, but "
#                 f"Factions/{faction}.md does not exist")
