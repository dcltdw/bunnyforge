# Sample 2 — many peoples

**Isolates:** several cultures in one setting; alias lookup via `draws_on`;
species decoupled from culture.

Three invented places — `vagharzan.toml`, `bilgekaya.toml`,
`birhankidus.toml` — each drawing on a different real, attested, historical
tradition: **Sogdian** (Central Asia), **Old Turkic** (the steppe), and
**Ge'ez** (the Horn of Africa). No two overlap, and none is used by any
other sample in this ladder.

## The decoupling lesson

Every culture in this project ships `species = ""`. That is not a gap to be
filled in — it is the point. A culture here is a **place**, not a people:
several species can live in Vagharzan, Bilgekaya, or Birhankidus, and every
one of them, whatever their species, has a name from that place. This tool
ships no species-to-real-world-tradition mappings; deciding which fantasy
species draws on which human tradition (if any) is a setting-authorship
choice this tool takes no position on.

Because species and culture are decoupled, lookup happens by **tradition**,
not by species:

```
python3 -m bunnyforge.generate_names sogdian -n 5
python3 -m bunnyforge.generate_names oldturkic -n 5
python3 -m bunnyforge.generate_names "ge'ez" -n 5
```

Each of these resolves through `draws_on`, exactly as the culture's own key
(`vagharzan`, `bilgekaya`, `birhankidus`) would. There is no `--species` flag
and no species argument anywhere in the CLI — species is not a naming axis
at all.

Each culture's inventory is deliberately distinct — Sogdian's consonant
clusters, Old Turkic's open vowels, Ge'ez's Semitic roots — so a reader can
tell one place's names from another's without being told which is which.

## Copy-and-go

```
cp cultures/*.toml <your-campaign>/names/cultures/
```

Same precondition as sample 1: `campaign.toml`'s `[names].official_culture`,
if set, must name one of `vagharzan`, `bilgekaya`, or `birhankidus` (or be
omitted) — otherwise the loader fails at import with `InventoryError`.

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
