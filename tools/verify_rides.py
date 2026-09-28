#!/usr/bin/env python3
"""Reads every ride sign back from the world save and checks that clicking it
really reaches a platform the player can stand on. It does not trust the
generator's own account.

Ride signs are found by reading back each sign's click action.
`function mrt:ride/<A>_<B>` rides from A to B, and
`function mrt:turn/<A>_<p|m>` moves the player to the opposite platform at a
terminus. The generator did place the signs, but every check below is rebuilt
independently from the blocks, signs and datapack files on disk:

  1. The sign is in the row of platform screen doors: its block is a standing
     sign, the block above is screen door glass, and the block below can be
     stood on.
  2. The spot two blocks straight in front of the sign is standable (the rules
     in domain/walk), and it is on a platform (a yellow warning strip is
     nearby).
  3. The text matches the command: the X in "下一站 X" on a Chinese sign is
     the name of the ride's destination, and Next on an English sign is that
     station's English name (abbreviations and truncation allowed). The sign
     is not far from the station it names. Signs on the terminus side say
     "本站終點" / "Terminus".
  4. If the save has the datapack (<save>/datapacks/<DATAPACK_NAME>/): every
     command's function file exists and holds exactly one line
     `tp @s x y z yaw pitch`, the teleport destination is standable and on a
     platform, and 2 to 3 blocks ahead there is a ride (or terminus) sign that
     the player faces squarely. Riding to B must leave the player in front of
     B's sign. (On a skewed alignment the rounded berth may be only one
     diagonal block, 1.41 m, from the sign; that counts too. Destinations in
     chunks that --bbox did not generate are listed separately and are not
     failures.)
  5. A count per station: a station box has three signs on each side for each
     line, and any shortfall is listed. A station in range without a single
     sign is a failure.

It also checks the route map ticket machines (signs that open a dialog): their
dialog id, and whether the datapack has that dialog.

Usage:
    ./.venv/bin/python tools/verify_rides.py <save>
    ./.venv/bin/python tools/verify_rides.py <save> --stations 台北車站 西門
    ./.venv/bin/python tools/verify_rides.py <save> --bbox X0 Z0 X1 Z1
"""
import argparse
import collections
import csv
import glob
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mrt import config
from mrt.domain import walk
from mrt.infrastructure.savereader import read_sign_entities, read_volume

PLAT_EDGE = "minecraft:yellow_concrete"
CMD_RE = re.compile(r"^function ([a-z0-9_.-]+):(ride|turn)/([a-z0-9_]+)$")
TP_RE = re.compile(r"(?:^|\s)tp @s (\S+) (\S+) (\S+) (\S+) (\S+)")
# Maximum distance (m) from a sign to the station it names (that station's point
# in mc_stations.csv).
MAX_FROM_STATION = 600
PER_STATION = 6             # Per station box and line: three on each side.


def fn_code(code):
    """Station code -> lowercase code for function paths (the same scheme as the
    datapack names: a-z0-9_ only)."""
    return "".join(ch for ch in code.lower() if ch.isalnum() or ch == "_")


def load_stations():
    """{lowercase station code: dict(code, zh, en, x, z)} (a transfer station has
    one entry per line's code).

    Only line station codes are kept (letters followed by digits: BL12, G03A,
    A14a). mc_stations.csv also holds the airport terminal Skytrain (ref
    "Skytrain") and nodes without a ref. They are not metro stations, and they
    used to be reported as stations without a single ride sign. The English
    name field is occasionally Chinese (Y07 Dapinglin on the Circular Line
    holds its Chinese name). As the generator does (network.build_network),
    borrow the English name from the station of the same name on another line;
    otherwise the correct "Next: Dapinglin" on a sign would be judged a
    mismatch.
    """
    rows = list(csv.DictReader(open(config.MC_STATIONS_CSV, encoding="utf-8")))
    en_of = {}
    for r in rows:
        if any("a" <= ch.lower() <= "z" for ch in r["name_en"]):
            en_of.setdefault(r["name_zh"] or r["name_en"], r["name_en"])
    out = {}
    for r in rows:
        zh = r["name_zh"] or r["name_en"]
        en = en_of.get(zh, r["name_en"])
        if "(" in en:
            en = en[:en.index("(")].rstrip()
        for code in r["ref"].split(";"):
            code = code.strip()
            if re.match(r"^[A-Z]+[0-9]", code):
                out[fn_code(code)] = dict(code=code, zh=zh, en=en,
                                          x=int(r["mc_x"]), z=int(r["mc_z"]))
    return out


def save_extent(save):
    rdir = config.region_dir(save)
    xs, zs = [], []
    for p in glob.glob(os.path.join(rdir, "r.*.mca")):
        m = re.match(r"r\.(-?\d+)\.(-?\d+)\.mca$", os.path.basename(p))
        if m:
            xs.append(int(m.group(1))); zs.append(int(m.group(2)))
    if not xs:
        return None
    return (min(xs) * 512, min(zs) * 512, max(xs) * 512 + 511, max(zs) * 512 + 511)


def region_exists(save, x, z):
    return os.path.exists(os.path.join(config.region_dir(save), f"r.{x >> 9}.{z >> 9}.mca"))


def chunk_exists(save, x, z):
    """Whether the chunk containing (x, z) was written to the save (its entry in
    the offset table at the start of the region file is not 0).

    --bbox generates only some regions. A ride to a neighbor outside that range
    has a destination that was never built, and it reads back as air. That is
    not a datapack error: the station is not in this save, and it must be
    reported separately."""
    p = os.path.join(config.region_dir(save), f"r.{x >> 9}.{z >> 9}.mca")
    if not os.path.exists(p):
        return False
    i = ((x >> 4) & 31) + ((z >> 4) & 31) * 32
    with open(p, "rb") as f:
        f.seek(i * 4)
        head = f.read(4)
    return len(head) == 4 and int.from_bytes(head[:3], "big") != 0


# ---------- Text ----------

def _words(s):
    return [w for w in re.split(r"[\s/\-]+", s) if w]


def en_match(text, name):
    """Whether the English on a sign (possibly abbreviated or truncated) is this
    station name.

    Each word must match some word of the station name, in order (words of the
    station name may be skipped, since abbreviations often drop Taipei and the
    like). An all-caps word is an acronym (WTC, CKS) or the word itself. Other
    words may be abbreviations (Exh. -> Exhibition, Bldg -> Building: the
    letters appear in order in the original word, and the first letter
    matches). The last word may be only a prefix if "…" follows it.
    """
    t = text.strip()
    cut = t.endswith("…")
    t = t.rstrip("…").strip()
    if not t:
        return False
    if t.lower() == name.lower():
        return True
    words = [w.lower().rstrip(".") for w in _words(name)]   # Names abbreviate too (Minquan W. Rd.).
    words = [w for w in words if w]
    toks = _words(t)
    wi = 0
    matched = 0
    for k, tok in enumerate(toks):
        last = k == len(toks) - 1
        if tok == "&":
            tok = "and"
        low = tok.lower().rstrip(".")
        found = False
        while wi < len(words):
            w = words[wi]
            if low == w or (last and cut and w.startswith(low)):
                found = True; wi += 1; break
            if tok.isupper() and len(tok) >= 2 and "".join(x[0] for x in words[wi:wi + len(tok)]) == low:
                found = True; wi += len(tok); break
            # Abbreviations (Exh., Ctr., Bldg, Pk): the letters appear in order in
            # the original word, and the first letter matches.
            if len(low) >= 2 and low[0] == w[0] and _subseq(low, w) or (low and low == w[:len(low)] and tok.endswith(".")):
                found = True; wi += 1; break
            wi += 1
        if not found:
            return False
        matched += 1
    return matched > 0


def _subseq(a, b):
    it = iter(b)
    return all(ch in it for ch in a)


def sign_next(front):
    """The next station written on the sign: ("zh", name) / ("en", English name)
    / (None, None)."""
    for i, ln in enumerate(front):
        s = ln.strip()
        if s.startswith("下一站"):
            return "zh", s[len("下一站"):].strip()
        if s.startswith("下站"):
            return "zh", s[len("下站"):].strip()
        if s.startswith("Next:"):
            return "en", s[len("Next:"):].strip()
        if s == "Next station" and i + 1 < len(front):
            return "en", front[i + 1].strip()
    return None, None


def zh_match(text, name):
    t = text.strip()
    if t.endswith("…"):
        return name.startswith(t.rstrip("…"))
    return t == name


# ---------- Blocks ----------

class Blocks:
    """Several volumes read back, searched in order. Anything outside them is
    air (the caller makes sure the volumes were read first)."""

    def __init__(self):
        self.vols = []

    def add(self, vol):
        self.vols.append(vol)

    def covers(self, x, y, z):
        return any(v.x0 <= x <= v.x1 and v.y0 <= y <= v.y1 and v.z0 <= z <= v.z1
                   for v in self.vols)

    def get(self, x, y, z):
        for v in self.vols:
            if v.x0 <= x <= v.x1 and v.y0 <= y <= v.y1 and v.z0 <= z <= v.z1:
                return v.get(x, y, z)
        return "minecraft:air"


def read_clusters(save, pts, blocks, grid=160, pad=8, below=4, above=6):
    """Groups the points to check into cells of grid meters and reads one volume
    per cell."""
    groups = collections.defaultdict(list)
    for x, y, z in pts:
        if not blocks.covers(x, y, z):
            groups[(x // grid, z // grid)].append((x, y, z))
    for g in groups.values():
        xs = [p[0] for p in g]; ys = [p[1] for p in g]; zs = [p[2] for p in g]
        blocks.add(read_volume(save, min(xs) - pad, min(ys) - below, min(zs) - pad,
                               max(xs) + pad, max(ys) + above, max(zs) + pad, verbose=False))


def rotation_of(block):
    m = re.search(r"rotation=(\d+)", block)
    return int(m.group(1)) if m else None


def facing_vec(rot):
    """Standing sign rotation (0 = south, 4 = west, …) -> unit vector (dx, dz)
    the sign faces."""
    yaw = math.radians(rot * 22.5)
    return -math.sin(yaw), math.cos(yaw)


def yaw_vec(yaw_deg):
    yaw = math.radians(yaw_deg)
    return -math.sin(yaw), math.cos(yaw)


def near_yellow(get, x, y, z, r=2):
    """Whether the yellow warning strip of a platform edge is near the berth (on
    the layer under the feet)."""
    return any(get(x + dx, y - 1, z + dz) == PLAT_EDGE
               for dx in range(-r, r + 1) for dz in range(-r, r + 1))


def stand_in_front(get, sx, sy, sz, f):
    """A standable block about two blocks straight in front of the sign (the one
    closest to 2 blocks away); None if there is none."""
    best = None
    for dx in range(-3, 4):
        for dz in range(-3, 4):
            d = math.hypot(dx, dz)
            if not (1.3 <= d <= 2.95):
                continue
            if (dx * f[0] + dz * f[1]) / d < 0.7:
                continue
            c = (sx + dx, sy, sz + dz)
            if walk.standable(get, *c):
                score = abs(d - 2.0) + 0.5 * (1 - (dx * f[0] + dz * f[1]) / d)
                if best is None or score < best[0]:
                    best = (score, c)
    return best[1] if best else None


# ---------- Datapack ----------

def function_dir(save):
    root = os.path.join(save, "datapacks", config.DATAPACK_NAME, "data", config.DATAPACK_NS)
    for sub in ("function", "functions"):
        d = os.path.join(root, sub)
        if os.path.isdir(d):
            return d
    return None


def read_tp(path):
    """The tp commands in a function file: [(x, y, z, yaw, pitch)] (by
    convention, exactly one line)."""
    out = []
    with open(path, encoding="utf-8") as f:
        for ln in f:
            ln = ln.split("#", 1)[0] if ln.lstrip().startswith("#") else ln
            for m in TP_RE.finditer(ln):
                try:
                    out.append(tuple(float(v) for v in m.groups()))
                except ValueError:
                    out.append(None)
    return out


# ---------- Main ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("save", nargs="?", default=config.DEFAULT_SAVE)
    ap.add_argument("--stations", nargs="*")
    ap.add_argument("--bbox", nargs=4, type=int, metavar=("X0", "Z0", "X1", "Z1"))
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    if not os.path.isdir(a.save):
        print(f"World save not found: {a.save}")
        return 1
    stn = load_stations()
    by_name = collections.defaultdict(list)
    for c, s in stn.items():
        by_name[s["zh"]].append(c)

    if a.bbox:
        box = tuple(a.bbox)
    elif a.stations:
        pts = [(stn[c]["x"], stn[c]["z"]) for n in a.stations for c in by_name.get(n, ())]
        if not pts:
            print("None of these stations is in mc_stations.csv"); return 1
        box = (min(p[0] for p in pts) - 500, min(p[1] for p in pts) - 500,
               max(p[0] for p in pts) + 500, max(p[1] for p in pts) + 500)
    else:
        box = save_extent(a.save)
        if box is None:
            print("The world save has no region files"); return 1

    print(f"World save {a.save}\nReading signs in x {box[0]}..{box[2]}  z {box[1]}..{box[3]} …")
    signs = read_sign_entities(a.save, *box)
    rides, maps, bad_exit = [], [], []
    for s in signs:
        click = s["click"] or {}
        cmd = click.get("command", "")
        m = CMD_RE.match(cmd) if click.get("action") == "run_command" else None
        if m and m.group(1) == config.DATAPACK_NS:
            kind, ident = m.group(2), m.group(3)
            parts = ident.split("_")
            if kind == "ride" and len(parts) == 2:
                s.update(kind="ride", ident=f"ride/{ident}", frm=parts[0], to=parts[1])
            elif kind == "turn" and len(parts) == 2 and parts[1] in ("p", "m"):
                s.update(kind="turn", ident=f"turn/{ident}", frm=parts[0], to=None)
            else:
                s.update(kind="bad", ident=ident, frm=None, to=None)
            rides.append(s)
        elif click.get("action") == "show_dialog":
            maps.append(s)
        if s["front"] and s["front"][0].startswith("出口") and click:
            bad_exit.append(s)
    if a.stations:
        want = {c for n in a.stations for c in by_name.get(n, ())}
        rides = [s for s in rides if s.get("frm") in want]
    print(f"{len(signs):,} signs: {sum(1 for s in rides if s['kind'] == 'ride')} ride signs, "
          f"{sum(1 for s in rides if s['kind'] == 'turn')} terminus platform-change signs, "
          f"{len(maps)} route map ticket machines")

    # ---- Datapack: read the destinations first, so their blocks are read in the same pass ----
    fdir = function_dir(a.save)
    targets = {}                            # Function id -> (x, y, z, yaw, pitch) or an error message.
    if fdir is None:
        print(f"(The save has no datapack datapacks/{config.DATAPACK_NAME}/; checking signs and berths "
              f"only, not teleport destinations)")
    else:
        for ident in sorted({s["ident"] for s in rides if s["kind"] in ("ride", "turn")}):
            p = os.path.join(fdir, ident + ".mcfunction")
            if not os.path.exists(p):
                targets[ident] = "function file missing"
                continue
            tps = read_tp(p)
            if len(tps) != 1 or tps[0] is None:
                targets[ident] = f"expected exactly one line tp @s x y z yaw pitch, found {len(tps)}"
                continue
            targets[ident] = tps[0]
        print(f"Datapack {fdir}: {len(targets)} functions")

    blocks = Blocks()
    pts = [(s["x"], s["y"], s["z"]) for s in rides]
    tcells = {k: (math.floor(v[0]), math.floor(v[1]), math.floor(v[2]))
              for k, v in targets.items() if isinstance(v, tuple)}
    read_clusters(a.save, pts + list(tcells.values()), blocks)
    get = blocks.get

    # Signs near the destinations: those outside the range are read separately.
    sign_at = {(s["x"], s["y"], s["z"]): s for s in rides}
    extra = [c for c in tcells.values()
             if not (box[0] <= c[0] <= box[2] and box[1] <= c[2] <= box[3])]
    for c in extra:
        for s in read_sign_entities(a.save, c[0] - 4, c[2] - 4, c[0] + 4, c[2] + 4):
            m = CMD_RE.match((s["click"] or {}).get("command", ""))
            if m:
                parts = m.group(3).split("_")
                s.update(kind=m.group(2), ident=f"{m.group(2)}/{m.group(3)}", frm=parts[0])
                sign_at.setdefault((s["x"], s["y"], s["z"]), s)

    # ---- Check each sign ----
    problems = collections.defaultdict(list)       # Station code -> [messages].
    count = collections.Counter()
    outside = set()                                # Destinations outside the range this save generated.
    for s in rides:
        x, y, z = s["x"], s["y"], s["z"]
        code = s.get("frm")
        tag = f"{' / '.join(t for t in s['front'][:2] if t)} ({x},{y},{z})"
        if s["kind"] == "bad":
            problems[code or "?"].append(f"{tag}: unrecognised command {s['ident']}")
            continue
        count[(code, s["kind"])] += 1
        me = stn.get(code)
        if me is None:
            problems[code].append(f"{tag}: station code {code} is not in mc_stations.csv")
        elif math.hypot(me["x"] - x, me["z"] - z) > MAX_FROM_STATION:
            problems[code].append(f"{tag}: {math.hypot(me['x'] - x, me['z'] - z):.0f} m from the "
                                  f"station point of {me['zh']}, too far to be that station's sign")
        blk = get(x, y, z)
        rot = rotation_of(blk)
        if "_sign" not in blk or rot is None:
            problems[code].append(f"{tag}: the block is not a standing sign ({blk})")
            continue
        above, below = get(x, y + 1, z), get(x, y - 1, z)
        if "glass_pane" not in above:
            problems[code].append(f"{tag}: not in the row of platform screen doors "
                                  f"(above is {above}, not screen door glass)")
        if not walk.is_support(below):
            problems[code].append(f"{tag}: nothing to stand on below ({below})")
        f = facing_vec(rot)
        st = stand_in_front(get, x, y, z, f)
        if st is None:
            problems[code].append(f"{tag}: the spot two blocks in front of the sign is not standable")
        elif not near_yellow(get, *st):
            problems[code].append(f"{tag}: no platform warning strip near berth {st}, "
                                  f"so it is not on a platform")
        # Check that the text matches the command.
        if s["kind"] == "ride":
            to = stn.get(s["to"])
            lang, nxt = sign_next(s["front"])
            if to is None:
                problems[code].append(f"{tag}: destination code {s['to']} is not in mc_stations.csv")
            elif lang is None:
                problems[code].append(f"{tag}: the sign does not name the next station")
            elif lang == "zh" and not zh_match(nxt, to["zh"]):
                problems[code].append(f"{tag}: the sign says next station '{nxt}', but the command rides "
                                      f"to {to['zh']} ({s['ident']})")
            elif lang == "en" and not en_match(nxt, to["en"]):
                problems[code].append(f"{tag}: the sign says Next '{nxt}', but the command rides "
                                      f"to {to['en']} ({s['ident']})")
            elif lang == "zh" and me is not None and not any(me["zh"] in t for t in s["front"]):
                problems[code].append(f"{tag}: the Chinese sign does not name this station, {me['zh']}")
        else:
            if not ("本站終點" in s["front"][0] or "Terminus" in s["front"][0]):
                problems[code].append(f"{tag}: the terminus platform-change sign does not say "
                                      f"'本站終點' or 'Terminus'")
        # Datapack: the destination.
        if fdir is not None:
            t = targets.get(s["ident"])
            if not isinstance(t, tuple):
                problems[code].append(f"{tag}: {s['ident']}: {t}")
                continue
            tx, ty, tz, yaw, _ = t
            c = tcells[s["ident"]]
            where = f"{s['ident']} -> ({tx:g},{ty:g},{tz:g})"
            if not chunk_exists(a.save, c[0], c[2]):
                outside.add(s["ident"])
                continue
            if abs(tx - c[0] - 0.5) > 1e-6 or abs(tz - c[2] - 0.5) > 1e-6:
                problems[code].append(f"{tag}: {where} is not at the centre of a block "
                                      f"(x and z should end in .5)")
            if not walk.standable(get, *c):
                problems[code].append(f"{tag}: {where} is not standable "
                                      f"(feet {get(*c)}, below {get(c[0], c[1] - 1, c[2])})")
                continue
            if not near_yellow(get, *c):
                problems[code].append(f"{tag}: {where} has no platform warning strip nearby")
            fv = yaw_vec(yaw)
            faced = None
            for (qx, qy, qz), q in sign_at.items():
                if qy != c[1]:
                    continue
                dx, dz = qx - c[0], qz - c[2]
                d = math.hypot(dx, dz)
                # On a skewed alignment the rounded berth may be only one diagonal
                # block (1.41 m) from the sign; that still counts as in front.
                if 1.3 <= d <= 3.5 and (dx * fv[0] + dz * fv[1]) / d >= 0.75:
                    faced = q
                    break
            if faced is None:
                problems[code].append(f"{tag}: {where} has no ride sign 2 to 3 blocks ahead "
                                      f"(or does not face it squarely)")
                continue
            arrive = s["to"] if s["kind"] == "ride" else code
            if faced.get("frm") != arrive:
                problems[code].append(f"{tag}: {where} faces the sign for {faced.get('ident')}, "
                                      f"not a sign of station {arrive}")
            elif s["kind"] == "turn" and faced.get("kind") != "ride":
                problems[code].append(f"{tag}: after the platform change the player still faces a "
                                      f"terminus-side sign ({faced.get('ident')})")

    # ---- Route map ticket machines ----
    want_dialog = f"{config.DATAPACK_NS}:network"
    wrong = [s for s in maps if (s["click"] or {}).get("dialog") != want_dialog]
    for s in wrong:
        problems["Route map"].append(f"({s['x']},{s['y']},{s['z']}) opens dialog "
                                     f"{(s['click'] or {}).get('dialog')}, not {want_dialog}")
    if fdir is not None and maps:
        dlg = os.path.join(os.path.dirname(fdir), "dialog", "network.json")
        if not os.path.exists(dlg):
            problems["Route map"].append(f"the datapack has no {want_dialog} dialog ({dlg})")
    for s in bad_exit:
        problems["Exit sign"].append(f"({s['x']},{s['y']},{s['z']}) has the first line "
                                     f"'{s['front'][0]}' but carries a click action")

    # ---- Per station ----
    codes = sorted({s["frm"] for s in rides if s.get("frm")} | set(problems) - {"Route map", "Exit sign"},
                   key=lambda c: (re.sub(r"\d.*", "", c), int(re.sub(r"\D", "", c) or 0), c))
    in_box = [c for c, s in stn.items()
              if box[0] <= s["x"] <= box[2] and box[1] <= s["z"] <= box[3]
              and region_exists(a.save, s["x"], s["z"])
              and (not a.stations or s["zh"] in a.stations)]
    missing = sorted(c for c in in_box if c not in codes)
    print()
    few = []
    for c in codes:
        me = stn.get(c, dict(zh="?", code=c))
        nr, nt = count[(c, "ride")], count[(c, "turn")]
        flag = "   <- problem" if problems.get(c) else ""
        note = ""
        if nr + nt < PER_STATION:
            note = f"  (fewer than {PER_STATION})"
            few.append(c)
        print(f"  {me['code']:<6} {me['zh']:<8} ride {nr:>2}  terminus {nt:>2}{note}{flag}")
        for p in problems.get(c, ())[:8 if not a.verbose else None]:
            print(f"      {p}")
        if not a.verbose and len(problems.get(c, ())) > 8:
            print(f"      …and {len(problems[c]) - 8} more (-v shows all)")
    for k in ("Route map", "Exit sign"):
        for p in problems.get(k, ()):
            print(f"  {k}: {p}")
    for c in missing:
        print(f"  {stn[c]['code']:<6} {stn[c]['zh']:<8} no ride signs at all   <- problem")

    if outside:
        print(f"  ({len(outside)} functions have destinations in chunks this save did not generate; "
              f"not checked: {', '.join(sorted(outside)[:8])}{' …' if len(outside) > 8 else ''})")
    n_bad = sum(len(v) for v in problems.values())
    print(f"\nTotal: station codes {len(codes)}, ride and terminus signs {len(rides)}; "
          f"problems {n_bad}; stations in range without signs {len(missing)}; "
          f"station codes with fewer than {PER_STATION} signs {len(few)}")
    if n_bad or missing:
        return 1
    print("All passed: every ride sign is in the row of platform screen doors, the spot in front "
          "is standable, and the text matches where a click goes"
          + ("; every datapack teleport also lands in front of the next station's sign" if fdir else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
