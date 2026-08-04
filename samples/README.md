# Sample settings

A ladder of sample settings, each isolating one axis of the naming schema.
Pick the one closest to your campaign, copy its cultures into place, and get
working names immediately — no sample depends on another's.

Every sample culture ships `species = ""`. This tool ships no
species-to-real-world-tradition mappings — which real naming tradition a
fantasy species draws on is a setting-authorship decision, and this tool
takes no position on it. A culture here is a **place**, not a people:
several species can live in one place and share its names. `draws_on` names
a real, attested, historical tradition so you know where to look for source
material; lookup happens through that, never through species.

The tools resolve their workspace — the directory holding `campaign.toml` —
from the `--workspace PATH` flag, else the `BUNNYFORGE_WORKSPACE` environment
variable, else the nearest `campaign.toml` walking up from the current
directory. A sample directory is not a workspace: it holds cultures and no
`campaign.toml`. Copy a sample's cultures into a real campaign, then drive
that campaign with `--workspace <path-to-that-campaign>` from any directory,
or run from inside it and let the walk find it with no flag at all.

Copying a sample's `cultures/*` into a real campaign's
`names/cultures/` is the supported flow.

| # | Directory | Isolates | Copy-and-go |
|---|---|---|---|
| 1 | [`1-one-people`](1-one-people/) | The floor. One culture, `categories = ["personal"]`, zero optional keys. | yes |
| 2 | `2-many-peoples` | Several cultures; alias lookup via `draws_on`; species decoupled. | yes |
| 3 | `3-name-shape` | `join`, `place_split`, `given_syllables`. | yes |
| 4 | `4-genders` | Genders that are not male/female. | yes |
| 5 | `5-name-registers` | Categories that are not genders at all. | yes |
| 6 | `6-spelling` | A culture's own `[spelling]` against the built-in floor. | yes |
| 7 | `7-official-language` | `official_culture` — local plus administrative names. | **no** |
| 8 | `8-capstone` | Everything at once. | **no** |

"Copy-and-go" means: copying `cultures/*.toml` into your campaign's
`names/cultures/` is sufficient. Samples 7 and 8 also need a two-line merge
into `campaign.toml` (`[names].official_culture`, and a `[names.spelling]`
block where present) — see each of those samples' own README for exactly
how.
