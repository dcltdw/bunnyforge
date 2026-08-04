# Sample 3 — name shape

**Isolates:** `join`, `place_split`, `given_syllables` — the three knobs that
shape how a given name and a place name are assembled, independent of any
culture's syllable content.

Two cultures, chosen to contrast rather than to pile on: a third would add
files without adding a lesson.

| | `hattuwassa.toml` (Hittite) | `zimrigal.toml` (Akkadian) |
|---|---|---|
| `join` | `"hyphen"` | `"concat"` |
| `place_split` | `0.5` | omitted (defaults to `0.0`) |
| `given_syllables` | `{ min = 1, max = 3, weights = [0.2, 0.5, 0.3] }` | `{ min = 2, max = 2, weights = [1] }` |

`species` is empty on both, for the same reason as every other sample: a
culture here is a place, not a people, and this tool ships no
species-to-tradition mappings.

## What to expect

- **Hattuwassa** spreads across 1-3 syllables, and whenever a given name
  draws 2 or more, `join = "hyphen"` joins them with a dash (e.g.
  `Hattusil Ha-Tar`). `place_split = 0.5` means roughly half its place names
  come out as two words (e.g. `Zippa Wanda`) instead of one (`Zippawanda`).
- **Zimrigal** always draws exactly 2 syllables and concatenates them solidly
  with no separator (e.g. `Ashurbani Sharnabu`) — never a hyphen. Its
  `place_split` is omitted, which defaults to `0.0`, so its place names are
  never split into two words — always one solid word (e.g. `Urgal`).

## Copy-and-go

```
cp cultures/*.toml <your-campaign>/names/cultures/
```

Same precondition as the earlier samples: `campaign.toml`'s
`[names].official_culture`, if set, must name one of `hattuwassa` or
`zimrigal` (or be omitted).

## Not runnable in place

The tools resolve their workspace — the directory holding `campaign.toml` —
from the `--workspace PATH` flag, else the `BUNNYFORGE_WORKSPACE` environment
variable, else the nearest `campaign.toml` walking up from the current
directory. A sample directory holds cultures and no `campaign.toml`, so it is
not a workspace and none of the three resolves to one here. Drive the campaign
you copied into instead: `--workspace <path-to-that-campaign>` works from any
directory, and running from inside it needs no flag at all.

Copying `cultures/*`
into a real campaign's `names/cultures/` is the supported flow, and it works
today.
