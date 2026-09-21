"""test_docs.py — the repo's own docs, where they lean on packaged doctrine.

README.md and docs/serve-mcp.md do not describe how work in a workspace is
sequenced: the packaged AGENTS.md does, under "The working sequence", and
these two link to it (#111). That was a deliberate choice against three
prose copies -- the README's scaffold inventory has already drifted from
MANIFEST once, silently (#37) -- and a choice nothing enforces is a choice
that lasts until the next well-meant edit. So:

  * each doc must link the section, and the link must resolve -- to the
    packaged file, at a heading that exists;
  * the README's five-line outline, the one thing that IS restated, must
    match the doctrine's phase headings, names and order.

Read from the repo tree, not from the installed package: the link targets
are repo paths, and that is the file a reader following one lands on.
"""

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOCTRINE = REPO / "src" / "bunnyforge" / "data" / "doctrine" / "AGENTS.md"
LINKING_DOCS = ("README.md", "docs/serve-mcp.md")
ANCHOR = "the-working-sequence"


def _slug(heading: str) -> str:
    """GitHub's heading anchor: lowercased, punctuation dropped (hyphens
    and underscores survive), each space a hyphen."""
    kept = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return kept.replace(" ", "-")


class TestDocsLinkTheWorkingSequence(unittest.TestCase):

    def test_each_doc_links_the_section_and_the_link_resolves(self):
        doctrine = DOCTRINE.read_text(encoding="utf-8")
        slugs = {_slug(h) for h in
                 re.findall(r"^#{1,6} (.+)$", doctrine, re.MULTILINE)}
        self.assertIn(ANCHOR, slugs,
                      "AGENTS.md has no 'The working sequence' heading")
        for name in LINKING_DOCS:
            with self.subTest(doc=name):
                doc = REPO / name
                links = re.findall(r"\]\(([^)\s#]*AGENTS\.md)#([^)\s]+)\)",
                                   doc.read_text(encoding="utf-8"))
                self.assertIn(
                    ANCHOR, [anchor for _target, anchor in links],
                    f"{name} no longer links the working sequence — it "
                    "must link it rather than restate it (#111)")
                for target, anchor in links:
                    self.assertEqual((doc.parent / target).resolve(),
                                     DOCTRINE.resolve(), f"{name}: {target}")
                    self.assertIn(anchor, slugs,
                                  f"{name}: #{anchor} matches no heading")

    def test_the_readme_outline_matches_the_phase_headings(self):
        phases = re.findall(r"^### Phase (\d) — (.+)$",
                            DOCTRINE.read_text(encoding="utf-8"),
                            re.MULTILINE)
        self.assertTrue(phases, "no '### Phase N — name' headings found; "
                                "an empty list would match vacuously")
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertIn("\n## Working in a workspace\n", readme)
        section = readme.split("\n## Working in a workspace\n", 1)[1]
        section = section.split("\n## ", 1)[0]
        outline = re.findall(r"^(\d)\. \*\*(.+?)\*\*", section, re.MULTILINE)
        self.assertEqual(
            outline, phases,
            "README.md's outline and AGENTS.md's phase headings disagree "
            "— the doctrine is canonical; bring the README in line")


if __name__ == "__main__":
    unittest.main()
