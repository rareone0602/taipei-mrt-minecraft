#!/usr/bin/env python3
"""中式傳統建築的零件：瓦屋面、屋脊（鴟吻、燕尾）、山花、拱門、雉堞、石欄杆。

城門（city_gates.py）與艋舺龍山寺（longshan_temple.py）共用。kit.py 給的是「形狀」
（遮罩、屋頂高度場）；這裡把形狀寫成看得出是中式建築的方塊：

  tile_roof    屋頂高度場 -> 瓦屋面。坡面頂層用樓梯方塊（朝上坡方向）與半磚，
               筒瓦一壟一壟順著坡往下，兩種材質隔壟交錯；殼厚跟著坡度走，
               陡的地方（舉折的上段）不會透光。簷下另外塗一層斗拱／椽子的顏色
  corner_lift  自己算的坡面（披檐、下簷）加上四角起翹
  ridge_line   沿局部座標的一條折線疊方塊（龍身、短的脊）
  seg_mask     離一條線段不到半格的格子：斜的屋脊一格寬，不會變成兩格寬的鋸齒
  swallowtail  閩南式燕尾脊：正脊兩端上揚、伸出山牆外、末端分叉
  chiwen       北方宮殿式正脊兩端的鴟吻
  gable_face   歇山的山花
  cut_arch     半圓拱門洞；拱頂兩角用倒置的樓梯修圓
  plaque_sign  匾上的字（壁掛告示牌貼在匾的正方位鄰格）
  walls_conn / panes_conn
               石欄杆（牆方塊）、鐵欄杆的連線狀態：寫進存檔的方塊不會自己更新連線

模組本身沒有 BUILDS，登錄表掃到也不會多出景點。只呼叫 Painter／BlockSink 的 set()。
"""
import math

import numpy as np

from mrt.application.attractions import kit

AIR = kit.AIR

# 瓦：每種屋面兩壟交錯的 (整塊, 樓梯的前綴, 半磚的前綴)
# 綠色琉璃瓦（東門、南門、小南門 1966 年改建的北方宮殿式屋頂，照片上是青綠色）
GREEN_TILES = (("minecraft:prismarine_bricks", "prismarine_brick", "prismarine_brick"),
               ("minecraft:waxed_oxidized_cut_copper", "waxed_oxidized_cut_copper",
                "waxed_oxidized_cut_copper"))
# 橙紅色的閩南紅瓦（北門、龍山寺）：上蠟切製銅（不會氧化變綠）與樹脂磚交錯
ORANGE_TILES = (("minecraft:waxed_cut_copper", "waxed_cut_copper", "waxed_cut_copper"),
                ("minecraft:resin_bricks", "resin_brick", "resin_brick"))


def stairs(prefix, facing, half="bottom"):
    """樓梯方塊字串。facing 是往上走的方向（屋面上就是上坡、朝屋脊）。"""
    return "minecraft:%s_stairs[facing=%s,half=%s,shape=straight,waterlogged=false]" % (
        prefix, facing, half)


def slab(prefix, kind="bottom"):
    """半磚方塊字串（kind：bottom 下半、top 上半）。"""
    return "minecraft:%s_slab[type=%s,waterlogged=false]" % (prefix, kind)


# ---------------------------------------------------------------- 瓦屋面

def _grad(S, mask, axis):
    """遮罩裡的中央差分；只有一側在遮罩裡就用單側差分，兩側都不在回 0。"""
    fwd, fm = np.roll(S, -1, axis), np.roll(mask, -1, axis)
    bwd, bm = np.roll(S, 1, axis), np.roll(mask, 1, axis)
    return np.where(fm & bm, (fwd - bwd) / 2.0,
                    np.where(fm, fwd - S, np.where(bm, S - bwd, 0.0)))


def tile_roof(p, mask, y_eave, h, tiles, shell=2, under=None, under_mask=None, steep=0.3,
              ridge_full=0.12):
    """把屋頂高度場鋪成瓦屋面。

    y_eave   簷口那一圈瓦所在的方塊 y（h = 0 的地方屋面頂在 y_eave + 1）
    h        kit.hip / hip_gable / gable / pyramid 回傳的高度場（公尺，簷口 = 0）
    tiles    (整塊, 樓梯前綴, 半磚前綴) 的序列，隔壟輪流用
    shell    最少殼厚；上坡鄰格比自己高很多的地方自動加厚，側面才不會透光
    under    殼底下再塗一格的材質（簷下的斗拱、椽子）；under_mask 限定哪些格子塗
    回傳每格屋面頂的方塊 y（陣列，遮罩外 -999），給屋脊、山花對齊用。
    """
    fr = p.fr
    S = y_eave + 1 + np.asarray(h, dtype=float)
    S = np.broadcast_to(S, fr.shape)
    H = np.where(mask, S, np.nan)
    # 上坡方向：只用遮罩裡的鄰格算差分（硬山的山牆邊不會被牆外的空氣帶歪）
    gz, gx = _grad(S, mask, 0), _grad(S, mask, 1)
    # 鄰格最大落差：決定殼厚
    dmax = np.zeros(fr.shape)
    for dz, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nb = np.roll(np.roll(H, dz, axis=0), dx, axis=1)
        d = np.abs(np.nan_to_num(nb - H, nan=0.0))
        dmax = np.maximum(dmax, d)
    tops = np.full(fr.shape, -999, dtype=np.int32)
    idx = np.argwhere(mask)
    s = p.w.set
    for i, j in idx:
        x, z = int(fr.X[i, j]), int(fr.Z[i, j])
        sv = float(S[i, j])
        n = int(math.floor(sv))
        f = sv - n
        ax, az = float(gx[i, j]), float(gz[i, j])
        slope = math.hypot(ax, az)
        # 筒瓦順著坡往下：坡朝東西就按 z 隔壟、朝南北就按 x 隔壟
        k = (z if abs(ax) > abs(az) else x) % len(tiles)
        full, st, sl = tiles[k]
        cap = None
        if f < 0.25:
            top = n - 1
        elif f < 0.75:
            top = n - 1
            if slope >= steep:
                cap = stairs(st, kit.cardinal(ax, az))
            else:
                cap = slab(sl)
        else:
            top = n
        if slope < ridge_full and f >= 0.25:
            top, cap = n, None                                # 屋脊一帶整塊，不留一排半磚
        top = max(top, y_eave)
        thick = max(shell, int(math.ceil(dmax[i, j])) + 1)
        lo = max(y_eave, top - thick + 1)
        for y in range(lo, top + 1):
            s(x, y, z, full)
        if cap is not None:
            s(x, n, z, cap)
            tops[i, j] = n
        else:
            tops[i, j] = top
        if under is not None and (under_mask is None or under_mask[i, j]):
            s(x, lo - 1, z, under)
    return tops


def corner_lift(fr, a, b, lift, du=0.0, dv=0.0):
    """矩形 |u-du|<=a、|v-dv|<=b 四個翼角的起翹高度場（跟 kit.hip 的 lift 同一個式子），
    給自己算坡面（披檐、下簷）的屋頂加上翹角。"""
    u, v = np.abs(fr.U - du), np.abs(fr.V - dv)
    d = np.minimum(a - u, b - v).clip(0, None)
    return kit._lift(u, v, a, b, lift, None, d)


# ---------------------------------------------------------------- 屋脊

def ridge_line(p, pts, block, step=0.25, thick=1, cells=None):
    """沿局部座標的折線 [(u, v, y), ...] 疊方塊。y 是浮點數，取 floor。
    thick：每一點往下再疊幾格（屋脊有厚度）。cells 給一個 set 就只記錄不寫（呼叫端合併）。"""
    out = set()
    for (u0, v0, y0), (u1, v1, y1) in zip(pts[:-1], pts[1:]):
        L = math.hypot(u1 - u0, v1 - v0) + abs(y1 - y0)
        n = max(1, int(math.ceil(L / step)))
        for t in range(n + 1):
            a = t / float(n)
            u, v, y = u0 + (u1 - u0) * a, v0 + (v1 - v0) * a, y0 + (y1 - y0) * a
            x, z = p.fr.cell(u, v)
            yi = int(math.floor(y))
            for k in range(thick):
                out.add((x, yi - k, z))
    if cells is not None:
        cells |= out
        return out
    for x, y, z in out:
        p.set(x, y, z, block)
    return out


def top_at(tops, fr, u, v):
    """屋面在局部 (u, v) 那一格的頂 y（tile_roof 的回傳值）；遮罩外回 None。"""
    x, z = fr.cell(u, v)
    i, j = z - fr.z0, x - fr.x0
    if 0 <= i < fr.shape[0] and 0 <= j < fr.shape[1] and tops[i, j] > -999:
        return int(tops[i, j])
    return None


def seg_mask(fr, u0, v0, u1, v1, half=0.5):
    """格心離局部線段 (u0, v0)-(u1, v1) 不到 half 的格子 -> (遮罩, 沿線段的參數 t 0..1)。
    斜的屋脊用這個挑格子，每一列只有一格寬；逐點取樣的話轉個角度就變成兩格寬的鋸齒。"""
    du, dv = u1 - u0, v1 - v0
    L2 = du * du + dv * dv or 1e-9
    t = (((fr.U - u0) * du + (fr.V - v0) * dv) / L2).clip(0, 1)
    d = np.hypot(fr.U - (u0 + t * du), fr.V - (v0 + t * dv))
    return d <= half, t


def swallowtail(p, L, y, block, ext=1.6, rise=2.2, tip=None, dv=0.0, body=2, fork=0.7, half=0.5):
    """閩南式燕尾脊：沿 u 從 -L 到 L 的正脊（頂在 y、厚 body 格），兩端最後 1/4 起
    慢慢上揚、再伸出 ext 公尺、翹高 rise 公尺，末端分叉成兩股（燕子的尾巴）。
    tip：尾端最後一段的材質（剪黏常用深色或彩色收頭），None 同 block。
    格子照「離脊線不到半格」挑，轉任何角度都是一格寬。"""
    fr = p.fr
    c = max(1.5, 0.3 * L)
    au = np.abs(fr.U)
    off = np.abs(fr.V - dv)
    line = (off < half) & (au <= L + ext)
    forks = (off >= half) & (off < half + 0.8) & (au > L + ext - fork) & (au <= L + ext)
    cells = {}
    for sel, extra in ((line, 0), (forks, 1)):
        for i, j in np.argwhere(sel):
            a = float(au[i, j])
            k = max(0.0, (a - (L - c)) / (c + ext))
            yi = int(math.floor(y + rise * k ** 2)) + extra
            x, z = int(fr.X[i, j]), int(fr.Z[i, j])
            blk = tip if (tip and a > L + ext * 0.4) else block
            for q in range(body if (extra == 0 and a <= L) else 1):
                cells[(x, yi - q, z)] = blk
    for (x, yy, z), blk in cells.items():
        p.set(x, yy, z, blk)
    return cells


def chiwen(p, u, v, y, block, inward, h=2, accent=None):
    """北方宮殿式正脊兩端的鴟吻：脊端往上疊 h 格，頂上往屋脊內側捲一格。
    inward = +1 / -1：屋脊內側在 +u 還是 -u。"""
    x, z = p.fr.cell(u, v)
    for k in range(h):
        p.set(x, y + k, z, block)
    xi, zi = p.fr.cell(u + inward * 0.9, v)
    p.set(xi, y + h - 1, zi, accent or block)
    xo, zo = p.fr.cell(u - inward * 0.9, v)
    p.set(xo, y, zo, block)


def gable_face(p, cells_mask, tops, y_top_fn, fill, border=None, center=None):
    """歇山的山花：cells_mask 那一排格子，從屋面頂（tops）往上填到 y_top_fn(i, j)。
    border：每一柱最上面那格（博風板）；center：中線上半段的裝飾（懸魚、花飾）。"""
    fr = p.fr
    for i, j in np.argwhere(cells_mask):
        t0 = int(tops[i, j]) if tops[i, j] > -999 else None
        t1 = int(y_top_fn(i, j))
        if t0 is None or t1 <= t0:
            continue
        x, z = int(fr.X[i, j]), int(fr.Z[i, j])
        for y in range(t0 + 1, t1 + 1):
            blk = fill
            if border is not None and y == t1:
                blk = border
            p.set(x, y, z, blk)
    if center is not None:
        center()


# ---------------------------------------------------------------- 拱門

def arch_halfwidth(hc, w, spring):
    """半圓拱在離地板 hc 公尺處的半寬（hc 以下是直牆）。"""
    r = w / 2.0
    if hc <= spring:
        return r
    d = hc - spring
    return math.sqrt(r * r - d * d) if d < r else -1.0


def arch_rows(w, spring):
    """拱洞逐層的 (層號 k（從地板上第一格 0 起）, 格心半寬, 格底半寬)。"""
    out = []
    k = 0
    while True:
        hc = arch_halfwidth(k + 0.5, w, spring)
        hb = arch_halfwidth(k + 0.02, w, spring)
        if hb < 0:
            break
        out.append((k, hc, hb))
        k += 1
    return out


def cut_arch(p, sel, U0, y_floor, w, spring, wall_facing=None, stair_block=None, ring=None,
             ring_block=None, ceil_y=None):
    """在遮罩 sel 的範圍（通道）裡挖半圓拱：U0 是每格離拱中線的距離（|U - uc|）。
    y_floor 是地板面（人站的那一格）。拱頂兩角用倒置樓梯修圓（stair_block 是樓梯前綴，
    wall_facing(i, j) -> 樓梯朝向）。ring：拱圈（外擴一格的那一環）寫 ring_block。
    ceil_y：這一格（通常是城座頂的樓板）以上不挖空，只准放倒置樓梯（上半格仍是實心）。"""
    fr = p.fr
    rows = arch_rows(w, spring)
    for i, j in np.argwhere(sel):
        x, z = int(fr.X[i, j]), int(fr.Z[i, j])
        du = float(U0[i, j])
        for k, hc, hb in rows:
            y = y_floor + k
            if ceil_y is not None and y > ceil_y:
                break
            if du <= hc + 0.05 and (ceil_y is None or y < ceil_y):
                p.set(x, y, z, AIR)
            elif k + 0.5 > spring and du <= hb + 0.45 and stair_block and wall_facing:
                p.set(x, y, z, stairs(stair_block, wall_facing(i, j), "top"))
    if ring is not None and ring_block:
        rows2 = arch_rows(w + 2.0, spring)
        top = {k: hc for k, hc, hb in rows}
        for i, j in np.argwhere(ring):
            x, z = int(fr.X[i, j]), int(fr.Z[i, j])
            du = float(U0[i, j])
            for k, hc, hb in rows2:
                inner = top.get(k, -1.0)
                if du <= hc + 0.05 and du > inner + 0.45:
                    p.set(x, y_floor + k, z, ring_block)


# ---------------------------------------------------------------- 牆方塊連線

def walls_conn(cells, name, tall=False):
    """一組 (x, y, z) 的牆方塊 -> {(x, y, z): 方塊字串}，四向連線照鄰格有沒有牆算。
    寫進存檔的牆方塊不會自己更新連線，不算的話每一根都是孤零零的柱子。"""
    cs = set(cells)
    out = {}
    lvl = "tall" if tall else "low"
    for x, y, z in cs:
        side = {}
        for d, (dx, dz) in (("east", (1, 0)), ("west", (-1, 0)), ("south", (0, 1)), ("north", (0, -1))):
            side[d] = lvl if (x + dx, y, z + dz) in cs else "none"
        straight = (side["east"] != "none" and side["west"] != "none" and side["north"] == "none"
                    and side["south"] == "none") or (side["north"] != "none" and side["south"] != "none"
                                                     and side["east"] == "none" and side["west"] == "none")
        up = "false" if straight else "true"
        out[(x, y, z)] = "minecraft:%s[east=%s,north=%s,south=%s,up=%s,waterlogged=false,west=%s]" % (
            name, side["east"], side["north"], side["south"], up, side["west"])
    return out


STEP = {"east": (1, 0), "west": (-1, 0), "south": (0, 1), "north": (0, -1)}


def plaque_sign(p, u, v, y, face, lines, wood="dark_oak", glow=True, color="black"):
    """匾上的字：局部 (u, v) 那一格是匾（牆面），告示牌掛在它朝 face（局部方向）
    那一側的正方位鄰格 —— 壁掛告示牌只貼得住正後方那一格。"""
    x, z = p.fr.cell(u, v)
    card = kit.cardinal(*p.fr.dir(*face))
    dx, dz = STEP[card]
    p.w.sign(x + dx, y, z + dz, lines, facing=(dx, dz), wood=wood, kind="wall", glow=glow, color=color)
    return (x + dx, y, z + dz)


def panes_conn(cells, name):
    """一組 (x, y, z) 的鐵欄杆（或玻璃片）-> {(x, y, z): 方塊字串}，四向連線照鄰格算。"""
    cs = set(cells)
    out = {}
    for x, y, z in cs:
        side = {d: ("true" if (x + dx, y, z + dz) in cs else "false")
                for d, (dx, dz) in (("east", (1, 0)), ("west", (-1, 0)), ("south", (0, 1)), ("north", (0, -1)))}
        out[(x, y, z)] = "minecraft:%s[east=%s,north=%s,south=%s,waterlogged=false,west=%s]" % (
            name, side["east"], side["north"], side["south"], side["west"])
    return out


def edge_coord(fr, i, j, a, b):
    """外圈格子沿著所在那條邊的座標：靠長邊（|V| 接近 b）用 U，靠短邊用 V。
    雉堞、欄杆的花樣按它排，四條邊各自連續。"""
    u, v = float(fr.U[i, j]), float(fr.V[i, j])
    return u if (b - abs(v)) <= (a - abs(u)) else v
