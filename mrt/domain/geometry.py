#!/usr/bin/env python3
"""Building geometry tools: polygon fill, outer wall outline and hip roofs.

A station box is swept from the cross-section along the line, but a station building
above ground is not: it is an arbitrary polygon taken from OSM and has to be rasterized
here. This module does pure geometry and writes nothing to the world, so its self-test
can run on its own.

Self-test: ./.venv/bin/python -m mrt.domain.geometry
"""
import math


def poly_cells(poly):
    """Return the integer cells (x, z) inside a polygon, by scanline and the even-odd rule.

    The test is whether the **cell center** (xc+0.5, zc+0.5) is inside the polygon, not a
    cell corner. That way the cell count equals the area (a (0,0)-(10,10) square is exactly
    100 cells), and adjacent polygons that share an edge never both fill the same cell.
    """
    if len(poly) < 3:
        return set()
    zs = [p[1] for p in poly]
    out = set()
    for zc in range(int(math.floor(min(zs))), int(math.ceil(max(zs))) + 1):
        zy = zc + 0.5
        xs = []
        for i in range(len(poly)):
            x0, z0 = poly[i]
            x1, z1 = poly[(i + 1) % len(poly)]
            if z0 == z1:
                continue
            lo, hi = (z0, z1) if z0 < z1 else (z1, z0)
            if lo <= zy < hi:
                xs.append(x0 + (zy - z0) * (x1 - x0) / (z1 - z0))
        xs.sort()
        for i in range(0, len(xs) - 1, 2):
            a, b = xs[i], xs[i + 1]
            for xc in range(int(math.ceil(a - 0.5)), int(math.floor(b - 0.5)) + 1):
                if a <= xc + 0.5 < b:
                    out.add((xc, zc))
    return out


def ring_cells(cells):
    """Return the outermost ring of a filled area: a cell with any of its four neighbors outside
    the set is outer wall."""
    return {(x, z) for x, z in cells
            if not all((x + dx, z + dz) in cells
                       for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)))}


def inset(cells, n=1):
    """Shrink a filled area inward by n cells (peeling off n outer rings in turn)."""
    cur = set(cells)
    for _ in range(n):
        cur -= ring_cells(cur)
    return cur


def depth_map(cells):
    """Return each cell's Manhattan distance to the edge (outer ring = 1), by multi-source BFS.

    A hip roof uses this as its height: the farther from the edge, the higher, so the
    ridge appears naturally innermost. It works for a floor plan of any shape, with no
    need to assume a rectangle.
    """
    from collections import deque
    d = {}
    q = deque()
    for c in ring_cells(cells):
        d[c] = 1
        q.append(c)
    while q:
        x, z = q.popleft()
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (x + dx, z + dz)
            if n in cells and n not in d:
                d[n] = d[(x, z)] + 1
                q.append(n)
    return d


def hip_roof(cells, y0, slope=0.5, max_rise=None):
    """Hip roof -> {(x, z): (y_bottom, y_top)}.

    y0 is the eave height. Each cell is stacked from the eave up to
    y0 + round(dist * slope), clamped to max_rise; the capping cell is returned
    separately so that the caller can replace it with ridge tiles.
    """
    d = depth_map(cells)
    out = {}
    for c, dist in d.items():
        rise = (dist - 1) * slope
        if max_rise is not None:
            rise = min(rise, max_rise)
        out[c] = (y0, y0 + int(round(rise)))
    return out


def centroid(poly):
    a = cx = cz = 0.0
    for i in range(len(poly)):
        x0, z0 = poly[i]
        x1, z1 = poly[(i + 1) % len(poly)]
        cr = x0 * z1 - x1 * z0
        a += cr; cx += (x0 + x1) * cr; cz += (z0 + z1) * cr
    if abs(a) < 1e-9:
        n = len(poly)
        return (sum(p[0] for p in poly) / n, sum(p[1] for p in poly) / n)
    a *= 0.5
    return (cx / (6 * a), cz / (6 * a))


def bbox(poly):
    xs = [p[0] for p in poly]; zs = [p[1] for p in poly]
    return min(xs), min(zs), max(xs), max(zs)


def rect(cx, cz, w, h, rot=0.0):
    """Return the vertices of a rectangle centered at (cx,cz), w wide and h deep, rotated
    counterclockwise by rot radians."""
    c, s = math.cos(rot), math.sin(rot)
    out = []
    for dx, dz in ((-w/2, -h/2), (w/2, -h/2), (w/2, h/2), (-w/2, h/2)):
        out.append((cx + dx * c - dz * s, cz + dx * s + dz * c))
    return out
