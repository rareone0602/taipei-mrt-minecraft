#!/usr/bin/env python3
"""Generates the elevated structure of the Wenhu Line (BR) into a Minecraft
world save.

The Wenhu Line is a fully elevated, medium-capacity, rubber-tired system
(VAL256 / INNOVIA APM 256) with no tunnels and no underground stations, which
makes it the cleanest vertical slice for a first line.

Scale: 1 block = 1 meter. Cross-section (centerline at 0, positive to the
right):

      -5    -4 -3 -2    -1 0 +1    +2 +3 +4     +5
    [wall] [ track 1 ] [ median ] [ track 2 ] [wall]

Usage: ./.venv/bin/python -m cli.build_br [--out DIR] [--limit N]
"""
import math

GROUND    = 64          # Top block of the superflat ground.
DECK_TOP  = 77          # Track bed height (13 m above the ground, close to the real Wenhu Line).
PIER_EVERY = 25         # Pier spacing, in meters.
STEP      = 0.5         # Sampling interval along the line; it must be this dense to leave no gaps.

CONC  = "minecraft:light_gray_concrete"   # Viaduct concrete.
DECK  = "minecraft:smooth_stone"          # Track bed.
WALL  = "minecraft:gray_concrete"         # Guide wall / parapet.
PIER  = "minecraft:polished_andesite"     # Pier.
PLAT  = "minecraft:polished_diorite"      # Platform surface.
ROOF  = "minecraft:light_gray_concrete"
GLASS = "minecraft:light_gray_stained_glass_pane"
PSD   = "minecraft:glass_pane"                 # Platform screen doors.
STAIR = "minecraft:smooth_stone"               # Stair tread.

PLATFORM_LEN  = 70      # Four cars are about 55 m, so the platform is 70 m.
PLATFORM_HALF = PLATFORM_LEN // 2


def resample(pts, step):
    """Resample a polyline into evenly spaced points and return (x, z, dx, dz),
    where dx, dz is the unit tangent."""
    out = []
    acc = 0.0
    for i in range(len(pts) - 1):
        (x0, z0), (x1, z1) = pts[i], pts[i + 1]
        seg = math.hypot(x1 - x0, z1 - z0)
        if seg < 1e-9:
            continue
        ux, uz = (x1 - x0) / seg, (z1 - z0) / seg
        t = -acc
        while t < seg:
            if t >= 0:
                out.append((x0 + ux * t, z0 + uz * t, ux, uz))
            t += step
        acc = (acc + seg) % step
    return out


def build_viaduct(w, samples, station_zones):
    """Lay the viaduct deck along the line. station_zones is a set of
    (lower index, upper index) pairs; station platforms are handled separately."""
    placed = 0
    for i, (x, z, ux, uz) in enumerate(samples):
        # The normal is the tangent rotated by 90 degrees.
        nx, nz = -uz, ux
        dist_m = i * STEP

        for off in range(-5, 6):
            bx = round(x + nx * off)
            bz = round(z + nz * off)
            if off in (-5, 5):                      # Outer guide wall.
                w.set(bx, DECK_TOP,     bz, CONC)
                w.set(bx, DECK_TOP + 1, bz, WALL)
                w.set(bx, DECK_TOP + 2, bz, WALL)
            elif off == 0:                          # Median.
                w.set(bx, DECK_TOP,     bz, CONC)
                w.set(bx, DECK_TOP + 1, bz, WALL)
            else:                                   # Track bed.
                w.set(bx, DECK_TOP, bz, DECK)
            w.set(bx, DECK_TOP - 1, bz, CONC)       # Deck slab.
            placed += 1

        # Piers: one 3x3 pier every PIER_EVERY meters, from 4 blocks underground
        # up to just below the deck slab.
        if abs(dist_m % PIER_EVERY) < STEP / 2:
            cx0, cz0 = round(x), round(z)
            for ddx in (-1, 0, 1):
                for ddz in (-1, 0, 1):
                    for y in range(GROUND - 4, DECK_TOP - 1):
                        w.set(cx0 + ddx, y, cz0 + ddz, PIER)
            # Pier cap: extends to both sides to carry the deck.
            for off in range(-4, 5):
                bx = round(x + nx * off); bz = round(z + nz * off)
                w.set(bx, DECK_TOP - 2, bz, CONC)
    return placed


def build_station(w, samples, idx, name):
    """Build an elevated side-platform station at sample index idx, with
    platform screen doors and an exit stair."""
    n = len(samples)
    half = int(PLATFORM_HALF / STEP)
    lo, hi = max(0, idx - half), min(n - 1, idx + half)

    for i in range(lo, hi + 1):
        x, z, ux, uz = samples[i]
        nx, nz = -uz, ux
        end = i in (lo, hi)
        along_m = (i - lo) * STEP

        # Platform screen doors: the Wenhu Line has full-height doors, with the
        # openings aligned to the train doors (one set about every 7 m, 2 m wide).
        door = (along_m % 7.0) < 2.0
        for off in (-5, 5):
            bx = round(x + nx * off); bz = round(z + nz * off)
            for y in range(DECK_TOP + 1, DECK_TOP + 4):
                w.set(bx, y, bz, "minecraft:air" if door else PSD)

        for off in list(range(-10, -5)) + list(range(6, 11)):   # Platforms on both sides.
            bx = round(x + nx * off); bz = round(z + nz * off)
            w.set(bx, DECK_TOP - 1, bz, CONC)
            w.set(bx, DECK_TOP,     bz, PLAT)
            if abs(off) == 10 or end:                            # Outer wall.
                for y in range(DECK_TOP + 1, DECK_TOP + 5):
                    w.set(bx, y, bz, GLASS if 1 <= (y - DECK_TOP) <= 3 and not end else CONC)
            if abs(off) == 6:                                    # Platform-edge warning strip.
                w.set(bx, DECK_TOP, bz, "minecraft:yellow_concrete")
        for off in range(-10, 11):                               # Roof.
            bx = round(x + nx * off); bz = round(z + nz * off)
            w.set(bx, DECK_TOP + 5, bz, ROOF)

    build_entrance(w, samples, lo, hi)
    return name


def build_entrance(w, samples, lo, hi):
    """Exit stair: climbs from the ground to the platform level.

    Each step rises 1 m over 2 m of run (a slab for the first half, a full
    block for the second), so the player can walk up without jumping.
    Samples are STEP meters apart, so distances have to be converted to sample
    counts; meters cannot be used as indices directly.
    """
    rise = DECK_TOP - GROUND
    per_m = max(1, int(round(1.0 / STEP)))     # Samples per meter.
    need = rise * 2 * per_m + 2 * per_m        # Total stair length, in samples.
    start = lo + 4 * per_m
    if start + need > hi:
        # If the platform section is too short, extend outward.
        start = max(0, lo - need - 4 * per_m)

    top_si = start
    for k in range(rise + 1):
        y = GROUND + k
        for j in (0, 1):                       # j=0 is the first half meter, j=1 the second.
            si = start + (k * 2 + j) * per_m
            if not (0 <= si < len(samples)):
                continue
            top_si = si
            x, z, ux, uz = samples[si]
            nx, nz = -uz, ux
            # The stairway is 3 m wide, along the outside of the platform.
            for off in range(11, 14):
                bx = round(x + nx * off); bz = round(z + nz * off)
                w.set(bx, y, bz, "minecraft:smooth_stone_slab[type=bottom]" if j == 0 else STAIR)
                for yy in range(y + 1, y + 4):  # Headroom.
                    w.set(bx, yy, bz, "minecraft:air")
                if off == 13:                   # Outer guardrail.
                    w.set(bx, y + 1, bz, "minecraft:iron_bars")
                    w.set(bx, y + 2, bz, "minecraft:iron_bars")

    # The top of the stair joins the platform: add a landing and open a door
    # in the outer wall.
    for si in range(max(0, top_si - per_m), min(len(samples), top_si + per_m + 1)):
        x, z, ux, uz = samples[si]
        nx, nz = -uz, ux
        for off in range(10, 14):
            bx = round(x + nx * off); bz = round(z + nz * off)
            w.set(bx, DECK_TOP, bz, STAIR)
            for yy in range(DECK_TOP + 1, DECK_TOP + 4):
                w.set(bx, yy, bz, "minecraft:air")
