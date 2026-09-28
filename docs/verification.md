# Verification

Nothing the generator reports about itself is taken on trust. Every check reads the save back from disk and compares.

## Checks that need no world

```bash
./.venv/bin/python tests/run_all.py
```

- `tests/` gives geometry, alignment, rails and landmarks their own unit tests (polygon fill area, outer ring, inset, roof convergence, the treads and headroom of switchback stairs), all without generating a world.
- `mrt/domain/tunnel_layers.py` checks its own banding: where the underground blocks of two different lines are adjacent, their bands must differ.
- An ASCII cross-section: print the section and look at it (see [slices](#slices)).

## Tools that read the save back

### `tools/verify_render.py`

Reads the region files back and renders a plan view, with any block missing from the palette in magenta. `--bbox X0 Z0 X1 Z1` renders a small area as a close-up (with `--scale 1`, at 1 m per pixel). **Beware**: the terminal output lists only the first 20 block types, so a new material that fails to make the list never raises the "not in palette" warning. Only a scan of the image itself for magenta pixels counts, and height shading darkens the magenta, so the test is g=0 and r=b, not r>200.

### `tools/render_view.py`

Reads an area back and draws elevations, a plan and an isometric view, with colours computed from the game's textures. `verify_render` now does the same for any block outside its hand-picked palette, so magenta is left meaning only that no colour could be computed at all, which usually means a mistyped block id.

### `tools/verify_attractions.py`

Reads back every attraction: its height against published figures the tool carries itself, whether the OSM outline is covered, whether anything spills outside it, whether each teleport point can be stood on, and the plaques (see [attractions](attractions.md)).

### `tools/verify_concourse.py`

Reads back the underground malls and checks that every exit can reach every other **without surfacing**. That rule is the whole point of the tool. The exits all open onto the same streets, so if walking at street level were allowed they would all connect, and nothing would have been tested. "Underground" is judged block by block against the local ground surface (feet at least two blocks below the surface block), not by a global ceiling on y. Walking follows the rules a player can actually manage (`mrt/domain/walk.py`: four neighbours, up or down one block, two blocks of headroom, three when standing on a bottom slab, slabs understood). The rules are deliberately symmetric. Real Minecraft lets you drop from any height, and checking with that would pass a dead-end stair that you can jump down but never climb back up.

### `tools/verify_exits.py`

Reads back the signs to find every exit kiosk, then walks from its door to the yellow warning strip on a platform **without stepping on soil** (only man-made blocks underfoot). This is stricter than not surfacing. The kiosks themselves stand in the street; if walking on terrain were allowed, any broken stair could be bypassed by walking along the street to the next exit and going down there, and again nothing would have been tested. At an interchange station every exit must also be in the same connected component: two clumps mean the interchange passage does not connect.

### `tools/verify_rails.py`

Reads back every rail and checks that each declared connection has a rail on the other side that connects back, that sloped rails meet at the right heights, and that no rail sits on air. The generator's own unit tests prove only that the computed path is valid, not that it stays valid once written into the world.

### `tools/verify_tracks.py`

Reads back the rails in a slice every metre along the line from a given point: how many tracks there are, and the offset and height of each. The stacked stations (`--station 西門 --expect 4 --levels 2`) and the pocket tracks (`--pocket 大安 信義安和 --expect 3`, where the middle slice must show three tracks) were counted off the disk this way. `verify_exits --levels 府中 西門 中正紀念堂 古亭 東門` additionally requires those stations' exits to reach the warning strips on both platform levels. The tool always picks its geometry through `alignment.select_variants`, as the generator does; otherwise OSM's two relations, one per direction, can differ by a dozen metres or more, and a slice through the one that was never built reports a problem that does not exist.

### `tools/verify_spawn.py`

Reads back the spawn point in level.dat and the chunk heightmaps. The spawn point must be standable, with sky overhead; the four stored heightmaps must match heightmaps recomputed from the blocks, column by column (`--all` compares every chunk); and a walk over the heightmaps in the manner of the game's `getLevelRespawnPos` must put the player exactly on the spawn block, facing the door of the exit kiosk.

Players once spawned at (0.5, −63, 0.5), in the stone at the bottom of the world. At the time the chunks were written with empty `Heightmaps`, and the spawn point was straight above the station node, the column most hollowed out by the underground mall and two station boxes. But 26.2 recomputes missing heightmaps when it loads a chunk (`SerializableChunkData.read` calls `primeHeightmaps`), and −63 looks more like the fallback for when every candidate fails (`PlayerSpawnFinder.fixupSpawnHeight`). It could not be reproduced, so both suspects were changed. Full chunks now carry the same four maps the game saves (`mrt/infrastructure/heightmap.py`: WORLD_SURFACE, OCEAN_FLOOR, MOTION_BLOCKING and MOTION_BLOCKING_NO_LEAVES), packed bit for bit as the 26.2 GameTest server saves them: 9 bits a column, 7 entries to a long and 37 longs in the original 384-block world, 10 bits and 43 longs in the raised one. The classification of blocks was checked against the game's `Heightmap.Types.isOpaque()` for all 32,366 block states. Signs, banners and pressure plates can be walked through but count as blocking in the heightmap (forceSolidOn); snow layers, ladders and scaffolding are the other way round. The spawn point moved to just outside the kiosk at Taipei Main Station's exit M4, facing its door (`mrt/application/spawn.py`). The game's default respawn_radius is 10, and within that radius are the roofs of the kiosk and stairs, which gave about a 16% chance of landing on a roof.

### `tools/check_datapack.py`

Reads back the ride system's datapack and hands it to **the real Minecraft 26.2** to load and run: the headless GameTest server shipped in the game jar, plus a throwaway test datapack generated for the purpose. The pack must load with no errors and no warnings; the world's initial settings must really apply when the server starts; every ride, turn and go function runs once in the game, and the landing position and facing are read back; every route-map button, dispatched through its trigger, must land at the station on the button; the arrival notice's range scan must catch every landing point; and each sign's click_event must survive the game loading it. Negative controls (a deliberately broken function, a sign pointing at a dialog that does not exist, a marker that was never teleported and so on) must be caught, or the tool counts itself as failed.

### `tools/verify_rides.py`

Reads back every ride sign, recognised by its click command (`function mrt:ride/…` or `mrt:turn/…`). Each sign must stand in the row of platform screen doors, the block in front of it must be standable and on the platform, and the next station written on it must be the command's destination. If the save has the datapack, the tool then opens every function file and checks its one `tp` line: the destination must be standable, on the platform, and facing the next station's sign. It counts the signs at each station, and a station with none in range fails (see [signs](stations.md#signs)).

## What the checks caught

The first round found tunnels hanging in the void, stair slabs overwritten (with `STEP=0.5`, each step advanced only 1 m), and all-black renders caused by the camera's default `clip_end` of 100 m.

Building the same area with the old version of the program and diffing it block by block caught another batch. The build log had reported every one of them as done.

- **A shared trunk hollowed out twelve stations.** The Zhonghe-Xinlu Line's two variants share 13 km of trunk, and building it twice was thought merely a waste of time. In fact the second copy swept through after the first copy's stations were built, and its own duplicate stations had been removed by deduplication, so it had no widened section: a plain tunnel 15 m wide ran straight through station boxes 25 m wide. The platforms, platform screen doors and concourse floors of the twelve stations from Dingxi to Daqiaotou all turned to air, and parts of Qizhang, Beitou and seven Danhai LRT stations were erased. The cross-section of a shared corridor is now built only once.
- **A sheet of grass floated on the rivers.** A section that was entirely air was not written, and when the game saves, unwritten sections are filled with the superflat background (grass at y=64). So over the Keelung and Tamsui rivers floated a layer of grass at y=64, with air beneath and the water below that. Between Yuanshan and Jiantan, 12.7% of the surface blocks over the river were like that.
- **Stairs stopped one block short.** With the surface block at y=g, a person standing on it has their feet at g+1. All three kinds of stair climbed to g and stopped, so you had to jump a block to get out and dropped one getting in. The walk check allowed one block up or down, so it could not see this.
- **`runs()` skipped one block after every gap**, and a branch exactly 200 m long vanished completely.
- **`verify_rails` missed one row in 16.** When a rail sat in the bottom row of a section, the block beneath it was in the section below, and the check had looked down only within the same section.
- **`slice_world` sliced the wrong station.** It matched names by substring, and 中山 (Zhongshan) hit 中山國中 (Zhongshan Junior High School) first.
- **The verifiers lied as well.** With "underground" defined as a global ceiling on y, two more stations and ground 3 m lower got the whole underground mall judged to be on the surface. Keyed by exit number, Ximen station's exit 1 and the Ximen underground mall's exit 1 overwrote each other. Reading back only 6 m above the exit sign left the platforms of elevated stations, 14 m up, out of view, so every elevated station was judged unable to reach its platform. Now "underground" is judged block by block against the local surface, the keys include coordinates, and reads go 32 m up.
- **Ten termini were only half built.** The alignment ended at the terminus's station node, so the back half of the station box had no sample points to build from; at Tamsui the concourse hit a wall at the centre of the box. The ends are now extended along the tangent as tail track.
- **Two-block-wide stairs on a 45° diagonal broke off halfway.** The blocks of adjacent steps touched only at a corner, although every step was there in section. Each step now also fills the block at the half-metre sample point between steps.
- **A level interchange passage sealed the opening at the far end.** At Hongshulin (R/V) the passage runs from the Tamsui-Xinyi Line's box into the LRT's, and walling the outer edge of its floor also walled up the inner side of the opening in the LRT concourse.
- **Interchange passages cut across their own shafts.** At Banqiao, Touqianzhuang and Taipei Nangang Exhibition Center the interchange shaft could face any of four ways. With the station box behind the shaft and to one side, the straight run from the shaft's porch to the box passed through the shaft itself. The shaft was built after the passage, so restoring its walls cut the passage, and the planner's collision check had exempted the shaft body. Now, if a passage block falls inside a shaft, the planner moves on to the next candidate position.
- **A branch's starting point was extended as if it were a terminus.** The Xiaobitan branch leaves from Qizhang, and the rule "extend tail track where an end is near a station" pushed it 35 m back towards Qizhang, straight into the main line's Qizhang station box. An end that another variant of the same line passes through is not a terminus, and is no longer extended.
- **Exits on hillsides had no street at the door.** At Muzha, Tamkang University and Yingge Station the shafts stand on slopes, with two or three blocks of difference in the terrain either side of the threshold. A small apron (grass paving, two blocks of headroom) is now laid in front of the street door.
- **A shaft with only 2 m between street and concourse had a doorway one block high.** A shaft's two doors are in the same wall, and the top of the lower one is clamped below the upper landing; with a 2-block drop in standing level the doorway was one block high, and the apron in front happened to clear away the footbridge's floor. That is how Tamkang University's exit came to be "not connected to the street at the door", the only one of 474 on the network to fail. `MIN_RISE` used to be 2. Now no shaft is built for a rise of less than 3 m, and the exit becomes an at-grade exit (see [elevated and at-grade stations](stations.md#elevated-and-at-grade-stations)).

## Slices

`tools/slice_world.py` cuts ASCII sections straight out of the save, and it is the only way to see what was actually built:

```
./.venv/bin/python tools/slice_world.py 忠孝復興          # across the line
./.venv/bin/python tools/slice_world.py 忠孝復興 --long   # along the line
```

Station ends sealed off by lining walls, and exits that were a single bare shaft without a step in it, were both found this way. `--save <save>` reads a test save instead.

## What `verify_rails.py` caught

Floating rails: to land sloped rails on straight sections, `rails.py` shifts a rise a few blocks forwards or back, and the shifted blocks floated one block above the track bed. A 180° turnback at the end of the Ankeng LRT that pushed two tracks onto the same blocks. And a branch and its main line, sharing a corridor, overwriting each other's rails.
