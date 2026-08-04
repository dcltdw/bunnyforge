# bunnyforge

An opinionated way to run a tabletop-RPG campaign as a plain-files
workspace — designed to be managed collaboratively by a GM and an AI
agent, with one-way publishing to a DokuWiki players' site.

Your campaign is a directory of Markdown files with front matter: NPCs,
factions, places, sessions, mechanics. bunnyforge gives that directory a
skeleton, reviews its integrity, generates names from culture inventories
you define, and exports the player-visible slice to DokuWiki. Everything
is a text file; everything works offline; the only state is your git
history.

- **Python ≥ 3.11, zero runtime dependencies.**
- **Agent-first doctrine.** `init` writes an `AGENTS.md` contract that
  tells an AI agent how to behave in the workspace, and doctrine
  *skeletons* — a style guide and a situation-design guide that interview
  you: each section explains what belongs in it, so filling them in is
  answering questions, not staring at a blank file.
- **Player-visibility model.** Every file carries a `visibility` field;
  the exporter enforces it, so GM-only material cannot leak to the wiki.

## Install

    pip install bunnyforge

## Quickstart

    bunnyforge init my-campaign --name "My Campaign"
    cd my-campaign
    bunnyforge review checkup     # 0 errors, 0 warnings on a fresh workspace

Then fill in `style-guide.md` and `situation-design.md` — they arrive as
skeletons that tell you what each section is for — and start writing
entity files from the templates in `_Templates/`.

## Subcommands

| command | what it does |
|---|---|
| `init` | scaffold a new campaign workspace |
| `review` | run a named workspace review suite (`checkup`, `wiki`) |
| `export-player` | write player-safe copies of content files to `Export/` |
| `deploy-export` | render `Export/` into a DokuWiki staging tree |
| `import-perceptions` | import player-authored wiki pages into `Perceptions/` |
| `build-sheets` | build one-page HTML reference sheets for a session |
| `names` | generate culture-appropriate names |
| `test` | run the workspace test suite |

Run `bunnyforge <command> --help` for a command's own options.

## The workspace

`campaign.toml` marks the workspace root and holds configuration —
directory layout, wiki namespace, name-generator inventories. Commands
work from any subdirectory (they walk up to the marker), from
`$BUNNYFORGE_WORKSPACE`, or from anywhere with `--workspace PATH`.

`init` also scaffolds a `tests/` folder. Its `README.md` explains the
campaign tests it invites you to write — the setting-specific invariants
`review checkup` cannot know, like "every NPC's faction actually exists" —
and ships a worked example, commented out, to adapt. `bunnyforge test`
runs them, and checks that no test wrote into your campaign while running.

## Names

`bunnyforge names` builds names from syllable inventories you write
yourself, one TOML file per culture. The tool ships the engine and a
worked example; it ships no cultures of its own, and takes no position on
which real-world naming tradition any fantasy species should draw on —
that is a setting-authorship decision, and it stays yours.

    bunnyforge names --list
    bunnyforge names <culture> -n 10
    bunnyforge names <culture> --place --seed 42

The [`samples/`](samples/) directory is a ladder of eight worked
configurations, from a single people to a full multi-culture setting with
registers and spelling variants.

## DokuWiki export

`export-player` renders the player-visible slice; `deploy-export` pushes
it into a DokuWiki staging tree. Sync is strictly one-way: the wiki is a
published artifact, never a source of truth. `import-perceptions` brings
player-authored pages back as *perceptions* — recorded belief, explicitly
not canon.

## Development

    pip install -e .
    python3 -m unittest discover -s tests -t .

(`bunnyforge test` is for running a *campaign's* tests from inside a
workspace — it is not this package's test runner.)

The `bunnyforge` command is not a file in this repository: pip generates a
launcher from `[project.scripts]` in `pyproject.toml` at install time, and
it calls the dispatcher in [`src/bunnyforge/cli.py`](src/bunnyforge/cli.py).
Every subcommand is also runnable on its own — `python3 -m
bunnyforge.generate_names` — which is exactly what the dispatcher forwards
to.

Design history lives in [docs/superpowers/specs/](docs/superpowers/specs/).

## Releasing

Releases are triggered by pushing a tag, and published to PyPI by
[trusted publishing](https://docs.pypi.org/trusted-publishers/) — there is
no API token stored anywhere.

1. Land the changes on `main` in the usual way (branch, PR, review).
2. Bump `version` in `pyproject.toml`. **This is a separate step from the
   tag, which is why they drift** — CI refuses a tag that disagrees with it.
3. Tag and push:

       git tag vX.Y.Z && git push origin vX.Y.Z

4. Watch `publish.yml`. It verifies the tag against `pyproject.toml`, builds
   the sdist and wheel, and uploads.
5. Bump the pin in any campaign that depends on this package, in its own
   commit, so the upgrade is deliberate and its drift guard can report what
   changed underneath it.

Note that PyPI never releases a name and never lets a version number be
reused, even after deletion — so step 2 is the one to get right.

## License

MIT — see [LICENSE](LICENSE).
