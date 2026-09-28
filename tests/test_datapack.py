#!/usr/bin/env python3
"""The ride system's datapack (application/ride_plan.py -> infrastructure/datapack.py).

Builds a synthetic network of two straight lines (Tamsui-Xinyi Line R09—R10
Taipei Main Station—R11 and Bannan Line BL11—BL12 Taipei Main Station—BL13, each
line with its own "台北車站" station box), plans the berths, generates the spec,
writes it to files and reads it back from disk to check:
  · every id the signs use (ride_fn / turn_fn / go_fn) has a function file
  · every ride/turn/go has exactly one tp @s x y z yaw pitch line, landing on the
    right berth and aiming at its sign
  · the dialogs are valid JSON: one route map button per line, one button per
    station in each line list, trigger values 1..N consecutive and unique, and a
    dispatch table that maps n to the go function of the station on that button
  · every dialog text and chat or action bar message with Chinese also has English
  · the two tags, pack.mcmeta, and DataPacks.Enabled in level.dat
  · the initial world settings apply only on first load; first join goes to R10
  · arrival notice: every landing spot is inside its own station's area (the last
    hit of the scan)
  · the read-back checks of tools/check_datapack.py find nothing wrong with this
    datapack, and catch a broken one

Loading the datapack into the real game is checked by tools/check_datapack.py
(it needs Minecraft 26.2).

Usage: ./.venv/bin/python tests/test_datapack.py
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
from mrt.application.attractions import kit
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
    """tp lands on the center of slot's berth, with the yaw toward the sign and the pitch toward its face."""
    tp = pack.tp(fn)
    if tp is None:
        return False
    x, y, z, yaw, pitch = tp
    tx, ty, tz = slot.stand
    sx, sy, sz = slot.sign
    return (x, y, z) == (tx + 0.5, ty, tz + 0.5) \
        and abs(yaw - NW.yaw_of(sx - tx, sz - tz)) < 0.051 and 0 < pitch < 45


# ---------------------------------------------------------------- Function ids and tp
print("Functions: every id the signs use has a file, and tp lands on the berth")
rides = NW.rides(net, berths)
chk("8 rides (4 per line)", len(rides) == 8)
chk("Every ride has a ride function; tp lands on the arrival berth, aiming at the sign that continues onward",
    all(os.path.exists(fpath(NW.ride_fn(a.code, b.code))) and aim_ok(NW.ride_fn(a.code, b.code), s)
        for _, a, b, s, _ in rides))
sign_ids = set()
for b in berths:
    for s in b.slots:
        if s.dest is not None:
            sign_ids.add(NW.ride_fn(b.station.code, net[(b.line, s.dest.next)].code))
        else:
            sign_ids.add(NW.turn_fn(b.station.code, b.d))
chk("The function behind every platform sign exists (%d ids)" % len(sign_ids),
    all(os.path.exists(fpath(i)) for i in sign_ids))
turns = [b for b in berths if not b.dests]
chk("4 terminus arrival sides (both ends of both lines)", len(turns) == 4)
chk("Turn functions go to the primary berth on the opposite platform (the side with a next station)",
    all(aim_ok(NW.turn_fn(b.station.code, b.d),
               bidx[(b.line, b.station.name, -b.d)].primary()) for b in turns))
chk("One go function per station, going to home_slot",
    all(aim_ok(NW.go_fn(st.code), NW.home_slot(bidx, st)) for st in net.values()))
tp_counts = [sum(1 for ln in pack.functions[p] if ln.startswith("tp "))
             for p in pack.functions if p.split("/")[0] in ("ride", "turn", "go")]
chk("Every ride/turn/go has exactly one tp line (%d functions)" % len(tp_counts),
    len(tp_counts) == 8 + 4 + 6 and all(n == 1 for n in tp_counts))
chk("tp lines follow the convention tp @s <x> <y> <z> <yaw> <pitch>, all numbers",
    all(pack.tp(p) is not None for p in pack.functions if p.split("/")[0] in ("ride", "turn", "go")))
chk("Function file names are valid resource paths", all(re.match(r"^[a-z0-9_./-]+$", p) for p in pack.functions))

# ---------------------------------------------------------------- Arrival screen
print("\nArrival screen")
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
chk("Every title and tellraw text component is valid JSON (the 26.2 SNBT subset, %d of them)" % len(comps),
    parsed == len(comps) and len(comps) > 0)
chk("The R09→R10 title is the arriving station's name, in the line colour", any('title @s title {"text":"台北車站","color":"#FF0000"' in ln for ln in ride))
chk("The action bar gives the next station (丙) and the terminal", any("actionbar" in ln and "下一站" in ln and "丙" in ln for ln in ride))
chk("The arrival chime plays after the teleport, at the player's position",
    [i for i, ln in enumerate(ride) if ln.startswith("tp ")][0]
    < [i for i, ln in enumerate(ride) if "playsound" in ln][0]
    and all(ln.startswith("execute at @s run playsound") for ln in ride if "playsound" in ln))

# ---------------------------------------------------------------- Dialogs
print("\nDialogs")
menu = pack.dialogs[NW.MENU_DIALOG]
chk("The route map is a multi_action with one button per line, each opening that line's station list",
    menu["type"] == "minecraft:multi_action" and len(menu["actions"]) == 2
    and [a["action"]["dialog"] for a in menu["actions"]] == ["%s:line/r" % NS, "%s:line/bl" % NS])
chk("Buttons are in the line colour", menu["actions"][0]["label"][0]["color"] == "#FF0000")
btn = CK.line_buttons(pack)
chk("One button per station in each line list (R 3, BL 3)",
    [len(pack.dialogs["line/r"]["actions"]), len(pack.dialogs["line/bl"]["actions"])] == [3, 3])
vals = [n for _, _, _, n in btn]
chk("Trigger values 1..N are consecutive and unique", sorted(vals) == list(range(1, len(btn) + 1)))
chk("Every button is /trigger %s set <n> (usable without operator rights)" % RP.OBJ_GO, all(o == RP.OBJ_GO for _, _, o, _ in btn))
disp = {}
for ln in pack.functions["sys/go_dispatch"]:
    m = re.match(r"^execute if score @s \S+ matches (\d+) run return run function %s:(\S+)$" % NS, ln)
    if m:
        disp[int(m.group(1))] = m.group(2)
chk("The dispatch table maps each n to the go function of the station code on its button",
    all(disp.get(n) == "go/" + NW.fn_code(code) for _, code, _, n in btn))
chk("Station lists are sorted by station code", [c for p, c, _, _ in btn if p == "line/r"] == ["R09", "R10", "R11"])
tip = json.dumps(pack.dialogs["line/r"]["actions"][1]["tooltip"], ensure_ascii=False)
chk("A transfer station's tooltip gives the other line's station code", "BL12" in tip)
chk("A station list's back button returns to the route map", pack.dialogs["line/r"]["exit_action"]["action"]["dialog"] == "%s:network" % NS)

# ---------------------------------------------------------------- Bilingual copy
print("\nBilingual copy")
CJK = re.compile(r"[\u3400-\u9fff]")
LATIN = re.compile(r"[a-z]")          # Lower case only: station codes such as BL12 are not English.


def flat(comp):
    """The plain text of a text component (a string, a list or a dict with extra)."""
    if isinstance(comp, str):
        return comp
    if isinstance(comp, list):
        return "".join(flat(c) for c in comp)
    if isinstance(comp, dict):
        return flat(comp.get("text", "")) + flat(comp.get("extra", []))
    return ""


def chinese_only(texts):
    return [t for t in texts if CJK.search(t) and not LATIN.search(t)]


def dialog_texts(dialogs):
    for d in dialogs.values():
        yield flat(d.get("title"))
        yield flat(d.get("external_title"))
        for body in d.get("body", ()):
            yield flat(body.get("contents"))
        for a in list(d.get("actions", ())) + [d.get("exit_action") or {}]:
            yield flat(a.get("label"))
            yield flat(a.get("tooltip"))


beimen = dict(id="beimen", name_zh="北門（承恩門）", name_en="North Gate (Beimen)",
              station=("甲", "R09", 200, "Jia"), facts=["1884 年"],
              spots=[kit.Spot("", 1, 66, 2, 0.0, -10.0, "北門", "North Gate")._asdict()])
bad = chinese_only(dialog_texts(RP.build_spec(net, berths, colours, sights=[beimen])["dialogs"]))
chk("Every dialog title, body, button label and tooltip with Chinese also has English (%d without)" % len(bad),
    not bad)
for t in bad[:4]:
    print("     ", t)
msgs = [flat(json.loads(m.group(1))) for ln in pack.functions.values() for cmd in ln
        for m in [re.match(r"^(?:title @s actionbar|tellraw @s) (.*)$", cmd)] if m]
bad = chinese_only(msgs)
chk("Every action bar and chat message with Chinese also has English (%d of %d without)" % (len(bad), len(msgs)),
    bool(msgs) and not bad)
for t in bad[:4]:
    print("     ", t)
setup_says = [ln for ln in pack.functions["sys/setup"] if ln.startswith("say ")]
chk("The console note on the initial settings comes in Chinese and in English",
    len(setup_says) == 3 and sum(1 for ln in setup_says if CJK.search(ln)) == 1)
long_says = [(p, len(ln) - 4) for p, lines in pack.functions.items() for ln in lines
             if ln.startswith("say ") and len(ln) - 4 > RP.MAX_SAY]
chk("Every say message fits the game's %d-character limit %s" % (RP.MAX_SAY, long_says[:3]),
    not long_says)

# ---------------------------------------------------------------- Tags, pack.mcmeta, level.dat
print("\nTags and settings files")
chk("#minecraft:load → sys/load, #minecraft:tick → sys/tick",
    pack.tags[("function", "minecraft:load")] == ["%s:sys/load" % NS]
    and pack.tags[("function", "minecraft:tick")] == ["%s:sys/tick" % NS])
chk("The route map is in #minecraft:quick_actions and #minecraft:pause_screen_additions",
    pack.tags[("dialog", "minecraft:quick_actions")] == ["%s:network" % NS]
    and pack.tags[("dialog", "minecraft:pause_screen_additions")] == ["%s:network" % NS])
meta = json.load(open(os.path.join(root, "pack.mcmeta"), encoding="utf-8"))["pack"]
chk("pack.mcmeta uses the 26.2 min_format/max_format (107.1 to 107.*)",
    meta["min_format"] == [107, 1] and meta["max_format"] == 107 and "pack_format" not in meta)
lvl = nbtlib.load(os.path.join(save, "level.dat"))
chk("DataPacks.Enabled in level.dat lists file/%s" % config.DATAPACK_NAME,
    "file/" + config.DATAPACK_NAME in [str(s) for s in lvl["Data"]["DataPacks"]["Enabled"]])

# ---------------------------------------------------------------- System functions
print("\nSystem functions")
load = pack.functions["sys/load"]
chk("The initial world settings run only while #setup has no version (/reload keeps later changes)",
    any(ln.startswith("execute unless score #setup") and ln.endswith("sys/setup") for ln in load))
setup = pack.functions["sys/setup"]
chk("The initial settings change nine rules, with 26.2 snake_case ids",
    all(("gamerule %s %s" % (r, v)) in setup for r, v, _, _ in RP.GAME_RULES) and len(RP.GAME_RULES) == 9
    and all(re.match(r"^[a-z_]+$", r) for r, _, _, _ in RP.GAME_RULES))
chk("Time is set to noon and the weather to clear", "time set 6000" in setup and "weather clear" in setup)
notice = " ".join(pack.functions["sys/notice"])
chk("The notice lists the undo command for every rule",
    all(("/gamerule %s %s" % (r, d)) in notice for r, _, d, _ in RP.GAME_RULES))
join = pack.functions["sys/join"]
chk("First join tags the player, enables both triggers and goes to R10 Taipei Main Station",
    "tag @s add %s" % RP.TAG_JOINED in join and "function %s:go/r10" % NS in join
    and "scoreboard players enable @s %s" % RP.OBJ_GO in join and spec["home"] == "go/r10")
welcome = " ".join(ln for ln in join if ln.startswith("tellraw"))
chk("The welcome message covers riding by sign, the route map button (show_dialog) and the OpenStreetMap credit",
    "告示牌" in welcome and '"show_dialog","dialog":"%s:network"' % NS in welcome
    and "© OpenStreetMap contributors" in welcome)
tick = pack.functions["sys/tick"]
chk("Each tick runs only three selectors (the heavy work is in sys/hud)", sum(1 for ln in tick if not ln.startswith("#")) == 3)
chk("sys/go resets the trigger and enables it again",
    pack.functions["sys/go"][-2:] == ["scoreboard players set @s %s 0" % RP.OBJ_GO,
                                      "scoreboard players enable @s %s" % RP.OBJ_GO])
chk("sys/hud schedules its next run (schedule … replace) and stops at once with no players",
    any(ln.startswith("schedule function %s:sys/hud %dt replace" % (NS, RP.HUD_EVERY))
        for ln in pack.functions["sys/hud"])
    and "execute unless entity @a run return 0" in pack.functions["sys/hud"])

# ---------------------------------------------------------------- Arrival notice
print("\nArrival notice")
chk("One area per station box (6)", len(spec["areas"]) == 6)
chk("Taipei Main Station on both lines shares one station number", len({a[6] for a in spec["areas"]}) == 5)


def last_hit(x, y, z):
    hits = [a[6] for a in spec["areas"]
            if a[0] <= x <= a[0] + a[3] + 1 and a[1] <= y <= a[1] + a[4] + 1 and a[2] <= z <= a[2] + a[5] + 1]
    return hits[-1] if hits else None


land = []
for p, lines in pack.functions.items():
    if p.split("/")[0] in ("ride", "turn", "go"):
        g = [int(ln.split()[-1]) for ln in lines if ln.startswith("scoreboard players set @s %s " % RP.OBJ_AREA)]
        land.append((pack.tp(p), g[0] if g else None))
chk("Every landing spot is inside its station's area and matches the number recorded on teleport "
    "(the name does not show again on arrival)",
    all(g is not None and last_hit(*tp[:3]) == g for tp, g in land))
enter = pack.functions["sys/hud_enter"]
chk("A transfer station's notice has both lines' station codes", any("R10" in ln and "BL12" in ln for ln in enter))

# ---------------------------------------------------------------- Read-back check tool
print("\nRead-back checks of tools/check_datapack.py")
problems = []
CK.static_checks(save, pack, problems, lambda *a: None)
chk("No complaints about this datapack", problems == [])
bad = os.path.join(tmp, "bad")
shutil.copytree(save, bad)
bp = os.path.join(bad, "datapacks", config.DATAPACK_NAME, "data", NS, "function")
with open(os.path.join(bp, "go", "r10.mcfunction"), "a", encoding="utf-8") as f:
    f.write("tp @s 0 0 0 0 0\n")
os.remove(os.path.join(bp, "go", "bl13.mcfunction"))
problems = []
CK.static_checks(bad, CK.Pack(os.path.join(bad, "datapacks", config.DATAPACK_NAME)), problems, lambda *a: None)
chk("Two tp lines are caught", any("go/r10" in p and "tp" in p for p in problems))
chk("A station button without a go function is caught", any("BL13" in p for p in problems))
chk("A dispatch to a missing function is caught", any("go/bl13" in p for p in problems))

# ---------------------------------------------------------------- Writing files
print("\nWriting files")
junk = os.path.join(root, "data", NS, "function", "ride", "zz_old.mcfunction")
open(junk, "w").write("say old\n")
DP.write_datapack(save, spec)
chk("A rewrite clears the whole folder first (old rides do not linger)", not os.path.exists(junk))
try:
    DP.write_datapack(save, dict(spec, functions={"Ride/X": ["say x"]}))
    chk("An upper-case resource path is rejected", False)
except ValueError:
    chk("An upper-case resource path is rejected", True)
try:
    DP.write_datapack(save, dict(spec, functions={"x": ["say a\nsay b"]}))
    chk("A newline inside a command is rejected", False)
except ValueError:
    chk("A newline inside a command is rejected", True)

shutil.rmtree(tmp, ignore_errors=True)
print("\n" + ("All tests passed" if ok else "Some tests failed"))
sys.exit(0 if ok else 1)
