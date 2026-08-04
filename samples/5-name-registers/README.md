# Sample 5 — categories that are not genders

**Isolates:** the honest mechanism behind `categories`. This sample follows
sample 4 deliberately — readers arrive asking how to do genders, and should
get that answered before being shown that `categories` was never about
gender at all.

One culture, `natakabal.toml`, whose `categories` are registers of personal
name rather than genders: **public**, **kin**, **initiate**. One person
holds a name used in public life, a different name used only among kin, and
a third name taken at initiation.

```toml
categories      = ["public", "kin", "initiate"]
given_public    = [...]
given_kin       = [...]
given_initiate  = [...]
```

`species` is empty, for the same reason as every other sample: a culture
here is a place, not a people. `draws_on = "Meroitic"`, the language of the
Kingdom of Kush, written in its own script that remains only partially
deciphered — a tradition no earlier sample in this ladder uses.

## Be honest about the mechanism

`categories` selects which pool the **given** name is drawn from — that is
all it has ever done, in every sample in this ladder including this one. A
person here does not carry "public name + kin name + initiate name"
simultaneously as separate components the way a `family` name and a `given`
name are separate components of a full name. They carry **one** given name
at a time, chosen from whichever register applies, exactly the way `--gender
f` chooses one given name from the `f` pool rather than adding a component
to it. If you expected `full name = clan + given + epithet` — several name
components held at once — that is a different feature this tool doesn't
have; `categories` only ever changes which pool a single given name comes
from.

## What to expect

```
$ python3 -m bunnyforge.generate_names natakabal --gender public -n 4 --seed 1
  Amanishe Nataarik
  Natakama Teri
  Teriteq Amannata
  Teriteq Teri

$ python3 -m bunnyforge.generate_names natakabal --gender kin -n 4 --seed 1
  Amanishe Kdaktama
  Natakama Resh
  Teriteq Nekhkdak
  Teriteq Resh

$ python3 -m bunnyforge.generate_names natakabal --gender initiate -n 4 --seed 1
  Amanishe Qashhabl
  Natakama Yerq
  Teriteq Nterqash
  Teriteq Yerq
```

Same family name, three different given-name registers — `--gender` is
still the flag that selects one, whatever you call the categories it's
choosing between.

## Copy-and-go

```
cp cultures/*.toml <your-campaign>/names/cultures/
```

Same precondition as the earlier samples: `campaign.toml`'s
`[names].official_culture`, if set, must name `natakabal` (or be omitted) —
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
