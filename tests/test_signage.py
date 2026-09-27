#!/usr/bin/env python3
"""車站告示牌與路線色（application/signage.py）。

合成的路網，站體與告示牌都真的蓋出來（DictSink）再驗：
  · 搭車告示牌：每個上車位置一面，立在月台門那一排（上面還是月台門玻璃、
    底下踩得住），前面兩格站得住；點擊指令跟 network 的 ride/turn 函式一致；
    牌上寫的下一站就是指令的目的地；每一行都放得進 90 px；發光墨水、淡色木頭
  · 終點站的到站側寫「本站終點」、點了換月台
  · 列車離站的箭頭：島式月台從右往左（←），側式月台從左往右（→）
  · 路線色帶：月台門門楣與軌道外側牆，疊式站兩層都有、共用站體每一側照那一側的線
  · 穿堂：閘門機箱上的雙面牌（正面往月台、背面往出口）、路線圖售票機（打開
    路線圖對話框）、側式站兩座月台樓梯口的方向牌、疊式站層間樓梯口的牌
  · 立了這些東西之後，從非付費區還是走得到每一層月台的警示帶與每一個站位
  · 出口牌：第一行上路線色、發光，純文字跟原本一個字都不差（verify_exits 靠它）
  · 其他牌子的第一行都不是「出口」開頭
  · 斜 45 度的線形也一樣

用法: ./.venv/bin/python tests/test_signage.py
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from mrt import config
from mrt.application import build_exits as BX
from mrt.application import build_line as BL
from mrt.application import signage as SG
from mrt.domain import alignment as AL
from mrt.domain import network as NW
from mrt.domain import stacked as SK
from mrt.domain import walk
from mrt.ports.block_sink import DictSink

ok = True


def chk(name, cond):
    global ok
    print(("  ok   " if cond else "  FAIL ") + name)
    ok = ok and cond


G = 66
COLOURS = {"T": "#007EC7", "S": "#FFD900", "BL": "#007EC7", "G": "#1E7B54", "D": "#FF0000"}
NS = config.DATAPACK_NS


def make_seg(ref, pts, stations, y):
    """stations = [(x 或 (x, z), 站號, 站名, 英文名)]，車站落在最近的取樣點。"""
    samples = AL.resample(pts, ["tunnel"] * len(pts), AL.STEP)
    n = len(samples)
    stn = {}
    for pos, code, name, en in stations:
        px, pz = pos if isinstance(pos, tuple) else (pos, samples[0][1])
        i = min(range(n), key=lambda k: (samples[k][0] - px) ** 2 + (samples[k][1] - pz) ** 2)
        stn[i] = (code, name, en)
    return dict(ref=ref, samples=samples, ys=np.full(n, y), ground=np.full(n, G),
                stn=stn, stn_seq=dict(stn))


def build(segs, net, berths):
    """照 cli 的順序：每座站體先 build_station，再 station_signage。"""
    w = DictSink()
    of = {}
    for b in berths:
        of.setdefault(b.box.key, []).append(b)
    for li, sg in enumerate(segs):
        for i, (full, name, en) in sg["stn"].items():
            under = AL.structure_for_ground(int(sg["ys"][i]), int(sg["ground"][i])) == "tunnel"
            BL.build_station(w, SK.station_samples(sg, i), sg["ys"], i, under,
                             label=(full, name, en), grounds=sg["ground"], access=False,
                             stacked=sg.get("stacked", {}).get(i))
            SG.station_signage(w, of.get((li, i), ()), net, COLOURS, grounds=sg["ground"])
    return w


def ride_signs_ok(w, berths, net, tag):
    """每個站位一面搭車告示牌，位置、指令、文字、樣式都對。"""
    n = bad = 0
    for b in berths:
        for s in b.slots:
            n += 1
            meta = w.sign_meta.get(s.sign)
            text = w.signs.get(s.sign)
            why = []
            if meta is None:
                why.append("沒有牌子")
            else:
                sx, sy, sz = s.sign
                if "pane" not in w.get(sx, sy + 1, sz):
                    why.append(f"上面不是月台門玻璃（{w.get(sx, sy + 1, sz)}）")
                if not walk.is_support(w.get(sx, sy - 1, sz)):
                    why.append("底下踩不住")
                if not walk.standable(w.get, *s.stand):
                    why.append("站位站不住")
                if not (meta["glow"] and meta["wood"] == SG.SIGN_WOOD):
                    why.append("不是發光墨水／淡色木頭")
                if s.dest is not None:
                    to = net[(b.line, s.dest.next)]
                    want = f"function {NS}:{NW.ride_fn(b.station.code, to.code)}"
                    if meta["command"] != want:
                        why.append(f"指令 {meta['command']} != {want}")
                    if s.lang == "zh" and not any(t.endswith(s.dest.next) and "下一站" in t
                                                  for t in text):
                        why.append(f"中文牌沒寫下一站 {s.dest.next}：{text}")
                    if s.lang == "en" and not any(to.en.split(" ")[0] in t for t in text[1:3]):
                        why.append(f"英文牌沒寫下一站 {to.en}：{text}")
                    if not isinstance(meta["lines"][0], dict) or "color" not in meta["lines"][0]:
                        why.append("方向那一行沒有路線色")
                else:
                    want = f"function {NS}:{NW.turn_fn(b.station.code, b.d)}"
                    if meta["command"] != want:
                        why.append(f"終點側指令 {meta['command']} != {want}")
                    if not ("本站終點" in text[0] or "Terminus" in text[0]):
                        why.append(f"終點側沒寫本站終點：{text}")
                wide = [SG.line_width(t) for t in meta["lines"]]
                if max(wide) > SG.SIGN_W:
                    why.append(f"有一行 {max(wide)} px 超過 {SG.SIGN_W}：{text}")
            if why:
                bad += 1
                print(f"      {b} {s}: {'；'.join(why)}")
    chk(f"{tag}：{n} 個站位都有一面搭車告示牌（位置、指令、文字、樣式）", n > 0 and bad == 0)


def no_exit_first_line(w, tag):
    bad = [t for t in w.signs.values() if t and t[0].startswith("出口")]
    chk(f"{tag}：沒有任何牌子的第一行以「出口」開頭", not bad)


def all_fit(w, tag):
    bad = []
    for k, meta in w.sign_meta.items():
        for side in ("lines", "back"):
            for t in (meta.get(side) or ()):
                if SG.line_width(t) > SG.SIGN_W:
                    bad.append((k, t))
    chk(f"{tag}：{len(w.sign_meta)} 面牌子的每一行（含背面）都放得進 {SG.SIGN_W} px", not bad)
    for b in bad[:4]:
        print("     ", b)


def yellow_reached(w, dist):
    return {(x, y + 1, z) for (x, y, z), blk in w.blocks.items()
            if blk == BL.YELLOW and (x, y + 1, z) in dist}


def signs_with(w, pred):
    return [(k, w.signs[k], m) for k, m in w.sign_meta.items() if pred(w.signs[k], m)]


# ================================================================ 直線地下線
print("直線地下線：甲—乙—丙，島式月台")
line = make_seg("T", [(0, 0), (3000, 0)],
                [(500, "T01", "甲", "Jia"), (1500, "T02", "乙", "Yi"),
                 (2500, "T03", "丙", "Bing")], 40)
segs = [line]
net, berths = NW.plan_berths(segs)
w = build(segs, net, berths)
ride_signs_ok(w, berths, net, "島式站")
bidx = NW.berth_index(berths)
b = bidx[("T", "乙", 1)]
s0 = b.slots[0]
t = w.signs[s0.sign]
chk(f"乙往丙的中文牌：{t}", t[0] == "← 往 丙" and t[1] == "下一站 丙" and t[2] == "T02 乙"
    and "搭車" in t[3])
chk("島式月台：列車從右往左開（箭頭 ←）", SG.travel_arrow(b) == "←")
t = w.signs[b.slots[1].sign]
chk(f"乙往丙的英文牌：{t}", t[0] == "← To Bing" and t[1] == "Next: Bing" and t[2] == "T02 Yi")
end = bidx[("T", "丙", 1)]
t = w.signs[end.slots[0].sign]
chk(f"丙的到站側：本站終點、請至對面、搭往甲（{t}）",
    t[0] == "本站終點" and t[1] == "請至對面月台" and t[2] == "搭往 甲")
chk("丙的到站側點了換到對面月台（turn/t03_p）",
    w.sign_meta[end.slots[0].sign]["command"] == f"function {NS}:turn/t03_p")
# 門楣與外牆色帶
box = b.box
blk = SG.band_block("T", COLOURS)
chk(f"板南線色 #007EC7 -> {blk}", blk == "minecraft:light_blue_concrete")
mid = (box.lo + box.hi) // 2
hx, hz = box.cell(mid, AL.PLAT_HALF)
chk("月台門最上面一排是路線色門楣", w.get(hx, 40 + 5, hz) == blk)
chk("門楣底下還是月台門（玻璃或門洞）", w.get(hx, 40 + 4, hz) in (BL.PSD, BL.AIR))
wx, wz = box.cell(mid, AL.BOX_HALF - 1)
chk("軌道外側牆在人眼高度砌兩排路線色", w.get(wx, 43, wz) == blk and w.get(wx, 44, wz) == blk)
wx, wz = box.cell(mid, -(AL.BOX_HALF - 1))
chk("另一側的牆也是", w.get(wx, 43, wz) == blk and w.get(wx, 44, wz) == blk)
ix, iz = box.cell(mid, AL.BOX_HALF - 2)
chk("色帶沒有凸進站內（±10 那一格還是空的）", w.get(ix, 43, iz) == BL.AIR)
# 穿堂
ym = 40 + AL.LEVEL_DY["tunnel"]
gates = signs_with(w, lambda t, m: t[0].startswith("往月台") and abs(m.get("facing", (0, 0))[0] + 1) < 1e-6
                   and m.get("back"))
per_st = {}
for k, t, m in gates:
    per_st.setdefault(round(k[0] / 1000), []).append((k, t, m))
chk(f"每座車站的閘門列上兩面雙面牌（{ {k: len(v) for k, v in per_st.items()} }）",
    len(per_st) == 3 and all(len(v) == 2 for v in per_st.values()))
k, t, m = next(g for g in gates if 1400 < g[0][0] < 1600)
chk(f"閘門牌立在機箱上、人眼高度（{k}，底下 {w.get(k[0], k[1] - 1, k[2])}）",
    k[1] == ym + 1 and w.get(k[0], k[1] - 1, k[2]) == BL.GATE)
chk(f"閘門牌正面：往月台、路線、兩個方向（{t}）",
    "往月台" in t[0] and "T" in t[1] and "甲" in t[2] and "丙" in t[2])
chk(f"閘門牌背面朝付費區：往出口（{m['back']}）", m["back"][0].startswith("往出口") and m["back"][1] == "乙")
chk("閘門牌正面朝非付費區（面向 −u）", m["facing"][0] < -0.99)
maps = signs_with(w, lambda t, m: m.get("dialog"))
chk(f"每座車站一台路線圖售票機（{len(maps)} 台）", len(maps) == 3)
k, t, m = next(g for g in maps if 1400 < g[0][0] < 1600)
chk(f"點了打開路線圖對話框（{m['dialog']}）", m["dialog"] == f"{NS}:{NW.MENU_DIALOG}")
chk("售票機在非付費區（lo+10 m、閘門之前）",
    box.samples[box.lo][0] < k[0] < box.samples[box.lo + 14 * 2][0])
chk("售票機的牌子立在機台上", w.get(k[0], k[1] - 1, k[2]) == BL.GATE)
# 走得到
start = (int(round(box.samples[box.lo + 4][0])), ym, int(round(box.samples[box.lo + 4][1])))
chk("非付費區站得住", walk.standable(w.get, *start))
dist, _ = walk.flood(w.get, [start])
yel = yellow_reached(w, dist)
n_yel = sum(1 for (x, y, z), bb in w.blocks.items() if bb == BL.YELLOW
            and box.samples[box.lo][0] <= x <= box.samples[box.hi][0])
chk(f"從非付費區走得到整座月台的警示帶（{len([c for c in yel if 1400 < c[0] < 1600])}/{n_yel}）",
    len([c for c in yel if 1400 < c[0] < 1600]) == n_yel)
chk("每一個站位都走得到", all(s.stand in dist for bb in berths if bb.station.name == "乙"
                         for s in bb.slots))
no_exit_first_line(w, "島式站")
all_fit(w, "島式站")
# 彎道上門洞的取樣點會取整到牌子那一格（台北車站的淡水信義線）：假裝那一柱是門洞，
# 立牌之後上面兩格要補回玻璃
b = bidx[("T", "乙", -1)]
sx, sy, sz = b.slots[0].sign
for yy in range(sy, sy + 4):
    w.set(sx, yy, sz, BL.AIR)
SG.ride_signs(w, [b], net, COLOURS)
chk("牌子那一柱原本是門洞的話，立牌時補回玻璃（島式：牌子上面兩格）",
    w.get(sx, sy + 1, sz) == BL.PSD and w.get(sx, sy + 2, sz) == BL.PSD and "sign" in w.get(sx, sy, sz))

# ================================================================ 高架側式
print("\n高架側式站：軌面比地面高 20 m（橋下穿堂）")
sky = make_seg("S", [(0, 0), (3000, 0)],
               [(500, "S01", "戊", "Wu"), (1500, "S02", "己", "Ji"),
                (2500, "S03", "庚", "Geng")], G + 20)
net, berths = NW.plan_berths([sky])
w = build([sky], net, berths)
ride_signs_ok(w, berths, net, "側式站")
b = NW.berth_index(berths)[("S", "己", 1)]
chk("側式月台：列車從左往右開（箭頭 →）", SG.travel_arrow(b) == "→")
t = w.signs[b.slots[0].sign]
chk(f"側式站中文牌：{t}", t[0] == "往 庚 →" and t[1] == "下一站 庚")
box = b.box
blk = SG.band_block("S", COLOURS)
chk(f"環狀線黃 #FFD900 的色帶不是黃色混凝土（{blk}）", blk != BL.YELLOW and "yellow" in blk)
mid = (box.lo + box.hi) // 2
hx, hz = box.cell(mid, AL.PLAT_HALF - 1)
chk("側式站月台門的門楣（+4）", w.get(hx, G + 20 + 4, hz) == blk)
kind = SG.concourse_kind(box, sky["ground"])
ym = G + 20 + AL.LEVEL_DY[kind]
stair_signs = [(k, t, m) for k, t, m in signs_with(w, lambda t, m: True)
               if 1400 < k[0] < 1600 and k[1] == ym and not m.get("dialog")]
chk(f"穿堂兩座月台樓梯口各一面方向牌（{[t[0] for k, t, m in stair_signs]}）",
    len(stair_signs) == 2 and {("庚" in t[0]) for k, t, m in stair_signs} == {True, False})
for k, t, m in stair_signs:
    side = 1 if k[2] > 0 else -1
    want = "庚" if side > 0 else "戊"
    chk(f"  {'+' if side > 0 else '−'} 側樓梯口寫往{want}（{t}）", want in t[0] and "下一站" in t[2])
start = (int(round(box.samples[box.lo + 4][0])), ym, int(round(box.samples[box.lo + 4][1])))
chk("橋下穿堂的非付費區站得住", walk.standable(w.get, *start))
dist, _ = walk.flood(w.get, [start])
yel = [c for c in yellow_reached(w, dist) if 1400 < c[0] < 1600]
chk(f"從非付費區走得到兩座側式月台（{len({c[2] > 0 for c in yel})} 座）",
    {c[2] > 0 for c in yel} == {True, False})
chk("每一個站位都走得到", all(s.stand in dist for bb in berths if bb.station.name == "己"
                         for s in bb.slots))
no_exit_first_line(w, "側式站")
all_fit(w, "側式站")
b = NW.berth_index(berths)[("S", "己", -1)]
sx, sy, sz = b.slots[0].sign
for yy in range(sy, sy + 3):
    w.set(sx, yy, sz, BL.AIR)
SG.ride_signs(w, [b], net, COLOURS)
chk("側式站：門洞那一柱補回玻璃（牌子上面那一格）", w.get(sx, sy + 1, sz) == BL.PSD)
# 牌子底下那一格：真的是門洞才補；是月台面（斜線上取整撞在一起）就不動
box = b.box
slot_cells = {(s.sign[0], s.sign[2]) for bb in berths for s in bb.slots}
yb = G + 20 + 1
row = {box.cell(i, sd * (AL.PLAT_HALF - 1)) for i in range(box.lo + 1, box.hi)
       for sd in (1, -1)} - slot_cells
agree = [(w.get(c[0], yb, c[1]) == BL.AIR) == SG._side_below_is_door(box, c) for c in row]
n_door = sum(1 for c in row if w.get(c[0], yb, c[1]) == BL.AIR)
plat_cells = [box.cell(i, -(AL.PLAT_HALF + 1)) for i in range(box.lo + 2, box.hi - 2)]
chk(f"側式站：月台門那一排（+1）哪一格是門洞，重跑的結果跟蓋出來的一致"
    f"（{len(row)} 格、門洞 {n_door}），月台格不算門洞",
    all(agree) and n_door > 0 and not any(SG._side_below_is_door(box, c) for c in plat_cells))

# ================================================================ 共用疊式站
print("\n共用島式疊式站（西門那種）：板南線在 z=0、松山新店線在 z=17")
# 兩條線只差 17 m，鄰站錯開 200 m，免得兩座一般站體疊在一起（那是合成路網的假象）
bl = make_seg("BL", [(0, 0), (3000, 0)],
              [(500, "BL10", "龍山寺", "Longshan Temple"), (1500, "BL11", "西門", "Ximen"),
               (2500, "BL12", "台北車站", "Taipei Main Station")], 48)
gl = make_seg("G", [(0, 17), (3000, 17)],
              [((300, 17), "G11", "小南門", "Xiaonanmen"), ((1500, 17), "G12", "西門", "Ximen"),
               ((2700, 17), "G13", "北門", "Beimen")], 48)
bi = next(i for i, v in bl["stn"].items() if v[1] == "西門")
pbi = next(i for i, v in gl["stn"].items() if v[1] == "西門")
j_to = next(i for i, v in bl["stn"].items() if v[1] == "台北車站")
pj_to = next(i for i, v in gl["stn"].items() if v[1] == "北門")
SK.plan_shared(bl, bi, SK.direction_sign(bi, j_to), gl, pbi, SK.direction_sign(pbi, pj_to))
net, berths = NW.plan_berths([bl, gl])
w = build([bl, gl], net, berths)
ride_signs_ok(w, berths, net, "疊式站兩層")
bidx = NW.berth_index(berths)
box = bidx[("BL", "西門", 1)].box
mid = (box.lo + box.hi) // 2
c_bl, c_g = SG.band_block("BL", COLOURS), SG.band_block("G", COLOURS)
chk(f"兩條線的色帶不同（{c_bl} / {c_g}）", c_bl != c_g)
ok_levels = True
for dy0 in (0, -SK.LEVEL_H):
    y = 48 + dy0
    for sd, want in ((-box.side, c_bl), (box.side, c_g)):
        hx, hz = box.cell(mid, sd * AL.PLAT_HALF)
        wx, wz = box.cell(mid, sd * (AL.BOX_HALF - 1))
        if not (w.get(hx, y + 5, hz) == want and w.get(wx, y + 3, wz) == want):
            ok_levels = False
            print(f"      dy0={dy0} 側 {sd}: 門楣 {w.get(hx, y + 5, hz)} 外牆 {w.get(wx, y + 3, wz)}")
chk("上下兩層：板南線那一側是板南線色、松山新店線那一側是松山新店線色", ok_levels)
ym = 48 + AL.LEVEL_DY["tunnel"]
gates = [(k, t, m) for k, t, m in signs_with(w, lambda t, m: t[0].startswith("往月台"))
         if 1400 < k[0] < 1600]
chk(f"閘門上每條線一面（{[t[1] for k, t, m in gates]}）",
    len(gates) == 2 and {t[1] for k, t, m in gates} == {"板南線 BL", "松山新店線 G"})
for k, t, m in gates:
    x, z = k[0], k[2]
    _, off = (x - box.samples[mid][0]), z - box.samples[mid][1]
    want = -box.side if "BL" in t[1] else box.side
    chk(f"  {t[1]} 的閘門牌在自己月台那一側（離線位 {off:+.0f}）", off * want > 0)
    chk(f"  {t[1]}：{t[2]}", ("頂埔" in t[2] or "龍山寺" in t[2] or "新店" in t[2] or "小南門" in t[2]))
lv = [(k, t) for k, t, m in signs_with(w, lambda t, m: "層月台" in t[0]) if 1400 < k[0] < 1600]
chk(f"層間樓梯口兩面：上層往下層、下層往上層（{[t[0] for k, t in lv]}）",
    sorted(k[1] for k, t in lv) == [48 + 2 - SK.LEVEL_H, 48 + 2]
    and any("下層" in t[0] and k[1] == 50 for k, t in lv)
    and any("上層" in t[0] and k[1] == 50 - SK.LEVEL_H for k, t in lv))
k_up = next(k for k, t in lv if k[1] == 50)
t_up = next(t for k, t in lv if k[1] == 50)
chk(f"上層那面列出下層的方向（{t_up[2:]}）",
    any("龍山寺" in x or "頂埔" in x for x in t_up) and any("小南門" in x or "新店" in x for x in t_up))
chk("上層那面底下是月台（不是樓梯洞）", walk.is_support(w.get(k_up[0], 49, k_up[2])))
start = (int(round(box.samples[box.lo + 4][0])), ym, int(round(box.samples[box.lo + 4][1])))
chk("疊式站穿堂的非付費區站得住", walk.standable(w.get, *start))
dist, _ = walk.flood(w.get, [start])
lvls = sorted({c[1] for c in yellow_reached(w, dist) if 1400 < c[0] < 1600})
chk(f"立了牌子之後從非付費區還是走得到兩層月台（{lvls}）", lvls == [50 - SK.LEVEL_H, 50])
chk("每一個站位都走得到", all(s.stand in dist for bb in berths if bb.station.name == "西門"
                         for s in bb.slots))
no_exit_first_line(w, "疊式站")
all_fit(w, "疊式站")

# ================================================================ 側式疊式站
print("\n側式疊式站（府中那種）")
fz = make_seg("D", [(0, 0), (3000, 0)],
              [(500, "D01", "子", "Zi"), (1500, "D02", "丑", "Chou"),
               (2500, "D03", "寅", "Yin")], 48)
bi = next(i for i, v in fz["stn"].items() if v[1] == "丑")
SK.plan_side(fz, bi, +1, "left")
net, berths = NW.plan_berths([fz])
w = build([fz], net, berths)
ride_signs_ok(w, berths, net, "側式疊式站")
box = NW.berth_index(berths)[("D", "丑", 1)].box
dist, _ = walk.flood(w.get, [(int(round(box.samples[box.lo + 4][0])), ym,
                              int(round(box.samples[box.lo + 4][1])))])
lvls = sorted({c[1] for c in yellow_reached(w, dist) if 1400 < c[0] < 1600})
chk(f"從非付費區走得到兩層月台（{lvls}）", lvls == [50 - SK.LEVEL_H, 50])
lv = [(k, t) for k, t, m in signs_with(w, lambda t, m: "層月台" in t[0]) if 1400 < k[0] < 1600]
chk(f"層間樓梯口兩面（{[t for k, t in lv]}）", len(lv) == 2)
mid = (box.lo + box.hi) // 2
wx, wz = box.cell(mid, -box.side * (AL.BOX_HALF - 1))
px, pz = box.cell(mid, box.side * (AL.BOX_HALF - 1))
blk = SG.band_block("D", COLOURS)
chk(f"色帶砌在軌道那一側的牆（{blk}），月台背後那面牆不砌",
    w.get(wx, 51, wz) == blk and w.get(wx, 51 - SK.LEVEL_H, wz) == blk and w.get(px, 51, pz) != blk)
all_fit(w, "側式疊式站")

# ================================================================ 斜 45 度
print("\n斜 45 度的地下線")
k = 1 / math.sqrt(2)
diag = make_seg("T", [(0, 0), (3000 * k, 3000 * k)],
                [((500 * k, 500 * k), "T01", "甲", "Jia"), ((1500 * k, 1500 * k), "T02", "乙", "Yi"),
                 ((2500 * k, 2500 * k), "T03", "丙", "Bing")], 40)
net, berths = NW.plan_berths([diag])
w = build([diag], net, berths)
ride_signs_ok(w, berths, net, "斜線島式站")
box = NW.berth_index(berths)[("T", "乙", 1)].box
inner = {box.cell(i, o) for i in range(box.lo, box.hi + 1) for o in range(-10, 11)}
blk = SG.band_block("T", COLOURS)
leak = [(x, z) for (x, y, z), bb in w.blocks.items() if bb == blk and y in (43, 44) and (x, z) in inner]
chk(f"斜線上色帶也沒有凸進站內（{len(leak)} 格）", not leak)
ym = 40 + AL.LEVEL_DY["tunnel"]
start = walk.nearest_standable(w.get, *[int(round(v)) for v in box.samples[box.lo + 6][:2]][:1],
                               ym, int(round(box.samples[box.lo + 6][1])), radius=3, dy=1)
dist, _ = walk.flood(w.get, [start])
chk("斜線上從非付費區走得到每一個站位", all(s.stand in dist for bb in berths
                                    if bb.station.name == "乙" for s in bb.slots))
gates = [kk for kk, t, m in signs_with(w, lambda t, m: t[0].startswith("往月台"))
         if box.samples[box.lo][0] < kk[0] < box.samples[box.hi][0]]
chk(f"斜線上閘門牌也立在機箱上（{len(gates)} 面）",
    len(gates) == 2 and all(w.get(x, y - 1, z) == BL.GATE for x, y, z in gates))
all_fit(w, "斜線")
for ang in (30, 45, 60):
    ca, sa = math.cos(math.radians(ang)), math.sin(math.radians(ang))
    dsky = make_seg("S", [(0, 0), (3000 * ca, 3000 * sa)],
                    [((500 * ca, 500 * sa), "S01", "戊", "Wu"), ((1500 * ca, 1500 * sa), "S02", "己", "Ji"),
                     ((2500 * ca, 2500 * sa), "S03", "庚", "Geng")], G + 20)
    net, berths = NW.plan_berths([dsky])
    w0 = DictSink()
    for i, (full, name, en) in dsky["stn"].items():
        BL.build_station(w0, SK.station_samples(dsky, i), dsky["ys"], i, False,
                         label=(full, name, en), grounds=dsky["ground"], access=False)
    w = build([dsky], net, berths)
    y0 = {k for k, v in w0.blocks.items() if v == BL.YELLOW}
    y1 = {k for k, v in w.blocks.items() if v == BL.YELLOW}
    ride_signs_ok(w, berths, net, f"斜 {ang} 度側式站")
    chk(f"斜 {ang} 度側式站：立牌沒有挖掉任何一格警示帶（{len(y0)} -> {len(y1)}）", y0 == y1)

# ================================================================ 出口牌
print("\n出口牌")
lines = BX.sign_lines(["2"], "乙", "Yi")
styled = SG.exit_sign_lines(lines, "#FFD900")
chk(f"第一行上路線色（調暗過）、純文字不變（{styled[0]}）",
    isinstance(styled[0], dict) and styled[0]["text"] == lines[0] == "出口 2"
    and styled[0]["color"] != "#FFD900" and styled[1:] == lines[1:])
well = BX.make_well(dict(x0=100, z0=100, ux=1, uz=0, g0=G, y_to=G - 12), styled, SG.SIGN_STYLE)
w = DictSink()
well.build(w)
(k, t), = list(w.signs.items())
m = w.sign_meta[k]
chk(f"出口井的牌子：{t}", t == ["出口 2", "乙", "Yi", "Exit 2"] and m["glow"]
    and m["wood"] == SG.SIGN_WOOD and m["lines"][0]["color"] == styled[0]["color"])
gate = BX.make_gate(dict(x0=0, z0=0, ux=1, uz=0, g0=G, y_to=G + 1), styled, SG.SIGN_STYLE)
w = DictSink()
gate.build(w)
(k, t), = list(w.signs.items())
chk(f"平面出入口的牌子也是（{t}）", t[0] == "出口 2" and w.sign_meta[k]["glow"])

# ================================================================ 字色與文字
print("\n字色與文字")
cols = NW.line_colours(json.load(open(config.MC_LINES_JSON, encoding="utf-8")))
low = {ref: round(SG.contrast(SG._rgb(SG.ink(c))), 2) for ref, c in cols.items()
       if SG.contrast(SG._rgb(SG.ink(c))) < SG.MIN_CONTRAST}
chk(f"每條線的字色在淡色木板上的對比都 ≥ {SG.MIN_CONTRAST}", not low)
chk(f"環狀線黃調暗了（{cols['Y']} -> {SG.ink(cols['Y'])}）", SG.ink(cols["Y"]) != cols["Y"])
chk(f"板南線藍夠深，原樣（{SG.ink(cols['BL'])}）", SG.ink(cols["BL"]) == cols["BL"])
bands = {ref: SG.band_block(ref, cols) for ref in cols}
chk(f"色帶方塊沒有一條是黃色混凝土（警示帶）：{bands}", BL.YELLOW not in bands.values())
chk("淡水信義線紅、中和新蘆線橘", bands["R"] == "minecraft:red_concrete"
    and bands["O"] == "minecraft:orange_concrete")
forms = SG.en_forms("Taipei Nangang Exhibition Center")
chk(f"南港展覽館的英文縮寫不會縮成南港（{forms}）", "Nangang" not in forms)
chk("所有縮寫都比原名短", all(len(f) <= len(forms[0]) for f in forms))
chk("放不下的截短補「…」", SG.fit(["X" * 40]).endswith("…")
    and SG.text_width(SG.fit(["X" * 40])) <= SG.SIGN_W)
chk("中文八個字加前綴放得下", SG.text_width("下一站 南港軟體園區") <= SG.SIGN_W)

print("\n" + ("全部通過" if ok else "有測試失敗"))
sys.exit(0 if ok else 1)
