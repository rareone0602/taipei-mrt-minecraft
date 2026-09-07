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
from mrt.domain import alignment as AL
from mrt.domain import rails
from mrt.domain import tunnel_layers as TL
from mrt.domain.terrain import Terrain
from mrt.infrastructure.mcworld import Chunk, World

# main() 沿用原本的模組層常數
BLEND_CELL = BW.BLEND_CELL
FLAT_Y = BW.FLAT_Y
STEP = BW.STEP
OFFSET = BW.OFFSET
blend_field = BW.blend_field
moving_avg = BW.moving_avg
profile = BW.profile
runs = BW.runs
terrain_chunk = BW.terrain_chunk


def load_stations():
    """mc_stations.csv -> [(refs, 中文名, mc_x, mc_z, 英文名, ref字串)]"""
    stations = []
    with open(config.MC_STATIONS_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            stations.append((r["ref"].split(";"), r["name_zh"] or r["name_en"],
                             int(r["mc_x"]), int(r["mc_z"]), r["name_en"], r["ref"]))
    return stations


def plan_segments(refs=None, terr=None, verbose=True):
    """規劃全網但不蓋：取樣、深度帶、縱斷面、車站對應、去重、離線位、共用幹線遮罩。

    回傳 (segs, stations, terr)。每個路段是 dict(ref, samples, ys, ground, stn,
    band, toff, hw, build, fresh)。工具與測試靠這個拿到跟生成器一模一樣的路段
    （出入口、轉乘通道的規劃都以它為準），不必真的產生世界。
    """
    terr = terr or Terrain()
    lines = json.load(open(config.MC_LINES_JSON, encoding="utf-8"))
    refs = refs or sorted(lines)
    stations = load_stations()
    say = print if verbose else (lambda *a, **k: None)

    # ---- 規劃：所有線的取樣點、縱斷面、車站對應 ----
    # 先把所有線的平面取樣做完，才能決定深度帶：某條線要不要潛下去，
    # 取決於別條線在哪裡，一條一條各自算是看不出來的。
    raw = []
    n_ext = 0.0
    for ref in refs:
        if ref not in lines:
            continue
        for v in AL.select_variants(lines[ref]):
            pts = [tuple(p) for p in v["points"]]
            kinds = v.get("kinds") or ["ground"] * len(pts)
            pts, kinds = AL.drop_reversal(pts, kinds)
            samples = AL.resample(pts, kinds, STEP)
            if len(samples) >= 10:
                raw.append((ref, samples))
    # 終點站的線形在站點就斷了，站體只蓋得出半座：往外延伸一段尾軌。
    # 支線接上幹線的那一端（七張、北投）不是終點，延伸出去會插進幹線的站體
    for k, (ref, samples) in enumerate(raw):
        spts = [(sx, sz) for rs, _, sx, sz, _, _ in stations
                if any(t.startswith(ref) and len(t) > len(ref) and t[len(ref)].isdigit()
                       for t in rs)]
        others = [(o[0], o[1]) for j, (oref, osm) in enumerate(raw)
                  if j != k and oref == ref for o in osm[::20]]
        n0, n1 = AL.terminus_extension(samples, spts, others)
        if n0 or n1:
            raw[k] = (ref, AL.extend_ends(samples, STEP, n0, n1))
            n_ext += n0 + n1

    if n_ext:
        say(f"終點站尾軌：線形端點共延伸 {n_ext:.0f} m，讓終點站蓋得出整座站體")
    pins = TL.station_pins()
    bands = TL.assign_bands(raw, pins=pins)
    if pins:
        say(f"隧道深度釘樁 {len(pins)} 根（依 OSM 月台 level 還原真實上下關係）")
    nb = np.bincount(np.concatenate([b[b >= 0] for b in bands]) if bands else [0],
                     minlength=1)
    say("隧道深度帶：" + "  ".join(
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
        say(f"（跨支線重複的車站略過 {dropped} 座，避免站體重疊）")

    # 軌道離線位（進站張開成島式月台）與隧道半寬，必須在車站去重後才算，
    # 否則被砍掉的重複車站也會在區間隧道上開出一段莫名其妙的張開段。
    nmask = 0
    # 同一條線的變體常常共用一大段幹線（中和新蘆、淡海輕軌）。兩份幾何差個
    # 一兩公尺就會互相蓋掉對方的鐵軌，把幹線打成碎片。做法是先鋪最長的那一段，
    # 之後的變體只鋪「連續 200 m 以上真正沒鋪過」的區段 —— 也就是支線本身。
    # 交會處會斷一格（沒有真的道岔），但至少幹線與支線各自都是連通的。
    #
    # 斷面也一樣只蓋「真正沒蓋過」的區段（sg["build"]）。原本共用幹線的
    # 斷面蓋兩次，以為只是浪費時間 —— 其實第二份是在第一份的車站蓋好之後
    # 才掃過去的，而它的重複車站已經被上面去重砍掉、沒有張開段，於是一條
    # 15 m 寬的素隧道直直穿過 25 m 寬的站體：月台、月台門、穿堂樓板全部
    # 被挖成空氣，頂板襯砌橫在穿堂層的高度。中和新蘆線共用幹線上的 12 座
    # 車站（頂溪到大橋頭）就這樣整座被抹掉，七張、北投與淡海輕軌七站被
    # 抹掉一部分 —— 從存檔切剖面才看出來，生成紀錄上每一站都是「已完成」。
    seen = {}
    for sg in sorted(segs, key=lambda s: -len(s["samples"])):
        samples, ys = sg["samples"], sg["ys"]
        toff = AL.track_offsets(samples, ys, sg["ground"], sorted(sg["stn"]))
        sg["toff"] = toff
        sg["hw"] = [AL.half_width(t) for t in toff]
        grid = seen.setdefault(sg["ref"], set())
        fresh = [(int(x) >> 3, int(z) >> 3) not in grid
                 for x, z, _, _, _ in samples]
        for i, (x, z, _, _, _) in enumerate(samples):
            grid.add((int(x) >> 3, int(z) >> 3))
        build = [False] * len(samples)
        for lo_i, hi_i in runs(fresh, 400):
            for i in range(lo_i, hi_i):
                build[i] = True
        sg["build"] = build
        sg["fresh"] = fresh                  # 鐵軌也照這張遮罩鋪，見 main()
        nmask += len(samples) - sum(build)
    if nmask:
        say(f"支線與幹線共用的路廊只蓋一次：略過 {nmask * STEP / 1000:.1f} km 的重複斷面")
    return segs, stations, terr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=config.DEFAULT_SAVE)
    ap.add_argument("--corridor", type=int, default=96, help="完整地形的半寬（公尺）")
    ap.add_argument("--fade", type=int, default=64, help="再往外漸變回平坦的寬度")
    ap.add_argument("--lines", nargs="*", default=None)
    ap.add_argument("--bbox", nargs=4, type=int, metavar=("X0", "Z0", "X1", "Z1"),
                    help="只產生落在這個範圍內的 region（測試單一站區用，"
                         "省得為了看台北車站等三十分鐘）")
    ap.add_argument("--rails", action="store_true",
                    help="順便鋪鐵軌。預設不鋪 —— 走行面留白，方便用模組自己鋪")
    a = ap.parse_args()
    outer = a.corridor + a.fade

    segs, stations, terr = plan_segments(a.lines)

    # 預設不鋪鐵軌：走行面（smooth_stone）照留，軌道要不要鋪、鋪成什麼樣
    # 交給玩家用模組決定。--rails 才會鋪。鋪的範圍照 plan_segments 的
    # sg["fresh"]：只鋪「連續 200 m 以上真正沒鋪過」的區段，幹線與支線各自連通。
    rail_b = {}
    nrail = nskip = 0
    if a.rails:
        for sg in segs:
            samples, ys, toff, fresh = sg["samples"], sg["ys"], sg["toff"], sg["fresh"]
            for lo_i, hi_i in runs(fresh, 400):
                for side in (1, -1):
                    pts = []
                    for i in range(lo_i, hi_i):
                        x, z, ux, uz, _ = samples[i]
                        o = side * toff[i]
                        pts.append((x - uz * o, int(ys[i]) + 1, z + ux * o))
                    for e in rails.rail_path(pts):
                        rail_b.setdefault((e[0] >> 9, e[2] >> 9), []).append(e)
                        nrail += 1
            nskip += 2 * (len(samples) - sum(h - l for l, h in runs(fresh, 400)))
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
            if AL.structure_for_ground(y, g) == "tunnel":
                reach[(li, bi)] = 45 + 2 * max(0, g - (y + AL.MEZZ_DY + 1)) + 25
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
    marks, real_exits = LM.for_world(segs, stations, terr)
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
            # 地下街整片都在地表以下，不需要為它生成真實地形；而且它切成
            # 上百塊，每塊都餵距離場的話點數會多一個數量級，地形反而變慢。
            if getattr(m, "underground", False):
                continue
            mx0, mz0, mx1, mz1 = m.bbox()
            for x in range(mx0, mx1 + 1, 8):
                for z in range(mz0, mz1 + 1, 8):
                    for rx in range((x - outer) >> 9, ((x + outer) >> 9) + 1):
                        for rz in range((z - outer) >> 9, ((z + outer) >> 9) + 1):
                            terr_pts.setdefault((rx, rz), []).append((x, z))
        print(f"地標 {len(marks)} 座，涵蓋 {len(mark_b)} 個 region")

    regions = sorted(set(struct_b) | set(terr_pts) | set(mark_b))
    if a.bbox:
        x0, z0, x1, z1 = a.bbox
        keep = [(rx, rz) for rx, rz in regions
                if rx * 512 <= x1 and (rx + 1) * 512 > x0
                and rz * 512 <= z1 and (rz + 1) * 512 > z0]
        print(f"--bbox {x0},{z0}..{x1},{z1}：{len(regions)} 個 region 只留 {len(keep)} 個")
        regions = keep
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
            build = sg["build"]
            for i in idxs:
                if not build[i]:            # 幹線已經蓋過這一段，見上面的說明
                    continue
                x, z, ux, uz, _ = samples[i]
                nx, nz = -uz, ux
                y, g = int(ys[i]), int(gnd[i])
                hw, to = sg["hw"][i], sg["toff"][i]
                st = AL.structure_for_ground(y, g)
                if st == "tunnel":
                    BL.sec_tunnel(w, x, z, nx, nz, y, hw=hw)
                    if abs((i * STEP) % 8.0) < STEP / 2:
                        lights.append((x, z, nx, nz, y, to))
                elif st == "viaduct":
                    BL.sec_bridge(w, x, z, nx, nz, y, g, hw=hw,
                                  pier=(abs((i * STEP) % AL.PIER_EVERY) < STEP / 2))
                else:
                    BL.sec_ground(w, x, z, nx, nz, y, g, hw=hw)
            for x, z, nx, nz, y, to in lights:  # 挖完才裝燈，否則會被下一點挖掉
                for off in (-to, to):
                    w.set(round(x + nx * off), y + 6, round(z + nz * off), BL.LAMP)
            for i in idxs:
                if i in stn:
                    under = AL.structure_for_ground(int(ys[i]), int(gnd[i])) == "tunnel"
                    # 有真實出入口的站不蓋樣板樓梯（見 application/build_exits.py）
                    BL.build_station(w, samples, ys, i, under, label=stn[i], grounds=gnd,
                                     access=(li, i) not in real_exits)

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
