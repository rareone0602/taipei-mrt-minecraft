#!/usr/bin/env python3
"""隧道分層：決定每一段地下線要走在哪個深度帶。

原本的做法是每條線一個固定深度（build_world.TUNNEL_DEPTH 常數）。
兩個問題：

  1. 判斷「要不要分帶」時看的是兩條線目前的垂直間距 —— 可是垂直間距正是
     分帶自己造成的，循環論證。BL-O 與 A-G 就是這樣被漏掉，實際疊在一起，
     後蓋的線把先蓋的鐵軌覆寫掉，驗軌報「對面沒接回來」。
  2. 就算改成只看水平距離，BL / G / O / R 四條線在市中心兩兩都會交會
     （K4 完全圖），每線一個固定深度就需要四層，最深那條要挖到地下 60 m。
     北捷實際最深約 30 m。

真實的捷運不是整條線挑一個深度，而是**平常走淺層，只在真的要穿越別條線的
地方才潛下去**。所以這裡改成逐取樣點指派：沿線掃過去，只有在目前的深度帶被
別條線占用時才換帶，並且用前瞻挑一個「可以撐最久」的帶，免得一直上上下下。

縱斷面的 4% 坡度限制會自動把換帶處拉成一段斜坡，不需要另外處理。

用法（分析報告）: ./.venv/bin/python -m mrt.domain.tunnel_layers
"""
import os, json, math
import numpy as np

from mrt import config
from mrt.domain import alignment as AL

CELL_M   = 30      # 空間雜湊格邊長（公尺）；連同 8 個鄰格 = 至少 30 m 的水平淨距
BAND0    = 15      # 第 0 帶的埋深（公尺）
BAND_DY  = 15      # 帶距。站體斷面 dy -2..10 共 13 格，15 m 才咬不到
LOOK_M   = 1500    # 換帶時往前看多遠，挑撐得最久的帶
MAXBAND  = 8
RAMP_M   = BAND_DY / AL.MAX_GRADE   # 換一帶要走的斜坡長度：15 m / 4% = 375 m
PRE_EVERY = 20     # 每幾個取樣點往前探一次要不要提前換帶（10 m 一次就夠）


def band_depth(band):
    """帶號 -> 隧道偏移量（負值，公尺）"""
    return -(BAND0 + BAND_DY * np.maximum(np.asarray(band), 0))


def assign_bands(raw, cell=CELL_M, look_m=LOOK_M, pins=(), shared=()):
    """raw: [(ref, samples), ...]，samples 是 AL.resample 的輸出。

    回傳與 raw 等長的 list，每個元素是該段的 per-sample 帶號 int 陣列
    （非地下段為 -1）。長的先指派，短的讓路。

    pins 是 [(x, z, 半徑, ref, band)]，用來釘死已知的真實上下關係。
    貪婪演算法只知道「不能撞在一起」，不知道現實中誰在上面 —— 例如台北車站
    的板南線在 B3、淡水信義線在 B4，演算法卻可能給出相反的結果。
    釘樁會先把該範圍內的帶預留給指定路線，其他線只能繞開。

    **換帶要提前一段斜坡的距離。** 帶號只是目標深度，真正的高程由縱斷面的
    4% 坡度包絡線決定，換一帶要走 375 m 的斜坡。原本走到「目前的帶被占用」
    那一格才換，斜坡從衝突點才開始下潛，衝突點本身還在半路上 ——
    松江南京的松山新店線就這樣停在地下 27 m，與地下 30 m 的中和新蘆線站體
    上下只差 3 m，兩座箱涵直接交疊。所以往前探一段斜坡：目前的帶在前方
    375 m 內會被占用，就現在換；換掉的舊帶在斜坡走完之前也繼續算占用，
    免得別條線鑽進斜坡底下。

    shared 是 [(x, z, 半徑, {ref, ...})]：共用一座站體的幾條線（西門的板南線與
    松山新店線）在那一帶本來就疊在同一帶裡，彼此不算占用。少了這一條，
    松山新店線的釘樁會把板南線嚇跑：板南線往前探到「帶 0 在西門被 G 占了」，
    就在台北車站與西門之間潛到帶 2，再被自己的釘樁拉回帶 0 —— 縱斷面因此把
    西門與台北車站都拖低 13 m，台北車站的板南線直接撞進淡水信義線的站體。
    """
    look = int(look_m / AL.STEP)
    ramp = int(RAMP_M / AL.STEP)
    occ = {}                       # cell -> {band: ref}

    ally = {}                      # cell -> 在這一格彼此不算占用的路線
    for sx, sz, sr, refs in shared:
        c0 = int(math.floor((sx - sr) / cell)); c1 = int(math.floor((sx + sr) / cell))
        d0 = int(math.floor((sz - sr) / cell)); d1 = int(math.floor((sz + sr) / cell))
        for cx in range(c0, c1 + 1):
            for cz in range(d0, d1 + 1):
                ally.setdefault((cx, cz), set()).update(refs)

    pin_by_ref = {}
    for px, pz, pr, pref, pb in pins:
        pin_by_ref.setdefault(pref, []).append((px, pz, pr * pr, pb))
        c0 = int(math.floor((px - pr) / cell)); c1 = int(math.floor((px + pr) / cell))
        d0 = int(math.floor((pz - pr) / cell)); d1 = int(math.floor((pz + pr) / cell))
        for cx in range(c0, c1 + 1):
            for cz in range(d0, d1 + 1):
                occ.setdefault((cx, cz), {})[pb] = pref
    order = sorted(range(len(raw)), key=lambda i: -len(raw[i][1]))
    out = [None] * len(raw)

    def taken_at(ck, ref):
        t = set()
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                c = (ck[0] + dx, ck[1] + dz)
                al = ally.get(c)
                for b, r in occ.get(c, {}).items():
                    if r != ref and not (al is not None and ref in al and r in al):
                        t.add(b)
        return t

    for idx in order:
        ref, samples = raw[idx]
        n = len(samples)
        arr = np.full(n, -1, dtype=np.int8)
        cks = [None] * n
        for i, s in enumerate(samples):
            if s[4] == "tunnel":
                cks[i] = (int(math.floor(s[0] / cell)), int(math.floor(s[1] / cell)))
        def taken_within(i0, band, span):
            """band 在 i0..i0+span 之間有沒有被別條線占用（每 20 點看一次）"""
            for j in range(i0, min(n, i0 + span + 1), PRE_EVERY):
                if cks[j] is not None and band in taken_at(cks[j], ref):
                    return True
            return False

        cur = None
        hold = {}                               # 舊帶 -> 斜坡走完的取樣索引
        for i in range(n):
            s = samples[i]
            ck = cks[i]
            if ck is None:                      # 出洞了，下次進洞重新挑
                cur = None
                hold = {}
                continue
            t = taken_at(ck, ref)
            forced = None
            for px, pz, r2, pb in pin_by_ref.get(ref, ()):
                if (s[0] - px) ** 2 + (s[1] - pz) ** 2 <= r2:
                    forced = pb
                    break
            prev = cur
            if forced is not None:
                cur = forced
            elif cur is None or cur in t or (
                    i % PRE_EVERY == 0 and taken_within(i, cur, ramp)):
                # 前瞻：每個候選帶能撐到哪裡，挑最遠的（平手取最淺）
                best, best_d = 0, -1
                for b in range(MAXBAND):
                    if b in t:
                        continue
                    d = look
                    for j in range(i, min(n, i + look)):
                        if cks[j] is not None and b in taken_at(cks[j], ref):
                            d = j - i
                            break
                    if d > best_d:
                        best, best_d = b, d
                    if d >= look:
                        break
                cur = best
            if prev is not None and prev != cur:
                hold[prev] = i + ramp * abs(cur - prev)
            arr[i] = cur
            occ.setdefault(ck, {})[cur] = ref
            for b in list(hold):                # 斜坡還沒走完，舊帶也占著
                if i <= hold[b]:
                    occ.setdefault(ck, {})[b] = ref
                else:
                    del hold[b]
        out[idx] = arr
    return out


def check_clearance(segs, shared=(), cell=16, every=4, shared_r=300.0):
    """實際幾何的跨線淨距檢查：任兩條不同路線的地下結構不准在空間裡交疊。

    帶號的驗算只知道「帶號不同」；疊式站的雙層箱涵比一帶還高、釘平的縱斷面
    又可能離開帶的深度，所以另外拿每一點真正的箱涵範圍（半寬與上下緣）算一次。
    segs 是 cli 規劃完的路段（samples / ys / ground / stn / hw，可有 frames /
    stacked / y_side）。shared 是 [(x, z, ref_a, ref_b)]：共用一座站體的兩條線
    在 shared_r 內本來就疊在一起，不算衝突。

    回傳 [(ref_a, ref_b, x, z, ya0, ya1, yb0, yb1), ...]，每個格子每對路線最多一筆。
    """
    from mrt.domain.stacked import BOX_BOTTOM_DY
    half = int(AL.PLATFORM_LEN / 2 / AL.STEP)
    grid = {}
    for sg in segs:
        samples, ys, gnd = sg["samples"], sg["ys"], sg["ground"]
        hws = sg.get("hw")
        frames, stk, yside = sg.get("frames", {}), sg.get("stacked", {}), sg.get("y_side")
        nob = sg.get("nobuild", set())
        n = len(samples)
        rng = [(max(0, bi - half), min(n - 1, bi + half), bi) for bi in sg.get("stn", ())]
        for i in range(0, n, every):
            y, g = int(ys[i]), int(gnd[i])
            if AL.structure_for_ground(y, g) != "tunnel" or i in nob:
                continue
            bi = next((b for lo, hi, b in rng if lo <= i <= hi), None)
            if bi is not None:
                x, z = frames.get(bi, samples)[i][:2]
                r = AL.BOX_HALF + 1
                y0 = y + (BOX_BOTTOM_DY if bi in stk else -2)
                y1 = y + AL.BOX_TOP_DY
            else:
                x, z = samples[i][0], samples[i][1]
                r = (int(hws[i]) if hws is not None else 5) + 2
                ylo = y if yside is None else min(y, int(yside[1][i]), int(yside[-1][i]))
                y0, y1 = ylo - 2, y + 7
            grid.setdefault((int(x // cell), int(z // cell)), []).append(
                (sg["ref"], x, z, r, y0, y1))

    def exempt(ra, rb, x, z):
        return any({ra, rb} == {a, b} and math.hypot(x - sx, z - sz) <= shared_r
                   for sx, sz, a, b in shared)

    bad, seen = [], set()
    for (cx, cz), pts in grid.items():
        near = []
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                near += grid.get((cx + dx, cz + dz), ())
        for ra, xa, za, rra, a0, a1 in pts:
            for rb, xb, zb, rrb, b0, b1 in near:
                if rb <= ra or (ra, rb, cx, cz) in seen:
                    continue
                # 上下緣都是襯砌那一排；兩座箱涵共用一排襯砌不算交疊（西門北側
                # 板南線與松山新店線的箱涵就是這樣貼著過）
                if math.hypot(xa - xb, za - zb) < rra + rrb and a0 < b1 and b0 < a1 \
                        and not exempt(ra, rb, xa, za):
                    seen.add((ra, rb, cx, cz))
                    bad.append((ra, rb, xa, za, a0, a1, b0, b1))
    return bad


# ---------- 以下只是分析報告 ----------

PIN_RADIUS = AL.PLATFORM_LEN / 2 + RAMP_M     # 35 + 375 = 410 m


def station_pins(min_margin=15.0, ratio=2.0, radius=PIN_RADIUS, verbose=False):
    """從 OSM 月台的 level 標籤推出真實的上下關係，轉成釘樁。

    釘樁半徑要涵蓋半個站體再加一段斜坡：帶號一離開釘樁範圍就可以換，
    換帶的斜坡有 375 m，半徑只給 120 m 的話斜坡會伸進站體，把釘在 B2 的
    站體拉到地下 21 m（中山站的淡水信義線實測正是如此）。

    只處理「同一座車站有兩條以上路線、而且 level 不同」的轉乘站 ——
    那正是貪婪演算法可能猜反、而現實有明確答案的地方。月台屬於哪條線
    要用幾何判斷（OSM 的 station_ref 只給車站代碼，不給月台屬於哪線），
    判不準的就跳過，不硬猜。
    """
    import re, collections
    pf = config.PLATFORM_LEVELS_JSON
    if not os.path.exists(pf):
        return []
    items = json.load(open(pf, encoding="utf-8"))["items"]
    lines = json.load(open(config.MC_LINES_JSON,
                           encoding="utf-8"))

    def dist_to(ref, cx, cz):
        best = 1e18
        for v in lines.get(ref, []):
            p = v["points"]
            for i in range(len(p) - 1):
                ax, az = p[i]; bx, bz = p[i + 1]
                vx, vz = bx - ax, bz - az
                L = vx * vx + vz * vz
                t = 0.0 if L == 0 else max(0, min(1, ((cx-ax)*vx + (cz-az)*vz) / L))
                best = min(best, math.hypot(cx - (ax + t*vx), cz - (az + t*vz)))
        return best

    byst = collections.defaultdict(dict)
    for p in items:
        try:
            lv = int(str(p.get("level")).split(";")[0])
        except (TypeError, ValueError):
            continue
        if lv >= 0 or not p.get("station_ref") or not p.get("station"):
            continue
        cands = sorted({m.group(0) for t in
                        str(p["station_ref"]).replace(",", ";").split(";")
                        for m in [re.match(r"[A-Z]+", t.strip())] if m})
        cands = [c for c in cands if c in lines]
        if len(cands) < 2:
            continue
        cx, cz = p["mc_x"], p["mc_z"]
        ds = sorted((dist_to(c, cx, cz), c) for c in cands)
        if ds[0][0] > min_margin or ds[1][0] < ratio * max(ds[0][0], 1.0):
            continue                       # 判不準，跳過
        st = p["station"]
        prev = byst[st].get(ds[0][1])
        if prev is None or lv < prev[0]:
            byst[st][ds[0][1]] = (lv, cx, cz)

    pins = []
    for st, d in sorted(byst.items()):
        if len(d) < 2 or len({v[0] for v in d.values()}) < 2:
            continue                       # 只有一條線、或深度相同，不必釘
        order = sorted(d.items(), key=lambda kv: -kv[1][0])   # level 大的在上
        for band, (ref, (lv, cx, cz)) in enumerate(order):
            pins.append((cx, cz, radius, ref, band))
            if verbose:
                print(f"  釘樁 {st:<8} {ref:<3} level {lv} -> 帶{band}  ({cx},{cz})")
    return pins


def _plan_raw():
    lines = json.load(open(config.MC_LINES_JSON, encoding="utf-8"))
    raw = []
    for ref in sorted(lines):
        for v in AL.select_variants(lines[ref]):
            pts = [tuple(p) for p in v["points"]]
            kinds = v.get("kinds") or ["ground"] * len(pts)
            pts, kinds = AL.drop_reversal(pts, kinds)
            samples = AL.resample(pts, kinds, AL.STEP)
            if len(samples) >= 10:
                raw.append((ref, samples))
    return raw


def main():
    raw = _plan_raw()
    nu = sum(int((np.array([s[4] for s in sm]) == "tunnel").sum()) for _, sm in raw)
    print(f"{len(raw)} 個路段，地下取樣點 {nu:,} 個（{nu*AL.STEP/1000:.1f} km）")

    pins = station_pins(verbose=True)
    print(f"釘樁 {len(pins)} 根")
    bands = assign_bands(raw, pins=pins)

    per_ref = {}
    for (ref, _), b in zip(raw, bands):
        u = b[b >= 0]
        if not len(u):
            continue
        e = per_ref.setdefault(ref, [])
        e.append(u)
    print(f"\n每條線的深度帶分布（帶 k 的埋深 = {BAND0} + {BAND_DY}k m）：")
    tot = np.zeros(MAXBAND, dtype=np.int64)
    for ref in sorted(per_ref):
        u = np.concatenate(per_ref[ref])
        cnt = np.bincount(u, minlength=MAXBAND)
        tot += cnt
        share = " ".join(f"帶{k} {100*c/len(u):>4.0f}%" for k, c in enumerate(cnt) if c)
        print(f"  {ref:<3} 地下 {len(u)*AL.STEP/1000:>5.1f} km   {share}")
    print("\n全網:")
    for k, c in enumerate(tot):
        if c:
            print(f"  帶{k}（地下 {BAND0+BAND_DY*k:>2} m）{c*AL.STEP/1000:>7.1f} km"
                  f"  {100*c/tot.sum():>5.1f}%")
    deepest = int(np.nonzero(tot)[0].max())
    print(f"最深 {BAND0+BAND_DY*deepest} m（北捷實際最深約 30 m）")

    # 驗算：任兩條不同線的地下點，若水平 <30 m 則垂直必須 >= 15 m
    print("\n驗算同格衝突 …")
    occ = {}
    bad = 0
    for (ref, sm), b in zip(raw, bands):
        for i, s in enumerate(sm):
            if b[i] < 0:
                continue
            ck = (int(math.floor(s[0]/CELL_M)), int(math.floor(s[1]/CELL_M)))
            occ.setdefault(ck, {}).setdefault(int(b[i]), set()).add(ref)
    for ck, bb in occ.items():
        for band, refs in bb.items():
            for dx in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    o = occ.get((ck[0]+dx, ck[1]+dz), {}).get(band, set())
                    if o - refs:
                        bad += 1
    print(f"  同帶又相鄰的異線格數：{bad}" + ("  ← 仍有衝突" if bad else "  （無衝突）"))


if __name__ == "__main__":
    main()
