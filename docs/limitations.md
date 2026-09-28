# Known limitations

What the world does not have yet, and where it is an approximation.

## Exits and interchanges

Beyond the 472 exits that are built, 24 could not be connected (the reasons are in [real exits](stations.md#real-exits)); 4 of them are exits in the station complexes that the underground mall could not reach either. That is 3 more than the previous version. The exits of the four cross-platform interchange stations now all crowd onto one shared station box, and a few that fitted when they were split between two boxes no longer do.

An interchange passage is a single passage from paid area to paid area, plus a shaft; it is not the real interchange route. The three station boxes of the Taipei Main Station complex connect through the underground mall and have no passage of their own.

## Track

There are no turnouts, signals, platform numbers or trains. With `--rails`, the track breaks for one block where a branch meets its main line, because the main line is laid first and the branch fills in only stretches of 200 m or more that are genuinely unlaid. The third track of a pocket track joins the running lines at neither end, and the crossovers and depot leads are not built (Tucheng Depot branches off between Far Eastern Hospital and Haishan, Nangang Depot between Kunyang and Nangang). The Xiaobitan branch at Qizhang and the Xinbeitou branch at Beitou begin outside the end wall of the junction station's box and do not connect to the station; they used to run straight through its platform.

## Stations

Five stacked stations are built: Fuzhong, Ximen, Chiang Kai-shek Memorial Hall, Guting and Dongmen. The Zhonghe-Xinlu Line has three more, with side platforms: Taipei Bridge (B4/B6), Yongan Market (B2/B4) and Jingan (B4/B6). Which level serves which direction, and which side the doors open, has been established for all three, and they do not even agree on the upper level: at Taipei Bridge trains towards Nanshijiao use it, at Yongan Market and Jingan the lower one. They would follow the `kind="side"` path, but are not wired in yet.

All seven underground pocket tracks are laid. The three elevated ones (Shipai–Qilian, Wende–Gangqian, Xingfu–New Taipei Industrial Park) wait for a viaduct version of `sec_multi`.

Taipei Main Station's official exterior colour and material could not be found, so the beige walls (`smooth_sandstone`) are a guess. The brick-red tiled roof with white trim does have a source.

## Underground malls

Underground malls are built only from Taipei Main Station to Shuanglian, and **flattened into a single level**. In reality Taipei City Mall and the metro concourses are on two levels, but between the surface at y66 and the roof of the Bannan Line's station box at y61 this world has room for only one level of headroom. So OSM's `level` decides only whether a walkway is underground, not which floor it is on. Another 15 stations have more than 250 m of underground walkway in OSM (Songshan Airport 1.5 km, Chiang Kai-shek Memorial Hall 1.0 km, the East District underground mall spanning Zhongxiao Fuxing and Zhongxiao Dunhua, and six stations on the southern Songshan-Xindian Line mapped the same way). The same code ought to cope with them; they are not wired in yet.

## Terrain and data

The Taoyuan section, the western end of the Airport MRT and about 3% of the network, has no DTM and is still filled from the bias-corrected DSM, so its ground elevation is less accurate than in Taipei and New Taipei.

The Sanying Line has only its route and stations. The Bade extension is still `railway=proposed` in OSM and is not included.

Mountains above 180 m, Yangmingshan among them, are compressed vertically 2:1. Terrain still stays below y312; the world is raised to y639, but the extra height is for buildings such as Taipei 101.

## Attractions

Only a few interiors are really built: the lobbies, Taipei 101's 89th and 91st floors, the domed hall of the National Taiwan Museum, and the halls of the Chiang Kai-shek and Sun Yat-sen memorial halls. Every other floor is a slab and some lighting. There are no stairs or lifts; Taipei 101's "lift" is a teleport. Blue and yellow glazed tiles have no slab form, so those roofs slope in whole-block steps. The city gates and Longshan Temple have no official heights and were measured from the proportions in photographs. For two details the agents building them found no photographs and worked from written sources alone: a few stages at the top of the Presidential Office's tower, and the roof colours.

## In the game

The game may warn about experimental settings when you open the world. It marks every registry entry added by a non-vanilla datapack as experimental, and this one adds two: the route map dialogs and the dimension type of the raised world. Go in as normal.

Riding is teleportation, not a moving train. The GameTest server used for the in-game checks (`check_datapack`) has no player. Every teleport function, the dispatch of every route-map button and every sign's click action after loading have run in the real game, but a player actually right-clicking a sign, the dialog screen itself, the Quick Actions and pause-menu buttons, and the detection of a first join count only once someone goes in and clicks.

English station names that are too long for a sign are abbreviated, or truncated with "…" (Songjiang Nanji…, Zhongxiao Xinsh…, about 20 signs across the network). The Chinese sign beside each one has the full name.
