#!/usr/bin/env python3
"""疊式車站與袋狀軌：一條線的兩股道在車站分到上下兩層、或區間裡多出第三股道。

北捷不是每一座地下站都是「島式月台、兩股道在同一層」：

  · 府中（BL06）是地下五層的**側式疊式月台**：B3 一月台往南港展覽館、B5 二月台
    往頂埔，兩股道上下疊在同一個位置，月台都在往南港展覽館方向的左側
    （B3 左側開門、B5 右側開門）。OSM 的兩塊月台多邊形（level -3 / -4）
    落在完全相同的位置，就是這個意思。
  · 西門（BL11/G12）是**島式疊式月台的平行轉乘站**：B2 板南線往南港展覽館
    （右側開門）＋松山新店線往松山（左側開門）共用一座島式月台，B3 板南線往頂埔
    （左側開門）＋松山新店線往新店（右側開門）共用另一座。板南線的兩股道疊在
    西側、松山新店線的疊在東側，每一層都是「一股板南、一座島、一股松山新店」。
    OSM 的兩塊月台（layer -2 / -3）中心正好落在兩條線的中線上。

兩者要的是同一件事：**一條線的兩股道在車站附近分到上下兩層**。做法：

  1. 站體外 SPLIT_M 公尺處，其中一股道開始以最大坡度下潛 LEVEL_H 公尺，
     另一股維持線形的軌面。哪一股下潛由 ``upper_toward`` 決定：北捷靠右行駛，
     往那一站行駛的列車走的是行進方向右側那股道，它留在上層，對面那股下潛。
  2. 進站前 FLARE_M 公尺，兩股道從 ±3 的離線位併到同一個離線位（上下疊）。
     共用站體的（西門），兩條線各自的兩股道併到站體座標系裡 ±8 的位置；站體
     以兩條線的中線為準（``shift_samples`` 做出來的 frame），只由 primary
     那條線蓋一次，partner 那條線在站體範圍內不蓋斷面、也不再有自己的車站。
  3. 站體是 21 格高的雙層箱涵：上層就是原本的島式站（dy -2..10，穿堂仍在
     軌面 +7，所以出入口、轉乘通道與驗證工具全部不必改），下層在 dy -10..-2。

袋狀軌（POCKETS）是區間裡兩股正線之間多出來的一股儲車軌：正線先張開到
±POCKET_OFF，中間鋪第三股道，再收回 ±3。沒有道岔（見 README 已知限制），
第三股道在正線收攏到離它太近之前就結束。

哪一股道在上層、月台在哪一側、袋狀軌在哪裡，都是 OSM 沒有的真實資料，
出處寫在各筆旁邊。
"""
import numpy as np

from mrt.domain.alignment import (
    BOX_HALF, MAX_GRADE, PLAT_HALF, PLATFORM_LEN, STEP, STN_TRACK_OFF,
    TUN_TRACK_OFF,
)
from mrt.domain.alignment import FLARE_M as STATION_FLARE_M

# 下層軌面比上層低幾格。上層月台廳佔 dy -1..5、穿堂樓板在 6；下層放在 -8 才有
# 自己的底板（-10）、月台（-7）、四格淨空（-6..-3）與頂板（-2，就是上層的底板）。
LEVEL_H = 8
RAMP_M  = LEVEL_H / MAX_GRADE      # 下潛 8 m 要走 200 m
FLARE_M = 40                       # 兩股道從 ±3 併到目標離線位的過渡長度
SPLIT_M = RAMP_M + FLARE_M         # 站體之外的過渡段總長
BOX_BOTTOM_DY = -(LEVEL_H + 2)     # 雙層箱涵的底板

POCKET_OFF     = 6                 # 袋狀軌段正線的離線位（第三股道在 0）
POCKET_FLARE_M = 60                # 正線張開／收攏的過渡長度（實際的道岔段約 80 m）
POCKET_LEN_M   = 190               # 儲車軌長度：北捷後期路網的中央避車線內部約 190 m
POCKET_MIN_GAP = 4.5               # 正線離中線不到這麼近，第三股道就結束（沒有道岔）
ALLY_M         = 500               # 共用站體的兩條線在站區這個半徑內彼此不算占用（深度帶）


# ---------- 真實資料 ----------

# (站名, 路線) -> 規格
#   kind          "side"   側式疊式（一股道一層，月台在同一側）
#                 "shared" 兩條線共用的島式疊式（每層一股自己的道、一座島、一股對方的道）
#   upper_toward  上層那股道的列車往哪一站開（同一條線的鄰站）
#   plat          "left" / "right"：月台在上層列車行進方向的哪一側（只有 side 用）
#   partner       共用站體的另一條線（只有 shared 用；寫在 primary 那一筆）
STACKED = {
    # 維基百科「府中站 (臺灣)」車站構造：地下五層，側式疊式月台。
    # 地下三樓一月台 板南線往南港展覽館 左側開門；地下五樓二月台 往頂埔 右側開門。
    ("府中", "BL"): dict(kind="side", upper_toward="板橋", plat="left"),
    # 維基百科「西門站 (臺北市)」月台配置：地下二樓 板南線往南港展覽館（右側開門）、
    # 松山新店線往松山（左側開門）；地下三樓 板南線往頂埔（左側開門）、
    # 松山新店線往新店（右側開門）。
    ("西門", "BL"): dict(kind="shared", partner="G", upper_toward="台北車站"),
    ("西門", "G"):  dict(kind="shared", upper_toward="北門"),
}

# 袋狀軌：路線、兩端的站、OSM 上那條儲車軌的 way id（data/sidings.json 有它就
# 照它的幾何放）、沒有資料時的退路（儲車軌起點離甲站站體中心幾公尺、長度）。
# 板南線只有這兩處，兩份車迷畫的軌道配置圖與 OSM 都只畫這兩處：
#   忠孝復興—忠孝敦化：維基百科「忠孝敦化站」：「本站與忠孝復興站間設有可供列車
#     調度的袋狀軌」。OSM way 877532286（211 m），緊貼忠孝敦化站西側。
#   亞東醫院—海山：亞東醫院折返列車用的儲車軌在站體南側（往海山方向），
#     土城機廠的機廠線也在這裡分歧。OSM 五條 way 名叫「亞東醫院袋狀軌」，
#     中央那條是 818792051（197 m）。捷運公司的駕駛室影片在亞東醫院開車後
#     29～68 秒看得到這座箱涵、兩端的道岔與第三股道。
POCKETS = [
    dict(ref="BL", a="忠孝復興", b="忠孝敦化", osm=877532286, start=None, length=POCKET_LEN_M),
    dict(ref="BL", a="亞東醫院", b="海山", osm=818792051, start=300, length=POCKET_LEN_M),
]


# ---------- 方向與版面 ----------

def direction_sign(idx, idx_toward):
    """從 idx 往 idx_toward 那一站走，是取樣順序的正向（+1）還是反向（-1）。"""
    return 1 if idx_toward > idx else -1


def upper_side(direction):
    """上層那股道在線形的哪一側（+1 = 取樣方向的右手邊，即 nx,nz 那一側）。

    靠右行駛：往 +u 方向開的列車走 +off 那股道，往 -u 開的走 -off。
    """
    return direction


def plat_side(direction, plat):
    """側式月台在線形的哪一側。plat 是相對上層列車行進方向的左右。"""
    return -direction if plat == "left" else direction


def layout(kind, side):
    """一層月台的版面（站體座標系的離線位）：
      tracks  這一層有哪幾股道
      psd     月台門
      yellow  警示帶
      plat    月台鋪面的離線位範圍（含兩端）
      stair   穿堂下月台的樓梯離線位範圍
      lstair  上層月台下到下層月台的樓梯離線位範圍
    kind="side" 的 side 是月台那一側；kind="shared" 的 side 是 partner 那條線那一側。
    """
    if kind == "side":
        s = side
        return dict(tracks=[-STN_TRACK_OFF * s], psd=[-PLAT_HALF * s],
                    yellow=[-(PLAT_HALF - 1) * s],
                    plat=(min(-(PLAT_HALF - 1) * s, (BOX_HALF - 2) * s),
                          max(-(PLAT_HALF - 1) * s, (BOX_HALF - 2) * s)),
                    stair=(min(0, 2 * s), max(0, 2 * s)),
                    lstair=(min(6 * s, 8 * s), max(6 * s, 8 * s)))
    return dict(tracks=[-STN_TRACK_OFF * side, STN_TRACK_OFF * side],
                psd=[-PLAT_HALF, PLAT_HALF],
                yellow=[-(PLAT_HALF - 1), PLAT_HALF - 1],
                plat=(-(PLAT_HALF - 1), PLAT_HALF - 1),
                stair=(-3, 3), lstair=(-3, 3))


# ---------- 座標系 ----------

def shift_samples(samples, m):
    """整條取樣序列沿法向平移 m 公尺（+m = 右手邊）。共用站體的 frame 就是
    primary 的取樣點平移到兩線中線。"""
    return [(x - uz * m, z + ux * m, ux, uz, k) for x, z, ux, uz, k in samples]


def station_samples(sg, bi):
    """車站 bi 的站體座標系：共用站體用 frame，其餘就是路段自己的取樣點。"""
    return sg.get("frames", {}).get(bi, sg["samples"])


def tracks_at(sg, i):
    """取樣點 i 有哪幾股道：[(離線位, 軌面 y), ...]。

    分層過渡段（sg["split"]）裡兩股道各有自己的離線位與軌面；其餘是 ±toff、
    同一個軌面。袋狀軌（sg["extras"]）的第三股道落在範圍內就一起回傳。
    """
    y = int(sg["ys"][i])
    if sg.get("split") is not None and sg["split"][i]:
        out = [(float(sg["off_side"][s][i]), int(sg["y_side"][s][i])) for s in (1, -1)]
    else:
        t = float(sg["toff"][i]) if "toff" in sg else float(TUN_TRACK_OFF)
        out = [(t, y), (-t, y)]
    for ex in sg.get("extras", ()):
        if ex["i0"] <= i <= ex["i1"]:
            out.append((float(ex["off"]), y))
    return out


def strands(sg):
    """鐵軌要鋪的每一股道：[(i0, i1, off_at(i), y_at(i)), ...]。兩股正線整段各一，
    袋狀軌另外一股。"""
    n = len(sg["samples"])
    split = sg.get("split")
    out = []
    for s in (1, -1):
        def off_at(i, s=s):
            if split is not None and split[i]:
                return float(sg["off_side"][s][i])
            return s * float(sg["toff"][i])

        def y_at(i, s=s):
            if split is not None and split[i]:
                return int(sg["y_side"][s][i])
            return int(sg["ys"][i])
        out.append((0, n - 1, off_at, y_at))
    for ex in sg.get("extras", ()):
        out.append((ex["i0"], ex["i1"], lambda i, o=ex["off"]: float(o),
                    lambda i: int(sg["ys"][i])))
    return out


def lateral_offset(samples, j, x, z):
    """點 (x, z) 在取樣點 j 座標系裡的離線位（+ = 右手邊）。"""
    sx, sz, ux, uz, _ = samples[j]
    return -(x - sx) * uz + (z - sz) * ux


def nearest(samples, x, z, lo=0, hi=None):
    hi = len(samples) - 1 if hi is None else hi
    best, bi = 1e18, lo
    for j in range(lo, hi + 1):
        d = (samples[j][0] - x) ** 2 + (samples[j][1] - z) ** 2
        if d < best:
            best, bi = d, j
    return bi


def frame_track_offsets(samples, lo, hi, frame, flo, fhi, foff):
    """partner 的取樣點 lo..hi 逐點算「frame 座標系裡離線位 foff 的那條線」
    落在自己座標系的哪個離線位。兩條線在站體內幾乎平行，用最近的 frame 點就夠。"""
    pts = [(frame[i][0] - frame[i][3] * foff, frame[i][1] + frame[i][2] * foff)
           for i in range(flo, fhi + 1)]
    out = []
    for j in range(lo, hi + 1):
        sx, sz = samples[j][0], samples[j][1]
        px, pz = min(pts, key=lambda p: (p[0] - sx) ** 2 + (p[1] - sz) ** 2)
        out.append(lateral_offset(samples, j, px, pz))
    return out


# ---------- 兩股道分層 ----------

def split_sides(n, lo, hi, up_side, tgt_in, ys, step=STEP):
    """把兩股道在車站 lo..hi 附近分到上下兩層。

    tgt_in  站體範圍內每個取樣點兩股道併到的離線位（len = hi - lo + 1）
    回傳 (off_side, y_side, multi)：
      off_side[s]  s = ±1 那股道逐點的離線位（區間仍是 ±3）
      y_side[s]    逐點的軌面；下潛那股在站內是 ys - LEVEL_H
      multi        bool 陣列，True 的取樣點斷面要用 sec_multi 蓋
    """
    ys = np.asarray(ys)
    off_side = {1: np.full(n, float(TUN_TRACK_OFF)), -1: np.full(n, -float(TUN_TRACK_OFF))}
    y_side = {1: ys.astype(float).copy(), -1: ys.astype(float).copy()}
    multi = np.zeros(n, dtype=bool)
    fl = max(1, int(round(FLARE_M / step)))
    rp = max(1, int(round(RAMP_M / step)))
    down = -up_side
    tgt = list(tgt_in)
    for i in range(lo, hi + 1):
        t = tgt[i - lo]
        off_side[1][i] = off_side[-1][i] = t
        y_side[down][i] = ys[i] - LEVEL_H
        multi[i] = True
    for end, sgn, t_end in ((lo, -1, tgt[0]), (hi, 1, tgt[-1])):
        for j in range(1, fl + 1):                           # 併攏
            i = end + sgn * j
            if not (0 <= i < n):
                break
            f = j / fl
            for s in (1, -1):
                off_side[s][i] = t_end + (s * TUN_TRACK_OFF - t_end) * f
            y_side[down][i] = ys[i] - LEVEL_H
            multi[i] = True
        for j in range(1, rp + 1):                           # 下潛
            i = end + sgn * (fl + j)
            if not (0 <= i < n):
                break
            y_side[down][i] = ys[i] - LEVEL_H * (1 - j / rp)
            multi[i] = True
    for s in (1, -1):
        y_side[s] = np.round(y_side[s]).astype(int)
    return off_side, y_side, multi


def split_extent(lo, hi, n, step=STEP):
    """分層過渡段涵蓋的取樣索引範圍（含站體）。"""
    ext = int(round(SPLIT_M / step))
    return max(0, lo - ext), min(n - 1, hi + ext)


def station_range(n, bi, step=STEP):
    half = int(PLATFORM_LEN / 2 / step)
    return max(0, bi - half), min(n - 1, bi + half)


def _ensure_split(sg):
    """路段第一次有分層時，把兩股道的逐點陣列補上（預設 ±3、同一個軌面）。"""
    n = len(sg["samples"])
    if "split" not in sg:
        sg["off_side"] = {1: np.full(n, float(TUN_TRACK_OFF)),
                          -1: np.full(n, -float(TUN_TRACK_OFF))}
        sg["y_side"] = {1: np.asarray(sg["ys"]).astype(int).copy(),
                        -1: np.asarray(sg["ys"]).astype(int).copy()}
        sg["split"] = np.zeros(n, dtype=bool)
    if "multi" not in sg:
        sg["multi"] = np.zeros(n, dtype=bool)


def _apply_split(sg, lo, hi, up_side, tgt):
    _ensure_split(sg)
    off_side, y_side, multi = split_sides(len(sg["samples"]), lo, hi, up_side, tgt, sg["ys"])
    for s in (1, -1):
        sg["off_side"][s][multi] = off_side[s][multi]
        sg["y_side"][s][multi] = y_side[s][multi]
    sg["split"] |= multi
    sg["multi"] |= multi


def plan_side(sg, bi, direction, plat):
    """側式疊式站（府中）：釘平縱斷面、兩股道分層。direction 是上層列車的行進
    方向（取樣順序的 ±1），plat 是月台在那個方向的左或右。回傳版面
    （也記在 sg["stacked"][bi]，cli 與出入口規劃靠它認出疊式站）。"""
    n = len(sg["samples"])
    lo, hi = station_range(n, bi)
    fl = int(round(FLARE_M / STEP))
    sg["ys"] = pin_profile(sg["ys"], max(0, lo - fl), min(n - 1, hi + fl), int(sg["ys"][bi]))
    lay = layout("side", plat_side(direction, plat))
    _apply_split(sg, lo, hi, upper_side(direction), [lay["tracks"][0]] * (hi - lo + 1))
    sg.setdefault("stacked", {})[bi] = lay
    return lay


def plan_shared(sg, bi, direction, psg, pbi, pdirection):
    """兩線共用的島式疊式站（西門）。sg 是 primary（蓋站體的那條線），psg 是
    partner。站體座標系是 primary 的取樣點平移到兩線中線（frame）；primary 的
    兩股道併到 frame 的 −8·side、partner 的併到 +8·side（side 是 partner 在
    primary 的哪一側）。partner 的軌面釘成跟 primary 一樣，在站體範圍內不蓋
    斷面（nobuild）、也不再有自己的車站。回傳 (版面, 中線偏移 m, side, partner 的站體範圍)。"""
    n, pn = len(sg["samples"]), len(psg["samples"])
    lo, hi = station_range(n, bi)
    fl = int(round(FLARE_M / STEP))
    y_c = int(sg["ys"][bi])
    px, pz = psg["samples"][pbi][0], psg["samples"][pbi][1]
    doff = lateral_offset(sg["samples"], bi, px, pz)
    side = 1 if doff >= 0 else -1
    m = int(abs(doff) // 2)
    frame = shift_samples(sg["samples"], side * m)
    sg.setdefault("frames", {})[bi] = frame
    sg["ys"] = pin_profile(sg["ys"], max(0, lo - fl), min(n - 1, hi + fl), y_c)
    lay = layout("shared", side)
    _apply_split(sg, lo, hi, upper_side(direction),
                 [side * (m - STN_TRACK_OFF)] * (hi - lo + 1))
    plo = nearest(psg["samples"], frame[lo][0], frame[lo][1])
    phi = nearest(psg["samples"], frame[hi][0], frame[hi][1])
    if plo > phi:
        plo, phi = phi, plo
    ptgt = frame_track_offsets(psg["samples"], plo, phi, frame, lo, hi, side * STN_TRACK_OFF)
    psg["ys"] = pin_profile(psg["ys"], max(0, plo - fl), min(pn - 1, phi + fl), y_c)
    _apply_split(psg, plo, phi, upper_side(pdirection), ptgt)
    psg.setdefault("nobuild", set()).update(range(plo, phi + 1))
    psg["stn"].pop(pbi, None)
    sg.setdefault("stacked", {})[bi] = lay
    return lay, m, side, (plo, phi)


def plan_pocket(sg, ia, ib, start_m, length_m, rng=None):
    """在 sg 的 ia、ib 兩站之間開袋狀軌：正線離線位就地張開、第三股道記進
    sg["extras"]。要在 track_offsets 之後、算 hw 之前呼叫。回傳 (i0, i1) 或 None。"""
    n = len(sg["samples"])
    if "multi" not in sg:
        sg["multi"] = np.zeros(n, dtype=bool)
    res = pocket_zone(sg["toff"], n, ia, ib, start_m, length_m, rng=rng)
    if res is None:
        return None
    i0, i1, multi = res
    sg["multi"] |= multi
    sg.setdefault("extras", []).append(dict(i0=i0, i1=i1, off=0.0))
    return i0, i1


# ---------- 袋狀軌 ----------

def pocket_zone(toff, n, ia, ib, start_m, length_m, step=STEP, rng=None,
                off=POCKET_OFF, flare_m=POCKET_FLARE_M, min_gap=POCKET_MIN_GAP):
    """在 ia、ib 兩站之間開一段袋狀軌。就地把正線的離線位張開，回傳
    (i0, i1, multi)：第三股道占的取樣範圍，與要用 sec_multi 蓋的遮罩。

    rng      (i0, i1)：儲車軌的取樣範圍（OSM 畫了那條軌就用它，只夾進兩站之間
             放得下的範圍）；沒有的話用 start_m / length_m
    start_m  儲車軌起點離 ia 站體中心幾公尺（None = 置於兩站正中間）
    """
    half = int(PLATFORM_LEN / 2 / step)
    fl = max(1, int(round(flare_m / step)))
    ln = int(round(length_m / step))
    a, b = (ia, ib) if ia < ib else (ib, ia)
    # 兩站進站張開段（±3 -> ±8，FLARE_M）之外才是袋狀軌的地盤；忠孝敦化那一處
    # 的道岔腿在 OSM 上一路畫到站體西端，儲車軌本身離站體只有 90 m
    stn_fl = int(round(STATION_FLARE_M / step))
    free_lo, free_hi = a + half + stn_fl, b - half - stn_fl
    if rng is not None:
        i0, i1 = max(free_lo + fl, min(rng)), min(free_hi - fl, max(rng))
    else:
        if start_m is None:
            c = (a + b) // 2
            i0 = c - ln // 2
        else:
            i0 = (ia + int(round(start_m / step))) if ia < ib else (ia - int(round(start_m / step)) - ln)
        i0 = max(free_lo + fl, min(free_hi - fl - ln, i0))
        i1 = i0 + ln
    if i1 - i0 < 2 * fl or i0 < free_lo:
        return None
    multi = np.zeros(n, dtype=bool)
    for i in range(i0, i1 + 1):
        toff[i] = max(toff[i], float(off))
    for j in range(1, fl + 1):
        v = off + (TUN_TRACK_OFF - off) * j / fl
        toff[i0 - j] = max(toff[i0 - j], v)
        toff[i1 + j] = max(toff[i1 + j], v)
    for i in range(i0 - fl, i1 + fl + 1):
        multi[i] = True
    # 第三股道往兩端的張開段延伸，到正線離中線不到 min_gap 為止
    lo, hi = i0, i1
    while lo - 1 >= i0 - fl and toff[lo - 1] >= min_gap:
        lo -= 1
    while hi + 1 <= i1 + fl and toff[hi + 1] >= min_gap:
        hi += 1
    return lo, hi, multi


# ---------- 縱斷面釘平 ----------

def pin_profile(ys, lo, hi, y_c, step=STEP, grade=MAX_GRADE):
    """把 lo..hi 釘平在 y_c，兩側以最大坡度收斂回原本的縱斷面（升降都夾）。

    共用站體的兩條線軌面要一模一樣，兩層月台之間的樓梯也要站體是平的才蓋得準。
    原本的縱斷面只往下夾（下包絡線），釘平之後鄰近的點可能比 y_c 低太多或高太多，
    這裡從釘平段往外走，每一步都夾在 ±坡度 之內。
    """
    y = np.asarray(ys, dtype=float).copy()
    n = len(y)
    d = grade * step
    y[lo:hi + 1] = y_c
    for i in range(hi + 1, n):
        y[i] = min(max(y[i], y[i - 1] - d), y[i - 1] + d)
    for i in range(lo - 1, -1, -1):
        y[i] = min(max(y[i], y[i + 1] - d), y[i + 1] + d)
    return np.round(y).astype(int)


def stacked_pins(stations, refs_of, band=0, radius_m=410.0, reserve_m=60.0):
    """疊式車站的深度帶釘樁：

      · 車站本身釘在 band（西門 B2/B3、府中 B3/B5 都是淺層），共用站體的兩條線
        釘在同一帶 —— 它們本來就是同一座箱涵。
      · 下層在上層底下 LEVEL_H，21 格高的箱涵會伸進下一帶的深度，所以站體
        範圍另外替下一帶占位，別條線不能從底下鑽過去。

    stations  [(refs, 站名, x, z, ...)]（cli.load_stations 的格式）
    refs_of   站名 -> 這座站在 STACKED 裡登記的路線代號集合
    回傳 tunnel_layers.assign_bands 的 pins 格式 [(x, z, 半徑, ref, band)]。
    真正的釘樁排在前面，占位的排在後面 —— assign_bands 對自己的線取第一根命中的。
    """
    pins, reserve = [], []
    for row in stations:
        name, x, z = row[1], row[2], row[3]
        for ref in sorted(refs_of.get(name, ())):
            pins.append((x, z, radius_m, ref, band))
            reserve.append((x, z, reserve_m, ref, band + 1))
    return pins + reserve
