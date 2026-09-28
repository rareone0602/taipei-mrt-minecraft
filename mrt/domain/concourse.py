#!/usr/bin/env python3
"""Underground pedestrian routes: turns OSM indoor corridors into a plan that can be built as is.

Despite the file name, this module models the underground malls, not a station's
concourse (the fare-gate level).

Everything here is a pure function; no world save is touched and no block written.
The input is projected polylines and exit coordinates; the output is corridor
centerlines, exit connector segments and vertical connection points.

Three problems found in the data that must be dealt with here:

1. **OSM's level is not an absolute floor.** Taipei City Mall is tagged level=-2,
   Station Front Metro Mall level=-2 but layer=-1, and Zhongshan Metro Mall level=-1,
   yet all three are in fact B1, and walking from one to another takes only two
   hundred meters. Each cluster of mappers uses its own datum for level, so comparing
   across clusters means nothing. Level is therefore not used as an elevation here,
   only to decide whether a way is underground.

2. **Endpoints are not joined.** Around Taipei Main Station there are 199 dangling
   endpoints, 71 of them less than 5 m from another node: the mappers failed to join
   them, and the corridors are not really broken. Without merging nodes first, the
   8.8 km connected network falls apart into 60 pieces.

3. **Exits do not always lie on a corridor.** Taipei City Mall is five centerlines,
   and exits Y9~Y20 and Y22~Y28 along it all lie 9~42 m off the line, because the
   cross passages were never drawn. A connector has to be added for each of them.

Self-test: ./.venv/bin/python tests/test_concourse.py
"""
import math
import re

# A number: optional minus sign, optional decimal point
_NUM = r"-?\d+(?:\.\d+)?"
_RANGE = re.compile(r"^(%s)-(%s)$" % (_NUM, _NUM))
_LEAD = re.compile(r"^(%s)" % _NUM)


def parse_level(value):
    """Map an OSM level tag to (lowest floor, highest floor); return None if it cannot parse.

    Forms found in practice (all of them occur around Taipei Main Station):
      "-1"          A single floor
      "-1;0"        A semicolon list, not necessarily sorted ("0;-0.5;-1" also occurs)
      "-2--1"       A range. The minus sign is both the negative sign and the separator,
                    so it splits correctly only when both ends are anchored
      "-2--0"       -0 must be normalized to 0
      "-1:0;1;2..." The colon is a mistyped semicolon (an elevator in a Zhongshan department
                    store)
      "5A"          A floor code with a letter suffix; take the leading number

    Stairs and elevators use (lowest, highest) as the two ends they connect: only 6 of
    120 stairways are tagged with step_count, so the number of steps cannot be looked
    up and must be inferred from the floor difference.
    """
    if not value:
        return None
    s = str(value).strip().replace(":", ";").replace("；", ";").replace(",", ";")
    levels = []
    for tok in s.split(";"):
        tok = tok.strip()
        if not tok:
            continue
        m = _RANGE.match(tok)
        if m:
            levels += [float(m.group(1)), float(m.group(2))]
            continue
        m = _LEAD.match(tok)
        if m:
            levels.append(float(m.group(1)))
    if not levels:
        return None
    return min(levels) + 0.0, max(levels) + 0.0        # +0.0 turns -0.0 into 0.0


def underground(tags):
    """Tell whether this way counts as an underground pedestrian route.

    It decides by level, not indoor=yes. A university next to Zhongxiao Xinsheng station
    has mapped the interiors of its buildings in full: 92 corridors, 1.2 km, all at
    level 0~14. Collecting by indoor would build a fourteen-story school on top of the
    metro station.
    """
    lv = parse_level(tags.get("level"))
    if lv is not None:
        lo, hi = lv
        return lo < 0 and hi <= 0        # Exclude anything reaching the ground floor or above
                                         # (department store escalators)
    # No level but tagged as a tunnel: a pedestrian underpass beneath a road also counts
    return tags.get("tunnel") in ("yes", "building_passage")


# ---------- Node merging and connectivity ----------

class _Union:
    def __init__(self):
        self.p = {}

    def find(self, a):
        self.p.setdefault(a, a)
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def join(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def merge_nodes(coords, tol=3.0):
    """Merge nodes within tol meters of each other. Return {original node: representative node}.

    tol is 3 m: measured, 2~3 m catches most of the unjoined endpoints, while 5 m catches
    all of them but starts gluing together two corridors that really are separated by a wall.
    """
    u = _Union()
    grid = {}
    cell = max(tol, 1.0)
    for nid, (x, z) in coords.items():
        u.find(nid)
        grid.setdefault((int(math.floor(x / cell)), int(math.floor(z / cell))),
                        []).append(nid)
    t2 = tol * tol
    for (cx, cz), ids in grid.items():
        near = []
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                near += grid.get((cx + dx, cz + dz), ())
        for a in ids:
            ax, az = coords[a]
            for b in near:
                if a >= b:
                    continue
                bx, bz = coords[b]
                if (ax - bx) ** 2 + (az - bz) ** 2 <= t2:
                    u.join(a, b)
    return {nid: u.find(nid) for nid in coords}


def build_graph(ways, tol=3.0):
    """ways: [{"nodes": [id...], "points": [[x, z], ...]}, ...]

    Return (pos, adj, edges):
      pos   {representative node: (x, z)}           Merged coordinates (the mean of each group)
      adj   {representative node: {neighbor, ...}}
      edges [(a, b, way index)]                     Without self-loops or duplicates
    """
    coords = {}
    for w in ways:
        for nid, p in zip(w["nodes"], w["points"]):
            coords[nid] = (float(p[0]), float(p[1]))
    rep = merge_nodes(coords, tol)

    acc = {}
    for nid, (x, z) in coords.items():
        r = rep[nid]
        sx, sz, n = acc.get(r, (0.0, 0.0, 0))
        acc[r] = (sx + x, sz + z, n + 1)
    pos = {r: (sx / n, sz / n) for r, (sx, sz, n) in acc.items()}

    adj, edges, seen = {}, [], set()
    for wi, w in enumerate(ways):
        ids = [rep[n] for n in w["nodes"]]
        for a, b in zip(ids, ids[1:]):
            if a == b:
                continue
            key = (a, b) if a < b else (b, a)
            adj.setdefault(a, set()).add(b)
            adj.setdefault(b, set()).add(a)
            if key in seen:
                continue
            seen.add(key)
            edges.append((a, b, wi))
    return pos, adj, edges


def components(pos, adj):
    """Return the connected components, largest first: [set(nodes), ...]."""
    seen, out = set(), []
    for start in pos:
        if start in seen:
            continue
        stack, group = [start], set()
        seen.add(start)
        while stack:
            n = stack.pop()
            group.add(n)
            for m in adj.get(n, ()):
                if m not in seen:
                    seen.add(m)
                    stack.append(m)
        out.append(group)
    out.sort(key=len, reverse=True)
    return out


def main_component(pos, adj, near=(0.0, 0.0), radius=400.0):
    """Pick the corridor network of the station being built.

    Picking the component nearest to near is not enough: directly above Taipei Main
    Station there is an isolated two-node corridor, which that rule would pick, building
    only 17 meters of underground mall. The right question is which nearby component is
    the largest.
    """
    comps = components(pos, adj)
    if not comps:
        return set()
    hit = [g for g in comps
           if min(math.dist(pos[n], near) for n in g) <= radius]
    return max(hit, key=len) if hit else comps[0]


def bridge_gaps(pos, adj, edges, max_gap=25.0):
    """Join components that are close but not connected; return the added edges [(a, b)].

    OSM has 199 dangling endpoints around Taipei Main Station. merge_nodes catches those
    within 3 m; the rest really do have an undrawn gap. For example, the Beimen passage
    to the Airport MRT is entirely isolated, yet its east end is only twenty-odd meters
    from the west section of Taipei City Mall. Closing such gaps restores reality (you
    can walk through); left open, the underground mall loses a whole branch.

    Edges are added only to the current largest cluster, one at a time with a recount
    after each, so that two clusters that should not be joined to each other are not
    strung together.
    """
    added = []
    comps = components(pos, adj)
    if not comps:
        return added
    main = set(comps[0])
    rest = [set(g) for g in comps[1:]]
    while rest:
        best = None
        for gi, g in enumerate(rest):
            for a in g:
                ax, az = pos[a]
                for b in main:
                    bx, bz = pos[b]
                    d = math.hypot(ax - bx, az - bz)
                    if best is None or d < best[0]:
                        best = (d, gi, a, b)
        if best is None or best[0] > max_gap:
            break
        _, gi, a, b = best
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
        edges.append((a, b, -1))
        added.append((a, b))
        main |= rest.pop(gi)
    return added


# ---------- Exit connectors ----------

def snap_entrances(pos, group, entrances, radius=60.0):
    """Connect each exit to the nearest corridor node.

    Return (connected, orphan):
      connected [(ref, ex, ez, node, distance)]   A distance of 0 means the exit is itself a node
      orphan    [(ref, ex, ez)]                   Exits with no corridor within radius

    radius is 60 m: measured, 30 m connects 60% of exits and 50 m connects 80%. Any wider
    and the exits of the neighboring station get connected to unrelated corridors.
    """
    cand = [(n, pos[n]) for n in group]
    connected, orphan = [], []
    for ref, ex, ez in entrances:
        best, bd = None, None
        for n, (x, z) in cand:
            d = math.hypot(x - ex, z - ez)
            if bd is None or d < bd:
                best, bd = n, d
        if best is not None and bd <= radius:
            connected.append((ref, ex, ez, best, bd))
        else:
            orphan.append((ref, ex, ez))
    return connected, orphan


def corridor_lines(pos, edges, group):
    """Return the corridor centerlines to build, [((x0, z0), (x1, z1)), ...], only within group."""
    out = []
    for a, b, _ in edges:
        if a in group and b in group:
            out.append((pos[a], pos[b]))
    return out


def degree(adj, group):
    """Return the degree of each node, used to decide where wayfinding signs go (only a junction
    of three or more ways merits one)."""
    return {n: len(adj.get(n, ())) for n in group}


def total_length(lines):
    return sum(math.dist(a, b) for a, b in lines)


def outward(pos, adj, node, ex, ez):
    """Return the orthogonal direction the exit stair climbs in: away from the corridor.

    An exit is often the corridor's end node itself. At Taipei Main Station, M1, M3, M8,
    Y7 and Z2 are all like this: the exit minus the node is the zero vector, so the
    direction is undefined. With an arbitrary choice the stair climbs back along the
    corridor, overwriting the very corridor it should connect to, and builds a dead end
    nobody can reach (measured, each of these five exits became a connected component
    of its own).

    The fix is to look at the neighbors: the stair climbs away from the direction the
    corridor comes from. When the exit is far enough from the node (with a connector
    added), the stair simply continues outward along the connector.
    """
    nx, nz = pos[node]
    vx, vz = ex - nx, ez - nz
    if math.hypot(vx, vz) < 2.0:
        nbrs = [pos[m] for m in adj.get(node, ())]
        if nbrs:
            ax = sum(p[0] for p in nbrs) / len(nbrs)
            az = sum(p[1] for p in nbrs) / len(nbrs)
            vx, vz = nx - ax, nz - az
    if abs(vx) < 1e-6 and abs(vz) < 1e-6:
        vx = 1.0
    if abs(vx) >= abs(vz):
        return (1 if vx > 0 else -1), 0
    return 0, (1 if vz > 0 else -1)
