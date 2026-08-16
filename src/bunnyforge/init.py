#!/usr/bin/env python3
"""
init.py — scaffold a new campaign workspace.

The one tool that does NOT resolve a workspace: it creates the campaign.toml
marker every other tool walks to. No --workspace flag, no BUNNYFORGE_WORKSPACE
lookup, no marker walk. An ancestor workspace does not block init either --
the walk always finds the NEAREST campaign.toml, so nesting is harmless and
refusing it would be policy without a defect behind it.

Everything init writes comes from MANIFEST, which maps each file packaged
under data/ to its destination in the new workspace and, where that packaged
file is a verbatim copy of an in-repo canonical source, to that source. init
iterates the manifest to write; tests/test_init.py iterates the SAME manifest
to prove every copy is still byte-identical to its canonical.
setup_campaign.py died of embedded doctrine that drifted silently from the
real files; the manifest is what makes that drift a red test rather than a
matter of discipline.

Usage:
    bunnyforge init PATH --name "My Campaign" [--namespace mycampaign]

Stdlib only.
"""

from __future__ import annotations

import argparse
import sys
from collections import namedtuple
from importlib import resources
from pathlib import Path

from bunnyforge._workspace import CONFIG_NAME


class InitError(Exception):
    """init cannot proceed. The message is user-facing."""


# One packaged file. `resource` is its path under data/; `dest` where it lands
# in the new workspace; `canonical` the in-repo file it must stay
# byte-identical to, or None for the files that have no canonical source (the
# authored stubs and the config template); `render` marks the one file that is
# substituted rather than copied.
Packaged = namedtuple("Packaged", "resource dest canonical render")

# What a workspace's _Templates/ holds, verbatim: one README, three session
# briefs, and eight durable writeups. The -brief suffix marks the axis that
# matters -- brief (true THIS session) vs writeup (true always) -- which is
# why it cannot simply be dropped: faction-brief.md's writeup is faction.md.
#
# The two doctrine skeletons are NOT here. They land once, at the workspace
# root under the names root_docs expects (see MANIFEST below); their prompts
# survive being filled in, so a pristine second copy under a .skeleton name
# bought nothing but a file a user could not tell the purpose of. The suffix
# now appears only in data/ and in this repo's own _Templates/.
TEMPLATE_FILES = (
    "README.md", "npc-brief.md", "faction-brief.md", "place-brief.md",
    "faction.md", "handout.md", "idea.md", "mechanic.md",
    "npc.md", "pc.md", "session.md", "setting.md",
)

# The 8 entity_dirs then the 2 inherit_dirs of _config._DEFAULTS. Each gets its
# packaged README, and writing that README is what creates the directory --
# there is no separate list of directories to fall out of step with this one.
CONTENT_DIRS = (
    "NPCs", "Factions", "Setting", "Mechanics", "PCs", "Ideas", "Sessions",
    "Handouts", "Briefs", "Perceptions",
)

# The root docs with no canonical in-repo source: the in-repo copies are live
# campaign state rather than doctrine, so these are authored generically for
# data/root/ instead.
ROOT_STUBS = ("compendium.md", "front-burner.md", "open-questions.md",
              "out-of-game.md", "tickets.md")

MANIFEST = (
    Packaged("campaign.toml.in", CONFIG_NAME, None, True),
    Packaged("doctrine/AGENTS.md", "AGENTS.md", "AGENTS.md", False),
    # Shipped without the dot so no packaging glob has to care about dotfiles.
    Packaged("root/gitignore", ".gitignore", None, False),
    # The VS Code visibility colour language, source-view half (#34).
    # Ships INERT: the managed block is disabled with "//- " prefixes;
    # `bunnyforge vscode` (#33) toggles it between the marker comments.
    # canonical=None: authored stubs, no in-repo canonical source.
    Packaged("vscode/settings.json", ".vscode/settings.json", None, False),
    Packaged("vscode/extensions.json", ".vscode/extensions.json", None, False),
    *(Packaged(f"root/{name}", name, None, False) for name in ROOT_STUBS),
    *(Packaged(f"templates/{name}", f"_Templates/{name}",
               f"_Templates/{name}", False) for name in TEMPLATE_FILES),
    *(Packaged(f"dir-readmes/{d}.md", f"{d}/README.md", f"{d}/README.md",
               False) for d in CONTENT_DIRS),
    # The two skeletons land a SECOND time, under the canonical names the
    # config's root_docs expects. Same packaged bytes, different destination:
    # skeleton-vs-filled-in is the governing distinction, and the .skeleton
    # suffix never appears at a workspace root.
    Packaged("templates/style-guide.skeleton.md", "style-guide.md",
             "_Templates/style-guide.skeleton.md", False),
    Packaged("templates/situation-design.skeleton.md", "situation-design.md",
             "_Templates/situation-design.skeleton.md", False),
    Packaged("cultures/vashkand.toml", "names/cultures/vashkand.toml",
             "samples/1-one-people/cultures/vashkand.toml", False),
    # The tests/ scaffold: the doctrine-skeleton pattern applied to campaign
    # tests -- a folder whose README explains what belongs in it, and a
    # worked example shipped commented out. Authored stubs, so no canonical.
    #
    # __init__.py is load-bearing rather than decorative: without it unittest
    # discovery cannot import the directory, which is the ImportError a fresh
    # workspace used to meet. The resource names dodge both the __init__
    # dunder and the test_ prefix so nothing -- setuptools, any discovery
    # run -- can mistake data/tests/ for a live package or test tree.
    Packaged("tests/init.py", "tests/__init__.py", None, False),
    Packaged("tests/README.md", "tests/README.md", None, False),
    Packaged("tests/example.py", "tests/test_example.py", None, False),
)


def packaged_bytes(resource: str) -> bytes:
    """Read one file from the package's data/ tree.

    importlib.resources rather than a path built from __file__: the package
    owns these files wherever it is installed, including out of a wheel.
    """
    return resources.files("bunnyforge").joinpath("data", resource).read_bytes()


def slugify(name: str) -> str:
    """Lowercase, non-alphanumerics stripped.

    May return "" -- a name with no alphanumeric characters in it has no slug.
    That is the caller's error to report, not something to paper over with a
    generated placeholder nobody asked for.
    """
    return "".join(ch for ch in name.lower() if ch.isalnum())


def toml_basic(value: str) -> str:
    """Escape a value for a TOML basic string.

    campaign.toml is rendered by placeholder substitution rather than by a TOML
    writer (the stdlib has none, and the parent spec rules one out), so the
    single thing substitution can get wrong -- a quote or a backslash in --name
    closing the string early and producing a campaign.toml no tool can read --
    is handled here. A namespace is alphanumeric by construction and needs none
    of this, but goes through the same call so the two cannot drift.
    """
    return value.replace("\\", "\\\\").replace('"', '\\"')


def render_config(name: str, namespace: str) -> bytes:
    template = packaged_bytes("campaign.toml.in").decode("utf-8")
    return (template
            .replace("@@NAME@@", toml_basic(name))
            .replace("@@NAMESPACE@@", toml_basic(namespace))
            ).encode("utf-8")


def check_destination(path: Path) -> None:
    """Refuse anything but a new path or an empty directory.

    Ordered most-specific-first: an existing campaign.toml gets its own
    message rather than the generic "not empty", because that is the case
    where the user is one --force away from losing a campaign, and there is
    no --force precisely so they cannot be.
    """
    if path.exists() and not path.is_dir():
        raise InitError(f"{path} exists and is not a directory")
    if (path / CONFIG_NAME).is_file():
        raise InitError(f"{path} already contains {CONFIG_NAME} — it is "
                        f"already a campaign workspace")
    if path.is_dir() and any(path.iterdir()):
        raise InitError(f"{path} is not empty — init writes only into a new "
                        f"or empty directory")


def write_workspace(path: Path, name: str, namespace: str) -> list[Path]:
    """Write every manifest entry under `path`; return the paths written.

    Every directory the new workspace needs is created by the parents=True
    below, on the way to writing a file that lives in it -- the 10 content
    directories each have a packaged README, so none of them needs its own
    entry in a second list that could fall out of step with MANIFEST.
    """
    written: list[Path] = []
    for entry in MANIFEST:
        dest = path / entry.dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(render_config(name, namespace) if entry.render
                         else packaged_bytes(entry.resource))
        written.append(dest)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bunnyforge init",
        description="Scaffold a new campaign workspace.")
    parser.add_argument("path", metavar="PATH",
                        help="Directory to create; must not exist, or be empty")
    parser.add_argument("--name", required=True,
                        help='Campaign name, e.g. "My Campaign"')
    parser.add_argument("--namespace", metavar="SLUG",
                        help="Wiki namespace (default: a slug of --name)")
    args = parser.parse_args(argv)

    # Whichever way the namespace arrives it is slugged, so an explicit
    # --namespace cannot smuggle in a character the default path would strip.
    # The flag it came from is carried along so the error names the argument
    # the user actually typed.
    flag, raw = (("--namespace", args.namespace) if args.namespace
                 else ("--name", args.name))
    namespace = slugify(raw)

    path = Path(args.path)
    try:
        if not namespace:
            raise InitError(
                f"{flag} {raw!r} has no alphanumeric characters to build a "
                f"namespace from; pass --namespace explicitly")
        check_destination(path)
        written = write_workspace(path, args.name, namespace)
    except (InitError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Created campaign workspace {path} — {len(written)} files "
          f"(name {args.name!r}, namespace {namespace!r}).")
    print("Optional: VS Code colouring by visibility ships off — "
          "run 'bunnyforge vscode setup'.")
    print(f"Next: cd {path} && bunnyforge review checkup")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        sys.stderr.close()
        raise SystemExit(0)
