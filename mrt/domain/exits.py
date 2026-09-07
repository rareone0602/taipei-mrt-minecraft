#!/usr/bin/env python3
"""真實出入口：把 OSM 的出入口座標接到樣板車站的穿堂層。

除了台北車站以外，每座車站原本只有一座樣板樓梯，開在站體側邊固定的位置。
但 `data/entrances.json` 早就有全網 786 個真實出入口的座標與編號 ——
中正紀念堂 6 號出口離站體 264 m、公館有 27 個出入口。這裡把它們接上。

每個出入口做三件事：
  1. 一座折返式樓梯井（build_concourse.ShaftStair）從地面下到穿堂層的高度
  2. 一段接駁通道，從井底的門沿著站體外側走到站體側牆
  3. 在側牆開一個洞通進穿堂層的非付費區（閘門前那一段）

三件事全是純幾何，這一層只算「東西該放在哪」，不放方塊；放方塊在
application/build_exits.py。

實際資料踩到的三件事，決定了下面的做法：

- **出入口不在站體旁邊。** 沿線距離的中位數是 73 m、九成在 240 m 內 ——
  一半以上的出入口落在 70 m 長的月台範圍之外。所以通道不能垂直於站體
  直直穿進去，得先沿站體外側走到開洞的位置。通道一律走在離線位 PASS_OFF
  （站體半寬 12 再往外 3）：沿著取樣點跟著線形走，站體再彎也不會切進去。
- **出入口常常就在隧道正上方。** 一成的出入口離中心線不到 10 m。井從地面
  一路挖到穿堂層，直接放的話會把區間隧道的頂板挖穿。所以井一律擺在站體
  外側，離中心線不夠遠就往外推，推到與所有路線的地下結構都不相撞為止。
- **轉乘站的出入口是共用的。** 忠孝新生的 14 個出入口同時掛在板南線與
  中和新蘆線名下。每個出入口只接離它最近的那一座站體（assign_to_boxes）。

自我測試: ./.venv/bin/python tests/test_exits.py
"""
import math

from mrt.domain.alignment import (
    BOX_HALF, MEZZ_DY, BOX_TOP_DY, PLATFORM_LEN, STEP, structure_for_ground,
)

PASS_OFF   = BOX_HALF + 3      # 接駁通道中心線的離線位（站體外側 3 m）
PASS_HALF  = 2                 # 通道半寬 -> 5 m 寬
CLEAR_OFF  = PASS_OFF + PASS_HALF + 1   # 井身（含一格邊距）離中心線至少這麼遠：
                                        # 通道帶 13~17、外牆 18，井壁落在 18 以外，
                                        # 別的出入口的通道才能從門前經過而不撞井
SAME_REF_M = 40.0              # 同一站同編號的兩個節點在這個距離內算同一個出入口
HOLE_ALONG = 7                 # 側牆開洞位置：自站體 lo 端起算幾公尺（閘門在 14）
HOLE_HALF  = 2                 # 洞的半寬（沿線方向）
MIN_DROP   = 3                 # 地面到穿堂層至少要差這麼多才值得蓋井
MAX_ALONG  = 350               # 出入口離站體中心沿線超過這個距離就不接
MAX_OFF    = 300               # 離中心線超過這個距離就不接
MERGE_M    = 12.0              # 兩個出入口靠得比這近就共用一座井
SLIDE_MAX  = 60                # 井最多往外推幾公尺

# 折返梯井的尺寸，與 build_concourse.ShaftStair 一致：
# 井內座標 a 沿 u 方向 -1..FLIGHT+2、b 沿法向 -HALF_W-1..HALF_W+1
SHAFT_FLIGHT = 14
SHAFT_HALF_W = 4
SHAFT_A = (-1, SHAFT_FLIGHT + 2)
SHAFT_B = (-SHAFT_HALF_W - 1, SHAFT_HALF_W + 1)


# ---------- 占用索引 ----------

class Occupancy:
    """所有路線的結構在平面上占了哪些格、各占哪一段高度。

    問的問題只有一個：「(x, z) 這一格在 y0..y1 之間有沒有東西」。
    井與通道靠這個避開別條線的隧道 —— 轉乘站的出入口井從地面挖到深層那條線
    的穿堂層，中途一定會經過淺層那條線的深度，不查的話會把人家的隧道挖穿。

    每個取樣點沿法向刷 2r+1 格，記下這一格被哪段高度占用、屬於哪一段路線
    （tag）。同一格可能被兩條線在不同深度占用，所以存的是區間清單。

    tag 是給通道用的：通道本來就沿著自己那條線的外側走，照取樣點的法向
    量出來的離線位一定夠遠，只有斜線光柵化的邊界會與襯砌的最外一格擦到
    同一個格子 —— 那不是真的相撞，所以通道檢查時略過自己那一段。
    井不略過：井從地面挖下來，真的可能落在自己的區間隧道正上方。
    """

    def __init__(self):
        self.cells = {}

    def add(self, x, z, y0, y1, tag=None):
        c = (int(round(x)), int(round(z)))
        self.cells.setdefault(c, []).append((int(y0), int(y1), tag))

    def add_span(self, x, z, nx, nz, r, y0, y1, tag=None):
        """以 (x, z) 為中心、沿法向 (nx, nz) 兩側各 r 格，占用 y0..y1。"""
        for o in range(-r, r + 1):
            self.add(x + nx * o, z + nz * o, y0, y1, tag)

    def blocked(self, x, z, y0, y1, skip_tag=None):
        for a, b, t in self.cells.get((int(x), int(z)), ()):
            if a <= y1 and b >= y0 and (skip_tag is None or t != skip_tag):
                return True
        return False

    def any_blocked(self, cells, y0, y1, skip_tag=None):
        for x, z in cells:
            if self.blocked(x, z, y0, y1, skip_tag):
                return True
        return False

    def who(self, cells, y0, y1, skip_tag=None):
        """擋住這批格子的是哪些 tag（給報表用）。"""
        out = set()
        for x, z in cells:
            for a, b, t in self.cells.get((int(x), int(z)), ()):
                if a <= y1 and b >= y0 and (skip_tag is None or t != skip_tag):
                    out.add(t)
        return out


def index_segments(segs, box_half=BOX_HALF):
    """把 build_world 規劃好的路段全部刷進 Occupancy，tag 是路段索引。

    segs 的每個元素要有 samples / ys / ground / stn / hw（cli 規劃完的格式）。
    地下段占 y-2..y+7（隧道斷面），車站範圍占 y-2..y+10 而且半寬放到站體；
    高架與平面段也記，因為井會一路挖到地面 —— 蓋在橋墩或路堤上就糟了。
    橋墩只到地面下 4 格（sec_bridge 的 ground-4），第 0 帶的穿堂頂板在
    地面下 5 格，剛好從橋墩底下過得去；多算一格就會把高架線底下全封死。
    """
    occ = Occupancy()
    half = int(PLATFORM_LEN / 2 / STEP)
    for li, sg in enumerate(segs):
        samples, ys, gnd = sg["samples"], sg["ys"], sg["ground"]
        hws = sg.get("hw")
        stn_rng = []
        for bi in sg.get("stn", ()):
            stn_rng.append((max(0, bi - half), min(len(samples) - 1, bi + half)))
        n = len(samples)
        for i in range(0, n, 2):                    # 每 1 m 一點就夠了
            x, z, ux, uz, _ = samples[i]
            nx, nz = -uz, ux
            y, g = int(ys[i]), int(gnd[i])
            hw = int(hws[i]) if hws is not None else 5
            st = structure_for_ground(y, g)
            in_stn = any(lo <= i <= hi for lo, hi in stn_rng)
            if st == "tunnel":
                if in_stn:
                    occ.add_span(x, z, nx, nz, box_half + 1, y - 2, y + BOX_TOP_DY, li)
                else:
                    occ.add_span(x, z, nx, nz, hw + 2, y - 2, y + 7, li)
            elif st == "viaduct":
                occ.add_span(x, z, nx, nz, hw + 1, y - 2, y + 8, li)
                occ.add_span(x, z, nx, nz, 2, g - 4, y, li)          # 橋墩
                if in_stn:                                            # 地面站廳
                    occ.add_span(x, z, nx, nz, 11, g - 3, y + 8, li)
            else:
                occ.add_span(x, z, nx, nz, hw + 2, y - 2, y + 8, li)
    return occ


# ---------- 站體座標 ----------

def station_frame(samples, ys, idx):
    """車站的取樣範圍 (lo, hi) 與開洞位置的取樣索引。"""
    n = len(samples)
    half = int(PLATFORM_LEN / 2 / STEP)
    lo, hi = max(0, idx - half), min(n - 1, idx + half)
    per_m = max(1, int(round(1.0 / STEP)))
    hole = min(hi, lo + HOLE_ALONG * per_m)
    return lo, hi, hole


def nearest_index(samples, x, z, lo=None, hi=None):
    """離 (x, z) 最近的取樣點索引（可限制在 lo..hi）。"""
    lo = 0 if lo is None else lo
    hi = len(samples) - 1 if hi is None else hi
    best, bd = lo, None
    for i in range(lo, hi + 1):
        d = (samples[i][0] - x) ** 2 + (samples[i][1] - z) ** 2
        if bd is None or d < bd:
            best, bd = i, d
    return best, math.sqrt(bd) if bd is not None else 0.0


def local_coords(samples, i, x, z):
    """(x, z) 相對於取樣點 i 的 (沿線, 離線位)。離線位正值在法向那一側。"""
    sx, sz, ux, uz, _ = samples[i]
    dx, dz = x - sx, z - sz
    return dx * ux + dz * uz, -dx * uz + dz * ux


def offset_point(samples, i, off):
    sx, sz, ux, uz, _ = samples[i]
    return sx - uz * off, sz + ux * off


def box_cells(samples, lo, hi, half):
    """站體在 lo..hi 之間、|離線位| <= half 的格子。"""
    out = set()
    for i in range(lo, hi + 1):
        sx, sz, ux, uz, _ = samples[i]
        for o in range(-half, half + 1):
            out.add((int(round(sx - uz * o)), int(round(sz + ux * o))))
    return out


def box_distance(samples, ys, idx, x, z):
    """出入口到站體矩形的距離（在矩形內為 0），轉乘站分派用。"""
    lo, hi, _ = station_frame(samples, ys, idx)
    i, _ = nearest_index(samples, x, z, lo, hi)
    along, off = local_coords(samples, i, x, z)
    da = max(0.0, abs(along) - 1.0) if i not in (lo, hi) else abs(along)
    do = max(0.0, abs(off) - BOX_HALF)
    return math.hypot(da, do)


def assign_to_boxes(entrances, boxes):
    """轉乘站：每個出入口只接最近的那座站體。

    entrances [(ref, x, z)]；boxes {key: (samples, ys, idx)}。
    回傳 {key: [(ref, x, z)]}。
    """
    out = {k: [] for k in boxes}
    for ref, x, z in entrances:
        best = min(boxes, key=lambda k: box_distance(boxes[k][0], boxes[k][1],
                                                     boxes[k][2], x, z))
        out[best].append((ref, x, z))
    return out


# ---------- 光柵化（與 build_concourse.stroke 同一套，這裡不能引用 application）----------

def stroke(p0, p1, half_w):
    (x0, z0), (x1, z1) = p0, p1
    n = int(max(abs(x1 - x0), abs(z1 - z0)))
    out = set()
    if n == 0:
        cx, cz = int(round(x0)), int(round(z0))
        for dx in range(-half_w, half_w + 1):
            for dz in range(-half_w, half_w + 1):
                out.add((cx + dx, cz + dz))
        return out
    ux, uz = (x1 - x0) / n, (z1 - z0) / n
    for t in range(n + 1):
        cx, cz = x0 + ux * t, z0 + uz * t
        for dx in range(-half_w, half_w + 1):
            for dz in range(-half_w, half_w + 1):
                if dx * dx + dz * dz <= half_w * half_w + half_w:
                    out.add((int(round(cx)) + dx, int(round(cz)) + dz))
    return out


def polyline_cells(pts, half_w):
    out = set()
    for a, b in zip(pts, pts[1:]):
        out |= stroke(a, b, half_w)
    return out


# ---------- 井的擺放 ----------

def shaft_cells(x0, z0, ux, uz, margin=0):
    """折返梯井的平面占用格（含井壁），可再往外加 margin。"""
    vx, vz = -uz, ux
    out = set()
    for a in range(SHAFT_A[0] - margin, SHAFT_A[1] + margin + 1):
        for b in range(SHAFT_B[0] - margin, SHAFT_B[1] + margin + 1):
            out.add((x0 + ux * a + vx * b, z0 + uz * a + vz * b))
    return out


def _quantize(vx, vz):
    if abs(vx) >= abs(vz):
        return (1 if vx >= 0 else -1), 0
    return 0, (1 if vz >= 0 else -1)


def place_shaft(samples, ys, lo, hi, ex, ez, ym, g_top, occ, used, ground_at,
                extra=frozenset()):
    """替一個出入口找井的位置與方向。

    回傳 (x0, z0, ux, uz, g0, 推了幾公尺, 方向種類) 或 None；
    方向種類 "normal" 是背對站體、"tangent" 是順著線形。

    方向優先「背對站體」：井口的門（a=-1）朝向路線，接駁通道從門直接往
    站體走。其次是順著線形的兩個方向。井身朝向站體那個方向不考慮 ——
    井會擋在門與站體之間，通道得繞過自己的井。

    位置從出入口本身開始，沿法向往外推，直到：
      · 井身每一格（含一格邊距）離中心線至少 CLEAR_OFF —— 通道走在離線位
        PASS_OFF 的那條帶上，別的出入口的通道會從這扇門前經過。要逐格量，
        不能只量門：井只能擺成正交的四個方向，線形斜 45 度時井的角會比
        門近 4 m（府中站就是這樣把 1 號出口的通道擋掉的）
      · 井身與所有地下結構（occ）、已經蓋好的井與通道（used）都不相撞；
        extra 是這一站自己已經鋪好的通道格，井不准壓上去
    推的距離越短越好。
    """
    i, _ = nearest_index(samples, ex, ez, lo, hi)
    along, off = local_coords(samples, i, ex, ez)
    side = 1 if off >= 0 else -1
    sx, sz, ux, uz, _ = samples[i]
    nx, nz = -uz * side, ux * side              # 指向出入口那一側的法向

    dirs = [(_quantize(nx, nz), "normal")]
    for t in ((ux, uz), (-ux, -uz)):
        q = _quantize(*t)
        if q != dirs[0][0] and q != (-dirs[0][0][0], -dirs[0][0][1]):
            dirs.append((q, "tangent"))
    y_lo = ym - 1                                # 井底樓板
    for slide in range(0, SLIDE_MAX + 1):
        px, pz = ex + nx * slide, ez + nz * slide
        for (dx, dz), kind in dirs:
            x0, z0 = int(round(px)), int(round(pz))
            door = (x0 - dx, z0 - dz)
            di, _ = nearest_index(samples, door[0], door[1])
            near = min(abs(local_coords(samples, di, cx, cz)[1])
                       for cx, cz in shaft_cells(x0, z0, dx, dz, margin=1))
            if near < CLEAR_OFF:
                continue
            cells = shaft_cells(x0, z0, dx, dz)
            if any(c in extra for c in cells):
                continue
            g0 = int(ground_at(*door))
            if g0 - ym < MIN_DROP:
                return None                      # 這裡的地面太低，井沒有意義
            if occ.any_blocked(cells, y_lo, g0 + 5) or used.any_blocked(cells, y_lo, g0 + 5):
                continue
            return x0, z0, dx, dz, g0, slide, kind
    return None


# ---------- 整座車站的計畫 ----------

def merge_entrances(entrances, merge_m=MERGE_M, same_ref_m=SAME_REF_M):
    """把其實是同一個出入口的節點併起來。回傳 [dict(refs, x, z)]。

    兩種情形：靠得很近的兩個門（兩個名字、一個出入口），以及同一站同編號
    卻畫了兩個節點（OSM 常常每條線各標一次，或門與樓梯口各標一次，
    府中站的 1 號出口兩個節點差 26 m）。後者不併的話，兩座井會一前一後
    疊在同一條法線上，後面那座的通道被前面那座擋死。
    """
    groups = []
    for ref, x, z in sorted(entrances, key=lambda e: str(e[0])):
        ref = str(ref)
        for g in groups:
            d = math.hypot(g["x"] - x, g["z"] - z)
            if d <= merge_m or (ref and ref in g["refs"] and d <= same_ref_m):
                n = len(g["refs"])
                g["x"] = (g["x"] * n + x) / (n + 1)
                g["z"] = (g["z"] * n + z) / (n + 1)
                g["refs"].append(ref)
                break
        else:
            groups.append(dict(refs=[ref], x=float(x), z=float(z)))
    for g in groups:                       # 同名只留一個，牌子上才不會印兩次
        seen, refs = set(), []
        for r in g["refs"]:
            if r not in seen:
                seen.add(r); refs.append(r)
        g["refs"] = refs
    return groups


def plan_station(samples, ys, grounds, idx, entrances, ground_at, occ, used,
                 own_tag=None):
    """把一座地下站的出入口全部接上。

    samples/ys/grounds  cli 規劃好的路段陣列
    idx                 車站的取樣索引
    entrances           [(ref, x, z)]，ref 是出入口編號（可能重複或空白）
    ground_at           f(x, z) -> 地面 y
    occ                 Occupancy（所有路線）
    used                Occupancy：已經蓋好的井與通道（會被這裡更新：這一站的
                        井與通道規劃完會全部加進去）。跟 occ 分開，因為它是
                        一邊規劃一邊長出來的。有高度：轉乘站兩座站體的穿堂層
                        差了 15 m，兩邊的通道在平面上交叉但根本碰不到
    own_tag             這條路段在 occ 裡的 tag，通道檢查時略過（見 Occupancy）

    回傳 dict：
      ym       穿堂層站立面 y
      shafts   [dict(refs, x0, z0, ux, uz, g0, y_to, slide)]
      cells    接駁通道的地板格（含側牆開洞）
      no_wall  不准砌牆的格子（站體內部）
      skipped  [(refs, x, z, 原因, 擋住的是誰)]
    """
    lo, hi, hole = station_frame(samples, ys, idx)
    ym = int(ys[hole]) + MEZZ_DY + 1
    interior = box_cells(samples, lo, hi, BOX_HALF - 2)
    own_box = box_cells(samples, lo, hi, BOX_HALF + 2)   # 通道本來就要穿進自己的站體
    cells, shafts, skipped = set(), [], []
    sides_used = set()

    groups = merge_entrances(entrances)

    for g in groups:
        ex, ez = g["x"], g["z"]
        i, _ = nearest_index(samples, ex, ez)
        along_c, off_c = local_coords(samples, idx, ex, ez)
        if abs(along_c) > MAX_ALONG or abs(off_c) > MAX_OFF:
            skipped.append((g["refs"], ex, ez, "離站體太遠", set()))
            continue
        g_here = int(ground_at(ex, ez))
        if g_here - ym < MIN_DROP:
            skipped.append((g["refs"], ex, ez, "地面太低，沒有落差", set()))
            continue
        # 井不准壓到這一站已經鋪好的通道；通道之間則可以重疊（同一層、同高）
        placed = place_shaft(samples, ys, lo, hi, ex, ez, ym, g_here, occ,
                             used, ground_at, extra=cells)
        if placed is None:
            skipped.append((g["refs"], ex, ez, "井擺不下（撞到別線或別的井）", set()))
            continue
        x0, z0, dx, dz, g0, slide, kind = placed

        # 接駁通道：門 -> 站體外側 PASS_OFF 處 -> 沿線走到開洞位置 -> 洞。
        # 順著線形擺的井，門朝著線形方向，出門先直走三格再轉向站體 ——
        # 直接斜著轉的話通道的刷寬會切到井口那一排井壁。
        door = (x0 - dx, z0 - dz)
        pts = [door]
        if kind == "tangent":
            door = (x0 - 4 * dx, z0 - 4 * dz)
            pts.append(door)
        di, _ = nearest_index(samples, door[0], door[1])
        _, doff = local_coords(samples, di, door[0], door[1])
        side = 1 if doff >= 0 else -1
        pts.append(offset_point(samples, di, side * PASS_OFF))
        step = max(1, int(4 / STEP))
        rng = range(di, hole, step if hole > di else -step)
        for k in rng:
            pts.append(offset_point(samples, k, side * PASS_OFF))
        pts.append(offset_point(samples, hole, side * PASS_OFF))
        pts.append(offset_point(samples, hole, side * (BOX_HALF - 1)))
        pcells = polyline_cells(pts, PASS_HALF)
        pcells -= interior                                   # 站體裡面不必再鋪
        # 通道是平的，地形不是：板橋站往環狀線那頭地面低了 6 m，通道走過去
        # 頂板會冒出街面。頂板上面至少要留一格土。
        if any(int(ground_at(x, z)) < ym + 4 for x, z in pcells):
            skipped.append((g["refs"], ex, ez, "通道會露出地面", set()))
            continue
        # 通道不准穿過別線的結構，也不准穿過別的井
        shaft_own = shaft_cells(x0, z0, dx, dz)
        chk = pcells - shaft_own - own_box
        if occ.any_blocked(chk, ym - 1, ym + 3, skip_tag=own_tag):
            skipped.append((g["refs"], ex, ez, "通道撞到別線的結構",
                            occ.who(chk, ym - 1, ym + 3, skip_tag=own_tag)))
            continue
        if used.any_blocked(chk, ym - 1, ym + 3):
            skipped.append((g["refs"], ex, ez, "通道撞到別的井或通道",
                            used.who(chk, ym - 1, ym + 3)))
            continue

        for c in shaft_cells(x0, z0, dx, dz, margin=1):
            used.add(c[0], c[1], ym - 1, g0 + 5, ("井", tuple(g["refs"])))
        cells |= pcells
        sides_used.add(side)
        shafts.append(dict(refs=g["refs"], x0=x0, z0=z0, ux=dx, uz=dz,
                           g0=g0, y_to=ym, slide=slide, ex=ex, ez=ez))

    # 開洞：側牆 |off| 11..12 加上外側一格，沿線 ±HOLE_HALF。
    # 不往裡多挖：穿堂層 |off| <= 10 本來就是空的，多鋪只是把樓板換色。
    holes = set()
    for side in sides_used:
        for k in range(hole - HOLE_HALF * 2, hole + HOLE_HALF * 2 + 1):
            if not (lo <= k <= hi):
                continue
            for o in range(BOX_HALF - 1, BOX_HALF + 2):
                x, z = offset_point(samples, k, side * o)
                holes.add((int(round(x)), int(round(z))))
    cells |= holes
    for c in cells:
        used.add(c[0], c[1], ym - 1, ym + 3, ("通道", ym))

    return dict(ym=ym, lo=lo, hi=hi, hole=hole, shafts=shafts, cells=cells,
                no_wall=interior, skipped=skipped)
