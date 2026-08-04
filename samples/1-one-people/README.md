# Sample 1 — one people

**Isolates:** the floor. One culture (`vashkand.toml`), one category
(`categories = ["personal"]`), and none of the optional keys (`[spelling]`,
`join`, `place_split`, `given_syllables`). This is also what a brand-new
campaign gets from `init` — a single naming scheme shared by everyone in the
setting, regardless of species.

A single category also shows something easy to miss: `categories` need be
neither plural nor gendered. Omitting `--gender` concatenates all of a
culture's categories, which here is just the one.

## Copy-and-go

```
cp cultures/*.toml <your-campaign>/names/cultures/
```

**Precondition:** this only works if the target campaign's `campaign.toml`
either omits `[names].official_culture` or sets it to a culture this sample
supplies (`vashkand`). If it names anything else, the loader fails at import:

```
InventoryError: [names].official_culture in campaign.toml names no culture:
  'harrowmoor'. Available: vashkand
```

That is the loader's validation working correctly, not a bug in the sample.
If the campaign you are copying into already sets `official_culture` to one
of its own cultures, clear or repoint that key first — this sample supplies
only `vashkand`, so any other value fails as above.

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
