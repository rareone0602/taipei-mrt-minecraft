#!/usr/bin/env python3
"""鐵軌生成器的單元測試：shape、斜軌、動力軌、退化輸入。

用法: ./.venv/bin/python tests/test_rails.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mrt.domain.rails import *  # noqa: F403

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
