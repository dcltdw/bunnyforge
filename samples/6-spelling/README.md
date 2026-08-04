# Sample 6 — a culture's own [spelling]

**Isolates:** a culture's own `[spelling]` table, layered on top of the
built-in defaults, contrasted against a sibling that has none.

Two cultures with deliberately long syllables:

| | `wertisand.toml` (Tocharian) | `huttanmesh.toml` (Elamite) |
|---|---|---|
| `given_personal` syllable lengths | all 6 characters | 5 or 6 characters |
| longest possible two-syllable join | **12** | **12** |
| shortest possible two-syllable join | 12 (every pair is 6+6) | **10** |
| own `[spelling]` | `max_join_length = 12` | none |
| effective `max_join_length` | 12 | 9 (built-in default) |

Both `species` fields are empty, for the same reason as every other sample.
`draws_on` names real, attested, historical traditions neither of which any
earlier sample uses: **Tocharian** (Tarim Basin oasis
city-states, attested through Buddhist manuscripts) and **Elamite** (Susa
and the surrounding region, attested across three millennia).

## The numbers, computed against the pools, not asserted

The built-in floor is `max_join_length = 9`. A prior plan in this phase
shipped an override that turned out to be inert, because the culture's
longest possible two-syllable join was already under 9 — so the override
never did anything, and its justifying comment claimed otherwise. This
sample's numbers are computed, not asserted:

- **`wertisand.toml`**'s `given_personal` pool
  (`yakwek, ashiyo, wersti, klyoma, tsopar, onkalm`) is six syllables, every
  one exactly 6 characters. Every possible pairing therefore joins to
  exactly **12** characters — always above the built-in floor of 9, never
  below it. Its own `[spelling]` sets `max_join_length = 12`, which is
  large enough to admit that join: the override is not inert.
- **`huttanmesh.toml`**'s `given_personal` pool
  (`hutran, kiddin, napirs, huban, shutru, tepti`) has five 6-character
  syllables and one 5-character syllable. The *shortest* possible pairing
  (`huban` + `tepti`) is already **10** characters — still above 9. Because
  this file carries no `[spelling]` of its own, it inherits the built-in
  default of 9, and **every** possible pairing (10 to 12 characters)
  exceeds it. A two-syllable given name from this pool is not merely
  unlikely here — it is structurally unreachable.

## What to expect

```
$ python3 -m bunnyforge.generate_names wertisand -n 10 --seed 7
  Werstan Klyomayakwek
  Yakweshtar Yakwekwersti
  Tsoparu Tsopar
  Ashiyar Klyoma
  Klyomek Yakwek
  Tsoparu Tsopar
  Yakweshtar Onkalmtsopar
  Yakweshtar Klyomayakwek
  Ashiyar Ashiyo
  Werstan Tsopar

$ python3 -m bunnyforge.generate_names huttanmesh -n 10 --seed 7
  Kidinu Shutru
  Untashnap Hutran
  Napirsha Kiddin
  Shutruknah Napirs
  Napirsha Napirs
  Hubanhal Hutran
  Untashnap Napirs
  Hubanhal Kiddin
  Kidinu Kiddin
  Hubanhal Huban
```

Wertisand reaches genuine 12-character two-syllable compounds —
`Klyomayakwek` (klyoma + yakwek), `Yakwekwersti` (yakwek + wersti),
`Onkalmtsopar` (onkalm + tsopar) — that huttanmesh cannot produce under the
built-in floor: every given name huttanmesh generates above is a single
syllable, because no pairing from its pool ever fits under 9.

## `[spelling]` must be the LAST thing in the file

In TOML, a table header swallows every bare key that follows it. A
`[spelling]` block placed above `place` and `place_tail` would swallow
them, and the loader would then reject the file for a missing `name` — the
right error for a baffling-looking reason. `wertisand.toml`'s `[spelling]`
table is the last thing in the file for exactly this reason; see its own
comments.

## `campaign-additions.toml` — optional, and the sample works without it

This sample is **copy-and-go without `campaign-additions.toml`**: copying
`cultures/*.toml` alone reproduces everything shown above. The file is
provided so a reader can additionally watch the **middle** spelling layer
(campaign.toml's setting-wide `[names.spelling]`) take effect, between the
built-in default and a culture's own `[spelling]`.

`campaign-additions.toml` sets `max_length = 8` — more restrictive than the
built-in default of 12. Merge it into your campaign's `campaign.toml` and
run the same commands again:

```
$ python3 -m bunnyforge.generate_names wertisand -n 10 --seed 7
  Tsoparu Tsopar
  Ashiyar Klyoma
  Klyomek Yakwek
  Tsoparu Tsopar
  Ashiyar Ashiyo
  Werstan Tsopar
  Werstan Onkalm
  Werstan Ashiyo
  Ashiyar Wersti
  Tsoparu Wersti
```

The 12-character compounds are gone, and so is the family name
`Yakweshtar` (10 characters) — even though `wertisand.toml` carries its own
`[spelling]`. That table sets only `max_join_length`; it never touches
`max_length`, so `max_length` still comes from whichever layer beneath it
last set it — here, the setting layer. Each spelling layer overrides only
the keys it sets: a culture's own `[spelling]` protects the keys it names,
not every key.

## Copy-and-go

```
cp cultures/*.toml <your-campaign>/names/cultures/
```

Same precondition as the earlier samples: `campaign.toml`'s
`[names].official_culture`, if set, must name `wertisand` or `huttanmesh`
(or be omitted) — otherwise the loader fails at import with
`InventoryError`.

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
