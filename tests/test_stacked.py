#!/usr/bin/env python3
"""疊式車站與袋狀軌的單元測試（domain/stacked.py、build_line.sec_multi / _station_stacked）。

三座合成的直線地下站，每一座都真的蓋出來（DictSink）再驗：
  · 側式疊式（府中那種）：一條線，兩股道在站前分到上下兩層、月台在同一側
  · 共用島式疊式（西門那種）：兩條平行的線相距 17 m，共用一座雙層站體
  · 袋狀軌：區間裡正線張開，中間多一股儲車軌

驗的是玩家真的走得動的規則（domain/walk）：從穿堂層出發，上下兩層月台的
警示帶都要走得到 —— 樓梯少一階、洞口沒開、下層頂板壓到淨空不夠，剖面上
看不出來，走一遍才知道。鐵軌照 cli 的方式從 strands() 鋪，過通用檢查器，
而且每一根都要落在走行面上（分層段的箱涵是逐點取聯集砌的，哪一格漏了
鐵軌就懸空）。

用法: ./.venv/bin/python tests/test_stacked.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from mrt.application import build_line as BL
from mrt.domain import alignment as AL
from mrt.domain import exits as EX
from mrt.domain import rails
from mrt.domain import stacked as SK
from mrt.domain import walk
from mrt.ports.block_sink import DictSink

ok = True


def chk(name, cond):
    global ok
    print(("  ok   " if cond else "  FAIL ") + name)
    ok = ok and cond


Y, G = 48, 66                       # 軌面、地面（平的）


def make_seg(ref, pts, stn_x, y=Y):
    """一條直線地下線，車站在最接近 x=stn_x 的取樣點。"""
    samples = AL.resample(pts, ["tunnel"] * len(pts), AL.STEP)
    n = len(samples)
    idxs = [min(range(n), key=lambda i: abs(samples[i][0] - sx)) for sx in stn_x]
    stn = {i: (f"{ref}{k + 1}", f"{ref}站{k + 1}", f"{ref} station {k + 1}")
           for k, i in enumerate(idxs)}
    return dict(ref=ref, samples=samples, ys=np.full(n, y), ground=np.full(n, G),
                stn=stn), idxs


def finish(sg):
    """cli.plan_segments 在分層／袋狀軌之後做的事：離線位與半寬。"""
    stk = sg.get("stacked", {})
    if "toff" not in sg:
        sg["toff"] = AL.track_offsets(sg["samples"], sg["ys"], sg["ground"],
                                      [i for i in sorted(sg["stn"]) if i not in stk])
    sg["hw"] = [AL.half_width(t) for t in sg["toff"]]


def build_sections(w, sg, skip_stn=True):
    """照 cli.main 的順序蓋斷面：站體範圍不蓋（車站自己會蓋），nobuild 不蓋。"""
    samples, ys = sg["samples"], sg["ys"]
    n = len(samples)
    half = int(AL.PLATFORM_LEN / 2 / AL.STEP)
    in_stn = set()
    for bi in sg["stn"]:
        in_stn.update(range(max(0, bi - half), min(n - 1, bi + half) + 1))
    nob = sg.get("nobuild", set())
    multi = sg.get("multi")
    for i, (x, z, ux, uz, _) in enumerate(samples):
        if (skip_stn and i in in_stn) or i in nob:
            continue
        if multi is not None and multi[i]:
            BL.sec_multi(w, x, z, -uz, ux, SK.tracks_at(sg, i))
        else:
            BL.sec_tunnel(w, x, z, -uz, ux, int(ys[i]), hw=sg["hw"][i])


def build_stations(w, sg):
    for bi, label in sg["stn"].items():
        BL.build_station(w, SK.station_samples(sg, bi), sg["ys"], bi, True, label=label,
                         grounds=sg["ground"], access=False,
                         stacked=sg.get("stacked", {}).get(bi))


def lay_rails(w, sg):
    """照 cli.main 鋪鐵軌；回傳 [(股道編號, blocks)]。"""
    out = []
    for k, (i0, i1, off_at, y_at) in enumerate(SK.strands(sg)):
        pts = []
        for i in range(i0, i1 + 1):
            x, z, ux, uz, _ = sg["samples"][i]
            o = off_at(i)
            pts.append((x - uz * o, y_at(i) + 1, z + ux * o))
        blocks = rails.rail_path(pts)
        for bx, by, bz, shape, pw in blocks:
            w.set(bx, by, bz, rails.block_string(shape, pw))
        out.append((k, blocks))
    return out


def rails_supported(w, blocks, cells):
    """回傳懸空的鐵軌數。rails.py 為了讓斜軌落在直線段上會把高差前後挪幾格，
    挪過的那幾格會比走行面高一格 —— cli 會在每根鐵軌底下補支承，所以下潛段
    每降一格允許一根懸空；超過就是箱涵漏挖或漏鋪。"""
    bad = 0
    for bx, by, bz, _, _ in blocks:
        below = w.get(bx, by - 1, bz)
        if below == BL.AIR or (bx, by - 1, bz) in cells:
            bad += 1
    return bad


def reach(w, start, floor_ok=None):
    bounds = None
    dist, _ = walk.flood(w.get, [start], bounds=bounds, floor_ok=floor_ok)
    return dist


def yellow_levels(w, dist):
    """走得到的警示帶（站立面）在哪幾個高度。"""
    lv = set()
    for (x, y, z), blk in w.blocks.items():
        if blk == BL.YELLOW and (x, y + 1, z) in dist:
            lv.add(y + 1)
    return sorted(lv)


def col(samples, i, off):
    x, z, ux, uz, _ = samples[i]
    return int(round(x - uz * off)), int(round(z + ux * off))


# ======================================================================
print("側式疊式站（府中）")
A, (ia,) = make_seg("A", [(-700.0, 0.0), (700.0, 0.0)], [0])
lay = SK.plan_side(A, ia, +1, "left")            # 上層往 +x，月台在左側（-z）
finish(A)
n = len(A["samples"])
chk("月台在 -off 側（往 +x 的左手邊）、軌道靠 +off 側牆",
    lay["plat"][0] == -(AL.BOX_HALF - 2) and lay["tracks"][0] == AL.STN_TRACK_OFF)
chk("上層是 +off 那股（靠右行駛）",
    int(A["y_side"][1][ia]) == Y and int(A["y_side"][-1][ia]) == Y - SK.LEVEL_H)
chk("站內兩股道併到同一個離線位",
    A["off_side"][1][ia] == A["off_side"][-1][ia] == lay["tracks"][0])
lo, hi = SK.station_range(n, ia)
ext = int(round(SK.SPLIT_M / AL.STEP))
chk("區間仍是 ±3、同一個軌面",
    A["off_side"][1][lo - ext - 10] == 3 and A["off_side"][-1][lo - ext - 10] == -3
    and int(A["y_side"][-1][lo - ext - 10]) == Y)
ramp = A["y_side"][-1][lo - ext:lo]
chk("下潛段每步最多降一格、總共降 LEVEL_H",
    int(ramp[0]) == Y and int(ramp[-1]) == Y - SK.LEVEL_H
    and max(abs(int(ramp[k + 1]) - int(ramp[k])) for k in range(len(ramp) - 1)) <= 1)

w = DictSink()
build_sections(w, A)
build_stations(w, A)
ym = Y + AL.LEVEL_DY["tunnel"]                    # 穿堂站立面
start = (*col(A["samples"], ia, 0), )
start = (start[0], ym, start[1])
chk("穿堂層站得住", walk.standable(w.get, *start))
dist = reach(w, start)
lv = yellow_levels(w, dist)
chk(f"從穿堂走得到上下兩層月台的警示帶（{lv}）", lv == [Y + 2 - SK.LEVEL_H, Y + 2])
# 下層月台面本身：站立面 Y-6，警示帶在月台門邊
yl = Y - SK.LEVEL_H
cx, cz = col(A["samples"], ia, lay["yellow"][0])
chk("下層警示帶方塊在月台面高度", w.get(cx, yl + 1, cz) == BL.YELLOW)
cx, cz = col(A["samples"], ia, lay["tracks"][0])
chk("下層走行面在軌面 -8", w.get(cx, yl, cz) == BL.DECK and w.get(cx, Y, cz) == BL.DECK)
chk("上下兩層之間有樓板", w.get(cx, Y - 2, cz) == BL.LINING)
strands = lay_rails(w, A)
chk("兩股正線", len(strands) == 2)
for k, blocks in strands:
    errs = rails.check_rails(blocks)
    chk(f"第 {k} 股鐵軌過通用檢查器（{len(blocks)} 格）", not errs)
    if errs:
        print("     ", errs[:3])
    nbad = rails_supported(w, blocks, set())
    allow = 0 if k == 0 else 2 * SK.LEVEL_H          # 下潛那股：來回各降 8 格
    chk(f"第 {k} 股鐵軌懸空的不多於高差的格數（懸空 {nbad}，上限 {allow}）", nbad <= allow)
ys_low = [b[1] for k, blocks in strands for b in blocks if k == 1]
chk("下潛那股的鐵軌真的低了 8 格", min(ys_low) == Y + 1 - SK.LEVEL_H)
occ = EX.index_segments([A])
cx, cz = col(A["samples"], ia, 0)
chk("占用表涵蓋下層", occ.blocked(cx, cz, Y - 9, Y - 8))
fl = int(round(SK.FLARE_M / AL.STEP))
cx, cz = col(A["samples"], lo - fl - 4, -3)         # 下潛段的盡頭，差不多降完 8 格
chk("占用表涵蓋下潛段", occ.blocked(cx, cz, Y - 8, Y - 7))

# ======================================================================
print("共用島式疊式站（西門）")
P, (ip,) = make_seg("P", [(-700.0, 0.0), (700.0, 0.0)], [0])
Q, (iq,) = make_seg("Q", [(-700.0, 17.0), (700.0, 17.0)], [0])
lay, m, side, prng = SK.plan_shared(P, ip, +1, Q, iq, +1)
finish(P); finish(Q)
chk("partner 在 +off 側、中線偏 8", side == 1 and m == 8)
chk("partner 的車站被拿掉、站體範圍不蓋斷面",
    iq not in Q["stn"] and prng[0] < iq < prng[1] and iq in Q["nobuild"])
fr = SK.station_samples(P, ip)
chk("frame 在兩線中線上", abs(fr[ip][1] - 8.0) < 1e-9)
chk("primary 的兩股道併到自己的中心線（frame 的 -8）", P["off_side"][1][ip] == 0.0)
chk("partner 的兩股道併到 frame 的 +8（自己座標系 -1）",
    abs(Q["off_side"][1][iq] - (-1.0)) < 1e-6)
chk("兩線軌面釘成一樣", int(Q["ys"][iq]) == int(P["ys"][ip]) == Y)

w = DictSink()
build_sections(w, P)
build_sections(w, Q)
build_stations(w, P)
start = (int(round(fr[ip][0])), ym, int(round(fr[ip][1])))
chk("穿堂層（frame 中線）站得住", walk.standable(w.get, *start))
dist = reach(w, start)
lv = yellow_levels(w, dist)
chk(f"從穿堂走得到上下兩層的島式月台（{lv}）", lv == [Y + 2 - SK.LEVEL_H, Y + 2])
n_y = {}
for (x, y, z), blk in w.blocks.items():
    if blk == BL.YELLOW and (x, y + 1, z) in dist:
        n_y[(y + 1, z)] = n_y.get((y + 1, z), 0) + 1
chk("每層月台兩側的警示帶都走得到（四條）", len(n_y) == 4)
all_blocks = []
for sg in (P, Q):
    for k, blocks in lay_rails(w, sg):
        errs = rails.check_rails(blocks)
        chk(f"{sg['ref']} 第 {k} 股鐵軌過通用檢查器", not errs)
        if errs:
            print("     ", errs[:3])
        all_blocks.append((sg["ref"], k, blocks))
for ref, k, blocks in all_blocks:
    nbad = rails_supported(w, blocks, set())
    allow = 0 if k == 0 else 2 * SK.LEVEL_H
    chk(f"{ref} 第 {k} 股鐵軌懸空的不多於高差的格數（懸空 {nbad}，上限 {allow}）", nbad <= allow)
# 站內：P 的鐵軌在 z=0（frame -8）、Q 的在 z=16（frame +8），各兩層
def rails_at(blocks, x):
    return sorted({(b[1], b[2]) for b in blocks if b[0] == x})
px = int(round(fr[ip][0]))
zs = {ref: set() for ref, _, _ in all_blocks}
for ref, k, blocks in all_blocks:
    for y, z in rails_at(blocks, px):
        zs[ref].add((y, z))
chk(f"站內 P 的兩股道疊在 z=0（{sorted(zs['P'])}）",
    zs["P"] == {(Y + 1, 0), (Y + 1 - SK.LEVEL_H, 0)})
chk(f"站內 Q 的兩股道疊在 z=16（{sorted(zs['Q'])}）",
    zs["Q"] == {(Y + 1, 16), (Y + 1 - SK.LEVEL_H, 16)})
occ = EX.index_segments([P, Q])
chk("占用表以 frame 為準：中線 z=8 的下層被占用", occ.blocked(px, 8, Y - 9, Y - 8))
chk("占用表：frame 側牆外一格沒被占用", not occ.blocked(px, 8 + 14, Y, Y + 2))

# ======================================================================
print("袋狀軌")
R, (ir0, ir1) = make_seg("R", [(-900.0, 0.0), (900.0, 0.0)], [-400, 400])
finish(R)
res = SK.plan_pocket(R, ir0, ir1, None, 150)
chk("兩站之間放得下", res is not None)
i0, i1 = res
R["hw"] = [AL.half_width(t) for t in R["toff"]]
mid = (i0 + i1) // 2
chk("儲車軌段正線張開到 ±6", R["toff"][mid] == 6.0)
chk("第三股道長度 >= 150 m", (i1 - i0) * AL.STEP >= 150)
trs = SK.tracks_at(R, mid)
chk(f"儲車軌段有三股道（{sorted(o for o, _ in trs)}）", sorted(o for o, _ in trs) == [-6.0, 0.0, 6.0])
chk("站體張開段沒被袋狀軌動到", R["toff"][ir0] == 8.0 and R["toff"][ir0 + int(80 / AL.STEP)] == 3.0)
w = DictSink()
build_sections(w, R)
build_stations(w, R)
cx, cz = col(R["samples"], mid, 0)
chk("儲車軌中線是走行面、不是分隔矮牆", w.get(cx, Y, cz) == BL.DECK and w.get(cx, Y + 1, cz) == BL.AIR)
cx, cz = col(R["samples"], mid, 3)
chk("正線與儲車軌之間有分隔矮牆", w.get(cx, Y + 1, cz) == BL.WALL)
cx, cz = col(R["samples"], mid, 9)
chk("側牆在 ±9", w.get(cx, Y + 2, cz) == BL.LINING)
strands = lay_rails(w, R)
chk("三股道", len(strands) == 3)
for k, blocks in strands:
    errs = rails.check_rails(blocks)
    chk(f"第 {k} 股鐵軌過通用檢查器（{len(blocks)} 格）", not errs)
    if errs:
        print("     ", errs[:3])
    nbad = rails_supported(w, blocks, set())
    chk(f"第 {k} 股鐵軌每一根都有支承（懸空 {nbad}）", nbad == 0)
# 三股道互不占用同一格
cells = {}
for k, blocks in strands:
    for b in blocks:
        cells.setdefault((b[0], b[2]), set()).add(k)
chk("三股道沒有搶同一格", all(len(v) == 1 for v in cells.values()))

print("\n" + ("全部通過" if ok else "有測試失敗"))
sys.exit(0 if ok else 1)
