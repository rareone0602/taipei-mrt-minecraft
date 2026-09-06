#!/usr/bin/env python3
"""行人可達性：把蓋好的世界當成一張圖，用玩家真的走得動的規則洪水填滿。

地下街「每個出入口都連得到」這件事沒辦法用生成器自己的紀錄證明 ——
生成器只知道自己放了哪些方塊，不知道那些方塊拼起來走不走得通。少一階樓梯、
通道被別條線的隧道襯砌切斷、頂板壓到只剩一格淨空，這些在生成紀錄裡通通是
「已完成」。所以驗證只能反過來做：從方塊本身重建可走的空間。

方塊來源用注入的：tools/verify_concourse.py 餵的是從 Anvil 存檔讀回來的方塊，
tests/test_concourse.py 餵的是 DictSink 裡的方塊。規則只有這一份，兩邊共用。

移動規則刻意做成對稱的（上下各一格），可達性因此是無向的，可以直接談
「連通分量」。真實的 Minecraft 可以往下摔任意高度，那是單向的 —— 用它來
驗連通會把「跳得下去、爬不上來」的斷頭通道判成通過。

自我測試: ./.venv/bin/python -m tests.test_walk
"""
import collections

# 不擋路、也撐不住人的方塊：站在它們那一格要靠下面那格。
_PASSABLE_EXACT = {
    "minecraft:air", "minecraft:cave_air", "minecraft:void_air",
    "minecraft:water", "minecraft:light", "minecraft:structure_void",
}
_PASSABLE_SUFFIX = (
    "_rail", "_sign", "_torch", "_button", "_banner",
)
_PASSABLE_CONTAINS = ("rail", "sign", "torch", "pressure_plate", "carpet")


def base_name(block):
    """去掉方塊狀態：'minecraft:oak_sign[rotation=4]' -> 'minecraft:oak_sign'"""
    return block.split("[", 1)[0]


def is_bottom_slab(block):
    """下半磚：占半格，人站在這一格裡，頭頂那格仍然是空的。

    專案的樓梯是「整塊、下半磚」交替鋪的（build_line._stair_run、
    landmarks.ShaftStair），每公尺升降 0.5 m。少了這一條，整段樓梯會被
    當成一半實心一半懸空，走起來每兩格斷一次。
    nbtlib 寫出去的字串沒帶 type= 時預設就是 bottom。
    """
    name = base_name(block)
    if not name.endswith("_slab"):
        return False
    st = block[len(name):]
    return "type=top" not in st and "type=double" not in st


def is_passable(block):
    """人可以穿過去、但踩不住的方塊。"""
    name = base_name(block)
    if name in _PASSABLE_EXACT:
        return True
    if name.endswith(_PASSABLE_SUFFIX):
        return True
    return any(k in name for k in _PASSABLE_CONTAINS)


def is_support(block):
    """能踩在上面的方塊（實心，或本身就是下半磚）。"""
    return not is_passable(block) and not is_bottom_slab(block)


def standable(get, x, y, z, head=2):
    """(x, y, z) 能不能站人 —— 這一格是「腳」所在的格。

    要件：腳這一格與其上 head-1 格通得過；腳底下是實心，或腳這一格
    本身是下半磚（半磚把人墊高半格，等於自己當自己的地板）。
    """
    foot = get(x, y, z)
    slab = is_bottom_slab(foot)
    if not slab and not is_passable(foot):
        return False
    for dy in range(1, head):
        if not is_passable(get(x, y + dy, z)):
            return False
    return slab or is_support(get(x, y - 1, z))


NEIGHBOURS = ((1, 0), (-1, 0), (0, 1), (0, -1))


def flood(get, starts, bounds=None, head=2, limit=4_000_000):
    """從 starts 洪水填滿走得到的腳格。

    get(x, y, z) 回傳方塊名稱字串。bounds 是 (x0, y0, z0, x1, y1, z1) 含端點，
    用來把搜尋圈在關心的範圍內 —— 少了它，一條通到地面的樓梯會讓洪水漫過
    整張地圖。

    回傳 (dist, came)：dist 是 {腳格: 步數}，came 是 {腳格: 上一格}，
    後者用來把路徑倒推出來給人看。
    """
    if bounds is not None:
        x0, y0, z0, x1, y1, z1 = bounds

        def inside(x, y, z):
            return x0 <= x <= x1 and y0 <= y <= y1 and z0 <= z <= z1
    else:
        def inside(x, y, z):
            return True

    dist, came = {}, {}
    q = collections.deque()
    for c in starts:
        c = (int(c[0]), int(c[1]), int(c[2]))
        if c not in dist and inside(*c) and standable(get, *c, head=head):
            dist[c] = 0
            q.append(c)

    while q:
        x, y, z = q.popleft()
        if len(dist) >= limit:
            break
        d = dist[(x, y, z)] + 1
        for dx, dz in NEIGHBOURS:
            nx, nz = x + dx, z + dz
            for ny in (y + 1, y, y - 1):        # 上下各一格，對稱
                n = (nx, ny, nz)
                if n in dist or not inside(*n):
                    continue
                if standable(get, nx, ny, nz, head=head):
                    dist[n] = d
                    came[n] = (x, y, z)
                    q.append(n)
                    break                        # 同一柱只取最接近的一格
    return dist, came


def nearest_standable(get, x, y, z, radius=6, head=2, dy=8):
    """在 (x, y, z) 附近找一格站得住的地方。

    出入口的座標是 OSM 的節點位置，不保證正好落在樓梯的踏面上；
    驗證要從「那附近」開始走，而不是要求生成器把地板剛好放在那個點。
    回傳最近的腳格，找不到回 None。
    """
    best = None
    for ddy in range(-dy, dy + 1):
        for ddx in range(-radius, radius + 1):
            for ddz in range(-radius, radius + 1):
                c = (x + ddx, y + ddy, z + ddz)
                if not standable(get, *c, head=head):
                    continue
                w = ddx * ddx + ddz * ddz + 4 * ddy * ddy
                if best is None or w < best[0]:
                    best = (w, c)
    return best[1] if best else None


def path(came, cell):
    """把 flood() 的 came 倒推成一條路徑（起點在前）。"""
    out = [cell]
    while cell in came:
        cell = came[cell]
        out.append(cell)
    out.reverse()
    return out


def components(get, cells, bounds=None, head=2):
    """把一批腳格分成連通分量。回傳 [[cell, ...], ...]，大的在前。

    「所有出入口互相連得到」等價於「只有一個分量」，分不開的時候這個
    分組直接告訴你是哪幾個出入口被關在一起。
    """
    todo = [c for c in cells]
    seen, out = set(), []
    for c in todo:
        if c in seen:
            continue
        dist, _ = flood(get, [c], bounds=bounds, head=head)
        group = [d for d in todo if d in dist]
        seen.update(group)
        if group:
            out.append(group)
    out.sort(key=len, reverse=True)
    return out
