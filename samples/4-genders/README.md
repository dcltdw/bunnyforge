# Sample 4 — genders

**Isolates:** `categories` holding something other than `["m", "f"]` (or
`["m", "f", "n"]`) — the feature that removed the CLI's old hardcoded
`choices=["m","f","n"]` has had no worked example anywhere in this project
until now. Every earlier sample in this ladder uses
`categories = ["personal"]` or `["m", "f"]`.

One culture, `shaqirreth.toml`, recognising **four** genders: **Nexus**,
**Steward**, **Wildheart**, **Shaper**.

```toml
categories      = ["nexus", "steward", "wildheart", "shaper"]
given_nexus     = [...]
given_steward   = [...]
given_wildheart = [...]
given_shaper    = [...]
```

`species` is empty, for the same reason as every other sample: a culture
here is a place, not a people, and this tool ships no species-to-tradition
mappings. `draws_on = "Nabataean"`, the language of the Petra-based Arabian
trading kingdom, attested mainly through inscriptions — a tradition no
earlier sample in this ladder uses.

## Lowercase keys, capitalised prose

Category matching is case-sensitive: `--gender Nexus` against the lowercase
key `nexus` fails, and `--gender nexus` against a capitalised key `Nexus`
would equally fail. That asymmetry is real and this project isn't fixing it
here (it's a production behaviour change; see the design doc's Out of
Scope). This sample routes around it: the TOML keys are lowercase
(`nexus`, `steward`, `wildheart`, `shaper`) so `--gender nexus` works exactly
as a player would type it. This README and the file's own comments write
the names capitalised — Nexus, Steward, Wildheart, Shaper — because that's
how they'd read in prose or on a character sheet. Shipping capitalised keys
would force `--gender Wildheart` on every invocation, and a sample that
ships friction teaches friction.

## What to expect

```
$ python3 -m bunnyforge.generate_names shaqirreth --gender nexus -n 4 --seed 1
  Obodas Shaqdush
  Aretas Qir
  Malichos Rebshaq
  Malichos Qir

$ python3 -m bunnyforge.generate_names shaqirreth --gender steward -n 4 --seed 1
  Obodas Obodkem
  Aretas Rasu
  Malichos Hadrobod
  Malichos Rasu
```

Each `--gender` draws only from its own pool — `nexus` never produces a
`steward` syllable and vice versa — exactly as `--gender f` does for a
two-category culture, just with four pools instead of two.

Naming a category that doesn't exist fails loudly rather than guessing:

```
$ python3 -m bunnyforge.generate_names shaqirreth --gender Nexus -n 1 --seed 1
error: culture 'shaqirreth' has no category 'Nexus'. It defines: nexus, steward, wildheart, shaper
```

## Copy-and-go

```
cp cultures/*.toml <your-campaign>/names/cultures/
```

Same precondition as the earlier samples: `campaign.toml`'s
`[names].official_culture`, if set, must name `shaqirreth` (or be omitted) —
otherwise the loader fails at import with `InventoryError`.

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
