#!/usr/bin/env python3
"""Shared parts for Western-style buildings of the Japanese colonial era, used by the
Presidential Office Building, the National Taiwan Museum and the Red House.

kit.py supplies masks and heightfields; these three buildings need facades: bands of white
trim across red brick walls, one arched window per bay, quoins at the corners, and the
columns and pediment of a portico. This module provides them as:

  fit_angle   OSM outer ring -> the angle that minimizes the area of the local bounding
              rectangle. kit.principal_angle rounds to whole degrees; on the Presidential
              Office Building's 130 m facade, 0.4° of error is nearly 1 m of skew, so this
              works to 0.1°.
  to_local    World point -> local (u, v) (no half-block offset; for OSM vertices).
  Mason       Builds on a Frame (every write goes through the w the caller supplies, that
              is, the Guard):
                facade()  Builds `layers` layers of wall on the outer ring of the mask,
                          handing each cell to pattern(face, coordinate along the wall,
                          height, layer) to choose the material. A window is hollow in
                          the outer layer and glass in the inner layer, so a 1:1 wall
                          shows its depth.
                roof()    Heightfield roof: full blocks at whole heights, slabs at half
                          heights, stairs along the edges of steep slopes.
                column()  Square column: base, shaft, capital.
                gable()   Triangular pediment (the portico pediment, the Red House
                          entrance).
                dome()    Dome shell (the National Taiwan Museum, the corner towers of
                          the Presidential Office Building).
  stair()     Block state string of a stair (facing is the direction of its high side).

No building's dimensions are here; dimensions and their sources are in each building's own
module.
"""
import math

import numpy as np

from mrt.application.attractions.kit import AIR, Painter, erode

OPPOSITE = {"north": "south", "south": "north", "east": "west", "west": "east"}


def fit_angle(poly, step=0.1):
    """Outer ring (world coordinates) -> angle of the u axis (radians, within -45° to 45°)
    that minimizes the area of the local bounding rectangle."""
    pts = np.asarray(poly, dtype=float)
    pts = pts - pts.mean(axis=0)
    best, best_a = None, 0.0
    n = int(round(45.0 / step))
    for k in range(-n, n):
        a = math.radians(k * step)
        c, s = math.cos(a), math.sin(a)
        u = pts[:, 0] * c + pts[:, 1] * s
        v = -pts[:, 0] * s + pts[:, 1] * c
        area = (u.max() - u.min()) * (v.max() - v.min())
        if best is None or area < best - 1e-9:
            best, best_a = area, a
    return best_a


def to_local(fr, x, z):
    """World point -> local (u, v). Frame.local is for cells (it adds half a block); OSM
    vertices use this."""
    dx, dz = x - fr.cx, z - fr.cz
    return dx * fr.c + dz * fr.s, -dx * fr.s + dz * fr.c


def local_extent(fr, poly):
    """Extent of a polygon in local coordinates (u0, u1, v0, v1)."""
    L = [to_local(fr, x, z) for x, z in poly]
    us = [p[0] for p in L]
    vs = [p[1] for p in L]
    return min(us), max(us), min(vs), max(vs)


def convex_corners(pts, min_turn=60.0):
    """Convex corners of a polygon (local coordinates): outward vertices that turn by more
    than min_turn degrees. Vertices on arcs (a semicircular portico, circles other than
    octagons) each turn only a dozen or so degrees and do not count as corners."""
    n = len(pts)
    if n < 3:
        return []
    area = sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n))
    sgn = 1.0 if area > 0 else -1.0
    out = []
    for i in range(n):
        ax, az = pts[i - 1]
        bx, bz = pts[i]
        cx, cz = pts[(i + 1) % n]
        d1 = (bx - ax, bz - az)
        d2 = (cx - bx, cz - bz)
        if math.hypot(*d1) < 1e-6 or math.hypot(*d2) < 1e-6:
            continue
        cross = d1[0] * d2[1] - d1[1] * d2[0]
        dot = d1[0] * d2[0] + d1[1] * d2[1]
        turn = math.degrees(math.atan2(abs(cross), dot))
        if turn >= min_turn and cross * sgn > 0:
            out.append((bx, bz))
    return out


def centroid(poly):
    xs = [p[0] for p in poly]
    zs = [p[1] for p in poly]
    return sum(xs) / len(xs), sum(zs) / len(zs)


def stair(name, facing, half="bottom", shape="straight"):
    """State string of minecraft:<name>_stairs. facing is the stair's high side (walking in
    that direction goes up)."""
    return "minecraft:%s[facing=%s,half=%s,shape=%s,waterlogged=false]" % (name, facing, half, shape)


def slab(name, kind="bottom"):
    return "minecraft:%s[type=%s,waterlogged=false]" % (name, kind)


def shift(m, dz, dx):
    """Shift a mask: out[i, j] = m[i + dz, j + dx] (False out of bounds)."""
    out = np.zeros_like(m)
    h, w = m.shape
    i0, i1 = max(0, -dz), min(h, h - dz)
    j0, j1 = max(0, -dx), min(w, w - dx)
    if i0 < i1 and j0 < j1:
        out[i0:i1, j0:j1] = m[i0 + dz:i1 + dz, j0 + dx:j1 + dx]
    return out


class Mason:
    """Builds walls, roofs and columns on a Frame. w is a BlockSink (already wrapped in a
    Guard)."""

    def __init__(self, w, fr):
        self.w, self.fr = w, fr
        self.p = Painter(w, fr)
        self._face_cache = {}

    # ---- Basics ----
    def set(self, x, y, z, block):
        self.w.set(int(x), int(y), int(z), block)

    def at(self, u, v, y, block):
        x, z = self.fr.cell(u, v)
        self.w.set(x, int(y), z, block)

    def fill(self, mask, y0, y1, block):
        self.p.fill(mask, y0, y1, block)

    def facing(self, du, dv):
        """Local direction -> cardinal direction (cached: the thousands of cells in one wall
        all ask for the same direction)."""
        k = (du, dv)
        f = self._face_cache.get(k)
        if f is None:
            f = self._face_cache[k] = self.fr.facing(du, dv)
        return f

    @staticmethod
    def along(face):
        """Face normal (nu, nv) -> the positive direction along the wall (du, dv): for a wall
        whose normal runs along u, the coordinate along the wall is v."""
        return (0, 1) if face[0] else (1, 0)

    # ---- Facades ----
    def ring_cells(self, mask):
        """Each cell of the mask's outer ring: (x, z, u, v, face normal (nu, nv), coordinate
        along the wall t).

        The normal comes from which of the four neighbors lie outside the mask, combined
        into a world direction, turned back into local coordinates and snapped to the
        nearest axis. When the Frame is rotated the outer ring is jagged, yet each cell's
        normal is still the direction of its wall."""
        m = mask
        ex = m & ~shift(m, 0, 1)             # East neighbor (x+1) is outside
        wx = m & ~shift(m, 0, -1)
        sz = m & ~shift(m, 1, 0)             # South neighbor (z+1)
        nz = m & ~shift(m, -1, 0)
        edge = ex | wx | sz | nz
        dx = ex.astype(np.int8) - wx.astype(np.int8)
        dz = sz.astype(np.int8) - nz.astype(np.int8)
        ii, jj = np.nonzero(edge)
        fr = self.fr
        out = []
        for i, j in zip(ii.tolist(), jj.tolist()):
            wx_, wz_ = float(dx[i, j]), float(dz[i, j])
            if wx_ == 0 and wz_ == 0:            # Both sides of a one-block wall are outside: pick either
                wx_ = 1.0 if ex[i, j] else 0.0
                wz_ = 0.0 if ex[i, j] else 1.0
            du = wx_ * fr.c + wz_ * fr.s
            dv = -wx_ * fr.s + wz_ * fr.c
            if abs(du) >= abs(dv):
                face = (1 if du > 0 else -1, 0)
                t = float(fr.V[i, j])
            else:
                face = (0, 1 if dv > 0 else -1)
                t = float(fr.U[i, j])
            out.append((int(fr.X[i, j]), int(fr.Z[i, j]), float(fr.U[i, j]), float(fr.V[i, j]), face, t))
        return out

    @staticmethod
    def _ngon_cell(cell, ngon):
        """Classify a ring cell by the faces of a regular n-gon instead: the face is the index
        k of the side whose normal is nearest, and the coordinate along the wall t is
        measured from that side's midpoint (negative against the u→v direction)."""
        x, z, u, v, _, _ = cell
        n, rot, du, dv = ngon
        uu, vv = u - du, v - dv
        best, bk = None, 0
        for k in range(n):
            ph = rot + 2 * math.pi * k / n
            d = uu * math.cos(ph) + vv * math.sin(ph)
            if best is None or d > best:
                best, bk = d, k
        ph = rot + 2 * math.pi * bk / n
        t = -uu * math.sin(ph) + vv * math.cos(ph)
        return (x, z, u, v, bk, t)

    def facade(self, mask, y0, y1, pattern, base=0, layers=2, corners=None, ngon=None):
        """Build walls on the mask's outer ring from y0 to y1 (inclusive). Layer k is the
        outer ring of the mask after shrinking it by k cells.

        pattern(face, t, h, layer, u, v, q) -> a block string or None (None = write nothing
        and leave the cell to something else). h = y - base (base is usually the ground
        floor, so pattern deals only in meters above it).
        face is normally the normal (nu, nv) (±u or ±v). Given ngon=(n, rot, du, dv), it
        becomes the face index k of a regular n-gon (normal angle rot + k·360°/n), with t
        measured from the midpoint of that face; this is what tells apart the diagonal
        faces of the Red House's Octagon.
        Given corners, a list of convex corners in local coordinates (from convex_corners),
        q is the cell's Chebyshev distance to the nearest convex corner (for quoins);
        otherwise q is None."""
        cur = mask
        C = np.asarray(corners, dtype=float) if corners else None
        for k in range(layers):
            if k:
                cur = erode(cur)
            cells = self.ring_cells(cur)
            if ngon is not None:
                cells = [self._ngon_cell(c, ngon) for c in cells]
            if C is not None and len(cells):
                P = np.array([(c[2], c[3]) for c in cells])
                Q = np.min(np.maximum(np.abs(P[:, None, 0] - C[None, :, 0]),
                                      np.abs(P[:, None, 1] - C[None, :, 1])), axis=1).tolist()
            else:
                Q = [None] * len(cells)
            for (x, z, u, v, face, t), q in zip(cells, Q):
                for y in range(int(y0), int(y1) + 1):
                    b = pattern(face, t, y - base, k, u, v, q)
                    if b is not None:
                        self.w.set(x, y, z, b)

    # ---- Roofs ----
    def roof(self, mask, base, h, full, slab_name=None, stair_name=None, shell=2, under=None):
        """Heightfield roof: each cell stacks shell blocks down from base + h.

        Where the fraction is >= 0.5 a slab (slab_name) goes on top. Given stair_name, cells
        with a neighbor one block lower get a stair on top (high side upslope), so a 45°
        slope does not step one whole block at a time."""
        fr = self.fr
        H = np.asarray(h, dtype=float) * np.ones(fr.shape)
        B = np.broadcast_to(np.asarray(base), fr.shape)
        top = np.where(mask, B + H, -9999.0)
        ti = np.floor(top).astype(int)
        frac = top - ti
        # Tops of the four neighbors (infinitely low outside the mask): upslope is toward
        # the highest neighbor, and a stair goes only where a neighbor is one block lower.
        dirs = ((0, 1, "east"), (0, -1, "west"), (1, 0, "south"), (-1, 0, "north"))
        nbs = [np.where(shift(mask, dz, dx), shift(top, dz, dx), -9999.0) for dz, dx, _ in dirs]
        nb_max = np.max(nbs, axis=0)
        up = np.argmax(nbs, axis=0)
        lower = np.zeros(fr.shape, dtype=bool)
        for nb in nbs:
            lower |= np.floor(nb) < ti
        ii, jj = np.nonzero(mask)
        s = self.w.set
        for i, j in zip(ii.tolist(), jj.tolist()):
            x, z = int(fr.X[i, j]), int(fr.Z[i, j])
            b, t = int(round(B[i, j])), int(ti[i, j])
            lo = max(b, t - shell + 1)
            for y in range(lo, t + 1):
                s(x, y, z, full)
            if under is not None and lo - 1 >= b:
                s(x, lo - 1, z, under)
            if slab_name is not None and frac[i, j] >= 0.5:
                s(x, t + 1, z, slab(slab_name))
            elif stair_name is not None and lower[i, j] and nb_max[i, j] > top[i, j] + 0.25:
                s(x, t, z, stair(stair_name, dirs[int(up[i, j])][2]))

    # ---- Columns, pediments, domes ----
    def column(self, u, v, y0, y1, shaft, base=None, capital=None, size=1.0):
        """Square column: center (u, v), side size (meters). One block of base and one of
        capital (each only if given). A cell center on the edge counts on one side only (a
        half-open interval), so a column of side 1 is one block and of side 2 is two."""
        fr = self.fr
        r = size / 2.0
        cx, cz = fr.world(u, v)
        R = int(math.ceil(r + 1.5))
        for x in range(int(math.floor(cx)) - R, int(math.floor(cx)) + R + 1):
            for z in range(int(math.floor(cz)) - R, int(math.floor(cz)) + R + 1):
                du, dv = fr.local(x, z)
                if -r <= du - u < r and -r <= dv - v < r:
                    for y in range(int(y0), int(y1) + 1):
                        b = shaft
                        if base is not None and y == y0:
                            b = base
                        elif capital is not None and y == y1:
                            b = capital
                        self.w.set(x, y, z, b)

    def gable(self, u0, u1, v0, v1, y, rise, fill, edge=None, axis="u"):
        """Triangular pediment: along axis from u0 to u1, thickness v0..v1 (on the other
        axis), base at y, rise at the center. With axis="v" the two parameter pairs swap
        meaning: along v from u0 to u1, with thickness v0..v1 in u.

        Given a stair name as edge, stairs line the two sloping edges (high side toward the
        center) so the top of the pediment is sloped; the center cell gets a full block and
        a slab as the ridge instead."""
        fr = self.fr
        if axis == "u":
            A, D = fr.U, fr.V
        else:
            A, D = fr.V, fr.U
        mid, half = (u0 + u1) / 2.0, (u1 - u0) / 2.0
        m = (A >= u0) & (A <= u1) & (D >= v0) & (D <= v1)
        h = rise * (1.0 - np.abs(A - mid) / half)
        ii, jj = np.nonzero(m)
        for i, j in zip(ii.tolist(), jj.tolist()):
            x, z = int(fr.X[i, j]), int(fr.Z[i, j])
            hh = float(h[i, j])
            top = int(math.floor(hh + 0.25))
            for yy in range(int(y), int(y) + top):
                self.w.set(x, yy, z, fill)
            if edge is not None:
                a = float(A[i, j])
                toward = (1, 0) if a < mid else (-1, 0)
                if axis != "u":
                    toward = (toward[1], toward[0])
                if abs(a - mid) < 0.75:
                    self.w.set(x, int(y) + top, z, fill)
                    self.w.set(x, int(y) + top + 1, z, slab(edge.replace("_stairs", "_slab")))
                else:
                    self.w.set(x, int(y) + top, z, stair(edge, self.facing(*toward)))

    def dome(self, du, dv, r, y, rise, block, shell=2, slab_name=None, rib=None, ribs=0, profile=0.5):
        """Dome shell: center (du, dv), base radius r, base at y, height rise. profile=0.5 is
        a hemisphere (an ellipsoid); < 0.5 is flatter, > 0.5 more pointed. With ribs > 0,
        that many meridians take the rib material (the dome's ribs)."""
        fr = self.fr
        d = np.hypot(fr.U - du, fr.V - dv)
        m = d <= r
        h = rise * np.clip(1.0 - (d / r) ** 2, 0, 1) ** profile
        top = y + h
        ii, jj = np.nonzero(m)
        ang = np.arctan2(fr.V - dv, fr.U - du)
        for i, j in zip(ii.tolist(), jj.tolist()):
            x, z = int(fr.X[i, j]), int(fr.Z[i, j])
            t = float(top[i, j])
            ti = int(math.floor(t))
            b = block
            if ribs and rib is not None:
                k = (float(ang[i, j]) / (2 * math.pi / ribs)) % 1.0
                if min(k, 1 - k) * (2 * math.pi / ribs) * float(d[i, j]) < 0.55 and float(d[i, j]) > 0.8:
                    b = rib
            for yy in range(max(int(y), ti - shell + 1), ti + 1):
                self.w.set(x, yy, z, b)
            if slab_name is not None and t - ti >= 0.5:
                self.w.set(x, ti + 1, z, slab(slab_name))

    def clear_box(self, mask, y0, y1):
        self.p.fill(mask, y0, y1, AIR)
