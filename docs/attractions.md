# Attractions

Fourteen landmarks built 1:1 where they stand, with their outlines taken from OpenStreetMap and their looks from published architectural facts.

![Taipei 101 from its viewpoint, with the shopping mall and a skybridge at its foot](../demo/taipei101.jpg)

Taipei 101 from the viewpoint its teleport lands on.

Walk out of Taipei Main Station and the Shin Kong Life Tower is in view. To the south lie the North Gate, the National Taiwan Museum and the Presidential Office Building, and beyond them the Chiang Kai-shek Memorial Hall. Ride out to Taipei City Hall and Taipei 101 rises 508 m from the ground to the tip of its spire. All 14 stand where they really are.

| Attraction | Nearest station | Height | What is built |
|---|---|---:|---|
| Shin Kong Life Tower | Taipei Main Station, 241 m | 244 m | Thirty-odd `building:part`s from OSM stacked into a 16-storey department-store podium and a 50-storey tower, with setbacks at the 44th, 46th and 48th floors and a spire; a tall lobby facing the station |
| North Gate (Beimen) | Beimen, 206 m | 15 m | As it was under the Qing: an andesite base and gateway, a red-brick gate tower built like a blockhouse, and a single-eave hip-and-gable roof |
| National Taiwan Museum | NTU Hospital, 171 m | 30 m | A portico of six Doric columns with a pediment, and a dome; you can walk into the domed hall (32 columns, a stained-glass skylight) |
| Presidential Office Building | Ximen, 454 m | 60 m | A rectangle split by a central wing into two courtyards, red brick with white bands, a 60 m central tower (square below, octagonal above) and a porte-cochère |
| Red House | Ximen, 223 m | 28 m | The red-brick octagon (412 m²) with its octagonal pyramid roof and lantern, and the cruciform hall behind it |
| East Gate, South Gate and Little South Gate | NTU Hospital, Chiang Kai-shek Memorial Hall and Xiaonanmen, about 300 m each | 15–16 m | As rebuilt in 1966 in the northern palace style: stone bases, red columns, green glazed tiles, yellow ridges and ridge-end ornaments |
| Chiang Kai-shek Memorial Hall | Chiang Kai-shek Memorial Hall, 303 m | 70 m | The blue octagonal double-eave roof, three tiers of white base, the great front stair and the statue hall; Liberty Square's arch (five gateways, 30 m), the National Theater (double-eave hip roof), the National Concert Hall (double-eave hip-and-gable), the square and its cloister walls |
| Taipei 101 | Taipei 101/World Trade Center, 233 m | 508 m | The tapering base up to the 26th floor with its coin motifs, floors 27–90 as eight flared segments of eight floors each with ruyi ornaments, the top and spire, and the shopping mall; the ground-floor lobby, the 89th-floor observatory (with its 5.5 m golden damper sphere) and the outdoor deck on the 91st |
| Sun Yat-sen Memorial Hall | Sun Yat-sen Memorial Hall, 328 m | 31 m | The upswept yellow roof, the entrance portico, a colonnade of grey pillars and the statue in the main hall |
| Longshan Temple | Longshan Temple, 223 m | 18 m | Three halls in sequence: the front hall, the main hall with a double-eave hip-and-gable roof, and the rear hall; swallowtail ridges, cast-bronze dragon columns, bell and drum towers, and the courtyard pool with its waterfall wall |
| The Grand Hotel | Jiantan, 632 m | 87 m | Fourteen storeys halfway up Jiantan Mountain: red columns and golden tiles, a double-eave hip-and-gable roof, a portico and two flights of steps down to the fountain plaza, and the rear block climbing the slope |
| Miramar Ferris Wheel | Jiannan Road, 308 m | 100 m | A 70 m wheel with 48 cabins on the roof of a 30 m shopping centre |

## How they are built

**Position, orientation and outline come from OSM** (`mrt/adapters/osm/fetch_attractions.py` writes `data/attractions.json`, under the ODbL). For each attraction the fetcher takes every `building`, `building:part` and `historic` within a radius. Taipei 101's `building:part`s put the 89th floor at 386 m and the spire at 448–508 m; the Presidential Office's central tower is tagged at 60 m, with its colour.

**The looks are parametric code written from published architectural facts**: heights, storeys, bays, roof types and colours. The sources are in each module's comments: Wikipedia, the websites of the Presidential Office and the National Taiwan Museum, the Bureau of Cultural Heritage, the National Cultural Memory Bank and others. **No text, image or 3D model is copied.** Each attraction has its own module in `mrt/application/attractions/`, and the shared parts are in `kit.py`:

| Part | What it does |
|---|---|
| `Frame` | The building's own coordinate frame. Most OSM outlines are not square to north (the Chiang Kai-shek Memorial Hall's axis is 28° off, the Red House's 15°), so a building is drawn in local coordinates and every **world block** is mapped back and tested. No block is missed at any angle. |
| Roof height fields | Hip, hip-and-gable, pyramid (square, octagonal and round) and gable. The concave curve of a Chinese roof and the upturn at its eave corners are parameters. |
| `Site` | Finds the ground as built, sets the ground-floor slab, and levels the site, filling what is low and cutting what is high. |
| `Guard` | **The keep-out guard.** Attractions are built after the stations, exits and underground malls, so every write first passes a table of keep-out zones (`cli.build_world.sight_keepout`: exit shafts with a margin of 2 blocks, the underground malls' actual floors and outer walls, and line cross-sections). The Shin Kong Life Tower's base sits right on top of the Station Front Metro Mall; without the guard it would seal exits. |

Around every attraction, the nearby exits were compared with the same area built without attractions (`--no-sights`), and `verify_exits` reports exactly the same.

## A taller world

**The world is 704 blocks high, from y−64 to y639.** Vanilla stops at y319, 250 m above the floor of the basin, which would not get Taipei 101 halfway up. The datapack replaces the dimension type of `minecraft:overworld` with one 704 blocks high (`infrastructure/datapack.py`; every other field is vanilla's, word for word). Chunks, heightmaps (10 bits, 43 longs) and the read-back tools all take the height from `config.Y_MAX`. The clouds moved up from y192 to y600 as well; otherwise the view down from the 89th-floor observatory (y≈450) is a solid sheet of cloud, which is faithful to a Taipei winter but not what anyone buys a ticket for. The game really can hold a block at y639: `check_datapack` places one in the game, and without the dimension type the check fails. The terrain is still compressed below y312 as before; the extra height is for buildings only.

## Getting there

The datapack's `mrt:sight/<id>` teleports you to a viewpoint in front of each attraction, on the same convention as the ride and go functions: exactly one `tp` line. The route map's main menu has a `★ 觀光景點 Attractions` button that opens `mrt:sights`. The concourses of stations within walking distance have a sign for each attraction nearby, and in each line's station list the hover text on a station names them. A plaque stands beside each viewpoint, with the attraction's name and nearest station on the front and two facts on the back. Taipei 101's lobby and 89th floor are joined by "lift" signs (`sight/taipei101_top` and `_lobby`).

![The attractions menu: fourteen buttons, with a tooltip giving the National Taiwan Museum's opening year and nearest station](../demo/sights-menu.jpg)

The attractions menu, the last button on the route map. Each tooltip gives the year the building opened and its nearest station.

## Verification

`tools/verify_attractions.py` reads each attraction back from disk and compares its height with **public figures the tool carries itself**, not with what the generator says. It also checks the outline coverage, whether anything is built outside the outline, whether each teleport point can be stood on, whether each viewpoint faces its building, and the plaques. The Grand Hotel stands on a hillside, so its ground is measured from its own site; the ring around it is the riverside flat below. Read back from the whole-network save, all 14 pass (public figures on the right):

| Attraction | Top | Ground | Height | Public figure |
|---|---:|---:|---:|---:|
| Taipei 101 | y579 | y71 | 508 m | 508 m |
| Shin Kong Life Tower | y310 | y66 | 244 m | 244.15 m |
| The Grand Hotel | y184 | y97 | 87 m | 87 m |
| Chiang Kai-shek Memorial Hall | y138 | y68 | 70 m | 70 m |
| Miramar Ferris Wheel | y169 | y68 | 101 m | 100 m |
| Presidential Office Building | y127 | y67 | 60 m | 60 m |
| Sun Yat-sen Memorial Hall | y101 | y70 | 31 m | 30.4 m |
| National Taiwan Museum | y97 | y67 | 30 m | about 30 m |

The other checks on the same save are unchanged. All 472 exits reach both a platform and the street, so the attractions blocked none of them; the 1,158 ride signs have no faults; all 606 teleport functions in the game (23 of them for attractions) and all 207 buttons land where they should; and the top-down render has no magenta. A full build takes about 12 minutes and comes to 1.27 GB. How each tool works is in [verification](verification.md).

`tools/render_view.py` draws elevations, plans and isometric views of any area, with colours computed from the installed game's textures (`tools/blockcolors.py`). Every round of work on the attractions used it to compare proportion and outline with the real buildings.

What the attractions still lack is in [limitations](limitations.md#attractions).
