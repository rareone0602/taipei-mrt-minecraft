#!/usr/bin/env python3
"""Streaming world generator: real terrain plus the whole network's structures (composition root).

The whole terrain does not fit in memory, so the world is built in batches by region
(512x512 blocks): the sample points are bucketed by region, and each region in turn
gets its terrain and structures, is written to disk and is freed.

This layer is the only place that sees every implementation: it decides which World
the blocks are written into and where the data is read from. The actual rules live in
mrt/domain, and the code that builds things lives in mrt/application.

Usage:
    ./.venv/bin/python -m cli.build_world [--corridor 160] [--lines BR ...]
    ./.venv/bin/python -m cli.build_world --rails      # also lay rails
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

# main() keeps using the original module-level constants.
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
    """mc_stations.csv -> [(refs, Chinese name, mc_x, mc_z, English name, ref string)]."""
    stations = []
    with open(config.MC_STATIONS_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            stations.append((r["ref"].split(";"), r["name_zh"] or r["name_en"],
                             int(r["mc_x"]), int(r["mc_z"]), r["name_en"], r["ref"]))
    return stations


def landmark_blocker(marks):
    """(x, y, z) -> bool: whether the cell lies inside the box of an underground hall
    (the Taiwan Railway or High Speed Rail platform level, an underground hall's floor
    slab) or inside the shaft of a switchback stair shaft. Ride signs and berths must
    avoid these. At Taipei Main Station the railway and HSR platform level sits at the
    same depth as the Bannan Line station box and swallowed the stretch of platform
    screen doors on the north side of the west end. The link stair shaft from the
    underground mall to the Tamsui-Xinyi Line concourse (from y62 down to y44) passes
    through the middle of the Bannan Line platform. The shaft is built after the
    station, so that stretch of platform surface, the platform screen doors and the
    signs all became air inside the shaft (tools/verify_rides.py found this on read-back:
    the sign's block entity was still there, but the block was air)."""
    vols = []
    for m in marks:
        if hasattr(m, "cells") and hasattr(m, "clear") and hasattr(m, "y"):
            lo = m.y - getattr(m, "thick", 1)
            vols.append((set(m.cells), lo, m.y + m.clear + 1))
        elif hasattr(m, "g0") and hasattr(m, "y_to") and hasattr(m, "bbox"):
            # Switchback stair shaft (build_concourse.ShaftStair): from the landing at the
            # shaft head to the shaft bottom, including the cap and the base slab. A link
            # stair from the underground mall once dug away a stretch of the Bannan Line
            # platform. Planning now avoids other lines; this blocks it once more, using
            # the bbox with its margin, because concourse signs should not stand in front
            # of the door at the shaft bottom either.
            x0, z0, x1, z1 = (int(v) for v in m.bbox())
            cells = {(x, z) for x in range(x0, x1 + 1) for z in range(z0, z1 + 1)}
            vols.append((cells, min(m.g0, m.y_to) - 2, max(m.g0, m.y_to) + 6))

    def blocked(x, y, z, box=None):
        return any(lo <= y <= hi and (x, z) in cells for cells, lo, hi in vols)
    return blocked


def later_section_blocker(segs, reach=48.0):
    """(x, y, z, box) -> bool: whether the cell will be overwritten by another segment's
    cross-section after the station box is built.

    The region loop builds the segments one at a time in order, and each segment first
    sweeps its cross-section and then builds its own stations. So a tunnel or viaduct of
    a later segment (li greater than the station box's) that passes through a station box
    digs out the platform. The south end of Qizhang was crossed by the Xiaobitan branch
    tunnel, and one platform at Beitou was covered by the Xinbeitou branch viaduct, both
    in this way; a ride sign placed there either floats or is swallowed by a wall. This
    follows the extent that sec_tunnel / sec_multi / sec_bridge / sec_ground each sweep,
    counts only the sample points near a station box that are actually built (the build
    mask), and records which cells later segments will overwrite, and at what heights.
    """
    boxes = {}
    for li, sg in enumerate(segs):
        for bi in sg["stn"]:
            x, z = SK.station_samples(sg, bi)[bi][:2]
            boxes[(li, bi)] = (x, z)
    hit = {}                                     # (station box segment li, x, z) -> [(y0, y1)]
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
    """(x, y, z) -> bool: the cells an attraction may not write. Attractions are built
    after the stations, exits and underground malls, so writing these cells would
    overwrite them: the base of Shin Kong Life Tower sits right above the Station Front
    Metro Mall, and a Taipei Main Station exit kiosk stands at its door.

      · Underground malls and skybridges (Tile): the actual floor and outer wall cells,
        from one below the floor to one above the roof slab
      · Exit stair shafts and at-grade exits: expanded by pad cells (the doorway needs a
        walkway), up to 6 cells above street level
      · Other landmarks (station buildings, underground halls, passages): the whole bbox
        column, or its height range
      · Line cross-sections (underground, elevated, at-grade): the sample points near an
        attraction, expanded 3 cells beyond the half-width

    Only things near an attraction are collected; outside the attractions' extents this
    always returns False.
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
        elif hasattr(m, "y") and hasattr(m, "clear"):          # Slab, RailHall
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
            # Tunnels and underground station boxes (the concourse at +7, the roof slab a
            # few cells above) are all below ground. A viaduct covers its piers from the
            # ground up, the deck and the elevated station's roof.
            if st == "tunnel":
                y0, y1 = y - 3, min(y + 14, g - 1)
            elif st == "viaduct":
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
    """Plan the whole network without building it: sampling, depth bands, profiles,
    station matching, deduplication, track offsets and the shared-trunk mask.

    Returns (segs, stations, terr). Each segment is a dict(ref, samples, ys, ground, stn,
    band, toff, hw, build, fresh). Tools and tests use this to get exactly the same
    segments as the generator (exit and transfer passage planning are both based on it)
    without generating a world.
    """
    terr = terr or Terrain()
    lines = json.load(open(config.MC_LINES_JSON, encoding="utf-8"))
    refs = refs or sorted(lines)
    stations = load_stations()
    say = print if verbose else (lambda *a, **k: None)

    # ---- Planning: every line's sample points, profile and station matching ----
    # Every line must be sampled in plan before depth bands can be assigned: whether a
    # line has to dive depends on where the other lines are, which no line can tell on
    # its own.
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
    # A terminus's alignment ends at the station node, so only half a station box could
    # be built: extend a tail track outward. The end where a branch joins the trunk
    # (Qizhang, Beitou) is not a terminus; extending it would drive into the trunk's
    # station box.
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
        say(f"Terminus tail tracks: alignment ends extended by {n_ext:.0f} m in total, "
            f"so that each terminus gets a whole station box")
    pins = TL.station_pins()
    n_osm = len(pins)
    # Stacked stations (Fuzhong, Ximen) are pinned to the shallowest band. The two lines
    # of a shared station box are pinned to the same band, and the station box reserves
    # the next band as well: the two-level box structure is taller than one band, so no
    # other line may pass beneath it.
    stk_refs = {}
    for name, ref in SK.STACKED:
        stk_refs.setdefault(name, set()).add(ref)
    pins += SK.stacked_pins(stations, stk_refs)
    # Near the station, the two lines of a shared station box do not count as occupying
    # each other (see `shared` in assign_bands).
    shared_bands = [(row[2], row[3], SK.ALLY_M, frozenset(refs))
                    for row in stations for name, refs in stk_refs.items()
                    if row[1] == name and len(refs) >= 2]
    bands = TL.assign_bands(raw, pins=pins, shared=shared_bands)
    if pins:
        say(f"Tunnel depth pins: {len(pins)} ({n_osm} restore the real vertical order from "
            f"OSM platform levels, {len(pins) - n_osm} are for stacked stations)")
    nb = np.bincount(np.concatenate([b[b >= 0] for b in bands]) if bands else [0],
                     minlength=1)
    say("Tunnel depth bands: " + ", ".join(
        f"{c * STEP / 1000:.1f} km at {TL.BAND0 + TL.BAND_DY * k} m below ground"
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
        # stn_seq is a snapshot from before deduplication: the ride system derives each
        # variant's "next station" from that variant's own station sequence (the
        # Xiaobitan branch starts at Qizhang, and deduplication removes Qizhang from the
        # branch segment straight away).
        segs.append(dict(ref=ref, samples=samples, ys=ys, ground=ground,
                         stn=stn, stn_seq=dict(stn), band=band))

    # The same station can fall on both the trunk and a branch (such as Beitou and
    # Qizhang), and the Zhonghe-Xinlu Line's shared trunk is duplicated in its entirety.
    # If the two copies are more than 10 m apart, two skewed station boxes are stacked on
    # top of each other.
    #
    # The key must include ref: a transfer station such as Zhongxiao Fuxing has a real
    # station box on both BL and BR, and deduplicating by station name alone removes the
    # whole set of transfer stations (measured: 182 -> 159 stations).
    claimed = set()
    dropped = 0
    for sg in segs:
        for bi in sorted(sg["stn"]):
            key = (sg["ref"], sg["stn"][bi][1])
            if key in claimed:
                del sg["stn"][bi]; dropped += 1
                sg.setdefault("junction", []).append(bi)     # see the build mask below
            else:
                claimed.add(key)
    if dropped:
        say(f"Skipped {dropped} stations duplicated across branches, "
            f"so that their station boxes do not overlap")

    # A snapshot taken after deduplication and before anything else touches stn: a shared
    # station box removes the partner's station from stn (G at Ximen, G at Chiang
    # Kai-shek Memorial Hall), yet later code still has to ask "which sample is Chiang
    # Kai-shek Memorial Hall on the G line" to know which way Guting's upper level opens.
    # Neighbor lookups always use the snapshot, never whatever is left.
    stn0 = [{nm: bi for bi, (_, nm, _) in sg["stn"].items()} for sg in segs]
    li_of = {id(sg): li for li, sg in enumerate(segs)}

    def idx_on(sg, name):
        """The sample index of a station on this segment (None if it is not there)."""
        return stn0[li_of[id(sg)]].get(name)

    def find(ref, name):
        for li, sg in enumerate(segs):
            if sg["ref"] == ref and stn0[li].get(name) is not None:
                return li, stn0[li][name]
        return None

    # ---- Stacked stations (domain/stacked.py): Fuzhong's two tracks go on an upper and
    # a lower level. At Ximen the Bannan Line builds a two-level island-platform station
    # box, the Songshan-Xindian Line merges into it, and both lines' rail tops are pinned
    # to the same height. This must run after deduplication (when the indices are final)
    # and before the track offsets are computed (split-level sections compute their own).
    shared_at = []
    for (name, ref), spec in SK.STACKED.items():
        if spec["kind"] == "shared" and "partner" not in spec:
            continue                                  # the primary handles the partner's entry
        key = find(ref, name)
        if key is None:
            say(f"Stacked station {name} ({ref}): station not found on the line, skipped")
            continue
        li, bi = key
        sg = segs[li]
        if AL.structure_for_ground(int(sg["ys"][bi]), int(sg["ground"][bi])) != "tunnel":
            say(f"Stacked station {name} ({ref}): not an underground station, skipped")
            continue
        j_to = idx_on(sg, spec["upper_toward"])
        if j_to is None:
            say(f"Stacked station {name} ({ref}): {spec['upper_toward']} not found "
                f"on the same segment, skipped")
            continue
        d = SK.direction_sign(bi, j_to)
        if spec["kind"] == "side":
            SK.plan_side(sg, bi, d, spec["plat"])
            say(f"Stacked station {name} ({ref}): stacked side platforms, upper level towards "
                f"{spec['upper_toward']}, platform on the "
                f"{'left' if spec['plat'] == 'left' else 'right'} of the direction of travel, "
                f"rail top y{int(sg['ys'][bi])}")
            continue
        pref = spec["partner"]
        pkey, pspec = find(pref, name), SK.STACKED.get((name, pref))
        if pkey is None or pspec is None:
            say(f"Stacked station {name} ({ref}): shared station box partner {pref} "
                f"not found, skipped")
            continue
        pli, pbi = pkey
        psg = segs[pli]
        pj_to = idx_on(psg, pspec["upper_toward"])
        if pj_to is None:
            say(f"Stacked station {name} ({pref}): {pspec['upper_toward']} not found "
                f"on the same segment, skipped")
            continue
        r = SK.plan_shared(sg, bi, d, psg, pbi, SK.direction_sign(pbi, pj_to))
        if r is None:
            say(f"Stacked station {name} ({ref}+{pref}): the two centre lines are not "
                f"{SK.SEP_MIN}–{SK.SEP_MAX} m apart, so no shared station box can be built, "
                f"skipped")
            continue
        lay, m, side, prng = r
        x, z = sg["samples"][bi][:2]
        shared_at.append((x, z, ref, pref))
        # An exit passage running along the outside of the station box grazes the partner's
        # split-level transition; that does not count as hitting another line.
        sg.setdefault("ally_segs", {})[bi] = (pli,)
        say(f"Stacked station {name} ({ref}+{pref}): shared two-level island-platform box, "
            f"centre line offset {side * m:+d} m, {pref} not built separately inside it "
            f"(samples {prng[0]}..{prng[1]}), rail top y{int(sg['ys'][bi])}")

    # Track offsets (the tracks spreading apart around an island platform at a station)
    # and tunnel half-widths must be computed after station deduplication; otherwise the
    # removed duplicate stations would still open a stray spread section in the running
    # tunnel.
    nmask = 0
    # Variants of the same line often share a long stretch of trunk (Zhonghe-Xinlu Line,
    # Danhai LRT). If the two geometries differ by a meter or two, each overwrites the
    # other's rails and breaks the trunk into fragments. So the longest variant is laid
    # first, and each later variant lays only stretches that run for 200 m or more over
    # ground that has genuinely not been laid: in other words, the branch itself. The
    # junction has a one-cell gap (there is no real turnout), but the trunk and the branch
    # are each connected.
    #
    # Cross-sections likewise are built only on stretches not already built
    # (sg["build"]). Originally the shared trunk's cross-section was built twice, which
    # was thought to only waste time. In fact the second copy was swept after the first
    # copy's stations had been built, and its duplicate stations had already been removed
    # by the deduplication above and had no spread section. So a plain 15 m wide tunnel
    # went straight through a 25 m wide station box: the platform, the platform screen
    # doors and the concourse floor slab were all dug into air, and the roof lining lay
    # across at concourse height. The 12 stations on the Zhonghe-Xinlu Line's shared
    # trunk (Dingxi to Daqiaotou) were wiped out entirely this way, and Qizhang, Beitou
    # and seven Danhai LRT stations were partly wiped out. This showed up only in a
    # cross-section cut from the world save; the build log listed every station as done.
    # Pocket track geometry follows OSM first (data/sidings.json, fetched by
    # fetch_sidings); failing that, it uses the hand-entered distances in
    # domain/stacked.POCKETS.
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
        # Pocket tracks: the main tracks spread apart in place and the third track is
        # recorded in extras. This must run after track_offsets and before hw.
        for pk in SK.POCKETS:
            if pk["ref"] != sg["ref"]:
                continue
            ia, ib = idx_on(sg, pk["a"]), idx_on(sg, pk["b"])
            if ia is None or ib is None:
                continue
            rng, src = None, "hand-entered distances"
            way = sidings.get(pk.get("osm"))
            if way is not None:
                lo_i, hi_i = min(ia, ib) - 400, max(ia, ib) + 400
                j0 = SK.nearest(samples, way["mc"][0][0], way["mc"][0][1], max(0, lo_i), min(len(samples) - 1, hi_i))
                j1 = SK.nearest(samples, way["mc"][-1][0], way["mc"][-1][1], max(0, lo_i), min(len(samples) - 1, hi_i))
                rng, src = (min(j0, j1), max(j0, j1)), f"OSM way {way['id']}"
            r = SK.plan_pocket(sg, ia, ib, pk["start"], pk["length"], rng=rng)
            if r is None:
                say(f"Pocket track {pk['a']}–{pk['b']}: does not fit between the two stations, "
                    f"skipped")
                continue
            x0, z0 = samples[r[0]][:2]
            d0, d1 = sorted((abs(r[0] - ia) * STEP, abs(r[1] - ia) * STEP))
            say(f"Pocket track {pk['a']}–{pk['b']} ({src}): third track "
                f"{(r[1] - r[0]) * STEP:.0f} m long, {d0:.0f}–{d1:.0f} m from the centre "
                f"of the {pk['a']} station box, at ({x0:.0f},{z0:.0f})")
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
        # Inside a shared station box, the partner line's cross-section is not built.
        for i in sg.get("nobuild", ()):
            build[i] = False
        # Nor is a branch built on the stretch at its junction station. The station is
        # built on the trunk (deduplication above), but if the branch geometry strays 8 m
        # or more from the trunk within the station box, the "not yet built" mask would
        # sweep another tunnel or viaduct through it, after the trunk station has been
        # built. That is how the Xiaobitan branch tunnel dug away half the platform at the
        # south end of Qizhang, and how the Xinbeitou branch viaduct covered half the east
        # platform at Beitou (caught when the ride sign berths read back as places nobody
        # could stand). The branch starts outside the station box's end wall, and rails
        # are not laid on that stretch either.
        jhalf = int(AL.PLATFORM_LEN / 2 / STEP) + 4
        for bj in sg.get("junction", ()):
            for i in range(max(0, bj - jhalf), min(len(samples), bj + jhalf + 1)):
                build[i] = False
                fresh[i] = False
        sg["build"] = build
        sg["fresh"] = fresh                  # rails are laid by this mask too; see main()
        nmask += len(samples) - sum(build)
    if nmask:
        say(f"Corridors shared by a branch and the trunk are built once: "
            f"skipped {nmask * STEP / 1000:.1f} km of duplicate cross-section")

    # A depth band assignment without conflicts does not mean the box structures do not
    # overlap: a stacked station's two-level box structure is taller than one band, and a
    # pinned, flattened profile leaves its band's depth. Check again against each point's
    # actual box structure extent. An overlap deeper than the lining is a real collision
    # and must be reported loudly; one that only bites into the lining is reported without
    # a warning, because a warning that is always on is no warning at all.
    bad = TL.check_clearance(segs, shared_at)
    deep = [b for b in bad if b[8] > TL.LINING_DY]
    graze = len(bad) - len(deep)
    if deep:
        say(f"warning: cross-line clearance: underground structures of different lines "
            f"overlap in {len(deep)} places: "
            + "; ".join(f"{a}×{b} ({x:.0f},{z:.0f}) y{a0}..{a1} / y{b0}..{b1}, {d}-block overlap"
                        for a, b, x, z, a0, a1, b0, b1, d in deep[:6]))
    elif graze:
        say(f"Cross-line clearance: no box structure intrudes into another line; {graze} places "
            f"run one directly above the other and share a row or two of lining "
            f"({'; '.join(f'{a}×{b} ({x:.0f},{z:.0f}) {d}-block overlap' for a, b, x, z, *_, d in bad[:4])})")
    else:
        say("Cross-line clearance: no underground structures of different lines overlap")
    return segs, stations, terr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=config.DEFAULT_SAVE)
    ap.add_argument("--corridor", type=int, default=96,
                    help="Half-width of the full-terrain corridor, in metres")
    ap.add_argument("--fade", type=int, default=64,
                    help="Width of the band beyond the corridor that fades back to flat, in metres")
    ap.add_argument("--lines", nargs="*", default=None)
    ap.add_argument("--bbox", nargs=4, type=int, metavar=("X0", "Z0", "X1", "Z1"),
                    help="Only generate the regions that fall within this box (for testing "
                         "one station area without waiting 30 minutes to see Taipei Main Station)")
    ap.add_argument("--rails", action="store_true",
                    help="Also lay rails. Off by default: the track bed is left bare, "
                         "so that you can lay track with a mod")
    ap.add_argument("--sights", nargs="*", default=None, metavar="ID",
                    help="Build only these attractions (ids from data/attractions.json); "
                         "without it, all are built")
    ap.add_argument("--no-sights", action="store_true", help="Build no attractions")
    a = ap.parse_args()
    outer = a.corridor + a.fade

    segs, stations, terr = plan_segments(a.lines)

    # Rails are not laid by default: the track bed (smooth_stone) is kept, and whether and
    # how to lay track is left to the player's mods. Only --rails lays them. What gets laid
    # follows plan_segments' sg["fresh"]: only stretches of 200 m or more that have
    # genuinely not been laid, so the trunk and the branches are each connected.
    rail_b = {}
    nrail = nskip = 0
    if a.rails:
        for sg in segs:
            samples, fresh = sg["samples"], sg["fresh"]
            # One strand per track: each of the two main tracks runs its whole length
            # (split-level sections follow their own track offset and rail top), and a
            # pocket track's third track is a separate strand.
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
        print(f"Rails: {nrail:,} blocks (double track, including powered rails)"
              + (f", {nskip:,} not relaid where they overlap the trunk" if nskip else ""))
    else:
        print("No rails laid (use --rails to lay them); the track bed stays smooth_stone")

    by_ref = {}
    for sg in segs:
        e = by_ref.setdefault(sg["ref"], [0.0, 0, 999, -999, 999, -999])
        e[0] += len(sg["samples"]) * STEP / 1000
        e[1] += len(sg["stn"])
        e[2] = min(e[2], int(sg["ys"].min())); e[3] = max(e[3], int(sg["ys"].max()))
        e[4] = min(e[4], int(sg["ground"].min())); e[5] = max(e[5], int(sg["ground"].max()))
    for ref in sorted(by_ref):
        km, ns, y0, y1, g0, g1 = by_ref[ref]
        print(f"{ref:<3} {km:>6.2f} km  rail top y{y0:>3}~{y1:<3}  "
              f"ground y{g0:>3}~{g1:<3}  stations {ns}")
    print(f"\nTotal {sum(v[0] for v in by_ref.values()):.1f} km, "
          f"{sum(v[1] for v in by_ref.values())} stations")

    # ---- Bucket by region ----
    # A station's reach is no longer just its platform length: a long exit stair can
    # extend 76 m, and if the bucket radius is too small, those regions never call
    # build_station and the stair is cut off.
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
            if i % 8 == 0:                        # the distance field needs no point every 0.5 m
                for rx in range((x - outer) >> 9, ((x + outer) >> 9) + 1):
                    for rz in range((z - outer) >> 9, ((z + outer) >> 9) + 1):
                        terr_pts.setdefault((rx, rz), []).append((x, z))

    # Line colors (OSM `colour`, the same data as the network map in the README): exit
    # signs, ride signs and the color bands inside station boxes all take them from here.
    colours = NW.line_colours(json.load(open(config.MC_LINES_JSON, encoding="utf-8")))

    # ---- Landmarks: things not swept along the line ----
    # Station buildings, underground halls and exits at their real positions.
    marks, real_exits = LM.for_world(segs, stations, terr, colours=colours)
    mark_b = {}
    for m in marks:
        mx0, mz0, mx1, mz1 = m.bbox()
        for rx in range(mx0 >> 9, (mx1 >> 9) + 1):
            for rz in range(mz0 >> 9, (mz1 >> 9) + 1):
                mark_b.setdefault((rx, rz), []).append(m)
    if marks:
        # Landmarks often reach beyond the line corridor (the Taipei Main Station
        # building is 240 m from the Bannan Line). Terrain outside the corridor is flat,
        # so a building would squat on a platform at the wrong height. Feed the
        # landmarks' extents into the distance field as well, so that real terrain is
        # generated there.
        for m in marks:
            # An underground mall lies entirely below the ground surface and needs no
            # real terrain. It is also cut into hundreds of pieces, and feeding every
            # piece into the distance field would add an order of magnitude more points
            # and make the terrain slower.
            if getattr(m, "underground", False):
                continue
            mx0, mz0, mx1, mz1 = m.bbox()
            for x in range(mx0, mx1 + 1, 8):
                for z in range(mz0, mz1 + 1, 8):
                    for rx in range((x - outer) >> 9, ((x + outer) >> 9) + 1):
                        for rz in range((z - outer) >> 9, ((z + outer) >> 9) + 1):
                            terr_pts.setdefault((rx, rz), []).append((x, z))
        print(f"Landmarks: {len(marks)}, covering {len(mark_b)} regions")

    # ---- Attractions (application/attractions/) ----
    # Taipei 101, Chiang Kai-shek Memorial Hall, the city gates and others. Positions and footprints come from OSM (data/attractions.json); each attraction's
    # module writes its appearance from published architectural facts.
    sights = [] if a.no_sights else AT.for_world(stations, only=a.sights)
    sight_b = {}
    for s_ in sights:
        sx0, sz0, sx1, sz1 = s_.bbox()
        for rx in range(sx0 >> 9, (sx1 >> 9) + 1):
            for rz in range(sz0 >> 9, (sz1 >> 9) + 1):
                sight_b.setdefault((rx, rz), []).append(s_)
        # Attractions need real terrain around them. The extent gets an extra
        # terrain_margin (48 m by default; the Grand Hotel on the slope of Mount Jiantan
        # gets a large one, so that the mountain behind it is not shaved into a slope
        # behind the building), so that the fade ring does not cut in at the building's foot.
        tm = int(getattr(s_, "terrain_margin", 48))
        for x in range(sx0 - tm, sx1 + tm + 1, 8):
            for z in range(sz0 - tm, sz1 + tm + 1, 8):
                for rx in range((x - outer) >> 9, ((x + outer) >> 9) + 1):
                    for rz in range((z - outer) >> 9, ((z + outer) >> 9) + 1):
                        terr_pts.setdefault((rx, rz), []).append((x, z))
    if sights:
        print(f"Attractions: {len(sights)}, covering {len(sight_b)} regions")

    # ---- Ride system: berths (domain/network.py) ----
    # One berth for each line and direction of travel at each station box. The ride signs
    # on the platforms and the datapack's teleport destinations both come from this one
    # plan, computed once.
    blocked = landmark_blocker(marks)
    later = later_section_blocker(segs)
    net, berths = NW.plan_berths(
        segs, blocked=lambda x, y, z, box=None: blocked(x, y, z) or later(x, y, z, box))
    n_slot = sum(len(b.slots) for b in berths)
    print(f"Ride system: {sum(1 for s in net.values() if s.box is not None)} stations, "
          f"{len(berths)} platform edges, {n_slot} ride signs, {len(NW.rides(net, berths))} rides")
    # Signs are placed per station box (application/signage.py): box.key is the (segment
    # index, sample index) of the station box that build_station builds, and the platform
    # edges of both lines of a shared stacked station are in the primary's station box.
    berths_of = collections.defaultdict(list)
    for b in berths:
        berths_of[b.box.key].append(b)

    # ---- Spawn point (rules in application/spawn.py) ----
    # Outside the door of a Taipei Main Station metro exit kiosk. The ground height at the doorway must match what is actually built. Outside the
    # corridor the terrain fades back to flat, so it is computed with the same formula and
    # the same distance field as terrain_chunk, not read from the save.
    blend_cache = {}

    def built_ground(x, z):
        rx, rz = int(x) >> 9, int(z) >> 9
        pts = terr_pts.get((rx, rz))
        if not pts:
            return FLAT_Y                       # no terrain in this region: superflat background
        if (rx, rz) not in blend_cache:
            blend_cache[(rx, rz)] = blend_field(pts, rx, rz, a.corridor, outer)
        return int(BW.surface_y(terr, blend_cache[(rx, rz)], rx, rz, x, z))

    spawn = SP.plan_spawn(marks, stations, built_ground)
    if spawn is None:
        # If no kiosk qualifies, fall back to the ground right above the Taipei Main
        # Station metro node (at least a cell the heightmap can compute).
        nx, nz = SP.station_node(stations) or (0, 0)
        spawn = dict(x=nx, y=built_ground(nx, nz) + 1, z=nz, facing=None,
                     why="no suitable exit kiosk found, so fell back to the ground "
                         "above the metro station node")
    # Finalizing the attractions (ground floor level, viewpoints) must use the same
    # "built ground", and must happen before the cache is cleared.
    sight_keep = sight_keepout(marks, segs, sights)
    if sights:
        AT.plan_all(sights, built_ground, sight_keep)
    # Clear the contents only and keep the variable: an attraction's build() may query
    # site.g() again (built_ground still needs this cache), and deleting it would raise
    # NameError: free variable 'blend_cache'.
    blend_cache.clear()

    regions = sorted(set(struct_b) | set(terr_pts) | set(mark_b) | set(sight_b))
    if a.bbox:
        x0, z0, x1, z1 = a.bbox
        keep = [(rx, rz) for rx, rz in regions
                if rx * 512 <= x1 and (rx + 1) * 512 > x0
                and rz * 512 <= z1 and (rz + 1) * 512 > z0]
        print(f"--bbox {x0},{z0}..{x1},{z1}: keeping {len(keep)} of {len(regions)} regions")
        regions = keep
        if (spawn["x"] >> 9, spawn["z"] >> 9) not in set(keep):
            print(f"warning: the spawn point ({spawn['x']},{spawn['z']}) is outside the "
                  f"--bbox area, so the game will start you on empty superflat ground")
    print(f"Generating {len(regions)} regions "
          f"({len(terr_pts)} with terrain across the whole network)")

    shutil.rmtree(a.out, ignore_errors=True)

    # ---- The ride system's datapack ----
    # The functions signs run when clicked, the route map dialog, the first-join message
    # and the station entry notices. It uses the same net and berths as the signs (ids come from ride_fn and the related
    # functions in domain/network.py). It must be written after the old save is removed;
    # level.dat's DataPacks already lists it as enabled.
    colours = NW.line_colours(json.load(open(config.MC_LINES_JSON, encoding="utf-8")))
    sight_entries = AT.datapack_entries(sights)
    spec = RP.build_spec(net, berths, colours, sights=sight_entries)
    # Attractions within walking distance of each station (nearest first): an attraction
    # sign stands next to the ticket machines in the concourse.
    near_sights = collections.defaultdict(list)
    for e in sorted(sight_entries, key=lambda e: e["station"][2] if e["station"] else 1e9):
        if e["station"]:
            near_sights[e["station"][0]].append(e)
    info = DP.write_datapack(a.out, spec)
    print(f"Datapack {config.DATAPACK_NAME}: {info['functions']} functions, "
          f"{info['dialogs']} dialogs, {len(spec['triggers'])} route map buttons, "
          f"{len(spec['areas'])} station entry notice areas")
    for msg in spec["warnings"]:
        print("  warning: " + msg)

    t0 = time.time(); nch = 0; nsign = 0; nbytes = 0
    sight_drop = {}
    for n, (rx, rz) in enumerate(regions, 1):
        w = World(a.out, name=config.WORLD_NAME)
        w._region_filter = (rx, rz)

        pts = terr_pts.get((rx, rz))
        if pts:
            bf = blend_field(pts, rx, rz, a.corridor, outer)
            if bf.max() > 0:
                per = 16 // BLEND_CELL          # distance field cells per chunk
                for cx in range(rx * 32, rx * 32 + 32):
                    bi = (cx - rx * 32) * per
                    for cz in range(rz * 32, rz * 32 + 32):
                        bj = (cz - rz * 32) * per
                        # All-zero weights mean flat ground; writing it out only wastes space.
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
                if not build[i]:            # the trunk already built this stretch; see above
                    continue
                x, z, ux, uz, _ = samples[i]
                nx, nz = -uz, ux
                y, g = int(ys[i]), int(gnd[i])
                hw = sg["hw"][i]
                st = AL.structure_for_ground(y, g)
                if st == "tunnel":
                    if multi is not None and multi[i]:
                        # Split-level transitions and pocket tracks: take the union of the
                        # multi-track, multi-height cross-sections point by point.
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
            for x, z, nx, nz, trs in lights:  # after digging, or the next point digs them out
                for off, ty in trs:
                    w.set(round(x + nx * off), ty + 6, round(z + nz * off), BL.LAMP)
            for i in idxs:
                if i in stn:
                    under = AL.structure_for_ground(int(ys[i]), int(gnd[i])) == "tunnel"
                    # Stations with real exits do not get the template stairs (see
                    # application/build_exits.py). Stacked stations use the station box's
                    # frame (for a shared station box, the frame of the two lines' center
                    # line) and the two-level layout.
                    BL.build_station(w, SK.station_samples(sg, i), ys, i, under,
                                     label=stn[i], grounds=gnd,
                                     access=(li, i) not in real_exits,
                                     stacked=sg.get("stacked", {}).get(i))
                    # Ride signs, line color bands and concourse wayfinding: these go in
                    # after the station box is built (a sign replaces the glass in that
                    # platform screen door cell). A station box that spans two regions gets
                    # them placed once in each.
                    SG.station_signage(w, berths_of.get((li, i), ()), net, colours,
                                       grounds=gnd, blocked=blocked,
                                       sights=near_sights.get(stn[i][1], ()))

        # Landmarks are built after the structures along the line: the station box
        # structures are dug first, so that the halls can connect into them.
        for m in mark_b.get((rx, rz), ()):
            m.build(w)

        # Attractions come after landmarks: the exits and underground malls are already in
        # place, and every attraction write passes through the keep-out guard.
        for s_ in sight_b.get((rx, rz), ()):
            dropped = AT.build(s_, w, sight_keep)
            if dropped:
                sight_drop[s_.id] = sight_drop.get(s_.id, 0) + dropped

        # Rails must be laid last: station excavation and stairs both overwrite the track bed.
        rr = rail_b.get((rx, rz), ())
        cells = {(a, b, c) for a, b, c, _, _ in rr}
        for bx, by, bz, shape, powered in rr:
            # Put a support block under every rail. To keep sloped rails on straight
            # stretches, rails.py shifts height changes a few cells forward or back, and
            # the rails on those shifted cells end up one block above the track bed,
            # floating. Powered rails sit on a redstone block instead, for power; leave the
            # cell alone if it already holds another track's rail.
            if (bx, by - 1, bz) not in cells:
                w.set(bx, by - 1, bz,
                      "minecraft:redstone_block" if powered else BL.DECK)
            w.set(bx, by, bz, rails.block_string(shape, powered))

        nsign += sum(len(c.bes) for c in w.chunks.values())
        nch += len(w.chunks)
        nbytes += w.save_region(rx, rz)
        if n % 40 == 0 or n == len(regions):
            el = time.time() - t0
            print(f"  [{n}/{len(regions)}] {el:>5.0f}s  {nch:>7,} chunks  "
                  f"{nbytes/1e6:>6.0f} MB  about {el/n*(len(regions)-n):.0f}s left")

    w = World(a.out, name=config.WORLD_NAME,
              spawn=(spawn["x"], spawn["y"], spawn["z"]), spawn_facing=spawn["facing"])
    w._write_level()
    print(f"\nDone: {nch:,} chunks, {nsign:,} signs, {nbytes/1e6:.0f} MB, {time.time()-t0:.0f}s")
    for sid, n in sorted(sight_drop.items()):
        print(f"  Attraction {sid}: keep-out zones (exits, underground malls, lines) "
              f"blocked {n:,} block writes")
    print(f"Spawn point ({spawn['x']},{spawn['y']},{spawn['z']})"
          + (f" facing ({spawn['facing'][0]},{spawn['facing'][1]})" if spawn["facing"] else "")
          + f": {spawn['why']}")


if __name__ == "__main__":
    main()
