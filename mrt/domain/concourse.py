#!/usr/bin/env python3
"""地下人行動線：把 OSM 的室內通道折線整理成「可以照著蓋」的計畫。

這一層全是純函式，不碰存檔也不寫方塊。輸入是投影好的折線與出入口座標，
輸出是通道中心線、出入口接駁段與垂直連接點。

三件在資料裡踩到、必須在這裡處理掉的事：

1. **OSM 的 level 不是絕對樓層。** 台北地下街標 level=-2、站前地下街標
   level=-2 但 layer=-1、中山地下街標 level=-1 —— 三者實際上都是 B1，
   彼此走過去只要兩百公尺。level 是各測繪聚落自己的基準，跨聚落比較沒有意義。
   所以這裡不拿 level 當高程，只拿它判斷「這條線在不在地下」。

2. **端點沒接起來。** 台北車站一帶有 199 個懸空端點，其中 71 個離另一個
   節點不到 5 m —— 那是測繪時沒接上，不是真的斷開。不先併點的話，
   8.8 km 的連通網會碎成 60 塊。

3. **出入口不一定落在通道上。** 台北地下街是五條中心線，沿線的 Y9~Y20、
   Y22~Y28 全部離線 9~42 m，因為橫向的聯絡通道沒有畫。這些要自己補一段。

自我測試: ./.venv/bin/python tests/test_concourse.py
"""
import math
import re

# 數字：可有負號、可有小數點
_NUM = r"-?\d+(?:\.\d+)?"
_RANGE = re.compile(r"^(%s)-(%s)$" % (_NUM, _NUM))
_LEAD = re.compile(r"^(%s)" % _NUM)


def parse_level(value):
    """OSM 的 level 標籤 -> (最低樓層, 最高樓層)；解析不出來回 None。

    實際遇到的寫法（台北車站一帶全部出現過）：
      "-1"          單一樓層
      "-1;0"        分號清單，順序不保證排序（"0;-0.5;-1" 也有）
      "-2--1"       範圍。減號同時當負號與分隔號，兩端各錨一次才切得對
      "-2--0"       -0 要正規化成 0
      "-1:0;1;2..." 冒號是分號打錯（中山某座百貨電梯）
      "5A"          樓層代號帶字母後綴，取前面的數字

    樓梯與電梯要用 (最低, 最高) 當作「它連通的兩端」—— 120 條樓梯裡只有
    6 條標了 step_count，級數是問不到的，只能從樓層差反推。
    """
    if not value:
        return None
    s = str(value).strip().replace(":", ";").replace("；", ";").replace(",", ";")
    levels = []
    for tok in s.split(";"):
        tok = tok.strip()
        if not tok:
            continue
        m = _RANGE.match(tok)
        if m:
            levels += [float(m.group(1)), float(m.group(2))]
            continue
        m = _LEAD.match(tok)
        if m:
            levels.append(float(m.group(1)))
    if not levels:
        return None
    return min(levels) + 0.0, max(levels) + 0.0        # +0.0 把 -0.0 收成 0.0


def underground(tags):
    """這條 way 算不算地下人行動線。

    用 level 判斷，不用 indoor=yes —— 忠孝新生站旁有一所大學把校舍室內圖
    畫得很完整，92 條 corridor、1.2 km，level 全是 0~14。照 indoor 收的話
    會在捷運站上面蓋出一棟十四層的學校。
    """
    lv = parse_level(tags.get("level"))
    if lv is not None:
        lo, hi = lv
        return lo < 0 and hi <= 0        # 通到 1 樓以上的（百貨電扶梯）不要
    # 沒有 level 但標了隧道：馬路底下的人行地下道，也算
    return tags.get("tunnel") in ("yes", "building_passage")


# ---------- 併點與連通 ----------

class _Union:
    def __init__(self):
        self.p = {}

    def find(self, a):
        self.p.setdefault(a, a)
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def join(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def merge_nodes(coords, tol=3.0):
    """把相距 tol 公尺以內的節點併成一個。回傳 {原節點: 代表節點}。

    tol 給 3 m：實測 2~3 m 能收掉大部分沒接上的端點，5 m 全收但會開始把
    真的隔著一道牆的兩條通道黏在一起。
    """
    u = _Union()
    grid = {}
    cell = max(tol, 1.0)
    for nid, (x, z) in coords.items():
        u.find(nid)
        grid.setdefault((int(math.floor(x / cell)), int(math.floor(z / cell))),
                        []).append(nid)
    t2 = tol * tol
    for (cx, cz), ids in grid.items():
        near = []
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                near += grid.get((cx + dx, cz + dz), ())
        for a in ids:
            ax, az = coords[a]
            for b in near:
                if a >= b:
                    continue
                bx, bz = coords[b]
                if (ax - bx) ** 2 + (az - bz) ** 2 <= t2:
                    u.join(a, b)
    return {nid: u.find(nid) for nid in coords}


def build_graph(ways, tol=3.0):
    """ways: [{"nodes": [id...], "points": [[x, z], ...]}, ...]

    回傳 (pos, adj, edges)：
      pos   {代表節點: (x, z)}          併點後的座標（同群取平均）
      adj   {代表節點: {鄰居, ...}}
      edges [(a, b, way索引)]           去掉自環與重複
    """
    coords = {}
    for w in ways:
        for nid, p in zip(w["nodes"], w["points"]):
            coords[nid] = (float(p[0]), float(p[1]))
    rep = merge_nodes(coords, tol)

    acc = {}
    for nid, (x, z) in coords.items():
        r = rep[nid]
        sx, sz, n = acc.get(r, (0.0, 0.0, 0))
        acc[r] = (sx + x, sz + z, n + 1)
    pos = {r: (sx / n, sz / n) for r, (sx, sz, n) in acc.items()}

    adj, edges, seen = {}, [], set()
    for wi, w in enumerate(ways):
        ids = [rep[n] for n in w["nodes"]]
        for a, b in zip(ids, ids[1:]):
            if a == b:
                continue
            key = (a, b) if a < b else (b, a)
            adj.setdefault(a, set()).add(b)
            adj.setdefault(b, set()).add(a)
            if key in seen:
                continue
            seen.add(key)
            edges.append((a, b, wi))
    return pos, adj, edges


def components(pos, adj):
    """連通分量，大的在前。回傳 [set(節點), ...]"""
    seen, out = set(), []
    for start in pos:
        if start in seen:
            continue
        stack, group = [start], set()
        seen.add(start)
        while stack:
            n = stack.pop()
            group.add(n)
            for m in adj.get(n, ()):
                if m not in seen:
                    seen.add(m)
                    stack.append(m)
        out.append(group)
    out.sort(key=len, reverse=True)
    return out


def main_component(pos, adj, near=(0.0, 0.0), radius=400.0):
    """挑出要蓋的那一座車站的通道網路。

    不能只挑「離 near 最近的分量」—— 台北車站正上方就有一條兩個節點的
    孤立通道，那樣會選到它，然後只蓋出 17 公尺的地下街。
    正確的問法是「近處的分量裡最大的那個」。
    """
    comps = components(pos, adj)
    if not comps:
        return set()
    hit = [g for g in comps
           if min(math.dist(pos[n], near) for n in g) <= radius]
    return max(hit, key=len) if hit else comps[0]


def bridge_gaps(pos, adj, edges, max_gap=25.0):
    """把離得很近卻沒接起來的分量接上，回傳補的邊 [(a, b)]。

    OSM 台北車站一帶有 199 個懸空端點；merge_nodes 收掉 3 m 以內的，
    剩下的是真的隔了一段沒畫 —— 例如北門機捷連通道整條是孤立的，
    但它的東端就在台北地下街西段旁邊二十幾公尺。這種缺口補起來是還原
    現實（走得過去），不補的話地下街會少掉一整條分支。

    只補到「目前最大的那一團」，而且一次補一條、補完重算，
    免得把兩團互相都不該接的東西串成一條。
    """
    added = []
    comps = components(pos, adj)
    if not comps:
        return added
    main = set(comps[0])
    rest = [set(g) for g in comps[1:]]
    while rest:
        best = None
        for gi, g in enumerate(rest):
            for a in g:
                ax, az = pos[a]
                for b in main:
                    bx, bz = pos[b]
                    d = math.hypot(ax - bx, az - bz)
                    if best is None or d < best[0]:
                        best = (d, gi, a, b)
        if best is None or best[0] > max_gap:
            break
        _, gi, a, b = best
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
        edges.append((a, b, -1))
        added.append((a, b))
        main |= rest.pop(gi)
    return added


# ---------- 出入口接駁 ----------

def snap_entrances(pos, group, entrances, radius=60.0):
    """把出入口接到最近的通道節點上。

    回傳 (connected, orphan)：
      connected [(ref, ex, ez, 節點, 距離)]   distance 0 表示出入口本身就是節點
      orphan    [(ref, ex, ez)]               radius 內找不到通道的

    radius 給 60 m：實測 30 m 接得到六成、50 m 八成。再放寬就會把隔壁站的
    出入口接到不相干的通道上。
    """
    cand = [(n, pos[n]) for n in group]
    connected, orphan = [], []
    for ref, ex, ez in entrances:
        best, bd = None, None
        for n, (x, z) in cand:
            d = math.hypot(x - ex, z - ez)
            if bd is None or d < bd:
                best, bd = n, d
        if best is not None and bd <= radius:
            connected.append((ref, ex, ez, best, bd))
        else:
            orphan.append((ref, ex, ez))
    return connected, orphan


def corridor_lines(pos, edges, group):
    """要蓋的通道中心線段：[((x0, z0), (x1, z1)), ...]，只留在 group 裡的。"""
    out = []
    for a, b, _ in edges:
        if a in group and b in group:
            out.append((pos[a], pos[b]))
    return out


def degree(adj, group):
    """節點分歧度，用來決定哪裡要放指標牌（三岔以上才值得立牌）。"""
    return {n: len(adj.get(n, ())) for n in group}


def total_length(lines):
    return sum(math.dist(a, b) for a, b in lines)


def outward(pos, adj, node, ex, ez):
    """出入口樓梯該往哪個方向爬（四個正交方向之一）：背對通道。

    出入口常常「就是」通道的端點節點 —— 台北車站的 M1、M3、M8、Y7、Z2
    都是這樣，出入口減節點是零向量，方向無從決定。隨便挑一個的話樓梯會
    沿著通道往回爬，把自己要接上的那條通道整段覆寫掉，蓋出一個誰也走不到的
    死胡同（實測這五個出入口各自成為一個連通分量）。

    正解是看鄰居：通道從哪個方向過來，樓梯就往反方向爬。
    出入口離節點夠遠時（有補接駁段）則直接沿接駁段的方向繼續往外。
    """
    nx, nz = pos[node]
    vx, vz = ex - nx, ez - nz
    if math.hypot(vx, vz) < 2.0:
        nbrs = [pos[m] for m in adj.get(node, ())]
        if nbrs:
            ax = sum(p[0] for p in nbrs) / len(nbrs)
            az = sum(p[1] for p in nbrs) / len(nbrs)
            vx, vz = nx - ax, nz - az
    if abs(vx) < 1e-6 and abs(vz) < 1e-6:
        vx = 1.0
    if abs(vx) >= abs(vz):
        return (1 if vx > 0 else -1), 0
    return 0, (1 if vz > 0 else -1)
