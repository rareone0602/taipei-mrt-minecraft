#!/usr/bin/env python3
"""單線軌道生成器：把浮點中心線轉成 Minecraft 的鐵軌方塊與 shape 狀態。

存檔是直接寫 NBT、沒有方塊更新，遊戲不會幫忙把鐵軌接起來 —— 每一格的 shape
都得自己算對。算錯的那一格不會報錯，只會讓礦車默默停在那裡。

用法（跑自我測試）:
    ./.venv/bin/python -m mrt.domain.rails
"""
import math

RAIL    = "minecraft:rail"
POWERED = "minecraft:powered_rail"

# 北 = −Z、南 = +Z、東 = +X、西 = −X
DIRS     = {"north": (0, -1), "south": (0, 1), "east": (1, 0), "west": (-1, 0)}
_DIR_OF  = {v: k for k, v in DIRS.items()}
OPPOSITE = {"north": "south", "south": "north", "east": "west", "west": "east"}
AXIS     = {"north": "north_south", "south": "north_south",
            "east":  "east_west",   "west":  "east_west"}

STRAIGHT_SHAPES = {"north_south", "east_west"}
CURVE_SHAPES    = {"north_east", "north_west", "south_east", "south_west"}
ASCEND_SHAPES   = {"ascending_" + d for d in DIRS}
ALL_SHAPES      = STRAIGHT_SHAPES | CURVE_SHAPES | ASCEND_SHAPES
# powered_rail 的 shape 列舉裡沒有彎道，硬塞會變成無效方塊狀態
POWERED_SHAPES  = STRAIGHT_SHAPES | ASCEND_SHAPES


# ---------- 對外 API ----------

def rail_path(pts, booster_every=12):
    """pts: iterable of (x, y, z) floats, ordered along the track.
    Returns list of (x:int, y:int, z:int, shape:str, powered:bool)."""
    pts = [(float(x), float(y), float(z)) for x, y, z in pts]
    if not pts:
        return []
    cells = _quantize(pts)          # 取整、併掉同一格的連續取樣
    cells = _orthogonalize(cells)   # 對角步拆成兩個正交步
    cells = _despike(cells)         # 拿掉 a-b-a 的折返尖點
    ys     = _plan_profile(cells)   # 縱斷面：夾坡度、把高差挪離彎道
    shapes = _shapes(cells, ys)
    power  = _boosters(shapes, booster_every)
    return [(c[0], ys[i], c[1], shapes[i], power[i]) for i, c in enumerate(cells)]


def block_string(shape, powered):
    """-> 'minecraft:rail[shape=north_south]' or
          'minecraft:powered_rail[shape=east_west,powered=true]'"""
    if shape not in ALL_SHAPES:
        raise ValueError("未知的 rail shape: %r" % (shape,))
    if powered:
        if shape not in POWERED_SHAPES:
            raise ValueError("powered_rail 不能是彎道: %r" % (shape,))
        return "%s[shape=%s,powered=true]" % (POWERED, shape)
    return "%s[shape=%s]" % (RAIL, shape)


def shape_connections(shape):
    """回傳 (這個 shape 接出去的兩個方向, 上坡方向或 None)。"""
    if shape in STRAIGHT_SHAPES:
        return (("north", "south") if shape == "north_south"
                else ("east", "west")), None
    if shape in ASCEND_SHAPES:
        d = shape[len("ascending_"):]
        return (d, OPPOSITE[d]), d
    if shape in CURVE_SHAPES:
        ns, ew = shape.split("_")
        return (ns, ew), None
    raise ValueError("未知的 rail shape: %r" % (shape,))


# ---------- 平面線形 ----------

def _r(v):
    """半數往上取整。內建 round() 是 banker's rounding —— round(0.5)=0 但
    round(1.5)=2，用在 0.5 m 取樣上會讓方塊的長度忽長忽短。"""
    return int(math.floor(v + 0.5))


def _quantize(pts):
    """取整成方塊格，並把落在同一格的連續取樣併成一點。

    0.5 m 取樣時同一格常出現兩三個點；高度取群組平均而不是第一個，
    緩坡的縱斷面才不會整條往格子的前緣偏半格。
    """
    out = []
    for x, y, z in pts:
        xi, zi = _r(x), _r(z)
        if out and out[-1][0] == xi and out[-1][1] == zi:
            c = out[-1]
            c[3] += 1
            c[2] += (y - c[2]) / c[3]
        else:
            out.append([xi, zi, y, 1])
    return [(c[0], c[1], c[2]) for c in out]


def _ortho_walk(a, b, state):
    """從 a 走到 b 只走上下左右，回傳沿途格子（不含 a、含 b）。

    每一步挑離 a→b 直線比較近的那個軸；兩邊一樣近時（正 45°）改走上一步
    沒走的軸 —— 對角線因此走成規律階梯，而不是先直行一長段再急轉。
    """
    ax, az = a
    bx, bz = b
    dx, dz = bx - ax, bz - az
    span = math.hypot(dx, dz)
    x, z, out = ax, az, []
    while (x, z) != (bx, bz):
        cands = []
        if x != bx:
            cands.append(("x", (x + (1 if bx > x else -1), z)))
        if z != bz:
            cands.append(("z", (x, z + (1 if bz > z else -1))))
        if len(cands) == 1:
            axis, nxt = cands[0]
        else:
            dev = [abs(dz * (c[1][0] - ax) - dx * (c[1][1] - az)) / span
                   for c in cands]
            if abs(dev[0] - dev[1]) < 1e-9:
                axis, nxt = cands[1] if state[0] == "x" else cands[0]
            else:
                axis, nxt = cands[0] if dev[0] < dev[1] else cands[1]
        state[0] = axis
        out.append(nxt)
        x, z = nxt
    return out


def _orthogonalize(cells):
    """把相鄰格補成 4-連通。鐵軌沒有斜向接點，對角步一定要拆成兩步。"""
    out = [cells[0]]
    state = [None]
    for bx, bz, by in cells[1:]:
        ax, az, ay = out[-1]
        steps = _ortho_walk((ax, az), (bx, bz), state)
        for k, (x, z) in enumerate(steps, 1):
            # 插進去的中間點沒有原始高度，沿曼哈頓進度線性內插
            out.append((x, z, ay + (by - ay) * k / len(steps)))
    return out


def _despike(cells):
    """拿掉 a-b-a 的折返：同一格出現兩個朝同方向的鄰居，shape 無解。"""
    out = []
    for c in cells:
        if out and (out[-1][0], out[-1][1]) == (c[0], c[1]):
            continue
        if len(out) >= 2 and (out[-2][0], out[-2][1]) == (c[0], c[1]):
            out.pop()
            continue
        out.append(c)
    return out


def _straight_flags(cells):
    """每一格是不是直線段（兩個鄰居在正相反方向）。端點視為直線 —— 只有
    一個鄰居，一定能挑到直線或斜軌的 shape。"""
    n = len(cells)
    flags = [True] * n
    for i in range(1, n - 1):
        px, pz = cells[i - 1][0] - cells[i][0], cells[i - 1][1] - cells[i][1]
        nx, nz = cells[i + 1][0] - cells[i][0], cells[i + 1][1] - cells[i][1]
        flags[i] = (px == -nx and pz == -nz)
    return flags


# ---------- 縱斷面 ----------

def _limit_grade(ys):
    """把每步高差夾在 ±1：斜軌一次只能升一格，輸入再陡也不能照抄。"""
    out = list(ys)
    for i in range(1, len(out)):
        out[i] = max(out[i - 1] - 1, min(out[i - 1] + 1, out[i]))
    return out


def _nearest_ok(ok, idx, lo):
    """找離 idx 最近、且 >= lo 的合法邊；同距離時偏好往回挪（比較不落後）。"""
    n = len(ok)
    for r in range(n):
        for j in ((idx,) if r == 0 else (idx - r, idx + r)):
            if lo <= j < n and ok[j]:
                return j
        if idx - r < lo and idx + r >= n:
            break
    return None


def _plan_profile(cells):
    """規劃每一格的 y。

    高差只能落在「低的那一格是直線段」的邊上：斜軌不能同時是彎道，
    而上坡的斜軌永遠是低的那一格。另外相鄰兩條邊不准都有高差 ——
    這樣每個斜軌的另一端必定同高，也順便消掉山谷與山峰。
    真實坡度 4% 時兩次升降相距 25 格以上，這個限制不會綁到手。
    """
    n = len(cells)
    tgt = _limit_grade([_r(c[2]) for c in cells])
    if n < 2:
        return tgt
    straight = _straight_flags(cells)
    up_ok   = [straight[i]     for i in range(n - 1)]   # 升：斜軌是第 i 格
    down_ok = [straight[i + 1] for i in range(n - 1)]   # 降：斜軌是第 i+1 格

    placed, last = [], -2
    for i in range(n - 1):
        d = tgt[i + 1] - tgt[i]
        if d == 0:
            continue
        j = _nearest_ok(up_ok if d > 0 else down_ok, i, last + 2)
        if j is None:
            continue        # 整段都在彎道上，只能放棄這次高差（軌道仍然可通行）
        placed.append((j, d))
        last = j

    ys, cur, k = [0] * n, tgt[0], 0
    for i in range(n):
        if k < len(placed) and placed[k][0] == i - 1:
            cur += placed[k][1]
            k += 1
        ys[i] = cur
    return ys


# ---------- shape 與動力軌 ----------

def _shapes(cells, ys):
    n = len(cells)
    out = []
    for i in range(n):
        nbs = []
        for j in (i - 1, i + 1):
            if 0 <= j < n:
                d = _DIR_OF[(cells[j][0] - cells[i][0], cells[j][1] - cells[i][1])]
                nbs.append((d, ys[j]))
        if not nbs:
            out.append("north_south")   # 只有一格的軌道，軸向隨便挑
            continue
        is_straight = len(nbs) == 1 or nbs[0][0] == OPPOSITE[nbs[1][0]]
        up = [d for d, y in nbs if y == ys[i] + 1]
        if up:
            # 這兩種情形代表 _plan_profile 沒擋住，寧可炸掉也不要生出走不了的軌道
            if not is_straight:
                raise ValueError("#%d 斜軌落在彎道上" % i)
            if len(up) > 1:
                raise ValueError("#%d 兩側都比自己高（山谷）" % i)
            out.append("ascending_" + up[0])
        elif is_straight:
            out.append(AXIS[nbs[0][0]])
        else:
            ns = nbs[0][0] if nbs[0][0] in ("north", "south") else nbs[1][0]
            ew = nbs[0][0] if nbs[0][0] in ("east", "west")   else nbs[1][0]
            out.append(ns + "_" + ew)
    return out


def _boosters(shapes, every):
    """每隔 every 格放一根動力軌；落在彎道就順延到下一格直線。

    整條網路 240 km，礦車不補速就會在半路停住，所以寧可多放。
    """
    out = [False] * len(shapes)
    if not every or every <= 0:
        return out
    since = every       # 第一格就先給一根，礦車才推得動
    for i, s in enumerate(shapes):
        if since >= every and s in POWERED_SHAPES:
            out[i] = True
            since = 0
        since += 1
    return out


# ---------- 通用檢查器 ----------

def check_rails(blocks):
    """礦車可通行性檢查。回傳錯誤訊息清單，空清單代表這條軌道走得過去。"""
    errs = []
    n = len(blocks)
    if n == 0:
        return errs

    seen = {}
    for i, (x, y, z, shape, pw) in enumerate(blocks):
        if shape not in ALL_SHAPES:
            errs.append("#%d 未知的 shape %r" % (i, shape))
        if pw and shape in CURVE_SHAPES:
            errs.append("#%d 彎道 %s 不能是 powered_rail" % (i, shape))
        if (x, z) in seen:
            errs.append("#%d 與 #%d 佔用同一格 (%d,%d)" % (i, seen[(x, z)], x, z))
        seen[(x, z)] = i

    for i in range(n - 1):
        ax, _, az = blocks[i][:3]
        bx, _, bz = blocks[i + 1][:3]
        if abs(ax - bx) + abs(az - bz) != 1:
            errs.append("#%d (%d,%d) -> #%d (%d,%d) 不是正交相鄰"
                        % (i, ax, az, i + 1, bx, bz))
    if errs:
        return errs     # 連通性都壞了，接下來的 shape 檢查沒有意義

    for i, (x, y, z, shape, pw) in enumerate(blocks):
        dirs, asc = shape_connections(shape)
        nbs = []
        for j in (i - 1, i + 1):
            if 0 <= j < n:
                nbs.append((j, _DIR_OF[(blocks[j][0] - x, blocks[j][2] - z)]))

        for j, d in nbs:
            ny = blocks[j][1]
            back = OPPOSITE[d]
            jdirs, jasc = shape_connections(blocks[j][3])
            if d not in dirs:
                errs.append("#%d %s 沒有朝 %s 的接點（鄰居 #%d）" % (i, shape, d, j))
            if back not in jdirs:
                errs.append("#%d %s 沒有接回 %s（鄰居 #%d）"
                            % (j, blocks[j][3], back, i))
            if asc == d:
                if ny != y + 1:
                    errs.append("#%d %s 的 %s 側鄰居應該高 1 格，實際 %+d"
                                % (i, shape, d, ny - y))
            elif jasc == back:
                # 斜坡頂端：鄰居低 1 格但它正朝我上坡。規格書寫「非斜軌的兩側
                # 都同高」，照字面走的話任何高度變化都不成立 —— 這格必須放行。
                if ny != y - 1:
                    errs.append("#%d 的鄰居 #%d 宣稱朝我上坡，卻不是低 1 格" % (i, j))
            elif ny != y:
                errs.append("#%d 與 #%d 高差 %+d，但兩邊都不是斜軌"
                            % (i, j, ny - y))

        if asc:
            ndirs = [d for _, d in nbs]
            if asc not in ndirs:
                errs.append("#%d %s 朝 %s 上坡，那個方向卻沒有軌道" % (i, shape, asc))
            if len(nbs) == 2 and nbs[0][1] != OPPOSITE[nbs[1][1]]:
                errs.append("#%d 斜軌不能同時是彎道" % i)
            for j, d in nbs:
                if d != asc and blocks[j][1] != y:
                    errs.append("#%d %s 的另一端鄰居 #%d 必須同高" % (i, shape, j))

        if len(nbs) == 2:
            y0, y1 = blocks[nbs[0][0]][1], blocks[nbs[1][0]][1]
            if y < y0 and y < y1:
                errs.append("#%d 比兩側都低（山谷）" % i)
            if y > y0 and y > y1:
                errs.append("#%d 比兩側都高（山峰）" % i)
    return errs
