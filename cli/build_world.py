#!/usr/bin/env python3
"""串流式世界生成器：真實地形 + 全路網結構（組合根）。

整片地形放不進記憶體，所以按 region (512x512 方塊) 分批：把取樣點依 region
分桶，逐 region 生地形、蓋結構、寫檔、釋放。

這一層是唯一看得到全部實作的地方 —— 決定要把方塊寫進哪個 World、
從哪裡讀資料。真正的規則在 mrt/domain，蓋東西的程式在 mrt/application。

用法:
    ./.venv/bin/python -m cli.build_world [--corridor 160] [--lines BR ...]
    ./.venv/bin/python -m cli.build_world --rails      # 順便鋪鐵軌
"""
import argparse
import csv
import json
import math
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from mrt import config
from mrt.application import build_line as BL
from mrt.application import build_world as BW
from mrt.application import landmarks as LM
from mrt.domain import rails
from mrt.domain import tunnel_layers as TL
from mrt.domain.terrain import SEA_Y, Terrain
from mrt.infrastructure.mcworld import Chunk, World

# main() 沿用原本的模組層常數
BLEND_CELL = BW.BLEND_CELL
FLAT_Y = BW.FLAT_Y
STEP = BW.STEP
OFFSET = BW.OFFSET
blend_field = BW.blend_field
moving_avg = BW.moving_avg
profile = BW.profile
terrain_chunk = BW.terrain_chunk


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=config.DEFAULT_SAVE)
    ap.add_argument("--corridor", type=int, default=96, help="完整地形的半寬（公尺）")
    ap.add_argument("--fade", type=int, default=64, help="再往外漸變回平坦的寬度")
    ap.add_argument("--lines", nargs="*", default=None)
    ap.add_argument("--rails", action="store_true",
                    help="順便鋪鐵軌。預設不鋪 —— 走行面留白，方便用模組自己鋪")
    a = ap.parse_args()
    outer = a.corridor + a.fade

    terr = Terrain()
    lines = json.load(open(config.MC_LINES_JSON))
    refs = a.lines or sorted(lines)

    stations = []
    with open(config.MC_STATIONS_CSV) as f:
        for r in csv.DictReader(f):
            stations.append((r["ref"].split(";"), r["name_zh"] or r["name_en"],
                             int(r["mc_x"]), int(r["mc_z"]), r["name_en"], r["ref"]))

    # ---- 規劃：所有線的取樣點、縱斷面、車站對應 ----
    # 先把所有線的平面取樣做完，才能決定深度帶：某條線要不要潛下去，
    # 取決於別條線在哪裡，一條一條各自算是看不出來的。
    raw = []
    for ref in refs:
        if ref not in lines:
            continue
        for v in BL.select_variants(lines[ref]):
            pts = [tuple(p) for p in v["points"]]
            kinds = v.get("kinds") or ["ground"] * len(pts)
            pts, kinds = BL.drop_reversal(pts, kinds)
            samples = BL.resample(pts, kinds, STEP)
            if len(samples) >= 10:
                raw.append((ref, samples))

    pins = TL.station_pins()
    bands = TL.assign_bands(raw, pins=pins)
    if pins:
        print(f"隧道深度釘樁 {len(pins)} 根（依 OSM 月台 level 還原真實上下關係）")
    nb = np.bincount(np.concatenate([b[b >= 0] for b in bands]) if bands else [0],
                     minlength=1)
    print("隧道深度帶：" + "  ".join(
        f"地下{TL.BAND0 + TL.BAND_DY * k} m {c * STEP / 1000:.1f} km"
        for k, c in enumerate(nb) if c))

    segs = []
    for (ref, samples), band in zip(raw, bands):
            ys, ground = profile(samples, terr, ref, band)
            stn = {}
            for _, name, sx, sz, en, full in stations:
                if not any(t.startswith(ref) and len(t) > len(ref) and t[len(ref)].isdigit()
                           for t in _):
                    continue
                d = [(x - sx) ** 2 + (z - sz) ** 2 for x, z, _, _, _ in samples]
                bi = int(np.argmin(d))
                if math.sqrt(d[bi]) <= 200:
                    stn[bi] = (full, name, en)
            segs.append(dict(ref=ref, samples=samples, ys=ys, ground=ground,
                             stn=stn, band=band))

    # 同一座車站可能同時落在幹線與支線上（如北投、七張），中和新蘆線的共用
    # 幹線更是整段重複。兩處若差了十幾公尺，會疊出兩座歪掉的站體。
    #
    # 鍵一定要帶上 ref：忠孝復興這種轉乘站在 BL 和 BR 上各有一座真實站體，
    # 只用站名去重會把整批轉乘站砍掉（實測 182 -> 159 座）。
    claimed = set()
    dropped = 0
    for sg in segs:
        for bi in sorted(sg["stn"]):
            key = (sg["ref"], sg["stn"][bi][1])
            if key in claimed:
                del sg["stn"][bi]; dropped += 1
            else:
                claimed.add(key)
    if dropped:
        print(f"（跨支線重複的車站略過 {dropped} 座，避免站體重疊）")

    # 軌道離線位（進站張開成島式月台）與隧道半寬，必須在車站去重後才算，
    # 否則被砍掉的重複車站也會在區間隧道上開出一段莫名其妙的張開段。
    rail_b = {}
    nrail = nskip = 0
    # 預設不鋪鐵軌：走行面（smooth_stone）照留，軌道要不要鋪、鋪成什麼樣
    # 交給玩家用模組決定。--rails 才會鋪。
    # 同一條線的變體常常共用一大段幹線（中和新蘆、淡海輕軌）。兩份幾何差個
    # 一兩公尺就會互相蓋掉對方的鐵軌，把幹線打成碎片。做法是先鋪最長的那一段，
    # 之後的變體只鋪「連續 200 m 以上真正沒鋪過」的區段 —— 也就是支線本身。
    # 交會處會斷一格（沒有真的道岔），但至少幹線與支線各自都是連通的。
    seen = {}
    for sg in sorted(segs, key=lambda s: -len(s["samples"])):
        samples, ys = sg["samples"], sg["ys"]
        toff = BL.track_offsets(samples, ys, sg["ground"], sorted(sg["stn"]))
        sg["toff"] = toff
        sg["hw"] = [BL.half_width(t) for t in toff]
        grid = seen.setdefault(sg["ref"], set())
        fresh = [(int(x) >> 3, int(z) >> 3) not in grid
                 for x, z, _, _, _ in samples]
        for i, (x, z, _, _, _) in enumerate(samples):
            grid.add((int(x) >> 3, int(z) >> 3))
        if not a.rails:
            continue
        for lo_i, hi_i in _runs(fresh, 400):
            for side in (1, -1):
                pts = []
                for i in range(lo_i, hi_i):
                    x, z, ux, uz, _ = samples[i]
                    o = side * toff[i]
                    pts.append((x - uz * o, int(ys[i]) + 1, z + ux * o))
                for e in rails.rail_path(pts):
                    rail_b.setdefault((e[0] >> 9, e[2] >> 9), []).append(e)
                    nrail += 1
        nskip += 2 * (len(samples) - sum(h - l for l, h in _runs(fresh, 400)))
    if a.rails:
        print(f"鐵軌 {nrail:,} 段（雙線，含加速軌）"
              + (f"，與幹線重疊而未重鋪 {nskip:,} 段" if nskip else ""))
    else:
        print("不鋪鐵軌（--rails 可開啟）；走行面保留為 smooth_stone")

    by_ref = {}
    for sg in segs:
        e = by_ref.setdefault(sg["ref"], [0.0, 0, 999, -999, 999, -999])
        e[0] += len(sg["samples"]) * STEP / 1000
        e[1] += len(sg["stn"])
        e[2] = min(e[2], int(sg["ys"].min())); e[3] = max(e[3], int(sg["ys"].max()))
        e[4] = min(e[4], int(sg["ground"].min())); e[5] = max(e[5], int(sg["ground"].max()))
    for ref in sorted(by_ref):
        km, ns, y0, y1, g0, g1 = by_ref[ref]
        print(f"{ref:<3} {km:>6.2f} km  軌面 y{y0:>3}~{y1:<3}  地面 y{g0:>3}~{g1:<3}  車站 {ns}")
    print(f"\n合計 {sum(v[0] for v in by_ref.values()):.1f} km，車站 {sum(v[1] for v in by_ref.values())} 座")

    # ---- 依 region 分桶 ----
    # 車站的影響範圍不再只有月台長度：出入口長梯可以伸出去 76 m，
    # 分桶半徑不夠的話那些 region 根本不會呼叫 build_station，樓梯就斷了。
    reach = {}
    for li, sg in enumerate(segs):
        for bi in sg["stn"]:
            y, g = int(sg["ys"][bi]), int(sg["ground"][bi])
            if BL.structure_for_ground(y, g) == "tunnel":
                reach[(li, bi)] = 45 + 2 * max(0, g - (y + BL.MEZZ_DY + 1)) + 25
            else:
                reach[(li, bi)] = 45 + 2 * abs(y + 2 - g) + 15

    struct_b, terr_pts = {}, {}
    for li, sg in enumerate(segs):
        for i, s in enumerate(sg["samples"]):
            x, z = int(s[0]), int(s[1])
            r = reach.get((li, i), 16)
            for rx in range((x - r) >> 9, ((x + r) >> 9) + 1):
                for rz in range((z - r) >> 9, ((z + r) >> 9) + 1):
                    struct_b.setdefault((rx, rz), {}).setdefault(li, []).append(i)
            if i % 8 == 0:                        # 距離場用不著每 0.5 m 一點
                for rx in range((x - outer) >> 9, ((x + outer) >> 9) + 1):
                    for rz in range((z - outer) >> 9, ((z + outer) >> 9) + 1):
                        terr_pts.setdefault((rx, rz), []).append((x, z))

    # ---- 地標：不是沿線掃出來的東西（車站大樓、地下大廳、實際位置的出入口）----
    marks = LM.for_world(segs, stations, terr)
    mark_b = {}
    for m in marks:
        mx0, mz0, mx1, mz1 = m.bbox()
        for rx in range(mx0 >> 9, (mx1 >> 9) + 1):
            for rz in range(mz0 >> 9, (mz1 >> 9) + 1):
                mark_b.setdefault((rx, rz), []).append(m)
    if marks:
        # 地標常常伸出路線走廊之外（台北車站大樓離板南線 240 m），
        # 走廊外的地形是平的，房子會蹲在一塊高低不合的平台上。
        # 把地標的範圍也餵進距離場，讓那一帶生成真實地形。
        for m in marks:
            mx0, mz0, mx1, mz1 = m.bbox()
            for x in range(mx0, mx1 + 1, 8):
                for z in range(mz0, mz1 + 1, 8):
                    for rx in range((x - outer) >> 9, ((x + outer) >> 9) + 1):
                        for rz in range((z - outer) >> 9, ((z + outer) >> 9) + 1):
                            terr_pts.setdefault((rx, rz), []).append((x, z))
        print(f"地標 {len(marks)} 座，涵蓋 {len(mark_b)} 個 region")

    regions = sorted(set(struct_b) | set(terr_pts) | set(mark_b))
    print(f"要產生 {len(regions)} 個 region（{len(terr_pts)} 個含地形）")

    shutil.rmtree(a.out, ignore_errors=True)
    t0 = time.time(); nch = 0; nsign = 0; nbytes = 0
    for n, (rx, rz) in enumerate(regions, 1):
        w = World(a.out, name=config.WORLD_NAME)
        w._region_filter = (rx, rz)

        pts = terr_pts.get((rx, rz))
        if pts:
            bf = blend_field(pts, rx, rz, a.corridor, outer)
            if bf.max() > 0:
                per = 16 // BLEND_CELL          # 一個 chunk 對應幾格距離場
                for cx in range(rx * 32, rx * 32 + 32):
                    bi = (cx - rx * 32) * per
                    for cz in range(rz * 32, rz * 32 + 32):
                        bj = (cz - rz * 32) * per
                        # 權重全 0 = 純平地，寫出去只是白佔空間
                        if bf[bj:bj + per, bi:bi + per].max() <= 0:
                            continue
                        ch = w.chunks.get((cx, cz)) or Chunk(cx, cz)
                        w.chunks[(cx, cz)] = ch
                        terrain_chunk(ch, cx, cz, terr, bf, rx, rz)

        for li, idxs in struct_b.get((rx, rz), {}).items():
            sg = segs[li]
            samples, ys, gnd, stn = sg["samples"], sg["ys"], sg["ground"], sg["stn"]
            lights = []
            for i in idxs:
                x, z, ux, uz, _ = samples[i]
                nx, nz = -uz, ux
                y, g = int(ys[i]), int(gnd[i])
                hw, to = sg["hw"][i], sg["toff"][i]
                st = BL.structure_for_ground(y, g)
                if st == "tunnel":
                    BL.sec_tunnel(w, x, z, nx, nz, y, hw=hw)
                    if abs((i * STEP) % 8.0) < STEP / 2:
                        lights.append((x, z, nx, nz, y, to))
                elif st == "viaduct":
                    BL.sec_bridge(w, x, z, nx, nz, y, g, hw=hw,
                                  pier=(abs((i * STEP) % BL.PIER_EVERY) < STEP / 2))
                else:
                    BL.sec_ground(w, x, z, nx, nz, y, g, hw=hw)
            for x, z, nx, nz, y, to in lights:  # 挖完才裝燈，否則會被下一點挖掉
                for off in (-to, to):
                    w.set(round(x + nx * off), y + 6, round(z + nz * off), BL.LAMP)
            for i in idxs:
                if i in stn:
                    under = BL.structure_for_ground(int(ys[i]), int(gnd[i])) == "tunnel"
                    BL.build_station(w, samples, ys, i, under, label=stn[i], grounds=gnd)

        # 地標蓋在沿線結構之後：站體箱涵先挖好，大廳才好接進去
        for m in mark_b.get((rx, rz), ()):
            m.build(w)

        # 鐵軌一定要最後鋪：車站的挖空與樓梯都會蓋過走行面
        rr = rail_b.get((rx, rz), ())
        cells = {(a, b, c) for a, b, c, _, _ in rr}
        for bx, by, bz, shape, powered in rr:
            # 每根鐵軌底下都補一塊支承。rails.py 為了讓斜軌落在直線段上會把
            # 高差往前後挪幾格，挪過的那幾格軌面就會比走行面高一格而懸空。
            # 動力軌改墊紅石塊供電；那一格若已是另一股道的鐵軌就別動。
            if (bx, by - 1, bz) not in cells:
                w.set(bx, by - 1, bz,
                      "minecraft:redstone_block" if powered else BL.DECK)
            w.set(bx, by, bz, rails.block_string(shape, powered))

        nsign += sum(len(c.bes) for c in w.chunks.values())
        nch += len(w.chunks)
        nbytes += w.save_region(rx, rz)
        if n % 40 == 0 or n == len(regions):
            el = time.time() - t0
            print(f"  [{n}/{len(regions)}] {el:>5.0f}s  {nch:>7,} 區塊  "
                  f"{nbytes/1e6:>6.0f} MB  剩餘約 {el/n*(len(regions)-n):.0f}s")

    gy = int(terr.y_at(np.array([0]), np.array([0]))[0])
    w = World(a.out, name=config.WORLD_NAME, spawn=(0, gy + 2, 0))
    w._write_level()
    print(f"\n完成：{nch:,} 區塊, {nsign:,} 面告示牌, {nbytes/1e6:.0f} MB, {time.time()-t0:.0f}s")
    print(f"出生點 (0,{gy+2},0) = 台北車站地面")


if __name__ == "__main__":
    main()
