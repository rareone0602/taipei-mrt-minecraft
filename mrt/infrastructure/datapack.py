#!/usr/bin/env python3
"""把資料包規格（application/ride_plan.py 產生的純資料）寫成 MC 26.2 的資料包。

26.2 的資料包佈局（資料夾一律單數，1.21 起改制）:
    <存檔>/datapacks/<名稱>/pack.mcmeta
    <存檔>/datapacks/<名稱>/data/<命名空間>/function/<路徑>.mcfunction
    <存檔>/datapacks/<名稱>/data/<命名空間>/dialog/<路徑>.json
    <存檔>/datapacks/<名稱>/data/<標籤命名空間>/tags/function/<標籤>.json
    <存檔>/datapacks/<名稱>/data/<標籤命名空間>/tags/dialog/<標籤>.json
    <存檔>/datapacks/<名稱>/data/minecraft/dimension_type/overworld.json   世界高度

pack.mcmeta 的版本號是這一層的細節（跟 mcworld.DATA_VERSION 同一類）：
26.2 的 version.json 寫 data_major 107、data_minor 1。1.21.9 起 pack.mcmeta 用
min_format／max_format（整數或 [主, 次]），不再寫 pack_format；max_format 寫整數
代表 107.*，之後的小改版也收。實際認不認得，由 tools/check_datapack.py 叫真的
遊戲載入一次來證明，不靠這裡的註解。
"""
import json
import os
import re
import shutil

from mrt import config

PACK_MIN_FORMAT = [107, 1]      # 26.2
PACK_MAX_FORMAT = 107           # 107.*

# 26.2 原版主世界的維度類型（net.minecraft.data.Main --server 從遊戲 jar 匯出的
# data/minecraft/dimension_type/overworld.json），只改高度與雲層：
#   · min_y / height / logical_height 照 config 的世界垂直範圍（台北101 要到 y≈580）
#   · 雲層原本在 y192.33，只比盆地地面高 125 格 —— 站在 101 的 89 樓觀景台（y≈450）
#     往下看會是一整片雲把城市蓋住。抬到 600.33，比觀景台與屋頂都高
# 同一個資料包裡的對話框本來就讓世界的登錄表生命週期變成 experimental
# （非原版資料包的登錄項目一律如此，見 ResourceManagerRegistryLoadTask），
# 多一個維度類型不會讓開世界時多跳出什麼。
CLOUD_HEIGHT = 600.33
_OVERWORLD_BASE = {
    "ambient_light": 0.0,
    "attributes": {
        "minecraft:audio/ambient_sounds": {"mood": {
            "block_search_extent": 8, "offset": 2.0, "sound": "minecraft:ambient.cave",
            "tick_delay": 6000}},
        "minecraft:audio/background_music": {
            "creative": {"max_delay": 24000, "min_delay": 12000, "sound": "minecraft:music.creative"},
            "default": {"max_delay": 24000, "min_delay": 12000, "sound": "minecraft:music.game"}},
        "minecraft:gameplay/bed_rule": {
            "can_set_spawn": "always", "can_sleep": "when_dark",
            "error_message": {"translate": "block.minecraft.bed.no_sleep"}},
        "minecraft:gameplay/nether_portal_spawns_piglin": True,
        "minecraft:gameplay/respawn_anchor_works": False,
        "minecraft:visual/ambient_light_color": "#0a0a0a",
        "minecraft:visual/cloud_color": "#ccffffff",
        "minecraft:visual/cloud_height": 192.33,
        "minecraft:visual/fog_color": "#c0d8ff",
        "minecraft:visual/sky_color": "#78a7ff",
    },
    "coordinate_scale": 1.0,
    "default_clock": "minecraft:overworld",
    "has_ceiling": False,
    "has_ender_dragon_fight": False,
    "has_skylight": True,
    "height": 384,
    "infiniburn": "#minecraft:infiniburn_overworld",
    "logical_height": 384,
    "min_y": -64,
    "monster_spawn_block_light_limit": 0,
    "monster_spawn_light_level": {"type": "minecraft:uniform", "max_inclusive": 7, "min_inclusive": 0},
    "timelines": "#minecraft:in_overworld",
}


def overworld_dimension_type():
    """主世界的維度類型：原版的一份，換上 config 的高度與抬高的雲層。"""
    d = json.loads(json.dumps(_OVERWORLD_BASE))
    d["min_y"] = config.Y_MIN
    d["height"] = d["logical_height"] = config.WORLD_HEIGHT
    d["attributes"]["minecraft:visual/cloud_height"] = CLOUD_HEIGHT
    return d


_PATH_RE = re.compile(r"^[a-z0-9_.\-/]+$")
_ID_RE = re.compile(r"^[a-z0-9_.\-]+:[a-z0-9_.\-/]+$")


def pack_dir(save, name=None):
    return os.path.join(save, "datapacks", name or config.DATAPACK_NAME)


def _check_path(path):
    if not _PATH_RE.match(path) or path.startswith("/") or path.endswith("/") or "//" in path:
        raise ValueError("資源路徑只能用 a-z0-9_.-/：%r" % path)


def _dump(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.write("\n")


def write_datapack(save, spec, name=None, ns=None):
    """把 spec 寫進 <save>/datapacks/<name>/，回傳 dict(path, functions, dialogs, tags)。

    整個資料夾先清掉再寫：路網改了、某一段車程不見了，舊的函式檔不能留著
    讓告示牌以為它還在。只清自己那一個資料夾，存檔的其他部分不碰。
    """
    ns = ns or config.DATAPACK_NS
    root = pack_dir(save, name)
    shutil.rmtree(root, ignore_errors=True)
    os.makedirs(root)
    _dump(os.path.join(root, "pack.mcmeta"), {"pack": {
        "description": spec.get("description", ""),
        "min_format": PACK_MIN_FORMAT,
        "max_format": PACK_MAX_FORMAT,
    }})

    data = os.path.join(root, "data")
    for path, lines in spec["functions"].items():
        _check_path(path)
        bad = [ln for ln in lines if "\n" in ln or "\r" in ln]
        if bad:
            raise ValueError("函式 %s 的一行指令裡有換行：%r" % (path, bad[0][:80]))
        fp = os.path.join(data, ns, "function", path + ".mcfunction")
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        with open(fp, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    for path, obj in spec.get("dialogs", {}).items():
        _check_path(path)
        _dump(os.path.join(data, ns, "dialog", path + ".json"), obj)

    ntag = 0
    for kind, tags in spec.get("tags", {}).items():          # kind: "function" / "dialog"
        for tag, values in tags.items():
            if not _ID_RE.match(tag) or any(not _ID_RE.match(v) for v in values):
                raise ValueError("標籤 %s 的 id 不合法：%r" % (tag, values))
            tns, tpath = tag.split(":", 1)
            _dump(os.path.join(data, tns, "tags", kind, tpath + ".json"),
                  {"replace": False, "values": list(values)})
            ntag += 1

    # 世界高度：區塊照 config.Y_MIN..Y_MAX 寫，遊戲要照同一個範圍讀
    _dump(os.path.join(data, "minecraft", "dimension_type", "overworld.json"),
          overworld_dimension_type())

    return dict(path=root, functions=len(spec["functions"]),
                dialogs=len(spec.get("dialogs", {})), tags=ntag)
