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
import os, sys, json, math
import numpy as np

from mrt import config
from mrt.domain import alignment as BL

CELL_M   = 30      # 空間雜湊格邊長（公尺）；連同 8 個鄰格 = 至少 30 m 的水平淨距
BAND0    = 15      # 第 0 帶的埋深（公尺）
BAND_DY  = 15      # 帶距。站體斷面 dy -2..10 共 13 格，15 m 才咬不到
LOOK_M   = 1500    # 換帶時往前看多遠，挑撐得最久的帶
MAXBAND  = 8


def band_depth(band):
    """帶號 -> 隧道偏移量（負值，公尺）"""
    return -(BAND0 + BAND_DY * np.maximum(np.asarray(band), 0))


def assign_bands(raw, cell=CELL_M, look_m=LOOK_M, pins=()):
    """raw: [(ref, samples), ...]，samples 是 BL.resample 的輸出。

    回傳與 raw 等長的 list，每個元素是該段的 per-sample 帶號 int 陣列
    （非地下段為 -1）。長的先指派，短的讓路。

    pins 是 [(x, z, 半徑, ref, band)]，用來釘死已知的真實上下關係。
    貪婪演算法只知道「不能撞在一起」，不知道現實中誰在上面 —— 例如台北車站
    的板南線在 B3、淡水信義線在 B4，演算法卻可能給出相反的結果。
    釘樁會先把該範圍內的帶預留給指定路線，其他線只能繞開。
    """
    look = int(look_m / BL.STEP)
    occ = {}                       # cell -> {band: ref}

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
                for b, r in occ.get((ck[0] + dx, ck[1] + dz), {}).items():
                    if r != ref:
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
        cur = None
        for i in range(n):
            s = samples[i]
            ck = cks[i]
            if ck is None:                      # 出洞了，下次進洞重新挑
                cur = None
                continue
            t = taken_at(ck, ref)
            forced = None
            for px, pz, r2, pb in pin_by_ref.get(ref, ()):
                if (s[0] - px) ** 2 + (s[1] - pz) ** 2 <= r2:
                    forced = pb
                    break
            if forced is not None:
                cur = forced
            elif cur is None or cur in t:
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
            arr[i] = cur
            occ.setdefault(ck, {})[cur] = ref
        out[idx] = arr
    return out


# ---------- 以下只是分析報告 ----------

def station_pins(min_margin=15.0, ratio=2.0, radius=120.0, verbose=False):
    """從 OSM 月台的 level 標籤推出真實的上下關係，轉成釘樁。

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
    lines = json.load(open(config.MC_LINES_JSON))
    raw = []
    for ref in sorted(lines):
        for v in BL.select_variants(lines[ref]):
            pts = [tuple(p) for p in v["points"]]
            kinds = v.get("kinds") or ["ground"] * len(pts)
            pts, kinds = BL.drop_reversal(pts, kinds)
            samples = BL.resample(pts, kinds, BL.STEP)
            if len(samples) >= 10:
                raw.append((ref, samples))
    return raw


def main():
    raw = _plan_raw()
    nu = sum(int((np.array([s[4] for s in sm]) == "tunnel").sum()) for _, sm in raw)
    print(f"{len(raw)} 個路段，地下取樣點 {nu:,} 個（{nu*BL.STEP/1000:.1f} km）")

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
        print(f"  {ref:<3} 地下 {len(u)*BL.STEP/1000:>5.1f} km   {share}")
    print("\n全網:")
    for k, c in enumerate(tot):
        if c:
            print(f"  帶{k}（地下 {BAND0+BAND_DY*k:>2} m）{c*BL.STEP/1000:>7.1f} km"
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
