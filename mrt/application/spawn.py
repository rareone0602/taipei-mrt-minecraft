#!/usr/bin/env python3
"""世界出生點：站在台北車站捷運出入口亭的門外，面向門口。

原本出生點是 (0, 地面+2, 0) —— 台北車站捷運站的站點座標，正下方就是地下街、
連絡梯與兩座站體，是全世界挖得最空的一柱。玩家曾經生在 (0.5, -63, 0.5)。

**怎麼挑（照順序，結果是決定性的）**

1. 只看台北車站捷運出口 M1～M8 的出入口亭（地下街 Stair 的 headhouse，
   OSM 的 subway_entrance 編號；K、Y、Z、R 開頭的是地下街自己的出口）。
2. 門外那一格要「直接站在街上」：地形表面剛好是亭的樓板高度（門檻與街面
   齊平，不必跳也不會掉），而且高於海平面（腳下不是水）。
3. 門外那一格不能落在任何地面上的地標範圍裡（站體大樓、別座出入口亭、
   樓梯井、空橋）—— 那一柱頭頂要是開放的天空。出生點的邏輯是查區塊的
   MOTION_BLOCKING 高度圖取柱頂，頭上有屋頂就會被放到屋頂上。
4. 剩下的取離台北車站捷運站點（板南線與淡水信義線轉乘的那個站點）最近的；
   一樣近就比出口編號。

面向：站在門外一格、面朝 -u（梯段延伸方向的反向），正對三格寬的門洞，
一抬頭就看得到亭內「出口 Exit」的牌子。

這裡只用規劃（landmarks.for_world 回傳的地標物件）與地形式子，不讀存檔；
蓋出來對不對由 tools/verify_spawn.py 從磁碟讀回來驗。
"""
import math

from mrt.application.build_concourse import Stair
from mrt.application.landmarks import Passage, RailHall, Slab
from mrt.domain.terrain import SEA_Y

STATION = "台北車站"
EXIT_PREFIX = "M"          # 台北車站捷運出口的編號是 M1～M8


def _refs(stair):
    lab = stair.label
    if lab is None:
        return []
    return [str(r) for r in (lab if isinstance(lab, (list, tuple)) else [lab])]


def _above_ground(o):
    """這個地標會不會蓋東西到地面以上（會的話它的範圍內頭頂不是天空）。

    地下街的物件一律標了 underground，但出入口亭（有 headhouse 的 Stair）
    是例外：梯子在地下、亭子在街上。B1 大廳（Slab）、臺鐵月台層（RailHall）、
    地下通道（Passage）沒有標，它們整個在地表以下。
    """
    if isinstance(o, Stair):
        return bool(o.headhouse)
    if isinstance(o, (Slab, RailHall, Passage)):
        return False
    return not getattr(o, "underground", False)     # Tile：地下街是地下的，空橋不是


def station_node(stations, name=STATION):
    """某站最主要的站點座標：同名的站點裡線別最多的那一個（台北車站是
    R10;BL12 的轉乘站點，不是機場線 A1）。"""
    rows = [r for r in stations if r[1] == name]
    if not rows:
        return None
    best = max(rows, key=lambda r: (len([t for t in r[0] if t]), -abs(r[2]) - abs(r[3])))
    return best[2], best[3]


def candidates(marks, ground_at, prefix=EXIT_PREFIX):
    """所有符合 2、3 條件的出入口亭門口：[(refs, x, y, z, (fx, fz), 亭)]。"""
    blockers = [o for o in marks if _above_ground(o)]
    out = []
    for m in marks:
        if not isinstance(m, Stair) or not m.headhouse:
            continue
        refs = _refs(m)
        if not any(r.startswith(prefix) and r[len(prefix):].isdigit() for r in refs):
            continue
        x, z, y, face = m.door_front()
        g = int(ground_at(x, z))
        if g != y - 1 or g <= SEA_Y:
            continue
        hit = False
        for o in blockers:
            if o is m:
                continue
            x0, z0, x1, z1 = o.bbox()
            if x0 <= x <= x1 and z0 <= z <= z1:
                hit = True
                break
        if not hit:
            out.append((refs, x, y, z, face, m))
    return out


def plan_spawn(marks, stations, ground_at):
    """挑出生點。回傳 dict(x, y, z, facing=(fx, fz), refs, why)，挑不到回 None。

    y 是腳站的那一格（level.dat 的 spawn.pos 就是這一格，遊戲會把玩家放在
    格子底面中央）。ground_at(x, z) 必須是「實際蓋出來的地形表面」——
    cli 傳 application.build_world.surface_y 包起來的版本。
    """
    node = station_node(stations)
    if node is None:
        return None
    cs = candidates(marks, ground_at)
    if not cs:
        return None
    nx, nz = node

    def key(c):
        refs, x, y, z, face, m = c
        num = min(int(r[len(EXIT_PREFIX):]) for r in refs
                  if r.startswith(EXIT_PREFIX) and r[len(EXIT_PREFIX):].isdigit())
        return (math.hypot(x - nx, z - nz), num)

    refs, x, y, z, face, m = min(cs, key=key)
    return dict(x=int(x), y=int(y), z=int(z), facing=face, refs=refs,
                why=f"{STATION}捷運出口 {'/'.join(refs)} 的出入口亭門外，"
                    f"離捷運站點 {math.hypot(x - nx, z - nz):.0f} m，"
                    f"符合條件的 {len(cs)} 座裡最近的")
