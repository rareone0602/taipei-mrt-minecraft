#!/usr/bin/env python3
"""路線斷面生成器：把算好的線形掃成地下、高架、平面三種結構的方塊。

線形本身（取樣、縱斷面、離線位、變體挑選）在 domain/alignment.py。
這裡只負責「把方塊放進去」—— 每個 build_* / sec_* 的第一個參數 w 是
ports.block_sink.BlockSink，不是特定的存檔實作，所以測試可以塞 DictSink 進來。

比例 1 方塊 = 1 公尺。用法見 cli/build_line.py。
"""
import math

from mrt.domain import stacked as SK
from mrt.domain.alignment import (
    GROUND, STEP, PIER_EVERY, PLATFORM_LEN, BOX_HALF, PLAT_HALF,
    TUN_TRACK_OFF, MEZZ_DY, BOX_TOP_DY, LEVEL_DY, structure_for_ground,
    station_kind,
)

# ---- 方塊配色 ----
# 這些是「蓋成什麼樣子」的決定，屬於這一層；線形不需要知道月台是什麼材質。
CONC   = "minecraft:light_gray_concrete"
DECK   = "minecraft:smooth_stone"
WALL   = "minecraft:gray_concrete"
PIER   = "minecraft:polished_andesite"
PLAT   = "minecraft:polished_diorite"
BALLAST= "minecraft:gravel"
LINING = "minecraft:deepslate_bricks"        # 隧道襯砌
PSD    = "minecraft:glass_pane"              # 月台門
GLASS  = "minecraft:light_gray_stained_glass_pane"
STAIR  = "minecraft:smooth_stone"
SLAB   = "minecraft:smooth_stone_slab[type=bottom]"
BARS   = "minecraft:iron_bars"
GATE   = "minecraft:polished_andesite"       # 閘門機箱
LANE   = "minecraft:lime_concrete"           # 閘門通道地坪
YELLOW = "minecraft:yellow_concrete"
AIR    = "minecraft:air"
LAMP   = "minecraft:sea_lantern"             # 照明：地下段不點燈會全黑且刷怪



# ---------- 三種斷面 ----------

def sec_bridge(w, x, z, nx, nz, y, ground=GROUND, pier=False, hw=5):
    for off in range(-hw, hw + 1):
        bx, bz = round(x + nx * off), round(z + nz * off)
        w.set(bx, y - 1, bz, CONC)
        if abs(off) == hw:
            w.set(bx, y, bz, CONC); w.set(bx, y + 1, bz, WALL); w.set(bx, y + 2, bz, WALL)
        elif off == 0:
            w.set(bx, y, bz, CONC); w.set(bx, y + 1, bz, WALL)
        else:
            w.set(bx, y, bz, DECK)
        for dy in range(1, 5):                  # 橋面上方淨空
            w.set(bx, y + 3 + dy, bz, AIR)
    if pier and y - 2 > ground:
        cx, cz = round(x), round(z)
        for ddx in (-1, 0, 1):
            for ddz in (-1, 0, 1):
                for yy in range(ground - 4, y - 1):
                    w.set(cx + ddx, yy, cz + ddz, PIER)
        for off in range(-hw + 1, hw):
            w.set(round(x + nx * off), y - 2, round(z + nz * off), CONC)


def sec_ground(w, x, z, nx, nz, y, ground=GROUND, hw=5):
    """平面段：高於地面填路堤，低於地面開挖成塹道，上方一律淨空。"""
    for off in range(-(hw + 1), hw + 2):
        bx, bz = round(x + nx * off), round(z + nz * off)
        for yy in range(min(y - 1, ground - 1), y):
            w.set(bx, yy, bz, BALLAST)
        for dy in range(1, 8):
            w.set(bx, y + dy, bz, AIR)
        if abs(off) == hw + 1:
            w.set(bx, y, bz, WALL); w.set(bx, y + 1, bz, WALL)
        elif abs(off) == hw:
            w.set(bx, y, bz, CONC)
        elif off == 0:
            w.set(bx, y, bz, CONC); w.set(bx, y + 1, bz, WALL)
        else:
            w.set(bx, y, bz, DECK)


def sec_tunnel(w, x, z, nx, nz, y, light=False, hw=5, toff=TUN_TRACK_OFF):
    # 先挖出襯砌好的箱涵，再鋪走行面。hw 進站前會張開，讓軌道移到 ±8
    for off in range(-(hw + 2), hw + 3):
        bx, bz = round(x + nx * off), round(z + nz * off)
        for dy in range(-2, 8):
            edge = abs(off) >= hw + 1 or dy in (-2, 7)
            w.set(bx, y + dy, bz, LINING if edge else AIR)
    for off in range(-hw, hw + 1):
        bx, bz = round(x + nx * off), round(z + nz * off)
        w.set(bx, y - 1, bz, CONC)
        if abs(off) == hw or off == 0:
            w.set(bx, y, bz, CONC); w.set(bx, y + 1, bz, WALL)
        else:
            w.set(bx, y, bz, DECK)
    if light:
        for off in (-toff, toff):                     # 兩股道上方各一盞
            w.set(round(x + nx * off), y + 6, round(z + nz * off), LAMP)


def sec_multi(w, x, z, nx, nz, tracks, light=False, half=2):
    """多股道或上下分層的隧道斷面。tracks = [(離線位, 軌面 y), ...]。

    同高的股道併成一個箱涵：內部從最外側股道再往外 half 格，股道之間立分隔矮牆
    （跟 sec_tunnel 一樣：兩股道在 ±3 時內部是 ±5、矮牆在 0；袋狀軌三股道
    −6/0/6 時內部 ±8、矮牆在 ±3）。不同高的股道各開各的箱涵，交疊處取聯集，
    襯砌只砌在聯集的外圈 —— 分層過渡段裡下潛那股道的箱涵一路從隔壁滑到正下方，
    襯砌逐點算才不會把對方的淨空砌死。上層先鋪，下層的淨空不會把上層的樓板挖掉。
    """
    groups = {}
    for off, y in tracks:
        groups.setdefault(int(y), []).append(int(round(off)))
    interior = {}                                   # (off, y) -> 方塊
    for y in sorted(groups, reverse=True):
        offs = sorted(groups[y])
        o0, o1 = offs[0] - half, offs[-1] + half
        curbs = {o0, o1} | {(a + b) // 2 for a, b in zip(offs, offs[1:])}
        for o in range(o0, o1 + 1):
            interior.setdefault((o, y - 1), CONC)
            interior.setdefault((o, y), CONC if o in curbs else DECK)
            for dy in range(1, 7):
                interior.setdefault((o, y + dy), WALL if (dy == 1 and o in curbs) else AIR)
    shell = set()
    for o, yy in interior:
        for do in (-2, -1, 0, 1, 2):
            for dyy in (-1, 0, 1):
                c = (o + do, yy + dyy)
                if c not in interior:
                    shell.add(c)
    for o, yy in shell:
        w.set(round(x + nx * o), yy, round(z + nz * o), LINING)
    for (o, yy), blk in interior.items():
        w.set(round(x + nx * o), yy, round(z + nz * o), blk)
    if light:
        for off, y in tracks:
            w.set(round(x + nx * off), int(y) + 6, round(z + nz * off), LAMP)


def build_alignment(w, samples, ys):
    counts = {"viaduct": 0, "surface": 0, "tunnel": 0}
    for i, (x, z, ux, uz, k) in enumerate(samples):
        nx, nz = -uz, ux
        y = ys[i]
        st = structure_for_ground(y, GROUND)
        counts[st] += 1
        if st == "tunnel":
            sec_tunnel(w, x, z, nx, nz, y)
        elif st == "viaduct":
            sec_bridge(w, x, z, nx, nz, y, GROUND,
                       pier=(abs((i * STEP) % PIER_EVERY) < STEP / 2))
        else:
            sec_ground(w, x, z, nx, nz, y)
    return counts


# ---------- 樓梯 ----------

def _stair_run(w, samples, ys, s0, d, per_m, y_from, y_to, off_lo, off_hi,
               head=4, clear_dy=None, wall_offs=(), wall_ground=None,
               clear_max_dy=None):
    """鋪一段直梯，每公尺升降 0.5 m（整塊與半磚交替）。

    y_from / y_to 是「可站立的表面高度」，也就是方塊上緣。
    交替順序一定要跟行進方向對上：下坡先放整塊再放半磚，
    反過來的話每兩公尺會出現 1.5 m 落差 —— 走得下去卻爬不上來。

    頭部淨空預設挖到踏面上方 head 格；clear_dy 改成挖到「軌面 + clear_dy」，
    clear_max_dy 則是上限 —— 梯頂緊貼著頂板時，最後幾階的淨空會把頂板挖穿。
    """
    n = int(round(abs(y_to - y_from) * 2))
    sgn = 1.0 if y_to > y_from else -1.0
    out, treads = [], []
    for t in range(1, n + 1):
        si = s0 + d * t * per_m
        if not (0 <= si < len(samples)):
            break
        surf = y_from + sgn * 0.5 * t
        half = abs(surf - math.floor(surf)) > 0.25
        yb = int(math.floor(surf)) if half else int(round(surf)) - 1
        treads.append((si, yb, SLAB if half else STAIR))
        out.append((si, yb))

    def cells_at(si):
        x, z, ux, uz, _ = samples[si]
        nx, nz = -uz, ux
        return [(round(x + nx * off), round(z + nz * off)) for off in range(off_lo, off_hi + 1)]

    # 線形斜 45 度時，相鄰兩階的格子只有斜角相接：取樣點每公尺走 (0.7, 0.7)，
    # 四捨五入後兩階的格子集合可能沒有任何一對四鄰相接（六張犁、淡水的
    # 兩格寬月台樓梯就是這樣，從剖面看每一階都在，走起來卻在半路斷掉）。
    # 補法：每一階順便鋪「上一階與這一階之間那個半公尺取樣點」的格子，只補
    # 沒被任何一階用到的格子，原本的踏面一格都不動。
    main = set()
    for si, yb, blk in treads:
        main.update(cells_at(si))
    filled = set()
    per_tread = []
    for si, yb, blk in treads:
        cells = cells_at(si)
        sh = si - d * (per_m // 2)
        if per_m >= 2 and 0 <= sh < len(samples):
            for c in cells_at(sh):
                if c not in main and c not in filled:
                    filled.add(c)
                    cells.append(c)
        per_tread.append(cells)
    # 半公尺取樣點的格子也可能剛好落在原本的踏面上（線形接近 45 度時常常如此），
    # 那就沒補到。再逐階檢查一次：相鄰兩階仍然沒有任何一對四鄰相接的話，
    # 在斜角相接的那一對之間補一格（跟下一階同高），保證整段樓梯四鄰連通。
    for t in range(len(per_tread) - 1):
        a, b = per_tread[t], set(per_tread[t + 1])
        if any((ax + ddx, az + ddz) in b for ax, az in a
               for ddx, ddz in ((1, 0), (-1, 0), (0, 1), (0, -1))):
            continue
        for ax, az in a:
            hit = next(((bx, bz) for bx, bz in b if abs(bx - ax) == 1 and abs(bz - az) == 1), None)
            if hit is not None:
                bx, bz = hit
                cand = [(ax, bz), (bx, az)]
                c = next((q for q in cand if q not in main and q not in filled), cand[0])
                filled.add(c)
                per_tread[t].append(c)
                break
    for (si, yb, blk), cells in zip(treads, per_tread):
        x, z, ux, uz, _ = samples[si]
        nx, nz = -uz, ux
        top = (int(ys[si]) + clear_dy) if clear_dy is not None else yb + head
        if clear_max_dy is not None:
            top = min(top, int(ys[si]) + clear_max_dy)
        for bx, bz in cells:
            w.set(bx, yb, bz, blk)
            for yy in range(yb + 1, top + 1):
                w.set(bx, yy, bz, AIR)
        for off in wall_offs:
            bx, bz = round(x + nx * off), round(z + nz * off)
            for yy in range(yb, yb + 1 + head):
                w.set(bx, yy, bz,
                      WALL if wall_ground is None or yy < wall_ground else BARS)
    return out


# ---------- 車站 ----------

def build_station(w, samples, ys, idx, underground, label=None, grounds=None,
                  access=True, stacked=None):
    """access=False 時不蓋樣板的出入口樓梯 —— 有真實出入口
    （application/build_exits.py）的車站用那些，樣板的那座只會多出一個
    誰也不會走的洞。地下站與側式月台站都適用。

    stacked 是 domain/stacked.layout() 的版面：兩股道分到上下兩層的地下站
    （府中的側式疊式、西門那種兩線共用的島式疊式）。samples 這時是站體座標系
    （共用站體的是兩線中線的 frame，見 stacked.station_samples）。"""
    n = len(samples)
    half = int(PLATFORM_LEN / 2 / STEP)
    lo, hi = max(0, idx - half), min(n - 1, idx + half)
    if stacked is not None:
        _station_stacked(w, samples, ys, grounds, lo, hi, label, stacked, access=access)
    elif underground:
        _station_island(w, samples, ys, grounds, lo, hi, label, access=access)
    else:
        _station_side(w, samples, ys, grounds, lo, hi, label, access=access)


# ===== 地下站：島式月台 + 穿堂層 =====

def _station_island(w, samples, ys, grounds, lo, hi, label, access=True):
    """地下島式月台車站。

    北捷地下站幾乎都是島式：軌道分到兩側、月台居中，上面再疊一層穿堂。
    側式月台的話中間的軌道會把穿堂動線切成兩半，每側都得再來一組樓梯。

    分兩趟做：先把整段站體挖乾淨，再安裝設備。取樣間距只有 STEP 公尺，
    若邊挖邊裝，下一個取樣點的挖空會把剛裝好的月台門和燈具抹掉。
    """
    per_m = max(1, int(round(1.0 / STEP)))

    # ---- 第一趟：挖空 ----
    for i in range(lo, hi + 1):
        x, z, ux, uz, _ = samples[i]
        nx, nz = -uz, ux
        y = int(ys[i])
        end = i in (lo, hi)
        for off in range(-BOX_HALF, BOX_HALF + 1):
            bx, bz = round(x + nx * off), round(z + nz * off)
            for dy in range(-2, BOX_TOP_DY + 1):
                # 端面只在隧道斷面（張開後的 ±10）開洞。整面填實會把站體封死，
                # 全開又會讓上層的穿堂直接通進隧道裡。
                portal = abs(off) <= BOX_HALF - 2 and -1 <= dy <= 6
                solid = (abs(off) >= BOX_HALF - 1 or dy in (-2, BOX_TOP_DY)
                         or (end and not portal))
                w.set(bx, y + dy, bz, LINING if solid else AIR)

    # ---- 第二趟：安裝 ----
    for i in range(lo, hi + 1):
        x, z, ux, uz, _ = samples[i]
        nx, nz = -uz, ux
        y = int(ys[i])
        along = (i - lo) * STEP
        door = (along % 7.0) < 2.0

        for off in list(range(-10, -PLAT_HALF)) + list(range(PLAT_HALF + 1, 11)):
            bx, bz = round(x + nx * off), round(z + nz * off)
            w.set(bx, y - 1, bz, CONC)
            w.set(bx, y, bz, DECK)                      # 兩側軌道走行面

        for off in range(-PLAT_HALF, PLAT_HALF + 1):    # 島式月台
            bx, bz = round(x + nx * off), round(z + nz * off)
            w.set(bx, y - 1, bz, CONC)
            w.set(bx, y, bz, CONC)
            w.set(bx, y + 1, bz, YELLOW if abs(off) == PLAT_HALF - 1 else PLAT)

        for off in (-PLAT_HALF, PLAT_HALF):             # 月台門
            bx, bz = round(x + nx * off), round(z + nz * off)
            for yy in range(y + 2, y + MEZZ_DY):
                w.set(bx, yy, bz, AIR if door else PSD)

        for off in range(-(BOX_HALF - 2), BOX_HALF - 1):
            w.set(round(x + nx * off), y + MEZZ_DY, round(z + nz * off), CONC)

        if (along % 8.0) < STEP:                        # 照明
            for off in (-10, -3, 3, 10):
                w.set(round(x + nx * off), y + MEZZ_DY - 1, round(z + nz * off), LAMP)
            for off in (-7, 0, 7):
                w.set(round(x + nx * off), y + BOX_TOP_DY - 1, round(z + nz * off), LAMP)

    _gates(w, samples, ys, lo + 14 * per_m, per_m)
    for a0 in (24, 48):
        _plat_stair(w, samples, ys, lo + a0 * per_m, per_m)
    if access:
        _station_access(w, samples, ys, grounds, lo, hi, label)
    if label:
        _plat_signs(w, samples, ys, lo, hi, label)


def _gates(w, samples, ys, s0, per_m, floor_dy=MEZZ_DY, half=BOX_HALF - 2):
    """驗票閘門：橫跨整個穿堂層，把付費區與非付費區隔開。

    出入口在 lo+6 一端、月台樓梯在另一端，閘門橫在中間才擋得住 ——
    只擺一小段的話旁邊就繞過去了。

    floor_dy 是穿堂樓板相對軌面的高差（預設是地下站的 MEZZ_DY），
    half 是閘門列的半寬；側式月台站的穿堂層用同一組閘門，只是樓板高度不同。
    """
    for t in range(2 * per_m):
        si = s0 + t
        if not (0 <= si < len(samples)):
            continue
        x, z, ux, uz, _ = samples[si]
        nx, nz = -uz, ux
        ym = int(ys[si]) + floor_dy
        for off in range(-half, half + 1):
            bx, bz = round(x + nx * off), round(z + nz * off)
            if off % 3 == 0:                            # 通行閘道
                w.set(bx, ym, bz, LANE)
                for yy in range(ym + 1, ym + 4):
                    w.set(bx, yy, bz, AIR)
            else:
                w.set(bx, ym + 1, bz, GATE)
                for yy in range(ym + 2, ym + 4):
                    w.set(bx, yy, bz, AIR)


def _plat_stair(w, samples, ys, s0, per_m, off_lo=-3, off_hi=3):
    """穿堂層下到月台的樓梯，順便在樓板上開口。off_lo..off_hi 是踏面的離線位
    （島式月台放在正中央 −3..3，側式疊式的放在月台上）。"""
    y0 = int(ys[min(s0, len(ys) - 1)])
    steps = _stair_run(w, samples, ys, s0, 1, per_m,
                       y0 + MEZZ_DY + 1, y0 + 2, off_lo, off_hi,
                       clear_dy=BOX_TOP_DY - 1)
    for si, yb in steps:                                # 開口兩側加欄杆
        x, z, ux, uz, _ = samples[si]
        nx, nz = -uz, ux
        ym = int(ys[si]) + MEZZ_DY
        for off in (off_lo - 1, off_hi + 1):
            bx, bz = round(x + nx * off), round(z + nz * off)
            w.set(bx, ym, bz, CONC)
            w.set(bx, ym + 1, bz, BARS)


def _level_stair(w, samples, ys, s0, per_m, drop, off_lo, off_hi):
    """疊式站上層月台下到下層月台的樓梯（站立面從軌面 +2 降到 +2 − drop）。

    頭部淨空最多挖到軌面 +5：梯頂就在上層月台上，四格淨空會把 +6 的穿堂樓板
    挖穿。上層月台被挖開的那幾階兩側圍欄杆，洞的盡頭橫著再圍一排 —— 從月台
    另一頭走過來的人，不圍的話一步就踩進四格深的洞。
    """
    y0 = int(ys[min(s0, len(ys) - 1)])
    steps = _stair_run(w, samples, ys, s0, 1, per_m, y0 + 2, y0 + 2 - drop,
                       off_lo, off_hi, head=4, clear_max_dy=5)
    opened = []
    for si, yb in steps:
        opened.append(yb + 4 >= int(ys[si]) + 1)      # 淨空挖到上層月台面（+1）
    for k, (si, yb) in enumerate(steps):
        x, z, ux, uz, _ = samples[si]
        nx, nz = -uz, ux
        stand = int(ys[si]) + 2
        if opened[k] and yb < int(ys[si]):
            for off in (off_lo - 1, off_hi + 1):
                w.set(round(x + nx * off), stand, round(z + nz * off), BARS)
        elif not opened[k] and k > 0 and opened[k - 1]:
            for off in range(off_lo - 1, off_hi + 2):
                w.set(round(x + nx * off), stand, round(z + nz * off), BARS)
    return steps


def _station_access(w, samples, ys, grounds, lo, hi, label):
    """穿堂層 -> 地面的樓梯與地面出入口建築。

    樓梯走在站體外側 off 13~17，深站要 2 公尺水平才降 1 公尺，
    最深的那條線一段就要 76 公尺 —— 所以不能夾在月台長度裡。
    """
    per_m = max(1, int(round(1.0 / STEP)))
    sd = min(lo + 6 * per_m, len(samples) - 1)
    y0 = int(ys[sd])
    ym = y0 + MEZZ_DY + 1                               # 穿堂層可站立高度
    g0 = int(grounds[sd]) if grounds is not None else GROUND
    # g0 是地表最上面那塊方塊，人站在它上面時腳在 g0+1；樓梯要爬到 g0+1
    # 才接得平站屋的地坪（_hall 把地坪墊到 g0）。原本爬到 g0 就停，
    # 梯頂到站屋差一格 —— 走得下去，上來要跳。
    n = g0 + 1 - ym
    if n < 2:
        return
    need = (2 * n + 12) * per_m
    d = 1 if sd + need < len(samples) else -1
    if not (0 <= sd + d * need < len(samples)):
        return

    for t in range(-2 * per_m, 2 * per_m + 1):          # 穿出站體側牆的通道
        si = sd + t
        if not (0 <= si < len(samples)):
            continue
        x, z, ux, uz, _ = samples[si]
        nx, nz = -uz, ux
        ymm = int(ys[si]) + MEZZ_DY
        for off in range(BOX_HALF - 1, 18):
            bx, bz = round(x + nx * off), round(z + nz * off)
            w.set(bx, ymm, bz, CONC)
            for yy in range(ymm + 1, ymm + 4):
                w.set(bx, yy, bz, AIR)
            w.set(bx, ymm + 4, bz, LINING)

    _stair_run(w, samples, ys, sd + d * 2 * per_m, d, per_m, ym, g0 + 1, 13, 17,
               head=4, wall_offs=(12, 18), wall_ground=g0)
    # 樓梯最後幾階的頭部淨空會把地表挖穿，站屋要往回罩到 t=-9，
    # 否則出入口前面會留一條沒有蓋子的壕溝。
    _hall(w, samples, ys, sd + d * (2 + 2 * n) * per_m, d, per_m, g0, label,
          t0=-9, t1=6, o0=12, o1=18, floor_t0=1, door_t=6)


def _hall(w, samples, ys, s0, d, per_m, g0, label, t0, t1, o0, o1,
          floor_t0, door_t, open_end=None, gate_t=None):
    """地面站屋：t0..t1 是沿線範圍、o0/o1 是兩側牆的離線位（皆相對 s0）。

    open_end 那一端不封（樓梯從那裡進出），door_t 那一端開門通到街上。
    """
    mid = (o0 + o1) // 2
    for t in range(t0, t1 + 1):
        si = s0 + d * t * per_m
        if not (0 <= si < len(samples)):
            continue
        x, z, ux, uz, _ = samples[si]
        nx, nz = -uz, ux
        cap = t in (t0, t1) and t != open_end
        for off in range(o0 - 1, o1 + 2):
            bx, bz = round(x + nx * off), round(z + nz * off)
            if o0 <= off <= o1:
                if t >= floor_t0:
                    for yy in range(g0 - 3, g0 + 1):
                        w.set(bx, yy, bz, CONC)         # 墊平地坪
                side = off in (o0, o1) or cap
                for yy in range(g0 + 1, g0 + 5):
                    door = (t == door_t and mid - 1 <= off <= mid + 1
                            and yy <= g0 + 3)
                    if side and not door:
                        w.set(bx, yy, bz, GLASS if g0 + 2 <= yy <= g0 + 3 else CONC)
                    else:
                        w.set(bx, yy, bz, AIR)
                if t % 4 == 0 and off == mid:
                    w.set(bx, g0 + 4, bz, LAMP)
            w.set(bx, g0 + 5, bz, CONC)                 # 屋頂（含出簷）
        if gate_t is not None and t in (gate_t, gate_t + 1):
            for off in range(o0 + 1, o1):
                bx, bz = round(x + nx * off), round(z + nz * off)
                if (off - mid) % 3 == 0:
                    w.set(bx, g0, bz, LANE)
                    for yy in range(g0 + 1, g0 + 4):
                        w.set(bx, yy, bz, AIR)
                else:
                    w.set(bx, g0 + 1, bz, GATE)
                    for yy in range(g0 + 2, g0 + 4):
                        w.set(bx, yy, bz, AIR)
    if label:
        st = door_t + (1 if door_t == t1 else -1)
        si = s0 + d * st * per_m
        if 0 <= si < len(samples):
            x, z, ux, uz, _ = samples[si]
            nx, nz = -uz, ux
            bx, bz = round(x + nx * mid), round(z + nz * mid)
            w.set(bx, g0, bz, CONC)
            w.sign(bx, g0 + 1, bz, [label[0], label[1], label[2], "出口 Exit"],
                   facing=(nx, nz))


def _plat_signs(w, samples, ys, lo, hi, label, offs=(PLAT_HALF, -PLAT_HALF), dy0=0):
    """月台門上每 20 m 一面站名牌，牌面朝月台內側。offs 是月台門的離線位，
    dy0 是這一層軌面相對線形軌面的高差（疊式站的下層是 −LEVEL_H）。"""
    ref, zh, en = label
    per_m = max(1, int(round(1.0 / STEP)))
    for i in range(lo + 20 * per_m, hi - 8 * per_m, 20 * per_m):
        x, z, ux, uz, _ = samples[i]
        nx, nz = -uz, ux
        y = int(ys[i]) + dy0
        for off in offs:
            face = (-nx, -nz) if off > 0 else (nx, nz)
            bx, bz = round(x + nx * off), round(z + nz * off)
            w.sign(bx, y + 2, bz, [ref, zh, en, ""], facing=face)


# ===== 疊式地下站：兩股道分到上下兩層 =====

def _station_stacked(w, samples, ys, grounds, lo, hi, label, lay, access=True):
    """雙層地下站（domain/stacked.py）。上層與島式站同一套尺寸 —— 穿堂仍在
    軌面 +7，出入口、轉乘通道與驗證工具全部不必改；下層整層複製到 LEVEL_H
    格底下，頂板就是上層的底板。lay 是 stacked.layout() 的版面：側式疊式
    （府中）每層一股道、月台在同一側；共用島式（西門）每層兩股道各屬一條線。

    跟島式站一樣分兩趟：先把 21 格高的箱涵挖乾淨，再安裝兩層的設備。
    端面在每一層的隧道斷面高度各開一個洞（上層 dy −1..6、下層 dy −9..−3）。
    """
    per_m = max(1, int(round(1.0 / STEP)))
    H, bot = SK.LEVEL_H, SK.BOX_BOTTOM_DY

    for i in range(lo, hi + 1):                         # ---- 第一趟：挖空 ----
        x, z, ux, uz, _ = samples[i]
        nx, nz = -uz, ux
        y = int(ys[i])
        end = i in (lo, hi)
        for off in range(-BOX_HALF, BOX_HALF + 1):
            bx, bz = round(x + nx * off), round(z + nz * off)
            for dy in range(bot, BOX_TOP_DY + 1):
                portal = abs(off) <= BOX_HALF - 2 and (-1 <= dy <= 6 or bot + 1 <= dy <= -3)
                solid = (abs(off) >= BOX_HALF - 1 or dy in (bot, -2, BOX_TOP_DY)
                         or (end and not portal))
                w.set(bx, y + dy, bz, LINING if solid else AIR)

    for dy0 in (0, -H):                                 # ---- 第二趟：兩層月台 ----
        _stacked_level(w, samples, ys, lo, hi, dy0, lay)

    for i in range(lo, hi + 1):                         # 穿堂樓板與照明
        x, z, ux, uz, _ = samples[i]
        nx, nz = -uz, ux
        y = int(ys[i])
        for off in range(-(BOX_HALF - 2), BOX_HALF - 1):
            w.set(round(x + nx * off), y + MEZZ_DY, round(z + nz * off), CONC)
        if (((i - lo) * STEP) % 8.0) < STEP:
            for off in (-7, 0, 7):
                w.set(round(x + nx * off), y + BOX_TOP_DY - 1, round(z + nz * off), LAMP)

    _gates(w, samples, ys, lo + 14 * per_m, per_m)
    s0, s1 = lay["stair"]
    for a0 in (24, 48):
        _plat_stair(w, samples, ys, lo + a0 * per_m, per_m, off_lo=s0, off_hi=s1)
    l0, l1 = lay["lstair"]
    _level_stair(w, samples, ys, lo + 4 * per_m, per_m, H, l0, l1)
    if access:
        _station_access(w, samples, ys, grounds, lo, hi, label)
    if label:
        for dy0 in (0, -H):
            _plat_signs(w, samples, ys, lo, hi, label, offs=lay["psd"], dy0=dy0)


def _stacked_level(w, samples, ys, lo, hi, dy0, lay):
    """疊式站的一層：軌面在線形軌面 + dy0。月台鋪面（含月台門那一排）、
    警示帶、月台門、其餘都是走行面；燈掛在這一層頂板底下。"""
    p0, p1 = lay["plat"]
    plat = set(range(p0, p1 + 1)) | set(lay["psd"])
    for i in range(lo, hi + 1):
        x, z, ux, uz, _ = samples[i]
        nx, nz = -uz, ux
        y = int(ys[i]) + dy0
        along = (i - lo) * STEP
        door = (along % 7.0) < 2.0
        for off in range(-(BOX_HALF - 2), BOX_HALF - 1):
            bx, bz = round(x + nx * off), round(z + nz * off)
            w.set(bx, y - 1, bz, CONC)
            if off in plat:
                w.set(bx, y, bz, CONC)
                w.set(bx, y + 1, bz, YELLOW if off in lay["yellow"] else PLAT)
            else:
                w.set(bx, y, bz, DECK)
        for off in lay["psd"]:
            bx, bz = round(x + nx * off), round(z + nz * off)
            for yy in range(y + 2, y + MEZZ_DY):
                w.set(bx, yy, bz, AIR if door else PSD)
        if (along % 8.0) < STEP:
            for off in (-10, -3, 3, 10):
                w.set(round(x + nx * off), y + MEZZ_DY - 1, round(z + nz * off), LAMP)


# ===== 高架／平面站：側式月台 =====

def _station_side(w, samples, ys, grounds, lo, hi, label, access=True):
    """側式月台車站：軌道走行面與區間同高，月台面再高 1 m。

    兩座月台各自封閉，靠一層穿堂（_side_concourse）串起來：閘門在穿堂層，
    每座月台一座樓梯。真實出入口也接到穿堂層；access=False 時不蓋樣板的
    地面樓梯（它只通到 + 側月台，有真實出入口的站用不到）。
    """
    roof_h = 6
    for i in range(lo, hi + 1):                         # 第一趟：清出站體
        x, z, ux, uz, _ = samples[i]
        nx, nz = -uz, ux
        y = int(ys[i])
        for off in range(-11, 12):
            bx, bz = round(x + nx * off), round(z + nz * off)
            for dy in range(1, roof_h + 1):
                w.set(bx, y + dy, bz, AIR)

    for i in range(lo, hi + 1):                         # 第二趟：安裝
        x, z, ux, uz, _ = samples[i]
        nx, nz = -uz, ux
        y = int(ys[i])
        end = i in (lo, hi)
        along = (i - lo) * STEP
        door = (along % 7.0) < 2.0

        for off in range(-5, 6):
            bx, bz = round(x + nx * off), round(z + nz * off)
            w.set(bx, y - 1, bz, CONC)
            w.set(bx, y, bz, DECK)

        for off in (-5, 5):                             # 月台門
            bx, bz = round(x + nx * off), round(z + nz * off)
            for yy in range(y + 1, y + 5):
                w.set(bx, yy, bz, AIR if door else PSD)

        for off in list(range(-10, -5)) + list(range(6, 11)):
            bx, bz = round(x + nx * off), round(z + nz * off)
            w.set(bx, y - 1, bz, CONC)
            w.set(bx, y, bz, CONC)
            w.set(bx, y + 1, bz, YELLOW if abs(off) == 6 else PLAT)
            if abs(off) == 10 or end:
                for yy in range(y + 2, y + roof_h):
                    w.set(bx, yy, bz, GLASS if not end else CONC)
        for off in range(-10, 11):
            w.set(round(x + nx * off), y + roof_h, round(z + nz * off), CONC)

        if (along % 8.0) < STEP:                        # 照明
            for off in (-8, 0, 8):
                w.set(round(x + nx * off), y + roof_h - 1, round(z + nz * off), LAMP)

    _side_concourse(w, samples, ys, grounds, lo, hi)
    if label:
        place_signs(w, samples, ys, lo, hi, label)
    if access:
        build_entrance(w, samples, ys, lo, hi, grounds, label)


def _side_concourse(w, samples, ys, grounds, lo, hi):
    """側式月台車站的穿堂層：閘門與往兩座月台的樓梯都在這一層，真實出入口
    （application/build_exits.py）也接到這裡。

    放哪一層由 domain/alignment.py 的 station_kind 決定 —— 整站只看中心
    取樣點判斷一次，各處的高度再以「int(ys[i]) + LEVEL_DY[型態]」逐點算，
    站內軌面有坡時樓板跟著走（與地下站的穿堂層同一套規則）：
      "under"  橋下穿堂：樓板在軌面 -7，橋面板（-1）就是它的頂板；
               淨空 5 格，側牆玻璃，橋墩穿過大廳
      "over"   天橋式穿堂：樓板在軌面 +7，疊在站屋屋頂（+6）上，
               頂板在 +11，側牆玻璃

    閘門在 lo+14 m（與地下站相同，出入口的側牆開洞在 lo+7）。兩座月台樓梯
    都擺在 hi 端、月台最外側兩排（|off| 8..9），梯底落在付費區：
      · 擺在 lo 端的話，"over" 的樓梯會在穿堂樓板上開一條 lo+1..lo+11 的洞，
        正好貼著出入口在 lo+5..lo+9 開的門 —— 出門一步就是三格深的梯井；
      · "under" 的樓梯 16 m 長，從 lo 端起算梯底會踩進 lo+14 的閘門列。
    月台最外側兩排給了樓梯，警戒帶（|off| 6）與內側一排仍走得通。
    """
    per_m = max(1, int(round(1.0 / STEP)))
    mid = (lo + hi) // 2
    g_mid = int(grounds[mid]) if grounds is not None else GROUND
    kind = station_kind(int(ys[mid]), g_mid)
    if kind == "tunnel":                                # 地下站不會走到這裡
        return
    dy = LEVEL_DY[kind]                                 # 站立面相對軌面
    under = kind == "under"

    def levels(y):
        """(樓板方塊, 頂板方塊)"""
        return y + dy - 1, (y - 1 if under else y + dy + 3)

    # ---- 樓板、淨空、側牆、端牆、照明 ----
    for i in range(lo, hi + 1):
        x, z, ux, uz, _ = samples[i]
        nx, nz = -uz, ux
        y = int(ys[i])
        fl, ceil = levels(y)
        end = i in (lo, hi)
        for off in range(-11, 12):
            bx, bz = round(x + nx * off), round(z + nz * off)
            side = abs(off) == 11
            w.set(bx, fl, bz, CONC)
            w.set(bx, ceil, bz, CONC)                   # "under" 的 |off|<=10 就是橋面板
            for yy in range(fl + 1, ceil):
                w.set(bx, yy, bz, CONC if end else (GLASS if side else AIR))
        if not end and (((i - lo) * STEP) % 8.0) < STEP:  # 端牆不嵌燈
            for off in (-7, 0, 7):
                w.set(round(x + nx * off), ceil - 1, round(z + nz * off), LAMP)

    _gates(w, samples, ys, lo + 14 * per_m, per_m, floor_dy=dy - 1)

    # ---- 橋墩 ----
    # 區間的 sec_bridge 在車站之前就蓋了，上面的掏空會把大廳裡那一截切掉；
    # 照 sec_bridge 的位置（同一個取樣條件、同樣以中心點取整的 3x3）補回來，
    # 橋面板在大廳裡才有東西撐著。樓板那一格維持 CONC，柱子像是穿樓板而過。
    if under:
        for i in range(lo, hi + 1):
            if abs((i * STEP) % PIER_EVERY) >= STEP / 2:
                continue
            x, z, _, _, _ = samples[i]
            y = int(ys[i])
            g = int(grounds[i]) if grounds is not None else GROUND
            if y - 2 <= g:
                continue
            fl, _ = levels(y)
            cx, cz = round(x), round(z)
            for ddx in (-1, 0, 1):
                for ddz in (-1, 0, 1):
                    for yy in range(fl + 1, y - 1):
                        w.set(cx + ddx, yy, cz + ddz, PIER)

    # ---- 月台樓梯 ----
    # 每座月台一座，2 格寬，從 hi 端往回退 run+1 m 起算；"under" 從穿堂往上爬
    # 到月台，"over" 從穿堂往下走。y_from / y_to 都是站立面：梯底那一階半磚
    # 與樓板齊平、梯頂整塊與月台面（y+1）齊平，兩端才不會差一格。
    run = 2 * abs(dy - 2)
    s0 = hi - (run + 1) * per_m
    if s0 <= lo:
        return
    y0 = int(ys[s0])
    for off_lo, off_hi in ((8, 9), (-9, -8)):
        _side_stair(w, samples, ys, s0, per_m, y0 + dy, y0 + 2, off_lo, off_hi,
                    under, levels)


def _side_stair(w, samples, ys, s0, per_m, y_from, y_to, off_lo, off_hi,
                under, levels):
    """一座月台樓梯，連同它在月台面或穿堂樓板上開的洞周圍的欄杆。

    頭部淨空（4 格）會自動把橋面板與月台面（"under"）或站屋屋頂與穿堂樓板
    （"over"）挖開；clear_max_dy 擋住它，免得挖穿站屋屋頂或穿堂頂板。
    """
    head = 4
    steps = _stair_run(w, samples, ys, s0, 1, per_m, y_from, y_to, off_lo, off_hi,
                       head=head, clear_max_dy=(5 if under else (y_from - y_to) + 2))
    if not steps:
        return
    sgn = 1.0 if y_to > y_from else -1.0
    sd = 1 if off_lo > 0 else -1
    # 每一階：踏面站立高度、是否把「走的那一層」的樓板挖開了
    info = []
    for k, (si, yb) in enumerate(steps):
        y = int(ys[si])
        fl, _ = levels(y)
        walk_blk = (y + 1) if under else fl               # 月台面 / 穿堂樓板
        foot = int(math.floor(y_from + sgn * 0.5 * (k + 1)))
        info.append((si, yb + head >= walk_blk, walk_blk + 1, foot))
    for k, (si, opened, stand, foot) in enumerate(info):
        x, z, ux, uz, _ = samples[si]
        nx, nz = -uz, ux
        if opened and stand - foot >= 2:
            # 洞口兩側：月台側只圍內側那一排（外側是站屋玻璃牆）；穿堂層
            # 兩側都圍，靠牆那一排太窄，別讓人從那裡掉下去
            for off in ((7,) if under else (7, 10)):
                w.set(round(x + nx * sd * off), stand, round(z + nz * sd * off), BARS)
        nb = [info[j][1] for j in (k - 1, k + 1) if 0 <= j < len(info)]
        if not opened and any(nb):
            # 洞的盡頭：這一格樓板還在、隔壁已經是洞，橫著圍一排
            for off in range(off_lo, off_hi + 1):
                w.set(round(x + nx * off), stand, round(z + nz * off), BARS)


def place_signs(w, samples, ys, lo, hi, label):
    """月台兩側每 20 m 立一面站名牌，牌面朝月台內側（朝軌道）。"""
    ref, zh, en = label
    per_m = max(1, int(round(1.0 / STEP)))
    for i in range(lo + 8 * per_m, hi - 6 * per_m, 20 * per_m):
        x, z, ux, uz, _ = samples[i]
        nx, nz = -uz, ux
        y = int(ys[i])
        for off, face in ((9, (-nx, -nz)), (-9, (nx, nz))):
            bx, bz = round(x + nx * off), round(z + nz * off)
            w.sign(bx, y + 2, bz, [ref, zh, en, ""], facing=face)


def build_entrance(w, samples, ys, lo, hi, grounds=None, label=None):
    """高架站出入口樓梯：從真實地面爬到月台面。

    階高一定要從當地地面 grounds[] 起算。之前寫死成常數 GROUND=64，
    地面在 71 m 的地方樓梯就從地下 7 m 才開始，上面只剩一口沒有階梯的直井。
    """
    per_m = max(1, int(round(1.0 / STEP)))
    start = min(lo + 4 * per_m, len(ys) - 1)
    g0 = int(grounds[start]) if grounds is not None else GROUND
    y_plat = int(ys[start]) + 2
    # 站在地表方塊 g0 上面時腳在 g0+1，樓梯從那裡起算才接得平站廳地坪
    need = (abs(y_plat - g0 - 1) * 2 + 4) * per_m
    d = 1 if start + need < len(samples) else -1
    if not (0 <= start + d * need < len(samples)):
        return
    steps = _stair_run(w, samples, ys, start, d, per_m, g0 + 1, y_plat, 11, 13,
                       head=4, wall_offs=(10, 14), wall_ground=g0)
    if not steps:
        return
    # 樓梯腳下的地面站廳，閘門擺在裡面。平面站的月台就在地面高度，
    # 站廳擺在 off 9 會把月台外側兩排與玻璃牆蓋掉，得整個往外挪到月台外。
    o0 = 11 if y_plat - g0 <= 6 else 9
    _hall(w, samples, ys, start, d, per_m, g0, label, t0=-11, t1=0,
          o0=o0, o1=o0 + 8, floor_t0=-11, door_t=-11, open_end=0, gate_t=-4)
    si, _ = steps[-1]
    for s in range(max(0, si - per_m), min(len(samples), si + 2 * per_m)):
        x, z, ux, uz, _ = samples[s]                    # 梯頂平台，接上月台面
        nx, nz = -uz, ux
        yb = int(ys[s]) + 1
        for off in range(10, 14):
            bx, bz = round(x + nx * off), round(z + nz * off)
            w.set(bx, yb, bz, STAIR)
            for yy in range(yb + 1, yb + 5):
                w.set(bx, yy, bz, AIR)
