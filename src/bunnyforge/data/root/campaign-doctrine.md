# Campaign Doctrine

Rules that apply to *this* campaign and no other. `[[AGENTS]]` is the generic
agent contract: the bunnyforge package owns it, ships it identically to every
workspace, and replaces it wholesale when you adopt a new version — so
anything campaign-specific written into it is lost on the next adoption. This
file is the other half, and it is yours. No packaged version of it will ever
overwrite what you write here.

Where a rule below contradicts `[[AGENTS]]`, this file wins — but say so in
the rule itself, naming the generic rule it displaces, so an exception is
visible from both sides rather than inferred.

An agent that finds this file empty should carry on with `[[AGENTS]]`
unchanged. Nothing here is required.

## Subtrees with their own rules

<!-- Directories that do not follow the workspace's normal conventions: a
     conlang enclave, an imported ruleset, anything with its own file format
     or its own checker. Say what stops applying, and what applies instead. -->

## Exemptions from the generic contract

<!-- Places where a rule in AGENTS.md does not hold here. Name the rule, say
     how it changes, and say why. An exemption nobody wrote a reason for gets
     re-litigated every few months. -->

## Task-start questions for this campaign

<!-- Extra questions this campaign's tasks must answer before work begins,
     beyond the generic set in AGENTS.md's "Task-start context" section.
     Also the place to strike or rephrase a generic question -- name the
     rule displaced, as with any exemption. -->

## Extra tools and checks

<!-- Commands this campaign runs that bunnyforge does not ship: campaign
     tests, custom checkers, scripts an agent should run before saying
     something is done. -->
