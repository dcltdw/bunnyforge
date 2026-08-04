# Sample 7 — an official language

**Not copy-and-go.** Unlike samples 1-6, copying `cultures/*.toml` into your
campaign's `names/cultures/` is not enough on its own. `official_culture`
lives in `campaign.toml`'s `[names]` table, not in any culture file, so this
sample also needs a small merge — `campaign-additions.toml`'s
`official_culture = "nabukathir"` line — into your own `campaign.toml`. See
"Copy-and-go" below for exactly how.

**Isolates:** `official_culture` — a settlement keeps its local name and
additionally carries an administrative one, in the language of a single
configured culture that plays no other role in the setting.

Two regional vernaculars — `byblashar.toml` (Phoenician, the Levantine coast)
and `oxariand.toml` (Bactrian, the Central Asian satrapy at the empire's
opposite edge) — plus one administrative culture, `nabukathir.toml`, drawing
on **Imperial Aramaic**: the actual administrative lingua franca of the
Achaemenid Persian empire, historically layered over local vernaculars from
the Levant to Bactria. Aramaic administrative documents have themselves been
recovered from Bactria, confirming the overlay reached that far east. The
mechanism this sample demonstrates and the tradition it illustrates with are
the same historical fact, not an arbitrary pairing.

All three cultures ship `species = ""`, for the same reason as every other
sample: a culture here is a place, not a people.

## The mechanism

`official_culture` names one culture — here, `nabukathir` — as the setting's
administrative language. A settlement generated for any OTHER culture
additionally prints an administrative name drawn from that one configured
culture:

```
Local            official: Administrative
```

A settlement generated directly for the official culture itself prints no
`official:` column: administrative Aramaic doesn't translate itself into
Aramaic.

## What to expect

(subprocess against a temp workspace with the merge applied — see "Not
runnable in place" below)

```
$ python3 -m bunnyforge.generate_names byblashar --place -n 5 --seed 3
  Sidoimesh        official: Mardaaddanu
  Tyruimesh        official: Aditareshal
  Bybimesh         official: Nabutanesh
  Tyruimesh        official: Sinaraddanu
  Ashkimesh        official: Mardatanesh

$ python3 -m bunnyforge.generate_names oxariand --place -n 5 --seed 3
  Marvavand        official: Mardaaddanu
  Balkhavand       official: Aditareshal
  Oxaravand        official: Nabutanesh
  Balkhavand       official: Sinaraddanu
  Zariqavand       official: Mardatanesh

$ python3 -m bunnyforge.generate_names nabukathir --place -n 5 --seed 3
  Sinarreshal
  Belkareshal
  Nabureshal
  Belkareshal
  Aditareshal
```

`byblashar` and `oxariand` both print an `official:` column carrying a
`nabukathir`-style name; `nabukathir`'s own settlements print no such column,
confirming the skip is keyed on "is this the official culture", not on
whether an `official:` column would be non-empty.

## Copy-and-go — the merge, step by step

```
cp cultures/*.toml <your-campaign>/names/cultures/
```

Then merge `campaign-additions.toml`'s content into your campaign's
`campaign.toml`: open your `campaign.toml`, find its existing `[names]`
table (it already exists — it names your `cultures` directory), and add the
line

```toml
official_culture = "nabukathir"
```

**under that existing `[names]` table** — do not paste a second `[names]`
header. Two `[names]` headers in one TOML file is invalid ("cannot declare
('names',) twice") and the file will fail to parse at all, not just fail to
pick up the new key.

If your campaign already sets `[names].official_culture` to something else,
decide which culture is actually the setting's official one — only one can
be configured at a time.

## Not runnable in place

The tools resolve their workspace — the directory holding `campaign.toml` —
from the `--workspace PATH` flag, else the `BUNNYFORGE_WORKSPACE` environment
variable, else the nearest `campaign.toml` walking up from the current
directory. A sample directory holds cultures and no `campaign.toml`, so it is
not a workspace and none of the three resolves to one here. Drive the campaign
you copied into instead: `--workspace <path-to-that-campaign>` works from any
directory, and running from inside it needs no flag at all.

Copying `cultures/*`
into a real campaign's `names/cultures/` — and, for this sample, also
merging `campaign-additions.toml`'s line into `campaign.toml` — is the
supported flow, and it works today.
