#!/usr/bin/env python3
"""Pedestrian reachability: treats the built world as a graph and flood-fills it under the rules
a player can actually walk by.

That every exit of an underground mall is reachable cannot be proven from the
generator's own records. The generator knows only which blocks it placed, not whether
those blocks fit together into something walkable. A missing stair step, a corridor cut
by another line's tunnel lining, a roof slab that leaves only one block of headroom: in
the generation records all of these are "done". So verification has to work the other
way round: rebuild the walkable space from the blocks themselves.

The block source is injected: tools/verify_concourse.py feeds blocks read back from the
Anvil world save, and tests/test_concourse.py feeds the blocks in a DictSink. There is
only one copy of the rules, shared by both.

The movement rules are deliberately symmetric (one block up or down), so reachability
is undirected and connected components can be discussed directly. Real Minecraft lets
a player drop any height, which is one-way; checking connectivity with it would pass a
dead-end corridor that you can jump down into but not climb out of.

Self-test: ./.venv/bin/python -m tests.test_walk
"""
import collections

# Blocks that neither block the way nor hold a player up: standing in their cell relies on the
# cell below.
_PASSABLE_EXACT = {
    "minecraft:air", "minecraft:cave_air", "minecraft:void_air",
    "minecraft:water", "minecraft:light", "minecraft:structure_void",
}
_PASSABLE_SUFFIX = (
    "_rail", "_sign", "_torch", "_button", "_banner",
)
_PASSABLE_CONTAINS = ("rail", "sign", "torch", "pressure_plate", "carpet")


def base_name(block):
    """Strip the block states: 'minecraft:oak_sign[rotation=4]' -> 'minecraft:oak_sign'."""
    return block.split("[", 1)[0]


def is_bottom_slab(block):
    """Tell whether a block is a bottom slab: it fills half a cell, a player stands inside that
    cell, and the cell above the head is still empty.

    The project's stairs alternate full blocks and bottom slabs (build_line._stair_run,
    landmarks.ShaftStair), rising 0.5 m per meter. Without this rule a whole stair would
    be read as half solid and half hanging in the air, breaking every second cell.
    A string written by nbtlib without type= defaults to bottom.
    """
    name = base_name(block)
    if not name.endswith("_slab"):
        return False
    st = block[len(name):]
    return "type=top" not in st and "type=double" not in st


def is_passable(block):
    """Tell whether a block can be walked through but not stood on."""
    name = base_name(block)
    if name in _PASSABLE_EXACT:
        return True
    if name.endswith(_PASSABLE_SUFFIX):
        return True
    return any(k in name for k in _PASSABLE_CONTAINS)


def is_support(block):
    """Tell whether a block can be stood on (solid, or itself a bottom slab)."""
    return not is_passable(block) and not is_bottom_slab(block)


def standable(get, x, y, z, head=2, floor_ok=None):
    """Tell whether a player can stand at (x, y, z), the cell the feet occupy.

    Requirements: the foot cell and the head-1 cells above it are passable, and the block
    below the feet is solid, or the foot cell is itself a bottom slab (a slab raises the
    player half a block, so it serves as its own floor).

    floor_ok(block name) can further restrict what the feet stand on. The exit check uses
    it to rule out terrain: if soil may not be stood on, the street cannot be reached, so
    nobody can walk along the street to another exit and go down there. Only then does
    the check show whether this one stair is passable on its own.
    """
    foot = get(x, y, z)
    slab = is_bottom_slab(foot)
    if not slab and not is_passable(foot):
        return False
    # Standing on a bottom slab raises the player half a block, so the head reaches one cell
    # higher; check one extra cell
    for dy in range(1, head + (1 if slab else 0)):
        if not is_passable(get(x, y + dy, z)):
            return False
    if slab:
        return floor_ok is None or floor_ok(base_name(foot))
    below = get(x, y - 1, z)
    return is_support(below) and (floor_ok is None or floor_ok(base_name(below)))


NEIGHBOURS = ((1, 0), (-1, 0), (0, 1), (0, -1))


def flood(get, starts, bounds=None, head=2, limit=4_000_000, floor_ok=None,
          allow=None):
    """Flood-fill the reachable foot cells from starts.

    get(x, y, z) returns a block name string. bounds is (x0, y0, z0, x1, y1, z1),
    inclusive, and keeps the search within the area of interest; without it, one stair
    leading up to the ground would let the flood spread over the whole map. allow(x, y, z)
    is a finer limit: the underground mall check uses it to exclude cells already close
    to the ground surface. The terrain rises and falls, and a fixed y limit cannot follow
    an uneven ground surface.

    Return (dist, came): dist is {foot cell: steps} and came is {foot cell: previous cell};
    the latter is used to trace the path back for display.
    """
    if bounds is not None:
        x0, y0, z0, x1, y1, z1 = bounds

        def inside(x, y, z):
            return (x0 <= x <= x1 and y0 <= y <= y1 and z0 <= z <= z1
                    and (allow is None or allow(x, y, z)))
    else:
        def inside(x, y, z):
            return allow is None or allow(x, y, z)

    dist, came = {}, {}
    q = collections.deque()
    for c in starts:
        c = (int(c[0]), int(c[1]), int(c[2]))
        if c not in dist and inside(*c) and standable(get, *c, head=head,
                                                       floor_ok=floor_ok):
            dist[c] = 0
            q.append(c)

    while q:
        x, y, z = q.popleft()
        if len(dist) >= limit:
            break
        d = dist[(x, y, z)] + 1
        for dx, dz in NEIGHBOURS:
            nx, nz = x + dx, z + dz
            for ny in (y + 1, y, y - 1):        # One block up or down, symmetric
                n = (nx, ny, nz)
                if n in dist or not inside(*n):
                    continue
                if standable(get, nx, ny, nz, head=head, floor_ok=floor_ok):
                    dist[n] = d
                    came[n] = (x, y, z)
                    q.append(n)
                    break                        # Take only the closest cell in each column
    return dist, came


def nearest_standable(get, x, y, z, radius=6, head=2, dy=8, floor_ok=None):
    """Find a cell near (x, y, z) where a player can stand.

    An exit's coordinates are the position of its OSM node and are not guaranteed to land
    exactly on a stair tread. The check should start walking from somewhere nearby, rather
    than require the generator to put a floor at exactly that point.
    Return the nearest foot cell, or None if there is none.
    """
    best = None
    for ddy in range(-dy, dy + 1):
        for ddx in range(-radius, radius + 1):
            for ddz in range(-radius, radius + 1):
                c = (x + ddx, y + ddy, z + ddz)
                if not standable(get, *c, head=head, floor_ok=floor_ok):
                    continue
                w = ddx * ddx + ddz * ddz + 4 * ddy * ddy
                if best is None or w < best[0]:
                    best = (w, c)
    return best[1] if best else None


def path(came, cell):
    """Trace flood()'s came back into a path (start first)."""
    out = [cell]
    while cell in came:
        cell = came[cell]
        out.append(cell)
    out.reverse()
    return out


def components(get, cells, bounds=None, head=2, floor_ok=None, allow=None):
    """Split foot cells into connected components. Return [[cell, ...], ...], largest first.

    "Every exit can reach every other" is equivalent to "there is only one component";
    when there are more, the grouping shows directly which exits are shut in together.
    """
    todo = [c for c in cells]
    seen, out = set(), []
    for c in todo:
        if c in seen:
            continue
        dist, _ = flood(get, [c], bounds=bounds, head=head, floor_ok=floor_ok,
                        allow=allow)
        group = [d for d in todo if d in dist]
        seen.update(group)
        if group:
            out.append(group)
    out.sort(key=len, reverse=True)
    return out
