#!/usr/bin/env python3
"""臺北府城四座城門（city_gates.py）與艋舺龍山寺（longshan_temple.py）。

不產生存檔：DictSink ＋ 平地 Site(y66) 蓋一次，驗：
  · 城門：位置在 OSM 城門輪廓上（東門、南門、小南門不信目錄中心點）；城座蓋滿輪廓；
    門洞從城外走得到城內（walk 的規則）、不會挖穿城座頂；有屋頂、高度合理；
    門額與說明牌；觀景點站得住、面向城門、不在整地範圍裡
  · 北門：紅牆、紅瓦、二方一圓的窗洞在北面（城外）
  · 宮殿式三門：綠琉璃瓦、紅柱、白雉堞；小南門背面紅磚欄杆
  · 龍山寺：正殿重簷（下簷、上簷兩層瓦）比前殿高、中庭是空的、從廟埕穿過前殿
    的門走得到中庭、兩座水池有水、兩個觀景點站得住
  · 共同：plan 之後不再查地面（cli 在 plan_all 之後就丟掉地形距離場）；沒有黃色混凝土（月台警示帶專用）、樓梯朝向是四個正方位、
    告示牌第一行不以「出口」開頭

用法: ./.venv/bin/python tests/test_attr_gates_temple.py
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mrt.application import attractions as AT
from mrt.application.attractions import city_gates as CG
from mrt.application.attractions import kit
from mrt.domain import geometry as shapes
from mrt.domain import walk
from mrt.ports.block_sink import DictSink

ok = True


def chk(name, cond):
    global ok
    print(("  ok   " if cond else "  FAIL ") + name)
    ok = ok and cond


GROUND = 66
ITEMS = {it["id"]: it for it in AT.load_items()}


def build(aid):
    """跟 cli 一樣：plan 之後地面函式就不能再查（cli 會把地形距離場丟掉），
    build 裡的整地只能用 plan 時查過、記在 Site 快取裡的值。"""
    a = AT.for_world([], items=[ITEMS[aid]])[0]
    w = DictSink()
    state = {"planning": True}

    def ground(x, z):
        if not state["planning"]:
            raise RuntimeError("plan 之後還在查地面 (%d, %d)" % (x, z))
        return GROUND
    a.plan(kit.Site(ground))
    state["planning"] = False
    AT.build(a, w)
    return a, w


def column_top(w, x, z):
    ys = [k[1] for k, b in w.blocks.items() if k[0] == x and k[2] == z and not b.endswith(":air")]
    return max(ys) if ys else None


def common(a, w):
    blocks = w.blocks.values()
    chk("沒有黃色混凝土（月台警示帶專用）", not any("yellow_concrete" in b for b in blocks))
    bad = [b for b in blocks if "_stairs[" in b and not any("facing=%s" % f in b for f in
                                                            ("north", "south", "east", "west"))]
    chk("樓梯的朝向都是正方位", not bad)
    firsts = [lines[0] for lines in w.signs.values() if lines]
    chk("告示牌第一行不以「出口」開頭（%d 面）" % len(firsts), not any(t.startswith("出口") for t in firsts))
    sp = a.spots()
    chk("第一個觀景點 key 是空字串", bool(sp) and sp[0].key == "")
    for s in sp:
        chk("觀景點 %r (%d,%d,%d) 站得住" % (s.key, s.x, s.y, s.z), walk.standable(w.get, s.x, s.y, s.z))
    s0 = sp[0]
    near = [k for k, lines in w.signs.items()
            if abs(k[0] - s0.x) <= 4 and abs(k[2] - s0.z) <= 4 and lines and lines[0] == a.name_zh]
    chk("觀景點旁的說明牌寫著「%s」" % a.name_zh, bool(near))


def facing_err(a, s):
    """觀景點朝向與「看向輪廓中心」的偏差（度）。"""
    cells = set()
    for r in [a.outline()]:
        cells |= shapes.poly_cells(r)
    cx = sum(c[0] for c in cells) / len(cells)
    cz = sum(c[1] for c in cells) / len(cells)
    want = math.degrees(math.atan2(-(cx + 0.5 - (s.x + 0.5)), cz + 0.5 - (s.z + 0.5)))
    return abs((s.yaw - want + 180) % 360 - 180)


print("城門的位置：一律照 OSM 城門輪廓")
expect = {"beimen": (-631.3, -162.2), "dongmen": (23.5, 799.6),
          "nanmen": (-242.9, 1232.3), "xiaonanmen": (-943.5, 1037.4)}
for aid, (ex, ez) in expect.items():
    a = AT.for_world([], items=[ITEMS[aid]])[0]
    cx, cz = a.center()
    chk("%s 中心 (%.1f, %.1f) 在 OSM 城門上（誤差 < 1.5 m）" % (aid, cx, cz), math.hypot(cx - ex, cz - ez) < 1.5)
    x0, z0, x1, z1 = a.bbox()
    chk("%s 的 bbox 包住城門輪廓" % aid, x0 < cx < x1 and z0 < cz < z1)
for aid in expect:
    a = AT.for_world([], items=[ITEMS[aid]])[0]
    f = a.feature(a.osm)
    chk("%s 用的是資料裡指名的城門 way（%s，historic=city_gate）" % (aid, a.osm),
        f is not None and f.get("main") and f["tags"].get("historic") == "city_gate")

for aid in ("beimen", "dongmen", "nanmen", "xiaonanmen"):
    print("\n%s" % aid)
    a, w = build(aid)
    fr, g0 = a.fr, a.g0
    # 城座蓋滿 OSM 輪廓：城座頂那一層實心（南門的輪廓含花台草坪，只要求一半）；
    # 跟 verify_attractions 一樣從上面看，柱頂高過地面 3 格的比例
    cells = shapes.poly_cells(a.outline())
    filled = sum(1 for x, z in cells if not w.get(x, a.hb, z).endswith(":air"))
    need = 0.35 if aid == "nanmen" else 0.9
    chk("OSM 輪廓 %d 格裡 %.0f%% 在城座頂 y%d 是實心" % (len(cells), 100.0 * filled / len(cells), a.hb),
        filled >= need * len(cells))
    tops = {}
    for (x, y, z), b in w.blocks.items():
        if not b.endswith(":air") and y > tops.get((x, z), -999):
            tops[(x, z)] = y
    cover = sum(1 for c in cells if tops.get(c, -999) >= g0 + 3) / float(len(cells))
    chk("從上面看，輪廓裡 %.0f%% 的柱頂高過地面 3 格（verify_attractions 要 50%%）" % (cover * 100), cover >= 0.55)
    # 門洞：從城外沿著門洞中線走到城內
    outer = fr.cell(0.0, -a.b - 3.0)
    inner = fr.cell(0.0, a.b + 3.0)
    x0, z0, x1, z1 = a.bbox()
    dist, _ = walk.flood(w.get, [(outer[0], g0 + 1, outer[1])],
                         bounds=(x0, g0, z0, x1, g0 + 3, z1),
                         allow=lambda x, y, z: abs(fr.local(x, z)[0]) <= 4.0)
    chk("門洞走得通：城外 %s -> 城內 %s（只在門洞中線 4 m 內走）" % (outer, inner),
        (inner[0], g0 + 1, inner[1]) in dist)
    mid = fr.cell(0.0, 0.0)
    chk("門洞中段頭頂淨空 >= 3 格",
        all(w.get(mid[0], y, mid[1]).endswith(":air") for y in range(g0 + 1, g0 + 4)))
    chk("門洞沒有挖穿城座頂（y%d 是實心或倒置樓梯）" % a.hb,
        not w.get(mid[0], a.hb, mid[1]).endswith(":air"))
    top = max(k[1] for k in w.blocks)
    chk("最高點離地 %d m（12～18）" % (top - g0), 12 <= top - g0 <= 18)
    roof = [b for k, b in w.blocks.items() if k[1] >= g0 + 10 and ("stairs" in b or "slab" in b)]
    chk("屋頂有瓦（樓梯、半磚 %d 塊）" % len(roof), len(roof) > 60)
    plaques = [lines for lines in w.signs.values() if len(lines) > 1 and lines[1] == a.plaque_text] \
        if aid != "beimen" else [lines for lines in w.signs.values() if len(lines) > 1 and lines[1] == "承恩門"]
    chk("門額告示牌", bool(plaques))
    s0 = a.spots()[0]
    i, j = s0.z - fr.z0, s0.x - fr.x0
    in_ground = 0 <= i < fr.shape[0] and 0 <= j < fr.shape[1] and a.ground[i, j]
    chk("觀景點在整地範圍外（不必猜地面高度）", not in_ground)
    chk("觀景點在城外那一側（離門額那一面較近）",
        fr.local(s0.x, s0.z)[1] < 0)
    chk("觀景點面向輪廓中心（偏差 %.0f°）" % facing_err(a, s0), facing_err(a, s0) <= 30)
    common(a, w)
    names = set(b.split("[")[0] for b in w.blocks.values())
    if aid == "beimen":
        chk("北門：紅牆、橙紅瓦、灰黑屋脊",
            {"minecraft:red_terracotta", "minecraft:waxed_cut_copper_stairs",
             "minecraft:polished_deepslate"} <= names)
        # 北面（城外）的窗洞：紅牆上 g0+8 那一排有穿透的洞
        holes = 0
        for du in (-3.7, 0.0, 3.7):
            x, z = fr.cell(du, -a.b + 0.3)
            holes += w.get(x, g0 + 8, z).endswith(":air")
        chk("北面外壁二方一圓：三個窗洞（%d）" % holes, holes == 3)
    else:
        chk("宮殿式：綠琉璃瓦、紅柱、白雉堞、黃脊",
            {"minecraft:prismarine_brick_stairs", "minecraft:red_concrete", "minecraft:white_concrete",
             "minecraft:honeycomb_block"} <= names)
        if aid == "xiaonanmen":
            back = [k for k, b in w.blocks.items() if b == "minecraft:bricks" and k[1] == a.hb + 1]
            chk("小南門：城內側欄杆是紅磚（%d 格）" % len(back), len(back) > 5)

print("\n艋舺龍山寺")
a, w = build("longshan_temple")
fr, g0 = a.fr, a.g0
common(a, w)
mx, mz = fr.cell(0.0, 0.0)
main_top = max(k[1] for k in w.blocks if abs(fr.local(k[0], k[2])[0]) <= a.ha and abs(fr.local(k[0], k[2])[1]) <= a.hb_)
front = a.front_box
fx, fz = fr.cell(0.0, (front[2] + front[3]) / 2)
front_top = max(k[1] for k in w.blocks if front[0] <= fr.local(k[0], k[2])[0] <= front[1]
                and front[2] <= fr.local(k[0], k[2])[1] <= front[3])
chk("正殿（最高 y%d）比前殿（y%d）高" % (main_top, front_top), main_top > front_top + 2)
chk("正殿離地 %d m（14～19）" % (main_top - g0), 14 <= main_top - g0 <= 19)
# 重簷：正殿前緣往內看，下簷與上簷各有一層瓦
ex, ez = fr.cell(0.0, a.hb_ - 2.7)                     # 上層牆與上簷出簷之間
tiles = [k[1] for k, b in w.blocks.items() if ("copper" in b or "resin" in b) and k[0] == ex and k[2] == ez]
eaves = sorted(set(tiles))
chk("正殿前緣上方有兩層瓦（重簷，y %s）" % eaves, len(eaves) >= 2 and max(eaves) - min(eaves) >= 3)
cx_, cz_ = fr.cell(0.0, (a.hb_ + front[2]) / 2 + 2.0)
chk("中庭是露天的", all(w.get(cx_, y, cz_).endswith(":air") for y in range(g0 + 1, g0 + 25)))
plaza = a.spots()[0]
court = a.spots()[1]
x0, z0, x1, z1 = a.bbox()
dist, _ = walk.flood(w.get, [(plaza.x, plaza.y, plaza.z)], bounds=(x0, g0, z0, x1, g0 + 4, z1))
chk("從廟埕穿過前殿的門走得到中庭", (court.x, court.y, court.z) in dist)
water = [k for k, b in w.blocks.items() if b.startswith("minecraft:water")]
chk("廟埕兩側的飛瀑水池有水（%d 格）" % len(water), len(water) > 60)
chk("有銅龍柱與石雕龍柱", {"minecraft:waxed_exposed_chiseled_copper", "minecraft:chiseled_deepslate"}
    <= set(b.split("[")[0] for b in w.blocks.values()))
chk("中庭觀景點 key = courtyard", court.key == "courtyard")
chk("預設觀景點面向正殿（偏差 %.0f°）" % facing_err(a, plaza), facing_err(a, plaza) <= 30)
chk("說明牌四行：名稱與英文名照資料", a.plaque()[:2] == [ITEMS["longshan_temple"]["name_zh"],
                                               ITEMS["longshan_temple"]["name_en"]])

print("\n說明牌的事實行放得下（不被截成「…」）")
from mrt.application import signage as SG
for aid in ("beimen", "dongmen", "nanmen", "xiaonanmen", "longshan_temple"):
    a = AT.for_world([], items=[ITEMS[aid]])[0]
    facts = [t for t in a.plaque()[2:] if t]
    chk("%s：%s" % (aid, " / ".join(facts)), len(facts) == 2 and all(SG.text_width(t) <= SG.SIGN_W for t in facts))

print("\n" + ("全部通過" if ok else "有測試失敗"))
sys.exit(0 if ok else 1)
