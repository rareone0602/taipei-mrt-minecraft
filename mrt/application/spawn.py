#!/usr/bin/env python3
"""The world spawn point: outside the door of a Taipei Main Station MRT exit kiosk, facing the door.

The spawn point used to be (0, ground+2, 0), the coordinates of the Taipei Main
Station MRT node, directly above the underground malls, the link stairs and two
station boxes: the most hollowed-out column in the world. Players once spawned at
(0.5, -63, 0.5).

**How it is chosen (in order; the result is deterministic)**

1. Only the exit kiosks of Taipei Main Station MRT exits M1 to M8 are considered
   (the headhouses of the underground mall's Stairs, numbered by OSM's
   subway_entrance; exits starting with K, Y, Z or R belong to the underground
   malls themselves).
2. The cell outside the door must stand directly on the street: the terrain
   surface is exactly at the kiosk's floor level (the threshold is flush with
   the street, so there is nothing to jump or fall), and above sea level (not
   standing in water).
3. The cell outside the door must not fall inside any above-ground landmark (a
   station building, another exit kiosk, a stair shaft, a skybridge): that
   column must be open to the sky. The game places the spawn at the top of the
   column from the chunk's MOTION_BLOCKING heightmap, so a roof overhead puts
   the player on the roof.
4. Of the rest, the one nearest the Taipei Main Station MRT node (the transfer
   node of the Bannan and Tamsui-Xinyi lines) wins; ties go to the lower exit
   number.

Facing: one cell outside the door, facing -u (opposite to the direction the
stair run extends), square to the three-wide door opening, so the "出口 Exit"
sign inside the kiosk is in view.

This uses only the plan (the landmark objects returned by landmarks.for_world)
and the terrain formula, without reading the save; tools/verify_spawn.py reads
the result back from disk to check it.
"""
import math

from mrt.application.build_concourse import Stair
from mrt.application.landmarks import Passage, RailHall, Slab
from mrt.domain.terrain import SEA_Y

STATION = "台北車站"
EXIT_PREFIX = "M"          # Taipei Main Station MRT exits are numbered M1 to M8.


def _refs(stair):
    lab = stair.label
    if lab is None:
        return []
    return [str(r) for r in (lab if isinstance(lab, (list, tuple)) else [lab])]


def _above_ground(o):
    """Whether this landmark builds anything above ground (if so, the sky is not
    open anywhere within its bounds).

    Underground mall objects are all marked underground, except the exit kiosks
    (Stairs with a headhouse): the stairs are underground but the kiosk is in the
    street. The B1 hall (Slab), the TRA platform level (RailHall) and the
    underground passages (Passage) are not marked; they lie entirely below the
    surface.
    """
    if isinstance(o, Stair):
        return bool(o.headhouse)
    if isinstance(o, (Slab, RailHall, Passage)):
        return False
    return not getattr(o, "underground", False)     # Tile: underground mall tiles are underground, skybridges are not.


def station_node(stations, name=STATION):
    """The main node of a station: of the nodes with that name, the one with the
    most lines (for Taipei Main Station, the R10;BL12 transfer node, not the
    Airport MRT's A1)."""
    rows = [r for r in stations if r[1] == name]
    if not rows:
        return None
    best = max(rows, key=lambda r: (len([t for t in r[0] if t]), -abs(r[2]) - abs(r[3])))
    return best[2], best[3]


def candidates(marks, ground_at, prefix=EXIT_PREFIX):
    """Every exit kiosk door that meets conditions 2 and 3: [(refs, x, y, z, (fx, fz), kiosk)]."""
    blockers = [o for o in marks if _above_ground(o)]
    out = []
    for m in marks:
        if not isinstance(m, Stair) or not m.headhouse:
            continue
        refs = _refs(m)
        if not any(r.startswith(prefix) and r[len(prefix):].isdigit() for r in refs):
            continue
        x, z, y, face = m.door_front()
        g = int(ground_at(x, z))
        if g != y - 1 or g <= SEA_Y:
            continue
        hit = False
        for o in blockers:
            if o is m:
                continue
            x0, z0, x1, z1 = o.bbox()
            if x0 <= x <= x1 and z0 <= z <= z1:
                hit = True
                break
        if not hit:
            out.append((refs, x, y, z, face, m))
    return out


def plan_spawn(marks, stations, ground_at):
    """Choose the spawn point. Returns dict(x, y, z, facing=(fx, fz), refs, why), or None if nothing qualifies.

    y is the cell the feet stand in (level.dat's spawn.pos is this cell, and the
    game puts the player at the center of its bottom face). ground_at(x, z) must
    be the terrain surface as actually built: the CLI passes a wrapper around
    application.build_world.surface_y.
    """
    node = station_node(stations)
    if node is None:
        return None
    cs = candidates(marks, ground_at)
    if not cs:
        return None
    nx, nz = node

    def key(c):
        refs, x, y, z, face, m = c
        num = min(int(r[len(EXIT_PREFIX):]) for r in refs
                  if r.startswith(EXIT_PREFIX) and r[len(EXIT_PREFIX):].isdigit())
        return (math.hypot(x - nx, z - nz), num)

    refs, x, y, z, face, m = min(cs, key=key)
    return dict(x=int(x), y=int(y), z=int(z), facing=face, refs=refs,
                why=f"outside the kiosk of {STATION} MRT exit {'/'.join(refs)}, "
                    f"{math.hypot(x - nx, z - nz):.0f} m from the MRT node, "
                    f"the nearest of the {len(cs)} that qualify")
