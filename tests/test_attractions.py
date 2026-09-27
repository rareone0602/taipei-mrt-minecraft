#!/usr/bin/env python3
"""觀光景點的共用框架（application/attractions/）。

各景點自己的長相由各自的測試檔驗（tests/test_attr_*.py）；這裡驗大家共用的東西：
  · Frame：任何角度的矩形反向光柵化都不漏格、面積對、局部與世界座標互轉一致
  · 屋頂高度場：簷口為 0、屋脊最高、歇山的山花、八角攢尖的對稱、起翹只在角落
  · Guard：禁區不寫、有記數；說明牌第一行不准以「出口」開頭
  · 資料包：sight 函式恰好一行 tp、按鈕的 trigger 值接在站名後面、主選單有景點按鈕
  · 登錄表：每座景點都有類別（沒有專屬模組的退回 OsmMassing），id 不重複

用法: ./.venv/bin/python tests/test_attractions.py
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from mrt.application import attractions as AT
from mrt.application.attractions import kit
from mrt.ports.block_sink import DictSink

ok = True


def chk(name, cond):
    global ok
    print(("  ok   " if cond else "  FAIL ") + name)
    ok = ok and cond


def holes(mask):
    """遮罩裡被四鄰包圍、自己卻是 False 的格子數（反向光柵化不該有）。"""
    m = mask
    inner = np.zeros_like(m)
    inner[1:-1, 1:-1] = (m[:-2, 1:-1] & m[2:, 1:-1] & m[1:-1, :-2] & m[1:-1, 2:]) & ~m[1:-1, 1:-1]
    return int(inner.sum())


print("Frame：旋轉的矩形")
for deg in (0, 7, 30, 45, 62, 90, 133):
    fr = kit.Frame(100.3, -50.7, math.radians(deg), 40)
    m = fr.box(20, 10)
    area = int(m.sum())
    chk(f"{deg:>3}°：半長 20、半寬 10 -> {area} 格（面積 800）、沒有破洞",
        abs(area - 800) <= 40 and holes(m) == 0)
fr = kit.Frame(10, 20, math.radians(30), 30)
x, z = fr.world(5, -3)
u, v = fr.local(int(math.floor(x)), int(math.floor(z)))
chk("局部 -> 世界 -> 局部 誤差在一格內", abs(u - 5) <= 1 and abs(v + 3) <= 1)
chk("u 軸 = angle：30° 的 (1,0) 是世界 (cos30, sin30)",
    all(abs(a - b) < 1e-9 for a, b in zip(fr.dir(1, 0), (math.cos(math.radians(30)), math.sin(math.radians(30))))))
fr0 = kit.Frame(0, 0, 0.0, 20)
chk("angle=0 時 v 軸是 +z（南）", fr0.dir(0, 1) == (0.0, 1.0) and fr0.facing(0, 1) == "south")
fo = kit.Frame(0.5, 0.5, 0.0, 20)
oct_ = fo.ngon(8, 10)
pts = set(zip(fo.U[oct_].round(3).tolist(), fo.V[oct_].round(3).tolist()))
# 格心剛好落在邊上的也算進去，格數比面積多大約半圈周長（Pick 定理）
chk("邊心距 10 的八角形（面積 331 m2、%d 格）、左右上下對稱" % oct_.sum(),
    abs(int(oct_.sum()) - 331) <= 40 and pts == {(-u, -v) for u, v in pts} == {(v, u) for u, v in pts})
chk("ring 是外圈、erode 之後沒有外圈",
    kit.ring(fr0.box(5, 5)).sum() == 36 and not (kit.erode(fr0.box(5, 5)) & kit.ring(fr0.box(5, 5))).any())

print("\n屋頂高度場")
fr = kit.Frame(0, 0, 0.0, 30)
h = kit.hip(fr, 20, 10, 8, profile=1.5)
box = fr.box(20, 10)
chk("廡殿：簷口 0、屋脊約 8（格心離屋脊半格）",
    abs(h[box].min()) < 0.8 and 7.0 < h[box].max() <= 8.0)
ridge = h[fr.box(8, 0.6)]
chk("廡殿的屋脊沿 u 方向（中線一整段都是最高）", ridge.min() >= h[box].max() - 1e-9)
hg = kit.hip_gable(fr, 20, 10, 8, gable_in=6)
end_mid = float(hg[fr.box(0.5, 0.5, du=13)].max())
chk("歇山：山花（離端點 6 m）內側，中線高度跟長坡一樣到屋脊",
    end_mid >= float(h[box].max()) - 1e-9)
chk("歇山：端點的小坡比廡殿高（山花豎起來了）", float(hg[fr.box(0.5, 0.5, du=16)].max()) > float(h[fr.box(0.5, 0.5, du=16)].max()))
pl = kit.pyramid(fr, 10, 12, sides=8, profile=1.3)
chk("八角攢尖：中心最高約 12、簷口 0", 10.5 < float(pl.max()) <= 12 and float(pl[fr.ngon(8, 10) & ~fr.ngon(8, 9)].min()) < 1.5)
hl = kit.hip(fr, 20, 10, 8, profile=1.5, lift=2.0)
corner = fr.box(0.6, 0.6, du=19.5, dv=9.5)
side_mid = fr.box(0.6, 0.6, du=0, dv=9.5)
chk("起翹：角落的簷口比簷口中段高將近 2 m",
    float(hl[corner].max() - h[corner].max()) > 1.2 and float(hl[side_mid].max() - h[side_mid].max()) < 0.2)

print("\nGuard 與 Painter")
w = DictSink()
g = kit.Guard(w, keep=lambda x, y, z: x == 0)
p = kit.Painter(g, kit.Frame(0.5, 0.5, 0.0, 3))
p.fill(p.fr.box(2, 2), 64, 65, "minecraft:stone")
chk("禁區那一排不寫、其他照寫", all(k[0] != 0 for k in w.blocks) and len(w.blocks) > 0 and g.dropped > 0)
w = DictSink()
p = kit.Painter(w, kit.Frame(0, 0, 0.0, 10))
p.heightfield(p.fr.box(3, 3), 70, np.full(p.fr.shape, 2.6), "minecraft:bricks", slab="minecraft:brick_slab")
chk("heightfield：小數 >= 0.5 的地方頂上加半磚",
    any(v.startswith("minecraft:brick_slab") for v in w.blocks.values()))


class Fake(kit.Attraction):
    def plaque(self):
        return ["出口 1", "Exit", "", ""]


print("\n說明牌與資料包")
try:
    AT.plaque_lines(Fake(dict(id="x", name_zh="出口", name_en="x")))
    chk("說明牌第一行以「出口」開頭會被擋下", False)
except ValueError:
    chk("說明牌第一行以「出口」開頭會被擋下", True)
a = kit.Attraction(dict(id="cks_memorial", name_zh="中正紀念堂", name_en="Chiang Kai-shek Memorial Hall"))
a.station = ("中正紀念堂", "R08;G10", 350.0, "Chiang Kai-shek Memorial Hall")
front, back = AT.plaque_lines(a)
from mrt.application import signage as SG
chk("說明牌：英文名太長斷成兩行、每行放得下（%s）" % [kit_t if isinstance(kit_t, str) else kit_t["text"] for kit_t in front],
    all(SG.line_width(t) <= SG.SIGN_W for t in front) and len(front) == 4)
chk("說明牌第四行是走得到的捷運站", "中正紀念堂站" in str(front[3]))
chk("sight 函式路徑", kit.sight_fn("taipei101") == "sight/taipei101"
    and kit.sight_fn("taipei101", "top") == "sight/taipei101_top")

from mrt.application import ride_plan as RP
from mrt.domain import network as NW
entries = [dict(id="beimen", name_zh="北門", name_en="North Gate", station=("北門", "G13", 200, "Beimen"),
                facts=["1884 年"], spots=[kit.Spot("", 1, 66, 2, 0.0, -10.0, "北門", "North Gate")._asdict()]),
           dict(id="taipei101", name_zh="台北101", name_en="Taipei 101", station=None, facts=["508 m"],
                spots=[kit.Spot("", 10, 70, 20, 90.0, -30.0, "台北101", "Taipei 101")._asdict(),
                       kit.Spot("top", 12, 452, 22, 0.0, 10.0, "89 樓觀景台", "89F Observatory")._asdict()])]
spec = RP.build_spec({}, [], {}, sights=entries)
fns = spec["functions"]
tp_lines = {k: [ln for ln in v if ln.startswith("tp ")] for k, v in fns.items() if k.startswith("sight/")}
chk("每個傳送點一個 sight 函式、恰好一行 tp（%s）" % sorted(tp_lines),
    sorted(tp_lines) == ["sight/beimen", "sight/taipei101", "sight/taipei101_top"]
    and all(len(v) == 1 for v in tp_lines.values()))
chk("tp 行是方塊中心：tp @s 1.5 66 2.5 0.0 -10.0", tp_lines["sight/beimen"] == ["tp @s 1.5 66 2.5 0.0 -10.0"])
chk("景點按鈕的 trigger 值 1..2（沒有車站時從 1 開始）、指到預設觀景點",
    spec["triggers"] == {1: "sight/beimen", 2: "sight/taipei101"})
menu = spec["dialogs"][NW.MENU_DIALOG]
chk("主選單有「觀光景點」按鈕打開 mrt:sights",
    any(a_.get("action", {}).get("dialog") == "mrt:sights" for a_ in menu["actions"]) and "sights" in spec["dialogs"])
chk("景點清單的按鈕是 trigger mrt.go set n",
    [a_["action"]["command"] for a_ in spec["dialogs"]["sights"]["actions"]] == ["trigger mrt.go set 1", "trigger mrt.go set 2"])
chk("sys/go_dispatch 有景點的分派", any("sight/taipei101" in ln for ln in fns["sys/go_dispatch"]))

e = entries[0]
sl = SG.sight_lines(e)
chk("穿堂景點牌：★ 開頭、每行放得下、不以「出口」開頭（%s）" % [t if isinstance(t, str) else t["text"] for t in sl],
    all(SG.line_width(t) <= SG.SIGN_W for t in sl) and sl[0]["text"].startswith("★")
    and not str(sl[0]["text"]).startswith("出口"))
chk("穿堂景點牌點了執行 function mrt:sight/beimen", SG.sight_command(e) == "function mrt:sight/beimen")
dlg = RP.build_spec({}, [], {}, sights=entries)["dialogs"]
chk("沒有車站時站表對話框不受影響（只有主選單與景點清單）", sorted(dlg) == ["network", "sights"])

print("\n登錄表")
reg = AT.registry()
items = AT.load_items()
chk("data/attractions.json 有 14 座景點", len(items) == 14)
chk("id 都是資料包路徑可用的字元", all(all(c.isalnum() and c.islower() or c.isdigit() or c == "_" for c in it["id"]) for it in items))
objs = AT.for_world([], items=items)
chk("每座都有類別可蓋（%d 座專屬、其餘退回 OsmMassing）" % sum(1 for o in objs if type(o) is not AT.OsmMassing),
    len(objs) == len(items))
chk("每座的 bbox 合理（邊長 10～1200 m）",
    all(10 <= o.bbox()[2] - o.bbox()[0] <= 1200 and 10 <= o.bbox()[3] - o.bbox()[1] <= 1200 for o in objs))

print("\n" + ("全部通過" if ok else "有測試失敗"))
sys.exit(0 if ok else 1)
