#!/usr/bin/env python3
"""Reads the ride system's datapack back from a world save, then has the real
Minecraft 26.2 load it and run it.

The generator says it wrote 593 functions; that does not count. This tool works
in two stages:

1. Read back from disk (no game needed)
  · pack.mcmeta parses, and DataPacks.Enabled in level.dat lists this datapack
  · every ride/*, turn/*, go/* and sight/* holds exactly one line
    ``tp @s x y z yaw pitch`` (the convention; see application/ride_plan.py),
    with numeric coordinates
  · every ``function mrt:…`` a function mentions, every ``show_dialog`` in a
    dialog, and every id in the two tags has a file
  · the buttons of each line's station list: trigger values 1..N are
    consecutive with no repeats, and the station code on each button has a
    matching go function
  · the signs in the save (near each station box): the function or dialog
    that each click command points to exists
  · every teleport landing point (within the built area) is standable (the
    rules in domain/walk), and a sign stands 1 to 3 blocks ahead in the
    direction faced

2. Let the game check (the GameTest server shipped in the game jar: headless,
   opens no port)
  A separate one-off test datapack, mrt_selftest (setup and teardown functions
  for the test environment), is generated and handed to
  ``net.minecraft.gametest.Main`` together with taipei_mrt:
  · the server loads both datapacks without any function, tag or dialog load
    errors
  · #minecraft:load really ran at startup: the nine initial world rules are
    set and the time is fixed at noon; running sys/load again (the same as
    /reload) does not overwrite rules changed afterwards
  · every ride/turn/go/sight function runs once in the game (a summoned marker
    serves as @s); afterwards its Pos and Rotation must match the tp line in
    the function file
  · every button of each line's station list: set the button's trigger value
    on a marker and run sys/go; the marker must land at the position of the go
    function for the station code on the button. The buttons, the dispatch
    table and the go functions are generated independently, so only this
    checks that they agree
  · world height: the datapack's dimension type takes effect, and a block can
    be placed at config.Y_MAX (y639)
  · first join (sys/join): adds the tag and teleports to R10 Taipei Main
    Station
  · station entry notice: the range scan in sys/hud is copied verbatim with @a
    replaced by @s; every teleport landing point must be judged to be in its
    station, and hud_enter must have run. Its schedule loop keeps ticking
    under advance_time=false (a heartbeat score)
  · signs: the block entities of ride signs in the save are placed back into
    the game unchanged with setblock (if the save has none yet, one is
    generated with World.sign), and their click_event must still be there when
    read back. Each dialog also gets a show_dialog sign. The game cannot decode
    that text if the dialog id does not exist, so a sign that keeps its
    click_event proves the dialog is really registered
  · negative controls (verifiers lie too): a deliberately broken function must
    leave its load error in the log; a sign that points to a nonexistent
    dialog must lose its click_event; a marker that was not teleported must
    not be judged to have landed correctly; a button value with no matching
    number must not move anyone; a marker high in the air must not be judged
    to be in any station

What this cannot prove: a real player right-clicking a sign (GameTest has no
players), what the dialog screen looks like, and whether the client asks for
confirmation when it sends /trigger. Those need the real game.

Usage:
    ./.venv/bin/python tools/check_datapack.py <save> [--no-game] [--no-signs] [--keep DIR]
"""
import argparse
import glob
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import nbtlib

from mrt import config

NS = config.DATAPACK_NS
TEST_NS = "mrt_selftest"
TP_RE = re.compile(r"^tp @s (-?\d+(?:\.\d+)?) (-?\d+(?:\.\d+)?) (-?\d+(?:\.\d+)?) "
                   r"(-?\d+(?:\.\d+)?) (-?\d+(?:\.\d+)?)$")
FN_REF_RE = re.compile(r"\bfunction (%s:[a-z0-9_./-]+)" % NS)
DIALOG_REF_RE = re.compile(r'"dialog":"(%s:[a-z0-9_./-]+)"|dialog show \S+ (%s:[a-z0-9_./-]+)' % (NS, NS))
TRIG_RE = re.compile(r"^trigger (\S+) set (\d+)$")

MC_DIR = os.path.expanduser("~/Library/Application Support/minecraft")
VERSION = "26.2"


# ====================================================================== Read the datapack back

class Pack:
    def __init__(self, root):
        self.root = root
        self.mcmeta = json.load(open(os.path.join(root, "pack.mcmeta"), encoding="utf-8"))
        self.functions, self.dialogs, self.tags = {}, {}, {}
        data = os.path.join(root, "data")
        fdir = os.path.join(data, NS, "function")
        for fp in glob.glob(os.path.join(fdir, "**", "*.mcfunction"), recursive=True):
            path = os.path.relpath(fp, fdir)[:-len(".mcfunction")].replace(os.sep, "/")
            self.functions[path] = open(fp, encoding="utf-8").read().splitlines()
        ddir = os.path.join(data, NS, "dialog")
        for fp in glob.glob(os.path.join(ddir, "**", "*.json"), recursive=True):
            path = os.path.relpath(fp, ddir)[:-len(".json")].replace(os.sep, "/")
            self.dialogs[path] = json.load(open(fp, encoding="utf-8"))
        for fp in glob.glob(os.path.join(data, "*", "tags", "*", "**", "*.json"), recursive=True):
            rel = os.path.relpath(fp, data).split(os.sep)
            tns, kind, tpath = rel[0], rel[2], "/".join(rel[3:])[:-len(".json")]
            self.tags[(kind, "%s:%s" % (tns, tpath))] = json.load(open(fp, encoding="utf-8"))["values"]

    def tp(self, path):
        """The single tp line the convention requires in a function: (x, y, z,
        yaw, pitch); None unless there is exactly one."""
        hits = [TP_RE.match(ln) for ln in self.functions.get(path, ()) if ln.startswith("tp ")]
        if len(hits) != 1 or hits[0] is None:
            return None
        return tuple(float(g) for g in hits[0].groups())


def line_buttons(pack):
    """[(dialog path, station code on the button, trigger objective, trigger value)]"""
    out = []
    for path, d in sorted(pack.dialogs.items()):
        if not path.startswith("line/"):
            continue
        for a in d.get("actions", ()):
            lab = a.get("label")
            code = (lab[0]["text"] if isinstance(lab, list) else lab.get("text", "")).strip()
            m = TRIG_RE.match(a.get("action", {}).get("command", ""))
            out.append((path, code, m.group(1) if m else None, int(m.group(2)) if m else None))
    return out


SIGHT_NAME_RE = re.compile(r"^# Attraction (\S+)")
TP_KINDS = ("ride", "turn", "go", "sight")


def sight_buttons(pack):
    """The buttons of the attraction list: [(Chinese attraction name, trigger
    objective, trigger value, matching sight function)].

    A button carries only a name. The function is matched back through the
    header line "# Attraction <Chinese name> ..." of sight/<id>; a sub-spot's
    header adds ": <spot>", so it is skipped. The dialog and the
    functions are generated separately by ride_plan, and only if they match
    does a button send the player to that attraction."""
    by_name = {}
    for path, lines in pack.functions.items():
        if path.startswith("sight/") and lines:
            m = SIGHT_NAME_RE.match(lines[0])
            if m and ": " not in lines[0]:
                by_name[m.group(1)] = path
    out = []
    d = pack.dialogs.get("sights")
    for a in (d or {}).get("actions", ()):
        lab = a.get("label")
        name = (lab[-1]["text"] if isinstance(lab, list) else lab.get("text", "")).strip()
        m = TRIG_RE.match(a.get("action", {}).get("command", ""))
        out.append((name, m.group(1) if m else None, int(m.group(2)) if m else None, by_name.get(name)))
    return out


def fn_code(code):
    return "".join(ch for ch in code.lower() if ch.isalnum() or ch == "_")


def game_data_version(mc_dir, version):
    """The datapack version (major, minor) from version.json in the game jar;
    None if the jar is not found."""
    import zipfile
    jar = os.path.join(mc_dir, "versions", version, version + ".jar")
    if not os.path.exists(jar):
        return None
    with zipfile.ZipFile(jar) as z:
        pv = json.loads(z.read("version.json"))["pack_version"]
    return pv["data_major"], pv["data_minor"]


def format_range(fmt):
    """min_format / max_format in pack.mcmeta -> ((major, minor), (major, minor)).

    Follows the game's PackFormat rules: an integer means (n, 0) as the lower
    bound and (n, any minor version) as the upper bound.
    """
    def one(v, top):
        if isinstance(v, int):
            return (v, 1 << 31) if top else (v, 0)
        return (int(v[0]), int(v[1]) if len(v) > 1 else (1 << 31 if top else 0))
    return one(fmt["min_format"], False), one(fmt["max_format"], True)


def static_checks(save, pack, problems, say, game_version=None):
    """Stage 1: the checks read back from disk. problems collects problem strings.

    game_version is the game's datapack version (major, minor). The GameTest
    server loads a datapack whose version range does not match without a word
    (tested), so the range can only be checked here, against version.json.
    """
    fmt = pack.mcmeta.get("pack", {})
    say(f"pack.mcmeta: min_format={fmt.get('min_format')} max_format={fmt.get('max_format')}")
    if "min_format" not in fmt or "max_format" not in fmt:
        problems.append("pack.mcmeta lacks min_format/max_format (26.2 uses these two fields)")
    elif game_version is not None:
        lo, hi = format_range(fmt)
        if lo <= tuple(game_version) <= hi:
            say(f"  The game's datapack version {game_version[0]}.{game_version[1]} "
                f"(version.json in the jar) is within the range")
        else:
            problems.append(f"The pack.mcmeta range {fmt['min_format']} to {fmt['max_format']} does not "
                            f"include the game's datapack version {game_version[0]}.{game_version[1]}")

    lvl = nbtlib.load(os.path.join(save, "level.dat"))
    enabled = [str(s) for s in lvl["Data"]["DataPacks"]["Enabled"]]
    want = "file/" + os.path.basename(pack.root)
    say(f"level.dat DataPacks.Enabled = {enabled}")
    if want not in enabled:
        problems.append(f"DataPacks.Enabled in level.dat does not list {want}")

    kinds = {k: 0 for k in TP_KINDS}
    for path in sorted(pack.functions):
        top = path.split("/")[0]
        if top in kinds:
            kinds[top] += 1
            n_tp = sum(1 for ln in pack.functions[path] if ln.startswith("tp "))
            if n_tp != 1 or pack.tp(path) is None:
                problems.append(f"{path}: expected exactly one tp line with absolute coordinates "
                                f"(found {n_tp})")
    say("%d functions: ride %d, turn %d, go %d, sight %d, other %d" % (
        len(pack.functions), kinds["ride"], kinds["turn"], kinds["go"], kinds["sight"],
        len(pack.functions) - sum(kinds.values())))

    fn_ids = {"%s:%s" % (NS, p) for p in pack.functions}
    dlg_ids = {"%s:%s" % (NS, p) for p in pack.dialogs}
    blob_dialogs = json.dumps(pack.dialogs, ensure_ascii=False, separators=(",", ":"))
    missing = set()
    for path, lines in pack.functions.items():
        for ln in lines:
            for ref in FN_REF_RE.findall(ln):
                if ref not in fn_ids:
                    missing.add(f"function {ref} called by {path}")
            for a, b in DIALOG_REF_RE.findall(ln):
                if (a or b) not in dlg_ids:
                    missing.add(f"dialog {a or b} opened by {path}")
    for a, b in DIALOG_REF_RE.findall(blob_dialogs):
        if (a or b) not in dlg_ids:
            missing.add(f"show_dialog target {a or b} in a dialog")
    for (kind, tag), values in pack.tags.items():
        pool = fn_ids if kind == "function" else dlg_ids
        for v in values:
            if v.startswith(NS + ":") and v not in pool:
                missing.add(f"{v} in tag #{tag}")
    for m in sorted(missing):
        problems.append("Missing: " + m)
    for kind, tag in (("function", "minecraft:load"), ("function", "minecraft:tick"),
                      ("dialog", "minecraft:quick_actions"),
                      ("dialog", "minecraft:pause_screen_additions")):
        if not pack.tags.get((kind, tag)):
            problems.append(f"No #{tag} ({kind} tag)")

    btn = line_buttons(pack)
    sbtn = sight_buttons(pack)
    vals = [n for _, _, _, n in btn] + [n for _, _, n, _ in sbtn]
    say(f"{len(pack.dialogs)} dialogs; {len(btn)} buttons in the line station lists, "
        f"{len(sbtn)} in the attraction list")
    if any(v is None for v in vals):
        problems.append("Some station list or attraction buttons are not /trigger <objective> set <n>")
    elif sorted(vals) != list(range(1, len(vals) + 1)):
        problems.append("The trigger values of the station list and attraction buttons are not 1..N "
                        "without gaps or repeats")
    for name, _, _, path in sbtn:
        if path is None:
            problems.append(f"Attraction list button {name} has no matching sight function")
    for path, code, _, _ in btn:
        if ("go/" + fn_code(code)) not in pack.functions:
            problems.append(f"Button {code} in {path} has no matching go function")
    return btn


# ====================================================================== Read the signs back

def _region_chunks(save):
    rdir = config.region_dir(save)
    return rdir, sorted(glob.glob(os.path.join(rdir, "r.*.*.mca")))


def scan_signs(save, targets, radius=48):
    """Reads back the sign block entities near each tp destination (±radius
    blocks).

    Ride signs all stand in the row of platform screen doors, at most 30 to 40
    meters from the primary position. A tp destination is a primary position,
    so scanning near the destinations covers every sign without decompressing
    the whole 1 GB save. Returns [(x, y, z, raw Compound)].
    """
    want = {}
    for x, _, z in targets:
        for cx in range((int(x) - radius) >> 4, ((int(x) + radius) >> 4) + 1):
            for cz in range((int(z) - radius) >> 4, ((int(z) + radius) >> 4) + 1):
                want.setdefault((cx >> 5, cz >> 5), set()).add((cx, cz))
    rdir = config.region_dir(save)
    out = []
    for (rx, rz), chunks in sorted(want.items()):
        p = os.path.join(rdir, f"r.{rx}.{rz}.mca")
        if not os.path.exists(p):
            continue
        raw = open(p, "rb").read()
        for cx, cz in sorted(chunks):
            i = (cx & 31) + (cz & 31) * 32
            off = int.from_bytes(raw[i * 4:i * 4 + 3], "big")
            if off == 0:
                continue
            q = off * 4096
            ln = int.from_bytes(raw[q:q + 4], "big")
            blob = raw[q + 5:q + 4 + ln]
            root = nbtlib.File.parse(io.BytesIO(zlib.decompress(blob) if raw[q + 4] == 2 else blob))
            root = root[""] if "" in root else root
            for be in root.get("block_entities", ()):
                if str(be.get("id", "")) in ("minecraft:sign", "minecraft:hanging_sign"):
                    out.append((int(be["x"]), int(be["y"]), int(be["z"]), be))
    return out


def click_of(be):
    for m in be.get("front_text", {}).get("messages", ()):
        if isinstance(m, dict) and "click_event" in m:
            return {str(k): str(v) for k, v in m["click_event"].items()}
    return None


def sign_checks(save, pack, problems, say):
    """Where each sign in the save leads when clicked: every function and dialog
    must exist. Returns the samples picked for the game to test."""
    targets = [pack.tp(p)[:3] for p in pack.functions
               if p.split("/")[0] in ("ride", "turn", "go") and pack.tp(p)]
    t0 = time.time()
    signs = scan_signs(save, targets)
    clicks = [(x, y, z, be, click_of(be)) for x, y, z, be in signs]
    with_click = [c for c in clicks if c[4] is not None]
    say(f"Signs: read back {len(signs)} near tp destinations, {len(with_click)} with a click action "
        f"({time.time() - t0:.0f}s)")
    fn_ids = {"%s:%s" % (NS, p) for p in pack.functions}
    dlg_ids = {"%s:%s" % (NS, p) for p in pack.dialogs}
    n_run = n_dlg = 0
    bad = []
    samples = {}
    for x, y, z, be, ck in with_click:
        act = ck.get("action")
        if act == "run_command":
            n_run += 1
            cmd = ck.get("command", "").lstrip("/")
            m = re.match(r"^function (\S+)$", cmd)
            if not m or m.group(1) not in fn_ids:
                bad.append(f"({x},{y},{z}) run_command {cmd!r}")
            else:
                kind = m.group(1).split(":")[1].split("/")[0]
                samples.setdefault(kind, (x, y, z, be))
        elif act == "show_dialog":
            n_dlg += 1
            if ck.get("dialog") not in dlg_ids:
                bad.append(f"({x},{y},{z}) show_dialog {ck.get('dialog')!r}")
            else:
                samples.setdefault("dialog", (x, y, z, be))
    say(f"  run_command {n_run}, show_dialog {n_dlg}; {len(bad)} point to something missing")
    for b in bad[:20]:
        problems.append("A sign's click points to something missing: " + b)
    return samples


def _chunk_table(save):
    """{(cx, cz)}: the chunks actually written to the save (reads only the header
    of each region file)."""
    have = set()
    for p in glob.glob(os.path.join(config.region_dir(save), "r.*.*.mca")):
        _, rx, rz, _ = os.path.basename(p).split(".")
        head = open(p, "rb").read(4096)
        for i in range(1024):
            if int.from_bytes(head[i * 4:i * 4 + 3], "big"):
                have.add((int(rx) * 32 + i % 32, int(rz) * 32 + i // 32))
    return have


def landing_checks(save, pack, problems, say):
    """The landing point of each ride/turn/go: within the built area it must be
    standable (the rules in domain/walk), and a sign (or platform screen door
    glass not yet replaced by a sign) must stand 1 to 3 blocks ahead in the
    direction faced.

    A world built with --bbox covers only a small area; a landing point whose
    chunk was not written is skipped (that station was not built).
    """
    import math
    from mrt.domain import walk
    from mrt.infrastructure.savereader import read_volume
    have = _chunk_table(save)
    targets = []
    for path in sorted(pack.functions):
        if path.split("/")[0] in ("ride", "turn", "go") and pack.tp(path):
            x, y, z, yaw, _ = pack.tp(path)
            x, y, z = int(math.floor(x)), int(y), int(math.floor(z))
            if (x >> 4, z >> 4) in have:
                targets.append((path, x, y, z, yaw))
    cells = {}
    for t in targets:
        cells.setdefault((t[1] >> 7, t[3] >> 7), []).append(t)
    n_ok = n_sign = n_pane = 0
    bad = []
    for grp in cells.values():
        xs, ys, zs = [t[1] for t in grp], [t[2] for t in grp], [t[3] for t in grp]
        vol = read_volume(save, min(xs) - 4, min(ys) - 1, min(zs) - 4,
                          max(xs) + 4, max(ys) + 2, max(zs) + 4, verbose=False)
        for path, x, y, z, yaw in grp:
            if walk.standable(vol.get, x, y, z):
                n_ok += 1
            else:
                bad.append("%s lands at (%d,%d,%d), which is not standable: feet %s / head %s / below %s" % (
                    path, x, y, z, vol.get(x, y, z), vol.get(x, y + 1, z), vol.get(x, y - 1, z)))
            fx, fz = -math.sin(math.radians(yaw)), math.cos(math.radians(yaw))
            ahead = [vol.get(x + int(round(k * fx)), y, z + int(round(k * fz))) for k in (1, 2, 3)]
            if any("sign" in b for b in ahead):
                n_sign += 1
            elif any("pane" in b for b in ahead):
                n_pane += 1
    say(f"Teleport landing points: {len(targets)} in the built area, {n_ok} standable; "
        f"{n_sign} with a sign within 3 blocks ahead, {n_pane} with only platform screen door glass")
    problems.extend(bad[:20])
    if len(bad) > 20:
        problems.append("…and %d more landing points that are not standable" % (len(bad) - 20))


# ====================================================================== In-game tests

def find_java(mc_dir, version):
    v = json.load(open(os.path.join(mc_dir, "versions", version, version + ".json"), encoding="utf-8"))
    comp = v.get("javaVersion", {}).get("component", "")
    for pat in ("runtime/%s/*/%s/jre.bundle/Contents/Home/bin/java" % (comp, comp),
                "runtime/%s/*/%s/bin/java" % (comp, comp)):
        hits = sorted(glob.glob(os.path.join(mc_dir, pat)))
        if hits:
            return hits[0]
    return shutil.which("java")


def game_classpath(mc_dir, version):
    """Launcher version file -> classpath (the server needs no native libraries,
    so only jars are collected)."""
    v = json.load(open(os.path.join(mc_dir, "versions", version, version + ".json"), encoding="utf-8"))
    cp = []
    for lib in v["libraries"]:
        ok = True
        for r in lib.get("rules", ()):
            hit = "os" not in r or r["os"].get("name") == "osx"
            if r["action"] == "allow":
                ok = hit
            elif hit:
                ok = False
        art = lib.get("downloads", {}).get("artifact")
        if ok and art:
            p = os.path.join(mc_dir, "libraries", art["path"])
            if os.path.exists(p):
                cp.append(p)
    cp.append(os.path.join(mc_dir, "versions", version, version + ".jar"))
    return ":".join(cp)


def _snbt(tag):
    return tag.snbt()


def pos_check(name, tp, report=True):
    """After the marker runs, its Pos/Rotation must equal the tp line (x, y and z
    multiplied by 10 and rounded; angles within ±0.1°). The result goes to #hit
    (1 = correct); report=False prints no FAIL (a negative control judges the
    result itself)."""
    x, y, z, yaw, pitch = tp
    r = int(round(yaw * 10))
    shift = 3600 if 2 <= (r % 3600) <= 3597 else 5400        # Keep the tolerance from wrapping across 0°.
    er = (r + shift) % 3600
    ep = int(round(pitch * 10))
    return [
        "scoreboard players set #hit mrt_t 0",
        "execute store result score #x mrt_t run data get entity @s Pos[0] 10",
        "execute store result score #y mrt_t run data get entity @s Pos[1] 10",
        "execute store result score #z mrt_t run data get entity @s Pos[2] 10",
        "execute store result score #r mrt_t run data get entity @s Rotation[0] 10",
        "execute store result score #p mrt_t run data get entity @s Rotation[1] 10",
        "scoreboard players add #r mrt_t %d" % shift,
        "scoreboard players operation #r mrt_t %= #c3600 mrt_t",
        "execute if score #x mrt_t matches %d if score #y mrt_t matches %d if score #z mrt_t matches %d "
        "if score #r mrt_t matches %d..%d if score #p mrt_t matches %d..%d run scoreboard players set #hit mrt_t 1"
        % (int(round(x * 10)), int(round(y * 10)), int(round(z * 10)), er - 1, er + 1, ep - 1, ep + 1),
    ] + (["execute if score #hit mrt_t matches 0 run say MRTCHK FAIL %s expected %.1f %d %.1f %.1f %.1f"
          % (name, x, y, z, yaw, pitch)] if report else [])


def ok_fail(name, cond, want=True):
    """cond is an execute if condition (without the "if"): ok when it holds, FAIL
    when it does not (the reverse when want=False)."""
    yes, no = ("if", "unless") if want else ("unless", "if")
    return ["execute %s %s run say MRTCHK ok %s" % (yes, cond, name),
            "execute %s %s run say MRTCHK FAIL %s" % (no, cond, name)]


def build_selftest(pack, btn, samples, out_dir, rules):
    """Generates the mrt_selftest datapack. Returns (expected named checks,
    {count name: expected value}, number of function files)."""
    from mrt.infrastructure import datapack as DP
    root = os.path.join(out_dir, TEST_NS)
    fdir = os.path.join(root, "data", TEST_NS, "function")
    files = {}
    expect = []

    def fn(path, lines):
        files[path] = lines

    # ---- Test environment and test instance ----
    meta = {"pack": {"description": "One-off in-game test for taipei_mrt (generated by tools/check_datapack.py)",
                     "min_format": DP.PACK_MIN_FORMAT, "max_format": DP.PACK_MAX_FORMAT}}
    env = {"type": "minecraft:function", "setup": TEST_NS + ":setup", "teardown": TEST_NS + ":teardown"}
    inst = {"type": "minecraft:function", "function": "minecraft:always_pass",
            "environment": TEST_NS + ":env", "structure": "minecraft:empty",
            "max_ticks": 1, "setup_ticks": 100, "required": True}

    probes = [p for p in sorted(pack.functions) if p.split("/")[0] in TP_KINDS]
    setup = ["say MRTCHK begin",
             "scoreboard objectives add mrt_t dummy",
             "scoreboard players set #c3600 mrt_t 3600",
             "scoreboard players set #ok mrt_t 0",
             "scoreboard players set #tok mrt_t 0",
             "forceload add 0 0",
             # The station entry notice check scans hundreds of times in one go,
             # each time with over a hundred selectors.
             "gamerule max_command_sequence_length 2000000"]
    # The station entry notice check runs in teardown (a new execution, so the
    # command limit raised above takes effect).
    hud_targets = []
    for path in probes:
        tp = pack.tp(path)
        g = next((int(ln.split()[-1]) for ln in pack.functions[path]
                  if ln.startswith("scoreboard players set @s %s.area " % NS)), None)
        if tp is not None and g is not None:
            hud_targets.append((path, tp, g))
    # 1. Whether #minecraft:load ran at startup (nothing has been called yet).
    setup += ok_fail("load_ran_at_startup", "score #setup %s.state matches 1.." % NS)
    expect.append("load_ran_at_startup")
    setup.append("execute store result score #beat0 mrt_t run scoreboard players get #beat %s.state" % NS)
    # 2. Every scoreboard objective exists.
    for obj in ("state", "go", "menu", "area", "here"):
        setup.append("execute store success score #v mrt_t run scoreboard players set #probe %s.%s 0" % (NS, obj))
        setup += ok_fail("objective_%s" % obj, "score #v mrt_t matches 1")
        expect.append("objective_%s" % obj)
    # 3. Initial world settings.
    for rule, val in rules:
        want = {"true": 1, "false": 0}.get(val, None)
        want = int(val) if want is None else want
        setup.append("execute store result score #v mrt_t run gamerule %s" % rule)
        setup += ok_fail("rule_%s=%s" % (rule, val), "score #v mrt_t matches %d" % want)
        expect.append("rule_%s=%s" % (rule, val))
    setup.append("execute store result score #v mrt_t run time query time")
    setup += ok_fail("time_noon", "score #v mrt_t matches 6000")
    expect.append("time_noon")
    # 4. /reload (running sys/load again) must not overwrite rules changed
    #    afterwards.
    setup += ["gamerule keep_inventory false",
              "function %s:sys/load" % NS,
              "execute store result score #v mrt_t run gamerule keep_inventory"]
    setup += ok_fail("reload_keeps_player_rules", "score #v mrt_t matches 0")
    setup.append("gamerule keep_inventory true")
    expect.append("reload_keeps_player_rules")
    # 5. Every ride/turn/go runs once in the game.
    for k, path in enumerate(probes):
        setup.append("execute positioned 0 100 0 summon minecraft:marker run function %s:p/%d" % (TEST_NS, k))
        fn("p/%d" % k, ["function %s:%s" % (NS, path)] + pos_check(path, pack.tp(path))
           + ["scoreboard players operation #ok mrt_t += #hit mrt_t", "kill @s"])
    # 6. Every station list button: trigger value -> sys/go -> the position of
    #    the go function for the station code on the button.
    for path, code, obj, n in btn:
        tp = pack.tp("go/" + fn_code(code))
        if tp is None or obj is None:
            continue
        setup.append("execute positioned 0 100 0 summon minecraft:marker run function %s:t/%d" % (TEST_NS, n))
        fn("t/%d" % n, ["scoreboard players set @s %s %d" % (obj, n),
                        "function %s:sys/go" % NS]
           + pos_check("button_%s_%s" % (path.replace("/", "_"), code), tp)
           + ["execute unless score @s %s matches 0 run scoreboard players set #hit mrt_t 0" % obj,
              "execute unless score @s %s matches 0 run say MRTCHK FAIL trigger_not_reset_%d" % (obj, n),
              "scoreboard players operation #tok mrt_t += #hit mrt_t", "kill @s"])
    # 6b. Every attraction list button: trigger value -> sys/go -> the position
    #     of that attraction's sight function.
    for name, obj, n, path in sight_buttons(pack):
        tp = pack.tp(path) if path else None
        if tp is None or obj is None:
            continue
        setup.append("execute positioned 0 100 0 summon minecraft:marker run function %s:t/%d" % (TEST_NS, n))
        fn("t/%d" % n, ["scoreboard players set @s %s %d" % (obj, n),
                        "function %s:sys/go" % NS]
           + pos_check("button_sight_%s" % path.split("/")[-1], tp)
           + ["execute unless score @s %s matches 0 run scoreboard players set #hit mrt_t 0" % obj,
              "execute unless score @s %s matches 0 run say MRTCHK FAIL trigger_not_reset_%d" % (obj, n),
              "scoreboard players operation #tok mrt_t += #hit mrt_t", "kill @s"])
    # Negative control: a marker that ran no teleport must not be judged to be at
    # the position of a go function.
    first_go = next((p for p in probes if p.startswith("go/")), None)
    if first_go:
        setup.append("execute positioned 0 100 0 summon minecraft:marker run function %s:neg_tp" % TEST_NS)
        fn("neg_tp", pos_check("negative_control_tp", pack.tp(first_go), report=False)
           + ok_fail("negative_control_tp", "score #hit mrt_t matches 0") + ["kill @s"])
        expect.append("negative_control_tp")
    # Negative control: a trigger value with no matching number -> no movement,
    # and the value is reset.
    objs = {obj for _, _, obj, _ in btn if obj}
    if len(objs) == 1:
        obj = objs.pop()
        setup.append("execute positioned 0 100 0 summon minecraft:marker run function %s:neg_trig" % TEST_NS)
        n_all = len(btn) + len(sight_buttons(pack))       # Attraction buttons follow the station buttons.
        fn("neg_trig", ["scoreboard players set @s %s %d" % (obj, n_all + 1), "function %s:sys/go" % NS]
           + ok_fail("trigger_unknown_value_stays", "entity @s[x=0.5,y=100,z=0.5,distance=..0.01]")
           + ok_fail("trigger_unknown_value_reset", "score @s %s matches 0" % obj) + ["kill @s"])
        expect += ["trigger_unknown_value_stays", "trigger_unknown_value_reset"]
    # 6c. World height: the datapack's dimension_type/overworld.json raises the
    #     overworld to config.Y_MAX (the spire of Taipei 101 is at y≈580). If it
    #     has no effect, no block can be placed above the vanilla y319.
    top = config.Y_MAX
    setup += ["setblock 0 %d 0 minecraft:gold_block" % top]
    setup += ok_fail("world_height_y%d" % top, "block 0 %d 0 minecraft:gold_block" % top)
    setup += ["setblock 0 %d 0 minecraft:air" % top]
    expect.append("world_height_y%d" % top)
    # 7. First join.
    home = None
    for ln in pack.functions.get("sys/join", ()):
        m = re.match(r"^function %s:(go/\S+)$" % NS, ln)
        if m:
            home = m.group(1)
    setup.append("execute positioned 0 100 0 summon minecraft:marker run function %s:join" % TEST_NS)
    join = ["function %s:sys/join" % NS]
    join += ok_fail("join_tag", "entity @s[tag=%s.joined]" % NS)
    expect.append("join_tag")
    if home and pack.tp(home):
        join += pos_check("join_home_" + home.replace("/", "_"), pack.tp(home))
        join += ["execute if score #hit mrt_t matches 1 run say MRTCHK ok join_home_%s" % home.replace("/", "_")]
        expect.append("join_home_" + home.replace("/", "_"))
    fn("join", join + ["kill @s"])
    # 8. /trigger mrt.menu: reset after dispatch (dialog show fails on a marker,
    #    which does not matter).
    setup.append("execute positioned 0 100 0 summon minecraft:marker run function %s:menu" % TEST_NS)
    fn("menu", ["scoreboard players set @s %s.menu 1" % NS, "function %s:sys/menu" % NS]
       + ok_fail("menu_trigger_reset", "score @s %s.menu matches 0" % NS) + ["kill @s"])
    expect.append("menu_trigger_reset")
    # 9. Counts.
    setup += ["execute store result storage %s:r tp int 1 run scoreboard players get #ok mrt_t" % TEST_NS,
              "execute store result storage %s:r trig int 1 run scoreboard players get #tok mrt_t" % TEST_NS,
              "function %s:report with storage %s:r" % (TEST_NS, TEST_NS)]
    fn("report", ["$say MRTCHK count tp=$(tp) trig=$(trig)"])
    fn("setup", setup)

    # ---- Teardown: after setup_ticks (100 ticks). The chunk is loaded, and the schedule has run a few times ----
    td = ["say MRTCHK teardown",
          "execute store result score #beat1 mrt_t run scoreboard players get #beat %s.state" % NS,
          "scoreboard players operation #beat1 mrt_t -= #beat0 mrt_t"]
    td += ok_fail("hud_heartbeat", "score #beat1 mrt_t matches 2..")
    expect.append("hud_heartbeat")
    td += ok_fail("chunk_loaded", "loaded 0 100 0")
    expect.append("chunk_loaded")
    td.append("fill 0 99 0 15 99 15 minecraft:stone")
    sign_list = []                       # (name, block state, block entity Compound, expected to keep click_event)
    for kind, (x, y, z, be, state, src) in sorted(samples.items()):
        sign_list.append(("sign_%s_%s" % (kind, src), state, be, True))
    for path in sorted(pack.dialogs):
        sign_list.append(("dialog_sign_%s" % path.replace("/", "_"), "minecraft:oak_sign[rotation=0]",
                          _dialog_sign("%s:%s" % (NS, path)), True))
    sign_list.append(("negative_control_unknown_dialog", "minecraft:oak_sign[rotation=0]",
                      _dialog_sign("%s:no_such_dialog" % NS), False))
    for i, (name, state, be, keep) in enumerate(sign_list):
        x, y, z = 1 + (i % 7) * 2, 100, 2 + (i // 7) * 2
        body = nbtlib.tag.Compound({k: v for k, v in be.items() if k not in ("id", "x", "y", "z", "keepPacked")})
        m = re.search(r"facing=(\w+)", state)
        if m and "wall" in state:
            dx, dz = {"south": (0, -1), "north": (0, 1), "east": (-1, 0), "west": (1, 0)}[m.group(1)]
            td.append("setblock %d %d %d minecraft:stone" % (x + dx, y, z + dz))
        td.append("setblock %d %d %d %s%s" % (x, y, z, state, _snbt(body)))
        ck = None
        for msg in be["front_text"]["messages"]:
            if isinstance(msg, dict) and "click_event" in msg:
                ck = msg["click_event"]
        pattern = "{is_waxed:1b,front_text:{messages:[{click_event:%s}]}}" % _snbt(ck)
        td += ok_fail(name, "data block %d %d %d %s" % (x, y, z, pattern), want=keep)
        expect.append(name)
    # Station entry notice: copy the scan in sys/hud verbatim, replacing only @a
    # with @s (GameTest has no players; @s with range arguments compares the
    # executor's own coordinates, so no chunk needs to be loaded). For each
    # teleport destination, tp a marker there, clear its mrt.area and scan once.
    # It must fall within that station's range (mrt.here = the station number
    # recorded in the function), and hud_enter must have run (mrt.area follows).
    scan = []
    for ln in pack.functions.get("sys/hud", ()):
        if ("%s.here" % NS) in ln or "sys/hud_enter" in ln:
            scan.append(ln.replace("@a[", "@s[").replace("@a ", "@s "))
    fn("hud_scan", scan)
    td.append("scoreboard players set #hok mrt_t 0")
    for k, (path, tp, g) in enumerate(hud_targets):
        td.append("execute positioned 0 100 0 summon minecraft:marker run function %s:h/%d" % (TEST_NS, k))
        fn("h/%d" % k, ["tp @s %.1f %d %.1f" % tp[:3],
                        "scoreboard players reset @s %s.area" % NS,
                        "function %s:hud_scan" % TEST_NS,
                        "execute if score @s %s.here matches %d if score @s %s.area matches %d "
                        "run scoreboard players add #hok mrt_t 1" % (NS, g, NS, g),
                        "execute unless score @s %s.here matches %d run say MRTCHK FAIL hud_area_%s"
                        % (NS, g, path.replace("/", "_")),
                        "kill @s"])
    # Negative control: a point outside every station (high in the air at y=300)
    # must not be judged to be in any station.
    td.append("execute positioned 0 300 0 summon minecraft:marker run function %s:h_neg" % TEST_NS)
    fn("h_neg", ["function %s:hud_scan" % TEST_NS]
       + ok_fail("negative_control_hud_outside", "score @s %s.here matches 0" % NS) + ["kill @s"])
    expect.append("negative_control_hud_outside")
    td += ["execute store result storage %s:r hud int 1 run scoreboard players get #hok mrt_t" % TEST_NS,
           "function %s:report_hud with storage %s:r" % (TEST_NS, TEST_NS)]
    fn("report_hud", ["$say MRTCHK count hud=$(hud)"])
    td.append("forceload remove 0 0")
    fn("teardown", td)
    # Negative control: a deliberately broken function, whose load error must
    # appear in the log.
    fn("broken", ["this_is_not_a_command 1 2 3"])

    os.makedirs(root, exist_ok=True)
    json.dump(meta, open(os.path.join(root, "pack.mcmeta"), "w", encoding="utf-8"), ensure_ascii=False)
    for sub, obj in (("test_environment/env.json", env), ("test_instance/datapack.json", inst)):
        p = os.path.join(root, "data", TEST_NS, sub)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        json.dump(obj, open(p, "w", encoding="utf-8"))
    for path, lines in files.items():
        p = os.path.join(fdir, path + ".mcfunction")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    n_btn = sum(1 for path, code, obj, n in btn if pack.tp("go/" + fn_code(code)) and obj)
    n_btn += sum(1 for name, obj, n, path in sight_buttons(pack) if path and pack.tp(path) and obj)
    return expect, {"tp": len(probes), "trig": n_btn, "hud": len(hud_targets)}, len(files)


def _dialog_sign(dialog):
    from nbtlib.tag import Byte, Compound, List, String
    msgs = [Compound({"text": String("路線圖"),
                      "click_event": Compound({"action": String("show_dialog"), "dialog": String(dialog)})})]
    msgs += [Compound({"text": String("")}) for _ in range(3)]
    return Compound({"is_waxed": Byte(1),
                     "front_text": Compound({"messages": List[Compound](msgs), "color": String("black"),
                                             "has_glowing_text": Byte(0)}),
                     "back_text": Compound({"messages": List[Compound]([Compound({"text": String("")})] * 4),
                                            "color": String("black"), "has_glowing_text": Byte(0)})})


def synth_samples(pack):
    """When the save has no ride signs yet, makes three with the generator's own
    World.sign (the same code that builds the world)."""
    from mrt.infrastructure.mcworld import World
    w = World(tempfile.mkdtemp(prefix="mrt_sign_"))
    ride = next(p for p in sorted(pack.functions) if p.startswith("ride/"))
    turn = next((p for p in sorted(pack.functions) if p.startswith("turn/")), None)
    specs = [("ride", "standing", (0, 1), dict(command="function %s:%s" % (NS, ride)),
              [{"text": "往 下一站", "color": "#007EC7", "bold": True}, "Next station", "", "右鍵搭車"]),
             ("dialog", "wall", (0, 1), dict(dialog="%s:network" % NS),
              [{"text": "路線圖", "bold": True}, "Route map", "", ""])]
    if turn:
        specs.append(("turn", "wall", (1, 0), dict(command="function %s:%s" % (NS, turn)),
                      [{"text": "本站終點", "color": "#FF0000"}, "Terminal", "", ""]))
    out = {}
    for i, (kind, sk, facing, click, lines) in enumerate(specs):
        x, y, z = 3 + i * 2, 70, 3
        w.sign(x, y, z, lines, facing=facing, kind=sk, **click)
        c = w.chunks[(x >> 4, z >> 4)]
        a = c.sections[y >> 4]
        state = c.pal[a[(y & 15) * 256 + (z & 15) * 16 + (x & 15)]]
        out[kind] = (x, y, z, c.bes[(x, y, z)], state, "worldsign")
    return out


def run_game(java, cp, work, timeout):
    """Runs the GameTest server; returns (exit code, log text, elapsed seconds)."""
    cmd = [java, "-Xmx2G", "-cp", cp, "net.minecraft.gametest.Main",
           "--universe", os.path.join(work, "universe"), "--packs", os.path.join(work, "packs"),
           "--report", os.path.join(work, "report.xml"), "--tests", TEST_NS + ":*"]
    t0 = time.time()
    p = subprocess.run(cmd, cwd=work, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       timeout=timeout)
    log = p.stdout.decode("utf-8", "replace")
    open(os.path.join(work, "server.log"), "w", encoding="utf-8").write(log)
    return p.returncode, log, time.time() - t0


# A log record starts with "[hh:mm:ss] [thread/level]: "; the following lines of
# an exception stack trace belong to the same record.
REC_RE = re.compile(r"^\[\d\d:\d\d:\d\d\] \[([^\]]+)/(INFO|WARN|ERROR|FATAL|DEBUG)\]: ")
# Warnings the GameTest server emits on its own, unrelated to the datapack.
BENIGN_RE = re.compile(r"Can't keep up!")
# The record each of the two negative controls should leave.
CTL_FUNCTION = "Failed to load function %s:broken" % TEST_NS
CTL_DIALOG = "Failed to get element ResourceKey[minecraft:dialog / %s:no_such_dialog]" % NS


COUNT_NAMES = {"tp": "Teleport functions landing at the agreed position and facing in the game",
               "trig": "Station list and attraction buttons dispatched by trigger to the station "
                       "or attraction on the button",
               "hud": "Station entry notice: teleport destinations within their station's range, "
                      "with hud_enter run"}


def records(log):
    """log -> [(level, full record text)]; the WARNING lines the JVM prints at
    the start are not records."""
    out = []
    for ln in log.splitlines():
        m = REC_RE.match(ln)
        if m:
            out.append([m.group(2), ln])
        elif out:
            out[-1][1] += "\n" + ln
    return out


def analyse(log, expect, counts, problems, say):
    lines = log.splitlines()
    for pk in (config.DATAPACK_NAME, TEST_NS):
        if not any(("Included folder pack" in ln and pk in ln) for ln in lines):
            problems.append(f"The game did not include datapack {pk} (no 'Included folder pack' in the log)")
    if not any("Started game test server" in ln for ln in lines):
        problems.append("The GameTest server did not start (usually a datapack load failure; "
                        "see the errors below)")
    # Always strict: every record at WARN or above is a problem, except for the
    # two negative controls and the allowlist.
    bad, ctl_fn, ctl_dlg = [], 0, 0
    for level, rec in records(log):
        if level not in ("WARN", "ERROR", "FATAL"):
            continue
        if CTL_FUNCTION in rec:
            ctl_fn += 1
        elif CTL_DIALOG in rec:
            ctl_dlg += 1
        elif not BENIGN_RE.search(rec):
            bad.append(rec)
    if ctl_fn == 1:
        say(f"Negative control: exactly one '{CTL_FUNCTION}' in the log, so function load errors are caught")
    else:
        problems.append(f"Negative control failed: the deliberately broken {TEST_NS}:broken left "
                        f"{ctl_fn} load errors (expected 1), so this tool's log matching is unreliable")
    if ctl_dlg == 1:
        say("Negative control: the game cannot decode a sign that points to a nonexistent dialog "
            "(exactly one 'Failed to get element' in the log)")
    else:
        problems.append(f"Negative control failed: the nonexistent dialog left {ctl_dlg} decoding errors "
                        f"(expected 1)")
    for rec in bad[:15]:
        head = rec.splitlines()
        problems.append("Warning or error in the log: " + " / ".join(h.strip() for h in head[:3])[:400])
    ok = {}
    fails = []
    count = None
    for ln in lines:
        m = re.search(r"MRTCHK (ok|FAIL|count) ?(.*)$", ln)
        if not m:
            continue
        if m.group(1) == "count":
            count = dict(count or {}, **dict(kv.split("=") for kv in m.group(2).split()))
        elif m.group(1) == "ok":
            ok[m.group(2).split()[0]] = True
        else:
            fails.append(m.group(2))
    for f in fails:
        problems.append("In-game check failed: " + f)
    missing = [e for e in expect if e not in ok and not any(f.split()[0] == e for f in fails)]
    for e in missing:
        problems.append("In-game check did not run: " + e)
    say(f"In-game checks: {len(ok)} passed, {len(fails)} failed, {len(missing)} did not run")
    if count is None:
        problems.append("The game reported no counts (the setup function may not have finished)")
    else:
        for k, v in counts.items():
            got = int(count.get(k, -1))
            say("  %s: %d/%d" % (COUNT_NAMES.get(k, k), got, v))
            if got != v:
                problems.append(f"In-game {k}: only {got}/{v} correct")
    passed = any("All" in ln and "required tests passed" in ln for ln in lines)
    if not passed:
        problems.append("GameTest did not report 'All required tests passed'")
    return ok, fails


def main():
    ap = argparse.ArgumentParser(description="Read back the ride system datapack and verify it in the real game")
    ap.add_argument("save")
    ap.add_argument("--no-game", action="store_true", help="Run only the read-back checks; do not start the game")
    ap.add_argument("--no-signs", action="store_true", help="Do not read back the signs in the world save")
    ap.add_argument("--keep", help="Working directory for the in-game test (default: a temporary "
                                   "directory, kept on failure)")
    ap.add_argument("--mc-dir", default=MC_DIR)
    ap.add_argument("--version", default=VERSION)
    ap.add_argument("--timeout", type=int, default=600)
    a = ap.parse_args()
    say = print
    problems = []

    root = os.path.join(a.save, "datapacks", config.DATAPACK_NAME)
    if not os.path.isdir(root):
        print(f"✗ Datapack not found: {root}")
        return 1
    pack = Pack(root)
    say(f"== 1. Read back from disk: {root}")
    btn = static_checks(a.save, pack, problems, say, game_data_version(a.mc_dir, a.version))
    samples = {}
    if not a.no_signs:
        for kind, (x, y, z, be) in sign_checks(a.save, pack, problems, say).items():
            from mrt.infrastructure.savereader import read_volume
            state = read_volume(a.save, x, y, z, x, y, z, verbose=False).get(x, y, z)
            samples[kind] = (x, y, z, be, state, "save")
    landing_checks(a.save, pack, problems, say)
    if not a.no_game:
        say("\n== 2. Hand over to the Minecraft %s GameTest server" % a.version)
        synth = {k: v for k, v in synth_samples(pack).items() if k not in samples}
        if synth:
            say("The save has no %s signs to sample; using signs made with World.sign instead"
                % "/".join(sorted(synth)))
            samples.update(synth)
        java = find_java(a.mc_dir, a.version)
        if not java or not os.path.exists(os.path.join(a.mc_dir, "versions", a.version, a.version + ".jar")):
            print(f"✗ Minecraft {a.version} or its Java not found (--mc-dir {a.mc_dir}); "
                  f"add --no-game to run only the read-back checks")
            return 1
        cp = game_classpath(a.mc_dir, a.version)
        work = a.keep or tempfile.mkdtemp(prefix="mrt_dpcheck_")
        shutil.rmtree(os.path.join(work, "packs"), ignore_errors=True)
        shutil.rmtree(os.path.join(work, "universe"), ignore_errors=True)
        os.makedirs(os.path.join(work, "packs"))
        shutil.copytree(root, os.path.join(work, "packs", config.DATAPACK_NAME))
        from mrt.application import ride_plan as RP
        rules = [(r, v) for r, v, _, _ in RP.GAME_RULES]
        expect, counts, nfile = build_selftest(pack, btn, samples, os.path.join(work, "packs"), rules)
        say(f"Test datapack {TEST_NS}: {nfile} functions, {len(expect)} named checks, "
            f"plus {counts['tp']} teleport functions, {counts['trig']} station list buttons and "
            f"{counts['hud']} station entry notice landing points")
        say(f"java: {java}\nWorking directory: {work}")
        try:
            code, log, dt = run_game(java, cp, work, a.timeout)
        except subprocess.TimeoutExpired:
            problems.append(f"The game did not finish within {a.timeout}s")
            code, log, dt = -1, "", a.timeout
        say(f"GameTest server exit code {code} ({dt:.0f}s); log at {os.path.join(work, 'server.log')}")
        for ln in log.splitlines():
            if "Included folder pack" in ln or "GAME TESTS COMPLETE" in ln \
                    or "required tests" in ln or "[台北捷運]" in ln or "MRTCHK count" in ln:
                say("  | " + ln.strip()[:240])
        if code != 0:
            problems.append(f"GameTest server exit code {code} (not 0)")
        analyse(log, expect, counts, problems, say)
        if not problems and not a.keep:
            shutil.rmtree(work, ignore_errors=True)

    print()
    if problems:
        print(f"✗ {len(problems)} problems:")
        for p in problems[:60]:
            print("  - " + p)
        return 1
    print("✓ Datapack " + ("read-back checks all passed (game not started)" if a.no_game
                            else "read-back and in-game checks all passed"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
