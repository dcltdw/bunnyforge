# Campaign tests

`bunnyforge review checkup` checks the *mechanics* of your workspace —
front matter, links, visibility, whether every entity is indexed. It
cannot know what is true in **your** setting. Campaign tests are where you
write that down, so it gets checked every time instead of only when you
happen to reread the file.

Things worth asserting:

- every NPC's faction actually exists as a file
- no session file refers to a session that comes after it
- every `reveal_when:` trigger names something in `front-burner.md`
- every place in a region file has its own `Setting/` entry

Each one you record here is a continuity error you never have to catch by
rereading.

## How to start

1. Open `test_example.py` in this folder. It is a complete, working test —
   switched off, with every line commented out.
2. Delete the leading `# ` from each line below its instructions header.
3. Run `bunnyforge test`. It passes even before you have written any NPCs:
   it checks whatever exists, so turning it on is always safe.
4. When an invariant of your own setting occurs to you — *"every place
   file names its region"* — copy the example's shape into a new file
   called `test_something.py` and adapt it.

Files must be named `test_*.py` to be found. Everything else in this
folder is ignored, so notes and helpers can live here too.

## Running them

    bunnyforge test          # from anywhere inside your campaign
    bunnyforge test -v       # naming each test as it runs

`bunnyforge test` also checks that no test wrote into your campaign while
running. Tests should only ever read your files, or write into a temporary
directory — a test that edits real campaign content will fail the run and
tell you which file it touched.

A guided setup wizard is planned. Until then, the example is the guide.
