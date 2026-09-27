#!/usr/bin/env python3
"""中式宮殿建築的共用零件：台基、欄杆、半階樓梯、屋頂（廡殿推山、歇山、八角攢尖、
重簷的腰簷）、屋脊與簷口描邊、斗拱帶、寶頂，以及一座「重簷宮殿式廳堂」的整套砌法。

中正紀念堂園區（紀念堂、國家戲劇院、國家音樂廳、自由廣場牌樓）與國父紀念館共用。
這個模組不是一座景點，沒有 BUILDS；座標慣例與 kit.py 相同（Frame 的局部 u、v，
方塊 (x, z) 的中心在 (x+.5, z+.5)），寫入一律經過呼叫端給的 Painter（已包 Guard）。

高度的說法：G 是基地地面那一格方塊的 y（人站在 G+1）。「s 公尺高的站立面」
= 人的腳在 G+1+s；s 是 0.5 的倍數時，小數那半格用下半磚。
"""
import math

import numpy as np

from mrt.application.attractions import kit
from mrt.application.attractions.kit import Frame

AIR = kit.AIR


# ---------------------------------------------------------------- 框與輪廓

def local_bbox(fr, ring):
    """世界座標的多邊形 -> 在 fr 局部座標裡的 (u0, u1, v0, v1)。"""
    pts = [fr.local(x - 0.5, z - 0.5) for x, z in ring]   # local() 量的是格心，這裡要的是點
    us = [p[0] for p in pts]
    vs = [p[1] for p in pts]
    return min(us), max(us), min(vs), max(vs)


def ring_centroid(ring):
    """多邊形的面積重心（世界座標）。"""
    a = cx = cz = 0.0
    n = len(ring)
    for i in range(n):
        x1, z1 = ring[i]
        x2, z2 = ring[(i + 1) % n]
        c = x1 * z2 - x2 * z1
        a += c
        cx += (x1 + x2) * c
        cz += (z1 + z2) * c
    if abs(a) < 1e-9:
        return sum(p[0] for p in ring) / n, sum(p[1] for p in ring) / n
    return cx / (3 * a), cz / (3 * a)


def sub_frame(fr, u, v, extent, turn=0.0):
    """跟 fr 同方向（再轉 turn 弧度）、原點在 fr 的局部 (u, v) 的新框。"""
    x, z = fr.world(u, v)
    return Frame(x, z, fr.angle + turn, extent)


# ---------------------------------------------------------------- 寫入小工具

def steps(p, mask, g, s, block, slab):
    """半階樓梯（或任何站立面）：遮罩每格填到站立面 s（公尺，0.5 的倍數），
    從 g+1 開始往上填實心，小數半格用下半磚。s <= 0 的格子不寫。
    slab 帶不帶 [type=...] 都可以（Painter.heightfield 會自己加 [type=bottom]）。"""
    m = mask & (np.asarray(s) > 0)
    slab_id = slab.split("[")[0] if slab else None
    p.heightfield(m, g + 1, np.asarray(s, dtype=float) - 1.0, block, slab=slab_id)


def half_flight(t, s0, n):
    """一段半階梯段的站立面：t 是沿上坡方向、從梯段起點量的距離（公尺），
    第 k 格（k = floor(t)）的站立面 = s0 + 0.5 (k+1)，最多 n 階。t < 0 回 s0。"""
    k = np.floor(t)
    return np.where(t < 0, s0, s0 + 0.5 * (np.clip(k, -1, n - 1) + 1))


def balustrade(p, mask, y, rail, post, cap=None, every=3, skip=None):
    """台基邊緣的欄杆：遮罩外圈一格寬，高一格；每 every 格一根望柱（post），
    望柱頂上再加 cap（例如石英半磚），比欄板高半格。skip 遮罩裡的格子不立
    （樓梯口）。y 可以是整數或陣列（沿著樓梯斜上去的扶手）。"""
    rg = kit.ring(mask)
    if skip is not None:
        rg &= ~skip
    Y = np.broadcast_to(np.asarray(y), p.fr.shape)
    X, Z, YY = p.fr.X[rg].tolist(), p.fr.Z[rg].tolist(), np.rint(Y[rg]).astype(int).tolist()
    for x, z, yy in zip(X, Z, YY):
        if (x + 2 * z) % every == 0:
            p.set(x, yy, z, post)
            if cap:
                p.set(x, yy + 1, z, cap)
        else:
            p.set(x, yy, z, rail)


def band(p, mask, y0, y1, a, b, period=2):
    """斗拱帶：遮罩每格 y0..y1，a、b 兩種方塊沿格子交錯（遠看是一排一排的斗拱）。"""
    X, Z = p.fr.X[mask].tolist(), p.fr.Z[mask].tolist()
    for x, z in zip(X, Z):
        blk = a if ((x + z) // period) % 2 == 0 else b
        for y in range(int(y0), int(y1) + 1):
            p.set(x, y, z, blk)


def sphere(p, u, v, y, r, block, y_min=None):
    """局部 (u, v)、高度 y（浮點數，格心量）為中心、半徑 r 的實心球。寶頂用。"""
    fr = p.fr
    near = np.hypot(fr.U - u, fr.V - v) <= r + 0.5
    X, Z, UU, VV = fr.X[near].tolist(), fr.Z[near].tolist(), fr.U[near].tolist(), fr.V[near].tolist()
    for x, z, uu, vv in zip(X, Z, UU, VV):
        d2 = (uu - u) ** 2 + (vv - v) ** 2
        for yy in range(int(math.floor(y - r)), int(math.ceil(y + r)) + 1):
            if y_min is not None and yy < y_min:
                continue
            if d2 + (yy + 0.5 - y) ** 2 <= r * r:
                p.set(x, yy, z, block)


def fine_angle(ring):
    """輪廓的主軸方向（弧度，0～90°）：各邊方向折到 90° 以內、依邊長加權的圓形平均。
    kit.principal_angle 取整數度，國父紀念館偏 1.65° 取成 2°，100 m 的邊兩端差 0.6 m。"""
    sx = sy = 0.0
    n = len(ring)
    for i in range(n):
        x1, z1 = ring[i]
        x2, z2 = ring[(i + 1) % n]
        L = math.hypot(x2 - x1, z2 - z1)
        a = math.atan2(z2 - z1, x2 - x1) * 4.0          # 四重對稱：0°、90°、180°、270° 疊在一起
        sx += L * math.cos(a)
        sy += L * math.sin(a)
    return (math.atan2(sy, sx) / 4.0) % (math.pi / 2)


def seated_statue(p, cu, cv, y0, face, body, chair):
    """坐姿銅像（高約 6 m）：椅子、腿、長袍、手、頭，用幾個橢球與方塊拼。
    (cu, cv) 是像的中心（局部座標），face 是面向的局部方向 (du, dv)，y0 是座底那一格。
    中正紀念堂的蔣中正像（坐姿 6.3 m）與國父紀念館的孫中山像（本體 5.8 m）共用。"""
    fr = p.fr
    fu, fv = face
    n = math.hypot(fu, fv)
    fu, fv = fu / n, fv / n
    du, dv = fr.U - cu, fr.V - cv
    near = np.hypot(du, dv) <= 5.0
    b = -(du * fu + dv * fv)                 # 往後為正（椅背那側）
    l = -du * fv + dv * fu                   # 左右
    X, Z = fr.X[near].tolist(), fr.Z[near].tolist()
    for x, z, u, v in zip(X, Z, b[near].tolist(), l[near].tolist()):
        av = abs(v)
        for k in range(0, 7):
            yy = k + 0.5
            blk = None
            if -0.5 <= u <= 2.2 and av <= 2.6 and yy <= 1.0:
                blk = chair                                            # 椅座
            if 1.5 <= u <= 2.4 and av <= 2.6 and yy <= 4.6:
                blk = chair                                            # 椅背
            if -0.8 <= u <= 1.8 and 1.8 < av <= 2.6 and 1.0 <= yy <= 2.0:
                blk = chair                                            # 扶手
            if -2.6 <= u <= 0.8 and av <= 1.6 and 1.0 <= yy <= 2.1:
                blk = body                                             # 大腿
            if -2.9 <= u <= -1.7 and av <= 1.6 and yy <= 1.2:
                blk = body                                             # 小腿、鞋
            if ((u - 0.6) / 1.2) ** 2 + (v / 1.7) ** 2 + ((yy - 3.1) / 1.5) ** 2 <= 1.0:
                blk = body                                             # 身體（長袍）
            if -1.4 <= u <= 0.9 and 1.4 < av <= 2.3 and 2.0 <= yy <= 3.3:
                blk = body                                             # 手臂
            if (u - 0.5) ** 2 + v ** 2 + (yy - 5.3) ** 2 <= 0.95:
                blk = body                                             # 頭
            if blk:
                p.set(x, y0 + k, z, blk)


# ---------------------------------------------------------------- 屋頂高度場
#
# 跟 kit 的屋頂一樣回傳「比簷口高多少」的陣列，但多回一個屋脊遮罩（正脊與垂脊／
# 戧脊），讓 roof() 在上面加一道脊。

def hip_ridge(fr, a, b, rise, ridge, profile=1.0, lift=0.0, corner=None, du=0.0, dv=0.0):
    """廡殿頂，正脊沿 u、半長 ridge（推山：兩端的坡比前後坡陡，正脊才拉得長）。
    kit.hip 的正脊一定沿長邊；戲劇院的屋頂進深比面寬還大，正脊卻平行正面，要用這個。"""
    u, v = np.abs(fr.U - du), np.abs(fr.V - dv)
    t_long = ((b - v) / b).clip(0, 1)                     # 前後坡：到簷口的比例
    t_end = ((a - u) / (a - ridge)).clip(0, 1)            # 兩端的坡
    t = np.minimum(t_long, t_end)
    h = rise * t ** profile
    d = np.minimum(a - u, b - v).clip(0, None)
    h = h + kit._lift(u, v, a, b, lift, corner, d)
    # 垂脊：兩種坡的比例相等處（到那條線的距離不到 0.6 m）；正脊：v≈0、|u|<=ridge
    k = b / (a - ridge)
    hips = np.abs((b - v) - (a - u) * k) / math.hypot(1.0, k) <= 0.6
    main = (v <= 0.6) & (u <= ridge + 0.5)
    ridge_m = (hips | main) & (u <= a) & (v <= b)
    return h, ridge_m


def hip_gable(fr, a, b, rise, gable_in, profile=1.0, lift=0.0, corner=None, du=0.0, dv=0.0):
    """歇山頂（kit.hip_gable）加上屋脊遮罩與山花遮罩。

    回傳 (h, 脊, 山花)：山花是 |u| = a - gable_in 內側那一格寬的直立三角形牆面
    （那一排的高度場從兩端小坡的高度直接跳到長坡的高度）。"""
    h = kit.hip_gable(fr, a, b, rise, gable_in, profile, lift, corner, du, dv)
    u, v = np.abs(fr.U - du), np.abs(fr.V - dv)
    ug = a - gable_in
    main = (v <= 0.6) & (u <= ug + 0.5)
    # 戧脊：兩端小坡與前後坡交界（(b - v) 與 (a - u) 相等），只在山花外側
    hips = (np.abs((b - v) - (a - u)) / math.sqrt(2.0) <= 0.6) & (u > ug)
    # 垂脊：山花邊緣順著前後坡往下
    verge = (np.abs(u - ug) <= 0.6) & (v <= b)
    gable = (u <= ug) & (u > ug - 1.0) & (v < b * 0.95)
    inside = (u <= a) & (v <= b)
    return h, (main | hips | verge) & inside, gable & inside


def octagon(fr, r, rise, profile=1.0, lift=0.0, du=0.0, dv=0.0):
    """八角攢尖（kit.pyramid sides=8，一條邊正對 +u）加上八條垂脊的遮罩。"""
    h = kit.pyramid(fr, r, rise, sides=8, rot=0.0, profile=profile, lift=lift, du=du, dv=dv)
    u, v = fr.U - du, fr.V - dv
    ds = np.stack([u * math.cos(2 * math.pi * k / 8) + v * math.sin(2 * math.pi * k / 8)
                   for k in range(8)])
    top2 = np.sort(ds, axis=0)[-2:]
    hips = (top2[1] - top2[0]) <= 0.55
    return h, hips


def skirt(fr, a_out, b_out, a_in, b_in, rise, profile=1.0, lift=0.0, corner=None):
    """重簷的下簷（腰簷）：外框 |u|<=a_out、|v|<=b_out 的簷口往內升到內框（上層屋身）
    的牆腳，內框裡面不算。回傳 (h, 遮罩)。"""
    u, v = np.abs(fr.U), np.abs(fr.V)
    w = min(a_out - a_in, b_out - b_in)
    d = np.minimum(a_out - u, b_out - v).clip(0, None)
    h = rise * (d / w).clip(0, 1) ** profile + kit._lift(u, v, a_out, b_out, lift, corner, d)
    m = (u <= a_out) & (v <= b_out) & ~((u < a_in) & (v < b_in))
    return h, m


# ---------------------------------------------------------------- 把高度場寫成屋頂

def roof(p, mask, base, h, tile, shell=2, under=None, rim=None, rim_under=None,
         ridge=None, ridge_mask=None, cap_ridge=True, rim_w=2):
    """屋頂殼：每格頂面 = floor(base + h)，往下 shell 格；鄰格比較低的地方往下補到
    跟最低的四鄰接起來（山花、兩層屋頂交界那種陡坎才不會漏空）。

    under     殼底下一格（簷下的椽子／天花的顏色）
    rim       簷口最外一圈的頂面方塊；rim_under 是簷口外 rim_w 圈頂面底下那一格
              （封簷板）。斜著的框外圈是鋸齒狀的，只換一圈的話從正面看會在白邊之間
              露出第二圈的瓦，所以封簷板預設兩圈寬
    ridge     屋脊：ridge_mask 的格子在頂面上再加一格（cap_ridge=False 就只換材質）
    回傳頂面高度陣列（int，遮罩外是很小的數），放脊獸、寶頂用。"""
    fr = p.fr
    T = np.full(fr.shape, -10 ** 6, dtype=np.int64)
    B = np.broadcast_to(np.asarray(base, dtype=float), fr.shape)
    H = np.broadcast_to(np.asarray(h, dtype=float), fr.shape)
    T[mask] = np.floor(B[mask] + H[mask]).astype(np.int64)
    big = 10 ** 6
    Tn = np.where(mask, T, big)
    low = Tn.copy()
    low[1:, :] = np.minimum(low[1:, :], Tn[:-1, :])
    low[:-1, :] = np.minimum(low[:-1, :], Tn[1:, :])
    low[:, 1:] = np.minimum(low[:, 1:], Tn[:, :-1])
    low[:, :-1] = np.minimum(low[:, :-1], Tn[:, 1:])
    lo = np.minimum(T - shell + 1, low + 1)
    none = np.zeros(fr.shape, dtype=bool)
    rimm = kit.ring(mask) if rim is not None else none
    rimu = kit.ring(mask, rim_w) if rim_under is not None else none
    rm = ridge_mask if (ridge is not None and ridge_mask is not None) else none
    X, Z = fr.X[mask].tolist(), fr.Z[mask].tolist()
    TT, LL = T[mask].tolist(), lo[mask].tolist()
    RI, RU, RG = rimm[mask].tolist(), rimu[mask].tolist(), rm[mask].tolist()
    s = p.set
    for x, z, t, l, ri, ru, rg in zip(X, Z, TT, LL, RI, RU, RG):
        for y in range(l, t + 1):
            s(x, y, z, tile)
        if under is not None:
            s(x, l - 1, z, under)
        if ru:
            s(x, t - 1, z, rim_under)
        if ri:
            s(x, t, z, rim)
        elif rg:
            if cap_ridge:
                s(x, t + 1, z, ridge)
            else:
                s(x, t, z, ridge)
    return T


def gable_panel(p, mask, T_face, T_low, block, border=None):
    """歇山的山花：遮罩（山花那一排格子）裡，從外側小坡的頂面 T_low+1 到
    這一排的頂面 T_face-1 換成 block（三角形的山花板），最上面一格留給 border。"""
    X, Z = p.fr.X[mask].tolist(), p.fr.Z[mask].tolist()
    A, B = T_face[mask].tolist(), T_low[mask].tolist()
    for x, z, t, lo in zip(X, Z, A, B):
        for y in range(int(lo) + 1, int(t)):
            p.set(x, y, z, block)
        if border is not None and t - lo >= 2:
            p.set(x, int(t), z, border)


# ---------------------------------------------------------------- 重簷宮殿式廳堂
#
# 國家戲劇院、國家音樂廳（楊卓成設計，1987）：平面是十字形 —— 中央主殿前後進深大、
# 兩側翼樓淺；主殿是重簷（上層廡殿或歇山、下層腰簷），翼樓是單簷；紅柱、斗拱、
# 黃色琉璃瓦、白色台基與欄杆、正面一座大階梯。公開照片量出來的比例（音樂廳正面照，
# 以面寬約 104 m 換算）：台基約 5 m、柱頭約 15 m、下簷口約 18～19 m、
# 上簷口約 25 m、正脊 37 m（OSM height=37、roof:height=12）。

class HallSpec:
    """一座重簷宮殿式廳堂的尺寸（局部座標，正面朝 -v）。

    ca, cb   中央主殿的半面寬、半進深（屋頂滴水線）
    wa, wb   翼樓外端的半長、翼樓半進深
    sw, sd   正面大階梯的半寬、深度（從主殿正面往外）
    roof     "hip"（廡殿）或 "hip_gable"（歇山）
    ridge    正脊半長（廡殿推山）或歇山的正脊半長（山花位置）
    """

    def __init__(self, ca, cb, wa, wb, sw, sd, roof, ridge,
                 plat=5, col_top=14, low_eave=18, wing_eave=17, up_eave=25, top=37):
        self.ca, self.cb, self.wa, self.wb = ca, cb, wa, wb
        self.sw, self.sd = sw, sd
        self.roof, self.ridge = roof, ridge
        self.plat, self.col_top = plat, col_top
        self.low_eave, self.wing_eave, self.up_eave, self.top = low_eave, wing_eave, up_eave, top


PALACE = dict(
    tile="minecraft:honeycomb_block",              # 黃色琉璃瓦（照片上偏橘金）
    ridge="minecraft:yellow_glazed_terracotta",    # 屋脊、脊獸
    column="minecraft:red_concrete",               # 紅柱
    wall="minecraft:white_terracotta",             # 柱後的牆（淡橘粉）
    window="minecraft:yellow_glazed_terracotta",   # 牆上的金色方窗
    door="minecraft:brown_stained_glass",          # 正門
    beam="minecraft:cyan_glazed_terracotta",       # 額枋（青綠彩畫）
    bracket="minecraft:dark_prismarine",           # 斗拱、簷下
    red="minecraft:red_terracotta",                # 簷口的紅色封簷板、上層屋身
    base="minecraft:polished_diorite",             # 台基
    floor="minecraft:smooth_stone",                # 台基面
    rail="minecraft:smooth_quartz",                # 白色欄杆
    post="minecraft:quartz_pillar",
    cap="minecraft:smooth_quartz_slab[type=bottom]",
    stair="minecraft:polished_andesite",           # 花崗石階
    stair_slab="minecraft:polished_andesite_slab",
    gable="minecraft:blue_glazed_terracotta",      # 山花板
    plaque="minecraft:lapis_block",                # 匾（磁青底）
    gold="minecraft:gold_block",
)


def palace_hall(w, fr, spec, g, mat=None):
    """在 fr（正面朝 -v）上蓋一座重簷宮殿式廳堂。g 是基地地面方塊的 y。"""
    M = dict(PALACE)
    M.update(mat or {})
    p = kit.Painter(w, fr)
    S = spec
    au, av = np.abs(fr.U), np.abs(fr.V)
    V = fr.V

    central = (au <= S.ca) & (av <= S.cb)
    wing = (au <= S.wa) & (av <= S.wb)
    stairs = (au <= S.sw + 1) & (V < -S.cb) & (V >= -S.cb - S.sd)
    plat = central | wing

    # ---- 台基：實心，外牆淡灰石、頂面石板
    y_top = g + S.plat
    p.fill(plat, g + 1, y_top - 1, M["base"])
    p.layer(plat, y_top, M["floor"])
    balustrade(p, plat, y_top + 1, M["rail"], M["post"], M["cap"],
               skip=(au <= S.sw + 1.5) & (V < -S.cb + 2))

    # ---- 正面大階梯：半階，往 +v 升到台基面
    run = S.sd
    n = 2 * S.plat
    tread = run / n
    t = (V - (-S.cb - S.sd)) / tread
    s = np.where(t >= n, float(S.plat), 0.5 * (np.floor(t) + 1))
    body = stairs & (au <= S.sw)
    steps(p, body, g, s, M["stair"], M["stair_slab"])
    cheek = stairs & (au > S.sw)
    p.fill(cheek, g + 1, g + np.ceil(s).astype(int), M["base"])
    balustrade(p, cheek | ((au > S.sw) & (au <= S.sw + 1) & (V >= -S.cb) & (V < -S.cb + 1)),
               g + np.ceil(s).astype(int) + 1, M["rail"], M["post"], M["cap"], every=2)

    # ---- 柱列：主殿滴水線內 3.5 m、翼樓內 3 m；每 6.5 m 左右一根，正中一間放寬
    y0, y1 = y_top + 1, g + S.col_top
    pts = []
    vf = S.cb - 3.5
    n_c = max(2, int(round(2 * (S.ca - 2.5) / 6.5)) + 1)
    for k in range(n_c):
        u = -(S.ca - 2.5) + 2 * (S.ca - 2.5) * k / (n_c - 1)
        if abs(u) < 5.0:                    # 正門那一間
            continue
        pts += [(u, -vf), (u, vf)]
    pts += [(-4.5, -vf), (4.5, -vf), (-4.5, vf), (4.5, vf)]
    for sgn in (-1, 1):
        # 主殿兩側（翼樓以外的那一段）
        for v in np.linspace(S.wb - 3.0 + 3.2, vf, 3):
            pts += [(sgn * (S.ca - 2.5), v), (sgn * (S.ca - 2.5), -v)]
        # 翼樓正面、背面
        for u in np.linspace(S.ca + 1.5, S.wa - 2.5, 3):
            pts += [(sgn * u, -(S.wb - 3.0)), (sgn * u, S.wb - 3.0)]
        # 翼樓外端
        n_e = max(2, int(round(2 * (S.wb - 3.0) / 6.5)) + 1)
        for k in range(n_e):
            v = -(S.wb - 3.0) + 2 * (S.wb - 3.0) * k / (n_e - 1)
            pts.append((sgn * (S.wa - 2.5), v))
    p.columns(pts, 0.8, y0, y1, M["column"])

    # ---- 柱後的牆（前廊 3.5 m）：主殿與翼樓的聯集外圈
    wall_c = (au <= S.ca - 5.0) & (av <= S.cb - 7.0)
    wall_w = (au <= S.wa - 5.0) & (av <= S.wb - 5.0)
    wm = wall_c | wall_w
    p.walls(wm, y0, y1 + 3, M["wall"])
    rg = kit.ring(wm)
    win = rg & (((fr.X + fr.Z) % 11) <= 2)
    p.fill(win, y0 + 4, y0 + 6, M["window"])
    door = rg & (au <= 4.5) & (V < 0)
    p.fill(door, y0, y0 + 7, M["door"])
    # 天花（室內頂）：牆頂那一層蓋起來，裡面是空的大廳
    p.layer(kit.erode(wm, 1), y1 + 3, M["bracket"])

    # ---- 額枋與斗拱：柱頭上一圈
    col_line = (((au <= S.ca - 2.5) & (av <= S.cb - 3.5)) |
                ((au <= S.wa - 2.5) & (av <= S.wb - 3.0)))
    cl = kit.ring(col_line)
    p.layer(cl, y1 + 1, M["beam"])
    band(p, cl, y1 + 2, y1 + 3, M["bracket"], M["beam"])

    # ---- 下層屋頂：翼樓單簷（廡殿，正脊沿 v）+ 主殿腰簷，取聯集的最高面
    e_w, e_l = g + S.wing_eave, g + S.low_eave
    a_core, b_core = S.ca - 2.0, S.cb - 7.0
    hs, ms = skirt(fr, S.ca + 4.5, S.cb, a_core, b_core, rise=(S.up_eave - 1 - S.low_eave),
                   profile=1.3, lift=1.2)
    H = np.full(fr.shape, -1e9)
    H[ms] = e_l + hs[ms]
    wing_len = (S.wa - (S.ca - 4.0)) / 2.0
    for sgn in (-1, 1):
        du = sgn * (S.ca - 4.0 + wing_len)
        uu, vv = np.abs(fr.V), np.abs(fr.U - du)            # 翼樓的長向（v）當廡殿的 u
        a_, b_ = S.wb, wing_len
        d = np.minimum(a_ - uu, b_ - vv).clip(0, None)
        hw = 5.0 * (d / min(a_, b_)).clip(0, 1) ** 1.3 + kit._lift(uu, vv, a_, b_, 1.2, None, d)
        mw = (uu <= a_) & (vv <= b_)
        H = np.where(mw, np.maximum(H, e_w + hw), H)
    low_m = (ms | wing) & ~((au < a_core) & (av < b_core))
    low_m &= H > -1e8
    roof(p, low_m, 0, H, M["tile"], shell=2, under=M["bracket"],
         rim=M["tile"], rim_under=M["red"])

    # ---- 上層屋身（兩簷之間）：紅牆 + 斗拱
    core = (au <= a_core) & (av <= b_core)
    cr = kit.ring(core)
    p.fill(cr, e_l, g + S.up_eave - 3, M["red"])
    band(p, cr, g + S.up_eave - 2, g + S.up_eave - 1, M["bracket"], M["beam"])
    # 匾：兩簷之間正中，藍底金框，壓在下簷的屋脊上
    plq = (au <= 1.6) & (V >= -b_core - 1.0) & (V < -b_core)
    for y in range(g + S.up_eave - 4, g + S.up_eave):
        edge = (y in (g + S.up_eave - 4, g + S.up_eave - 1)) | (au > 0.6)
        p.layer(plq & edge, y, M["gold"])
        p.layer(plq & ~edge, y, M["plaque"])

    # ---- 上層屋頂
    a_up, b_up = S.ca + 1.0, S.cb - 4.5
    rise = S.top - S.up_eave
    up_m = (au <= a_up) & (av <= b_up)
    if S.roof == "hip":
        hu, rm = hip_ridge(fr, a_up, b_up, rise, S.ridge, profile=1.35, lift=1.8)
        gm = None
    else:
        hu, rm, gm = hip_gable(fr, a_up, b_up, rise, a_up - S.ridge, profile=1.35, lift=1.8)
    Tu = roof(p, up_m, g + S.up_eave, hu, M["tile"], shell=2, under=M["bracket"],
              rim=M["tile"], rim_under=M["red"], ridge=M["ridge"], ridge_mask=rm & ~kit.ring(up_m))
    if gm is not None:
        # 山花：下緣是外側小坡（四鄰裡不屬於山花那一排、最低的頂面）
        lowg = _neighbor_low(Tu, gm, up_m & ~gm & (au > S.ridge))
        gable_panel(p, gm & up_m, Tu, lowg, M["gable"], border=M["ridge"])
    # 鴟吻：正脊兩端各一座（3 格高，金頂）
    for sgn in (-1, 1):
        x, z = fr.cell(sgn * S.ridge, 0.0)
        i, j = z - fr.z0, x - fr.x0
        if 0 <= i < fr.shape[0] and 0 <= j < fr.shape[1] and Tu[i, j] > -10 ** 5:
            t0 = int(Tu[i, j]) + 1
            p.set(x, t0, z, M["ridge"])
            p.set(x, t0 + 1, z, M["tile"])
            p.set(x, t0 + 2, z, M["gold"])
    return dict(platform_top=y_top, top=int(Tu[up_m].max()) if up_m.any() else None)


# ---------------------------------------------------------------- 牌樓
#
# 局部座標：u 沿牌樓面寬、v 是穿過門洞的方向。柱、門洞、屋頂的位置都用 u 表示。

BLUE_WHITE = dict(
    wall="minecraft:smooth_quartz",                # 白色大理石
    trim="minecraft:chiseled_quartz_block",        # 門洞的券面、雕花
    panel="minecraft:quartz_bricks",
    tile="minecraft:blue_concrete",                # 寶藍色琉璃瓦
    bracket="minecraft:blue_glazed_terracotta",    # 斗拱（藍白彩）
    ridge="minecraft:blue_glazed_terracotta",
    rim="minecraft:smooth_quartz",
)


class Roof:
    """牌樓的一片屋頂（歇山）：中心 du、半長 a、半深 b、簷口高 eave、升高 rise（皆為公尺）。"""

    def __init__(self, du, a, b, eave, rise):
        self.du, self.a, self.b, self.eave, self.rise = du, a, b, eave, rise


def paifang(w, fr, g, pillars, bays, roofs, pillar_w=3.5, pillar_d=5.0, wall_d=4.0,
            pedestal=None, scrolls=True, mat=None):
    """牌樓：pillars 是柱中心 [(u, 柱頂高)]；bays 是門洞 [(中心 u, 半淨寬, 起拱高, 牆頂高)]；
    roofs 是 [Roof]（由低往高蓋，高的蓋在上面）。pedestal=(半寬, 半深, 高) 是柱腳的須彌座，
    scrolls 在柱腳前後加抱鼓石。所有高度是離地公尺數（方塊 y = g + 高）。"""
    M = dict(BLUE_WHITE)
    M.update(mat or {})
    p = kit.Painter(w, fr)
    U, V = fr.U, fr.V
    av = np.abs(V)

    # 門洞上方的牆（額枋、匾）：柱與柱之間，照各間的牆頂高
    for c, half, spring, top in bays:
        m = (np.abs(U - c) <= half + 0.01) & (av <= wall_d / 2)
        p.fill(m, g + 1, g + top, M["wall"])
    # 柱
    for u, top in pillars:
        m = (np.abs(U - u) <= pillar_w / 2) & (av <= pillar_d / 2)
        p.fill(m, g + 1, g + top, M["wall"])
        if pedestal:
            ha, hb, hh = pedestal
            pm = (np.abs(U - u) <= ha) & (av <= hb)
            p.fill(pm, g + 1, g + hh, M["wall"])
            p.layer(pm & ~kit.erode(pm, 1), g + hh, M["trim"])
            if scrolls:
                # 抱鼓石：柱腳前後各一道，側面是四分之一橢圓
                dv = av - hb
                sm = (np.abs(U - u) <= 1.0) & (dv > 0) & (dv <= 4.7)
                hs = 1.5 + 3.3 * np.sqrt((1 - (dv / 4.7) ** 2).clip(0, 1))
                p.fill(sm, g + 1, g + np.rint(hs).astype(int), M["wall"])
                drum = sm & (dv <= 1.6)
                p.layer(drum, g + int(round(hh)) - 1, M["trim"])
    # 門洞：下半方、上半圓拱，整個穿透
    for c, half, spring, top in bays:
        du = U - c
        inside = np.abs(du) <= half
        for k in range(1, int(math.ceil(spring + half)) + 1):
            y = g + k
            if k <= spring:
                m = inside
                ring_m = (np.abs(du) > half) & (np.abs(du) <= half + 1.0)
            else:
                dy = k - spring
                r2 = du ** 2 + dy ** 2
                m = inside & (r2 <= half * half + 0.3)
                ring_m = (r2 > half * half + 0.3) & (r2 <= (half + 1.0) ** 2 + 0.3)
            p.layer(m & (av <= pillar_d / 2 + 0.5), y, AIR)
            # 券面：門洞外緣一圈刻花石（牆的前後兩面）
            face = ring_m & (av <= wall_d / 2) & (av > wall_d / 2 - 1.0)
            p.layer(face, y, M["trim"])
    # 斗拱與屋頂
    for rf in sorted(roofs, key=lambda r: r.eave):
        bm = (np.abs(U - rf.du) <= rf.a - 0.8) & (av <= rf.b - 1.2)
        band(p, bm, g + rf.eave - 2, g + rf.eave - 1, M["bracket"], M["wall"])
        h, rm, gm = hip_gable(fr, rf.a, rf.b, rf.rise, rf.a * 0.3, profile=1.4, lift=0.9, du=rf.du)
        mask = (np.abs(U - rf.du) <= rf.a) & (av <= rf.b)
        T = roof(p, mask, g + rf.eave, h, M["tile"], shell=2, under=M["bracket"],
                 rim=M["rim"], rim_under=M["bracket"], ridge=M["ridge"],
                 ridge_mask=rm & ~kit.ring(mask))
        lowg = _neighbor_low(T, gm & mask, mask & ~gm & (np.abs(U - rf.du) > rf.a * 0.7))
        gable_panel(p, gm & mask, T, lowg, M["bracket"], border=M["rim"])
        # 正脊兩端的吻獸
        for sgn in (-1, 1):
            x, z = fr.cell(rf.du + sgn * rf.a * 0.7, 0.0)
            i, j = z - fr.z0, x - fr.x0
            if 0 <= i < fr.shape[0] and 0 <= j < fr.shape[1] and T[i, j] > -10 ** 5:
                p.set(x, int(T[i, j]) + 2, z, M["ridge"])


def _neighbor_low(T, target, source):
    """target 遮罩每格：四鄰裡屬於 source 的格子的最低頂面（沒有就用自己的頂面 - 1）。"""
    big = 10 ** 6
    S = np.where(source, T, big)
    low = np.full(T.shape, big, dtype=np.int64)
    low[1:, :] = np.minimum(low[1:, :], S[:-1, :])
    low[:-1, :] = np.minimum(low[:-1, :], S[1:, :])
    low[:, 1:] = np.minimum(low[:, 1:], S[:, :-1])
    low[:, :-1] = np.minimum(low[:, :-1], S[:, 1:])
    return np.where(target & (low < big), low, T - 1)
