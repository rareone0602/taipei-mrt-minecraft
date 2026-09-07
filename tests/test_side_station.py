#!/usr/bin/env python3
"""側式月台車站（高架／平面）穿堂層的單元測試。

高架站與平面站原本只有兩座各自封閉的側式月台，樣板樓梯只通到 + 側那一座，
- 側月台誰也走不到。現在每座非地下站都有一層穿堂（型態由
domain/alignment.station_kind 決定）：閘門、往兩座月台各一座樓梯，真實出入口
接到這一層。這裡蓋兩座直線的合成車站，各用玩家真的走得動的規則
（domain/walk）從 + 側月台出發，證明：

  月台 -> 端點樓梯 -> 穿堂 -> 閘門 -> 另一座樓梯 -> 另一座月台

兩種型態各一：
  · 高架站（軌面比地面高 13 m）-> "under"，穿堂在橋下、橋面板就是頂板
  · 平面站（軌面與地面同高）  -> "over"，穿堂是跨在月台上方的天橋

樓梯兩端差一格是這裡的經典錯誤（梯頂比月台面高一格 / 梯底比樓板低一格，
走得下去爬不上來），所以除了洪水填滿，也逐格看兩端的踏面。

用法: ./.venv/bin/python tests/test_side_station.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mrt.application import build_concourse as BCC
from mrt.application import build_line as BL
from mrt.domain import alignment as AL
from mrt.domain import walk
from mrt.ports.block_sink import DictSink

ok = True


def chk(name, cond):
    global ok
    print(("  ok   " if cond else "  FAIL ") + name)
    ok = ok and cond


PER_M = max(1, int(round(1.0 / AL.STEP)))


def straight(y, g, x0=-400, x1=400):
    """一條沿 X 軸的直線，軌面 y、地面 g 都是平的。車站在 x=0。"""
    pts = [(float(x0), 0.0), (float(x1), 0.0)]
    samples = AL.resample(pts, ["bridge", "bridge"], AL.STEP)
    n = len(samples)
    idx = min(range(n), key=lambda i: abs(samples[i][0]))
    half = int(AL.PLATFORM_LEN / 2 / AL.STEP)
    return samples, [y] * n, [g] * n, idx, idx - half, idx + half


def build(sec, y, g):
    """照 cli/build_world.py 的順序：先整條線的斷面（車站範圍也蓋，
    橋墩就是這樣長進站體裡的），再疊車站。"""
    w = DictSink()
    samples, ys, gnd, idx, lo, hi = straight(y, g)
    for i, (x, z, ux, uz, _) in enumerate(samples):
        if sec is BL.sec_bridge:
            sec(w, x, z, -uz, ux, ys[i], gnd[i],
                pier=(abs((i * AL.STEP) % AL.PIER_EVERY) < AL.STEP / 2))
        else:
            sec(w, x, z, -uz, ux, ys[i], gnd[i])
    BL.build_station(w, samples, ys, idx, False, label=("T1", "測試站", "Test"),
                     grounds=gnd, access=False)
    return w, samples, ys, gnd, idx, lo, hi


def col(samples, i, off):
    """取樣點 i 離線位 off 的 (x, z) 方塊座標，與生成器同一套取整。"""
    x, z, ux, uz, _ = samples[i]
    nx, nz = -uz, ux
    return int(round(x + nx * off)), int(round(z + nz * off))


def walk_station(kind_expect, w, samples, ys, gnd, idx, lo, hi):
    y, g = int(ys[idx]), int(gnd[idx])
    kind = AL.station_kind(y, g)
    chk(f"型態 {kind}", kind == kind_expect)
    L = y + AL.LEVEL_DY[kind]                             # 穿堂站立面
    fl = L - 1
    x_lo, x_hi = col(samples, lo, 0)[0], col(samples, hi, 0)[0]
    get = w.get

    # 月台警戒帶：兩端那一排壓在端牆底下（站屋本來就把月台兩端封住），不算
    yellow = [(x, yy + 1, z) for (x, yy, z), b in w.blocks.items()
              if b == BL.YELLOW and x_lo < x < x_hi]
    chk(f"月台警戒帶 {len(yellow)} 格（兩座月台各 {(x_hi - x_lo - 1)} 格）",
        len(yellow) == 2 * (x_hi - x_lo - 1))
    plus = [c for c in yellow if c[2] > 0]
    minus = [c for c in yellow if c[2] < 0]
    chk("兩側都有", len(plus) == len(minus) and len(plus) > 0)

    start = (0, y + 2, 6)                                 # + 側月台中央
    chk(f"起點 {start} 站得住", walk.standable(get, *start))
    bounds = (x_lo - 30, min(g, y) - 6, -20, x_hi + 30, max(g, y) + 16, 20)
    dist, _ = walk.flood(get, [start], bounds=bounds)
    chk(f"+ 側警戒帶全部走得到（{sum(1 for c in plus if c in dist)}/{len(plus)}）",
        all(c in dist for c in plus))
    chk(f"- 側警戒帶全部走得到（{sum(1 for c in minus if c in dist)}/{len(minus)}）",
        all(c in dist for c in minus))
    conc = [c for c in dist if c[1] == L and abs(c[2]) <= 10 and x_lo <= c[0] <= x_hi]
    chk(f"走得到穿堂層 y{L}（{len(conc)} 格）", len(conc) > 200)
    chk("走得到閘門前的非付費區（lo+14 m 之前）",
        any(c[0] < x_lo + 14 for c in conc))
    chk("穿堂層兩側靠牆那一排（|off| 10）在非付費區走得通",
        all((x, L, s * 10) in dist for x in range(x_lo + 3, x_lo + 12) for s in (1, -1)))
    lane = col(samples, lo + 14 * PER_M, 0)
    chk("閘門列在穿堂樓板上（lo+14 m 中央是通行閘道）",
        get(lane[0], fl, lane[1]) == BL.LANE and get(lane[0], fl + 1, lane[1]) == "minecraft:air")
    chk("閘門機箱也在", get(lane[0], fl + 1, lane[1] + 1) == BL.GATE)

    # 樓梯兩端：+ 側在 off 8，- 側在 off -9；都從 hi 端往回退 run+1 m
    run = 2 * abs(AL.LEVEL_DY[kind] - 2)
    s0 = hi - (run + 1) * PER_M
    for off in (8, -9):
        top = col(samples, s0 + run * PER_M, off)            # 最後一階（靠 hi 端）
        first = col(samples, s0 + PER_M, off)                # 第一階（靠穿堂樓板）
        if kind == "under":
            chk(f"off {off:>2}: 梯頂整塊與月台面齊平（y{y + 1}）",
                get(top[0], y + 1, top[1]) == BL.STAIR)
            chk(f"off {off:>2}: 梯底半磚落在穿堂樓板上（y{fl + 1}）",
                get(first[0], fl + 1, first[1]) == BL.SLAB
                and get(first[0], fl, first[1]) == BL.CONC)
        else:
            chk(f"off {off:>2}: 梯底整塊與月台面齊平（y{y + 1}）",
                get(top[0], y + 1, top[1]) == BL.STAIR)
            chk(f"off {off:>2}: 梯頂半磚嵌在穿堂樓板裡（y{fl}）",
                get(first[0], fl, first[1]) == BL.SLAB)
    return dist, L, fl, x_lo, x_hi, s0, run


# ============ 高架站：橋下穿堂 ============
print("高架站（軌面 y80、地面 y67）")
Y, G = 80, 67
w, samples, ys, gnd, idx, lo, hi = build(BL.sec_bridge, Y, G)
dist, L, fl, x_lo, x_hi, s0, run = walk_station("under", w, samples, ys, gnd, idx, lo, hi)
chk(f"穿堂樓板 y{fl} 在地面上（>= g+2 = {G + 2}）", fl >= G + 2)
chk("樓板下面是空的（懸在橋下，不是埋在土裡）",
    w.get(5, fl, 3) == BL.CONC and w.get(5, fl - 1, 3) == "minecraft:air")
chk("橋面板（y-1）就是穿堂頂板，月台正下方沒被挖掉",
    all(w.get(x, Y - 1, z) == BL.CONC for x in range(x_lo + 2, x_lo + 40) for z in (0, 7, -7)))
chk("側牆 |off| 11 是玻璃、頂到橋面板邊緣",
    w.get(10, L, 11) == BL.GLASS and w.get(10, Y - 1, 11) == BL.CONC
    and w.get(10, fl, -11) == BL.CONC)
chk("端牆封閉", all(w.get(x_lo, yy, z) == BL.CONC for yy in range(L, Y - 1) for z in range(-11, 12)))
# 橋墩：sec_bridge 在 x=0 立了一根，穿堂挖空後要補回來，柱子從地面連到橋面板
piers = [i for i in range(lo, hi + 1) if abs((i * AL.STEP) % AL.PIER_EVERY) < AL.STEP / 2]
chk(f"站內有 {len(piers)} 根橋墩", len(piers) >= 2)
cx = int(round(samples[piers[0]][0]))
chk(f"橋墩 x={cx} 在大廳裡連續（樓板上 -> 橋面板下）",
    all(w.get(cx + dx, yy, dz) == BL.PIER for yy in range(fl + 1, Y - 1)
        for dx in (-1, 0, 1) for dz in (-1, 0, 1)))
chk("橋墩在樓板下也還在", w.get(cx, fl - 1, 0) == BL.PIER and w.get(cx, G - 4, 0) == BL.PIER)
chk("橋墩擋不住穿堂（柱子旁邊走得過）",
    (cx + 2, L, 0) in dist and (cx - 2, L, 0) in dist)
# 月台上的洞與欄杆：樓梯挖穿月台面的地方，內側那一排（off 7）圍起來
# 月台面那一層不是月台鋪面的地方就是洞（最上面兩階的踏面本身就在 y+1）
opening = [x for x in range(x_lo + 1, x_hi) if w.get(x, Y + 1, 8) != BL.PLAT]
chk(f"+ 側月台面開了 {len(opening)} m 的洞（x {min(opening)}..{max(opening)}，直到 hi-1）",
    len(opening) == 10 and max(opening) == x_hi - 1)
fenced = [x for x in opening if w.get(x, Y + 2, 7) == BL.BARS]
chk(f"洞旁邊 off 7 有欄杆（{len(fenced)} 格）", len(fenced) >= 6)
chk("梯頂最後三階旁邊沒有欄杆（要從那裡上月台）",
    all(w.get(x, Y + 2, 7) != BL.BARS for x in range(x_hi - 3, x_hi)))
chk("洞的盡頭橫著圍一排", w.get(min(opening) - 1, Y + 2, 8) == BL.BARS
    and w.get(min(opening) - 1, Y + 2, 9) == BL.BARS)
chk("警戒帶（off 6）沒被欄杆佔掉",
    all(w.get(x, Y + 2, 6) == "minecraft:air" for x in opening))
chk("- 側對稱", all(w.get(x, Y + 2, -7) == BL.BARS for x in fenced)
    and all(w.get(x, Y + 1, -8) != BL.PLAT for x in opening))
chk("站屋屋頂沒被樓梯挖穿",
    all(w.get(x, Y + 6, z) == BL.CONC for x in range(x_lo, x_hi + 1) for z in range(-10, 11)))

# ============ 平面站：天橋式穿堂 ============
print("平面站（軌面 y71、地面 y71）")
Y, G = 71, 71
w, samples, ys, gnd, idx, lo, hi = build(BL.sec_ground, Y, G)
dist, L, fl, x_lo, x_hi, s0, run = walk_station("over", w, samples, ys, gnd, idx, lo, hi)
chk(f"穿堂樓板 y{fl} 疊在站屋屋頂（y{Y + 6}）上", fl == Y + 7)
foot = set()
for t in range(1, run + 1):
    for off in (8, 9, -9, -8):
        foot.add(col(samples, s0 + t * PER_M, off))
roof_bad = [(x, z) for x in range(x_lo, x_hi + 1) for z in range(-10, 11)
            if (x, z) not in foot and w.get(x, Y + 6, z) != BL.CONC]
chk(f"站屋屋頂 y{Y + 6} 除了樓梯以外都還是 CONC（壞 {len(roof_bad)} 格）", not roof_bad)
chk("穿堂頂板沒被梯頂的淨空挖穿",
    all(w.get(x, Y + 11, z) == BL.CONC for x in range(x_lo, x_hi + 1) for z in range(-11, 12)))
chk("側牆 |off| 11 是玻璃", w.get(10, L, 11) == BL.GLASS and w.get(10, L + 2, -11) == BL.GLASS)
hole = [x for x in range(x_lo, x_hi + 1) if w.get(x, fl, 8) == "minecraft:air"]
chk(f"穿堂樓板開了 {len(hole)} m 的洞", len(hole) >= 6)
chk("洞兩側（off 7 與 off 10）有欄杆",
    sum(1 for x in hole if w.get(x, L, 7) == BL.BARS) >= 5
    and sum(1 for x in hole if w.get(x, L, 10) == BL.BARS) >= 5)
chk("洞的盡頭（靠 hi 端）橫著圍一排",
    w.get(max(hole) + 1, L, 8) == BL.BARS and w.get(max(hole) + 1, L, 9) == BL.BARS)
chk("月台上沒有多出來的欄杆",
    all(w.get(x, Y + 2, 7) != BL.BARS for x in range(x_lo, x_hi + 1)))

# ============ 有出入口時樣板樓梯照舊 ============
print("access 開關")
w1 = DictSink()
samples, ys, gnd, idx, lo, hi = straight(80, 67)
BL.build_station(w1, samples, ys, idx, False, label=("T1", "測試站", "Test"), grounds=gnd, access=True)
w0 = DictSink()
BL.build_station(w0, samples, ys, idx, False, label=("T1", "測試站", "Test"), grounds=gnd, access=False)
chk(f"access=True 多了 {len(w1) - len(w0):,} 個方塊（樣板樓梯與站屋）", len(w1) > len(w0) + 500)
chk("access=False 沒有站屋的出口牌", not any("Exit" in " ".join(v) for v in w0.signs.values()))

# ============ build_concourse：往上爬的井與空橋 ============
print("出入口井（往上爬）與空橋")
w = DictSink()
well = BCC.ShaftStair(100, 100, 1, 0, 90, 71, bottom_door=True, sign_bottom=["T1", "測試站", "Test", "出口 1"])
well.build(w)
sx, sz = well._w(-2, 2)
chk("井底門邊立了出口牌", w.signs.get((sx, 71, sz)) == ["T1", "測試站", "Test", "出口 1"])
chk("牌子底下墊了一塊", w.get(sx, 70, sz) == well.step)
chk("井口沒有牌子", (well._w(-2, 2)[0], 91, well._w(-2, 2)[1]) not in w.signs)
w = DictSink()
cells = {(x, z) for x in range(0, 30) for z in range(-2, 3)}
ring = BCC.outer_ring(cells)
tile = BCC.Tile(cells, ring, 80, {}, shopfront=False, bridge=True, pier_to={(0, 0): 66, (25, 0): 60})
tile.build(w)
chk("空橋外緣是玻璃欄板", w.get(10, 80, 3) == BCC.RAIL and w.get(10, 82, 3) == BCC.RAIL)
chk("空橋外緣的橋面與頂板", w.get(10, 79, 3) == BCC.EDGE and w.get(10, 83, 3) == BCC.CEIL)
chk("橋墩從地面下 2 格到橋面板下一格",
    all(w.get(25, yy, 0) == BCC.PIER for yy in range(58, 79)) and w.get(25, 79, 0) == BCC.FLOOR)
chk("沒有 bridge 的 Tile 照舊",
    (lambda d: (BCC.Tile(cells, ring, 80, {}).build(d), d.get(10, 80, 3) == BCC.WALL)[1])(DictSink()))

print("\n全部通過" if ok else "\n有測試失敗")
raise SystemExit(0 if ok else 1)
