#!/usr/bin/env python3
"""Real exit and transfer passage generator: turns the plans computed by domain/exits.py into buildable objects.

Each station originally had one template stair. This module follows the real
coordinates and numbers in `data/entrances.json`: each exit gets a switchback
stair shaft (ShaftStair) down to the concourse, and a connecting passage (Tile)
runs along the outside of the station box into the concourse's unpaid area. All
three reuse the underground mall parts; the link stairs at Taipei Main Station
are connected the same way, only with g0 changed from "the underground mall
floor" to "the real ground".

Three kinds of station have three kinds of concourse (alignment.station_kind):
an underground station's concourse is at rail top +7 and the shaft digs down
from the street; an elevated station's concourse is under the viaduct (rail top
-6), the shaft climbs up from the street and the passage is a skybridge; an
at-grade station's concourse spans above the platforms (rail top +8). The shaft
is the same in every case; only which door is at the top differs.

A transfer station's two station boxes are also joined by a transfer passage
(paid area to paid area): at the same level it is one passage; at different
levels a shaft stands between the two boxes, and each level gets a passage to
one of the shaft's doors.

Stations without real exit data (the Taoyuan section of the Airport MRT and the
at-grade stations of the Ankeng and Danhai LRT) get one exit at a default
position through the same process, so every station on the network can be
walked to from the street down to the platform.

Every returned object has bbox() and build(w) and is bucketed by region in
cli/build_world like any other landmark. Underground passages are marked
underground=True (no terrain needs generating for them); stair shafts and
skybridges are not: they stand in the street and need real terrain around them
so they neither float nor end up buried.

Self-test: ./.venv/bin/python tests/test_exits.py
"""
import collections

from mrt import config
from mrt.application import build_concourse as BCC
from mrt.application import signage as SG
from mrt.domain import exits as EX
from mrt.domain import network as NW
from mrt.domain.alignment import station_kind
from mrt.domain.stacked import station_samples

PIER_EVERY = 6         # Meters between skybridge piers.
APRON = "minecraft:grass_block"   # Apron paving in front of an exit door: counts as terrain, and the "door opens onto the street" check looks for it.


def sign_lines(refs, name_zh, name_en):
    """The four lines of an exit sign: number, station name, English station name, Exit."""
    tags = [str(r) for r in refs if str(r)]
    tag = "/".join(tags[:3]) if tags else ""
    return [("出口 " + tag).strip(), name_zh or "", name_en or "",
            ("Exit " + tag).strip()]


def transfer_lines(ref, name_zh, name_en):
    """The sign beside a transfer shaft door: which line it leads to.

    The line in English sits under its Chinese, so the station name takes one
    line in both languages (and in Chinese alone when both do not fit).
    tests/test_transfer.py expects the second line to be exactly f"往 {ref} 線"."""
    zh, en = name_zh or "", name_en or ""
    both = [f"{zh} {f}" for f in SG.en_forms(en)] if zh and en else []
    station = SG.fit(both + ([zh] if zh else SG.en_forms(en))) if (zh or en) else ""
    return ["轉乘 Transfer", f"往 {ref} 線", _to_line_en(ref), station]


def _to_line_en(ref):
    """The English for 往 X 線 ("to line X"): the line's English name, shortened to fit."""
    en = NW.LINE_NAMES.get(ref, (ref, ref))[1]
    short = en.replace(" Line", "")
    words = en.split(" ")
    tail = " ".join(words[1:]) if len(words) > 2 else short    # Taoyuan Airport MRT -> Airport MRT
    return SG.fit(["To " + en, "To " + short, "To " + tail, short, "To " + ref])


def footprint(objs, used=None):
    """Add the cells occupied by a batch of landmarks to an Occupancy (a Tile by
    its actual floor and walls, anything else by its bbox, always as a full
    column).

    Exit shafts must not cut into Taipei Main Station's underground malls: the
    Zhongshan underground mall runs all the way to Shuanglian, and the exit
    shafts of Zhongshan and Shuanglian stations dig down from the ground right
    through it.
    """
    used = EX.Occupancy() if used is None else used
    for o in objs:
        cells = getattr(o, "cells", None)
        if cells is not None and getattr(o, "ring", None) is not None:
            for x, z in set(cells) | set(o.ring):
                used.add(x, z, config.Y_MIN, config.Y_MAX)
            continue
        x0, z0, x1, z1 = o.bbox()
        for x in range(int(x0), int(x1) + 1):
            for z in range(int(z0), int(z1) + 1):
                used.add(x, z, config.Y_MIN, config.Y_MAX)
    return used


def make_well(s, sign, sign_style=None):
    """Build an exit shaft from a plan. If the street is above the concourse the
    shaft digs down from the street (underground station); otherwise it climbs
    up from the street (elevated station). The exit sign always stands by the
    street door."""
    street = s["g0"] + 1
    if street > s["y_to"]:
        return BCC.ShaftStair(s["x0"], s["z0"], s["ux"], s["uz"], s["g0"], s["y_to"],
                              bottom_door=True, sign=sign, apron=APRON,
                              sign_style=sign_style)
    return BCC.ShaftStair(s["x0"], s["z0"], s["ux"], s["uz"], s["y_to"] - 1, street,
                          bottom_door=True, sign_bottom=sign, apron=APRON,
                          sign_style=sign_style)


class GroundGate:
    """At-grade exit: the passage opens straight onto the street, with a ramp and
    an apron outside the door.

    An elevated station's under-viaduct concourse is only 3 to 7 m above the
    ground, so on a hillside an exit's street level may be within two meters of
    the concourse. A switchback shaft cannot be built there: its two doors are in
    the same wall, with less than three blocks of drop the bottom door opening
    shrinks to one block, and the apron in front of the door happens to clear
    the skybridge floor (the default exit at Tamkang University ended up with
    "the door not reaching the street" this way). A difference of 0 to 2 m needs
    no shaft at all: the end of the passage is the door, the ground outside
    rises or falls one block per cell to the street, and a small apron is paved.

    The coordinates are those of ShaftStair: (x0, z0) is the door cell (the last
    cell of the passage, whose floor the passage lays), u = (ux, uz) points to
    the street, and the ramp and apron occupy a = 1..run, b = -half..half. The
    passage floor is built first (the passage brush covers a = 1..2), and this
    class then turns those cells into the ramp.
    """

    def __init__(self, x0, z0, ux, uz, street, level, sign=None,
                 step=BCC.STAIR, apron=APRON, run=EX.GATE_RUN, half=EX.PASS_HALF,
                 sign_style=None):
        self.x0, self.z0 = int(x0), int(z0)
        self.ux, self.uz = int(round(ux)), int(round(uz))
        self.street, self.level = int(street), int(level)   # Standing heights of the street and the concourse.
        self.sign = list(sign) if sign else None
        self.step, self.apron = step, apron
        self.run, self.half = int(run), int(half)
        self.sign_style = dict(sign_style or {})

    def _w(self, a, b):
        vx, vz = -self.uz, self.ux
        return self.x0 + self.ux * a + vx * b, self.z0 + self.uz * a + vz * b

    def bbox(self):
        pts = [self._w(a, b) for a in (0, self.run + 1)
               for b in (-self.half - 1, self.half + 1)]
        xs = [p[0] for p in pts]; zs = [p[1] for p in pts]
        return min(xs) - 1, min(zs) - 1, max(xs) + 1, max(zs) + 1

    def floor_at(self, a):
        """Paving of cell a outside the door: one block up or down per cell from
        the passage floor to the street, then the street level."""
        d = self.street - self.level
        sgn = (d > 0) - (d < 0)
        return self.level - 1 + sgn * min(a, abs(d))

    def build(self, w):
        for a in range(1, self.run + 1):
            y = self.floor_at(a)
            blk = self.apron if y == self.street - 1 else self.step
            for b in range(-self.half, self.half + 1):
                x, z = self._w(a, b)
                w.set(x, y, z, blk)
                for yy in range(y + 1, y + 4):
                    w.set(x, yy, z, BCC.AIR)
        # The exit sign stands beside the apron at the street end, facing people
        # walking in from the street.
        if self.sign and hasattr(w, "sign"):
            x, z = self._w(self.run, self.half + 1)
            w.set(x, self.street - 1, z, self.step)
            w.sign(x, self.street, z, self.sign[:4], facing=(self.ux, self.uz),
                   **self.sign_style)
            w.set(x, self.street + 1, z, BCC.AIR)


def make_gate(s, sign, sign_style=None):
    """Build an at-grade exit from a plan (an item of gates in exits.plan_station)."""
    return GroundGate(s["x0"], s["z0"], s["ux"], s["uz"], s["g0"] + 1, s["y_to"],
                      sign=sign, sign_style=sign_style)


def make_tile(cells, no_wall, level, kind, ground_at):
    """One level's passage floor: a tunnel for an underground station, otherwise
    a glass skybridge (on piers where the terrain is lower)."""
    ring = BCC.outer_ring(cells) - no_wall
    if kind == "tunnel":
        tile = BCC.Tile(cells, ring, level, {}, shopfront=False)
        tile.underground = True
        return tile
    piers = {}
    for x, z in cells:
        if x % PIER_EVERY == 0 and z % PIER_EVERY == 0:
            g = int(ground_at(x, z))
            if g < level - 2:
                piers[(x, z)] = g
    tile = BCC.Tile(cells, ring, level, {}, shopfront=False, bridge=True, pier_to=piers)
    tile.underground = False
    return tile


def station_exits(segs, entrances_by_name, ground_at, skip=(), used=None,
                  verbose=True, no_transfer=(), no_default=(), colours=None):
    """Build the real exits of every station, then the transfer passages of transfer stations.

    segs               the segments planned by the CLI (samples / ys / ground / stn / hw)
    entrances_by_name  {station name: [(ref, x, z)]}
    ground_at          f(x, z) -> ground y
    skip               station names to leave alone (the underground malls handle the Taipei Main Station area)
    used               an Occupancy of cells taken by other landmarks (the result of footprint())
    no_transfer        station names that get no transfer passage (the Taipei Main Station complex transfers through the underground malls)
    no_default         station names that get no default exit when they have none (the complex is entered by the underground malls' link stairs)
    colours            {line: "#rrggbb"} (network.line_colours): the line color and glow ink for
                       the first line of exit signs (signage.exit_sign_lines). None gives the old plain signs.

    Returns (objects, exits, report):
      exits   {(segment index, sample index): number of shafts}, which the CLI uses to turn off template stairs
      report  {station name: dict(built, skipped, transfer)}
    """
    used = EX.Occupancy() if used is None else used
    occ = EX.index_segments(segs)

    # Station box coordinates come from stacked.station_samples: for a shared
    # station box (Ximen) the frame is the centerline between the two lines, and
    # exits and transfer passages must connect to that box structure's side wall,
    # not beside the line's own centerline.
    boxes = collections.defaultdict(dict)          # Station name -> {(li, bi): ...}.
    labels = {}
    for li, sg in enumerate(segs):
        for bi, (full, name, en) in sg["stn"].items():
            boxes[name][(li, bi)] = (station_samples(sg, bi), sg["ys"], bi)
            labels[(li, bi)] = (full, name, en)

    objs, exits, report = [], {}, {}
    floors = collections.defaultdict(set)          # (li, bi, level) -> floor cells.
    no_wall, kinds = {}, {}
    wells = []                                     # Shafts are built after the floors.
    n_default = n_tr = n_all = 0

    def interior_of(key):
        sg = segs[key[0]]
        fr = station_samples(sg, key[1])
        lo, hi, _ = EX.station_frame(fr, sg["ys"], key[1])
        return EX.box_cells(fr, lo, hi, EX.BOX_HALF - 2)

    def kind_of(key):
        sg = segs[key[0]]
        return station_kind(int(sg["ys"][key[1]]), int(sg["ground"][key[1]]))

    def plan_exits(name, key, ents, used_):
        """The exits of one station box. Returns (plan, shafts)."""
        li, bi = key
        sg = segs[li]
        plan = EX.plan_station(station_samples(sg, bi), sg["ys"], sg["ground"], bi,
                               ents, ground_at, occ, used_, own_tag=li,
                               ally_tags=sg.get("ally_segs", {}).get(bi, ()))
        out = []
        full, zh, en = labels[key]
        style = SG.SIGN_STYLE if colours is not None else None

        def sign_of(refs):
            lines = sign_lines(refs, zh, en)
            if colours is None:
                return lines
            return SG.exit_sign_lines(lines, colours.get(sg["ref"]))
        for s in plan["shafts"]:
            well = make_well(s, sign_of(s["refs"]), style)
            well.label = (name, s["refs"])
            well.underground = False
            out.append(well)
        for s in plan["gates"]:
            gate = make_gate(s, sign_of(s["refs"]), style)
            gate.label = (name, s["refs"])
            gate.underground = False
            out.append(gate)
        plan["built"] = plan["shafts"] + plan["gates"]
        return plan, out

    def plan_transfers(name, used_):
        """Chain all station boxes of a transfer station and connect them pair by
        pair. Returns [(ka, kb, result, shaft)]."""
        keys = sorted(boxes[name])

        def bx(key):
            li, bi = key
            sg = segs[li]
            return dict(samples=station_samples(sg, bi), ys=sg["ys"], grounds=sg["ground"],
                        idx=bi, tag=li, key=key)
        pairs, rest, cur = [], keys[1:], keys[0]
        while rest:
            nxt = min(rest, key=lambda k: _dist(boxes[name][cur], boxes[name][k]))
            pairs.append((cur, nxt)); rest.remove(nxt); cur = nxt
        out = []
        for ka, kb in pairs:
            A, B = bx(ka), bx(kb)
            res = EX.plan_transfer(A, B, occ, used_)
            well = None
            if res["ok"] and res["well"] is not None:
                x0, z0, dx, dz, top, bottom = res["well"]
                # Each door's sign names the line that door leads to.
                (ta, la, _), (tb, lb, _) = res["legs"]
                up_key, lo_key = (ka, kb) if la >= lb else (kb, ka)
                fa, za, ea = labels[lo_key]
                fb, zb, eb = labels[up_key]
                ra, rb = segs[lo_key[0]]["ref"], segs[up_key[0]]["ref"]
                sa, sb = transfer_lines(ra, za, ea), transfer_lines(rb, zb, eb)
                if colours is not None:
                    sa = SG.transfer_sign_lines(sa, colours.get(ra))
                    sb = SG.transfer_sign_lines(sb, colours.get(rb))
                well = BCC.ShaftStair(x0, z0, dx, dz, top - 1, bottom, bottom_door=True,
                                      sign=sa, sign_bottom=sb,
                                      sign_style=SG.SIGN_STYLE if colours is not None else None)
                well.label = (name, "轉乘")
                well.underground = False
            out.append((ka, kb, res, well))
        return out

    def plan_name(name, assigned, order, used_):
        """The complete plan of one station (all its station boxes). Order "tr"
        connects transfers first and then exits, "ex" the reverse. Returns
        dict(score, wells, floors, exits, built, skipped, transfer)."""
        r = dict(score=0, wells=[], floors=collections.defaultdict(set), exits={},
                 built=[], skipped=[], transfer=None, n_default=0, open={})
        do_tr = name not in no_transfer and len(boxes[name]) >= 2

        def exits_pass():
            for key, mine in assigned.items():
                if mine:
                    plan, ws = plan_exits(name, key, mine, used_)
                    r["skipped"] += plan["skipped"]
                    r["built"] += plan["built"]
                    if plan["built"]:
                        r["floors"][(key[0], key[1], plan["ym"])] |= plan["cells"]
                        r["open"].setdefault(key, set()).update(plan["open"])
                        r["wells"] += ws
                        r["exits"][key] = r["exits"].get(key, 0) + len(plan["built"])
                if key in r["exits"] or name in no_default:
                    continue
                # No data, or none could be connected: try an exit at a default
                # position, once on each side.
                samples, ys, bi = boxes[name][key]
                for e in EX.default_entrances(samples, ys, bi):
                    plan, ws = plan_exits(name, key, [e], used_)
                    if plan["built"]:
                        r["built"] += plan["built"]
                        r["floors"][(key[0], key[1], plan["ym"])] |= plan["cells"]
                        r["open"].setdefault(key, set()).update(plan["open"])
                        r["wells"] += ws
                        r["exits"][key] = len(plan["built"])
                        r["n_default"] += 1
                        break

        def transfer_pass():
            r["transfer"] = plan_transfers(name, used_)
            for ka, kb, res, well in r["transfer"]:
                if not res["ok"]:
                    continue
                for tag, level, cells in res["legs"]:
                    key = ka if tag == ka[0] else kb
                    r["floors"][(key[0], key[1], level)] |= cells
                if well is None:
                    # Direct connection on one level: this floor starts in box A
                    # and runs into box B, so no wall may go up inside B's
                    # concourse either, or the edge of this floor seals the inner
                    # side of the opening (this happened to R/V at Hongshulin:
                    # the passage was built but could not be entered from the
                    # Tamsui line side).
                    r["open"].setdefault(ka, set()).update(interior_of(kb))
                    r["open"].setdefault(kb, set()).update(interior_of(ka))
                else:
                    r["wells"].append(well)

        if order == "tr" and do_tr:
            transfer_pass(); exits_pass()
        else:
            exits_pass()
            if do_tr:
                transfer_pass()
        n_ok = sum(1 for t in r["transfer"] if t[2]["ok"]) if r["transfer"] else 0
        # One transfer passage is worth four exits: a missing exit only means a
        # longer walk, but two unconnected station boxes are a break.
        r["score"] = len(r["built"]) + 4 * n_ok
        return r

    for name in sorted(boxes):
        if name in skip:
            continue
        ents = entrances_by_name.get(name) or []
        # Merge duplicate nodes before assigning them to station boxes: if two
        # nodes with the same number went to two boxes, the passage planned
        # second would always hit the shaft built first.
        merged = [("/".join(g["refs"]), g["x"], g["z"])
                  for g in EX.merge_entrances(ents)]
        assigned = EX.assign_to_boxes(merged, boxes[name])
        # Try both orders at a transfer station and keep the higher score:
        # transfers first leaves room for the shaft but may block an exit or two;
        # exits first may leave no room for the transfer passage.
        best = None
        orders = ("ex", "tr") if (name not in no_transfer and len(boxes[name]) >= 2) else ("ex",)
        for order in orders:
            trial = used.copy()
            r = plan_name(name, assigned, order, trial)
            if best is None or r["score"] > best[0]["score"]:
                best = (r, trial)
        r, trial = best
        used.cells = trial.cells
        for k, cells in r["floors"].items():
            floors[k] |= cells
            no_wall.setdefault(k[:2], interior_of(k[:2]))
            kinds.setdefault(k[:2], kind_of(k[:2]))
        for k, cells in r["open"].items():
            no_wall.setdefault(k, interior_of(k)).update(cells)
        wells += r["wells"]
        exits.update(r["exits"])
        n_default += r["n_default"]
        if r["transfer"]:
            n_all += len(r["transfer"])
            n_tr += sum(1 for t in r["transfer"] if t[2]["ok"])
        report[name] = dict(built=r["built"], skipped=r["skipped"],
                            transfer=[(ka, kb, res) for ka, kb, res, _ in r["transfer"]]
                            if r["transfer"] else None)

    # ---- Floors (one per level of each station box) first, then the shafts and
    #      at-grade exits: shafts are built after the floors so their walls restore
    #      the row the passage brushed over and their doors can open; the ramps
    #      turn the two floor cells the passage brushed over into steps ----
    for (li, bi, level), cells in sorted(floors.items()):
        objs.append(make_tile(cells, no_wall[(li, bi)], level, kinds[(li, bi)], ground_at))
    objs += wells

    if verbose:
        nb = sum(len(r["built"]) for r in report.values())
        ng = sum(1 for o in wells if isinstance(o, GroundGate))
        ns = sum(len(r["skipped"]) for r in report.values())
        why = collections.Counter(s[3] for r in report.values() for s in r["skipped"])
        print(f"  Real exits: {nb} in {len(exits)} station boxes"
              + (f" ({nb - ng} stair shafts, {ng} at-grade exits" if ng else " (")
              + (f"; {n_default} are default exits for stations without data)" if n_default else ")")
              + (f"; {ns} could not be connected ("
                 + ", ".join(f"{k}: {v}" for k, v in why.most_common()) + ")"
                 if ns else ""))
        bad = [(n, r["transfer"]) for n, r in report.items()
               if r["transfer"] and any(not t[2]["ok"] for t in r["transfer"])]
        print(f"  Transfer passages: {n_tr}/{n_all}"
              + (f"; not connected: " + "; ".join(
                  f"{n} ({t[2]['reason']})" for n, ts in bad for t in ts if not t[2]["ok"])
                 if bad else ""))
    return objs, exits, report


def _dist(a, b):
    sa, ya, ia = a
    sb, yb, ib = b
    return ((sa[ia][0] - sb[ib][0]) ** 2 + (sa[ia][1] - sb[ib][1]) ** 2) ** 0.5
