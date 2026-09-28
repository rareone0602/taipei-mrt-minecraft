# CLAUDE.md

A 1:1 rebuild of the Taipei Metro in Minecraft. The background, data sources and
design decisions are in `README.md` and `docs/`, which are the project's source
of truth. This file covers only the rules for working here.

## Style

The project follows phy's style guide:
[STYLE.md](https://github.com/rareone0602/phy_friends/blob/main/STYLE.md)
([raw](https://raw.githubusercontent.com/rareone0602/phy_friends/main/STYLE.md)).
Where this file and the guide disagree, the guide wins. In practice:

- **Code is American English** (§10): identifiers, comments, docstrings,
  generated `.mcfunction` comments and commit messages. Comments are formal,
  full sentences that say why. A commit's subject is imperative, in sentence
  case and about 50 characters, with the why in the body.
- **Prose is British English, as The Economist writes it** (§3): `README.md`,
  `docs/`, `LICENSE-DATA`, and everything the code prints for people (progress
  logs, reports, argparse help, error messages). Sentence case, the exact word
  in a short sentence, numbers rather than adjectives, no exclamation marks, no
  emoji, no hype.
- **Text inside the game is bilingual**, Chinese and English, as on the Taipei
  Metro's own signs, which are what is being rebuilt. Never drop the Chinese.
  The English half uses the Metro's own terms (Exit, Transfer, Terminus) and is
  otherwise British English.
- **Chinese stays where it is data**: station and line names, OSM tags, strings
  the code matches against data, and test fixtures.
- **Show, then ship** (§11): discuss anything big first, and let phy review
  before anything is pushed or published. Pushing is phy's call, each time.

## Hard rules

- **Python is always `./.venv/bin/python`**, never the system Python. Install
  packages with `./.venv/bin/pip`. The venv is 3.9.6, so no 3.10+ syntax such as
  `X | Y` in type hints.
- **Leave `out/` alone.** It holds the existing 1 GB world save, and rebuilding
  it with `build_world` takes over 20 minutes. To test, point `--out` at a
  temporary directory.
- Temporary files go in the scratchpad, never in the project directory.
- **`demo/` holds finished files only**, plus `demo/fonts/`: Shantell Sans,
  the face every caption and page is set in, copied with its licence from the
  style guide's kit. The raw screen recordings (`demo/raw-*.mov`; the demo is
  cut from `raw-4.mov` alone) and the intermediates in `demo/.work/` are in
  `.gitignore`.
  Every cut, caption and still is timed in `demo/make_demo.py`. To change the
  demo, change that script and rerun it (`./.venv/bin/python demo/make_demo.py`);
  never edit a finished file by hand.
- No HTTP request may carry personal data (names, email addresses). The Overpass
  User-Agent gives only the project name (`infrastructure/overpass.USER_AGENT`;
  overpass-api.de answers curl's default User-Agent with a 406).

## Architecture

Clean Architecture. **Dependencies point inwards only; an inner layer never
imports an outer one:**

```
mrt/
  config.py         Project paths and the world's vertical range. Any layer may
                    import it.
  domain/           Pure rules, no I/O: alignment, track geometry, building
                    geometry, tunnel depth bands, elevation sampling, underground
                    mall routes (concourse), placing real exits and transfer
                    passages and keeping them clear (exits), stacked stations and
                    pocket tracks (stacked), walkability (walk), and the ride
                    network and boarding positions (network).
  ports/            Interfaces the inner layers expose to the outer ones:
                    BlockSink (block by block), ChunkSink (whole sections),
                    SignSink (signs: text components, glow, click commands,
                    dialogs).
  application/      Use cases that write what domain computes into a BlockSink:
                    station signs (signage), the datapack spec (ride_plan), the
                    spawn point (spawn), and the attractions (attractions/).
  adapters/         External data coming in: OSM (osm/), DEM (dem/), projection
                    (projection.py).
  infrastructure/   External technical detail: Anvil save writing (mcworld),
                    reading back (savereader), Overpass HTTP (overpass),
                    heightmaps (heightmap), and the datapack (datapack, including
                    the dimension_type that raises the overworld).

cli/                The composition root, and the only place that sees every
                    implementation and decides which World the blocks go into.
                    `cli.build_world.plan_segments()` plans without building, so
                    tools and scratch scripts get exactly the segments the
                    generator uses.
tools/              Verification and inspection: they read the save back on
                    their own and don't trust the generator's account of itself.
tests/              Tests that run without generating a world.
```

What each layer may import is defined by `ALLOWED` in
`tests/test_architecture.py`:

| layer | may import |
|---|---|
| `ports` | the standard library only |
| `domain` | `domain`, `ports` |
| `application` | `domain`, `ports`, `application` |
| `infrastructure` | `ports`, `infrastructure` |
| `adapters` | `domain`, `ports`, `infrastructure`, `adapters` |

**After any change, run `./.venv/bin/python tests/run_all.py`.** Directory names
stop nobody. What keeps the layers honest is `test_architecture.py`, which parses
every module's imports and names the offenders.

### Why it is cut this way

- The generator always took the world as an argument (`def build_station(w, ...)`)
  and only ever called `w.set()`. The interface already existed;
  `ports/block_sink.py` merely states it. So a test can pass in a `DictSink`
  instead of producing a save.
- The alignment maths (`domain/alignment.py`) and the cross-section masonry
  (`application/build_line.py`) change for different reasons: what a section
  looks like is an artistic decision, whether the alignment is right is an
  engineering one.
- `domain/tunnel_layers.py` once did `import build_world` (and never used it).
  That cycle is gone.

A naming wart: `domain/concourse.py` and `application/build_concourse.py` model
the underground malls (地下街), not the station concourse (穿堂). The prose and
comments say "underground mall"; the module names are older.

## Common commands

```bash
# Data pipeline (in order)
./.venv/bin/python -m mrt.adapters.osm.fetch_network      # OSM line geometry
./.venv/bin/python -m mrt.adapters.osm.fetch_stations     # station nodes
./.venv/bin/python -m mrt.adapters.osm.fetch_way_tags     # way tags
./.venv/bin/python -m mrt.adapters.osm.fetch_branch       # branches with non-standard refs
./.venv/bin/python -m mrt.adapters.osm.fetch_details      # exits, station buildings, platform levels
./.venv/bin/python -m mrt.adapters.osm.fetch_indoor       # underground walkways (underground malls)
./.venv/bin/python -m mrt.adapters.osm.fetch_sidings      # pocket tracks, crossovers, depot leads
./.venv/bin/python -m mrt.adapters.osm.fetch_attractions  # attraction building outlines (Taipei 101 etc.)
./.venv/bin/python -m mrt.adapters.projection             # project into MC coordinates
./.venv/bin/python -m mrt.adapters.dem.make_heightmap     # DEM -> elevation grid

# Generation
./.venv/bin/python -m cli.build_world                     # whole network + terrain
./.venv/bin/python -m cli.build_world --rails             # and lay track
./.venv/bin/python -m cli.build_line --lines BR           # a few lines only (fast, no terrain)
./.venv/bin/python -m cli.build_world --out /tmp/w \
    --bbox -900 -1400 400 250                             # just around Taipei Main Station (tens of seconds)
./.venv/bin/python -m cli.build_world --out /tmp/w --bbox ... \
    --sights taipei101                                    # only some attractions (--no-sights for none)

# Tests and verification
./.venv/bin/python tests/run_all.py                       # all unit tests
./.venv/bin/python tools/verify_render.py <save> out.png  # read back and render a top-down map
./.venv/bin/python tools/verify_rails.py [save]           # read back and check track connectivity
./.venv/bin/python tools/verify_exits.py <save>           # read back every exit and walk from street to platform
./.venv/bin/python tools/verify_concourse.py <save> --stations 台北車站 北門 中山 雙連
./.venv/bin/python tools/verify_exits.py <save> \
    --levels 府中 西門 中正紀念堂 古亭 東門                 # stacked stations must reach both platform levels
./.venv/bin/python tools/verify_tracks.py <save> --station 西門 --expect 4 --levels 2
./.venv/bin/python tools/verify_tracks.py <save> --pocket 大安 信義安和 --expect 3
                                                          # read back how many tracks each cut has, and at what height
./.venv/bin/python tools/verify_spawn.py <save> [--all]   # read back the spawn point and heightmaps; find spawn as the game does
./.venv/bin/python tools/verify_rides.py <save>           # read back every ride sign and its datapack destination
./.venv/bin/python tools/check_datapack.py <save>         # load and run the datapack in the real 26.2 (headless GameTest server)
./.venv/bin/python tools/slice_world.py 忠孝復興          # ASCII cross-section
./.venv/bin/python tools/verify_attractions.py <save>     # read back each attraction's height, outline, viewpoint and plaque
./.venv/bin/python tools/render_view.py <save> --bbox X0 Z0 X1 Z1 --out prefix \
    --views south,east,iso,top                            # elevations, isometric and top-down views (colours from the game's textures)
```

Station names on the command line are in Chinese because they match the data.

There are two walking rules; don't mix them up. `verify_concourse` checks that a
walk **never surfaces** (feet at least two blocks below the local ground, checked
block by block against the terrain). `verify_exits` checks that it **never treads
on soil** (only man-made blocks underfoot). The second is stricter, and the
first cannot check an exit kiosk, which stands on the ground by design. At a
transfer station `verify_exits` also requires every exit to be in one connected
component, which is how it knows the transfer passages work.

**The concourse height has one definition**: `alignment.station_kind` /
`LEVEL_DY` (+7 underground, −6 under the viaduct, +8 above the platform). The
station builder, the exit shafts, the transfer passages and the verifiers all
take it from there. Don't compute it anywhere else: one block out and a whole
station can't be walked. Stacked stations (`domain/stacked.py`: Fuzhong, Ximen,
Chiang Kai-shek Memorial Hall, Guting, Dongmen) keep to the same rule: the upper
level is the ordinary island station, the lower level is a copy `LEVEL_H` blocks
below it, and the concourse stays at +7. The level spacing changes only through
`LEVEL_H`.

**Two lines sharing a station box are allies in `assign_bands`** (`shared=`), and
after planning, always read the `check_clearance` line: bands without a conflict
do not mean box structures without an overlap. Ximen's pinning once scared the
Bannan line into band 2, and at Taipei Main Station it drove straight into the
Tamsui-Xinyi line's station box; the band check never noticed. **The ally radius
(`stacked.ALLY_M`) must hug the length of what really is one structure** (half a
station box plus `SPLIT_M`, about 350 m). It was once 500 m, and south of Guting
the Songshan-Xindian and Zhonghe-Xinlu lines, which run side by side for 500 m
with centre lines 7 to 13 m apart, were judged not to need separate depths. Their
box structures overlapped at the same depth for 400 m.

**Tools pick alignment geometry through `alignment.select_variants`, always.**
OSM often has two relations for one line, one per direction, and near Daan the
Tamsui-Xinyi pair are 19 m apart. A tool that picks the nearest one for itself
picks the one the generator didn't build, and reports a problem that doesn't
exist.

**Boarding positions have one definition**: `network.plan_berths` (computed once
by `cli.build_world`). The ride signs on the platforms (`signage`) and the
datapack's teleport destinations (`ride_plan`) consume the same `berths`.
Function ids come only from `network.ride_fn / turn_fn / go_fn / MENU_DIALOG`,
and the namespace only from `config.DATAPACK_NS`: the command on a sign and the
file name in the datapack are two ends of one agreement. Every ride, turn and go
function is exactly one line, `tp @s x y z yaw pitch`, which is how
`verify_rides` reads it back.

**Two traps with signs.** `verify_exits` recognises an exit kiosk by a first line
that starts with `出口` and a second line that is the station name, so no other
sign's first line may start with `出口`. Yellow concrete is the platform's
warning strip (both verifiers use it to find platforms), so no line-colour band
may use it. Click actions go on the first line only: the game runs every line's
click_event once.

**The world is 704 blocks tall (y−64..639), not vanilla's 384.** Taipei 101's
spire is at about y580. The height is defined once, in `config.Y_MIN / Y_MAX`:
the section count per chunk, the heightmap's bit width (10 bits, 43 longs), the
datapack's `dimension_type/overworld.json` and the readers all take it from
there, so never hard-code 319 or 384 again. If the datapack isn't loaded, the
game reads the world at vanilla height and everything above y319 vanishes;
`check_datapack` places a block at y639 in the game to check exactly that. The
terrain is still capped below 312 by `terrain.Y_CAP`.

**Attractions (`application/attractions/`) are one module each, registered with
`BUILDS = {id: class}`.** The package scans itself, so a new attraction needs no
change to shared files. Position, orientation and outline come from
`data/attractions.json` (OSM); the look is a parametric program written from
public architectural facts. **Copy no text, image or 3D model.** Attractions are
built after the stations, exits and underground malls, and every write goes
through `Guard`: the keep-out zone from `cli.build_world.sight_keepout` (exit
shafts, the underground malls' actual blocks, line cross-sections) is never
written. An attraction's ground level is looked up in `plan()`, and `build()` is
called once per region. After changing an attraction, run `verify_attractions`
(heights against published figures, outline, whether the viewpoint can be stood
on); if there are exits nearby, run `verify_exits` as well and compare with
`--no-sights`. An attraction's teleport function `sight/<id>` follows the same
agreement as ride/turn/go (exactly one tp line), and its path comes only from
`kit.sight_fn`. Plaques and the concourse attraction signs, too, may not start
their first line with `出口`.

**The game itself can be a verifier.** The installed 26.2 client jar ships a
headless GameTest server (`net.minecraft.gametest.Main`, run with the launcher's
bundled Java) that runs inside the sandbox; an ordinary server needs to open a
port and can't. `check_datapack` uses it to load the datapack, run every teleport
function and read back where it lands. `heightmap.py`'s packing and block
classification were checked bit for bit against chunks it saved (signs, banners
and pressure plates count as blocking in the heightmap, against intuition). It
has no player: right-clicking a sign and dialog screens can only be checked in
the game. For formats, don't trust memory: `net.minecraft.data.Main --reports`
dumps the full command tree and registries.

## Licences

The code is GPL-3.0 (`LICENSE`); `data/` is ODbL 1.0 (`LICENSE-DATA`, inherited
from OpenStreetMap). Both are copyleft. When adding a data file to `data/`,
check the source's terms and update the file list in `LICENSE-DATA`, which names
every file individually rather than using a wildcard.

## How to verify

**Don't trust the generator's account of itself; read everything back from disk
independently.** Every tool in `tools/` exists because of this rule, and
docs/verification.md lists what each one has caught.

`verify_render.py` has a trap: the terminal lists only the 20 commonest blocks,
so a new material may never show up there. Scan the image for magenta pixels
instead. Magenta is darkened by the height shading, so the test is `g=0 and r=b`,
not `r>200`. Blocks outside the hand-picked palette are coloured from the game's
textures (`tools/blockcolors.py` reads the installed jar); magenta means even the
texture couldn't produce a colour, which usually means a mistyped block id.

**Verifiers lie too.** Three real cases. Defining "underground" as one global
y ceiling: add two stations with ground 3 m lower and the whole underground mall
was judged to be on the surface, with sixty exits each in its own component. A
verifier keyed on exit numbers: Ximen station's exit 1 and the Ximen underground
mall's exit 1 overwrote each other, and the broken half never appeared in the
report. Reading heights back only up to 6 m above the exit sign: elevated
platforms sit 14 m up, so every elevated station was judged unable to reach its
platform. When a result looks absurd, suspect the verifier first.

**Passing unit tests does not mean the build can be walked.** The tests use
straight lines. On a real alignment at 45 degrees, two adjacent steps of a
two-wide stair touch only at a corner, and the stair breaks halfway. Only
building a small area with `--bbox` and walking it with `verify_exits` shows
that. After changing station or stair geometry, build at least one diagonal
station (Liuzhangli, Tamsui) and check it before going further.

**In `ShaftStair`, `g0` is a floor and `y_to` a standing surface, and both doors
are in the same wall.** The bottom door's top is clamped below the landing at the
top of the shaft, so when the standing surfaces differ by less than 3 blocks the
doorway becomes too low to pass (that is how Tamkang University broke). Exits
where the street and the concourse differ by 0 to 2 m use `exits.place_gate`
(at-grade exits); don't set `MIN_RISE` back to 2.

**Shafts and passages must avoid other lines, not just what is in their own
area.** The underground mall's link-stair shafts dig from y61 down to the deepest
line's concourse, and on the way they must pass the depths of the shallower
lines. At Taipei Main Station the shaft down to the Tamsui-Xinyi line once dug
more than ten metres out of the Bannan line's platform, and the old save in
`out/` still shows it. `build_concourse.plan` now takes the occupancy table from
`exits.index_segments`; anything new that crosses depths vertically must check
it.

**After changing the generator, compare against a save from the old version.**
`git worktree add <temp dir> HEAD` plus a symlink to `data/heightmap.npy` builds
the same area with the old code; then diff block by block
(`savereader.read_volume` on each side). That is how a shared trunk that hollowed
out twelve stations, and stair tops one block off, were told apart from the
differences that were meant.
