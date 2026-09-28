#!/usr/bin/env python3
"""Project paths and global constants.

Each script used to compute ROOT on its own, and several hard-coded relative paths
such as "data/xxx.json", which worked only when run from the project root. With the
paths gathered here, every script behaves the same wherever it is run from.

This module belongs to no architectural layer; it is configuration that every layer may import.
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATA = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "out")

# --- Outputs of each pipeline stage ---
LINES_DIR = os.path.join(DATA, "lines")            # Raw OSM line geometry
STATIONS_JSON = os.path.join(DATA, "stations.json")
WAY_TAGS_JSON = os.path.join(DATA, "way_tags.json")
MC_LINES_JSON = os.path.join(DATA, "mc_lines.json")      # Already projected to MC coordinates
MC_STATIONS_CSV = os.path.join(DATA, "mc_stations.csv")
ENTRANCES_JSON = os.path.join(DATA, "entrances.json")
STATION_BUILDINGS_JSON = os.path.join(DATA, "station_buildings.json")
PLATFORM_LEVELS_JSON = os.path.join(DATA, "platform_levels.json")
SIDINGS_JSON = os.path.join(DATA, "sidings.json")        # Pocket tracks, crossovers, depot lines
HEIGHTMAP_NPY = os.path.join(DATA, "heightmap.npy")
HEIGHTMAP_JSON = os.path.join(DATA, "heightmap.json")

# --- DEM sources ---
DEM_NLSC = os.path.join(DATA, "dem", "nlsc20")           # NLSC 20 m DTM (Taiwan's national survey)
DEM_COPERNICUS = os.path.join(DATA, "dem", "copernicus")  # GLO-30 DSM (fills gaps)

# --- Vertical extent of the world ---
# The vanilla overworld is y-64..319 (384 blocks). The spire of Taipei 101 is 508 m above
# the ground (ground at y≈70), so a 1:1 build reaches y≈580. A datapack therefore replaces the
# dimension type of minecraft:overworld with one 704 blocks tall
# (infrastructure/datapack.py writes dimension_type/overworld.json from the numbers here).
# Chunks, the heightmap bit width and the read-back tools all take these values from here;
# do not hard-code 319 or 384 anywhere else.
# Terrain is still capped below 312 by Y_CAP in domain/terrain.py; the extra height is for
# buildings only.
Y_MIN, Y_MAX = -64, 639                       # Inclusive
SEC_MIN, SEC_MAX = Y_MIN >> 4, Y_MAX >> 4     # -4 .. 39
N_SEC = SEC_MAX - SEC_MIN + 1                 # 44
WORLD_HEIGHT = Y_MAX - Y_MIN + 1              # 704 (a multiple of 16; min_y + height <= 2032)

# --- Datapack ---
# The click commands on signs (set by the application layer) and the functions in the datapack
# (written by the infrastructure layer) are the two ends of one contract: the namespace is
# defined only once, here, and both sides take it from here.
DATAPACK_NAME = "taipei_mrt"                  # Folder name under <world save>/datapacks/
DATAPACK_NS = "mrt"                           # Namespace for functions, dialogs and scoreboards

WORLD_NAME = "Taipei MRT"
DEFAULT_SAVE = os.path.join(OUT, WORLD_NAME)
MC_SAVES = os.path.expanduser("~/Library/Application Support/minecraft/saves")
INSTALLED_SAVE = os.path.join(MC_SAVES, WORLD_NAME)


def region_dir(save):
    """Return the region directory of a world save. Since 26.2 it lives under dimensions/."""
    return os.path.join(save, "dimensions", "minecraft", "overworld", "region")
