#!/usr/bin/env python3
"""專案路徑與全域常數。

原本每支腳本各自算一次 ROOT，而且好幾支直接寫死 "data/xxx.json" 的相對路徑
—— 只有從專案根目錄執行才會對。路徑集中在這裡之後，從哪裡執行都一樣。

這一層不屬於任何架構層，是所有層都可以引用的組態。
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATA = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "out")

# --- 管線各階段的產物 ---
LINES_DIR = os.path.join(DATA, "lines")            # OSM 原始路線幾何
STATIONS_JSON = os.path.join(DATA, "stations.json")
WAY_TAGS_JSON = os.path.join(DATA, "way_tags.json")
MC_LINES_JSON = os.path.join(DATA, "mc_lines.json")      # 已投影成 MC 座標
MC_STATIONS_CSV = os.path.join(DATA, "mc_stations.csv")
ENTRANCES_JSON = os.path.join(DATA, "entrances.json")
STATION_BUILDINGS_JSON = os.path.join(DATA, "station_buildings.json")
PLATFORM_LEVELS_JSON = os.path.join(DATA, "platform_levels.json")
HEIGHTMAP_NPY = os.path.join(DATA, "heightmap.npy")
HEIGHTMAP_JSON = os.path.join(DATA, "heightmap.json")

# --- DEM 來源 ---
DEM_NLSC = os.path.join(DATA, "dem", "nlsc20")           # 國土測繪中心 20 m DTM
DEM_COPERNICUS = os.path.join(DATA, "dem", "copernicus")  # GLO-30 DSM（補洞用）

# --- 世界的垂直範圍（26.2）---
Y_MIN, Y_MAX = -64, 319                       # 含端點
SEC_MIN, SEC_MAX = Y_MIN >> 4, Y_MAX >> 4     # -4 .. 19
N_SEC = SEC_MAX - SEC_MIN + 1                 # 24

WORLD_NAME = "Taipei MRT"
DEFAULT_SAVE = os.path.join(OUT, WORLD_NAME)
MC_SAVES = os.path.expanduser("~/Library/Application Support/minecraft/saves")
INSTALLED_SAVE = os.path.join(MC_SAVES, WORLD_NAME)


def region_dir(save):
    """存檔的 region 目錄。26.2 起搬到 dimensions/ 底下。"""
    return os.path.join(save, "dimensions", "minecraft", "overworld", "region")
