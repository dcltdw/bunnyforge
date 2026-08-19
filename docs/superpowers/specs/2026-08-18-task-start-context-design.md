# Task-start context: contextual questions before work begins (#70)

Design for issue #70. Generalizes the one task-start question #66 shipped
(retrieval scope: live/archive/both) into the framework it turned out to be an
instance of: a small, explicit set of contextual questions answered before any
task's work begins, so nothing falls between the cracks.

Decisions below were settled with the GM in brainstorming on 2026-08-18.

## Decisions

1. **The framework governs all tasks.** Not only creative/canon work. A
   question that does not apply to the task's kind is skipped silently, and a
   question the request already answers is skipped silently — so a Q&A task
   typically skips everything and pays no friction.
2. **Initial question set — four questions:**
   - What are we building — plot, encounter, combat; writeup or brief?
   - Will new NPCs be created, or existing ones reused?
   - Retrieval scope: live, archive, or both? (#66's question, folded in.)
   - Is any of the output meant to be player-visible?
3. **One bundled ask.** All applicable-and-unanswered questions go to the GM
   in a single message at task start. "One ask per task" now means literally
   one message, not one per question.
4. **Placement: split.** The framework and the four generic questions live in
   packaged doctrine (`src/bunnyforge/data/doctrine/AGENTS.md`).
   Campaign-specific growth — extra questions, or striking/rephrasing a
   generic one — lives in the GM-owned `campaign-doctrine.md`, whose scaffold
   gains a commented stub section. Release cost: this enlarges the single
   hand-reconcile diff the current release (#69) already forces, rather than
   creating a second reconcile event a release later — which is exactly the
   cost #69 accepted when it pulled #70 into this release.
5. **Composition: doctrine owns the list; the tool surface carries pointers
   only.** The existing `search`/`list_entities` scope mirrors stay exactly
   as they are — they exist because those tools have a `scope=` parameter the
   question governs, which is not an N-questions pattern and does not
   generalize. `campaign_overview`'s docstring — the designated "call this
   before anything else" moment — gains one pointer sentence. No new tools,
   no new resources, no question list in any payload.

## Component 1: packaged doctrine — new section "Task-start context"

A new `## Task-start context` section in
`src/bunnyforge/data/doctrine/AGENTS.md`, placed immediately after "Clarify
before proceeding". They are siblings: clarify governs the task-specific
questions that emerge from a request; task-start context is the standing
checklist every task is held against first.

Content shape (final prose written at implementation time, under the style of
the surrounding file):

- **The rule.** At the start of any task, before work begins, check the
  questions below. Skip silently any the request already answers and any
  that do not apply to the task's kind. Ask the GM the rest **in one
  message**.
- **The generic list**, each question one line plus a pointer to the section
  carrying its full rule:
  1. What are we building — plot, encounter, combat; writeup or brief?
     (→ "What gets written where".)
  2. Will new NPCs be created, or existing ones reused?
  3. Retrieval scope: live, archive, or both? (→ "Retrieval scope: live,
     archive, or both", which keeps its rationale and mechanics.)
  4. Is any of the output meant to be player-visible? (→ "Player
     visibility"; `gm-only` remains the fail-safe default, but a wrong
     silent default costs a re-edit later.)
- **Persistence**, generalized from #66: answers attach to the work and
  persist — picking a piece back up later continues under the answers it was
  made with. One bundled ask per task, held until the task changes or the GM
  re-answers.
- **Growth.** The list is doctrine and grows as gaps appear.
  Campaign-specific questions belong in `[[campaign-doctrine]]`; a gap that
  is generic goes upstream as a ticket.
- **Relation to "Clarify before proceeding".** These questions do not license
  manufacturing asks: skipping all four is the normal case for a task whose
  request is complete.

**Duplication collapse.** The "Retrieval scope: live, archive, or both"
section currently carries its own ask discipline ("ask at task start …
One ask per task; hold it until the task changes or I re-scope it"). Those
sentences are replaced with a pointer to the task-start section, so the ask
discipline has a single owner. The scope section keeps what is genuinely its
own: the answering-vs-creative distinction, the contamination rationale, and
the `scope=` mechanics.

## Component 2: campaign-doctrine.md scaffold — one stub section

`src/bunnyforge/data/root/campaign-doctrine.md` gains one commented stub
section alongside the existing three, e.g.:

```markdown
## Task-start questions for this campaign

<!-- Extra questions this campaign's tasks must answer before work begins,
     beyond the generic set in AGENTS.md. Also the place to strike or
     rephrase a generic question — name the rule displaced, as with any
     exemption. -->
```

No migration machinery. Workspaces scaffolded before this change simply lack
the section; nothing reads it mechanically, and the packaged section's
`[[campaign-doctrine]]` pointer covers them. Same graceful-absence stance the
doctrine-resource listing already takes for an absent `campaign-doctrine.md`.

## Component 3: serve_mcp.py — one docstring sentence

Append one sentence to `campaign_overview`'s docstring, roughly:

> Then, before work begins, answer the task-start questions in the AGENTS.md
> doctrine resource — ask the GM the ones the request has not answered, in
> one message.

Tool docstrings are the remote agent's decision surface (the file says so),
so the sentence is a pointer, not a restatement of the list. The
`search`/`list_entities` scope mirrors are untouched. No other code changes.

## Testing

Follow the established patterns; all tests run against packaged bytes or
temp-dir workspaces — no test writes into the repo.

- `test_init.py` style, section-scoped assertions on
  `init.packaged_bytes("doctrine/AGENTS.md")`:
  - `## Task-start context` exists and names all four questions.
  - The retrieval-scope section points at the task-start section and no
    longer carries its own ask-discipline sentences.
  - The existing wikilink-resolution test automatically covers any new
    `[[...]]` links the section introduces.
- Scaffold assertion that the packaged `campaign-doctrine.md` carries the new
  stub section.
- `test_serve_mcp.py` style assertion that `campaign_overview`'s advertised
  description carries the task-start pointer.

Suite: `PYTHONPATH=src python3 -m unittest discover -s tests -t .` from the
worktree root. Baseline on main (2800873): `Ran 931 tests … OK (skipped=57)`;
the 57 skips are the optional mcp extra.

## Release and portability notes

- #65 is deferred: nothing mechanically screens packaged data for
  campaign-specific terms. The new `AGENTS.md` and scaffold prose must be
  cleared by a deliberate human read at PR time — the same basis recorded on
  PRs #72 and #75. The implementation plan must say so.
- #69's release notes already anticipate #70 changing the packaged
  `AGENTS.md`; this design adds one section and edits one, covered by the
  existing hand-reconcile/migration-recipe pointer.

## Out of scope

- Any mechanical enforcement of the questions (payloads, new tools, checks).
- Migrating existing campaigns' `campaign-doctrine.md` to carry the stub.
- #65 (packaged-prose screening) and #74 remain deferred.
