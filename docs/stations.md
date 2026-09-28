# Stations

How the 193 stations are built, from the standard box to Taipei Main Station, how their 472 exits reach the street, and how the ride system moves you between them. The tools that check all of this are in [verification](verification.md).

## Station structure

An underground station is a two-level box: an island platform with a concourse above it, 25 m wide and 13 blocks high.

```
dy 10  ────────────  roof slab
dy 7~9              concourse (the fare gates are on this level)
dy  6  ────────────  concourse floor (openings down to the platform)
dy 2~5              platform headroom, platform screen doors
dy  1   ▓▓▓▓▓▓▓     island platform (13 m wide, a warning strip along each edge)
dy  0   ══     ══    track bed; rails at dy 1, offset ±8
dy -2  ────────────  base slab
```

Almost every underground station on the Taipei Metro has an island platform, for a good reason. With side platforms the tracks in the middle cut the concourse in two, and each platform needs its own stairs and fare gates.

A running tunnel is only 11 m wide, with the tracks 3 m either side of the centre line. So over the 40 m before a station the tracks splay out to ±8, and the tunnel's half-width grows from 5 to 10 in step (`track_offsets()`). Jump from one to the other and the rails break in two.

**Elevated and at-grade stations have side platforms.** Where their concourse goes depends on how far the rail top stands above the ground, and `alignment.station_kind` is the only place in the project that decides it. Under the viaduct (rail top 9 m or more above the ground; 81 elevated stations), the concourse sits directly below the platforms, with its floor at rail top − 6. The deck is its roof, the side walls are glass, and the viaduct's piers pass through the hall as columns, which is how the elevated stations of the Wenhu Line and the old Tamsui line are built. Above the platforms (at-grade stations and low elevated ones; 19 in all), the concourse is a footbridge across the two side platforms, with its floor at rail top + 8, resting on the roof of the station building, like the footbridge concourses of the old Tamsui line's at-grade stations.

The fare gates cross the concourse at `lo + 14 m`. Each platform has a stair two blocks wide down (or up) to the concourse, and both stairs are at the box's `hi` end. At the `lo` end they would dig in beside the opening for the exit passage, and under a viaduct the foot of the stair would land on the gate line. At `hi`, the platform walkways are not cut by stairwells, and the two platforms can reach each other for the first time: the second platform used to have no stair at all.

The old template stair, a straight 2:1 flight climbing the outside of the box to a station house on the street, is now built only where neither the real exits nor the default exit fit (see [real exits](#real-exits)).

## Stacked stations and pocket tracks

A friend looked over the Bannan Line and pointed out four things: Fuzhong does not have an island platform; Ximen should be one box with parallel, cross-platform interchange; there is a pocket track between Zhongxiao Fuxing and Zhongxiao Dunhua; and there should be another between Far Eastern Hospital and Haishan. All four were right, and the first two are the same structural problem. **At these stations a line's two tracks split onto two levels** (`mrt/domain/stacked.py`). The Taipei Metro has more than two such stations, and all five are now built.

| Station | Type | Upper level | Lower level |
|---|---|---|---|
| Fuzhong BL06 | stacked side platforms, five levels down | B3: towards Taipei Nangang Exhibition Center, doors open on the left | B5: towards Dingpu, doors on the right |
| Ximen BL11/G12 | stacked island, cross-platform interchange | B2: Bannan towards Taipei Nangang Exhibition Center, and Songshan-Xindian towards Songshan | B3: towards Dingpu, and towards Xindian |
| Chiang Kai-shek Memorial Hall R08/G10 | as Ximen | B2: Tamsui-Xinyi towards Tamsui, and Songshan-Xindian towards Songshan | B3: towards Guangci/Fengtian Temple, and towards Xindian |
| Guting G09/O05 | as Ximen | B2: Songshan-Xindian towards Songshan, and Zhonghe-Xinlu towards Luzhou/Huilong | B3: towards Xindian, and towards Nanshijiao |
| Dongmen R07/O06 | as Ximen, four levels down | B2: Zhonghe-Xinlu towards Huilong/Luzhou, and Tamsui-Xinyi towards Tamsui | B4: towards Nanshijiao, and towards Guangci/Fengtian Temple |

The side each train's doors open on comes from Wikipedia's platform tables, and is noted beside each entry in `stacked.STACKED`. **Dongmen is the one exception**, and deserves a note. At the other four stations, both tracks on a level run in the same direction (one line opens its doors on the left, the other on the right). At Dongmen a whole level opens on one side (B2 on the right, B4 on the left), which means the two tracks on each level run in opposite directions. Wikipedia itself singles it out as unlike the other stacked island stations, and gives the reason: the layout follows the main passenger flows, so that B2 handles both the Xiangshan to Huilong/Luzhou interchange and the Nanshijiao to Tamsui one on a single level. The model needs no special case for it. Which track stays on the upper level is decided by `upper_toward` alone (the neighbouring station the upper level's trains head for). At Dongmen the two lines' `upper_toward` point to opposite ends of the box, and the reversal falls out by itself.

The method: from 240 m outside the box, one track dives 8 m at 4%. Trains run on the right, so trains heading for the upper level's neighbour take the right-hand track, which stays up, and the other track dives. Over the last 40 m the two tracks close from ±3 to the same offset. The station box has two levels and is 21 blocks high. **The upper level is the ordinary island station (concourse still at rail top + 7), and the lower level is a complete copy of it 8 blocks further down**, so the exits, the interchange passages and every verifier work without a line changed. A 16 m stair leads from the upper platform to the lower one.

A shared box is built by one of its two lines (the primary), centred on the midline between them. Each level holds one of the line's own tracks, an island and one of the other line's tracks. Within the box the other line builds no cross-section and has no station of its own, and every exit hangs off the shared box. The two lines' rail tops are pinned to the same height (`stacked.pin_profile`), and either side of the pinned stretch they return to their own profiles at 4%. At the four shared stations the two centre lines are 17–22.5 m apart (Ximen 17.2, Chiang Kai-shek Memorial Hall 22.5, Guting 17.5, Dongmen 17.1). `plan_shared` accepts only 14–24 m. Outside that range it builds nothing, rather than quietly produce a box that spans an entire road.

The transition cannot be drawn as one box with two tracks, because the diving track's box slides from beside its neighbour to directly beneath it. `build_line.sec_multi` takes the union of each track's box at every point and lines only the outside of the union. The upper level is laid first, so the lower level's clearance never digs out the upper floor.

### Depth bands

**The depth bands were nearly wrecked by their own pins, twice, in opposite directions.** The first time the pins were too strict. Both lines at Ximen are pinned to the shallowest band, and in `assign_bands` the Songshan-Xindian pin read as "band 0 is taken by G around Ximen". The Bannan Line, looking ahead, saw it and dived to band 2 between Taipei Main Station and Ximen, only to be pulled back to band 0 by its own pin. Its profile dragged both Ximen and Taipei Main Station 13 m deeper, and at Taipei Main Station the Bannan Line ran straight into the Tamsui-Xinyi station box. The band check noticed nothing. The fix is that two lines sharing a box do not count as occupying each other near the station (`assign_bands(shared=…)`).

The second time the exemption was too generous. Its radius was 500 m. South of Guting the Songshan-Xindian and Zhonghe-Xinlu lines run side by side under Roosevelt Road for 500 m, their centre lines only 7–13 m apart. As allies they were judged to need no separate bands, and two boxes 14 m wide overlapped at the same depth for 400 m. The radius now matches the length that really is one structure: half a station box plus the transition, about 350 m (`stacked.ALLY_M`; the pin radius at stacked stations uses the same value).

After planning, always read the line that `tunnel_layers.check_clearance` prints. It works from the real geometry, the true extent of each box at every point (half-width, top and bottom), whereas the band check knows only that two band numbers differ. A two-level box 21 blocks high is taller than a band, and a pinned profile leaves its band's depth altogether. It now also reports by how many blocks two boxes overlap. The top two and bottom two rows of a box are lining and slab, and an overlap within that depth simply builds one shared wall. North of Ximen, where the Songshan-Xindian Line is about to dive to band 1 and the Bannan Line runs level 11 m beside it, there are three such overlaps of 1–2 blocks. A cross-section shows the two boxes biting into the same row of bricks: the Bannan base slab and the Songshan-Xindian roof slab make up for each other, each clearance is intact, and no air passes between them. Only an overlap deeper than that is a real intrusion into the other box.

### Pocket tracks

**Pocket tracks** are laid where OSM draws them (`data/sidings.json`, fetched by `fetch_sidings`). The running lines splay out to ±6, a third track runs down the middle, and the running lines close back to ±3. There are no turnouts (see [limitations](limitations.md#track)), so the third track ends before the running lines come within 4.5 m of it. There are seven in the network, all underground:

| Between | Line | OSM way | Source |
|---|---|---|---|
| Taipei Main Station–Zhongshan | R | 1226066660 | DORTS track engineering book, p. 406 |
| Daan–Xinyi Anhe | R | 685934617, named "Daan pocket track" | turnback for the Beitou–Daan short workings |
| Zhongxiao Fuxing–Zhongxiao Dunhua | BL | 877532286 | DORTS, as above |
| Far Eastern Hospital–Haishan | BL | 818792051, named "Far Eastern Hospital pocket track" | DORTS, as above, and a cab-ride video |
| Taipower Building–Gongguan | G | 818790283, named "Taipower Building–Gongguan pocket track" | DORTS, as above |
| Dapinglin–Qizhang | G | 619265949 | DORTS, as above (the Xiaobitan branch turns back here) |
| Songjiang Nanjing–Nanjing Fuxing | G | 871168318 | **only a compilation on PTT**; see below |

The main source is a book by the Department of Rapid Transit Systems (DORTS) itself, "MRT Engineering Series, Enhanced Edition, 9: Rapid Transit Track Engineering Practice" (捷運工程叢書 精進版 9 捷運軌道工程實務), section 8.3.5.2, "Central sidings", page 406. It lists all six that existed at the time (including an elevated one, between Shipai and Qilian), and even says why the Zhonghe line has none: they were "not provided, as the road width was difficult to obtain". Wikipedia adds another reason: the NT$10bn "slimming" of the 2000s replaced refuge sidings with scissors crossovers.

The book predates the Xinyi Line (2013) and the Songshan Line (2014), so it misses Daan and Songjiang Nanjing–Nanjing Fuxing. Daan is backed by operating facts on Wikipedia: it is the terminus of the Beitou–Daan short workings, and its platform table lists an "alighting platform for short workings (no boarding)". Songjiang Nanjing–Nanjing Fuxing rests **only on a table compiled by enthusiasts on PTT**, the Taiwanese bulletin board; none of the three relevant Wikipedia articles mentions it. The shape, length and position in OSM agree with it, so it is built, but that table is its only source, as the note beside its entry in `POCKETS` says.

The three elevated pocket tracks (Shipai–Qilian, Wende–Gangqian, Xingfu–New Taipei Industrial Park) cannot be built yet. `sec_multi` digs only tunnel cross-sections; an elevated one needs a viaduct version.

### Checking the tracks

The check reads the save back (build two `--bbox` areas first, then the whole network). `tools/verify_tracks.py` cuts across the line every metre along a given direction and counts the rails. At the centre of each of the five stacked stations the cut finds four tracks (two at Fuzhong) at two heights; in the middle of each of the seven pocket tracks it finds three. `verify_exits --levels` requires every exit of a stacked station to reach the warning strips on both levels, and every exit of an interchange station to be in one connected component (a cross-platform interchange needs no interchange passage).

**The verifier itself lied twice.** Once it miscounted. At Guting and Chiang Kai-shek Memorial Hall the alignment is skewed by 56°, so a rail runs as a staircase, and one cut hit it at both −8 and −9: four tracks were counted as six, or eight. Now adjacent offsets at the same height count as one track. The second time was more insidious: it cut in the wrong place. OSM often has two relations for one line, one for each direction, and near Daan the two Tamsui-Xinyi geometries are 19 m apart. The tool picked the nearer one, which was the one the generator had not built, found a single track, and reported what looked like a missing pocket track. Now every tool goes through `alignment.select_variants` first, and looks only at the variants the generator builds.

## Signs

The stations used to have only a plain-text name sign every 20 m on the platform screen doors (`R10;BL12／台北車站`) and an "出口 N" at each exit: no direction, no next station, no line colour, and nothing at all in the concourse. The signs are now in `mrt/application/signage.py`, and every one stands at a berth from `domain/network.py`.

**Ride signs.** Each line in each station box has three on each side, alternating Chinese and English, standing in the row of platform screen doors (each replaces a pane of glass, where the old name signs stood).

| Sign | Text in the game | Click |
|---|---|---|
| Chinese | `← 往 南港展覽館 / 下一站 善導寺 / BL12 台北車站 / ▶ 右鍵點擊搭車` | `function mrt:ride/<this>_<next>` |
| English | `← To Dingpu / Next: Longshan Temple / BL11 Ximen / ▶ Click to ride` | the same |
| Terminus, arrival side | `本站終點 / 請至對面月台 / 搭往 頂埔` | `mrt:turn/…`: to the opposite platform |

The Chinese sign says what the English one does: towards Taipei Nangang Exhibition Center, next station Shandao Temple, right-click to ride. The terminus sign says that this is the end of the line, and to cross to the opposite platform for Dingpu. The arrow points the way the train leaves. Trains run on the right, so on an island platform, where you stand between the two tracks, they always run from right to left; on a side platform, where you stand outside the track, from left to right.

**Fitting the text.** A line is at most 90 px wide, and the game simply does not draw anything beyond that. A Chinese character counts as 9 px (Unifont's full width); ASCII is measured glyph by glyph from the game's font, with a pixel more per character in bold. An English name that does not fit is abbreviated in stages (Exhibition Center becomes Exh. Ctr., Chiang Kai-Shek becomes CKS, and so on). Dropping words always leaves at least two: "Taipei Nangang Exhibition Center" cut down to "Nangang" would be a different station. Only then is it truncated with "…". Where "Next: " and the name do not fit on one line (Zhongxiao Fuxing, Shandao Temple and others), it splits over two, under "Next station", and this station's own name makes way. The Chinese sign next to it carries this station's number, but only this sign gives the next station in English.

**Pale oak and glowing ink.** The signs are `pale_oak`, because the Taipei Metro's own station signs are white, and their text glows, because a station box is dark; glowing black text gets an off-white outline. Line colours too pale to read on it (the Circular Line's yellow, the light rail pastels, the pale purple that OSM gives the Airport MRT) keep their hue and are darkened to a contrast of at least 3:1.

**Line-colour bands.** The top row of the platform screen doors becomes a lintel in the line colour (the doorways are still three blocks high), and in underground stations the wall beyond the tracks gets two rows at eye level, visible through the doors. The block is whichever concrete or terracotta is nearest in colour, with three exceptions: the Tamsui-Xinyi Line (the colour-difference formula rates bright orange nearer its red than dark red), the Zhonghe-Xinlu Line (the nearest is yellow terracotta, which is the Circular Line's) and the Airport MRT (the nearest to pale purple is white). **Yellow concrete is never a candidate.** It is the platform warning strip, and both `verify_exits` and `verify_rides` find platforms by the block above yellow concrete. Stacked stations have bands on both levels; a shared box takes each side's colour from the line on that side; and the stacked side-platform station has them on the track side only.

**In the concourse.** A two-faced sign stands on a fare-gate cabinet. The front faces the unpaid area: `往月台 Platforms / 板南線 BL / 往 南港展覽館/頂埔` (to the platforms; Bannan Line; towards Taipei Nangang Exhibition Center and Dingpu). The back faces the paid area: `往出口 To Exits` and the station name. The unpaid area has a route-map ticket machine (the same block as the gates), which opens the `mrt:network` dialogue. At side-platform stations the two platforms go different ways, so each stair head has its own sign giving the direction and the next station in both languages (`↑ 往 淡水`, `To Tamsui`, and so on). At stacked stations there is one at the top of the stair down from the upper platform and one at the foot of the stair up from the lower, listing the direction of each line on that level. None of them blocks the exit openings (side wall, `lo+5..9`) or the interchange-passage openings (side wall, paid area).

**Exit signs** get a glowing first line in the line colour, but not one character of their text changes. `verify_exits` recognises an exit kiosk by a first line of `出口` and a second line holding the station name, and no other sign's first line starts with `出口`.

![An exit sign at street level reading 出口 2, 公館, Gongguan, Exit 2, beside the top of the stair](../demo/exit.jpg)

Gongguan exit 2, at the top of the stair from the platform. The number is the real one.

### What the read-back caught

`tools/verify_rides.py` caught two faults on its first run, both of which the build log had recorded as done.

- **Signs standing in doorways.** When `network` chose berths it avoided only the doorways where `along % 7 < 2`. But on curves and diagonals two samples 1 m apart round to the same block, and the doorway sample was built later. On the Tamsui-Xinyi Line at Taipei Main Station and Chiang Kai-shek Memorial Hall, and on the Bannan Line at Banqiao, the signs had nothing above them (at side-platform stations, sometimes nothing below either). The column is now filled back with glass as each sign goes up. At side-platform stations the block under a sign may in fact be the platform warning strip (Liuzhangli), so `_station_side` runs again, in order, to confirm that it is a doorway before filling it. Only a block-by-block diff against the old save showed that the first version had turned one block of Liuzhangli's warning strip into glass.
- **A link stair shaft through a platform.** The link stair shaft from Taipei Main Station's underground mall to the Tamsui-Xinyi concourse (from y62 all the way down to y44) passed through the middle of the Bannan station box. The shaft is built after the station, so that stretch of platform, with its screen doors and signs, became air inside the shaft. The old name signs had been hanging there for some time: the block entity still present, the block itself air. `landmark_blocker` now counts the body of the switchback shaft, those berths are no longer planned, and the concourse signs avoid it too. The shaft itself has moved. `build_concourse.plan` takes the occupancy table from `exits.index_segments`, a shaft body loses 50 points for every block that passes through another line's station box or tunnel, and there are more candidate positions along the box (between the openings of the two platform stairs, between the gates and the first stair, and beyond the second stair). All eight link stairs around Taipei Main Station now keep clear of the other lines, and the Bannan platform reads back whole; the one at Zhongshan for the Songshan-Xindian Line has moved as well. The old save in `out/` still has the hole.

Building the whole network and reading it back caught three more that the `--bbox` areas had never met.

- **Berths pressed against the sign.** A berth used to be the sign's offset ±2, rounded separately. At some angles the two offsets round to adjacent blocks, and the player lands nose to the sign (Zhongxiao Xinsheng, Ankang, Danfeng). Now the berth is found by walking from the sign's block into the platform exactly two blocks along the main axis, so the Chebyshev distance is always 2, and the yaw faces the sign's block. `tests/test_network.py` gained stations at 15, 30, 45 and 60°.
- **Branches through junction stations.** The Xiaobitan branch at Qizhang and the Xinbeitou branch at Beitou lost their own stations to deduplication (the station is built on the main line). But inside the box the branch geometry strays more than 8 m from the main line, so the mask of what had not yet been built let another tunnel or viaduct sweep through, after the main line's station had been built. Qizhang lost 51% of one platform edge. On the east side of Beitou, 52% lay under the viaduct, one block higher, with its railings standing on the platform. A branch now builds no cross-section and lays no rails inside a junction station's box. The ride system also has `later_section_blocker`: blocks that a later segment will overwrite are not planned as berths, and if the first three sign positions are eaten, the next ones step in, in order.
- **Two false alarms from the verifier.** It took the airport terminals' Skytrain (ref `Skytrain` in `mc_stations.csv`) for metro stations. And it compared the correct "Next: Dapinglin" on a sign with the English-name column, which for Circular Line Y07 holds "大坪林". It now accepts only route station numbers, and borrows an English name from the station of the same name, as the generator does.

Checking the teleport destinations needs the datapack; without it, only the signs and berths are checked. In a small `--bbox` save, destinations in neighbouring stations outside the area are never generated; the tool lists them separately and does not count them as failures.

## Real exits

Apart from Taipei Main Station, every station used to have a single template stair at a fixed spot on the side of its box. Yet `data/entrances.json` had held the coordinates and numbers of all 786 real exits on the network all along: Gongguan has 27, and exit 6 at Chiang Kai-shek Memorial Hall is 264 m from its station box. Now all 193 stations are built from the data. Their 183 station boxes have **472 exits** between them: 467 switchback stair shafts and 5 at-grade exits, including 7 from the complexes that the underground mall could not reach, which fall back to connecting to their own station boxes. Every door has a sign reading `出口 N`, then the station name in Chinese and English, then `Exit N`. The 33 station boxes with no exits in the data (the at-grade stations of the Airport MRT's Taoyuan section, the Ankeng LRT and the Danhai LRT) get one exit at a default position, which goes through the same process.

Each exit is three things. `mrt/domain/exits.py` decides where they go and `application/build_exits.py` lays the blocks.

1. A switchback stair shaft (the same `ShaftStair` as the link stairs at Taipei Main Station, with `g0` set to the real ground) from the street down to concourse level.
2. A connecting passage from the door at the bottom of the shaft, along the outside of the box, to its side wall.
3. An opening in the side wall into the unpaid area in front of the fare gates.

![A switchback exit shaft and its passage to an underground station box, seen from inside the ground](../demo/cutaway.jpg)

An exit shaft, its passage and the station box, photographed from inside the rock in spectator mode: with the camera inside a solid block, Minecraft stops drawing the surface.

Three things in the data decided the approach.

- **Exits are not next to the box.** The median distance along the line is 73 m and nine in ten are within 240 m, so more than half the exits fall outside the 70 m of platform. A passage therefore cannot go straight in: it first runs along the outside of the box to the opening (`lo + 7 m`; the gates are at `lo + 14`). Passages always run at offset 15 (the box's half-width of 12, plus 3) and follow the alignment's samples, so they never cut into the box however it curves.
- **Exits are often right above the tunnel.** One in ten is less than 10 m from the centre line, and a shaft dug from the street to the concourse there would go through the roof of the running tunnel. So the shaft is pushed outward along the normal until every block of it (with a one-block margin) is at least 18 from the centre line and clear of every line's underground structures. **Measure every block, not just the door.** A shaft can face only the four compass directions, so where the alignment runs at 45° a corner of the shaft comes 4 m closer than its door (that is how Fuzhong exit 1's passage came to be blocked by its own station's shaft). Half the shafts are not pushed at all, and nine in ten move less than 17 m.
- **Exits at interchange stations are shared.** Zhongxiao Xinsheng's 14 exits belong to both the Bannan and Zhonghe-Xinlu lines, and each connects only to the nearer station box. Where one exit number has two nodes (OSM often tags an exit once per line; Fuzhong exit 1 has two nodes 26 m apart), they are merged into one. Otherwise two shafts end up one behind the other on the same normal, and the front one blocks the back one's passage.

**Avoidance runs on an occupancy table with heights.** The tunnels, station boxes, piers and at-grade station halls of every line are first painted in as "something is here between y0 and y1". Shafts and passages are checked against it block by block; passages are also checked against the shafts already built at their own station, the passages of other stations, and the terrain. A passage is flat and the terrain is not: at Banqiao the ground falls 6 m towards the Circular Line's end, and a passage there would push its roof up through the street. At an interchange station the two concourses are 15 m apart vertically, so their passages cross in plan and never touch. Without heights in the table, half the exits at interchanges would be blocked by their own side. The passage check also skips **its own line's segment**. A passage runs alongside its own line by design, and all that happens there is that the rasterised edge of a diagonal grazes the outermost block of lining; that is not a collision. Before this exemption, two-thirds of the exits were judged to hit another line.

In the full build of 27 September 2026, 24 exits cannot be connected, each for a reason that the report prints:

| Reason | Exits |
|---|---:|
| Hits another shaft or passage | 13 |
| The passage would break the surface | 5 |
| Hits another line's structure | 4 |
| More than 350 m from the station box | 1 |
| No room for the shaft | 1 |

Of the 13, four are fallbacks from the complexes, and one is Ximen exit 5. Ximen's 15 exits used to be split between the two lines' station boxes and now all hang off one shared box, and the last one does not fit. Two of the four that hit another line are at Beitou, with the Xinbeitou branch directly beneath them. The one too far away is Zhongxiao Xinsheng's emergency exit on Xinsheng South Road. The one with no room for its shaft is Donghu exit 2: once exit 1 became an at-grade exit, its passage ran right past exit 2's door, and pushing the shaft outward hit exit 1's ramp.

### Elevated and at-grade stations

The same shaft and the same geometry, with the doors the other way up. An underground station's shaft digs down from the street to the concourse; an elevated station's **climbs up** from the street to the concourse under the viaduct, and the exit sign stands by the lower door. The passage becomes a skybridge with glass parapets, on a column every 6 m wherever the terrain drops away beneath it. The occupancy table records elevated stations together with their concourses, under the viaduct or above the platforms. The passage also loses its rule against breaking the surface, since a skybridge is above ground anyway, and where the terrain rises higher than it, it cuts into the slope.

**Where the street is less than 3 m from the concourse, there is no shaft but an at-grade exit** (`exits.place_gate` and `build_exits.GroundGate`; one each at Muzha, Donghu, Tamkang University, Danjin Denggong and Yingge Station). A concourse under the viaduct is only 3–7 m above the ground, and on a hillside the street can be within two metres of it either way. A shaft cannot be built there: its two doors are in the same wall, and with less than three blocks of drop the lower doorway shrinks to one block. Nor is one needed. The end of the passage is the door, and outside it the floor rises or falls a block for every block along until it meets the street, followed by a three-block apron with the exit sign beside it. The passage's painted width covers two blocks beyond the door; the ramp is built after the floor and turns those two blocks into steps.

### Interchange passages

Sixteen interchange stations get an interchange passage between their two station boxes, from **paid area to paid area** (`exits.plan_transfer`). That leaves out the Taipei Main Station complex, and Ximen, Chiang Kai-shek Memorial Hall, Guting and Dongmen, where two lines share one box and the island platform is itself the interchange (see [stacked stations](#stacked-stations-and-pocket-tracks)). Where the two concourses are at the same height (New Taipei Industrial Park A/Y and Hongshulin R/V differ by only 1 m), one passage joins them directly. Where they are not, a switchback shaft stands between the boxes, each level runs a passage to one of its doors, and each door has a sign reading `轉乘 Transfer / 往 X 線` (to line X). At the underground-to-elevated interchanges, such as Zhongxiao Fuxing, Daan, Nanjing Fuxing and Taipei Nangang Exhibition Center, the shaft runs from the concourse under the viaduct all the way down to the underground one, and its tower rises through the street. The real interchange at Zhongxiao Fuxing is just such a tower.

To place the shaft, a 4 m grid is laid around the nearest pair of contact points on the two boxes' paid-area wall bands, and the cells near both boxes are tried first. Where the lines cross (Zhongxiao Xinsheng, Songjiang Nanjing and others), the contact points sit right beside the crossing, everything near the middle of the grid is too close to both lines, and the shaft has to retreat into one of the crossing's quadrants. So candidates are screened roughly by the shaft's centre first and checked block by block only if they pass; otherwise the first six hundred candidates all circle the crossing. The openings start 4 m past the gates and stop 4 m short of the end wall, and in an elevated concourse they also avoid the platform stairs at the `hi` end. Only positions where the rail top is at the same height as at the exit openings are chosen, so that in a station on a gradient the two floors still meet as one.

**Interchange first, or exits first?** There is only so much room between two boxes. At Taipei Nangang Exhibition Center, placing the ten exits first leaves nowhere for the interchange shaft; placing the shaft first costs Dapinglin two exits. So every interchange station is planned in both orders, each on its own copy of the occupancy table, and the higher score wins. One interchange passage is worth four exits: a missing exit means a detour, whereas two boxes that do not connect are simply broken. The result is that all 16 connect, at a cost of one exit compared with building no interchange passages at all. The four cross-platform interchanges (Ximen, Chiang Kai-shek Memorial Hall, Guting and Dongmen) are not among the 16: sharing one box, they need no passage.

### Tail tracks at termini

Ten termini, among them Tamsui, Dingpu and Yingtao Fude, used to be half a station. OSM's route geometry stops at the station node, the box runs 35 m either side of the node, and its back half had no samples to build on. Now, where a station stands near the end of an alignment, the alignment is extended along its tangent beyond the box (`alignment.extend_ends`; 371 m across the network). A real terminus has a tail track anyway.

### Checking the exits

`tools/verify_exits.py` reads the signs back from the save to find every exit kiosk, walks from each door to a platform's warning strip without stepping on soil, and then checks for a foothold on terrain outside the door. At interchange stations (those with more than one line in `mc_stations.csv`) every exit must also be in one connected component. All 472 exits reach a platform and every door opens onto the street; at each of the 22 interchange stations the exits form a single cluster; and at the five stacked stations every exit reaches both platform levels (`--levels`).

This round turned up two more surprises. The first was the verifier's. It read back only 6 m above the exit sign, while an elevated platform is 14 m above the street, so every elevated station was judged unable to reach its platform. The second was the generator's. Where the alignment runs at 45°, adjacent steps of a two-block-wide platform stair touched only at their corners: the samples advance (0.7, 0.7) per metre, and after rounding no pair of four-neighbours touches. A cross-section shows every step, and a walker falls off halfway. Each step now also lays the block at the half-metre sample between it and the step before. That block can land on the existing tread (Sanxia, Rose China Town), so every step is checked again, and where two adjacent steps still do not touch, one block is added between the diagonal pair.

**The order of full blocks and slabs on a stair must match the direction of travel.** Going down, a full block comes first and then a slab. The other way round leaves a drop of 1.5 m every two metres, which you can walk down but not climb back up.

## Taipei Main Station

The other 180 stations are swept out of one template along the line. Taipei Main Station is not: it is built from the actual drawings, and every number has a source.

### The station building

The building (`Building` in `mrt/application/landmarks.py`) takes its plan from OSM way 23641610, with 25 vertices. Measured along its axes it is 169×141 m, larger than the official size; the extra is overhanging eaves and canopies at ground level. Taiwan Railway's plan of its leased areas shows a column grid of 8.75 m: 17 bays east to west make 148.75 m, and 12 bays north to south plus a narrow central bay of 5.30 m make 110.3 m. So **the main structure is the intersection of the OSM outline with a 149×110 m rectangle**, and the eaves keep the full outline.

The eaves are at 30 m and the roof adds 18 m, 48 m in all. `height=30` cannot hold seven storeys and an 18 m roof as well, so 30 m is the eaves and not the total; the press describes the hall as seven storeys high, which agrees. The roof is **red-brick-coloured terracotta with white trim, and a truncated hip**: four slopes that stop at a flat top, not a pyramid. `hip_roof` clamps the rise at `roof_max`, and the flat top forms by itself. Roof height comes from a distance field from the boundary (a BFS), so the slopes close in evenly from all four sides, whatever the shape of the plan.

The **atrium hall is 61.25 × 40.30 m**, the area inside the columns, and rises from the ground to the roof. It has **eight free-standing columns** in two rows of four, 17.5 m apart within a row and 40.3 m between rows. The real ones are about 1.35 m square; these are 3 m square, because a one-block column vanishes in a 30 m void.

The floor is a **black-and-white diagonal chequerboard**. The parity of `(x+z)//4 + (x-z)//4` gives diamonds turned 45°, 4 m on the diagonal (2.83 m a side), within the estimated 3.0–3.2 m. Check it **row by row**: along its own grid lines a 45° chequerboard has whole rows of one colour, so sampling every other row mistakes it for stripes. (The real floor was laid in 2011; it is not the 1989 design.)

The **doors** are at the nodes OSM tags: South 1–3, North 1–3, East 1 and 3, West 1 and 3. Each of these nodes lies on a vertex of the building's plan: ten out of ten are on the outer wall.

### Railway platforms

`RailHall` builds the railway level. OSM draws platform ways as **closed outlines, not centre lines**. At first they were painted with a radius along the line, which made the 8.5 m platforms 18 m wide and stuck the four of them together into two blobs. Filling the polygons directly gives their real shape, each about 2,500–2,900 m² (that is, 327 m × 8.5 m). The base slab is at y50, the track bed at y51, the platforms at y52 and the roof slab at y58, in a box of 362×142 m. It has been checked for zero vertical overlap with the tunnels of every line. Taiwan Railway and the high-speed rail are **side by side on B2** (confirmed).

### Metro platforms

The metro platforms are built by the line generator, at depths set by the pins (see [tunnel layering](building.md#tunnel-layering)): the Bannan Line on B3 (rail top y51), the Tamsui-Xinyi Line on B4 (rail top y37).

Which platform belongs to which line is **decided by the direction of its axis, not by its tags**. The one tagged `level=-3` runs east to west, 8 m from the Bannan Line and 53 m from the Tamsui-Xinyi; the one tagged `level=-4` runs north to south, 7 m from the Tamsui-Xinyi Line and 133 m from the Bannan.

### Underground malls

Taipei Main Station's exits are not each a stair down to the station: in reality they are strung together by **underground malls**, which `mrt/application/build_concourse.py` builds. OSM maps the area thoroughly, with 8.9 km of passage centre lines. They cover Taipei City Mall (Y1–Y28, under Civic Boulevard towards Beimen), Station Front Metro Mall (zone Z), Zhongshan Metro Mall (which runs all the way to Shuanglian), the food court under the Caesar Park hotel, and the metro concourses of zones M and K. So the malls are built as mapped, not made up.

Following the data turned up three problems.

- **`level` is not an absolute storey.** Taipei City Mall is tagged `level=-2`, Station Front Metro Mall `level=-2` but `layer=-1`, and Zhongshan Metro Mall `level=-1`. All three are in fact B1, and walking from one to another takes a couple of hundred metres. `level` is relative to each group of mappers' own datum, and comparing it across groups means nothing. So `level` decides only whether something is underground; the height is worked out separately.
- **The ends do not meet.** The area has 199 dangling ends, 71 of them within 5 m of another node. Without merging them first, the 8.9 km network falls apart into 60 pieces. Nodes merge within 3 m, and components still apart within 25 m get a short link. (The Beimen link to the Airport MRT is entirely isolated, but its east end is twenty-odd metres from the western part of Taipei City Mall.)
- **Exits are not always on a passage.** In OSM, Taipei City Mall is five centre lines with none of the cross passages drawn, and exits Y9–Y20 and Y22–Y28 are all 9–42 m off them. These get connecting passages of their own.

**The vertical position is not chosen: it is worked out, and happens to line up.** Band 0 is 15 m deep, a station box's roof slab is at rail top + 10 and its concourse floor at rail top + 6, so with the ground at y66 the Bannan box's roof slab is at exactly y61 and its concourse floor at exactly y57. The mall floor is at y61. It **is** the Bannan box's roof slab, with no spare layer in between. The clearance is y62–64, and the roof slab at y65–66 follows the terrain. Each link stair is therefore just a way down from y62 to where you stand in each line's concourse: y58 for the Bannan Line, y52 for the Taiwan Railway and high-speed rail hall, y44 for the Tamsui-Xinyi Line and y59 for the Airport MRT.

The link stairs are switchback shafts, not straight flights. The Tamsui-Xinyi concourse is at y44, and a straight stair would need 36 m to climb out of it. The station box follows the curving alignment, so a straight 36 m flight would leave the box partway, and its foot would miss the concourse (which is exactly what happened when it was tried). A switchback folds the climb into an 18×11 m shaft. The same `ShaftStair` with a different `g0` turns from a street exit into a stair between levels: its top landing sits exactly on the mall floor, its door opens into the mall's clearance, and its cap is exactly the mall's roof slab.

**There are now four complex stations: Taipei Main Station, Beimen, Zhongshan and Shuanglian.** Zhongshan Metro Mall runs through to Shuanglian, and in reality the exits of both stations open onto the mall. Separate shafts would dig through the mall, so these exits are left to the mall as well. Each complex station gets a link stair to the concourse of every underground line (it used to be only Taipei Main Station's own three lines, and Beimen's Songshan-Xindian platform could not be reached from the mall at all). The template stair is switched off at complex stations: it climbs from the concourse to the ground right through the mall level, and its treads lie across the passage and seal it. Mall exits that cannot be connected (a few on the west side of Beimen) go back to the ordinary exit planning and connect to their own station boxes.

Placing the link stair shafts takes care.

- Two shafts close together (the two concourses at Zhongshan are only 14 m apart) overlap, and the later one digs the earlier one's stair out into a void. A cross-section shows both shafts; only walking them shows that one is empty.
- A shaft on top of a passage cuts it in two. Zhongshan Metro Mall lies directly above the Tamsui-Xinyi Line, so a shaft at the centre of the box lay across the passage, wider than it, and the northern and southern halves no longer connected. A shaft can move along the normal to the edge of the passage, with a connector joining its door back.
- The door moves 7 m along the box. The two stairs from the concourse to the platform open holes in its floor, and a door facing the middle of the box opens onto a five-metre drop.
- Out of the door, the connector runs straight for four blocks before turning towards the nearest node. The door is only three blocks wide, and a connector leaving at an angle sweeps away the shaft walls either side; the shaft is built after the passage, and once its walls go back in, the door is sealed.
- The exit stairs are planned first and the shafts keep clear of them; otherwise Shuanglian exits 1 and 2 lose half their stairs.

**The result**, as `tools/verify_concourse.py` reads it back from the save rather than as the generator reports it: of the 73 exits at the four complex stations, 67 have underground space, and **all 67 are in one connected component**. You can walk between any two without surfacing (the longest pair, Zhongshan exit 1 to Beimen exit 5, is 2,207 steps apart), all 67 lead up to the street, and the warning strips of all eleven platforms can be reached: Taiwan Railway and the high-speed rail, Taipei Main Station's three lines, Beimen's Songshan-Xindian Line, Zhongshan's two lines, and Shuanglian.

The version before had 58 exits at Taipei Main Station and Beimen in one component, reaching four platform levels. The one before that had 14 fragments that did not connect, and 32 exits with nothing underground at all.

## The ride system

Nobody walks 253 km, so the platforms have ride signs. **Right-click one and you ride to the next station**, arriving on its platform in the same direction of travel, facing the sign that carries on from there, with the crosshair on it; keep clicking and you ride on, stop after stop. In the concourse, the ticket-machine sign opens the route map: click a line, then a station, and you are teleported there. The rules are in `mrt/domain/network.py`, `mrt/application/ride_plan.py` generates the commands and dialogues, and `cli.build_world` finishes by writing the datapack to `<save>/datapacks/taipei_mrt/`, already enabled in `level.dat`.

![Arriving at Ximen: the station name as a title in the Bannan Line's blue, the station number and line beneath, the next station on the action bar](../demo/arrival.jpg)

Arriving at Ximen on the Bannan Line.

| Function | Count | What it does |
|---|---:|---|
| `mrt:ride/<from>_<to>` | 366 | Teleport, arrival chime, the station name as a title in the line colour, its number and line as a subtitle, and the next station on the action bar |
| `mrt:turn/*` | 24 | Behind the arrival-side sign at a terminus: moves you to the opposite platform |
| `mrt:go/<number>` | 193 | The route map's destinations |

Every one of these functions is exactly one line, `tp @s x y z yaw pitch` in absolute coordinates, and the read-back verification depends on it.

The route map, `mrt:network`, has one button per line in the line colour, each opening that line's station list, `mrt:line/<line>`. The station buttons send `/trigger mrt.go set <n>`, which works for players without operator rights. The map hangs off `#minecraft:quick_actions` (the Quick Actions key, G by default) and `#minecraft:pause_screen_additions` (the pause menu), and `/trigger mrt.menu` opens it too.

On first joining the world you arrive on the R10 Taipei Main Station platform, with a greeting in Chinese and English in the chat, including a route-map button and "© OpenStreetMap contributors". Walking into a station lights up the action bar once with its name and line numbers.

A few settings are applied once, when the world first loads (`#setup` records a version, so `/reload` does not undo changes made later): no hostile mobs, phantoms, patrols or wandering traders; time stopped at noon; clear weather; nothing dropped on death; mobs cannot break blocks; and respawns are not scattered at random. The chat lists what was changed and how to undo it; click a command and it is filled in.

In 26.2, `pack.mcmeta` uses `min_format` and `max_format` (here `[107, 1]` to `107`, since `version.json` in the game jar says data 107.1), and game rule ids are snake_case (`spawn_monsters`, `advance_time`). None of this was copied from the wiki; `tools/check_datapack.py` caught each point. Write only the old `pack_format` and the game warns "missing mandatory fields min_format and max_format"; get a rule id wrong and the whole function fails to load. But **a wrong range (a maximum of 106, say) loads without a murmur**, so the tool checks the range against `version.json` in the jar rather than trusting the game's silence.
