#!/usr/bin/env python3
"""路線斷面生成器：把算好的線形掃成地下、高架、平面三種結構的方塊。

線形本身（取樣、縱斷面、離線位、變體挑選）在 domain/alignment.py。
這裡只負責「把方塊放進去」—— 每個 build_* / sec_* 的第一個參數 w 是
ports.block_sink.BlockSink，不是特定的存檔實作，所以測試可以塞 DictSink 進來。

比例 1 方塊 = 1 公尺。用法見 cli/build_line.py。
"""
import math

from mrt.domain.alignment import (
    GROUND, STEP, PIER_EVERY, PLATFORM_LEN, BOX_HALF, PLAT_HALF,
    TUN_TRACK_OFF, MEZZ_DY, BOX_TOP_DY, structure_for_ground,
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
               head=4, clear_dy=None, wall_offs=(), wall_ground=None):
    """鋪一段直梯，每公尺升降 0.5 m（整塊與半磚交替）。

    y_from / y_to 是「可站立的表面高度」，也就是方塊上緣。
    交替順序一定要跟行進方向對上：下坡先放整塊再放半磚，
    反過來的話每兩公尺會出現 1.5 m 落差 —— 走得下去卻爬不上來。
    """
    n = int(round(abs(y_to - y_from) * 2))
    sgn = 1.0 if y_to > y_from else -1.0
    out = []
    for t in range(1, n + 1):
        si = s0 + d * t * per_m
        if not (0 <= si < len(samples)):
            break
        surf = y_from + sgn * 0.5 * t
        half = abs(surf - math.floor(surf)) > 0.25
        yb = int(math.floor(surf)) if half else int(round(surf)) - 1
        blk = SLAB if half else STAIR
        x, z, ux, uz, _ = samples[si]
        nx, nz = -uz, ux
        top = (int(ys[si]) + clear_dy) if clear_dy is not None else yb + head
        for off in range(off_lo, off_hi + 1):
            bx, bz = round(x + nx * off), round(z + nz * off)
            w.set(bx, yb, bz, blk)
            for yy in range(yb + 1, top + 1):
                w.set(bx, yy, bz, AIR)
        for off in wall_offs:
            bx, bz = round(x + nx * off), round(z + nz * off)
            for yy in range(yb, yb + 1 + head):
                w.set(bx, yy, bz,
                      WALL if wall_ground is None or yy < wall_ground else BARS)
        out.append((si, yb))
    return out


# ---------- 車站 ----------

def build_station(w, samples, ys, idx, underground, label=None, grounds=None,
                  access=True):
    """access=False 時地下站不蓋樣板的出入口樓梯 —— 有真實出入口
    （application/build_exits.py）的車站用那些，樣板的那座只會多出一個
    誰也不會走的洞。"""
    n = len(samples)
    half = int(PLATFORM_LEN / 2 / STEP)
    lo, hi = max(0, idx - half), min(n - 1, idx + half)
    if underground:
        _station_island(w, samples, ys, grounds, lo, hi, label, access=access)
    else:
        _station_side(w, samples, ys, grounds, lo, hi, label)


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


def _gates(w, samples, ys, s0, per_m):
    """驗票閘門：橫跨整個穿堂層，把付費區與非付費區隔開。

    出入口在 lo+6 一端、月台樓梯在另一端，閘門橫在中間才擋得住 ——
    只擺一小段的話旁邊就繞過去了。
    """
    for t in range(2 * per_m):
        si = s0 + t
        if not (0 <= si < len(samples)):
            continue
        x, z, ux, uz, _ = samples[si]
        nx, nz = -uz, ux
        ym = int(ys[si]) + MEZZ_DY
        for off in range(-(BOX_HALF - 2), BOX_HALF - 1):
            bx, bz = round(x + nx * off), round(z + nz * off)
            if off % 3 == 0:                            # 通行閘道
                w.set(bx, ym, bz, LANE)
                for yy in range(ym + 1, ym + 4):
                    w.set(bx, yy, bz, AIR)
            else:
                w.set(bx, ym + 1, bz, GATE)
                for yy in range(ym + 2, ym + 4):
                    w.set(bx, yy, bz, AIR)


def _plat_stair(w, samples, ys, s0, per_m):
    """穿堂層下到月台的樓梯，順便在樓板上開口。"""
    y0 = int(ys[min(s0, len(ys) - 1)])
    steps = _stair_run(w, samples, ys, s0, 1, per_m,
                       y0 + MEZZ_DY + 1, y0 + 2, -3, 3,
                       clear_dy=BOX_TOP_DY - 1)
    for si, yb in steps:                                # 開口兩側加欄杆
        x, z, ux, uz, _ = samples[si]
        nx, nz = -uz, ux
        ym = int(ys[si]) + MEZZ_DY
        for off in (-4, 4):
            bx, bz = round(x + nx * off), round(z + nz * off)
            w.set(bx, ym, bz, CONC)
            w.set(bx, ym + 1, bz, BARS)


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


def _plat_signs(w, samples, ys, lo, hi, label):
    """月台門上每 20 m 一面站名牌，牌面朝月台內側。"""
    ref, zh, en = label
    per_m = max(1, int(round(1.0 / STEP)))
    for i in range(lo + 20 * per_m, hi - 8 * per_m, 20 * per_m):
        x, z, ux, uz, _ = samples[i]
        nx, nz = -uz, ux
        y = int(ys[i])
        for off, face in ((PLAT_HALF, (-nx, -nz)), (-PLAT_HALF, (nx, nz))):
            bx, bz = round(x + nx * off), round(z + nz * off)
            w.sign(bx, y + 2, bz, [ref, zh, en, ""], facing=face)


# ===== 高架／平面站：側式月台 =====

def _station_side(w, samples, ys, grounds, lo, hi, label):
    """側式月台車站：軌道走行面與區間同高，月台面再高 1 m。"""
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

    if label:
        place_signs(w, samples, ys, lo, hi, label)
    build_entrance(w, samples, ys, lo, hi, grounds, label)


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
