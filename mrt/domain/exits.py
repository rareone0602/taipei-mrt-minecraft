#!/usr/bin/env python3
"""真實出入口與轉乘通道：把 OSM 的出入口座標接到車站的穿堂層，再把轉乘站的
兩座站體接起來。

除了台北車站以外，每座車站原本只有一座樣板樓梯，開在站體側邊固定的位置。
但 `data/entrances.json` 早就有全網 786 個真實出入口的座標與編號 ——
中正紀念堂 6 號出口離站體 264 m、公館有 27 個出入口。這裡把它們接上。

每個出入口做三件事：
  1. 一座折返式樓梯井（build_concourse.ShaftStair）從街上到穿堂層的高度 ——
     地下站往下挖，高架站往上爬到橋下的穿堂（alignment.station_kind 決定型態，
     LEVEL_DY 決定高度；全專案只有這一個定義）
  2. 一段接駁通道，從井的門沿著站體外側走到站體側牆（高架站是空橋）
  3. 在側牆開一個洞通進穿堂層的非付費區（閘門前那一段）

轉乘站另外規劃一條付費區對付費區的轉乘通道（plan_transfer）：兩層一樣高就
一條通道，不一樣高就在兩座站體之間立一座井，兩層各接一段通道到井的門。

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
    BOX_HALF, MEZZ_DY, BOX_TOP_DY, PLATFORM_LEN, STEP, LEVEL_DY,
    structure_for_ground, station_kind,
)

PASS_OFF   = BOX_HALF + 3      # 接駁通道中心線的離線位（站體外側 3 m）
PASS_HALF  = 2                 # 通道半寬 -> 5 m 寬
CLEAR_OFF  = PASS_OFF + PASS_HALF + 1   # 井身（含一格邊距）離中心線至少這麼遠：
                                        # 通道帶 13~17、外牆 18，井壁落在 18 以外，
                                        # 別的出入口的通道才能從門前經過而不撞井
SAME_REF_M = 40.0              # 同一站同編號的兩個節點在這個距離內算同一個出入口
HOLE_ALONG = 7                 # 側牆開洞位置：自站體 lo 端起算幾公尺（閘門在 14）
HOLE_HALF  = 2                 # 洞的半寬（沿線方向）
MIN_DROP   = 3                 # 地面到穿堂層至少要差這麼多才值得蓋井（地下站）
MIN_RISE   = 3                 # 高架站：街面到穿堂層至少差這麼多才蓋井往上爬。井的兩扇門開在
                               # 同一面牆上，差 2 的話井底的門洞只剩一格、門前的前庭又剛好
                               # 清掉空橋的樓板；差 0～2 的改用平面出入口（見 GATE_RUN）
GATE_RUN   = 3                 # 平面出入口：門外的坡道加前庭有幾格長
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

    def copy(self):
        """複本，拿來試規劃：不成就丟掉，成了再把 cells 換回來。"""
        o = Occupancy()
        o.cells = {c: list(v) for c, v in self.cells.items()}
        return o

    def add(self, x, z, y0, y1, tag=None):
        c = (int(round(x)), int(round(z)))
        self.cells.setdefault(c, []).append((int(y0), int(y1), tag))

    def add_span(self, x, z, nx, nz, r, y0, y1, tag=None):
        """以 (x, z) 為中心、沿法向 (nx, nz) 兩側各 r 格，占用 y0..y1。"""
        for o in range(-r, r + 1):
            self.add(x + nx * o, z + nz * o, y0, y1, tag)

    def blocked(self, x, z, y0, y1, skip_tag=None, ignore=None):
        """ignore(tag) 回 True 的占用不算數 —— 轉乘通道跟同一座站體、同一層的
        出入口通道重疊是正常的（兩條通道併成一片地板），跟別的東西重疊才是撞。"""
        for a, b, t in self.cells.get((int(x), int(z)), ()):
            if a <= y1 and b >= y0 and (skip_tag is None or t != skip_tag) \
                    and not (ignore is not None and ignore(t)):
                return True
        return False

    def any_blocked(self, cells, y0, y1, skip_tag=None, ignore=None):
        for x, z in cells:
            if self.blocked(x, z, y0, y1, skip_tag, ignore):
                return True
        return False

    def who(self, cells, y0, y1, skip_tag=None, ignore=None):
        """擋住這批格子的是哪些 tag（給報表用）。"""
        out = set()
        for x, z in cells:
            for a, b, t in self.cells.get((int(x), int(z)), ()):
                if a <= y1 and b >= y0 and (skip_tag is None or t != skip_tag) \
                        and not (ignore is not None and ignore(t)):
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
                if in_stn:                        # 站體連同橋下／月台上方的穿堂
                    occ.add_span(x, z, nx, nz, 11, g - 3, y + 12, li)
            else:
                occ.add_span(x, z, nx, nz, hw + 2, y - 2, y + 8, li)
                if in_stn:                        # 平面站的穿堂跨在月台上方
                    occ.add_span(x, z, nx, nz, 11, g - 3, y + 12, li)
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


def gate_cells(x0, z0, ux, uz, margin=0):
    """平面出入口門外的坡道與前庭：門格 (x0, z0) 往街上 1..GATE_RUN 格、兩側各
    PASS_HALF 格（與通道同寬），margin 再往外擴一圈。"""
    vx, vz = -uz, ux
    out = set()
    for a in range(1, GATE_RUN + margin + 1):
        for b in range(-PASS_HALF - margin, PASS_HALF + margin + 1):
            out.add((x0 + ux * a + vx * b, z0 + uz * a + vz * b))
    return out


def _quantize(vx, vz):
    if abs(vx) >= abs(vz):
        return (1 if vx >= 0 else -1), 0
    return 0, (1 if vz >= 0 else -1)


def well_span(level, street):
    """井占用的高度區間 (y_lo, y_hi)：兩端的站立面各往外留樓板與頂蓋。

    地下站的井從街上往下挖到穿堂，高架站的井從街上往上爬到橋下的穿堂 ——
    同一座井、同一套幾何，只是哪一端在上面不一樣。
    """
    top, bot = max(level, street), min(level, street)
    return bot - 1, top + 5


def place_shaft(samples, ys, lo, hi, ex, ez, ym, g_top, occ, used, ground_at,
                extra=frozenset(), kind="tunnel"):
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

    kind 是車站型態（alignment.station_kind）：地下站的井往下挖，街面要比
    穿堂高 MIN_DROP 才有意義；高架站的井往上爬，街面與穿堂差不到 MIN_RISE
    的話門洞會矮到鑽不過去。
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
    for slide in range(0, SLIDE_MAX + 1):
        px, pz = ex + nx * slide, ez + nz * slide
        for (dx, dz), kind_ in dirs:
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
            if not drop_ok(kind, g0, ym):
                return None                      # 這裡的地面高度不對，井沒有意義
            y_lo, y_hi = well_span(ym, g0 + 1)
            if occ.any_blocked(cells, y_lo, y_hi) or used.any_blocked(cells, y_lo, y_hi):
                continue
            return x0, z0, dx, dz, g0, slide, kind_
    return None


def drop_ok(kind, g0, level):
    """街面（地表方塊 g0）與穿堂站立面 level 的高差夠不夠蓋井。"""
    if kind == "tunnel":
        return g0 - level >= MIN_DROP
    return abs(g0 + 1 - level) >= MIN_RISE


def place_gate(samples, ys, lo, hi, ex, ez, ym, occ, used, ground_at,
               extra=frozenset()):
    """替街面與穿堂差不到 MIN_RISE 的出入口找平面出入口的位置。

    高架站的橋下穿堂只比地面高 3～7 m，山坡上的出入口街面可能就在穿堂那個
    高度前後兩公尺內。這時井蓋不出來 —— 井的兩扇門開在同一面牆上，落差
    不到三格井底的門洞只剩一格 —— 也根本不需要井：通道的盡頭就是門，門外
    每格升降一格接到街面，再鋪一小塊前庭。

    回傳 (x0, z0, ux, uz, g0, 推了幾公尺) 或 None：(x0, z0) 是門那一格
    （通道的盡頭），u 是背對站體、量化成正交的方向，坡道與前庭在門外 u 方向
    1..GATE_RUN 格。g0 是前庭盡頭的地面：人是從那裡走上坡道的，所以那裡的
    街面得在穿堂前後 MIN_RISE-1 格內，不然再往外推。

    跟 place_shaft 一樣沿法向往外推：坡道（含一格邊距）離中心線至少
    CLEAR_OFF，別的出入口的通道才能從門前經過；不撞別線的結構、別的井與
    通道，也不壓到這一站自己已經鋪好的通道（extra）。
    """
    i, _ = nearest_index(samples, ex, ez, lo, hi)
    along, off = local_coords(samples, i, ex, ez)
    side = 1 if off >= 0 else -1
    sx, sz, ux, uz, _ = samples[i]
    nx, nz = -uz * side, ux * side              # 指向出入口那一側的法向
    dx, dz = _quantize(nx, nz)
    for slide in range(0, SLIDE_MAX + 1):
        x0 = int(round(ex + nx * slide))
        z0 = int(round(ez + nz * slide))
        wide = gate_cells(x0, z0, dx, dz, margin=1) | {(x0, z0)}
        di, _ = nearest_index(samples, x0, z0)
        near = min(abs(local_coords(samples, di, cx, cz)[1]) for cx, cz in wide)
        if near < CLEAR_OFF:
            continue
        if any(c in extra for c in wide):
            continue
        g0 = int(ground_at(x0 + dx * GATE_RUN, z0 + dz * GATE_RUN))
        if abs(g0 + 1 - ym) >= MIN_RISE:
            continue                             # 前庭那裡的地面離穿堂太遠，再推
        if occ.any_blocked(wide, ym - 3, ym + 4) or used.any_blocked(wide, ym - 3, ym + 4):
            continue
        return x0, z0, dx, dz, g0, slide
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


def hole_cells(samples, lo, hi, k, side):
    """側牆開洞：|off| 11..13（襯砌兩格加外側一格），沿線 k ± HOLE_HALF。

    不往裡多挖：穿堂層 |off| <= 10 本來就是空的，多鋪只是把樓板換色。
    地下站的側牆在 11..12、高架穿堂的玻璃牆在 11，同一組格子兩種都打得穿。
    """
    out = set()
    for kk in range(k - HOLE_HALF * 2, k + HOLE_HALF * 2 + 1):
        if not (lo <= kk <= hi):
            continue
        for o in range(BOX_HALF - 1, BOX_HALF + 2):
            x, z = offset_point(samples, kk, side * o)
            out.add((int(round(x)), int(round(z))))
    return out


def passage_tag(own_tag, level):
    """通道在 used 裡的 tag：同一段路線、同一層的通道可以互相重疊（併成一片地板）。"""
    return ("通道", own_tag, int(level))


def plan_station(samples, ys, grounds, idx, entrances, ground_at, occ, used,
                 own_tag=None):
    """把一座車站的出入口全部接上（地下站接穿堂層，高架與平面站接橋下或
    月台上方的穿堂 —— 型態與高度由 alignment.station_kind / LEVEL_DY 決定）。

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
      kind     車站型態
      ym       穿堂層站立面 y
      shafts   [dict(refs, x0, z0, ux, uz, g0, y_to, slide)]  折返梯井
      gates    [dict(refs, x0, z0, ux, uz, g0, y_to, slide)]  平面出入口：
               (x0, z0) 是門格（通道盡頭），u 指向街上，g0 是前庭的地面
      cells    接駁通道的地板格（含側牆開洞）
      open     平面出入口門外不准砌牆的格子（坡道與前庭，通道的外牆不能封住它）
      no_wall  不准砌牆的格子（站體內部加 open）
      skipped  [(refs, x, z, 原因, 擋住的是誰)]
    """
    lo, hi, hole = station_frame(samples, ys, idx)
    kind = station_kind(int(ys[idx]), int(grounds[idx]))
    ym = int(ys[hole]) + LEVEL_DY[kind]
    interior = box_cells(samples, lo, hi, BOX_HALF - 2)
    own_box = box_cells(samples, lo, hi, BOX_HALF + 2)   # 通道本來就要穿進自己的站體
    cells, shafts, gates, skipped = set(), [], [], []
    open_cells, sides_used = set(), set()

    groups = merge_entrances(entrances)

    for g in groups:
        ex, ez = g["x"], g["z"]
        i, _ = nearest_index(samples, ex, ez)
        along_c, off_c = local_coords(samples, idx, ex, ez)
        if abs(along_c) > MAX_ALONG or abs(off_c) > MAX_OFF:
            skipped.append((g["refs"], ex, ez, "離站體太遠", set()))
            continue
        g_here = int(ground_at(ex, ez))
        if kind == "tunnel" and not drop_ok(kind, g_here, ym):
            skipped.append((g["refs"], ex, ez, "地面太低，沒有落差", set()))
            continue
        placed = gate = None
        if drop_ok(kind, g_here, ym):
            # 井不准壓到這一站已經鋪好的通道；通道之間則可以重疊（同一層、同高）
            placed = place_shaft(samples, ys, lo, hi, ex, ez, ym, g_here, occ,
                                 used, ground_at, extra=cells, kind=kind)
        if placed is None and kind != "tunnel":
            # 高架站的街面就在穿堂那個高度前後兩公尺內（或者井往外推以後變成
            # 這樣）：不蓋井，通道直接開到街上，門外接一段坡道
            gate = place_gate(samples, ys, lo, hi, ex, ez, ym, occ, used,
                              ground_at, extra=cells)
        if placed is None and gate is None:
            skipped.append((g["refs"], ex, ez, "井擺不下（撞到別線或別的井）", set()))
            continue

        if gate is not None:
            x0, z0, dx, dz, g0, slide = gate
            door = (x0, z0)
            pts = [door]
            own = gate_cells(x0, z0, dx, dz, margin=1)
        else:
            x0, z0, dx, dz, g0, slide, kind_ = placed
            # 接駁通道：門 -> 站體外側 PASS_OFF 處 -> 沿線走到開洞位置 -> 洞。
            # 順著線形擺的井，門朝著線形方向，出門先直走三格再轉向站體 ——
            # 直接斜著轉的話通道的刷寬會切到井口那一排井壁。
            door = (x0 - dx, z0 - dz)
            pts = [door]
            if kind_ == "tangent":
                door = (x0 - 4 * dx, z0 - 4 * dz)
                pts.append(door)
            own = shaft_cells(x0, z0, dx, dz)
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
        # 地下的通道是平的，地形不是：板橋站往環狀線那頭地面低了 6 m，通道走
        # 過去頂板會冒出街面。頂板上面至少要留一格土。高架站的通道是空橋，
        # 地形高過它就切進坡裡，低了就架橋墩，怎樣都蓋得成。
        if kind == "tunnel" and any(int(ground_at(x, z)) < ym + 4 for x, z in pcells):
            skipped.append((g["refs"], ex, ez, "通道會露出地面", set()))
            continue
        # 通道不准穿過別線的結構，也不准穿過別的井（自己的井身與坡道除外）
        chk = pcells - own - own_box
        if occ.any_blocked(chk, ym - 1, ym + 3, skip_tag=own_tag):
            skipped.append((g["refs"], ex, ez, "通道撞到別線的結構",
                            occ.who(chk, ym - 1, ym + 3, skip_tag=own_tag)))
            continue
        # 同一段路線、同一層的通道（這一站先接好的轉乘通道）可以重疊：併成一片地板
        same = passage_tag(own_tag, ym)
        if used.any_blocked(chk, ym - 1, ym + 3, ignore=lambda t: t == same):
            skipped.append((g["refs"], ex, ez, "通道撞到別的井或通道",
                            used.who(chk, ym - 1, ym + 3, ignore=lambda t: t == same)))
            continue

        cells |= pcells
        sides_used.add(side)
        if gate is not None:
            for c in own:
                used.add(c[0], c[1], ym - 3, ym + 4, ("井", tuple(g["refs"])))
            open_cells |= own
            gates.append(dict(refs=g["refs"], x0=x0, z0=z0, ux=dx, uz=dz,
                              g0=g0, y_to=ym, slide=slide, ex=ex, ez=ez, kind=kind))
            continue
        y_lo, y_hi = well_span(ym, g0 + 1)
        for c in shaft_cells(x0, z0, dx, dz, margin=1):
            used.add(c[0], c[1], y_lo, y_hi, ("井", tuple(g["refs"])))
        shafts.append(dict(refs=g["refs"], x0=x0, z0=z0, ux=dx, uz=dz,
                           g0=g0, y_to=ym, slide=slide, ex=ex, ez=ez, kind=kind))

    for side in sides_used:
        cells |= hole_cells(samples, lo, hi, hole, side)
    for c in cells:
        used.add(c[0], c[1], ym - 1, ym + 3, passage_tag(own_tag, ym))

    return dict(kind=kind, ym=ym, lo=lo, hi=hi, hole=hole, shafts=shafts,
                gates=gates, cells=cells, open=open_cells,
                no_wall=interior | open_cells, skipped=skipped)


def default_entrances(samples, ys, idx, offs=(24, -24), along_m=HOLE_ALONG):
    """沒有真實出入口資料的車站（機場線桃園段、安坑輕軌…）用的預設出入口：
    開洞位置正對面、離中心線 offs 公尺的一點，兩側各一個候選，先成功的算數。
    """
    lo, hi, hole = station_frame(samples, ys, idx)
    out = []
    for o in offs:
        x, z = offset_point(samples, hole, o)
        out.append(("", int(round(x)), int(round(z))))
    return out


# ---------- 轉乘通道 ----------

TRANSFER_MAX_M = 400     # 兩座站體最近的接點相距超過這個距離就不接（三重 A/O 302 m）
PAID_FROM_M    = 20      # 轉乘通道的洞開在付費區：閘門在 lo+14..16，洞本身寬 ±2 m，再留 2 m
PAID_END_M     = 4       # 離站體端牆至少留幾公尺
STAIR_END_M    = 18      # 高架穿堂的兩座月台樓梯都在 hi 端（build_line._side_concourse）
LEVEL_DIRECT   = 1       # 兩層差不到這個數就直接一條通道接過去（差一格用走的就上得去）
LEVEL_WELL     = 5       # 差這麼多以上才蓋井；2~4 m 兩端的通道會在門口互相切到，不接
GRID_M         = 4       # 井的候選位置網格
MAX_TRIES      = 1500    # 最多完整評估幾個候選位置（粗篩掉的不算）
MAX_PAIRS      = 40      # 同一層直接接時，最多試幾對接點


def paid_range(samples, ys, idx, kind, side):
    """轉乘通道可以在哪一段側牆開洞：回傳取樣索引清單（每 3 m 一個）。

    只挑軌面高度跟出入口開洞處（lo + HOLE_ALONG）一樣的位置：站內軌面有坡的話
    穿堂樓板跟著階梯狀往上，轉乘通道的高度得跟這一站出入口通道同一層，
    兩者才併得成一片地板；差一格的話就是兩片地板互相切。整段都不一樣高才退而
    求其次全部都收。
    """
    lo, hi, hole = station_frame(samples, ys, idx)
    per_m = max(1, int(round(1.0 / STEP)))
    a, b = lo + PAID_FROM_M * per_m, hi - PAID_END_M * per_m
    if kind != "tunnel":                         # 兩座月台樓梯都在 hi 端
        b = hi - STAIR_END_M * per_m
    ks = list(range(a, b + 1, 3 * per_m))
    same = [k for k in ks if int(ys[k]) == int(ys[hole])]
    return same or ks


def _box(box):
    """把 plan_transfer 需要的東西從站體 dict 算出來。"""
    samples, ys, grounds, idx = box["samples"], box["ys"], box["grounds"], box["idx"]
    lo, hi, hole = station_frame(samples, ys, idx)
    kind = station_kind(int(ys[idx]), int(grounds[idx]))
    return dict(box, lo=lo, hi=hi, hole=hole, kind=kind,
                interior=box_cells(samples, lo, hi, BOX_HALF - 2),
                own=box_cells(samples, lo, hi, BOX_HALF + 2))


def _leg(bx, px, pz):
    """從 (px, pz) 接進站體 bx：挑付費區內離它最近的開洞位置。

    回傳 (k, side, level, 通道折點 [...], 洞的格子)。
    """
    samples, ys = bx["samples"], bx["ys"]
    best = None
    for side in (1, -1):
        ks = paid_range(samples, ys, bx["idx"], bx["kind"], side)
        if not ks:
            continue
        k = min(ks, key=lambda k: (samples[k][0] - px) ** 2 + (samples[k][1] - pz) ** 2)
        _, off = local_coords(samples, k, px, pz)
        if (off >= 0) != (side > 0):
            continue
        band = offset_point(samples, k, side * PASS_OFF)
        d = math.hypot(band[0] - px, band[1] - pz)
        if best is None or d < best[0]:
            best = (d, k, side, band)
    if best is None:
        return None
    d, k, side, band = best
    level = int(ys[k]) + LEVEL_DY[bx["kind"]]
    pts = [(px, pz), band, offset_point(samples, k, side * (BOX_HALF - 1))]
    holes = hole_cells(samples, bx["lo"], bx["hi"], k, side)
    return k, side, level, pts, holes


def _leg_blocked(bx, cells, level, occ, used, exempt):
    """通道 cells 在 level 這一層能不能鋪：不撞別線、不撞別的井、
    不撞不同層的通道（同一段路線同一層的通道可以併）。"""
    chk = (cells | outer_ring(cells)) - exempt - bx["own"]
    if occ.any_blocked(chk, level - 1, level + 3, skip_tag=bx["tag"]):
        return "撞到別線的結構", occ.who(chk, level - 1, level + 3, skip_tag=bx["tag"])
    same = passage_tag(bx["tag"], level)
    if used.any_blocked(chk, level - 1, level + 3, ignore=lambda t: t == same):
        return "撞到別的井或通道", used.who(chk, level - 1, level + 3,
                                        ignore=lambda t: t == same)
    return None


def outer_ring(cells):
    ring = set()
    for x, z in cells:
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                c = (x + dx, z + dz)
                if c not in cells:
                    ring.add(c)
    return ring


def _near_off(bx, x0, z0, dx=None, dz=None):
    """井身每一格（含邊距）離這條線的中心線最近多少。只掃站體前後 200 m。
    不給方向就只量井心那一格（粗篩用）。"""
    samples = bx["samples"]
    a, b = max(0, bx["lo"] - 400), min(len(samples) - 1, bx["hi"] + 400)
    di, _ = nearest_index(samples, x0, z0, a, b)
    if dx is None:
        return abs(local_coords(samples, di, x0, z0)[1])
    return min(abs(local_coords(samples, di, cx, cz)[1])
               for cx, cz in shaft_cells(x0, z0, dx, dz, margin=1))


def _pairs(A, B):
    """兩座站體付費區側牆帶上的接點對，近的在前：[(d, ka, sa, pa, kb, sb, pb)]。"""
    out = []
    for sa in (1, -1):
        for ka in paid_range(A["samples"], A["ys"], A["idx"], A["kind"], sa):
            pa = offset_point(A["samples"], ka, sa * PASS_OFF)
            for sb in (1, -1):
                for kb in paid_range(B["samples"], B["ys"], B["idx"], B["kind"], sb):
                    pb = offset_point(B["samples"], kb, sb * PASS_OFF)
                    d = math.hypot(pa[0] - pb[0], pa[1] - pb[1])
                    out.append((d, ka, sa, pa, kb, sb, pb))
    out.sort(key=lambda t: t[0])
    return out


def plan_transfer(box_a, box_b, occ, used):
    """替轉乘站的兩座站體規劃一條轉乘通道（付費區對付費區）。

    box_* 是 dict(samples, ys, grounds, idx, tag)，tag 是該路段在 occ 裡的 tag。

    兩層一樣高（差 <= LEVEL_DIRECT）就一條通道直接接；否則在兩座站體之間
    找一個位置蓋折返梯井，兩層各一段通道接到井的門。井的門在同一面
    （ShaftStair 的頂門與底門都開在 a=-1），兩段通道都從那扇門出來、
    先直走四格（門廊）再各自轉向自己的站體。

    井的位置：以兩座站體最近的接點對為中心撒一張網格，離兩邊接點都近的先試。
    十字交叉的轉乘站（古亭、東門、西門……）兩座站體的接點就在交叉點旁邊，
    網格中心附近的位置全都離兩條線太近 —— 井得退到交叉的某個象限裡去，
    所以先用井心粗篩（離兩條線都 >= CLEAR_OFF + 5），過了才逐格細查。
    每個候選要（1）井身每一格離兩條線的中心線都夠遠（別擋住別人的通道帶）、
    （2）井身不撞任何結構或已蓋的井與通道、（3）兩段通道各自在自己那一層
    不撞東西。第一個過的就用。

    回傳 dict(ok, well, legs, reason)：
      well   (x0, z0, ux, uz, top, bottom) 或 None（直接接時）
      legs   [(box_tag, level, cells)]，各層要鋪的地板格（含洞）
    """
    A, B = _box(box_a), _box(box_b)
    pairs = _pairs(A, B)
    if not pairs:
        return dict(ok=False, reason="站體沒有可開洞的付費區")
    d = pairs[0][0]
    if d > TRANSFER_MAX_M:
        return dict(ok=False, reason=f"兩座站體相距 {d:.0f} m，太遠")
    _, ka, sa, pa, kb, sb, pb = pairs[0]
    la = int(A["ys"][ka]) + LEVEL_DY[A["kind"]]
    lb = int(B["ys"][kb]) + LEVEL_DY[B["kind"]]

    # ---- 同一層：一條通道直接接，最近的接點對被擋就換下一對 ----
    if abs(la - lb) <= LEVEL_DIRECT:
        reasons = {}
        for _, ka, sa, pa, kb, sb, pb in pairs[:MAX_PAIRS]:
            la = int(A["ys"][ka]) + LEVEL_DY[A["kind"]]
            pts = [offset_point(A["samples"], ka, sa * (BOX_HALF - 1)), pa, pb,
                   offset_point(B["samples"], kb, sb * (BOX_HALF - 1))]
            cells = polyline_cells(pts, PASS_HALF) - A["interior"] - B["interior"]
            cells |= hole_cells(A["samples"], A["lo"], A["hi"], ka, sa)
            cells |= hole_cells(B["samples"], B["lo"], B["hi"], kb, sb)
            # 檢查 A 那一頭時，B 站體周圍的格子要豁免（反之亦然）：通道本來就
            # 要穿進兩座站體，外緣一圈也一定貼著人家的箱涵
            why = _leg_blocked(A, cells, la, occ, used, B["own"])
            if why is None:
                why = _leg_blocked(B, cells, la, occ, used, A["own"])
            if why is not None:
                reasons["通道" + why[0]] = reasons.get("通道" + why[0], 0) + 1
                continue
            for c in cells:
                used.add(c[0], c[1], la - 1, la + 3, passage_tag(A["tag"], la))
            return dict(ok=True, well=None, legs=[(A["tag"], la, cells)], reason=None,
                        length=len(cells))
        why = "、".join(f"{k} {v}" for k, v in sorted(reasons.items(), key=lambda kv: -kv[1]))
        return dict(ok=False, reason=f"試了 {min(len(pairs), MAX_PAIRS)} 對接點都接不上（{why}）")
    if abs(la - lb) < LEVEL_WELL:
        return dict(ok=False, reason=f"兩層只差 {abs(la - lb)} m，井的兩扇門會互相切到")

    # ---- 不同層：找井的位置 ----
    mx, mz = (pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2
    r = int(d / 2) + 60
    cands = []
    for gx in range(int(mx) - r, int(mx) + r + 1, GRID_M):
        for gz in range(int(mz) - r, int(mz) + r + 1, GRID_M):
            est = math.hypot(gx - pa[0], gz - pa[1]) + math.hypot(gx - pb[0], gz - pb[1])
            cands.append((est, gx, gz))
    cands.sort()
    y_lo, y_hi = well_span(la, lb)
    tries = 0
    reasons = {}
    for est, gx, gz in cands:
        if tries >= MAX_TRIES:
            break
        if _near_off(A, gx, gz) < CLEAR_OFF + 5 or _near_off(B, gx, gz) < CLEAR_OFF + 5:
            continue                                   # 粗篩：井心就太近了
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            tries += 1
            if _near_off(A, gx, gz, dx, dz) < CLEAR_OFF or _near_off(B, gx, gz, dx, dz) < CLEAR_OFF:
                reasons["井離站體太近"] = reasons.get("井離站體太近", 0) + 1
                continue
            cells = shaft_cells(gx, gz, dx, dz)
            if occ.any_blocked(cells, y_lo, y_hi) or used.any_blocked(cells, y_lo, y_hi):
                reasons["井撞到東西"] = reasons.get("井撞到東西", 0) + 1
                continue
            door = (gx - dx, gz - dz)
            porch = (gx - 5 * dx, gz - 5 * dz)
            # 井身（門那一排與井口平台除外）：通道從門廊轉向站體時，站體若在井的
            # 側後方，直線會斜切過井身 —— 井是在通道之後蓋的，井壁一補回去通道
            # 就斷了（板橋、頭前庄、南港展覽館的轉乘都是這樣走到井頂就沒路）
            body = {c for c in cells
                    if (c[0] - gx) * dx + (c[1] - gz) * dz >= 2}
            legs, bad = [], None
            for bx in (A, B):
                leg = _leg(bx, porch[0], porch[1])
                if leg is None:
                    bad = "找不到開洞位置"; break
                k, side, level, pts, holes = leg
                lcells = polyline_cells([door] + pts, PASS_HALF) - bx["interior"] | holes
                if lcells & body:
                    bad = "通道穿過井身"; break
                why = _leg_blocked(bx, lcells, level, occ, used, cells)
                if why is not None:
                    bad = "通道" + why[0]; break
                legs.append((bx["tag"], level, lcells))
            if bad is not None:
                reasons[bad] = reasons.get(bad, 0) + 1
                continue
            # 兩段通道在門口那幾格會重疊，但一在上一在下（差 >= LEVEL_WELL），碰不到
            for c in shaft_cells(gx, gz, dx, dz, margin=1):
                used.add(c[0], c[1], y_lo, y_hi, ("井", "轉乘"))
            for tag, level, lcells in legs:
                for c in lcells:
                    used.add(c[0], c[1], level - 1, level + 3, passage_tag(tag, level))
            top, bottom = max(legs[0][1], legs[1][1]), min(legs[0][1], legs[1][1])
            return dict(ok=True, well=(gx, gz, dx, dz, top, bottom), legs=legs,
                        reason=None, tries=tries,
                        length=sum(len(l[2]) for l in legs))
    why = "、".join(f"{k} {v}" for k, v in sorted(reasons.items(), key=lambda kv: -kv[1]))
    return dict(ok=False, reason=f"試了 {tries} 個位置都擺不下井（{why}）")
