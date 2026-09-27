#!/usr/bin/env python3
"""搭乘系統的資料包（application/ride_plan.py → infrastructure/datapack.py）。

合成兩條直線路網（淡水信義線 R09—R10 台北車站—R11、板南線 BL11—BL12 台北車站—BL13，
兩條線各一座「台北車站」站體），規劃上車位置、產生規格、真的寫成檔案，再從
磁碟讀回來驗：
  · 告示牌會用到的每個 id（ride_fn／turn_fn／go_fn）都有函式檔
  · 每個 ride/turn/go 恰好一行 tp @s x y z yaw pitch，落在對的站位、瞄準那面牌
  · 對話框是合法 JSON：路線圖每條線一顆按鈕、各線站表每站一顆，trigger 值
    1..N 連續不重複，分派表把 n 對到按鈕上那一站的 go 函式
  · 兩個標籤、pack.mcmeta、level.dat 的 DataPacks.Enabled
  · 世界初始設定只在第一次載入做；首次進入傳到 R10
  · 進站提示：每個落點都在自己那一站的範圍裡（掃描的最後一個命中）
  · tools/check_datapack.py 的讀回檢查對這份資料包沒有意見，壞掉的資料包它抓得到

真的丟進遊戲載入的驗證在 tools/check_datapack.py（要有 Minecraft 26.2）。

用法: ./.venv/bin/python tests/test_datapack.py
"""
import json
import os
import re
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import nbtlib
import numpy as np

from mrt import config
from mrt.application import ride_plan as RP
from mrt.domain import alignment as AL
from mrt.domain import network as NW
from mrt.infrastructure import datapack as DP
from mrt.infrastructure.mcworld import World
from tools import check_datapack as CK

ok = True


def chk(name, cond):
    global ok
    print(("  ok   " if cond else "  FAIL ") + name)
    ok = ok and cond


def make_seg(ref, z, stations, y=40, g=66):
    pts = [(0, z), (3000, z)]
    samples = AL.resample(pts, ["tunnel"] * len(pts), AL.STEP)
    n = len(samples)
    stn = {}
    for x, code, name, en in stations:
        i = min(range(n), key=lambda k: (samples[k][0] - x) ** 2)
        stn[i] = (code, name, en)
    return dict(ref=ref, samples=samples, ys=np.full(n, y), ground=np.full(n, g),
                stn=stn, stn_seq=dict(stn))


R = make_seg("R", 0, [(500, "R09", "甲", "Jia"), (1500, "R10", "台北車站", "Taipei Main Station"),
                      (2500, "R11", "丙", "Bing")])
B = make_seg("BL", 300, [(500, "BL11", "戊", "Wu"), (1500, "BL12", "台北車站", "Taipei Main Station"),
                         (2500, "BL13", "己", "Ji")], y=30)
net, berths = NW.plan_berths([R, B])
bidx = NW.berth_index(berths)
colours = {"R": "#FF0000", "BL": "#007EC7"}
spec = RP.build_spec(net, berths, colours)

tmp = tempfile.mkdtemp(prefix="mrt_test_dp_")
save = os.path.join(tmp, "save")
World(save, name="t")._write_level()
info = DP.write_datapack(save, spec)
root = info["path"]
pack = CK.Pack(root)
NS = config.DATAPACK_NS


def fpath(fn):
    return os.path.join(root, "data", NS, "function", fn + ".mcfunction")


def aim_ok(fn, slot):
    """tp 落在 slot 的站位中心，偏航角朝著牌、俯角朝著牌面。"""
    tp = pack.tp(fn)
    if tp is None:
        return False
    x, y, z, yaw, pitch = tp
    tx, ty, tz = slot.stand
    sx, sy, sz = slot.sign
    return (x, y, z) == (tx + 0.5, ty, tz + 0.5) \
        and abs(yaw - NW.yaw_of(sx - tx, sz - tz)) < 0.051 and 0 < pitch < 45


# ---------------------------------------------------------------- 函式 id 與 tp
print("函式：告示牌用得到的 id 都有檔案，tp 對到站位")
rides = NW.rides(net, berths)
chk("車程 8 段（每條線 4 段）", len(rides) == 8)
chk("每段車程都有 ride 函式，tp 落在下車站位、瞄準繼續往前的那面牌",
    all(os.path.exists(fpath(NW.ride_fn(a.code, b.code))) and aim_ok(NW.ride_fn(a.code, b.code), s)
        for _, a, b, s, _ in rides))
sign_ids = set()
for b in berths:
    for s in b.slots:
        if s.dest is not None:
            sign_ids.add(NW.ride_fn(b.station.code, net[(b.line, s.dest.next)].code))
        else:
            sign_ids.add(NW.turn_fn(b.station.code, b.d))
chk("月台上每一面牌點下去的函式都存在（%d 個 id）" % len(sign_ids),
    all(os.path.exists(fpath(i)) for i in sign_ids))
turns = [b for b in berths if not b.dests]
chk("終點站到站側 4 個（兩條線各兩端）", len(turns) == 4)
chk("turn 函式傳到對面月台（有下一站那一側）的主位",
    all(aim_ok(NW.turn_fn(b.station.code, b.d),
               bidx[(b.line, b.station.name, -b.d)].primary()) for b in turns))
chk("每站一個 go 函式，傳到 home_slot",
    all(aim_ok(NW.go_fn(st.code), NW.home_slot(bidx, st)) for st in net.values()))
tp_counts = [sum(1 for ln in pack.functions[p] if ln.startswith("tp "))
             for p in pack.functions if p.split("/")[0] in ("ride", "turn", "go")]
chk("每個 ride/turn/go 恰好一行 tp（%d 個函式）" % len(tp_counts),
    len(tp_counts) == 8 + 4 + 6 and all(n == 1 for n in tp_counts))
chk("tp 行是約定的格式：tp @s <x> <y> <z> <yaw> <pitch>，全是數字",
    all(pack.tp(p) is not None for p in pack.functions if p.split("/")[0] in ("ride", "turn", "go")))
chk("函式檔名都是合法的資源路徑", all(re.match(r"^[a-z0-9_./-]+$", p) for p in pack.functions))

# ---------------------------------------------------------------- 到站畫面
print("\n到站畫面")
ride = pack.functions[NW.ride_fn("R09", "R10")]
comps = []
for ln in pack.functions.values():
    for cmd in ln:
        m = re.match(r"^(?:title @s (?:title|subtitle|actionbar)|tellraw @s) (.*)$", cmd)
        if m:
            comps.append(m.group(1))
parsed = 0
for c in comps:
    try:
        json.loads(c)
        parsed += 1
    except ValueError:
        pass
chk("所有 title／tellraw 的文字元件都是合法 JSON（26.2 的 SNBT 子集，%d 個）" % len(comps),
    parsed == len(comps) and len(comps) > 0)
chk("R09→R10 的大標題是到站的站名、線色", any('title @s title {"text":"台北車站","color":"#FF0000"' in ln for ln in ride))
chk("動作列提示下一站（丙）與終點", any("actionbar" in ln and "下一站" in ln and "丙" in ln for ln in ride))
chk("到站鈴在傳送之後、在人的位置響",
    [i for i, ln in enumerate(ride) if ln.startswith("tp ")][0]
    < [i for i, ln in enumerate(ride) if "playsound" in ln][0]
    and all(ln.startswith("execute at @s run playsound") for ln in ride if "playsound" in ln))

# ---------------------------------------------------------------- 對話框
print("\n對話框")
menu = pack.dialogs[NW.MENU_DIALOG]
chk("路線圖是 multi_action，每條線一顆按鈕，打開各線站表",
    menu["type"] == "minecraft:multi_action" and len(menu["actions"]) == 2
    and [a["action"]["dialog"] for a in menu["actions"]] == ["%s:line/r" % NS, "%s:line/bl" % NS])
chk("按鈕是線色", menu["actions"][0]["label"][0]["color"] == "#FF0000")
btn = CK.line_buttons(pack)
chk("各線站表每站一顆按鈕（R 3 顆、BL 3 顆）",
    [len(pack.dialogs["line/r"]["actions"]), len(pack.dialogs["line/bl"]["actions"])] == [3, 3])
vals = [n for _, _, _, n in btn]
chk("trigger 值 1..N 連續不重複", sorted(vals) == list(range(1, len(btn) + 1)))
chk("按鈕都是 /trigger %s set <n>（非 OP 玩家也按得動）" % RP.OBJ_GO, all(o == RP.OBJ_GO for _, _, o, _ in btn))
disp = {}
for ln in pack.functions["sys/go_dispatch"]:
    m = re.match(r"^execute if score @s \S+ matches (\d+) run return run function %s:(\S+)$" % NS, ln)
    if m:
        disp[int(m.group(1))] = m.group(2)
chk("分派表把每個 n 對到按鈕上那個站號的 go 函式",
    all(disp.get(n) == "go/" + NW.fn_code(code) for _, code, _, n in btn))
chk("站表依站號排序", [c for p, c, _, _ in btn if p == "line/r"] == ["R09", "R10", "R11"])
tip = json.dumps(pack.dialogs["line/r"]["actions"][1]["tooltip"], ensure_ascii=False)
chk("轉乘站的提示寫出另一條線的站號", "BL12" in tip)
chk("站表的返回鍵回到路線圖", pack.dialogs["line/r"]["exit_action"]["action"]["dialog"] == "%s:network" % NS)

# ---------------------------------------------------------------- 標籤、pack.mcmeta、level.dat
print("\n標籤與設定檔")
chk("#minecraft:load → sys/load、#minecraft:tick → sys/tick",
    pack.tags[("function", "minecraft:load")] == ["%s:sys/load" % NS]
    and pack.tags[("function", "minecraft:tick")] == ["%s:sys/tick" % NS])
chk("路線圖掛進 #minecraft:quick_actions 與 #minecraft:pause_screen_additions",
    pack.tags[("dialog", "minecraft:quick_actions")] == ["%s:network" % NS]
    and pack.tags[("dialog", "minecraft:pause_screen_additions")] == ["%s:network" % NS])
meta = json.load(open(os.path.join(root, "pack.mcmeta"), encoding="utf-8"))["pack"]
chk("pack.mcmeta 用 26.2 的 min_format／max_format（107.1 ~ 107.*）",
    meta["min_format"] == [107, 1] and meta["max_format"] == 107 and "pack_format" not in meta)
lvl = nbtlib.load(os.path.join(save, "level.dat"))
chk("level.dat 的 DataPacks.Enabled 列了 file/%s" % config.DATAPACK_NAME,
    "file/" + config.DATAPACK_NAME in [str(s) for s in lvl["Data"]["DataPacks"]["Enabled"]])

# ---------------------------------------------------------------- 系統函式
print("\n系統函式")
load = pack.functions["sys/load"]
chk("世界初始設定只在 #setup 還沒記版本時做（/reload 不會蓋掉之後的調整）",
    any(ln.startswith("execute unless score #setup") and ln.endswith("sys/setup") for ln in load))
setup = pack.functions["sys/setup"]
chk("初始設定改了九條規則，規則 id 是 26.2 的 snake_case",
    all(("gamerule %s %s" % (r, v)) in setup for r, v, _, _ in RP.GAME_RULES) and len(RP.GAME_RULES) == 9
    and all(re.match(r"^[a-z_]+$", r) for r, _, _, _ in RP.GAME_RULES))
chk("時間定在中午、天氣晴", "time set 6000" in setup and "weather clear" in setup)
notice = " ".join(pack.functions["sys/notice"])
chk("通知列出每條規則的還原指令",
    all(("/gamerule %s %s" % (r, d)) in notice for r, _, d, _ in RP.GAME_RULES))
join = pack.functions["sys/join"]
chk("首次進入：上標籤、打開兩個 trigger、傳到 R10 台北車站",
    "tag @s add %s" % RP.TAG_JOINED in join and "function %s:go/r10" % NS in join
    and "scoreboard players enable @s %s" % RP.OBJ_GO in join and spec["home"] == "go/r10")
welcome = " ".join(ln for ln in join if ln.startswith("tellraw"))
chk("歡迎訊息：告示牌搭車、路線圖按鈕（show_dialog）、OpenStreetMap 標示",
    "告示牌" in welcome and '"show_dialog","dialog":"%s:network"' % NS in welcome
    and "© OpenStreetMap contributors" in welcome)
tick = pack.functions["sys/tick"]
chk("每 tick 只跑三個選擇器（重活在 sys/hud）", sum(1 for ln in tick if not ln.startswith("#")) == 3)
chk("sys/go 用完把 trigger 歸零並重新打開",
    pack.functions["sys/go"][-2:] == ["scoreboard players set @s %s 0" % RP.OBJ_GO,
                                      "scoreboard players enable @s %s" % RP.OBJ_GO])
chk("sys/hud 自己排下一次（schedule … replace），沒有玩家就直接結束",
    any(ln.startswith("schedule function %s:sys/hud %dt replace" % (NS, RP.HUD_EVERY))
        for ln in pack.functions["sys/hud"])
    and "execute unless entity @a run return 0" in pack.functions["sys/hud"])

# ---------------------------------------------------------------- 進站提示
print("\n進站提示")
chk("每座站體一個範圍（6 座）", len(spec["areas"]) == 6)
chk("兩條線的台北車站共用一個車站編號", len({a[6] for a in spec["areas"]}) == 5)


def last_hit(x, y, z):
    hits = [a[6] for a in spec["areas"]
            if a[0] <= x <= a[0] + a[3] + 1 and a[1] <= y <= a[1] + a[4] + 1 and a[2] <= z <= a[2] + a[5] + 1]
    return hits[-1] if hits else None


land = []
for p, lines in pack.functions.items():
    if p.split("/")[0] in ("ride", "turn", "go"):
        g = [int(ln.split()[-1]) for ln in lines if ln.startswith("scoreboard players set @s %s " % RP.OBJ_AREA)]
        land.append((pack.tp(p), g[0] if g else None))
chk("每個落點都在那一站的範圍裡、跟傳送時記下的車站編號一致（到站不會再亮一次站名）",
    all(g is not None and last_hit(*tp[:3]) == g for tp, g in land))
enter = pack.functions["sys/hud_enter"]
chk("轉乘站的站名提示有兩條線的站號", any("R10" in ln and "BL12" in ln for ln in enter))

# ---------------------------------------------------------------- 讀回檢查工具
print("\ntools/check_datapack.py 的讀回檢查")
problems = []
CK.static_checks(save, pack, problems, lambda *a: None)
chk("對這份資料包沒有意見", problems == [])
bad = os.path.join(tmp, "bad")
shutil.copytree(save, bad)
bp = os.path.join(bad, "datapacks", config.DATAPACK_NAME, "data", NS, "function")
with open(os.path.join(bp, "go", "r10.mcfunction"), "a", encoding="utf-8") as f:
    f.write("tp @s 0 0 0 0 0\n")
os.remove(os.path.join(bp, "go", "bl13.mcfunction"))
problems = []
CK.static_checks(bad, CK.Pack(os.path.join(bad, "datapacks", config.DATAPACK_NAME)), problems, lambda *a: None)
chk("兩行 tp 抓得到", any("go/r10" in p and "tp" in p for p in problems))
chk("站表按鈕對不到 go 函式抓得到", any("BL13" in p for p in problems))
chk("分派表呼叫不存在的函式抓得到", any("go/bl13" in p for p in problems))

# ---------------------------------------------------------------- 寫檔
print("\n寫檔")
junk = os.path.join(root, "data", NS, "function", "ride", "zz_old.mcfunction")
open(junk, "w").write("say old\n")
DP.write_datapack(save, spec)
chk("重寫時整個資料夾先清掉（舊的車程不會留下來）", not os.path.exists(junk))
try:
    DP.write_datapack(save, dict(spec, functions={"Ride/X": ["say x"]}))
    chk("大寫的資源路徑被擋下來", False)
except ValueError:
    chk("大寫的資源路徑被擋下來", True)
try:
    DP.write_datapack(save, dict(spec, functions={"x": ["say a\nsay b"]}))
    chk("指令裡夾換行被擋下來", False)
except ValueError:
    chk("指令裡夾換行被擋下來", True)

shutil.rmtree(tmp, ignore_errors=True)
print("\n" + ("全部通過" if ok else "有測試失敗"))
sys.exit(0 if ok else 1)
