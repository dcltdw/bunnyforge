# Sample 8 — the capstone

**Not copy-and-go**, for the same reason as sample 7 and then some.
`campaign-additions.toml` here carries **two** things that live only in
`campaign.toml`, not in any culture file: `official_culture`, and a
setting-wide `[names.spelling]`. Both need merging into your own
`campaign.toml` for everything below to actually take effect — see
"Copy-and-go" for exactly how.

**Isolates:** everything at once. Four cultures, each carrying one lesson
from an earlier sample in this ladder, layered into a single setting:

| Culture | Draws on | Carries |
|---|---|---|
| `takshashri.toml` | Gandhari | non-gender categories (`householder`, `renunciant`) — sample 5 |
| `frashovant.toml` | Avestan | mixed name shape (`join = "hyphen"`, variable `given_syllables`, `place_split`) and ordinary `m`/`f` genders — sample 3 / sample 4 |
| `khotanreza.toml` | Khotanese | its own `[spelling]` — sample 6 |
| `nisayavesh.toml` | Parthian | the official/administrative culture — sample 7 |

Every culture ships `species = ""`, for the same reason as every other
sample. Four fresh traditions, none reused from earlier samples or from
sample 7's Phoenician/Bactrian/Imperial Aramaic: **Gandhari** (Kharosthi
script, attested through Buddhist manuscripts from the Gandhara region),
**Avestan** (the liturgical language of the Zoroastrian Avesta), **Khotanese**
(a Middle Iranian language of the Tarim Basin oasis kingdom of Khotan,
Buddhist-attested, distinct from sample 6's Tocharian — a different,
non-Iranian-speaking Tarim Basin people), and **Parthian** (the Arsacid
dynasty's language, ruling many regional vernaculars — its own distinct
historical administrative role, not a reuse of sample 7's Imperial Aramaic).

## What to expect

(subprocess against a temp workspace with **both** lines of
`campaign-additions.toml` merged — see "Not runnable in place" below)

**Non-gender categories** (`takshashri`, seed 5):

```
$ python3 -m bunnyforge.generate_names takshashri --gender householder -n 4 --seed 5
  Menandra Menakani
  Azesha Mena
  Gondopha Vasumena
  Kanishka Gondazes

$ python3 -m bunnyforge.generate_names takshashri --gender renunciant -n 4 --seed 5
  Azesha Sangh
  Gondopha Bodhi
  Kanishka Sangh
  Menandra Arah
```

**Mixed name shape and ordinary genders** (`frashovant`, seed 5) — hyphenated
multi-syllable given names, drawn from separate `m`/`f` pools:

```
$ python3 -m bunnyforge.generate_names frashovant --gender m -n 6 --seed 5
  Yoishta Mazd
  Yoishta Vohu
  Yoishta Ahura
  Vishtaru Vohu
  Jamaspa Zara
  Vishtaru Ahura

$ python3 -m bunnyforge.generate_names frashovant --gender f -n 6 --seed 5
  Yoishta Daena
  Yoishta Chista
  Jamaspa Armaiti
  Vishtaru Daena
  Vishtaru Armaiti
  Vishtaru Ashi
```

**A culture's own `[spelling]`, and the setting-wide layer on top of it**
(`khotanreza`, seed 5). `khotanreza.toml`'s `given_personal` pool
(`khotan, vijay, gyazas, nandiv, suraj, ttamra` — five 6-character syllables
and one 5-character syllable) has the same shape as sample 6's pair: its
shortest possible two-syllable join (`vijay` + `suraj` = 10 characters)
already exceeds the built-in `max_join_length` floor of 9, so its own
`[spelling]` sets `max_join_length = 12` to reach every pairing (10-12
characters). **Before** `campaign-additions.toml` is merged, that override
alone is in effect:

```
$ python3 -m bunnyforge.generate_names khotanreza -n 10 --seed 5
  Suraja Gyazas
  Suraja Nandiv
  Gyazaste Vijaykhotan
  Khotanraja Vijay
  Nandivard Surajvijay
  Vijitasi Nandivgyazas
  Gyazaste Nandivvijay
  Vijitasi Suraj
  Nandivard Khotan
  Vijitasi Vijay
```

Two-syllable joins (`Vijaykhotan`, `Surajvijay`, `Nandivgyazas`,
`Nandivvijay`) and the 9-10 character family names `Khotanraja` and
`Nandivard` all appear. **After** merging `campaign-additions.toml`'s
`[names.spelling]` (`max_length = 8`, more restrictive than the built-in
default of 12) — which reaches `khotanreza` too, because its own
`[spelling]` sets only `max_join_length`, never `max_length`:

```
$ python3 -m bunnyforge.generate_names khotanreza -n 10 --seed 5
  Suraja Gyazas
  Suraja Nandiv
  Vijitasi Suraj
  Vijitasi Vijay
  Vijitasi Gyazas
  Suraja Suraj
  Vijitasi Suraj
  Suraja Vijay
  Suraja Ttamra
  Suraja Gyazas
```

Every two-syllable given-name join and both long family names are gone —
only `Vijitasi` (8) and `Suraja` (6) remain, and every given name is a
single syllable. Each spelling layer overrides only the keys it names, not
every key: this culture's own `[spelling]` still wins on `max_join_length`,
but the setting layer supplies `max_length` because the culture never set
it.

**The official language, on top of all three** (seed 5):

```
$ python3 -m bunnyforge.generate_names takshashri --place -n 3 --seed 5
  Peukdava         official: Nisabegi
  Peukash          official: Nisaompy
  Swatdava         official: Nisayave

$ python3 -m bunnyforge.generate_names frashovant --place -n 3 --seed 5
  Haom Nair        official: Daraompy
  Fras Anav        official: Daraompy
  Fras Nair        official: Daraompy

$ python3 -m bunnyforge.generate_names khotanreza --place -n 3 --seed 5
  Suraasta         official: Nisabegi
  Gyazivar         official: Nisaompy
  Nandasta         official: Nisayave

$ python3 -m bunnyforge.generate_names nisayavesh --place -n 3 --seed 5
  Nisabegi
  Daraphon
  Nisaesif
```

`frashovant`'s two-word place names (`Haom Nair`, `Fras Anav`) are its
`place_split = 0.4` in action, the same knob sample 3 isolates, holding
alongside everything else.

`takshashri`, `frashovant`, and `khotanreza` each print an `official:`
column carrying a `nisayavesh`-style name; `nisayavesh`'s own settlements
print no such column — the same rule sample 7 demonstrates, now holding
alongside three other axes at once.

## Copy-and-go — the merge, step by step

```
cp cultures/*.toml <your-campaign>/names/cultures/
```

Then merge `campaign-additions.toml`'s content into your campaign's
`campaign.toml`:

```toml
official_culture = "nisayavesh"      # under your existing [names] table
```

```toml
[names.spelling]                     # a NEW table -- append this at the
max_length = 8                       # end of your campaign.toml
```

As in sample 7: do not paste a second `[names]` header into a
`campaign.toml` that already has one — add the bare key under the table
that's already there. `[names.spelling]`, by contrast, is a table your
`campaign.toml` most likely does not already declare, so it is safe to
append as its own new header.

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
merging both lines of `campaign-additions.toml` into `campaign.toml` — is
the supported flow, and it works today.
