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
SIDINGS_JSON = os.path.join(DATA, "sidings.json")        # 袋狀軌、橫渡線、機廠線
HEIGHTMAP_NPY = os.path.join(DATA, "heightmap.npy")
HEIGHTMAP_JSON = os.path.join(DATA, "heightmap.json")

# --- DEM 來源 ---
DEM_NLSC = os.path.join(DATA, "dem", "nlsc20")           # 國土測繪中心 20 m DTM
DEM_COPERNICUS = os.path.join(DATA, "dem", "copernicus")  # GLO-30 DSM（補洞用）

# --- 世界的垂直範圍 ---
# 原版主世界是 y-64..319（384 格）。台北101 的塔尖在地面上 508 m（地面 y≈70），
# 1:1 蓋要到 y≈580，所以用資料包把 minecraft:overworld 的維度類型換成 704 格高
# （infrastructure/datapack.py 照這裡的數字寫 dimension_type/overworld.json）。
# 區塊、高度圖的位元數、讀回工具都從這裡拿，不要在別處寫死 319 或 384。
# 地形仍照 domain/terrain.py 的 Y_CAP 壓在 312 以下 —— 多出來的高度只給建築用。
Y_MIN, Y_MAX = -64, 639                       # 含端點
SEC_MIN, SEC_MAX = Y_MIN >> 4, Y_MAX >> 4     # -4 .. 39
N_SEC = SEC_MAX - SEC_MIN + 1                 # 44
WORLD_HEIGHT = Y_MAX - Y_MIN + 1              # 704（16 的倍數，min_y + height <= 2032）

# --- 資料包（datapack）---
# 告示牌上的點擊指令（application 層立的）與資料包裡的函式（infrastructure 層寫的）
# 是同一份約定的兩端：命名空間只能在這裡定義一次，兩邊都從這裡拿。
DATAPACK_NAME = "taipei_mrt"                  # <存檔>/datapacks/ 底下的資料夾名稱
DATAPACK_NS = "mrt"                           # 函式、對話框、記分板的命名空間

WORLD_NAME = "Taipei MRT"
DEFAULT_SAVE = os.path.join(OUT, WORLD_NAME)
MC_SAVES = os.path.expanduser("~/Library/Application Support/minecraft/saves")
INSTALLED_SAVE = os.path.join(MC_SAVES, WORLD_NAME)


def region_dir(save):
    """存檔的 region 目錄。26.2 起搬到 dimensions/ 底下。"""
    return os.path.join(save, "dimensions", "minecraft", "overworld", "region")
