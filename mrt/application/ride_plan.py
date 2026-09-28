#!/usr/bin/env python3
"""The datapack spec of the ride system: turns the network (domain/network.py) into plain data.

The platform signs only decide which function a click runs (mrt:ride/bl12_bl13,
mrt:turn/bl01_m), and the ticket machine sign opens the route map dialog
(mrt:network). This module writes what those ids actually do as Minecraft
commands and dialog JSON:

  ride/*   Ride one stop: teleport to the platform for the same direction at the
           next station, facing the sign that continues onward. The title is the
           arriving station's name (in the line color), the subtitle its code,
           English name and line, the action bar gives the next station, and an
           arrival chime plays.
  turn/*   The sign on the arrival side of a terminus: move to the primary berth
           on the opposite platform (the side trains leave from).
  go/*     A station button on the route map: teleport to the primary berth on
           the side of that station that has a next station.
  sight/*  A button in the attraction list and the signs at attractions: teleport
           to the attraction's viewpoint (or Taipei 101's observatory).
  sys/*    Load, tick, first join, trigger dispatch, the arrival notice (HUD) and
           the initial world settings.

**Convention** (the read-back verifiers in tools/ and tools/check_datapack.py rely
on it): every ride/*, turn/*, go/* and sight/* function has exactly one line
``tp @s <x> <y> <z> <yaw> <pitch>`` with absolute numeric coordinates, where x
and z are the center of the berth block (+0.5) and y is the block the feet are in.

This layer only produces dicts, lists and strings and never touches files:
writing happens in infrastructure/datapack.py, and the namespace and folder names
live in config (the sign side takes them from there too).
"""
import json
import math

from mrt import config
from mrt.application import signage as SG
from mrt.application.attractions.kit import sight_fn
from mrt.domain import alignment as AL
from mrt.domain import network as NW
from mrt.domain import stacked as SK

NS = config.DATAPACK_NS

# ---- Scoreboards and tags (all prefixed with the namespace so they never collide with another datapack) ----
OBJ_GO = NS + ".go"          # trigger: the route map's station buttons (/trigger mrt.go set <n>).
OBJ_MENU = NS + ".menu"      # trigger: open the route map (/trigger mrt.menu).
OBJ_STATE = NS + ".state"    # dummy: #setup holds the initial settings version, #notice a pending settings notice, #beat the HUD heartbeat.
OBJ_AREA = NS + ".area"      # dummy: the station area the player was in on the previous scan (the arrival notice shows once).
OBJ_HERE = NS + ".here"      # dummy: the station area the player is in on this scan (0 = not in any station).
TAG_JOINED = NS + ".joined"  # Player tag: has joined before (the first-join teleport and welcome message happen once).

SETUP_VERSION = 1            # Bump when the initial world settings change: old worlds apply them again after /reload.
HUD_EVERY = 10               # Ticks between arrival notice scans (twice a second, about two hundred selectors across the network).
HOME = ("R", "台北車站")      # First-join landing spot: the primary berth of Taipei Main Station (R10) on the Tamsui-Xinyi Line.

# Line of sight: the eyes are 1.62 blocks up, aimed 0.6 blocks up inside the sign
# block (the middle of the face). After a teleport the crosshair rests on the
# sign, so one more right-click rides to the next station.
EYE_H, AIM_H = 1.62, 0.6

# Arrival chime: two chimes together, a perfect fourth apart (pitches 1.0 and 1.335 = 2^(5/12)).
CHIME = ("minecraft:block.note_block.chime", 0.8, (1.0, 1.335))

# Initial world settings: (rule, value, 26.2 default, description shown to the
# player). Rule ids in 26.2 are snake_case; the list comes from the
# game_rules.dat the game writes (see the in-game check in tools/check_datapack.py).
GAME_RULES = [
    ("spawn_monsters", "false", "true", "不生成敵對生物 No hostile mobs"),
    ("spawn_phantoms", "false", "true", "不生成夜魅 No phantoms"),
    ("spawn_patrols", "false", "true", "不生成災厄巡邏隊 No pillager patrols"),
    ("spawn_wandering_traders", "false", "true", "不生成流浪商人 No wandering traders"),
    ("advance_time", "false", "true", "時間停在中午 Time stays at noon"),
    ("advance_weather", "false", "true", "天氣固定晴天 Weather stays clear"),
    ("keep_inventory", "true", "false", "死亡不掉落物品 Items are kept on death"),
    ("mob_griefing", "false", "true", "生物不破壞方塊 Mobs do not break blocks"),
    ("respawn_radius", "0", "10", "重生不隨機偏移 Respawn exactly at the spawn point"),
]
NOON = 6000
MAX_SAY = 256                # The game rejects a whole function if one say message is longer.

ATTRIBUTION = "地圖資料 Map data © OpenStreetMap contributors（ODbL 1.0）"
MENU_TITLE = "台北捷運路線圖"

# Dialog buttons use the same font as signs, so signage.text_width measures
# their labels. A label keeps 2 px of margin on each side
# (AbstractButton.extractDefaultLabel) and scrolls if it is wider.
LABEL_MARGIN = 4
STATION_BUTTON_W = 130       # Three columns of 130 plus 2 px gaps stay within the 400 px body.
SIGHT_BUTTON_W = 200


# ---------- Helpers ----------

def fid(path):
    """Function or dialog path -> full id ("ride/bl12_bl13" -> "mrt:ride/bl12_bl13")."""
    return "%s:%s" % (NS, path)


def text(obj):
    """Text component -> its literal in a command.

    Commands in 26.2 take SNBT, and JSON is a subset of it (double-quoted keys,
    true and \\n escapes are all understood), so json.dumps is used directly.
    Chinese is not escaped; function files are UTF-8.
    """
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def line_name(ref):
    return NW.LINE_NAMES.get(ref, (ref, ref))


def line_order(refs):
    """Display order of lines: as in LINE_NAMES (the Taipei Metro line numbering), with unlisted lines last."""
    known = list(NW.LINE_NAMES)
    return sorted(refs, key=lambda r: (known.index(r) if r in known else len(known), r))


def _full_name(st):
    """Code, Chinese name and English name of a station, as a tooltip shows them."""
    en = st.en if st.en != st.name else ""
    return " ".join(p for p in (st.code, st.name, en) if p)


def _label_en(forms, used, width):
    """The longest English form that fits beside the used part of a button
    label, truncated if none fits; "" if there is no room for even that."""
    room = width - LABEL_MARGIN - used - SG.text_width(" ")
    if not forms or room < SG.text_width("Xx…"):
        return ""
    return SG.fit(forms, width=room)


def aim(slot):
    """(x, y, z, yaw, pitch): standing at the center of slot's berth, facing and aiming at its sign.

    The yaw is computed from the berth to the sign's block center rather than
    taken from slot.yaw (the platform screen door normal): at a 45-degree
    station the rounded sign cell is not always exactly on the normal, and half
    a block off can miss the sign.
    """
    sx, sy, sz = slot.sign
    tx, ty, tz = slot.stand
    fx, fz = sx - tx, sz - tz
    dist = math.hypot(fx, fz)
    yaw = NW.yaw_of(fx, fz) if dist > 0 else slot.yaw
    pitch = round(math.degrees(math.atan2(EYE_H - AIM_H + (ty - sy), max(dist, 0.5))), 1)
    return tx + 0.5, ty, tz + 0.5, yaw, pitch


def tp_line(slot):
    """The convention line: tp @s <x> <y> <z> <yaw> <pitch> (absolute coordinates)."""
    x, y, z, yaw, pitch = aim(slot)
    return "tp @s %.1f %d %.1f %.1f %.1f" % (x, y, z, yaw, pitch)


def chime_lines():
    snd, vol, pitches = CHIME
    return ["execute at @s run playsound %s player @s ~ ~ ~ %.2f %.3f" % (snd, vol, p)
            for p in pitches]


# ---------- Arrival screen ----------

def _station_en(net, ref, name):
    st = net.get((ref, name))
    return st.en if st is not None else name


def _terminals(net, ref, dr):
    """The terminals in this direction: ("南港展覽館", "Nangang Exhibition Center")."""
    zh = "／".join(dr.terminals)
    en = " / ".join(_station_en(net, ref, t) for t in dr.terminals)
    return zh, en


def arrival_lines(net, st, slot, colours):
    """Arrival: the station name as the title, its code and line as the subtitle, the next station in the action bar."""
    ref = st.ref
    c = colours.get(ref, "#FFFFFF")
    lz, le = line_name(ref)
    out = [
        "title @s times 5 50 15",
        "title @s subtitle " + text([
            {"text": st.code + " ", "color": c, "bold": True},
            {"text": "%s · %s %s" % (st.en, lz, le), "color": "white"}]),
        "title @s title " + text({"text": st.name, "color": c, "bold": True}),
    ]
    dr = slot.dest if slot is not None else None
    if dr is not None:
        tz_, te = _terminals(net, ref, dr)
        out.append("title @s actionbar " + text([
            {"text": "下一站 Next ", "color": "gray"},
            {"text": "%s %s" % (dr.next, _station_en(net, ref, dr.next)), "color": "white"},
            {"text": "　往 To %s %s" % (tz_, te), "color": "gray"}]))
    else:
        out.append("title @s actionbar " + text([
            {"text": "本站為終點站 Terminus", "color": "yellow"},
            {"text": "　點月台上的告示牌換到對面月台 Click a sign to cross to the other platform",
             "color": "gray"}]))
    return out


def _fn_header(desc):
    return ["# " + desc, "# Generated by mrt/application/ride_plan.py; edit the generator, not this file."]


# ---------- Functions ----------

def _ride_targets(net, berths):
    """{(line, from name, to name): (from station, to station, arrival Slot)}.

    NW.rides is authoritative. Every ride a platform sign points to needs a
    function, so if arrival finds no berth (landmarks blocked every sign on that
    side), it falls back to the destination's home_slot rather than answer the
    click with "Unknown function".
    """
    bidx = NW.berth_index(berths)
    got = {}
    for ref, st, to, slot, _dr in NW.rides(net, berths):
        got[(ref, st.name, to.name)] = (st, to, slot)
    for b in berths:
        for s in b.slots:
            if s.dest is None:
                continue
            key = (b.line, b.station.name, s.dest.next)
            to = net.get((b.line, s.dest.next))
            if key in got or to is None:
                continue
            slot = NW.home_slot(bidx, to)
            if slot is not None:
                got[key] = (b.station, to, slot)
    return got


def _turn_targets(berths):
    """[(Berth, target Slot)]: every platform edge on the arrival side of a terminus (no next station)."""
    bidx = NW.berth_index(berths)
    out = []
    for b in berths:
        if b.dests or not b.slots:
            continue
        opp = bidx.get((b.line, b.station.name, -b.d))
        if opp is not None and opp.slots and opp.dests:
            slot = opp.primary()
        else:
            slot = NW.home_slot(bidx, b.station)
        if slot is not None:
            out.append((b, slot))
    return out


def _stations_by_line(net, berths):
    """{line: [Station]} in natural code order, only stations with a home_slot (that a go function can reach)."""
    bidx = NW.berth_index(berths)
    out = {}
    for st in net.values():
        if st.box is None or NW.home_slot(bidx, st) is None:
            continue
        out.setdefault(st.ref, []).append(st)
    for ref in out:
        out[ref].sort(key=lambda s: NW.code_sort_key(s.code))
    return out


def _codes_by_name(net):
    """{station name: [(line, code)]}: a transfer station's code on each line (for display)."""
    out = {}
    for st in net.values():
        if st.box is not None:
            out.setdefault(st.name, []).append((st.ref, st.code))
    order = {r: i for i, r in enumerate(line_order({r for v in out.values() for r, _ in v}))}
    for k in out:
        out[k].sort(key=lambda rc: (order[rc[0]], NW.code_sort_key(rc[1])))
    return out


# ---------- Arrival notice (HUD) ----------

AREA_HALF = AL.BOX_HALF + 1      # Half the station box width, plus one block.


def station_area(box):
    """The axis-aligned bounding box of a station box (x0, y0, z0, dx, dy, dz), for @a[x=,y=,z=,dx=,dy=,dz=].

    Horizontal: the four corners BOX_HALF+1 blocks to either side of both
    platform ends (lo, hi).
    Vertical (foot height): an underground station spans from the platform (the
    lower platform in a stacked station) to the concourse (rail top +7); an
    elevated or at-grade station's concourse may be under the viaduct (rail top
    −6) or above the platforms (rail top +8), and both are covered.
    At a 45-degree station the bounding box is larger than the station box; the
    arrival notice simply shows a little earlier.
    """
    xs, zs = [], []
    for i in (box.lo, box.hi):
        for off in (-AREA_HALF, AREA_HALF):
            x, z = box.cell(i, off)
            xs.append(x)
            zs.append(z)
    ys = [int(box.ys[i]) for i in range(box.lo, box.hi + 1)]
    y_lo, y_hi = min(ys), max(ys)
    if box.kind == "side":
        y0 = y_lo + AL.LEVEL_DY["under"] - 1
        y1 = y_hi + AL.LEVEL_DY["over"] + 1
    else:
        y0 = y_lo + 1 - (SK.LEVEL_H if box.kind.startswith("stacked") else 0)
        y1 = y_hi + AL.LEVEL_DY["tunnel"] + 1
    x0, z0 = min(xs), min(zs)
    return x0, y0, z0, max(xs) - x0, y1 - y0, max(zs) - z0


def hud_text(name, en, codes, colours):
    """Action bar: the station codes (each in its line color), the station name and its English name."""
    parts = []
    for ref, code in codes:
        parts.append({"text": "▌", "color": colours.get(ref, "#FFFFFF")})
        parts.append({"text": code + " ", "color": colours.get(ref, "#FFFFFF"), "bold": True})
    one = len({r for r, _ in codes}) == 1
    parts.append({"text": " " + name, "color": colours.get(codes[0][0], "#FFFFFF") if one else "white",
                  "bold": True})
    parts.append({"text": "  " + en, "color": "gray"})
    return parts


# ---------- Dialogs ----------

def _line_dialog(ref, stations, trig, codes_by_name, colours, near_sights=None):
    c = colours.get(ref, "#FFFFFF")
    lz, le = line_name(ref)
    actions = []
    for st in stations:
        xfer = [rc for rc in codes_by_name.get(st.name, ()) if rc[0] != ref]
        tip = [{"text": st.en}]
        if xfer:
            tip.append({"text": "\n轉乘 Transfer:", "color": "gray"})
            for r, code in xfer:
                tip.append({"text": "\n%s %s %s" % ((code,) + line_name(r)),
                            "color": colours.get(r, "#FFFFFF")})
        near = (near_sights or {}).get(st.name)
        if near:
            tip.append({"text": "\n★ 附近景點 Nearby:", "color": SIGHT_COLOR})
            for zh, en in near:
                tip.append({"text": "\n%s %s" % (zh, en), "color": "white"})
        label = [{"text": st.code + " ", "color": c, "bold": True},
                 {"text": st.name, "color": "white"}]
        # Abbreviations only: a dropped word ("Taipei City" for Taipei City Hall)
        # misleads where a truncation ("Taipei City…") does not.
        en = _label_en(SG.en_abbrevs(st.en) if st.en and st.en != st.name else [],
                      SG.text_width(st.code + " ", True) + SG.text_width(st.name), STATION_BUTTON_W)
        if en:
            label.append({"text": " " + en, "color": "gray"})
        actions.append({
            "label": label,
            "tooltip": tip,
            "width": STATION_BUTTON_W,
            "action": {"type": "minecraft:run_command",
                       "command": "trigger %s set %d" % (OBJ_GO, trig[(st.ref, st.name)])},
        })
    return {
        "type": "minecraft:multi_action",
        "title": [{"text": "▌", "color": c}, {"text": "%s %s" % (lz, le), "color": c, "bold": True}],
        "external_title": [{"text": "▌", "color": c}, {"text": "%s %s" % (lz, le)}],
        "body": [{"type": "minecraft:plain_message", "width": 400, "contents": [
            {"text": "點站名就傳送到那一站的月台（面向往下一站的告示牌）\n", "color": "white"},
            {"text": "Click a station to teleport to its platform, facing the sign for the next station.",
             "color": "gray"}]}],
        "columns": 3,
        "actions": actions,
        "exit_action": {"label": {"text": "← 返回路線圖 Back"}, "width": 200,
                        "action": {"type": "minecraft:show_dialog", "dialog": fid(NW.MENU_DIALOG)}},
    }


def _menu_dialog(refs, by_line, colours, n_sights=0):
    actions = []
    for ref in refs:
        c = colours.get(ref, "#FFFFFF")
        lz, le = line_name(ref)
        sts = by_line[ref]
        actions.append({
            "label": [{"text": "▌", "color": c}, {"text": lz + " ", "color": c, "bold": True},
                      {"text": le, "color": "white"}],
            "tooltip": [{"text": "%d 站 stations\n" % len(sts)},
                        {"text": "%s\n↔ %s" % (_full_name(sts[0]), _full_name(sts[-1])),
                         "color": "gray"}],
            "width": 200,
            "action": {"type": "minecraft:show_dialog", "dialog": fid(NW.line_dialog(ref))},
        })
    if n_sights:
        actions.append({
            "label": [{"text": "★ ", "color": SIGHT_COLOR}, {"text": "觀光景點 ", "color": SIGHT_COLOR, "bold": True},
                      {"text": "Attractions", "color": "white"}],
            "tooltip": [{"text": "%d 處景點：台北101、中正紀念堂、總統府……\n" % n_sights},
                        {"text": "%d attractions, including Taipei 101, Chiang Kai-shek Memorial Hall "
                                 "and the Presidential Office Building\n" % n_sights, "color": "gray"},
                        {"text": "傳送到景點前的觀景點 Teleport to a viewpoint", "color": "gray"}],
            "width": 200,
            "action": {"type": "minecraft:show_dialog", "dialog": fid(SIGHTS_DIALOG)},
        })
    return {
        "type": "minecraft:multi_action",
        "title": {"text": "台北捷運路線圖 Taipei Metro Route Map", "bold": True},
        "external_title": {"text": MENU_TITLE + " Route Map"},
        "body": [{"type": "minecraft:plain_message", "width": 400, "contents": [
            {"text": "選一條路線，再點站名就傳送到那一站的月台。\n", "color": "white"},
            {"text": "Pick a line, then a station to teleport there.\n\n", "color": "gray"},
            {"text": "在月台上右鍵點告示牌，就能坐到下一站。\n", "color": "white"},
            {"text": "Right-click a platform sign to ride to the next station.\n\n", "color": "gray"},
            {"text": ATTRIBUTION, "color": "dark_gray"}]}],
        "columns": 2,
        "actions": actions,
        "exit_action": {"label": {"text": "關閉 Close"}, "width": 200},
    }


# ---------- Attractions ----------

SIGHT_COLOR = "#E0B040"      # Color of the attraction buttons and titles (gold, distinct from every line color).
SIGHTS_DIALOG = "sights"     # The attraction list dialog (mrt:sights).


def sight_tp_line(sp):
    """The teleport line of an attraction spot (the tp_line format); sp is the dict of an attractions.Spot."""
    return "tp @s %.1f %d %.1f %.1f %.1f" % (sp["x"] + 0.5, sp["y"], sp["z"] + 0.5, sp["yaw"], sp["pitch"])


def sight_arrival_lines(e, sp):
    """Arrival at an attraction: the name (or the observatory's name) as the
    title, the English name as the subtitle, and a fact and the nearest station
    in the action bar."""
    main = not sp["key"]
    title = e["name_zh"] if main else sp["zh"]
    sub = e["name_en"] if main else sp["en"]
    bar = [{"text": " · ".join(e["facts"]) + ("　" if e["facts"] else ""), "color": "white"}]
    st = e.get("station")
    if st and main:
        bar.append({"text": "最近的捷運站 Nearest MRT: %s %s（%d m）" % (st[0], st[3], st[2]), "color": "gray"})
    return [
        "title @s times 5 60 20",
        "title @s subtitle " + text({"text": sub, "color": "white"}),
        "title @s title " + text({"text": title, "color": SIGHT_COLOR, "bold": True}),
        "title @s actionbar " + text(bar),
        "execute at @s run playsound minecraft:block.note_block.bell player @s ~ ~ ~ 0.7 1.0",
    ]


def _sight_dialog(entries, trig):
    actions = []
    for e in entries:
        st = e.get("station")
        tip = [{"text": e["name_en"]}]
        if e["facts"]:
            tip.append({"text": "\n" + " · ".join(e["facts"]), "color": "white"})
        if st:
            tip.append({"text": "\n最近的捷運站 %s（%d m）\nNearest MRT: %s" % (st[0], st[2], st[3]),
                        "color": "gray"})
        # tools/check_datapack.py reads the Chinese name from the last label
        # element's "text", so the English rides in that element's "extra".
        name = {"text": e["name_zh"], "color": "white"}
        en = _label_en(SG.sight_en_forms(e["name_en"]),
                      SG.text_width("★ ") + SG.text_width(e["name_zh"]), SIGHT_BUTTON_W)
        if en:
            name["extra"] = [{"text": " " + en, "color": "gray"}]
        actions.append({
            "label": [{"text": "★ ", "color": SIGHT_COLOR}, name],
            "tooltip": tip,
            "width": SIGHT_BUTTON_W,
            "action": {"type": "minecraft:run_command",
                       "command": "trigger %s set %d" % (OBJ_GO, trig[e["id"]])},
        })
    return {
        "type": "minecraft:multi_action",
        "title": [{"text": "★ ", "color": SIGHT_COLOR},
                  {"text": "觀光景點 Attractions", "color": SIGHT_COLOR, "bold": True}],
        "external_title": {"text": "觀光景點 Attractions"},
        "body": [{"type": "minecraft:plain_message", "width": 400, "contents": [
            {"text": "點景點就傳送到它前面的觀景點。建築的位置、方位與輪廓來自 OpenStreetMap。\n",
             "color": "white"},
            {"text": "Click to teleport to a viewpoint in front of the attraction. "
                     "The buildings' positions, orientations and outlines come from OpenStreetMap.",
             "color": "gray"}]}],
        "columns": 2,
        "actions": actions,
        "exit_action": {"label": {"text": "← 返回路線圖 Back"}, "width": 200,
                        "action": {"type": "minecraft:show_dialog", "dialog": fid(NW.MENU_DIALOG)}},
    }


# ---------- System functions ----------

def _setup_fns():
    """The initial world settings (applied once) and the settings notice."""
    setup = _fn_header("Initial world settings: applied only on first load (#setup records the version), "
                       "so /reload does not overwrite later changes by players")
    for rule, val, _default, _desc in GAME_RULES:
        setup.append("gamerule %s %s" % (rule, val))
    setup += [
        "time set %d" % NOON,
        "weather clear",
        "scoreboard players set #setup %s %d" % (OBJ_STATE, SETUP_VERSION),
        "scoreboard players set #notice %s 1" % OBJ_STATE,
        # Visible on the server console (usually no player is online when the world opens).
        "say [台北捷運] 已套用世界初始設定：" + "、".join(
            "%s=%s" % (r, v) for r, v, _, _ in GAME_RULES)
        + "；時間定在中午、天氣晴。還原：/gamerule <規則> <原值>",
        # Two English lines, because a chat message is capped at 256 characters
        # (MAX_SAY) and the rules alone take most of that.
        "say [Taipei Metro] World rules set: " + ", ".join(
            "%s=%s" % (r, v) for r, v, _, _ in GAME_RULES),
        "say [Taipei Metro] Time set to noon, weather clear. To undo a rule: "
        "/gamerule <rule> <original value>",
        # On a /reload upgrade players are already online: tell them now rather
        # than wait for the next new player.
        "execute as @a run function %s" % fid("sys/notice"),
    ]
    notice = _fn_header("Tell players which rules the initial world settings changed and how to undo them "
                        "(clicking a command fills it into the chat box)")
    msg = [{"text": "[台北捷運 Taipei Metro] 已套用世界初始設定 World settings applied\n",
            "color": "gold", "bold": True}]
    for rule, val, default, desc in GAME_RULES:
        cmd = "/gamerule %s %s" % (rule, default)
        msg.append({"text": " · %s（%s = %s）" % (desc, rule, val), "color": "white"})
        msg.append({"text": "  還原 Undo: " + cmd + "\n", "color": "gray",
                    "click_event": {"action": "suggest_command", "command": cmd},
                    "hover_event": {"action": "show_text", "value": "點一下填入聊天欄 Click to fill in"}})
    msg.append({"text": " · 時間定在中午、天氣晴 Time set to noon, weather clear（time set %d、weather clear）"
                        % NOON, "color": "white"})
    notice += ["tellraw @s " + text(msg), "scoreboard players set #notice %s 0" % OBJ_STATE]
    return setup, notice


def _welcome_line(home, n_lines, n_stations):
    return [
        {"text": "\n歡迎來到 1:1 台北捷運 The Taipei Metro, 1:1\n", "color": "gold", "bold": True},
        {"text": "整個路網照 OpenStreetMap 資料等比例重建：%d 條路線、%d 站，" % (n_lines, n_stations)
                 + "隧道、高架、車站與出入口都在真實位置。\n", "color": "white"},
        {"text": "The whole network, rebuilt at real scale from OpenStreetMap data: %d lines and %d stations, "
                 "with tunnels, viaducts, stations and exits where they really are.\n\n" % (n_lines, n_stations),
         "color": "gray"},
        {"text": "▶ 右鍵點月台上的告示牌就能坐到下一站（連點就連坐好幾站）\n", "color": "white"},
        {"text": "   Right-click a platform sign to ride to the next station; click again to keep going.\n",
         "color": "gray"},
        # Pause menu: when #minecraft:pause_screen_additions holds a single dialog,
        # the game uses its external_title as the button itself
        # (PauseScreen.getCustomAdditions); with more than one, they are grouped
        # under one custom options button.
        {"text": "▶ 路線圖：按「快速動作」鍵（預設 G）、暫停選單裡的「%s」，或輸入 /trigger %s\n"
                 % (MENU_TITLE, OBJ_MENU), "color": "white"},
        {"text": "   Route map: Quick Actions key (G), the Route Map button in the pause menu, or /trigger %s\n"
                 % OBJ_MENU, "color": "gray"},
        {"text": "[ 打開路線圖 Open route map ]", "color": "aqua", "bold": True,
         "click_event": {"action": "show_dialog", "dialog": fid(NW.MENU_DIALOG)},
         "hover_event": {"action": "show_text", "value": "點一下打開路線圖 Click to open"}},
        {"text": "\n你現在在 %s %s 的月台。 You are on the platform at %s.\n" % (home.code, home.name, home.en),
         "color": "white"},
        {"text": ATTRIBUTION, "color": "dark_gray"},
    ]


# ---------- Putting it together ----------

def _areas(net):
    """({station name: station number}, [(x0, y0, z0, dx, dy, dz, station number)]).

    One area per station box. Stations with the same name (the boxes of a
    transfer station) share a number, so walking back and forth in a transfer
    passage does not replay the name. A shared stacked station (Ximen) is one
    box for both lines and counts once.
    """
    group, areas, seen = {}, [], set()
    built = [s for s in net.values() if s.box is not None]
    rank = {r: i for i, r in enumerate(line_order({s.ref for s in built}))}
    for st in sorted(built, key=lambda s: (rank[s.ref], NW.code_sort_key(s.code))):
        g = group.setdefault(st.name, len(group) + 1)
        if id(st.box) in seen:
            continue
        seen.add(id(st.box))
        areas.append(station_area(st.box) + (g,))
    return group, areas


def build_spec(net, berths, colours, sights=None):
    """The whole datapack spec (plain data):

    functions     {path: [command lines]}      paths without the namespace, e.g. "ride/bl12_bl13"
    dialogs       {path: dialog dict}
    tags          {"function": {tag id: [function ids]}, "dialog": {tag id: [dialog ids]}}
    description   the description in pack.mcmeta (a text component)
    triggers      {n: go or sight function path}  trigger values of the route map and attraction list buttons (1..N, consecutive and unique)
    areas         [(x0, y0, z0, dx, dy, dz, station number)]  the arrival notice areas
    home          the go function path called on first join
    warnings      [str]                        problems such as id collisions (investigate any)
    sights        [attraction dict]            the result of attractions.datapack_entries() (also the input)
    """
    sights = list(sights or [])
    bidx = NW.berth_index(berths)
    fns, warnings = {}, []
    group, areas = _areas(net)
    codes_by_name = _codes_by_name(net)

    def put(path, lines):
        if path in fns:
            warnings.append("duplicate function id, kept the first: " + path)
            return
        fns[path] = lines

    def landed(st):
        """After a teleport, first record the destination as the last station
        visited, so the arrival notice does not overwrite the arrival screen's
        action bar (the title has already given the station name)."""
        return ["scoreboard players set @s %s %d" % (OBJ_AREA, group[st.name])]

    # ride/*
    for (ref, _a, _b), (st, to, slot) in sorted(
            _ride_targets(net, berths).items(),
            key=lambda kv: (NW.code_sort_key(kv[1][0].code), NW.code_sort_key(kv[1][1].code))):
        lz, le = line_name(ref)
        put(NW.ride_fn(st.code, to.code),
            _fn_header("%s %s %s → %s %s" % (le, st.code, st.en or st.name, to.code, to.en or to.name))
            + [tp_line(slot)] + landed(to) + chime_lines() + arrival_lines(net, to, slot, colours))

    # turn/*
    for b, slot in _turn_targets(berths):
        st = b.station
        c = colours.get(st.ref, "#FFFFFF")
        dr = slot.dest
        if dr is not None:
            tz_, te = _terminals(net, st.ref, dr)
            title = [{"text": "往 " + tz_, "color": c, "bold": True}]
            sub = [{"text": "To " + te, "color": "white"}]
        else:
            title = [{"text": st.name, "color": c, "bold": True}]
            sub = [{"text": st.en, "color": "white"}]
        put(NW.turn_fn(st.code, b.d),
            _fn_header("%s %s terminus: cross to the opposite platform" % (st.code, st.en or st.name))
            + [tp_line(slot)] + landed(st) + chime_lines()
            + ["title @s times 5 40 15",
               "title @s subtitle " + text(sub),
               "title @s title " + text(title),
               "title @s actionbar " + text([
                   {"text": "本站終點，已換到對面月台 ", "color": "yellow"},
                   {"text": "Terminus — you have crossed to the other platform", "color": "gray"}])])

    # go/*
    by_line = _stations_by_line(net, berths)
    refs = line_order(by_line)
    for ref in refs:
        for st in by_line[ref]:
            slot = NW.home_slot(bidx, st)
            put(NW.go_fn(st.code),
                _fn_header("Teleport to %s %s (%s)" % (st.code, st.en or st.name, line_name(ref)[1]))
                + [tp_line(slot)] + landed(st) + chime_lines() + arrival_lines(net, st, slot, colours))

    # Trigger values of the route map buttons: line order × code order, 1..N.
    trig, triggers = {}, {}
    for ref in refs:
        for st in by_line[ref]:
            n = len(trig) + 1
            trig[(st.ref, st.name)] = n
            triggers[n] = NW.go_fn(st.code)

    # sight/*: one function per spot of each attraction; the default viewpoints
    # get trigger values after the station buttons.
    sight_trig = {}
    for e in sights:
        for sp in e["spots"]:
            put(sight_fn(e["id"], sp["key"]),
                _fn_header("Attraction %s %s%s" % (e["name_zh"], e["name_en"], (": " + sp["en"]) if sp["key"] else ""))
                + [sight_tp_line(sp), "scoreboard players set @s %s 0" % OBJ_AREA]
                + sight_arrival_lines(e, sp))
        n = len(trig) + len(sight_trig) + 1
        sight_trig[e["id"]] = n
        triggers[n] = sight_fn(e["id"])

    near_sights = {}                 # Station name -> [(Chinese, English) names of attractions within walking distance] (station button tooltips).
    for e in sights:
        st = e.get("station")
        if st:
            near_sights.setdefault(st[0], []).append((e["name_zh"], e["name_en"]))
    dialogs = {NW.MENU_DIALOG: _menu_dialog(refs, by_line, colours, n_sights=len(sights))}
    if sights:
        dialogs[SIGHTS_DIALOG] = _sight_dialog(sights, sight_trig)
    for ref in refs:
        dialogs[NW.line_dialog(ref)] = _line_dialog(ref, by_line[ref], trig, codes_by_name, colours,
                                                    near_sights)

    # First-join landing spot.
    home = net.get(HOME)
    if home is None or home.box is None or NW.home_slot(bidx, home) is None:
        home = by_line[refs[0]][0] if refs else None
        warnings.append("%s %s not found; first join goes to %s instead"
                        % (HOME[0], HOME[1], home.code if home else "(none)"))

    setup, notice = _setup_fns()
    fns["sys/setup"] = setup
    fns["sys/notice"] = notice

    fns["sys/load"] = _fn_header("#minecraft:load: runs on every load and /reload") + [
        "scoreboard objectives add %s dummy" % OBJ_STATE,
        "scoreboard objectives add %s trigger %s" % (OBJ_GO, text({"text": "捷運傳送 MRT teleport"})),
        "scoreboard objectives add %s trigger %s" % (OBJ_MENU, text({"text": "捷運路線圖 MRT map"})),
        "scoreboard objectives add %s dummy" % OBJ_AREA,
        "scoreboard objectives add %s dummy" % OBJ_HERE,
        "execute unless score #setup %s matches %d.. run function %s" % (OBJ_STATE, SETUP_VERSION, fid("sys/setup")),
        "schedule function %s %dt replace" % (fid("sys/hud"), HUD_EVERY),
    ]
    fns["sys/tick"] = _fn_header("#minecraft:tick: cheap selectors only; the heavy work is in sys/hud "
                                 "(every %d ticks)" % HUD_EVERY) + [
        "execute as @a[tag=!%s] run function %s" % (TAG_JOINED, fid("sys/join")),
        "execute as @a[scores={%s=1..}] run function %s" % (OBJ_GO, fid("sys/go")),
        "execute as @a[scores={%s=1..}] run function %s" % (OBJ_MENU, fid("sys/menu")),
    ]
    join = _fn_header("First join: teleport to the platform at %s %s and show the welcome message"
                      % (home.code, home.en or home.name) if home else "First join")
    join += ["tag @s add " + TAG_JOINED,
             "scoreboard players enable @s " + OBJ_GO,
             "scoreboard players enable @s " + OBJ_MENU]
    if home is not None:
        n_st = sum(1 for s in net.values() if s.box is not None)
        join.append("function " + fid(NW.go_fn(home.code)))
        join.append("tellraw @s " + text(_welcome_line(home, len(refs), n_st)))
    join.append("execute if score #notice %s matches 1 run function %s" % (OBJ_STATE, fid("sys/notice")))
    fns["sys/join"] = join

    fns["sys/go"] = _fn_header("/trigger %s set <n>: the route map's station buttons" % OBJ_GO) + [
        "function " + fid("sys/go_dispatch"),
        "scoreboard players set @s %s 0" % OBJ_GO,
        "scoreboard players enable @s " + OBJ_GO,
    ]
    fns["sys/go_dispatch"] = _fn_header("Trigger value -> go function (values assigned by ride_plan.build_spec "
                                        "in line and code order)") + [
        "execute if score @s %s matches %d run return run function %s" % (OBJ_GO, n, fid(path))
        for n, path in sorted(triggers.items())
    ] + ["tellraw @s " + text({"text": "[台北捷運 Taipei Metro] 沒有這個站的編號 Unknown station number",
                               "color": "red"})]
    fns["sys/menu"] = _fn_header("/trigger %s: open the route map" % OBJ_MENU) + [
        "dialog show @s " + fid(NW.MENU_DIALOG),
        "scoreboard players set @s %s 0" % OBJ_MENU,
        "scoreboard players enable @s " + OBJ_MENU,
    ]

    # Arrival notice: scan every station area once every HUD_EVERY ticks.
    names = {g: n for n, g in group.items()}
    en_of = {}
    for st in net.values():
        en_of.setdefault(st.name, st.en)
    fns["sys/hud"] = _fn_header("Arrival notice: scan every %d ticks and show the station name in the action bar "
                                "once when a player enters a station area" % HUD_EVERY) + [
        "schedule function %s %dt replace" % (fid("sys/hud"), HUD_EVERY),
        "scoreboard players add #beat %s 1" % OBJ_STATE,
        "execute unless entity @a run return 0",
        "scoreboard players enable @a " + OBJ_GO,
        "scoreboard players enable @a " + OBJ_MENU,
        "scoreboard players set @a %s 0" % OBJ_HERE,
    ] + [
        "execute as @a[x=%d,y=%d,z=%d,dx=%d,dy=%d,dz=%d] run scoreboard players set @s %s %d"
        % (x0, y0, z0, dx, dy, dz, OBJ_HERE, g) for x0, y0, z0, dx, dy, dz, g in areas
    ] + [
        "execute as @a unless score @s %s = @s %s run function %s" % (OBJ_HERE, OBJ_AREA, fid("sys/hud_enter")),
    ]
    fns["sys/hud_enter"] = _fn_header("Area changed: record it, and show the station name on entering a station "
                                      "(leaving a station is recorded without a notice)") + [
        "scoreboard players operation @s %s = @s %s" % (OBJ_AREA, OBJ_HERE),
    ] + [
        "execute if score @s %s matches %d run return run title @s actionbar %s"
        % (OBJ_HERE, g, text(hud_text(names[g], en_of[names[g]], codes_by_name[names[g]], colours)))
        for g in sorted(names)
    ]

    return {
        "description": [{"text": "台北捷運 1:1 搭乘系統", "color": "gold"},
                        {"text": "\nTaipei MRT ride system · © OpenStreetMap contributors", "color": "gray"}],
        "functions": fns,
        "dialogs": dialogs,
        "tags": {
            "function": {"minecraft:load": [fid("sys/load")], "minecraft:tick": [fid("sys/tick")]},
            "dialog": {"minecraft:quick_actions": [fid(NW.MENU_DIALOG)],
                       "minecraft:pause_screen_additions": [fid(NW.MENU_DIALOG)]},
        },
        "triggers": triggers,
        "areas": areas,
        "home": NW.go_fn(home.code) if home is not None else None,
        "sights": {e["id"]: [sight_fn(e["id"], sp["key"]) for sp in e["spots"]] for e in sights},
        "warnings": warnings,
    }
