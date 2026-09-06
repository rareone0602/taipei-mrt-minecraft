#!/usr/bin/env python3
"""線形：取樣、縱斷面、軌道離線位、路線變體挑選。

這裡全是純函式 —— 輸入折線與標籤，輸出座標與高度，不碰存檔也不寫方塊。
原本這些和「把方塊放進世界」的程式混在同一支 build_line.py 裡，但兩者的
變動理由完全不同：斷面長怎樣是美術決定，線形算得對不對是工程決定。
分開之後線形可以單獨測（見 tests/test_alignment.py），不必產生一個世界。

比例 1 方塊 = 1 公尺。座標 X = 東、Z = 南。
"""
import math

GROUND     = 64        # 超平坦地表最上層方塊
STEP       = 0.5       # 沿線取樣間距（公尺）
MAX_GRADE  = 0.04      # 最大坡度 4%
PIER_EVERY = 25        # 橋墩間距

# 各型態的走行面相對地面高度
PROFILE = {"bridge": 13, "ground": 1, "tunnel": -20}

PLATFORM_LEN = 70

# ---- 站體尺寸（dy 皆相對走行面 y）----
# 地下站是「島式月台 + 上方穿堂層」的雙層箱涵：
#   dy -2 底板 / y 走行面 / y+1 月台面 / dy 6 穿堂樓板 / dy 10 頂板
# 共 13 格高，所以隧道分層必須拉到 15 m 間距。
BOX_HALF      = 12     # 站體半寬（含 2 格襯砌）
PLAT_HALF     = 6      # 島式月台半寬 -> 13 m 寬
STN_TRACK_OFF = 8      # 站內軌道中心離線位
TUN_TRACK_OFF = 3      # 區間隧道軌道中心離線位
MEZZ_DY       = 6      # 穿堂層樓板
BOX_TOP_DY    = 10     # 站體頂板
FLARE_M       = 40     # 軌道由 ±3 張開到 ±8 的過渡長度


# ---------- 取樣與平滑 ----------

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

# ---------- 結構型態 ----------

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

# ---------- 路線變體 ----------

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

