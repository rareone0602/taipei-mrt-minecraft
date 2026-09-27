#!/usr/bin/env python3
"""讀回每座觀光景點：蓋出來的高度、輪廓、傳送點、說明牌，跟獨立的資料比。

生成器說台北101 有 508 m，不算數。這支工具只看磁碟：

  · 高度：輪廓範圍內最高的方塊，減掉輪廓外一圈地面的中位數，跟下面 FACTS
    表的公開數字比（誤差 max(2 m, 3%)）。FACTS 是這支工具自己帶的，
    不從生成器拿 —— 生成器寫錯了這裡才抓得到
  · 輪廓：OSM 的主體輪廓（data/attractions.json）裡，頂上有高過地面 3 格的東西的
    比例（蓋在哪裡、有沒有轉錯方向；大廳挖空不影響）；輪廓外擴 FACTS 容許的距離以外、地面 6 格
    以上還有建築的柱子比例（蓋歪、蓋出界）
  · 傳送點：資料包 sight/<id>*.mcfunction 那一行 tp（約定見 ride_plan）落在站得住
    的格子（domain/walk 的規則）；預設觀景點要面向輪廓（偏差 60° 以內）
  · 說明牌：預設觀景點 4 格內有一面牌，第一行是景點中文名、不以「出口」開頭
  · 景點範圍內每面有點擊動作的告示牌，指到的函式都真的在資料包裡

用法:
    ./.venv/bin/python tools/verify_attractions.py <存檔> [--only taipei101 cks_memorial ...]
"""
import argparse
import glob
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from mrt import config
from mrt.domain import geometry as shapes
from mrt.domain import walk
from mrt.infrastructure import savereader as SR

# 公開資料的高度（公尺，地面到最高點）與輪廓檢查的容許值。
# height=None：不驗高度（沒有可靠的公開數字）。cover：輪廓內地面層至少要有多少比例
# 蓋了東西（有中庭、廣場的景點低一點）。spill：輪廓外擴多少公尺以外不該再有建築
# （含台階、廣場、屋簷就大一點）。
FACTS = {
    "taipei101":              dict(height=508.0, cover=0.6, spill=30),   # 塔尖頂端 508 m（2004）
    "shin_kong_tower":        dict(height=244.15, cover=0.6, spill=15),  # 244.15 m（1993）
    "cks_memorial":           dict(height=70.0, cover=0.25, spill=60),   # 紀念堂本體 70 m
    "presidential_office":    dict(height=60.0, cover=0.4, spill=20),    # 中央塔樓 60 m
    "grand_hotel":            dict(height=87.0, cover=0.4, spill=40),    # 87 m（1973）
    "sun_yat_sen_memorial":   dict(height=30.4, cover=0.5, spill=40),    # 30.4 m
    "miramar_wheel":          dict(height=100.0, cover=0.2, spill=40),   # 摩天輪頂離地 100 m
    "national_taiwan_museum": dict(height=30.0, cover=0.5, spill=20),   # 圓頂頂端近 30 m（1915）
    "red_house":              dict(height=None, cover=0.5, spill=15),
    "longshan_temple":        dict(height=None, cover=0.4, spill=20),
    "beimen":                 dict(height=None, cover=0.5, spill=15),
    "dongmen":                dict(height=None, cover=0.5, spill=25),
    "nanmen":                 dict(height=None, cover=0.5, spill=25),
    "xiaonanmen":             dict(height=None, cover=0.5, spill=25),
}
DEFAULT = dict(height=None, cover=0.4, spill=25)

AIRS = ("minecraft:air", "minecraft:cave_air", "minecraft:void_air")
TP_RE = re.compile(r"^tp @s (-?[\d.]+) (-?\d+) (-?[\d.]+) (-?[\d.]+) (-?[\d.]+)$")


def is_air(b):
    return b.split("[")[0] in AIRS


def load_sight_fns(save):
    """資料包裡的 sight 函式：{路徑: (x, y, z, yaw, pitch)}。"""
    root = os.path.join(save, "datapacks", config.DATAPACK_NAME, "data", config.DATAPACK_NS, "function")
    out = {}
    for f in glob.glob(os.path.join(root, "sight", "*.mcfunction")):
        path = "sight/" + os.path.basename(f)[:-len(".mcfunction")]
        tps = [TP_RE.match(ln.strip()) for ln in open(f, encoding="utf-8")]
        tps = [m for m in tps if m]
        if len(tps) != 1:
            out[path] = None
            continue
        x, y, z, yaw, pitch = tps[0].groups()
        out[path] = (float(x), int(y), float(z), float(yaw), float(pitch))
    return out


def all_functions(save):
    root = os.path.join(save, "datapacks", config.DATAPACK_NAME, "data", config.DATAPACK_NS, "function")
    return {os.path.relpath(f, root)[:-len(".mcfunction")].replace(os.sep, "/")
            for f in glob.glob(os.path.join(root, "**", "*.mcfunction"), recursive=True)}


def main_outlines(item):
    rings = []
    for f in item["features"]:
        if f.get("main") and f.get("outer") and f.get("area", 0) > 0:
            rings += [r for r in f["outer"] if len(r) >= 3]
    if not rings:
        blds = [f for f in item["features"] if f.get("outer") and "building" in f["tags"]]
        if blds:
            f = min(blds, key=lambda f: f["dist"] - 0.001 * f["area"])
            rings = [max(f["outer"], key=len)]
    return rings


def check(save, item, fns, funcs, say):
    aid = item["id"]
    fact = FACTS.get(aid, DEFAULT)
    probs = []
    rings = main_outlines(item)
    if not rings:
        return ["資料裡沒有主體輪廓"]
    cells = set()
    for r in rings:
        cells |= shapes.poly_cells(r)
    xs = [c[0] for c in cells]
    zs = [c[1] for c in cells]
    m = int(fact["spill"]) + 24
    x0, z0, x1, z1 = min(xs) - m, min(zs) - m, max(xs) + m, max(zs) + m
    vol = SR.read_volume(save, x0, 40, z0, x1, config.Y_MAX, z1, verbose=False)
    data = vol.data                                    # [y][z][x]
    air = np.array([is_air(n) for n in vol.names])
    solid = ~air[data]
    col_any = solid.any(axis=0)
    top = np.where(col_any, vol.y0 + (vol.ny - 1 - np.argmax(solid[::-1], axis=0)), -999)   # [z][x]

    def T(x, z):
        return int(top[z - z0, x - x0])

    # 地面：輪廓外擴 spill+8 ~ spill+20 那一圈的柱頂中位數（那裡只該是地形）
    fp = np.zeros(top.shape, dtype=bool)
    for x, z in cells:
        fp[z - z0, x - x0] = True
    dist = _chebyshev_from(fp)
    band = (dist > fact["spill"] + 8) & (dist <= fact["spill"] + 20) & col_any
    if not band.any():
        return probs + ["讀不到輪廓外的地面（範圍外沒有區塊？）"]
    ground = int(np.median(top[band]))

    # 高度
    near = dist <= 3
    peak = int(top[near].max()) if near.any() else -999
    h = peak - ground
    if fact["height"] is not None:
        tol = max(2.0, 0.03 * fact["height"])
        ok = abs(h - fact["height"]) <= tol
        say("  %s 高度：最高點 y%d − 地面 y%d = %d m（公開資料 %.1f m，容許 ±%.0f）"
            % ("ok  " if ok else "FAIL", peak, ground, h, fact["height"], tol))
        if not ok:
            probs.append("高度 %d m，公開資料 %.1f m" % (h, fact["height"]))
    else:
        say("  --   高度：最高點 y%d − 地面 y%d = %d m（沒有公開數字可比）" % (peak, ground, h))
        if h < 4:
            probs.append("輪廓上幾乎沒有東西（高 %d m）" % h)

    # 輪廓覆蓋：從上面看，輪廓裡有多少格頂上有東西（高過地面 3 格；大廳挖空不影響）
    cover = float((top[fp] >= ground + 3).mean())
    ok = cover >= fact["cover"]
    say("  %s 輪廓覆蓋：OSM 輪廓 %d 格裡 %.0f%% 頂上有高過地面 3 格的東西（至少 %.0f%%）"
        % ("ok  " if ok else "FAIL", len(cells), cover * 100, fact["cover"] * 100))
    if not ok:
        probs.append("輪廓覆蓋只有 %.0f%%" % (cover * 100))

    # 出界：外擴 spill 以外，地面 6 格以上還有東西的柱子
    tall = top >= ground + 6
    out = tall & (dist > fact["spill"]) & (dist <= fact["spill"] + 20)
    n_out, n_in = int(out.sum()), int((tall & fp).sum())
    spill = n_out / max(1, n_in + n_out)
    ok = spill <= 0.10
    say("  %s 出界：輪廓外 %d m 以外還有 %d 根高過地面 6 格的柱子（%.0f%%，上限 10%%）"
        % ("ok  " if ok else "FAIL", fact["spill"], n_out, spill * 100))
    if not ok:
        probs.append("輪廓外 %d m 以外有 %d 根柱子（蓋歪或出界）" % (fact["spill"], n_out))

    # 傳送點
    mine = {p: v for p, v in fns.items() if p == "sight/" + aid or p.startswith("sight/%s_" % aid)}
    if "sight/" + aid not in mine:
        probs.append("資料包裡沒有 sight/%s" % aid)
        say("  FAIL 資料包裡沒有 sight/%s" % aid)
    cx, cz = sum(xs) / len(xs), sum(zs) / len(zs)
    for path, tp in sorted(mine.items()):
        if tp is None:
            probs.append("%s 不是恰好一行 tp" % path)
            continue
        x, y, z, yaw, pitch = tp
        bx, bz = int(math.floor(x)), int(math.floor(z))
        get = vol.get
        if not (x0 <= bx <= x1 and z0 <= bz <= z1):
            # 高的建築要退遠一點才看得全：觀景點可能在讀回範圍外，另外讀它那一小塊
            get = SR.read_volume(save, bx - 1, y - 2, bz - 1, bx + 1, y + 3, bz + 1, verbose=False).get
        stand = walk.standable(get, bx, y, bz)
        msg = "站得住" if stand else "站不住（腳 %s、頭 %s、腳下 %s）" % (
            get(bx, y, bz), get(bx, y + 1, bz), get(bx, y - 1, bz))
        ok = stand
        if path == "sight/" + aid:
            want = math.degrees(math.atan2(-(cx + 0.5 - x), cz + 0.5 - z))
            dev = abs((yaw - want + 180) % 360 - 180)
            ok = ok and dev <= 60
            msg += "、朝向偏離輪廓中心 %.0f°" % dev
        say("  %s 傳送點 %s (%.1f, %d, %.1f)：%s" % ("ok  " if ok else "FAIL", path, x, y, z, msg))
        if not ok:
            probs.append("%s：%s" % (path, msg))

    # 說明牌與點擊指令
    signs = SR.read_sign_entities(save, x0, z0, x1, z1)
    tp = mine.get("sight/" + aid)
    if tp and not (x0 <= tp[0] <= x1 and z0 <= tp[2] <= z1):
        signs += SR.read_sign_entities(save, int(tp[0]) - 6, int(tp[2]) - 6, int(tp[0]) + 6, int(tp[2]) + 6)
    if tp:
        x, y, z = tp[0], tp[1], tp[2]
        pl = [s for s in signs if abs(s["x"] - x) <= 4.5 and abs(s["z"] - z) <= 4.5 and abs(s["y"] - y) <= 2]
        named = [s for s in pl if s["front"] and s["front"][0].strip() == item["name_zh"]]
        ok = bool(named)
        say("  %s 說明牌：觀景點 4 格內 %d 面牌%s" % (
            "ok  " if ok else "FAIL", len(pl), ("，第一行「%s」" % named[0]["front"][0]) if named else ""))
        if not ok:
            probs.append("觀景點旁沒有寫著「%s」的說明牌" % item["name_zh"])
    ns = config.DATAPACK_NS + ":"
    for s in signs:
        if s["front"] and s["front"][0].startswith("出口") and (x0 + 20 < s["x"] < x1 - 20):
            pass                                         # 範圍內的捷運出口牌，不歸這裡管
        c = s.get("click")
        if not c or c.get("action") != "run_command":
            continue
        cmd = c.get("command", "").lstrip("/")
        mm = re.match(r"^function %s(\S+)$" % re.escape(ns), cmd)
        if mm and mm.group(1) not in funcs:
            probs.append("告示牌 (%d,%d,%d) 指到不存在的函式 %s" % (s["x"], s["y"], s["z"], cmd))
    return probs


def _chebyshev_from(mask):
    """每格到遮罩的切比雪夫距離（遮罩內 = 0）。"""
    d = np.where(mask, 0, 10 ** 6).astype(np.int64)
    cur = mask.copy()
    k = 0
    while not cur.all() and k < 400:
        k += 1
        n = cur.copy()
        n[1:, :] |= cur[:-1, :]
        n[:-1, :] |= cur[1:, :]
        n[:, 1:] |= cur[:, :-1]
        n[:, :-1] |= cur[:, 1:]
        n[1:, 1:] |= cur[:-1, :-1]
        n[:-1, :-1] |= cur[1:, 1:]
        n[1:, :-1] |= cur[:-1, 1:]
        n[:-1, 1:] |= cur[1:, :-1]
        d[n & ~cur] = k
        if (n == cur).all():
            break
        cur = n
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("save")
    ap.add_argument("--only", nargs="*", default=None)
    a = ap.parse_args()
    items = json.load(open(os.path.join(config.DATA, "attractions.json"), encoding="utf-8"))["items"]
    fns = load_sight_fns(a.save)
    funcs = all_functions(a.save)
    bad = {}
    n = 0
    for it in items:
        if a.only and it["id"] not in a.only:
            continue
        print("%s %s %s" % (it["id"], it["name_zh"], it["name_en"]))
        n += 1
        p = check(a.save, it, fns, funcs, print)
        if p:
            bad[it["id"]] = p
    print()
    if bad:
        print("有問題的景點 %d / %d：" % (len(bad), n))
        for k, v in bad.items():
            print("  %s：%s" % (k, "；".join(v)))
        sys.exit(1)
    print("全部 %d 座景點通過" % n)


if __name__ == "__main__":
    main()
