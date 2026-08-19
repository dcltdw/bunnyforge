# AGENTS.md

How to work in this repository. Process rules, not content rules — for tone,
voice, and prose constraints see `[[style-guide]]`.

This is a creative writing workspace for a long-running tabletop RPG campaign.
It is not a software project. The canonical material lives in files in this
directory. Conversation history is not canon and must not be treated as such.

## What a leading underscore means

A `_`-prefixed name is **not canon** — that is the whole rule, and it runs
both ways: everything that is not canon carries the marker, except the
repo-infrastructure directories (`docs/`, `scripts/`, `tests/`), which keep
their ecosystem names. `.`-prefixed names are hidden machine files, invisible
everywhere. `Archive/` carries no underscore for the same reason: it is
canon — the record of what happened — see the retirement rule under **File
conventions**.

The marker says nothing about whether you may *read* a directory; each one
carries its own contract, stated where it is introduced. `_Ignore/` holds raw
material, plus retired work that set no precedent: **never read it** unless I
name a file in it and ask. `_Templates/` is the reference for front-matter
shape. `_ExtractInbound/` is read only when I ask (its own section below).
`_AgentDrafts/` is read freely. A `_`-directory this file does not name
defaults to **never read unless I ask**; campaign-specific exceptions belong
in `[[campaign-doctrine]]`.

## This file and `[[campaign-doctrine]]`

This file is generic. The bunnyforge package owns it, ships it identically to
every workspace, and replaces it wholesale when a new version is adopted — so
anything written into it that is true of this campaign only will be lost.
`[[campaign-doctrine]]` is the other half: campaign-specific rules, owned by
me, never overwritten.

Where the two disagree, `[[campaign-doctrine]]` wins. It is required to name
the rule here that it displaces, so an exception is visible from both sides
rather than inferred.

## Read order

At the start of any working session, read in this order:

1. `[[campaign-doctrine]]` — this campaign's own rules. First, because it can
   override anything in this file, and it says so where it does.
2. `[[front-burner]]` — current state. Outranks every older file on any conflict.
3. `[[compendium]]` — the index. Use it to find what else is relevant.
4. `[[style-guide]]` — binding constraints on tone and voice.
5. `[[situation-design]]` — how prep material is structured. Read before
   building any scenario, NPC, or faction material.
6. `[[open-questions]]` — what is deliberately undecided.

Then read the entity files relevant to the task at hand.

## Clarify before proceeding

Before acting on any request — *including* an explicit "please proceed with X" —
if you have a genuine clarifying question, a substantive countersuggestion, or a
concern, raise it and **wait** for a response. Do not perform agreement, and do
not suppress a concern to seem agreeable.

The flip side: do not manufacture questions when something is genuinely clear.
Proceeding without asking signals you genuinely had none.

In creative work the questions that matter most are the ones that change the
*shape* of the output: whose POV, what the scene is for, what the reader already
knows, what the scene has to accomplish. Ask those before drafting, not after.

If you think the requested thing is the wrong thing to write, say so before
writing it.

## Task-start context

Some questions recur at the start of every task, and missing one is how
work goes wrong quietly. Before work begins, check each question below.
Skip the ones my request already answers and the ones that do not apply
to the kind of task at hand — skipping all of them is the normal case
for a complete request, and this list licenses no manufactured asks (see
**Clarify before proceeding** above). Ask me the rest **in one
message**, not one at a time.

1. **What are we building** — a plot, an encounter, a combat? A writeup
   or a brief? (**What gets written where**, below, carries the
   distinction.)
2. **Will new NPCs be created, or existing ones reused?**
3. **Should retrieval draw on live canon, the archive, or both?**
   (**Retrieval scope**, below, carries the full rule.)
4. **Is any of the output meant to be player-visible?** `gm-only` is the
   fail-safe default (**Player visibility**, below), but a wrong silent
   default costs a re-edit later.

Answers attach to the work and persist: picking a piece back up later
continues under the answers it was made with. One bundled ask per task;
hold the answers until the task changes or I re-answer.

The list is doctrine, and it grows as gaps appear. Questions specific to
one campaign belong in `[[campaign-doctrine]]`; a gap that would bite
any campaign belongs upstream as a bunnyforge ticket.

## Verify against the files, not against earlier prose

A fact restated in a conversation summary is not verified. Before relying on a
detail — a name, a date, who was present, what an NPC knows — re-read it in the
file that owns it. Summaries compress, and compression drops exactly the
specifics that cause continuity breaks.

Report what you checked versus what you assumed. If you could not find a fact,
say so rather than filling the gap with the most plausible option.

## Spike before declaring something unwritable

Before deferring on the grounds that material is missing, do a cheap check that
it is actually missing — search the workspace, check `[[compendium]]`, check
`[[open-questions]]`. A deferral resting on a stale assumption wastes the turn.
Often "I need to know X first" turns out to be already answered in a file.

## Perceptions are belief, not fact

`Perceptions/` holds player-authored material exported from the wiki, marked
`canon: perception`. It records what the players believed at a point in time.

- Never cite a perception file as evidence of what is true.
- Never edit a perception file. They are regenerated from the wiki, and
  correcting a player's belief destroys the only thing the record is good for.
- Do use them to answer questions about what the party thinks, what they have
  noticed, what they have missed, and where their theory diverges from my plan.

The gap between `Perceptions/` and the GM canon is the most useful thing in this
workspace. When asked to reconcile the two, treat both as fixed inputs and
propose changes to canon — not to the perception record.

## Extracting from _ExtractInbound/

`_ExtractInbound/` is an inbound queue for material brought into the workspace
— typically wiki pages unpacked from a tarball. It is distinct from `_Ignore/`,
which is never read.

- **Read it only when I ask you to extract.** Do not act on its contents
  proactively. You may notice it is non-empty and offer; you may not process it
  unbidden.
- **The MCP agent reaches this queue through `list_inbound` and
  `read_inbound`, under exactly these rules.**
- **Nothing in it is canon.** It is unreviewed source, and a copy — the wiki is
  the source of truth until the material is extracted into proper entity files.
- **On any conflict, ask — this is "Clarify before proceeding" applied here.**
  If something in the inbound material disagrees with an existing writeup, the
  style guide, or the compendium, stop and ask. Do not resolve it yourself, in
  either direction: the material may be newer than the workspace or older, and
  an apparent contradiction is often not one at all. (Two documents naming a
  guard captain who retires and a guard captain who is killed are describing two
  people, not one fact to reconcile.) When in doubt, surface it and let me
  answer.
- **Extract, show me, confirm, then move — never delete.** Once I confirm
  an extraction, move the spent source into `_ExtractInbound/_Done/` — or,
  if you cannot move files, say so and I will. Do not delete it; I clear
  `_Done/` myself. And never move anything before I have confirmed. The
  active directory emptying is how we track what remains to process.
- **`_ExtractInbound/_Done/` is never read**, exactly like `_Ignore/`. It holds
  processed source awaiting my manual cleanup.

## Version control

This workspace is a git repository. Commit content changes with a short
message naming what changed and why; never commit generated output
(`_Export/`, `_Reviews/`, `_Sheets/`) — `.gitignore` already excludes it.

This machine's specific git configuration — remote, separate git directory,
and bootstrap steps — is recorded in `docs/workspace-setup.md`. Read that file
rather than assuming any particular layout.

## Reviewing the workspace

`bunnyforge review checkup` runs the mechanical review suite (visibility audit,
front-matter, wikilinks, compendium completeness, reveal-when, name
collisions). "Run the checkup" also walks the agent-judgment checklist in
`checks/checkup.md`. Deferred tooling work is tracked in GitHub Issues (see
`[[tickets]]`).

## Player visibility

Every content file carries a `visibility` field in its front matter, an axis
independent of `canon`. It answers: who may see this?

- **`gm-only`** — the whole file is for the GM. Its existence or content would
  spoil. Example: a homebrew mechanic whose existence is itself the reveal.
- **`player-visible`** — the file's primary content (a mechanic's rules text, a
  place's public description) may be shown to players. The standard
  meta-sections — **Design intent, Balance notes, Playtest log** — remain
  GM-only regardless; `player-visible` licenses the rules/player-facing
  sections, not the whole file.
- **`mixed`** — the file uses an explicit `## GM notes` separator (handout
  style, below) to split audiences within one file.

The state is **swappable**: change `visibility` when it changes. For a file
that flips at an in-world event, record the trigger in an optional
`reveal_when:` field (e.g. `reveal_when: the coronation`) and swap
`visibility` when the event fires in play. This keeps the *why*, not only the
current state.

Default to `gm-only` when unsure — it is the fail-safe. Nothing is leaked by
being too cautious. Enforcement lives in `bunnyforge.export_player`, a full
player-facing export that writes a player-safe copy of every non-`gm-only`
file to `_Export/` (gitignored, generated): it drops `gm-only` files entirely,
keeps only the portion above `## GM notes` for `mixed` files, and strips the
Design intent / Balance notes / Playtest log sections from everything else.
Run it with `bunnyforge export-player`.

Visibility lives on the **durable writeup**, not on briefs. A session brief
inherits its entity's visibility from the writeup and does not carry the
field — a brief must never be able to change whether players know an entity
exists.

## Handouts

Handout files separate player-facing text from GM notes with a horizontal rule
followed by a `## GM notes` heading. Everything below that line is GM-only and
must never appear in player-facing output. When drafting a handout, always
include the separator, even if the GM notes section is empty. A handout is a
`mixed`-visibility file by construction.

## Never invent canon

- Do not invent canon to fill a gap. Ask, or mark it `speculative`.
- Do not resolve a plot thread that has not been resolved in play.
- Do not give NPCs knowledge they have no in-world route to acquiring.
- Do not contradict `[[front-burner]]`; it outranks older files.
- Do not rename, renumber, or silently retcon existing entities.
- Do not present `Archive/` material as current. It is canon, read like any
  canon — what was decided, what was tried, and why the thing that replaced
  it looks the way it does is exactly what it is for — but it is superseded
  by definition, so where it disagrees with a live file, the live file wins.
- Do not read `_Ignore/`. It is unmigrated raw material, unreviewed and
  partly contradicted by the rest of the workspace — plus retired work that set
  no precedent (see the deletion rule below). It is not canon, and it is not a
  fallback when an answer cannot be found elsewhere. The only exception is
  a file in it that I name explicitly and ask you to work on.
- Do not read `_ExtractInbound/` unless I ask you to extract from it. It is an
  inbound queue for imported material, none of it canon. See its own section
  below.
- `_AgentDrafts/` is the agents' outbox: drafts and proposed revisions
  awaiting my review, written by the MCP tools (or by you, if I ask you to
  draft something). Read it freely; nothing in it is canon. If I reject a
  draft I delete it or move it to `_AgentDrafts/_Rejected/`, which is
  never read, like `_Ignore/`.

## Retrieval scope: live, archive, or both

- When answering questions or reporting what is established, read live and
  archived material freely. Results are labelled, and the rules above
  govern presentation: the archive is never current, and where it disagrees
  with a live file, the live file wins.
- Creative work on canon — inventing new material, or revising it later —
  runs under a retrieval scope I own. Drawing on retired material can be
  deliberate (a successor, an echo) or contamination (a "new" thing that
  quietly re-skins a retired one). Labels do not protect generation:
  material read is material that shapes the output. Only I can tell the
  two intents apart.
- So the scope question is one of the standing questions in **Task-start
  context** above, and runs under its discipline: raised when a task
  will create or revise canon and my request has not already answered
  it, bundled with the other open questions, held for the task.
- Mechanically: over MCP, pass `scope=` to `search` and `list_entities`;
  on the filesystem, read or skip `Archive/` accordingly.

## Speculative material stays speculative

Anything you propose that I have not accepted is `speculative`. Do not carry a
proposal forward into later work as though it were settled, and do not let a
`speculative` fact from `Ideas/` leak into canon prose without being flagged.

`Ideas/` is `canon: speculative` by default. Treat every file in it as material
under consideration only.

## Delivering drafts

### Offer the reach and the plain version together

`[[style-guide]]` permits narration to occasionally reach for compressed,
evocative phrasing. When you take that reach, **offer a plainer alternative in
the same breath**, so it can be accepted or declined without a round trip:

> She set down the cup of ember-wine, still steaming.
> *(plain: She set down the cup of mulled wine, still steaming.)*

This applies to the reach, not to every sentence. If a passage has no elevated
phrasing, no alternative is needed. If it has three, the passage is already
wrong — see the style guide's cap.

Expect this to be calibrated over time. When a reach is accepted or rejected,
that is data about where the line sits.

### Flag invented canon in drafts

Prose and prep written for this campaign will inevitably establish small facts —
a street name, a dish, a minor NPC's manner. That is fine and necessary. But say
what you invented, in a short list after the draft, so it can be promoted to
canon or struck.

Do not bury new facts in prose and let them become canon by default.

## What gets written where

Most work on this campaign is **prep material**, not narrative prose. Three
kinds of file hold it, and putting something in the wrong one is the most common
structural mistake:

**The writeup** — `NPCs/mira-venn.md`, `Factions/harbor-guild.md`, `Setting/*.md`.
What is true *always*. Accretes over the campaign and is never session-specific.
Its **Synthesis** section is the highest-value part: a current portrait written
so that someone can predict how this entity reacts to something unplanned.
Rewrite the Synthesis as things change; the **Log** below it is append-only and
preserves what it used to say.

**The brief** — `Briefs/session-014/mira-venn.md`. What is true *this session*.
Terse. Exists for NPCs, factions, and places alike; the brief's `type` field
selects which. Sections here override the writeup's sections of the same name
when the sheet is built. Omit a section to inherit from the writeup; an empty
section is not the same as an absent one.

**The record** — `Sessions/session-014.md`. What actually happened, written
afterwards, append-only, never revised to fit a later decision.

`_Sheets/` is generated by `bunnyforge build-sheets` and must not be hand-edited
except in the notes area, which survives regeneration. Never treat a sheet as a
source of truth; it is derived from the writeup and the brief.

If asked for "an NPC," produce a writeup. If asked for prep for a specific
session, produce a brief. If unsure which is wanted, ask — the distinction is
load-bearing.

## Which file a new fact belongs in

Once you know *which kind* of file (above), this decides *which* file. When
something is established — in play or in writing — decide its scope before
recording it:

- **World-level** truth that constrains everything (cosmology, hard rules, tone)
  belongs in `[[compendium]]` or `[[style-guide]]`.
- **Entity-level** truth belongs in that entity's file in `NPCs/`, `Setting/`,
  `Factions/`, etc.
- **Current state** — position, momentum, who knows what right now — belongs in
  `[[front-burner]]` and nowhere else.

A world-level rule recorded in one NPC's file is invisible everywhere else. The
next session that needs it will not find it, and will invent an answer that
quietly contradicts this one.

## Situations, not plots

`[[situation-design]]` governs how scenarios are built. Its core requirements
apply to any prep material produced here:

- Three ways in, three genuinely different ways out, no preferred resolution.
- The **consequence cap**: the world moves when the party is elsewhere, but the
  cost of not engaging registers without devastating. Never write a consequence
  whose function is to teach the party a lesson about neglect.
- Every situation needs a version where the party does not engage at all.
- Backstory held in reserve, marked `speculative`, chosen at runtime.

## File conventions

- One entity per file. Filenames are lowercase-kebab-case, matching the entity's
  primary name.
- Every content file carries the YAML front matter described in
  `_Templates/`. The `summary` field must stand alone without pronouns or
  outside context; it is often the only part retrieved.
- Add every alias, title, and epithet to `aliases`. A file that cannot be found
  under the name someone uses for it is a file that does not exist.
- Every content file carries a `visibility` field (`gm-only` |
  `player-visible` | `mixed`), plus optional `reveal_when`. See **Player
  visibility** above. Default `gm-only` when unsure.
- Cross-reference with wikilinks: `[[style-guide]]` for a document,
  `[[Mechanics]]` for a directory.
- New files must be added to `[[compendium]]` in the same sitting. An unindexed
  file is an invisible file.
- Session files are append-only. Do not revise a past session to fit a later
  decision; add a correction note.
- Brief filenames must match their writeup: `Briefs/session-014/mira-venn.md` pairs
  with `NPCs/mira-venn.md`. A mismatch produces a sheet built from the brief alone.
- Generated sheets in `_Sheets/` are not canon and are not edited by hand.
- Nothing is deleted. Superseded material that was **used** moves to
  `Archive/` with `status: retired`, mirroring its section
  (`Archive/NPCs/old-hag.md`): it happened, so it is part of the record, and
  a retired thing still explains why what replaced it looks the way it does.
  That is why the archive is canon rather than machinery. Two rules when
  retiring: if the name will be reused by a replacement, rename the retiring
  file first — every stem and alias among writeups and root docs must name
  exactly one file, and `review checkup` enforces that — and update the
  file's `[[compendium]]` entry to its `Archive/` path. Material that never
  got used, or that was used once and can never be relevant again, sets no
  precedent — an abandoned draft of something later rebuilt from scratch, or
  a one-time instruction that did its job and whose steps the result has
  since contradicted. That moves to `_Ignore/` instead, which is never read
  at all. Note what the second move costs: `_Ignore/` is git-ignored, so the
  file leaves version control. It stays on disk, and its history up to the
  move remains, but a fresh clone will not contain it — which is the
  intended end state for material that constrains nothing.

## At the end of a working session

Tell me which files the session made stale — entity files contradicted by new
events, `[[front-burner]]` if state moved, `[[compendium]]` if entities were
created, `[[open-questions]]` if something was answered or newly opened. Draft
the updates rather than only listing them.

