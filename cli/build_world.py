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
import collections
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
from mrt.application import attractions as AT
from mrt.application import build_line as BL
from mrt.application import build_world as BW
from mrt.application import landmarks as LM
from mrt.application import ride_plan as RP
from mrt.application import spawn as SP
from mrt.application import signage as SG
from mrt.application.build_concourse import ShaftStair
from mrt.application.build_exits import GroundGate
from mrt.domain import alignment as AL
from mrt.domain import network as NW
from mrt.domain import rails
from mrt.domain import stacked as SK
from mrt.domain import tunnel_layers as TL
from mrt.domain.terrain import Terrain
from mrt.infrastructure import datapack as DP
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


def landmark_blocker(marks):
    """(x, y, z) -> bool：這一格落在某個地下大廳（臺鐵／高鐵月台層、地下大廳樓板）
    的箱體裡，或某座折返梯井的井身裡。搭車告示牌與站位要避開 —— 台北車站的
    臺鐵／高鐵月台層跟板南線站體在同一個深度，西端北側那一段月台門被它吃掉了；
    地下街往淡水信義線穿堂的連絡梯井（y62 一路下到 y44）從板南線月台正中間穿過去，
    井是在車站之後蓋的，那一段月台面、月台門跟牌子全變成井裡的空氣
    （tools/verify_rides.py 讀回來才看到：牌子的方塊實體還在，方塊是空氣）。"""
    vols = []
    for m in marks:
        if hasattr(m, "cells") and hasattr(m, "clear") and hasattr(m, "y"):
            lo = m.y - getattr(m, "thick", 1)
            vols.append((set(m.cells), lo, m.y + m.clear + 1))
        elif hasattr(m, "g0") and hasattr(m, "y_to") and hasattr(m, "bbox"):
            # 折返梯井（build_concourse.ShaftStair）：井口平台到井底，含頂蓋與底板。
            # 地下街的連絡梯曾經把板南線月台挖掉一段；規劃時現在會避開別條線，這裡
            # 再擋一次，而且用含邊距的 bbox —— 穿堂告示牌也不該立在井底的門前
            x0, z0, x1, z1 = (int(v) for v in m.bbox())
            cells = {(x, z) for x in range(x0, x1 + 1) for z in range(z0, z1 + 1)}
            vols.append((cells, min(m.g0, m.y_to) - 2, max(m.g0, m.y_to) + 6))

    def blocked(x, y, z, box=None):
        return any(lo <= y <= hi and (x, z) in cells for cells, lo, hi in vols)
    return blocked


def later_section_blocker(segs, reach=48.0):
    """(x, y, z, box) -> bool：這一格在站體蓋好之後，會被別的路段的斷面蓋掉。

    region 迴圈照路段順序一段一段蓋，每一段先掃斷面、再蓋自己的車站 —— 所以
    後面路段（li 比站體的大）的隧道或高架橋只要穿過站體，就會把月台挖掉。
    七張南端被小碧潭支線的隧道穿過、北投一側月台被新北投支線的高架橋壓過，
    都是這樣；搭車告示牌立在那裡不是懸空就是被牆吃掉。這裡照 sec_tunnel /
    sec_multi / sec_bridge / sec_ground 各自刷的範圍，只算站體附近真的會蓋的
    取樣點（build 遮罩），記下哪幾格在什麼高度會被後面的路段蓋掉。
    """
    boxes = {}
    for li, sg in enumerate(segs):
        for bi in sg["stn"]:
            x, z = SK.station_samples(sg, bi)[bi][:2]
            boxes[(li, bi)] = (x, z)
    hit = {}                                     # (站體路段 li, x, z) -> [(y0, y1)]
    for lj, sj in enumerate(segs):
        near = [(li, bx, bz) for (li, bi), (bx, bz) in boxes.items() if li < lj]
        if not near:
            continue
        samples, ys, gnd, build = sj["samples"], sj["ys"], sj["ground"], sj["build"]
        multi = sj.get("multi")
        for i in range(0, len(samples)):
            if not build[i]:
                continue
            x, z, ux, uz, _ = samples[i]
            owners = [li for li, bx, bz in near if abs(bx - x) <= reach and abs(bz - z) <= reach]
            if not owners:
                continue
            nx, nz = -uz, ux
            y, g = int(ys[i]), int(gnd[i])
            hw = sj["hw"][i]
            st = AL.structure_for_ground(y, g)
            if st == "tunnel" and multi is not None and multi[i]:
                trs = SK.tracks_at(sj, i)
                o0 = int(min(o for o, _ in trs)) - 4
                o1 = int(max(o for o, _ in trs)) + 4
                y0, y1 = min(t for _, t in trs) - 3, max(t for _, t in trs) + 8
            elif st == "tunnel":
                o0, o1, y0, y1 = -(hw + 2), hw + 2, y - 2, y + 7
            elif st == "viaduct":
                o0, o1, y0, y1 = -hw, hw, y - 2, y + 7
            else:
                o0, o1, y0, y1 = -(hw + 1), hw + 1, min(y - 1, g - 1), y + 7
            for off in range(o0, o1 + 1):
                c = (round(x + nx * off), round(z + nz * off))
                for li in owners:
                    hit.setdefault((li,) + c, []).append((y0, y1))

    def blocked(x, y, z, box=None):
        if box is None:
            return False
        return any(a <= y <= b for a, b in hit.get((box.li, int(x), int(z)), ()))
    return blocked


def sight_keepout(marks, segs, sights, pad=2):
    """(x, y, z) -> bool：景點不准寫的格子。景點比車站、出入口、地下街都晚蓋，
    寫到這些格子就會把人家蓋掉 —— 新光摩天大樓的基座壓在站前地下街正上方，
    台北車站的出入口亭就在它門口。

      · 地下街與空橋（Tile）：照實際的地板與外牆格子，地板下一格到頂板上一格
      · 出入口樓梯井、平面出入口：外擴 pad 格（門口要留走道），街面上 6 格以下
      · 其餘地標（站體大樓、地下大廳、通道）：bbox 整根柱子或它的高度範圍
      · 路線的斷面（地下、高架、平面）：景點附近的取樣點照半寬外擴 3 格

    只收景點範圍附近的東西；景點範圍以外一律回 False。
    """
    boxes = [s.bbox() for s in sights]
    if not boxes:
        return lambda x, y, z: False

    def near(x0, z0, x1, z1, m=0):
        return any(x0 - m <= bx1 and x1 + m >= bx0 and z0 - m <= bz1 and z1 + m >= bz0
                   for bx0, bz0, bx1, bz1 in boxes)

    spans = collections.defaultdict(list)            # (x, z) -> [(y0, y1)]

    def add_rect(x0, z0, x1, z1, y0, y1):
        for x in range(int(x0), int(x1) + 1):
            for z in range(int(z0), int(z1) + 1):
                spans[(x, z)].append((int(y0), int(y1)))

    for m in marks:
        x0, z0, x1, z1 = m.bbox()
        if not near(x0, z0, x1, z1, pad + 2):
            continue
        if hasattr(m, "cells") and hasattr(m, "ring") and hasattr(m, "ceil_of"):
            top = max(list(m.ceil_of.values()) or [m.y + 4]) + 1
            for x, z in set(m.cells) | set(m.ring):
                spans[(x, z)].append((m.y - 2, top))
        elif isinstance(m, ShaftStair):
            add_rect(x0 - pad, z0 - pad, x1 + pad, z1 + pad,
                     min(m.g0, m.y_to) - 2, max(m.g0, m.y_to) + 6)
        elif isinstance(m, GroundGate):
            add_rect(x0 - pad, z0 - pad, x1 + pad, z1 + pad, config.Y_MIN, config.Y_MAX)
        elif hasattr(m, "y") and hasattr(m, "clear"):          # Slab、RailHall
            add_rect(x0, z0, x1, z1, m.y - getattr(m, "thick", 1) - 1, m.y + m.clear + 2)
        elif hasattr(m, "y") and hasattr(m, "head"):           # Passage
            add_rect(x0, z0, x1, z1, m.y - 2, m.y + m.head + 1)
        else:
            add_rect(x0, z0, x1, z1, config.Y_MIN, config.Y_MAX)

    for sg in segs:
        samples, ys, gnd = sg["samples"], sg["ys"], sg["ground"]
        build, hws = sg.get("build"), sg.get("hw")
        for i in range(0, len(samples), 2):
            if build is not None and not build[i]:
                continue
            x, z, ux, uz, _ = samples[i]
            if not near(x, z, x, z, 40):
                continue
            nx, nz = -uz, ux
            y, g = int(ys[i]), int(gnd[i])
            hw = (hws[i] if hws is not None else 6) + 3
            st = AL.structure_for_ground(y, g)
            if st == "tunnel":            # 隧道與地下站體（穿堂在 +7、頂板再上去幾格），都在地面下
                y0, y1 = y - 3, min(y + 14, g - 1)
            elif st == "viaduct":         # 橋墩從地面起、橋面與高架站的屋頂
                y0, y1 = g - 3, y + 9
            else:
                y0, y1 = min(y, g) - 3, max(y, g) + 6
            for off in range(-hw, hw + 1):
                for t in (0.0, 0.5):
                    px, pz = x + ux * t + nx * off, z + uz * t + nz * off
                    spans[(int(math.floor(px)), int(math.floor(pz)))].append((y0, y1))

    spans = dict(spans)

    def keep(x, y, z):
        sp = spans.get((x, z))
        return sp is not None and any(a <= y <= b for a, b in sp)
    return keep


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
    n_osm = len(pins)
    # 疊式車站（府中、西門）釘在最淺的帶；共用站體的兩條線釘在同一帶，站體範圍
    # 再替下一帶占位 —— 雙層箱涵比一帶還高，別條線不能從底下鑽過去
    stk_refs = {}
    for name, ref in SK.STACKED:
        stk_refs.setdefault(name, set()).add(ref)
    pins += SK.stacked_pins(stations, stk_refs)
    # 共用站體的兩條線在站區附近彼此不算占用（見 assign_bands 的 shared）
    shared_bands = [(row[2], row[3], SK.ALLY_M, frozenset(refs))
                    for row in stations for name, refs in stk_refs.items()
                    if row[1] == name and len(refs) >= 2]
    bands = TL.assign_bands(raw, pins=pins, shared=shared_bands)
    if pins:
        say(f"隧道深度釘樁 {len(pins)} 根（{n_osm} 根依 OSM 月台 level 還原真實上下關係，"
            f"{len(pins) - n_osm} 根是疊式車站）")
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
        # stn_seq 是去重之前的快照：搭乘系統要從每個變體自己的車站序列排出
        # 「下一站」（小碧潭支線從七張出發，七張在支線這一段馬上就會被去重砍掉）
        segs.append(dict(ref=ref, samples=samples, ys=ys, ground=ground,
                         stn=stn, stn_seq=dict(stn), band=band))

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
                sg.setdefault("junction", []).append(bi)     # 見下面 build 遮罩
            else:
                claimed.add(key)
    if dropped:
        say(f"（跨支線重複的車站略過 {dropped} 座，避免站體重疊）")

    # 去重之後、任何人動 stn 之前的快照：共用站體會把 partner 的車站從 stn 拿掉
    # （西門的 G、中正紀念堂的 G），可是後面還要問「G 線上的中正紀念堂在哪一格」
    # 才知道古亭的上層往哪邊開。查鄰站一律看快照，不看還剩下什麼
    stn0 = [{nm: bi for bi, (_, nm, _) in sg["stn"].items()} for sg in segs]
    li_of = {id(sg): li for li, sg in enumerate(segs)}

    def idx_on(sg, name):
        """這一段路線上某站的取樣索引（沒有就 None）。"""
        return stn0[li_of[id(sg)]].get(name)

    def find(ref, name):
        for li, sg in enumerate(segs):
            if sg["ref"] == ref and stn0[li].get(name) is not None:
                return li, stn0[li][name]
        return None

    # ---- 疊式車站（domain/stacked.py）：府中的兩股道分到上下兩層；西門由板南線
    # 蓋一座雙層島式站體、松山新店線併進來，兩線的軌面釘成一樣。要在去重之後
    # （索引才是最後的）、算離線位之前（分層段的離線位自己算）。
    shared_at = []
    for (name, ref), spec in SK.STACKED.items():
        if spec["kind"] == "shared" and "partner" not in spec:
            continue                                  # partner 那一筆由 primary 處理
        key = find(ref, name)
        if key is None:
            say(f"疊式車站 {name}（{ref}）：路線上找不到這一站，略過")
            continue
        li, bi = key
        sg = segs[li]
        if AL.structure_for_ground(int(sg["ys"][bi]), int(sg["ground"][bi])) != "tunnel":
            say(f"疊式車站 {name}（{ref}）：不是地下站，略過")
            continue
        j_to = idx_on(sg, spec["upper_toward"])
        if j_to is None:
            say(f"疊式車站 {name}（{ref}）：同一段路線上找不到 {spec['upper_toward']}，略過")
            continue
        d = SK.direction_sign(bi, j_to)
        if spec["kind"] == "side":
            SK.plan_side(sg, bi, d, spec["plat"])
            say(f"疊式車站 {name}（{ref}）：側式疊式，上層往{spec['upper_toward']}、"
                f"月台在行進方向{'左' if spec['plat'] == 'left' else '右'}側，軌面 y{int(sg['ys'][bi])}")
            continue
        pref = spec["partner"]
        pkey, pspec = find(pref, name), SK.STACKED.get((name, pref))
        if pkey is None or pspec is None:
            say(f"疊式車站 {name}（{ref}）：找不到共用站體的 {pref}，略過")
            continue
        pli, pbi = pkey
        psg = segs[pli]
        pj_to = idx_on(psg, pspec["upper_toward"])
        if pj_to is None:
            say(f"疊式車站 {name}（{pref}）：同一段路線上找不到 {pspec['upper_toward']}，略過")
            continue
        r = SK.plan_shared(sg, bi, d, psg, pbi, SK.direction_sign(pbi, pj_to))
        if r is None:
            say(f"疊式車站 {name}（{ref}+{pref}）：兩線中線距離不在 "
                f"{SK.SEP_MIN}～{SK.SEP_MAX} m 之間，蓋不成共用站體，略過")
            continue
        lay, m, side, prng = r
        x, z = sg["samples"][bi][:2]
        shared_at.append((x, z, ref, pref))
        # 出入口通道沿站體外側走會擦到 partner 的分層過渡段，那不算撞到別線
        sg.setdefault("ally_segs", {})[bi] = (pli,)
        say(f"疊式車站 {name}（{ref}+{pref}）：共用雙層島式站體，站體中線偏 {side * m:+d} m、"
            f"{pref} 在站體內不另蓋（取樣 {prng[0]}..{prng[1]}），軌面 y{int(sg['ys'][bi])}")

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
    # 袋狀軌的幾何優先照 OSM（data/sidings.json，fetch_sidings 抓的）；沒有就用
    # domain/stacked.POCKETS 手填的距離
    sidings = {}
    if os.path.exists(config.SIDINGS_JSON):
        for it in json.load(open(config.SIDINGS_JSON, encoding="utf-8"))["items"]:
            sidings[it["id"]] = it

    seen = {}
    for sg in sorted(segs, key=lambda s: -len(s["samples"])):
        samples, ys = sg["samples"], sg["ys"]
        stk = sg.get("stacked", {})
        toff = AL.track_offsets(samples, ys, sg["ground"],
                                [i for i in sorted(sg["stn"]) if i not in stk])
        sg["toff"] = toff
        # 袋狀軌：正線就地張開、第三股道記進 extras。要在 track_offsets 之後、hw 之前
        for pk in SK.POCKETS:
            if pk["ref"] != sg["ref"]:
                continue
            ia, ib = idx_on(sg, pk["a"]), idx_on(sg, pk["b"])
            if ia is None or ib is None:
                continue
            rng, src = None, "手填距離"
            way = sidings.get(pk.get("osm"))
            if way is not None:
                lo_i, hi_i = min(ia, ib) - 400, max(ia, ib) + 400
                j0 = SK.nearest(samples, way["mc"][0][0], way["mc"][0][1], max(0, lo_i), min(len(samples) - 1, hi_i))
                j1 = SK.nearest(samples, way["mc"][-1][0], way["mc"][-1][1], max(0, lo_i), min(len(samples) - 1, hi_i))
                rng, src = (min(j0, j1), max(j0, j1)), f"OSM way {way['id']}"
            r = SK.plan_pocket(sg, ia, ib, pk["start"], pk["length"], rng=rng)
            if r is None:
                say(f"袋狀軌 {pk['a']}—{pk['b']}：兩站之間放不下，略過")
                continue
            x0, z0 = samples[r[0]][:2]
            d0, d1 = sorted((abs(r[0] - ia) * STEP, abs(r[1] - ia) * STEP))
            say(f"袋狀軌 {pk['a']}—{pk['b']}（{src}）：第三股道 {(r[1] - r[0]) * STEP:.0f} m，"
                f"離{pk['a']}站體中心 {d0:.0f}～{d1:.0f} m，({x0:.0f},{z0:.0f})")
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
        for i in sg.get("nobuild", ()):      # 共用站體裡 partner 那條線不蓋斷面
            build[i] = False
        # 支線在分歧站的那一段也不蓋：車站在幹線上蓋（上面去重），支線的幾何若在站體
        # 範圍裡偏出幹線 8 m 以上，照「沒蓋過」的遮罩會再掃一條隧道或高架橋過去，
        # 而它是在幹線車站之後才蓋的 —— 七張南端被小碧潭支線的隧道挖掉半邊月台、
        # 北投東側月台被新北投支線的高架橋壓掉一半，都是這樣（搭車告示牌的站位
        # 讀回來站不住才抓到）。支線從站體端牆外才開始；鐵軌同一段也不鋪
        jhalf = int(AL.PLATFORM_LEN / 2 / STEP) + 4
        for bj in sg.get("junction", ()):
            for i in range(max(0, bj - jhalf), min(len(samples), bj + jhalf + 1)):
                build[i] = False
                fresh[i] = False
        sg["build"] = build
        sg["fresh"] = fresh                  # 鐵軌也照這張遮罩鋪，見 main()
        nmask += len(samples) - sum(build)
    if nmask:
        say(f"支線與幹線共用的路廊只蓋一次：略過 {nmask * STEP / 1000:.1f} km 的重複斷面")

    # 帶號沒衝突不代表箱涵沒交疊：疊式站的雙層箱涵比一帶還高、釘平的縱斷面會離開
    # 帶的深度。拿每一點真正的箱涵範圍再算一次。疊得比襯砌還深才是撞進去，
    # 要大聲說；只咬到襯砌的照講但不必掛警示 —— 一直亮的警示等於沒有警示
    bad = TL.check_clearance(segs, shared_at)
    deep = [b for b in bad if b[8] > TL.LINING_DY]
    graze = len(bad) - len(deep)
    if deep:
        say(f"⚠ 跨線淨距：{len(deep)} 處不同路線的地下結構在空間裡交疊 —— "
            + "；".join(f"{a}×{b} ({x:.0f},{z:.0f}) y{a0}..{a1} / y{b0}..{b1} 疊 {d} 格"
                        for a, b, x, z, a0, a1, b0, b1, d in deep[:6]))
    elif graze:
        say(f"跨線淨距：沒有箱涵撞進別條線裡；{graze} 處上下貼著走、"
            f"共用一兩排襯砌（{'；'.join(f'{a}×{b} ({x:.0f},{z:.0f}) 疊 {d} 格' for a, b, x, z, *_, d in bad[:4])}）")
    else:
        say("跨線淨距：不同路線的地下結構沒有交疊")
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
    ap.add_argument("--sights", nargs="*", default=None, metavar="ID",
                    help="只蓋這幾座觀光景點（data/attractions.json 的 id）；不給就全蓋")
    ap.add_argument("--no-sights", action="store_true", help="不蓋觀光景點")
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
            samples, fresh = sg["samples"], sg["fresh"]
            # 每股道一條：兩股正線整段各一（分層段各走自己的離線位與軌面），
            # 袋狀軌的第三股道另外一條
            for i0, i1, off_at, y_at in SK.strands(sg):
                for lo_i, hi_i in runs(fresh, 400):
                    a0, a1 = max(lo_i, i0), min(hi_i, i1 + 1)
                    if a1 - a0 < 2:
                        continue
                    pts = []
                    for i in range(a0, a1):
                        x, z, ux, uz, _ = samples[i]
                        o = off_at(i)
                        pts.append((x - uz * o, y_at(i) + 1, z + ux * o))
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

    # 路線色（OSM 的 colour，跟 README 的全網圖同一份）：出口牌、搭車告示牌、
    # 站體裡的色帶都從這裡拿
    colours = NW.line_colours(json.load(open(config.MC_LINES_JSON, encoding="utf-8")))

    # ---- 地標：不是沿線掃出來的東西（車站大樓、地下大廳、實際位置的出入口）----
    marks, real_exits = LM.for_world(segs, stations, terr, colours=colours)
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

    # ---- 觀光景點（application/attractions/）：台北101、中正紀念堂、城門……----
    # 位置與輪廓是 OSM 的（data/attractions.json）；長相是各景點模組照公開的建築事實寫的
    sights = [] if a.no_sights else AT.for_world(stations, only=a.sights)
    sight_b = {}
    for s_ in sights:
        sx0, sz0, sx1, sz1 = s_.bbox()
        for rx in range(sx0 >> 9, (sx1 >> 9) + 1):
            for rz in range(sz0 >> 9, (sz1 >> 9) + 1):
                sight_b.setdefault((rx, rz), []).append(s_)
        # 景點四周要生成真實地形。範圍多給 terrain_margin（預設 48 m；圓山大飯店在劍潭山腰，
        # 給得大，背後的山才不會在建築後面被削成一道斜坡），淡出的那一圈不會切在建築腳下
        tm = int(getattr(s_, "terrain_margin", 48))
        for x in range(sx0 - tm, sx1 + tm + 1, 8):
            for z in range(sz0 - tm, sz1 + tm + 1, 8):
                for rx in range((x - outer) >> 9, ((x + outer) >> 9) + 1):
                    for rz in range((z - outer) >> 9, ((z + outer) >> 9) + 1):
                        terr_pts.setdefault((rx, rz), []).append((x, z))
    if sights:
        print(f"觀光景點 {len(sights)} 座，涵蓋 {len(sight_b)} 個 region")

    # ---- 搭乘系統：每座站體每條線每個行車方向的上車位置（domain/network.py）----
    # 月台上的搭車告示牌與資料包的傳送目的地都從這一份來，只算一次
    blocked = landmark_blocker(marks)
    later = later_section_blocker(segs)
    net, berths = NW.plan_berths(
        segs, blocked=lambda x, y, z, box=None: blocked(x, y, z) or later(x, y, z, box))
    n_slot = sum(len(b.slots) for b in berths)
    print(f"搭乘系統：{sum(1 for s in net.values() if s.box is not None)} 站、"
          f"{len(berths)} 個月台邊、{n_slot} 面搭車告示牌、{len(NW.rides(net, berths))} 段車程")
    # 告示牌以站體為單位立（application/signage.py）：box.key 就是 build_station 蓋的
    # 那座站體的 (路段索引, 取樣索引)，共用疊式站兩條線的月台邊都在 primary 的站體裡
    berths_of = collections.defaultdict(list)
    for b in berths:
        berths_of[b.box.key].append(b)

    # ---- 出生點：台北車站捷運出入口亭的門外（規則見 application/spawn.py）----
    # 門口那一格的地面高度要跟真的蓋出來的一樣：走廊外會漸變回平地，所以照
    # terrain_chunk 同一個式子、同一張距離場算，不讀存檔
    blend_cache = {}

    def built_ground(x, z):
        rx, rz = int(x) >> 9, int(z) >> 9
        pts = terr_pts.get((rx, rz))
        if not pts:
            return FLAT_Y                       # 這個 region 沒有地形：超平坦背景
        if (rx, rz) not in blend_cache:
            blend_cache[(rx, rz)] = blend_field(pts, rx, rz, a.corridor, outer)
        return int(BW.surface_y(terr, blend_cache[(rx, rz)], rx, rz, x, z))

    spawn = SP.plan_spawn(marks, stations, built_ground)
    if spawn is None:
        # 挑不到就退回台北車站捷運站點正上方的地面（至少是高度圖算得出來的一格）
        nx, nz = SP.station_node(stations) or (0, 0)
        spawn = dict(x=nx, y=built_ground(nx, nz) + 1, z=nz, facing=None,
                     why="找不到合格的出入口亭，退回捷運站點上方的地面")
    # 景點定案（一樓樓板高度、觀景點）要用同一個「蓋出來的地面」，也要在清快取之前
    sight_keep = sight_keepout(marks, segs, sights)
    if sights:
        AT.plan_all(sights, built_ground, sight_keep)
    # 只清內容、不刪變數：景點的 build() 也可能再查 site.g()（built_ground 還要用這個快取），
    # del 掉的話會變成 NameError: free variable 'blend_cache'
    blend_cache.clear()

    regions = sorted(set(struct_b) | set(terr_pts) | set(mark_b) | set(sight_b))
    if a.bbox:
        x0, z0, x1, z1 = a.bbox
        keep = [(rx, rz) for rx, rz in regions
                if rx * 512 <= x1 and (rx + 1) * 512 > x0
                and rz * 512 <= z1 and (rz + 1) * 512 > z0]
        print(f"--bbox {x0},{z0}..{x1},{z1}：{len(regions)} 個 region 只留 {len(keep)} 個")
        regions = keep
        if (spawn["x"] >> 9, spawn["z"] >> 9) not in set(keep):
            print(f"⚠ 出生點 ({spawn['x']},{spawn['z']}) 不在 --bbox 產生的範圍裡，"
                  f"進遊戲會站在一塊沒蓋東西的超平坦地上")
    print(f"要產生 {len(regions)} 個 region（{len(terr_pts)} 個含地形）")

    shutil.rmtree(a.out, ignore_errors=True)

    # ---- 搭乘系統的資料包：告示牌點了執行的函式、路線圖對話框、首次進入、進站提示 ----
    # 跟告示牌用同一份 net／berths（id 由 domain/network.py 的 ride_fn 等產生）。
    # 要在清掉舊存檔之後寫；level.dat 的 DataPacks 已經把它列為啟用
    colours = NW.line_colours(json.load(open(config.MC_LINES_JSON, encoding="utf-8")))
    sight_entries = AT.datapack_entries(sights)
    spec = RP.build_spec(net, berths, colours, sights=sight_entries)
    # 每一站走得到的景點（近的在前）：穿堂的售票機旁邊立景點牌
    near_sights = collections.defaultdict(list)
    for e in sorted(sight_entries, key=lambda e: e["station"][2] if e["station"] else 1e9):
        if e["station"]:
            near_sights[e["station"][0]].append(e)
    info = DP.write_datapack(a.out, spec)
    print(f"資料包 {config.DATAPACK_NAME}：{info['functions']} 個函式、{info['dialogs']} 個對話框、"
          f"{len(spec['triggers'])} 個路線圖按鈕、{len(spec['areas'])} 個進站提示範圍")
    for msg in spec["warnings"]:
        print("  ⚠ " + msg)

    t0 = time.time(); nch = 0; nsign = 0; nbytes = 0
    sight_drop = {}
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
            build, multi = sg["build"], sg.get("multi")
            for i in idxs:
                if not build[i]:            # 幹線已經蓋過這一段，見上面的說明
                    continue
                x, z, ux, uz, _ = samples[i]
                nx, nz = -uz, ux
                y, g = int(ys[i]), int(gnd[i])
                hw = sg["hw"][i]
                st = AL.structure_for_ground(y, g)
                if st == "tunnel":
                    if multi is not None and multi[i]:
                        # 分層過渡段與袋狀軌：多股道／不同高的斷面逐點取聯集
                        BL.sec_multi(w, x, z, nx, nz, SK.tracks_at(sg, i))
                    else:
                        BL.sec_tunnel(w, x, z, nx, nz, y, hw=hw)
                    if abs((i * STEP) % 8.0) < STEP / 2:
                        lights.append((x, z, nx, nz, SK.tracks_at(sg, i)))
                elif st == "viaduct":
                    BL.sec_bridge(w, x, z, nx, nz, y, g, hw=hw,
                                  pier=(abs((i * STEP) % AL.PIER_EVERY) < STEP / 2))
                else:
                    BL.sec_ground(w, x, z, nx, nz, y, g, hw=hw)
            for x, z, nx, nz, trs in lights:  # 挖完才裝燈，否則會被下一點挖掉
                for off, ty in trs:
                    w.set(round(x + nx * off), ty + 6, round(z + nz * off), BL.LAMP)
            for i in idxs:
                if i in stn:
                    under = AL.structure_for_ground(int(ys[i]), int(gnd[i])) == "tunnel"
                    # 有真實出入口的站不蓋樣板樓梯（見 application/build_exits.py）。
                    # 疊式站用站體座標系（共用站體是兩線中線的 frame）與雙層版面
                    BL.build_station(w, SK.station_samples(sg, i), ys, i, under,
                                     label=stn[i], grounds=gnd,
                                     access=(li, i) not in real_exits,
                                     stacked=sg.get("stacked", {}).get(i))
                    # 搭車告示牌、路線色帶、穿堂指引：要在站體蓋好之後（牌子取代
                    # 月台門那一格玻璃）。站體跨兩個 region 時兩邊各立一次
                    SG.station_signage(w, berths_of.get((li, i), ()), net, colours,
                                       grounds=gnd, blocked=blocked,
                                       sights=near_sights.get(stn[i][1], ()))

        # 地標蓋在沿線結構之後：站體箱涵先挖好，大廳才好接進去
        for m in mark_b.get((rx, rz), ()):
            m.build(w)

        # 觀光景點在地標之後：出入口、地下街都已經在了，景點的寫入經過禁區守門
        for s_ in sight_b.get((rx, rz), ()):
            dropped = AT.build(s_, w, sight_keep)
            if dropped:
                sight_drop[s_.id] = sight_drop.get(s_.id, 0) + dropped

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

    w = World(a.out, name=config.WORLD_NAME,
              spawn=(spawn["x"], spawn["y"], spawn["z"]), spawn_facing=spawn["facing"])
    w._write_level()
    print(f"\n完成：{nch:,} 區塊, {nsign:,} 面告示牌, {nbytes/1e6:.0f} MB, {time.time()-t0:.0f}s")
    for sid, n in sorted(sight_drop.items()):
        print(f"  景點 {sid}：禁區（出入口、地下街、路線）擋掉 {n:,} 格寫入")
    print(f"出生點 ({spawn['x']},{spawn['y']},{spawn['z']})"
          + (f" 面向 ({spawn['facing'][0]},{spawn['facing'][1]})" if spawn["facing"] else "")
          + f"：{spawn['why']}")


if __name__ == "__main__":
    main()
