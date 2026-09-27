#!/usr/bin/env python3
"""搭乘系統的路網規則（domain/network.py）。

合成的直線路網，站體真的蓋出來（DictSink）再驗上車位置：
  · 行車方向：靠右行駛，往 +u 的列車在 +側月台門；下一站、終點站
  · 站位：人站得住（domain/walk 的規則）、面向月台門、牌子在月台門那一排
  · 車程：從甲坐到乙，下車站在「繼續往丙」那面牌的前面；終點站的到站側
    沒有下一站
  · 支線：分歧站同一側長出兩個方向，牌子輪流分給兩個方向
  · 側式高架站：月台在月台門外側
  · 共用島式疊式站（西門那種）：兩條線的上下層與月台門側照 upper_toward

用法: ./.venv/bin/python tests/test_network.py
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from mrt.application import build_line as BL
from mrt.domain import alignment as AL
from mrt.domain import network as NW
from mrt.domain import stacked as SK
from mrt.domain import walk
from mrt.ports.block_sink import DictSink

ok = True


def chk(name, cond):
    global ok
    print(("  ok   " if cond else "  FAIL ") + name)
    ok = ok and cond


G = 66


def make_seg(ref, pts, stations, y):
    """stations = [(x 或 (x, z), 站號, 站名, 英文名)]，車站落在最近的取樣點。"""
    samples = AL.resample(pts, ["tunnel"] * len(pts), AL.STEP)
    n = len(samples)
    stn = {}
    for pos, code, name, en in stations:
        px, pz = pos if isinstance(pos, tuple) else (pos, samples[0][1])
        i = min(range(n), key=lambda k: (samples[k][0] - px) ** 2 + (samples[k][1] - pz) ** 2)
        stn[i] = (code, name, en)
    return dict(ref=ref, samples=samples, ys=np.full(n, y), ground=np.full(n, G),
                stn=stn, stn_seq=dict(stn))


def build(sg):
    """照 cli 的做法蓋出這一段的所有車站，回傳 DictSink。"""
    w = DictSink()
    for i, (full, name, en) in sg["stn"].items():
        under = AL.structure_for_ground(int(sg["ys"][i]), int(sg["ground"][i])) == "tunnel"
        BL.build_station(w, SK.station_samples(sg, i), sg["ys"], i, under,
                         label=(full, name, en), grounds=sg["ground"], access=False,
                         stacked=sg.get("stacked", {}).get(i))
    return w


def check_slots(w, berths, tag):
    """每個站位站得住、牌子在月台門那一排（原本是玻璃或站名牌）、人面向牌子。"""
    n = bad = 0
    for b in berths:
        for s in b.slots:
            n += 1
            sx, sy, sz = s.sign
            tx, ty, tz = s.stand
            here = walk.standable(w.get, tx, ty, tz)
            psd = w.get(sx, sy, sz)
            fx, fz = sx - tx, sz - tz
            facing = abs(NW.yaw_of(fx, fz) - s.yaw) < 1.0 or abs(abs(NW.yaw_of(fx, fz) - s.yaw) - 360) < 1.0
            if not (here and ("pane" in psd or "sign" in psd) and facing):
                bad += 1
                print(f"      {b} {s}: 站得住={here} 月台門={psd} 面向={facing}")
    chk(f"{tag}：{n} 個站位都站得住、面向月台門上的牌子", n > 0 and bad == 0)


# ---------------------------------------------------------------- 直線地下線
print("直線地下線：甲—乙—丙，島式月台")
line = make_seg("T", [(0, 0), (3000, 0)],
                [(500, "T01", "甲", "Jia"), (1500, "T02", "乙", "Yi"), (2500, "T03", "丙", "Bing")], 40)
segs = [line]
net, berths = NW.plan_berths(segs)
yi = net[("T", "乙")]
chk("乙有兩個方向：往甲在 −u、往丙在 +u",
    set(yi.dirs) == {"甲", "丙"} and yi.dirs["甲"].d == -1 and yi.dirs["丙"].d == 1)
chk("往丙的終點是丙、往甲的終點是甲",
    yi.dirs["丙"].terminals == ["丙"] and yi.dirs["甲"].terminals == ["甲"])
bidx = NW.berth_index(berths)
b = bidx[("T", "乙", 1)]
chk("靠右行駛：往 +u 的列車停 +側月台門（離線位 +6），人站在 +4",
    b.psd == 6 and all(s.stand[2] == 4 and s.sign[2] == 6 for s in b.slots))
chk("人面向月台門（面向 +z = 南，偏航角 0）", all(abs(s.yaw) < 0.01 for s in b.slots))
chk("每一側三面牌，全部往丙、中英文輪流",
    [s.dest.next for s in b.slots] == ["丙"] * 3 and [s.lang for s in b.slots] == ["zh", "en", "zh"])
check_slots(build(line), berths, "島式站")
slot = NW.arrival(net, bidx, "T", "甲", "乙")
chk("從甲坐到乙：下車站在繼續往丙那面牌的前面", slot is not None and slot.dest.next == "丙")
end = bidx[("T", "丙", 1)]
chk("丙的 +側沒有下一站：到站側的牌是「本站終點」", end.dests == [] and all(s.dest is None for s in end.slots))
slot = NW.arrival(net, bidx, "T", "乙", "丙")
chk("從乙坐到丙：下車在終點站的到站側", slot is not None and slot.dest is None and slot in end.slots)
chk("車程共 4 段（甲乙、乙甲、乙丙、丙乙）", len(NW.rides(net, berths)) == 4)
chk("去丙站：落在有下一站的那一側（往乙）", NW.home_slot(bidx, net[("T", "丙")]).dest.next == "乙")
chk("函式路徑是小寫站號", NW.ride_fn("T02", "T03") == "ride/t02_t03" and NW.go_fn("G03A") == "go/g03a")

# ---------------------------------------------------------------- 斜的線形
print("\n斜的線形：15°、30°、45°、60° 的島式站")
for deg in (15, 30, 45, 60):
    ux, uz = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    diag = make_seg("D", [(0, 0), (3000 * ux, 3000 * uz)],
                    [((500 * ux, 500 * uz), "D01", "子", "Zi"), ((1500 * ux, 1500 * uz), "D02", "丑", "Chou"),
                     ((2500 * ux, 2500 * uz), "D03", "寅", "Yin")], 40)
    net, berths = NW.plan_berths([diag])
    far = [max(abs(s.sign[0] - s.stand[0]), abs(s.sign[2] - s.stand[2])) for b in berths for s in b.slots]
    # 原本離線位 6 與 4 各自取整，斜的時候可能取整到相鄰兩格：人貼著牌子站
    # （忠孝新生、安康、丹鳳在全網存檔裡讀回來就是這樣）
    chk(f"{deg}°：牌子與站位的切比雪夫距離都是 {NW.STAND_IN}（{sorted(set(far))}）",
        set(far) == {NW.STAND_IN})
    check_slots(build(diag), berths, f"{deg}° 島式站")

# ---------------------------------------------------------------- 支線
print("\n支線：乙往東北分出一條到丁")
k = 1 / math.sqrt(2)
branch = make_seg("T", [(1500, 0), (1500 + 700 * k, -700 * k)],
                  [((1500, 0), "T02", "乙", "Yi"), ((1500 + 600 * k, -600 * k), "T02A", "丁", "Ding")], 40)
del branch["stn"][min(branch["stn"])]        # 乙在幹線上蓋，支線這一段去重砍掉
net, berths = NW.plan_berths([line, branch])
bidx = NW.berth_index(berths)
yi = net[("T", "乙")]
chk("乙多一個方向：往丁，跟往丙同一側", "丁" in yi.dirs and yi.dirs["丁"].d == yi.dirs["丙"].d == 1)
b = bidx[("T", "乙", 1)]
chk("同一側的三面牌輪流分給丙、丁", [s.dest.next for s in b.slots] == ["丙", "丁", "丙"])
chk("丁的站體在支線上（站號 T02A）", net[("T", "丁")].box is not None and net[("T", "丁")].code == "T02A")
slot = NW.arrival(net, bidx, "T", "丁", "乙")
chk("從丁坐回乙：下車站在往甲那面牌前面", slot is not None and slot.dest.next == "甲")

# ---------------------------------------------------------------- 高架側式
print("\n高架側式站：軌面比地面高 20 m")
sky = make_seg("S", [(0, 0), (2000, 0)],
               [(500, "S01", "戊", "Wu"), (1500, "S02", "己", "Ji")], G + 20)
net, berths = NW.plan_berths([sky])
b = NW.berth_index(berths)[("S", "戊", 1)]
chk("側式：月台門 ±5、月台在外側，人站在 ±7", b.psd == 5 and b.inward == 1
    and all(s.stand[2] == 7 for s in b.slots))
check_slots(build(sky), berths, "側式站")

# ---------------------------------------------------------------- 共用疊式站
print("\n共用島式疊式站（西門那種）：板南線在 z=0、松山新店線在 z=17")
bl = make_seg("BL", [(0, 0), (3000, 0)],
              [(500, "BL10", "龍山寺", "Longshan Temple"), (1500, "BL11", "西門", "Ximen"),
               (2500, "BL12", "台北車站", "Taipei Main Station")], 48)
gl = make_seg("G", [(0, 17), (3000, 17)],
              [((500, 17), "G11", "小南門", "Xiaonanmen"), ((1500, 17), "G12", "西門", "Ximen"),
               ((2500, 17), "G13", "北門", "Beimen")], 48)
bi = next(i for i, v in bl["stn"].items() if v[1] == "西門")
pbi = next(i for i, v in gl["stn"].items() if v[1] == "西門")
j_to = next(i for i, v in bl["stn"].items() if v[1] == "台北車站")
pj_to = next(i for i, v in gl["stn"].items() if v[1] == "北門")
r = SK.plan_shared(bl, bi, SK.direction_sign(bi, j_to), gl, pbi, SK.direction_sign(pbi, pj_to))
chk("plan_shared 蓋得成", r is not None)
net, berths = NW.plan_berths([bl, gl])
bidx = NW.berth_index(berths)
up_bl, dn_bl = bidx[("BL", "西門", 1)], bidx[("BL", "西門", -1)]
up_g, dn_g = bidx[("G", "西門", 1)], bidx[("G", "西門", -1)]
chk("板南線往台北車站在上層、往龍山寺在下層（upper_toward=台北車站）",
    up_bl.dy0 == 0 and dn_bl.dy0 == -SK.LEVEL_H)
chk("松山新店線往北門在上層、往小南門在下層（upper_toward=北門）",
    up_g.dy0 == 0 and dn_g.dy0 == -SK.LEVEL_H)
chk("兩條線在島的兩側：板南線 −6、松山新店線 +6（partner 在 +z）",
    up_bl.psd == dn_bl.psd == -6 and up_g.psd == dn_g.psd == 6)
chk("松山新店線停在板南線蓋的那座站體",
    net[("G", "西門")].box is net[("BL", "西門")].box)
w = DictSink()
for sg in (bl, gl):
    for i, (full, name, en) in sg["stn"].items():
        BL.build_station(w, SK.station_samples(sg, i), sg["ys"], i, True, label=(full, name, en),
                         grounds=sg["ground"], access=False, stacked=sg.get("stacked", {}).get(i))
check_slots(w, [up_bl, dn_bl, up_g, dn_g], "疊式站兩層")

print("\n" + ("全部通過" if ok else "有測試失敗"))
sys.exit(0 if ok else 1)
