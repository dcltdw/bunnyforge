#!/usr/bin/env python3
"""
build_sheets.py — generate one-page HTML reference sheets for a session.

Handles three entity types, chosen by each brief's `type` field: npc, faction,
and place. Each gets its own section layout and accent colour but the same
NOW/ALWAYS structure and the same notes-preservation behaviour.

Merges two sources and invents nothing:

  NPCs/<name>.md              the durable writeup — who they are, always
  Briefs/session-NNN/<name>.md the session brief — what is true this session

Output: Sheets/session-NNN/<name>.html, one page per NPC.

Sheets are regenerable. Anything typed into a sheet's editable regions in the
browser is preserved across regeneration: the script reads the previous HTML,
extracts the marked blocks, and carries them forward.

Usage:
    python3 -m bunnyforge.build_sheets 14
    python3 -m bunnyforge.build_sheets 14 --only mira-venn
    python3 -m bunnyforge.build_sheets 14 --open
    python3 -m bunnyforge.build_sheets --list-briefs
    python3 -m bunnyforge.build_sheets 14 --workspace /path/to/campaign
"""

from __future__ import annotations

import argparse
import html
import re
import subprocess
import sys
from pathlib import Path

from bunnyforge._common import (
    normalize_visibility,
    split_front_matter,
    strip_yaml_comment,
)
from bunnyforge._config import ConfigError, resolve_workspace
from bunnyforge._workspace import WorkspaceError

# Which writeup directory backs each entity type (looked up per-run in
# ws.config.type_dirs, keyed by this same etype string — see main()), and the
# accent colour that tells the three sheet kinds apart at a glance.
TYPES = {
    "npc": {
        "accent": "npc",
        "meta_fields": ("faction", "location"),
    },
    "faction": {
        "accent": "faction",
        "meta_fields": ("seat_of_power", "posture_toward_party"),
    },
    "place": {
        "accent": "place",
        "meta_fields": ("region", "controlled_by"),
    },
}

# Section layout per type. Each entry: (Heading, source, css_class).
#   source "brief"   — from the session brief only
#   source "writeup" — from the durable writeup only
#   source "pick"    — brief if present, else writeup
# A section whose content resolves empty is dropped.
LAYOUT = {
    "npc": {
        "now": [
            ("This session", "brief", ""),
            ("Want", "pick", ""),
            ("Obstacle", "pick", ""),
            ("Method", "pick", ""),
            ("What they know", "pick", ""),
            ("What they do not know", "pick", ""),
            ("Secrets", "pick", "secret"),
        ],
        "always": [
            ("Voice", "writeup", "voice"),
            ("Appearance", "writeup:appearance and first impression", ""),
            ("Disposition", "writeup:synthesis", ""),
            ("Relationships", "writeup", ""),
            ("If unengaged", "writeup", ""),
            ("Changed since", "brief:changes", ""),
        ],
    },
    "faction": {
        "now": [
            ("This session", "brief", ""),
            ("Doing now", "pick:current operations", ""),
            ("Just learned", "brief:just learned", ""),
            ("Clock", "pick", "clock"),
            ("Posture toward party", "pick:posture toward party", ""),
            ("Secrets", "pick", "secret"),
        ],
        "always": [
            ("Goal", "writeup", ""),
            ("Method", "writeup", ""),
            ("Weakness", "writeup:weaknesses", ""),
            ("Public face vs actual", "writeup:public face vs. actual", ""),
            ("Key members", "writeup", ""),
            ("Clock moved", "brief:clock moved", ""),
        ],
    },
    "place": {
        "now": [
            ("This session", "brief", ""),
            ("Situation", "pick", ""),
            ("Changed since last visit", "brief:changed since last visit", ""),
            ("Tension", "pick:tensions", ""),
        ],
        "always": [
            ("What it is", "writeup:what it is", ""),
            ("Who is here", "writeup:who is here", ""),
            ("Connections", "writeup", "connections"),
            ("Sensory palette", "writeup:sensory palette", ""),
            ("Secrets", "writeup", "secret"),
        ],
    },
}

# Sections lifted from the durable writeup, in sheet order.
WRITEUP_SECTIONS = [
    "Synthesis",
    "Want",
    "Obstacle",
    "Method",
    "Voice",
    "Appearance and first impression",
    "What they know",
    "What they do not know",
    "Secrets",
    "Relationships",
    "If unengaged",
]

# Sections lifted from the session brief. These override the writeup where
# they share a name.
BRIEF_SECTIONS = [
    "This session",
    "Want",
    "Obstacle",
    "Method",
    "What they know",
    "What they do not know",
    "Secrets",
    "Changes",
]

NOTES_MARKER_OPEN = "<!-- NOTES:START -->"
NOTES_MARKER_CLOSE = "<!-- NOTES:END -->"


# ---------------------------------------------------------------------------
# Markdown parsing
# ---------------------------------------------------------------------------

def strip_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)


def parse_sections(body: str) -> dict[str, str]:
    """Map '## Heading' -> content. Case-insensitive keys."""
    out: dict[str, str] = {}
    current = None
    buf: list[str] = []
    for line in body.splitlines():
        m = re.match(r"^#{2,3}\s+(.*?)\s*$", line)
        if m:
            if current:
                out[current.lower()] = "\n".join(buf).strip()
            current = m.group(1)
            buf = []
        elif current:
            buf.append(line)
    if current:
        out[current.lower()] = "\n".join(buf).strip()
    return out


def clean(text: str) -> str:
    text = strip_comments(text).strip()
    # Drop placeholder angle-bracket prompts left in from templates.
    lines = [l for l in text.splitlines() if not re.match(r"^\s*<[a-z].*>\s*$", l)]
    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# Minimal markdown -> HTML
# ---------------------------------------------------------------------------

def inline(text: str) -> str:
    t = html.escape(text)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"<em>\1</em>", t)
    t = re.sub(r"`([^`\n]+?)`", r"<code>\1</code>", t)
    t = re.sub(r"\[\[([^\]]+)\]\]", r'<span class="link">\1</span>', t)
    return t


def to_html(text: str) -> str:
    if not text.strip():
        return '<p class="empty">—</p>'
    out: list[str] = []
    in_list = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            if in_list:
                out.append("</ul>")
                in_list = False
            continue
        m = re.match(r"^\s*[-*]\s+(.*)$", line)
        if m:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(m.group(1))}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        out.append(f"<p>{inline(line)}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Notes preservation
# ---------------------------------------------------------------------------

def extract_notes(path: Path) -> str:
    """Pull previously-typed notes out of an existing sheet."""
    if not path.is_file():
        return ""
    prev = path.read_text(encoding="utf-8")
    m = re.search(
        re.escape(NOTES_MARKER_OPEN) + r"(.*?)" + re.escape(NOTES_MARKER_CLOSE),
        prev,
        re.DOTALL,
    )
    return m.group(1).strip() if m else ""


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

CSS = """
:root {
  --ink:        #1a1614;
  --ink-soft:   #5c534d;
  --paper:      #f7f4ee;
  --card:       #fffdf9;
  --rule:       #ddd5c8;
  --always:     #2f4858;
  --secret:     #6b4a1f;
  --secret-bg:  #f7f0e0;
  --now:        #7c2d2d;   /* overridden per type below */
}

/* Each sheet type gets its own NOW accent so three open windows are instantly
   distinguishable: NPC crimson, faction gold, place green. */
.type-npc     { --now: #7c2d2d; }
.type-faction { --now: #8a6a1c; }
.type-place   { --now: #3d6b45; }

* { box-sizing: border-box; }

html { -webkit-text-size-adjust: 100%; }

body {
  margin: 0;
  padding: 2rem 1.5rem 5rem;
  background: var(--paper);
  color: var(--ink);
  font: 16px/1.55 "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif;
}

.sheet { max-width: 60rem; margin: 0 auto; }

header {
  border-bottom: 2px solid var(--ink);
  padding-bottom: .75rem;
  margin-bottom: 1.5rem;
  display: flex;
  align-items: baseline;
  gap: 1rem;
  flex-wrap: wrap;
}

h1 {
  font-size: 2.1rem;
  margin: 0;
  letter-spacing: -.02em;
  font-weight: 600;
}

.meta {
  font: 600 .72rem/1.4 ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  letter-spacing: .1em;
  text-transform: uppercase;
  color: var(--ink-soft);
}

.meta .sep { opacity: .4; padding: 0 .4em; }

/* Two-column on wide screens: NOW on the left, ALWAYS on the right. */
.cols { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; }
@media (max-width: 62rem) { .cols { grid-template-columns: 1fr; } }

.band {
  font: 600 .7rem/1 ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  letter-spacing: .16em;
  text-transform: uppercase;
  padding: .45rem .7rem;
  border-radius: 3px 3px 0 0;
  color: #fff;
}
.band.now    { background: var(--now); }
.band.always { background: var(--always); }

.stack {
  border: 1px solid var(--rule);
  border-top: none;
  border-radius: 0 0 3px 3px;
  background: var(--card);
  padding: .25rem 1rem 1rem;
  margin-bottom: 1.5rem;
}

section { padding-top: .9rem; }
section + section { border-top: 1px solid var(--rule); margin-top: .9rem; }

h2 {
  font: 600 .74rem/1 ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  letter-spacing: .12em;
  text-transform: uppercase;
  color: var(--ink-soft);
  margin: 0 0 .5rem;
}

section p { margin: 0 0 .5rem; }
section p:last-child { margin-bottom: 0; }
section ul { margin: 0 0 .5rem; padding-left: 1.15rem; }
section li { margin-bottom: .25rem; }
.empty { color: #b3aaa0; }

.link {
  border-bottom: 1px dotted var(--ink-soft);
  color: var(--ink-soft);
}

code {
  font: .88em ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  background: #ece6dc;
  padding: .08em .3em;
  border-radius: 2px;
}

/* Secrets get their own treatment — the one thing you must not misread. */
section.secret { background: var(--secret-bg); margin: .9rem -1rem 0; padding: .9rem 1rem; }
section.secret h2 { color: var(--secret); }
section.secret + section { border-top: none; }

/* Voice sits at the top of ALWAYS: it is what you need first when speaking. */
section.voice p { font-size: 1.05rem; }

/* Clock: the faction's this-session pressure. Set it apart like secrets. */
section.clock {
  background: #f4efe3;
  margin: .9rem -1rem 0;
  padding: .9rem 1rem;
}
section.clock h2 { color: var(--now); }
section.clock + section { border-top: none; }

/* Connections: bordering places. Render the wikilinks as a route list. */
section.connections ul { list-style: none; padding-left: 0; }
section.connections li::before { content: "→ "; color: var(--ink-soft); }

.notes-wrap { margin-top: .5rem; }
.notes-band {
  font: 600 .7rem/1 ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  letter-spacing: .16em;
  text-transform: uppercase;
  color: var(--ink-soft);
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: .45rem 0;
  border-bottom: 1px solid var(--rule);
}

.notes {
  min-height: 11rem;
  padding: .8rem 1rem;
  background: repeating-linear-gradient(
    var(--card), var(--card) 1.54rem,
    var(--rule) 1.54rem, var(--rule) calc(1.54rem + 1px));
  border: 1px solid var(--rule);
  border-top: none;
  border-radius: 0 0 3px 3px;
  outline: none;
  line-height: 1.55rem;
}
.notes:focus { box-shadow: inset 0 0 0 2px rgba(124,45,45,.25); }
.notes p { margin: 0; }

button {
  font: 600 .7rem/1 ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  letter-spacing: .1em;
  text-transform: uppercase;
  padding: .45rem .8rem;
  border: 1px solid var(--rule);
  background: var(--card);
  color: var(--ink-soft);
  border-radius: 3px;
  cursor: pointer;
}
button:hover { border-color: var(--ink-soft); color: var(--ink); }
button:focus-visible { outline: 2px solid var(--now); outline-offset: 2px; }

.saved { color: var(--now); opacity: 0; transition: opacity .2s; margin-right: .6rem; }
.saved.on { opacity: 1; }

@media print {
  body { background: #fff; padding: 0; }
  .stack, .notes { border-color: #999; }
  button { display: none; }
  .cols { grid-template-columns: 1fr 1fr; }
}
"""

JS = """
(function () {
  var notes = document.querySelector('.notes');
  var flag  = document.querySelector('.saved');
  var key   = 'sheet-notes:' + document.body.dataset.sheetId;

  // Restore anything typed since the last regeneration.
  try {
    var stashed = sessionStorage.getItem(key);
    if (stashed && !notes.textContent.trim()) notes.innerHTML = stashed;
  } catch (e) {}

  var timer;
  notes.addEventListener('input', function () {
    clearTimeout(timer);
    timer = setTimeout(function () {
      try { sessionStorage.setItem(key, notes.innerHTML); } catch (e) {}
      flag.classList.add('on');
      setTimeout(function () { flag.classList.remove('on'); }, 900);
    }, 400);
  });

  document.querySelector('.download').addEventListener('click', function () {
    var doc = '<!doctype html>\\n' + document.documentElement.outerHTML;
    var blob = new Blob([doc], { type: 'text/html' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = document.body.dataset.sheetId + '.html';
    a.click();
    URL.revokeObjectURL(a.href);
  });
})();
"""


def section_html(title: str, content: str, cls: str = "") -> str:
    return (
        f'<section class="{cls}">\n'
        f"  <h2>{html.escape(title)}</h2>\n"
        f"  {to_html(content)}\n"
        f"</section>"
    )


def resolve_section(spec_source: str, heading: str,
                    writeup: dict, brief: dict) -> str:
    """Resolve a layout entry's source string to content.

    The source may name an explicit key after a colon (e.g. 'writeup:synthesis');
    otherwise the heading, lowercased, is the key.
    """
    if ":" in spec_source:
        mode, key = spec_source.split(":", 1)
    else:
        mode, key = spec_source, heading.lower()
    key = key.lower()

    w = clean(writeup.get(key, ""))
    b = clean(brief.get(key, ""))
    if mode == "brief":
        return b
    if mode == "writeup":
        return w
    if mode == "pick":
        return b or w
    return ""


def visibility_label(visibility: str, reveal_when: str = "") -> str:
    """Human label for the sheet meta: who currently may see this entity."""
    label = {
        "player-visible": "Player-visible",
        "mixed": "Mixed",
        "gm-only": "GM-only",
    }.get(visibility, "GM-only")
    if visibility == "gm-only" and reveal_when:
        label += f" (reveals: {reveal_when})"
    return label


def render(name: str, etype: str, session: str, writeup: dict, brief: dict,
           fm: dict, notes: str, visibility: str = "gm-only",
           reveal_when: str = "") -> str:
    sheet_id = f"session-{session}-{etype}-{name}"
    title = fm.get("title", "").strip() or name.replace("-", " ").title()
    accent = TYPES[etype]["accent"]
    type_label = {"npc": "NPC", "faction": "Faction", "place": "Place"}[etype]

    meta_bits = [f"Session {session}", type_label]
    for field in TYPES[etype]["meta_fields"]:
        val = fm.get(field, "").strip()
        if val:
            meta_bits.append(val)
    # The entity's visibility comes from the durable writeup, never the brief:
    # a session brief must not change whether players know an entity exists.
    meta_bits.append(visibility_label(visibility, reveal_when))
    meta = '<span class="sep">/</span>'.join(html.escape(b) for b in meta_bits)

    def build(column: list) -> str:
        out = []
        for heading, source, cls in column:
            content = resolve_section(source, heading, writeup, brief)
            if not content:
                continue
            out.append(section_html(heading, content, cls=cls))
        return "\n".join(out)

    now = build(LAYOUT[etype]["now"])
    always = build(LAYOUT[etype]["always"])

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} — Session {html.escape(session)}</title>
<style>{CSS}</style>
</head>
<body data-sheet-id="{html.escape(sheet_id)}" class="type-{accent}">
<div class="sheet">

<header>
  <h1>{html.escape(title)}</h1>
  <div class="meta">{meta}</div>
</header>

<div class="cols">
  <div>
    <div class="band now">Now</div>
    <div class="stack">
{now}
    </div>
  </div>
  <div>
    <div class="band always">Always</div>
    <div class="stack">
{always}
    </div>
  </div>
</div>

<div class="notes-wrap">
  <div class="notes-band">
    <span>Notes</span>
    <span>
      <span class="saved">saved</span>
      <button class="download" type="button">Download with notes</button>
    </span>
  </div>
  <div class="notes" contenteditable="true" spellcheck="false">{NOTES_MARKER_OPEN}{notes}{NOTES_MARKER_CLOSE}</div>
</div>

</div>
<script>{JS}</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bunnyforge build-sheets",
        description="Build one-page HTML reference sheets (NPC, faction, place) "
                    "for a session.",
    )
    parser.add_argument("session", nargs="?", help="Session number, e.g. 14")
    parser.add_argument("--only", action="append", default=[],
                        help="Build only this entity by filename stem (repeatable)")
    parser.add_argument("--open", action="store_true",
                        help="Open the sheets after building (macOS)")
    parser.add_argument("--list-briefs", action="store_true",
                        help="List sessions that have briefs and exit")
    parser.add_argument(
        "--workspace", metavar="PATH",
        help="Campaign workspace root (default: $BUNNYFORGE_WORKSPACE, else "
             "the nearest campaign.toml above the current directory)")
    args = parser.parse_args(argv)

    try:
        ws = resolve_workspace(args.workspace)
    except (WorkspaceError, ConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    briefs_dir = ws.root / ws.config.briefs_dir
    sheets_dir = ws.root / ws.config.sheets_dir

    if args.list_briefs:
        if not briefs_dir.is_dir():
            print(f"No {briefs_dir} directory yet.")
            return 0
        for d in sorted(briefs_dir.iterdir()):
            if d.is_dir():
                n = len([p for p in d.glob("*.md") if p.name.lower() != "readme.md"])
                print(f"  {d.name}  ({n} brief{'s' if n != 1 else ''})")
        return 0

    if not args.session:
        parser.error("session number required (or use --list-briefs)")

    session = args.session.lstrip("0") or "0"
    padded = session.zfill(3)
    brief_dir = briefs_dir / f"session-{padded}"

    if not brief_dir.is_dir():
        print(f"error: {brief_dir} not found.", file=sys.stderr)
        print(f"       Create it and add one brief per entity, or run --list-briefs.",
              file=sys.stderr)
        return 1

    out_dir = sheets_dir / f"session-{padded}"
    out_dir.mkdir(parents=True, exist_ok=True)

    briefs = [p for p in sorted(brief_dir.glob("*.md"))
              if p.name.lower() != "readme.md"]
    if args.only:
        briefs = [p for p in briefs if p.stem in args.only]
    if not briefs:
        print("No briefs to build.")
        return 0

    built, missing, unknown = 0, [], []
    for brief_path in briefs:
        name = brief_path.stem

        brief_fm, brief_body = split_front_matter(
            brief_path.read_text(encoding="utf-8"))
        brief_sections = parse_sections(brief_body)

        # The brief's `type` decides which writeup directory backs it and which
        # layout and accent the sheet uses. Default to npc for back-compatibility.
        etype = (brief_fm.get("type", "") or "npc").strip().lower()
        if etype == "brief":            # older NPC briefs used type: brief
            etype = "npc"
        if etype not in TYPES:
            unknown.append(f"{name} (type: {etype})")
            continue

        writeup_path = ws.root / ws.config.type_dirs[etype] / f"{name}.md"
        if not writeup_path.is_file():
            missing.append(f"{name} ({etype})")
            writeup_fm, writeup_sections = {}, {}
        else:
            writeup_fm, writeup_body = split_front_matter(
                writeup_path.read_text(encoding="utf-8"))
            writeup_sections = parse_sections(writeup_body)

        fm = {**writeup_fm, **{k: v for k, v in brief_fm.items() if v}}

        # Visibility is the entity's, from the durable writeup only — a brief
        # never changes whether players know the entity exists.
        visibility = normalize_visibility(writeup_fm)
        reveal_when = strip_yaml_comment(writeup_fm.get("reveal_when", ""))

        # Prefix the output filename with type so an NPC and a place of the same
        # name do not collide.
        dest = out_dir / f"{etype}-{name}.html"
        notes = extract_notes(dest)

        dest.write_text(
            render(name, etype, session, writeup_sections, brief_sections, fm,
                   notes, visibility, reveal_when),
            encoding="utf-8",
        )
        carried = " (notes carried forward)" if notes else ""
        print(f"  built  {dest.relative_to(ws.root)}{carried}")
        built += 1

    print(f"\n{built} sheet(s) in {out_dir.relative_to(ws.root)}")

    if missing:
        print(f"\nwarning: no writeup found for: {', '.join(missing)}",
              file=sys.stderr)
        print("         Sheets were built from the brief alone.", file=sys.stderr)

    if unknown:
        print(f"\nwarning: skipped briefs with unknown type: {', '.join(unknown)}",
              file=sys.stderr)
        print(f"         Known types: {', '.join(TYPES)}.", file=sys.stderr)

    if args.open and sys.platform == "darwin":
        subprocess.run(["open", str(out_dir)], check=False)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        sys.stderr.close()
        raise SystemExit(0)
