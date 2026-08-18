# bunnyforge

An opinionated way to run a tabletop-RPG campaign as a plain-files
workspace — designed to be managed collaboratively by a GM and an AI
agent, with one-way publishing to a DokuWiki players' site.

Your campaign is a directory of Markdown files with front matter: NPCs,
factions, places, sessions, mechanics. bunnyforge gives that directory a
skeleton, reviews its integrity, generates names from culture inventories
you define, and exports the player-visible slice to DokuWiki. Everything
is a text file; the only state is your git history. Every command works
offline except the wiki deploy itself — and even that keeps a fully
offline path via `deploy-export --render-only`.

- **Python ≥ 3.11, zero runtime dependencies.**
- **Agent-first doctrine.** `init` writes an `AGENTS.md` contract that
  tells an AI agent how to behave in the workspace — package-owned, so
  adopting a new release replaces it wholesale — plus
  `campaign-doctrine.md` beside it for the rules that are yours alone.
  And doctrine *skeletons*: a style guide and a situation-design guide
  that interview you, each section explaining what belongs in it, so
  filling them in is answering questions rather than staring at a blank
  file. See [`docs/adopting-doctrine.md`](docs/adopting-doctrine.md) for
  how to adopt a new version.
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
| `export-player` | write player-safe copies of content files to `_Export/` |
| `deploy-export` | render `_Export/` and deploy it to the wiki (dry run by default) |
| `import-perceptions` | import player-authored wiki pages into `Perceptions/` |
| `build-sheets` | build one-page HTML reference sheets for a session |
| `names` | generate culture-appropriate names |
| `vscode` | install the preview extension and toggle editor colouring |
| `serve-mcp` | serve the workspace to a remote AI agent over MCP — [guide](docs/serve-mcp.md) (needs `bunnyforge[mcp]`) |
| `test` | run the workspace test suite |

Run `bunnyforge <command> --help` for a command's own options.

## VS Code integration

`bunnyforge init` scaffolds `.vscode/settings.json` and
`.vscode/extensions.json` with a visibility colour language for the editor —
every `.md` file coloured by its front-matter `visibility`, the `## GM notes`
boundary marked. It ships off; `bunnyforge vscode` manages it:

    bunnyforge vscode status      # both halves: installed, available, on/off
    bunnyforge vscode setup       # install/update, then offer to enable
    bunnyforge vscode on|off      # toggle the source-view block
    bunnyforge vscode install|update|uninstall   # the preview extension

The source-view half is rendered by the Marketplace extension
`fabiospampinato.vscode-highlight`. The markdown-preview half,
[`dcltdw.bunnyforge-visibility-preview`](https://github.com/dcltdw/bunnyforge-visibility-preview),
is not on the Marketplace; it sideloads as a `.vsix` from GitHub releases,
and sideloaded extensions never auto-update — `bunnyforge vscode update`
checks the release feed. Only Visual Studio Code is tested; VS Code
Insiders, VSCodium and Cursor are offered but unsupported. `on`/`off`
rewrite only the marked managed block in `.vscode/settings.json`; the rest
of the file — including its comments — is yours.

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

It also scaffolds a `.vscode/` pair — a visibility colour language for the
editor — shipped off. `bunnyforge vscode` manages it; see
[VS Code integration](#vs-code-integration) above.

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

`export-player` renders the player-visible slice; `deploy-export` renders it
into DokuWiki markup and deploys it to the wiki over its JSON-RPC API. Sync
is strictly one-way: the wiki is a published artifact, never a source of
truth. `import-perceptions` brings player-authored pages back as
*perceptions* — recorded belief, explicitly not canon.

## Dry runs and --go

Every mutating command follows one convention: **the default run is a dry
run; `--go` performs the writes.** A bare `bunnyforge deploy-export` fetches
and prints the full deploy plan without writing anything; a bare
`bunnyforge import-perceptions` reports what it would import. Re-run with
`--go` to act. (`deploy-export --render-only` is not a rehearsal — it is a
different, offline deliverable, and needs no wiki config at all.)

Future mutating commands inherit this convention.

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
5. Confirm the release is actually **installable**, in a clean virtualenv on
   a path holding no checkout:

       pip install bunnyforge==X.Y.Z
       pip show bunnyforge          # check the version it really installed

   Check the version it reports rather than trusting the workflow's green
   tick — see the note on index lag below.
6. Bump the pin in any campaign that depends on this package, in its own
   commit, so the upgrade is deliberate and its drift guard can report what
   changed underneath it.

Note that PyPI never releases a name and never lets a version number be
reused, even after deletion — so step 2 is the one to get right.

### Index lag, right after a release

For a few minutes after a successful publish, PyPI may still serve the
*previous* version to some clients. Expect any of these, and do not go
looking for a bug:

- `pip install bunnyforge` quietly installs the older version — which is why
  step 5 checks what actually landed rather than assuming;
- a consuming project's CI fails with

      ERROR: Could not find a version that satisfies the requirement
      bunnyforge==X.Y.Z (from versions: <older>)

  on a clean runner with no cache involved.

The fix is to wait a few minutes and re-run. Two things that mislead here:
`https://pypi.org/pypi/bunnyforge/json` can report the new version while the
simple index a given client reaches has not caught up, and `--no-cache-dir`
does not help, because the staleness is not local. Different machines
disagree at the same moment.

All three of these were observed within minutes of one release; each
resolved on its own with no change.

## License

GPL-3.0-or-later — see [LICENSE](LICENSE).

Releases up to and including **0.2.3** were published under the MIT licence and
stay MIT forever; that grant cannot be withdrawn. The change applies from the
next release onward.

Contributions are accepted under the same licence as the project. If you are
opening a pull request, that is the licence you are granting.
