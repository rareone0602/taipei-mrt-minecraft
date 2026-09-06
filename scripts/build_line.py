#!/usr/bin/env python3
"""通用路線生成器：依 OSM 的 tunnel/bridge 標籤蓋出地下、高架、平面三種斷面。

比例 1 方塊 = 1 公尺。縱斷面用最大坡度限制平滑過渡（真實捷運約 3.5~5%），
所以隧道口前會自然出現引道，不會有垂直斷崖。

用法:
    ./.venv/bin/python scripts/build_line.py --lines BR R Y
    ./.venv/bin/python scripts/build_line.py --all
"""
import sys, os, json, csv, math, argparse, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcworld import World

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

GROUND     = 64        # 超平坦地表最上層方塊
STEP       = 0.5       # 沿線取樣間距（公尺）
MAX_GRADE  = 0.04      # 最大坡度 4%
PIER_EVERY = 25        # 橋墩間距

# 各型態的走行面相對地面高度
PROFILE = {"bridge": 13, "ground": 1, "tunnel": -20}

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
LAMP   = "minecraft:sea_lantern"           # 照明：地下段不點燈會全黑且刷怪

PLATFORM_LEN = 70

# ---- 站體尺寸（dy 皆相對走行面 y）----
# 地下站是「島式月台 + 上方穿堂層」的雙層箱涵：
#   dy -2 底板 / y 走行面 / y+1 月台面 / dy 6 穿堂樓板 / dy 10 頂板
# 共 13 格高，所以 build_world 的隧道分層必須拉到 15 m 間距。
BOX_HALF      = 12     # 站體半寬（含 2 格襯砌）
PLAT_HALF     = 6      # 島式月台半寬 -> 13 m 寬
STN_TRACK_OFF = 8      # 站內軌道中心離線位
TUN_TRACK_OFF = 3      # 區間隧道軌道中心離線位
MEZZ_DY       = 6      # 穿堂層樓板
BOX_TOP_DY    = 10     # 站體頂板
FLARE_M       = 40     # 軌道由 ±3 張開到 ±8 的過渡長度


def resample(pts, kinds, step):
    """等距重新取樣，回傳 (x, z, ux, uz, kind)"""
    out, acc = [], 0.0
    for i in range(len(pts) - 1):
        (x0, z0), (x1, z1) = pts[i], pts[i + 1]
        seg = math.hypot(x1 - x0, z1 - z0)
        if seg < 1e-9:
            continue
        ux, uz = (x1 - x0) / seg, (z1 - z0) / seg
        k = kinds[i] if i < len(kinds) else "ground"
        t = -acc
        while t < seg:
            if t >= 0:
                out.append((x0 + ux * t, z0 + uz * t, ux, uz, k))
            t += step
        acc = (acc + seg) % step
    return _smooth_tangents(out, step)


def drop_reversal(pts, kinds, thresh=140.0):
    """砍掉折線裡原地折返的那一段，只留較長的一半。

    OSM relation 串接出來的幾何偶爾會走到底再原路折回（安坑輕軌終點就有一處
    整整 180 度的折返）。留著的話偏移出去的兩股道會在同一批格子上打架，
    鐵軌互相打斷 —— 實測那 220 公尺就吃掉 551 格。
    """
    for i in range(1, len(pts) - 1):
        a = (pts[i][0] - pts[i-1][0], pts[i][1] - pts[i-1][1])
        b = (pts[i+1][0] - pts[i][0], pts[i+1][1] - pts[i][1])
        la, lb = math.hypot(*a), math.hypot(*b)
        if la < 1e-6 or lb < 1e-6:
            continue
        c = max(-1.0, min(1.0, (a[0]*b[0] + a[1]*b[1]) / (la * lb)))
        if math.degrees(math.acos(c)) < thresh:
            continue
        head, tail = pts[:i+1], pts[i:]
        if _length(head) >= _length(tail):
            return drop_reversal(head, kinds[:i], thresh)
        return drop_reversal(tail, kinds[i:], thresh)
    return pts, kinds


def _smooth_tangents(out, step, win_m=4.0):
    """方向向量改用前後 win_m 公尺的位置差重算。

    OSM 折線的頂點常常是硬轉角，逐段取方向會讓法線在頂點瞬間翻掉，
    偏移出去的鐵軌因此橫跳一大段，兩股道甚至會打到同一格 ——
    實測安坑輕軌有 553 格被兩股道搶著佔用，等於兩邊各被打斷一次。
    """
    k = max(1, int(win_m / step))
    n = len(out)
    res = []
    for i in range(n):
        a, b = out[max(0, i - k)], out[min(n - 1, i + k)]
        dx, dz = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dz)
        if L < 1e-9:
            dx, dz, L = out[i][2], out[i][3], 1.0
        res.append((out[i][0], out[i][1], dx / L, dz / L, out[i][4]))
    return res


def vertical_profile(kinds, step=STEP, grade=MAX_GRADE):
    """把各段的目標高度用坡度上限平滑成可行的縱斷面。

    做法是取「下包絡線」：y[i] = min_j (target[j] + grade*距離)。
    兩次線性掃描即可，效果是隧道會把前後的高架往下拉出引道 —
    這正是真實路線進洞前必須降坡的行為。
    """
    tgt = [GROUND + PROFILE.get(k, 1) for k in kinds]
    y = tgt[:]
    d = grade * step
    for i in range(1, len(y)):
        y[i] = min(y[i], y[i - 1] + d)
    for i in range(len(y) - 2, -1, -1):
        y[i] = min(y[i], y[i + 1] + d)
    return [int(round(v)) for v in y]


def track_offsets(samples, ys, grounds, stn_idx):
    """每個取樣點的軌道中心離線位。

    區間是 ±3（雙線隧道），地下站要張開到 ±8 才塞得下中間的島式月台，
    中間留 FLARE_M 公尺線性過渡 —— 直接跳過去的話鐵軌會斷成兩截。
    """
    n = len(samples)
    toff = [float(TUN_TRACK_OFF)] * n
    half = int(PLATFORM_LEN / 2 / STEP)
    fl = max(1, int(FLARE_M / STEP))
    for i in stn_idx:
        g = int(grounds[i]) if grounds is not None else GROUND
        if structure_for_ground(int(ys[i]), g) != "tunnel":
            continue                                   # 高架站維持側式月台
        lo, hi = max(0, i - half), min(n - 1, i + half)
        for k in range(lo, hi + 1):
            toff[k] = max(toff[k], float(STN_TRACK_OFF))
        for j in range(1, fl + 1):
            v = STN_TRACK_OFF + (TUN_TRACK_OFF - STN_TRACK_OFF) * j / fl
            if lo - j >= 0:
                toff[lo - j] = max(toff[lo - j], v)
            if hi + j < n:
                toff[hi + j] = max(toff[hi + j], v)
    return toff


def half_width(toff):
    """走行面半寬：軌道中心外側再留 2 格才有側牆。"""
    return max(5, int(round(toff)) + 2)


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


def structure_for_ground(y, ground):
    """蓋哪種結構要看軌面與「當地地面」的高差，不是看 OSM 標籤。

    標籤決定目標高度，但坡度平滑後引道會把高架一路拉到地面以下；
    那些點若仍當高架蓋，橋面會直接埋進土裡。
    """
    if y >= ground + 6:
        return "viaduct"
    if y >= ground - 1:
        return "surface"
    return "tunnel"


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

def build_station(w, samples, ys, idx, underground, label=None, grounds=None):
    n = len(samples)
    half = int(PLATFORM_LEN / 2 / STEP)
    lo, hi = max(0, idx - half), min(n - 1, idx + half)
    if underground:
        _station_island(w, samples, ys, grounds, lo, hi, label)
    else:
        _station_side(w, samples, ys, grounds, lo, hi, label)


# ===== 地下站：島式月台 + 穿堂層 =====

def _station_island(w, samples, ys, grounds, lo, hi, label):
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
    n = g0 - ym
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

    _stair_run(w, samples, ys, sd + d * 2 * per_m, d, per_m, ym, g0, 13, 17,
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
    need = (abs(y_plat - g0) * 2 + 4) * per_m
    d = 1 if start + need < len(samples) else -1
    if not (0 <= start + d * need < len(samples)):
        return
    steps = _stair_run(w, samples, ys, start, d, per_m, g0, y_plat, 11, 13,
                       head=4, wall_offs=(10, 14), wall_ground=g0)
    if not steps:
        return
    # 樓梯腳下的地面站廳，閘門擺在裡面
    _hall(w, samples, ys, start, d, per_m, g0, label, t0=-11, t1=0,
          o0=9, o1=17, floor_t0=-11, door_t=-11, open_end=0, gate_t=-4)
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


def _length(pts):
    return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def _same_corridor(a, b, tol=600, len_ratio=0.2):
    """兩條折線是否為同一路廊的上下行。

    端點相同或互換即可，容差放到 600 m —— 上下行常在終點站前後
    幾百公尺處各自收尾（文湖線動物園端就差了 476 m）。
    但光看端點會把短支線誤判成同路廊，所以再要求長度相差 20% 以內。
    """
    pa, pb = a["points"], b["points"]
    la, lb = _length(pa), _length(pb)
    if abs(la - lb) > len_ratio * max(la, lb, 1):
        return False
    a0, a1 = tuple(pa[0]), tuple(pa[-1])
    b0, b1 = tuple(pb[0]), tuple(pb[-1])
    fwd = math.dist(a0, b0) < tol and math.dist(a1, b1) < tol
    rev = math.dist(a0, b1) < tol and math.dist(a1, b0) < tol
    return fwd or rev


def select_variants(variants, tol=60, min_new_m=400):
    """挑出幾何互不重複的一組路線。

    同一條線在 OSM 常有多個 relation：上下行各一（幾何幾乎重疊）、
    支線、以及直達車/普通車等營運模式。全部照蓋會讓上下行變成兩座
    並排的結構；只蓋最長的又會漏掉支線。

    分兩步，因為單靠覆蓋率調不出同時滿足兩者的門檻：
      1. 先用端點配對把「上下行」收斂成一條（端點相同或互換即同一路廊）。
      2. 再對倖存者算未覆蓋的絕對長度，只收下真正帶來新幾何的。
    """
    uniq = []
    for v in sorted(variants, key=lambda v: -len(v["points"])):
        if not any(_same_corridor(v, u) for u in uniq):
            uniq.append(v)

    sel, grid = [], set()

    def mark(pts):
        for x, z in pts:
            grid.add((int(x // tol), int(z // tol)))

    def uncovered_m(pts):
        total = 0.0
        for i in range(len(pts) - 1):
            x, z = pts[i]
            gx, gz = int(x // tol), int(z // tol)
            if not any((gx + dx, gz + dz) in grid
                       for dx in (-1, 0, 1) for dz in (-1, 0, 1)):
                total += math.dist(pts[i], pts[i + 1])
        return total

    for v in uniq:
        if not sel or uncovered_m(v["points"]) > min_new_m:
            sel.append(v)
            mark(v["points"])
    return sel


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lines", nargs="*", default=["BR"])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--out", default=os.path.join(ROOT, "out", "Taipei MRT"))
    a = ap.parse_args()

    lines = json.load(open(os.path.join(ROOT, "data", "mc_lines.json")))
    refs = sorted(lines) if a.all else a.lines

    stations = []
    with open(os.path.join(ROOT, "data", "mc_stations.csv")) as f:
        for r in csv.DictReader(f):
            stations.append((r["ref"].split(";"), r["name_zh"] or r["name_en"],
                             int(r["mc_x"]), int(r["mc_z"]), r["name_en"], r["ref"]))

    shutil.rmtree(a.out, ignore_errors=True)
    w = World(a.out, name="Taipei MRT", spawn=(2633, 66, 1387))

    total_km = 0.0
    for ref in refs:
        if ref not in lines:
            print(f"{ref}: 沒有幾何資料，略過"); continue
        chosen = select_variants(lines[ref])
        all_samples, all_ys, cnt = [], [], {"viaduct": 0, "surface": 0, "tunnel": 0}
        km = 0.0
        for v in chosen:
            pts = [tuple(p) for p in v["points"]]
            kinds = v.get("kinds") or ["ground"] * len(pts)
            pts, kinds = drop_reversal(pts, kinds)
            samples = resample(pts, kinds, STEP)
            if len(samples) < 10:
                continue
            ys = vertical_profile([s[4] for s in samples])
            c = build_alignment(w, samples, ys)
            for k in cnt:
                cnt[k] += c[k]
            all_samples += samples
            all_ys += ys
            km += len(samples) * STEP / 1000
        if not all_samples:
            print(f"{ref}: 取樣點太少，略過"); continue
        total_km += km
        samples, ys = all_samples, all_ys
        branch = f" (+{len(chosen)-1} 支線/分歧)" if len(chosen) > 1 else ""
        mine = [s for s in stations if any(t.startswith(ref) and
                (len(t) > len(ref) and t[len(ref)].isdigit()) for t in s[0])]
        built = 0
        for _, name, sx, sz, en, full_ref in mine:
            best, bd = None, 1e18
            for i, (x, z, _, _, _) in enumerate(samples):
                dd = (x - sx) ** 2 + (z - sz) ** 2
                if dd < bd:
                    bd, best = dd, i
            if bd ** 0.5 > 200:
                continue
            build_station(w, samples, ys, best, structure_for_ground(ys[best], GROUND) == "tunnel",
                          label=(full_ref, name, en))
            built += 1
        tot = max(1, sum(cnt.values()))
        print(f"{ref:<3} {km:>6.2f} km  y{min(ys):>3}~{max(ys):<3}  "
              f"高架{100*cnt['viaduct']//tot:>3}% 平面{100*cnt['surface']//tot:>3}% "
              f"地下{100*cnt['tunnel']//tot:>3}%  車站 {built}/{len(mine)}{branch}")

    print(f"\n合計 {total_km:.1f} km，寫入存檔…")
    w.save()


if __name__ == "__main__":
    main()
