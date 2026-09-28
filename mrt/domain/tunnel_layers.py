#!/usr/bin/env python3
"""Tunnel layering: decides which depth band each underground segment runs in.

The original approach gave each line one fixed depth (the build_world.TUNNEL_DEPTH
constant). It had two problems:

  1. Whether two lines needed separate bands was decided from their current vertical
     separation, but that separation is itself produced by the banding: circular
     reasoning. BL-O and A-G were missed this way and actually overlapped; the line
     built later overwrote the rails of the one built earlier, and the rail check
     reported "the other side does not connect back".
  2. Even judged by horizontal distance alone, the four lines BL / G / O / R all cross
     one another downtown (the complete graph K4), so one fixed depth per line needs
     four layers, and the deepest line would be dug 60 m underground. The real Taipei
     Metro is at most about 30 m deep.

A real metro line does not pick one depth for its whole length: **it normally runs
shallow and dives only where it really has to cross another line**. So bands are
assigned per sample instead: sweeping along the line, it changes band only when the
current depth band is taken by another line, and it looks ahead to pick the band that
lasts longest, so as not to keep going up and down.

The 4% grade limit of the vertical profile automatically stretches each band change
into a ramp; no separate handling is needed.

Usage (analysis report): ./.venv/bin/python -m mrt.domain.tunnel_layers
"""
import os, json, math
import numpy as np

from mrt import config
from mrt.domain import alignment as AL

CELL_M   = 30      # Spatial hash cell size (meters); with the 8 neighboring cells this gives at
                   # least 30 m of horizontal clearance
BAND0    = 15      # Depth of band 0 (meters)
BAND_DY  = 15      # Band spacing. A station box cross-section spans dy -2..10, 13 blocks, so it
                   # takes 15 m to keep them from overlapping
LOOK_M   = 1500    # How far ahead to look when changing band, to pick the one that lasts longest
MAXBAND  = 8
RAMP_M   = BAND_DY / AL.MAX_GRADE   # Ramp length to change by one band: 15 m / 4% = 375 m
PRE_EVERY = 20     # Samples between look-aheads for an early band change (every 10 m is enough)


def band_depth(band):
    """Map a depth band to a tunnel offset (negative, meters)."""
    return -(BAND0 + BAND_DY * np.maximum(np.asarray(band), 0))


def assign_bands(raw, cell=CELL_M, look_m=LOOK_M, pins=(), shared=()):
    """raw: [(ref, samples), ...], where samples is the output of AL.resample.

    Return a list as long as raw; each element is that segment's per-sample int array
    of depth bands (-1 where it is not underground). Longer segments are assigned first,
    and shorter ones give way.

    pins is [(x, z, radius, ref, band)], used to fix known real vertical relationships.
    The greedy algorithm only knows that lines must not collide, not which one is on top
    in reality. For example, at Taipei Main Station the Bannan Line is at B3 and the
    Tamsui-Xinyi Line at B4, yet the algorithm may produce the opposite. A pin first
    reserves the band within its range for the given line, and other lines must go around.

    **A band change must start one ramp length early.** A depth band is only a target
    depth; the real elevation comes from the 4% grade envelope of the vertical profile,
    and changing by one band takes a 375 m ramp. Originally the change happened only at
    the cell where the current band became taken, so the ramp began its descent at the
    conflict point, and the conflict point itself was still partway down. That is how the
    Songshan-Xindian Line at Songjiang Nanjing stopped at 27 m underground, only 3 m above
    the Zhonghe-Xinlu Line's station box at 30 m, and the two box structures overlapped.
    So it looks one ramp length ahead: if the current band will be taken within 375 m,
    it changes now; and the old band stays counted as taken until the ramp is complete,
    so that no other line slips in under the ramp.

    shared is [(x, z, radius, {ref, ...})]: lines that share one station box (the Bannan
    Line and the Songshan-Xindian Line at Ximen) sit in the same band there by design, and
    do not count as taking it from one another. Without this, the Songshan-Xindian Line's
    pin scares the Bannan Line away: looking ahead, the Bannan Line sees band 0 taken by G
    at Ximen, dives to band 2 between Taipei Main Station and Ximen, and is then pulled back
    to band 0 by its own pin. The vertical profile therefore drags both Ximen and Taipei
    Main Station 13 m lower, and the Bannan Line at Taipei Main Station runs straight into
    the Tamsui-Xinyi Line's station box.
    """
    look = int(look_m / AL.STEP)
    ramp = int(RAMP_M / AL.STEP)
    occ = {}                       # cell -> {band: ref}

    ally = {}                      # cell -> lines that do not take bands from one another here
    for sx, sz, sr, refs in shared:
        c0 = int(math.floor((sx - sr) / cell)); c1 = int(math.floor((sx + sr) / cell))
        d0 = int(math.floor((sz - sr) / cell)); d1 = int(math.floor((sz + sr) / cell))
        for cx in range(c0, c1 + 1):
            for cz in range(d0, d1 + 1):
                ally.setdefault((cx, cz), set()).update(refs)

    pin_by_ref = {}
    for px, pz, pr, pref, pb in pins:
        pin_by_ref.setdefault(pref, []).append((px, pz, pr * pr, pb))
        c0 = int(math.floor((px - pr) / cell)); c1 = int(math.floor((px + pr) / cell))
        d0 = int(math.floor((pz - pr) / cell)); d1 = int(math.floor((pz + pr) / cell))
        for cx in range(c0, c1 + 1):
            for cz in range(d0, d1 + 1):
                occ.setdefault((cx, cz), {})[pb] = pref
    order = sorted(range(len(raw)), key=lambda i: -len(raw[i][1]))
    out = [None] * len(raw)

    def taken_at(ck, ref):
        t = set()
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                c = (ck[0] + dx, ck[1] + dz)
                al = ally.get(c)
                for b, r in occ.get(c, {}).items():
                    if r != ref and not (al is not None and ref in al and r in al):
                        t.add(b)
        return t

    for idx in order:
        ref, samples = raw[idx]
        n = len(samples)
        arr = np.full(n, -1, dtype=np.int8)
        cks = [None] * n
        for i, s in enumerate(samples):
            if s[4] == "tunnel":
                cks[i] = (int(math.floor(s[0] / cell)), int(math.floor(s[1] / cell)))
        def taken_within(i0, band, span):
            """Tell whether another line takes band in i0..i0+span (checked every 20 samples)."""
            for j in range(i0, min(n, i0 + span + 1), PRE_EVERY):
                if cks[j] is not None and band in taken_at(cks[j], ref):
                    return True
            return False

        cur = None
        hold = {}                               # old band -> sample index where its ramp ends
        for i in range(n):
            s = samples[i]
            ck = cks[i]
            if ck is None:                      # Out of the tunnel; pick again at the next one
                cur = None
                hold = {}
                continue
            t = taken_at(ck, ref)
            forced = None
            for px, pz, r2, pb in pin_by_ref.get(ref, ()):
                if (s[0] - px) ** 2 + (s[1] - pz) ** 2 <= r2:
                    forced = pb
                    break
            prev = cur
            if forced is not None:
                cur = forced
            elif cur is None or cur in t or (
                    i % PRE_EVERY == 0 and taken_within(i, cur, ramp)):
                # Look ahead: how far each candidate band lasts; take the farthest (shallowest on a tie)
                best, best_d = 0, -1
                for b in range(MAXBAND):
                    if b in t:
                        continue
                    d = look
                    for j in range(i, min(n, i + look)):
                        if cks[j] is not None and b in taken_at(cks[j], ref):
                            d = j - i
                            break
                    if d > best_d:
                        best, best_d = b, d
                    if d >= look:
                        break
                cur = best
            if prev is not None and prev != cur:
                hold[prev] = i + ramp * abs(cur - prev)
            arr[i] = cur
            occ.setdefault(ck, {})[cur] = ref
            for b in list(hold):                # Ramp not complete: the old band stays taken
                if i <= hold[b]:
                    occ.setdefault(ck, {})[b] = ref
                else:
                    del hold[b]
        out[idx] = arr
    return out


# The top and bottom edges of a box structure are each a few rows of lining or base slab,
# not walkable space. Two box structures that overlap by no more than this depth simply
# share a wall of bricks. A cross-section cut through the Bannan Line and the
# Songshan-Xindian Line north of Ximen showed it: the two box structures are only 11 m apart
# horizontally and overlap by 2 blocks vertically, the Bannan Line's base slab and the roof
# slab of the descending Songshan-Xindian Line share the same row, each keeps its full
# clearance, and the air on the two sides does not connect.
LINING_DY = 2


def check_clearance(segs, shared=(), cell=16, every=4, shared_r=None):
    """Check cross-line clearance on the actual geometry: the underground structures of two
    different lines must never overlap in space.

    The depth band check only knows that bands differ. The two-level box structure of a
    stacked station is taller than one band, and a flattened (pinned) vertical profile may
    leave its band's depth, so this computes it again from the real extent of the box
    structure at each point (half-width and top and bottom edges).
    segs are the segments planned by cli (samples / ys / ground / stn / hw, optionally
    frames / stacked / y_side). shared is [(x, z, ref_a, ref_b)]: two lines that share
    one station box overlap there by design within shared_r, which is not a conflict. The
    default is the length of the two-level box structure plus the layer transition (half
    a station box + SPLIT_M). Only the stretch that really is one structure is exempt;
    beyond it the two lines are two separate tunnels, and a collision must show. The ally
    radius of the depth bands (stacked.ALLY_M) is slightly larger than this because it
    also needs a margin for the spatial hash.

    Return [(ref_a, ref_b, x, z, ya0, ya1, yb0, yb1, overlap in blocks), ...], at most
    one entry per cell per pair of lines. An overlap of <= LINING_DY blocks only touches
    the lining, and the caller may treat it as passing flush; anything deeper really does
    run into the other line's space.
    """
    from mrt.domain.stacked import BOX_BOTTOM_DY, SPLIT_M
    if shared_r is None:
        shared_r = AL.PLATFORM_LEN / 2 + SPLIT_M
    half = int(AL.PLATFORM_LEN / 2 / AL.STEP)
    grid = {}
    for sg in segs:
        samples, ys, gnd = sg["samples"], sg["ys"], sg["ground"]
        hws = sg.get("hw")
        frames, stk, yside = sg.get("frames", {}), sg.get("stacked", {}), sg.get("y_side")
        nob = sg.get("nobuild", set())
        n = len(samples)
        rng = [(max(0, bi - half), min(n - 1, bi + half), bi) for bi in sg.get("stn", ())]
        for i in range(0, n, every):
            y, g = int(ys[i]), int(gnd[i])
            if AL.structure_for_ground(y, g) != "tunnel" or i in nob:
                continue
            bi = next((b for lo, hi, b in rng if lo <= i <= hi), None)
            if bi is not None:
                x, z = frames.get(bi, samples)[i][:2]
                r = AL.BOX_HALF + 1
                y0 = y + (BOX_BOTTOM_DY if bi in stk else -2)
                y1 = y + AL.BOX_TOP_DY
            else:
                x, z = samples[i][0], samples[i][1]
                r = (int(hws[i]) if hws is not None else 5) + 2
                ylo = y if yside is None else min(y, int(yside[1][i]), int(yside[-1][i]))
                y0, y1 = ylo - 2, y + 7
            grid.setdefault((int(x // cell), int(z // cell)), []).append(
                (sg["ref"], x, z, r, y0, y1))

    def exempt(ra, rb, x, z):
        return any({ra, rb} == {a, b} and math.hypot(x - sx, z - sz) <= shared_r
                   for sx, sz, a, b in shared)

    bad, seen = [], set()
    for (cx, cz), pts in grid.items():
        near = []
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                near += grid.get((cx + dx, cz + dz), ())
        for ra, xa, za, rra, a0, a1 in pts:
            for rb, xb, zb, rrb, b0, b1 in near:
                if rb <= ra or (ra, rb, cx, cz) in seen:
                    continue
                # The top and bottom edges are both lining rows; two box structures sharing one
                # row of lining do not count as overlapping (the box structures of the Bannan Line
                # and the Songshan-Xindian Line pass flush like this north of Ximen)
                if math.hypot(xa - xb, za - zb) < rra + rrb and a0 < b1 and b0 < a1 \
                        and not exempt(ra, rb, xa, za):
                    seen.add((ra, rb, cx, cz))
                    bad.append((ra, rb, xa, za, a0, a1, b0, b1,
                                min(a1, b1) - max(a0, b0)))
    return bad


# ---------- Everything below is only the analysis report ----------

PIN_RADIUS = AL.PLATFORM_LEN / 2 + RAMP_M     # 35 + 375 = 410 m


def station_pins(min_margin=15.0, ratio=2.0, radius=PIN_RADIUS, verbose=False):
    """Infer the real vertical order from the level tags of OSM platforms and turn it into pins.

    A pin's radius must cover half a station box plus one ramp: the depth band may change
    as soon as it leaves the pin's range, and a band change takes a 375 m ramp. With a
    radius of only 120 m, the ramp reaches into the station box and pulls a station box
    pinned at B2 down to 21 m underground (measured on the Tamsui-Xinyi Line at Zhongshan).

    Only transfer stations where one station has two or more lines at different levels
    are handled: that is exactly where the greedy algorithm may guess wrong while reality
    has a clear answer. Which line a platform belongs to is decided by geometry (OSM's
    station_ref gives only the station code, not the platform's line); platforms that
    cannot be decided reliably are skipped rather than guessed.
    """
    import re, collections
    pf = config.PLATFORM_LEVELS_JSON
    if not os.path.exists(pf):
        return []
    items = json.load(open(pf, encoding="utf-8"))["items"]
    lines = json.load(open(config.MC_LINES_JSON,
                           encoding="utf-8"))

    def dist_to(ref, cx, cz):
        best = 1e18
        for v in lines.get(ref, []):
            p = v["points"]
            for i in range(len(p) - 1):
                ax, az = p[i]; bx, bz = p[i + 1]
                vx, vz = bx - ax, bz - az
                L = vx * vx + vz * vz
                t = 0.0 if L == 0 else max(0, min(1, ((cx-ax)*vx + (cz-az)*vz) / L))
                best = min(best, math.hypot(cx - (ax + t*vx), cz - (az + t*vz)))
        return best

    byst = collections.defaultdict(dict)
    for p in items:
        try:
            lv = int(str(p.get("level")).split(";")[0])
        except (TypeError, ValueError):
            continue
        if lv >= 0 or not p.get("station_ref") or not p.get("station"):
            continue
        cands = sorted({m.group(0) for t in
                        str(p["station_ref"]).replace(",", ";").split(";")
                        for m in [re.match(r"[A-Z]+", t.strip())] if m})
        cands = [c for c in cands if c in lines]
        if len(cands) < 2:
            continue
        cx, cz = p["mc_x"], p["mc_z"]
        ds = sorted((dist_to(c, cx, cz), c) for c in cands)
        if ds[0][0] > min_margin or ds[1][0] < ratio * max(ds[0][0], 1.0):
            continue                       # Cannot be decided reliably; skip
        st = p["station"]
        prev = byst[st].get(ds[0][1])
        if prev is None or lv < prev[0]:
            byst[st][ds[0][1]] = (lv, cx, cz)

    pins = []
    for st, d in sorted(byst.items()):
        if len(d) < 2 or len({v[0] for v in d.values()}) < 2:
            continue                       # Only one line, or equal depths; no pin needed
        order = sorted(d.items(), key=lambda kv: -kv[1][0])   # Higher level on top
        for band, (ref, (lv, cx, cz)) in enumerate(order):
            pins.append((cx, cz, radius, ref, band))
            if verbose:
                print(f"  pin {st:<8} {ref:<3} level {lv} -> band {band}  ({cx},{cz})")
    return pins


def _plan_raw():
    lines = json.load(open(config.MC_LINES_JSON, encoding="utf-8"))
    raw = []
    for ref in sorted(lines):
        for v in AL.select_variants(lines[ref]):
            pts = [tuple(p) for p in v["points"]]
            kinds = v.get("kinds") or ["ground"] * len(pts)
            pts, kinds = AL.drop_reversal(pts, kinds)
            samples = AL.resample(pts, kinds, AL.STEP)
            if len(samples) >= 10:
                raw.append((ref, samples))
    return raw


def main():
    raw = _plan_raw()
    nu = sum(int((np.array([s[4] for s in sm]) == "tunnel").sum()) for _, sm in raw)
    print(f"{len(raw)} segments, {nu:,} underground samples ({nu*AL.STEP/1000:.1f} km)")

    pins = station_pins(verbose=True)
    print(f"{len(pins)} pins")
    bands = assign_bands(raw, pins=pins)

    per_ref = {}
    for (ref, _), b in zip(raw, bands):
        u = b[b >= 0]
        if not len(u):
            continue
        e = per_ref.setdefault(ref, [])
        e.append(u)
    print(f"\nDepth bands by line (band k lies {BAND0} + {BAND_DY}k m deep):")
    tot = np.zeros(MAXBAND, dtype=np.int64)
    for ref in sorted(per_ref):
        u = np.concatenate(per_ref[ref])
        cnt = np.bincount(u, minlength=MAXBAND)
        tot += cnt
        share = " ".join(f"band {k} {100*c/len(u):>4.0f}%" for k, c in enumerate(cnt) if c)
        print(f"  {ref:<3} underground {len(u)*AL.STEP/1000:>5.1f} km   {share}")
    print("\nWhole network:")
    for k, c in enumerate(tot):
        if c:
            print(f"  band {k} ({BAND0+BAND_DY*k:>2} m deep) {c*AL.STEP/1000:>7.1f} km"
                  f"  {100*c/tot.sum():>5.1f}%")
    deepest = int(np.nonzero(tot)[0].max())
    print(f"Deepest: {BAND0+BAND_DY*deepest} m (the real Taipei Metro is about 30 m at most)")

    # Check: underground points of two different lines less than 30 m apart horizontally must be
    # >= 15 m apart vertically
    print("\nChecking for same-cell conflicts …")
    occ = {}
    bad = 0
    for (ref, sm), b in zip(raw, bands):
        for i, s in enumerate(sm):
            if b[i] < 0:
                continue
            ck = (int(math.floor(s[0]/CELL_M)), int(math.floor(s[1]/CELL_M)))
            occ.setdefault(ck, {}).setdefault(int(b[i]), set()).add(ref)
    for ck, bb in occ.items():
        for band, refs in bb.items():
            for dx in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    o = occ.get((ck[0]+dx, ck[1]+dz), {}).get(band, set())
                    if o - refs:
                        bad += 1
    print(f"  Adjacent cells of different lines in the same band: {bad}"
          + ("  ← conflicts remain" if bad else "  (no conflicts)"))


if __name__ == "__main__":
    main()
