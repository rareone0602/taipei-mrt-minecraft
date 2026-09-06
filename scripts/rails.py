#!/usr/bin/env python3
"""單線軌道生成器：把浮點中心線轉成 Minecraft 的鐵軌方塊與 shape 狀態。

存檔是直接寫 NBT、沒有方塊更新，遊戲不會幫忙把鐵軌接起來 —— 每一格的 shape
都得自己算對。算錯的那一格不會報錯，只會讓礦車默默停在那裡。

用法（跑自我測試）:
    ./.venv/bin/python scripts/rails.py
"""
import math
import sys

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


# ---------- 自我測試 ----------

def _sample(f, length, step=0.5):
    """沿參數 s ∈ [0, length] 每 step 取一點，f(s) -> (x, y, z)"""
    n = int(round(length / step))
    return [f(i * step) for i in range(n + 1)]


_FAILS = []


def _fail(name, msg):
    _FAILS.append("%s: %s" % (name, msg))


def _expect(name, cond, msg):
    if not cond:
        _fail(name, msg)


def _case(name, pts, booster_every=12):
    """跑一個案例：生成、過通用檢查器、印一行摘要。"""
    try:
        blocks = rail_path(pts, booster_every)
    except Exception as e:                      # noqa: BLE001
        _fail(name, "rail_path 例外: %r" % (e,))
        print("[FAIL] %-14s %r" % (name, e))
        return []
    for e in check_rails(blocks):
        _fail(name, e)
    if blocks:
        ys = [b[1] for b in blocks]
        kinds = {"straight": 0, "curve": 0, "ascend": 0}
        for _, _, _, s, _p in blocks:
            kinds["curve" if s in CURVE_SHAPES else
                  "ascend" if s in ASCEND_SHAPES else "straight"] += 1
        pw = sum(1 for b in blocks if b[4])
        print("[%s] %-14s %5d 格  y %d..%d  直%d 彎%d 坡%d  動力軌 %d"
              % ("ok" if not any(f.startswith(name + ":") for f in _FAILS) else "!!",
                 name, len(blocks), min(ys), max(ys),
                 kinds["straight"], kinds["curve"], kinds["ascend"], pw))
    else:
        print("[ok] %-14s     0 格" % name)
    return blocks


def _selftest():
    # 1. 純東西向
    b = _case("east_west", _sample(lambda s: (s, 64.0, 0.0), 200))
    _expect("east_west", len(b) == 201, "應該是 201 格，實際 %d" % len(b))
    _expect("east_west", all(x[3] == "east_west" for x in b), "shape 不全是 east_west")
    _expect("east_west", all(x[1] == 64 for x in b), "高度不該變")

    # 2. 純南北向
    b = _case("north_south", _sample(lambda s: (0.0, 64.0, s), 200))
    _expect("north_south", all(x[3] == "north_south" for x in b),
            "shape 不全是 north_south")
    _expect("north_south", [x[2] for x in b] == list(range(201)), "z 應該連續遞增")

    # 3. 45° 對角線 —— 每個對角步都得拆成兩個正交步
    k = 1.0 / math.sqrt(2.0)
    b = _case("diagonal", _sample(lambda s: (s * k, 64.0, s * k), 200))
    _expect("diagonal", all(x[3] in CURVE_SHAPES for x in b[1:-1]),
            "45° 階梯的中間格應該全是彎道")
    dev = max(abs((x[0] - x[2])) for x in b)
    _expect("diagonal", dev <= 1, "偏離中心線太遠（%d 格）" % dev)

    # 4. 半徑 200 m 的四分之一圓弧
    R = 200.0
    b = _case("arc", _sample(lambda s: (R * math.sin(s / R), 64.0,
                                        R - R * math.cos(s / R)), R * math.pi / 2))
    for x, _y, z, _s, _p in b:
        _expect("arc", abs(math.hypot(x, R - z) - R) <= 1.0,
                "格子 (%d,%d) 偏離圓弧超過 1 m" % (x, z))
    _expect("arc", any(x[3] in CURVE_SHAPES for x in b), "圓弧上竟然沒有彎道")

    # 5. 4% 爬坡，共升 10 m
    b = _case("ramp4pct", _sample(lambda s: (s, 64.0 + 0.04 * s, 0.0), 250))
    _expect("ramp4pct", b[0][1] == 64 and b[-1][1] == 74,
            "起訖高度應為 64→74，實際 %d→%d" % (b[0][1], b[-1][1]))
    asc = [i for i, x in enumerate(b) if x[3] in ASCEND_SHAPES]
    _expect("ramp4pct", len(asc) == 10, "應該有 10 段斜軌，實際 %d" % len(asc))
    _expect("ramp4pct", all(asc[i + 1] - asc[i] >= 2 for i in range(len(asc) - 1)),
            "斜軌不該相鄰")

    # 6. S 形曲線
    b = _case("s_curve", _sample(lambda s: (s, 64.0, 60.0 * math.sin(s / 60.0)), 300))
    _expect("s_curve", any(x[3] == "north_east" or x[3] == "south_west"
                           for x in b), "S 形應該兩種轉向都有")

    # 7. 高差自然落在彎道上：直行 30 m 後轉 90°，y 剛好在轉角處跨過半格
    def _corner(s):
        y = 64.49 + 0.02 * (s - 30.0)
        return (s, y, 0.0) if s <= 30.0 else (30.0, y, s - 30.0)
    b = _case("ramp_corner", _sample(_corner, 60))
    corner = [i for i, x in enumerate(b) if x[3] in CURVE_SHAPES]
    _expect("ramp_corner", corner == [30], "應該只有第 30 格是彎道，實際 %s" % corner)
    _expect("ramp_corner", b[29][3] == "ascending_east",
            "高差應該往回挪到第 29 格，實際 %s" % b[29][3])
    _expect("ramp_corner", b[30][1] == b[29][1] + 1 == 65,
            "轉角應該座落在斜坡頂端 y=65")
    _expect("ramp_corner", b[-1][1] == 65, "終點高度應為 65")

    # 8. 極短路徑
    b = _case("two_pts", [(0.0, 64.0, 0.0), (1.0, 64.0, 0.0)])
    _expect("two_pts", [x[:3] for x in b] == [(0, 64, 0), (1, 64, 0)], "格子不對")
    _expect("two_pts", all(x[3] == "east_west" for x in b), "shape 不對")

    b = _case("three_pts", [(0.0, 64.0, 0.0), (1.0, 64.0, 0.0), (1.0, 64.0, 1.0)])
    _expect("three_pts", [x[3] for x in b] == ["east_west", "south_west",
                                               "north_south"], "轉角 shape 不對")

    b = _case("one_pt", [(3.2, 64.0, -7.8)])
    _expect("one_pt", b == [(3, 64, -8, "north_south", True)], "單格輸出不對: %r" % b)
    _expect("empty", rail_path([]) == [], "空輸入應該回空清單")

    # 9. 防禦：輸入坡度過陡時仍必須夾在每步 1 格內
    b = _case("steep", _sample(lambda s: (s, 64.0 + 0.5 * s, 0.0), 40))
    _expect("steep", all(abs(b[i + 1][1] - b[i][1]) <= 1 for i in range(len(b) - 1)),
            "每步高差必須 <= 1")

    # 10. 動力軌間距與 block_string
    b = _case("booster", _sample(lambda s: (s, 64.0, 0.0), 300), booster_every=8)
    idx = [i for i, x in enumerate(b) if x[4]]
    _expect("booster", idx[0] == 0, "起點就該有一根動力軌")
    _expect("booster", all(idx[i + 1] - idx[i] == 8 for i in range(len(idx) - 1)),
            "直線上的動力軌間距應該剛好 8")
    b = _case("no_booster", _sample(lambda s: (s, 64.0, 0.0), 20), booster_every=0)
    _expect("no_booster", not any(x[4] for x in b), "booster_every=0 不該有動力軌")

    _expect("block_string",
            block_string("north_south", False) == "minecraft:rail[shape=north_south]",
            "一般鐵軌字串不對")
    _expect("block_string",
            block_string("east_west", True)
            == "minecraft:powered_rail[shape=east_west,powered=true]",
            "動力軌字串不對")
    _expect("block_string",
            block_string("ascending_north", True)
            == "minecraft:powered_rail[shape=ascending_north,powered=true]",
            "斜向動力軌字串不對")
    for bad in ("south_east", "north_west"):
        try:
            block_string(bad, True)
            _fail("block_string", "彎道 %s 竟然可以是動力軌" % bad)
        except ValueError:
            pass

    # 11. 檢查器本身要抓得到壞軌道，否則上面全過也不代表什麼
    bad_cases = {
        "不連通":   [(0, 64, 0, "east_west", False), (2, 64, 0, "east_west", False)],
        "接不上":   [(0, 64, 0, "north_south", False), (1, 64, 0, "east_west", False)],
        "懸空高差": [(0, 64, 0, "east_west", False), (1, 65, 0, "east_west", False)],
        "彎道通電": [(0, 64, 0, "south_east", True), (1, 64, 0, "east_west", False)],
        "山峰":     [(0, 64, 0, "ascending_east", False), (1, 65, 0, "east_west", False),
                     (2, 64, 0, "ascending_west", False)],
        "山谷":     [(0, 65, 0, "east_west", False), (1, 64, 0, "ascending_east", False),
                     (2, 65, 0, "east_west", False)],
        "連續斜軌": [(0, 64, 0, "ascending_east", False), (1, 65, 0, "ascending_east", False),
                     (2, 66, 0, "east_west", False)],
    }
    for label, blocks in bad_cases.items():
        _expect("checker", check_rails(blocks), "檢查器沒抓到「%s」" % label)


if __name__ == "__main__":
    _selftest()
    print()
    if _FAILS:
        print("FAILED (%d)" % len(_FAILS))
        for f in _FAILS:
            print("  -", f)
        sys.exit(1)
    print("all tests passed")
