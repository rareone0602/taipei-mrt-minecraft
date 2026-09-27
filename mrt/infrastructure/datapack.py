#!/usr/bin/env python3
"""把資料包規格（application/ride_plan.py 產生的純資料）寫成 MC 26.2 的資料包。

26.2 的資料包佈局（資料夾一律單數，1.21 起改制）:
    <存檔>/datapacks/<名稱>/pack.mcmeta
    <存檔>/datapacks/<名稱>/data/<命名空間>/function/<路徑>.mcfunction
    <存檔>/datapacks/<名稱>/data/<命名空間>/dialog/<路徑>.json
    <存檔>/datapacks/<名稱>/data/<標籤命名空間>/tags/function/<標籤>.json
    <存檔>/datapacks/<名稱>/data/<標籤命名空間>/tags/dialog/<標籤>.json

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

    return dict(path=root, functions=len(spec["functions"]),
                dialogs=len(spec.get("dialogs", {})), tags=ntag)
