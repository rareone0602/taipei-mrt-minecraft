#!/usr/bin/env python3
"""Attractions: Taipei 101, the Chiang Kai-shek Memorial Hall, the Presidential Office
Building, the city gates and others, built in their real locations.

Data: data/attractions.json (outlines and tags fetched from OSM by
mrt/adapters/osm/fetch_attractions.py). Each entry is built by an Attraction subclass (see
the notes in kit.py). The subclasses live in the modules of this package, and each module
registers them with BUILDS = {attraction id: class}. This package scans for them, so adding
an attraction needs no change to this file. An attraction without its own module falls
back to OsmMassing, which extrudes OSM's building / building:part (using height where
tagged), so at least the location and outline are right.

Use from cli (cli/build_world.py):
    sights = AT.for_world(stations)                  # Read data, create objects, pair with nearest station
    ...each bbox() feeds the terrain distance field and the bucketing...
    AT.plan_all(sights, ground, keep)                # Settle ground-floor levels and viewpoints
    ...in the region loop, call AT.build(s, w, keep) for each attraction it covers...
    spec = RP.build_spec(..., sights=AT.datapack_entries(sights))
"""
import importlib
import json
import math
import os
import pkgutil

from mrt import config
from mrt.application.attractions import kit
from mrt.application.attractions.kit import Attraction, Frame, Guard, Painter, Site, Spot

ATTRACTIONS_JSON = os.path.join(config.DATA, "attractions.json")

WALKABLE_M = 900           # Plaques and the route map name the nearest MRT station only within this distance
ROUTE_DIALOG = "sights"    # Path of the attraction list dialog in the datapack (mrt:sights)


def registry():
    """Scan the modules of this package and collect their BUILDS."""
    out = {}
    for m in pkgutil.iter_modules(__path__):
        if m.name in ("kit",) or m.name.startswith("_"):
            continue
        mod = importlib.import_module(__name__ + "." + m.name)
        for aid, cls in getattr(mod, "BUILDS", {}).items():
            if aid in out:
                raise ValueError("Attraction %s is registered in two modules: %s and %s"
                                 % (aid, out[aid].__module__, cls.__module__))
            out[aid] = cls
    return out


def load_items(path=None):
    p = path or ATTRACTIONS_JSON
    if not os.path.exists(p):
        return []
    return json.load(open(p, encoding="utf-8"))["items"]


def nearest_station(stations, x, z):
    """(Chinese station name, station code string, distance in m, English station name);
    stations are the rows from cli.load_stations()."""
    best = None
    for refs, name, sx, sz, en, full in stations:
        d = math.hypot(sx - x, sz - z)
        if best is None or d < best[2]:
            best = (name, full, d, en)
    return best


def for_world(stations, items=None, only=None):
    """-> [Attraction]. Given a set of ids as only, builds just those (for testing)."""
    reg = registry()
    out = []
    for it in items if items is not None else load_items():
        if only and it["id"] not in only:
            continue
        cls = reg.get(it["id"], OsmMassing)
        a = cls(it)
        cx, cz = a.center()
        a.station = nearest_station(stations, cx, cz) if stations else None
        out.append(a)
    return out


def plan_all(sights, ground, keep=None, say=print):
    site = Site(ground, keep)
    for a in sights:
        a.keep = keep
        a.plan(site)
        st = a.station
        say("  Attraction %-22s %-10s ground floor y%s%s%s" % (
            a.id, a.name_zh, a.g0,
            (", top y%d" % a.top_y()) if a.top_y() else "",
            (", %s station %.0f m" % (st[0], st[2])) if st and st[2] <= WALKABLE_M else ""))


PLAQUE_STYLE = dict(wood="pale_oak", kind="standing", glow=True, color="black")
PLAQUE_INK = "#6B4A00"      # Color of the attraction name (dark gold, about 7:1 contrast on the pale wood)


def build(a, w, keep=None):
    """Build one attraction: writes pass through a Guard (nothing is written in the keep-out
    zone), the attraction's own build() runs, and a plaque is put up beside the default
    viewpoint (an attraction that puts up its own sets own_plaque = True). Returns how many
    writes were blocked."""
    g = Guard(w, keep if keep is not None else getattr(a, "keep", None))
    a.build(g)
    sp = a.spots()
    if sp and not getattr(a, "own_plaque", False):
        s0 = sp[0]
        # The player stands at the viewpoint facing the building; the plaque stands 2 blocks
        # to their right, turned to face them.
        fx, fz = -math.sin(math.radians(s0.yaw)), math.cos(math.radians(s0.yaw))
        rx, rz = -fz, fx
        px, pz = s0.x + int(round(rx * 2)), s0.z + int(round(rz * 2))
        front, back = plaque_lines(a)
        g.sign(px, s0.y, pz, front, facing=(s0.x - px, s0.z - pz), back=back, **PLAQUE_STYLE)
    return g.dropped


def _wrap(text, width, lines=2):
    """Break the English name into at most `lines` lines (each fitting in width px); None if
    it does not fit."""
    from mrt.application import signage as SG
    words, out, cur = str(text).split(), [], ""
    for wd in words:
        t = (cur + " " + wd).strip()
        if SG.text_width(t) <= width:
            cur = t
        else:
            if cur:
                out.append(cur)
            cur = wd
    if cur:
        out.append(cur)
    if len(out) > lines or any(SG.text_width(t) > width for t in out):
        return None
    return out


def plaque_lines(a):
    """Plaque -> (four front lines, four back lines).

    Front: the attraction name (dark gold, bold), the English name (broken over two lines
    if it does not fit on one) and the nearest MRT station.
    Back: the facts the attraction supplies (the third and fourth lines of plaque()) and the
    data source. With an English fact (plaque_en()), the English line takes the place of
    the name at the top of the back, so the Chinese facts and the source still fit.
    The first line must not start with `出口` (verify_exits recognizes exit kiosks by it)."""
    from mrt.application import signage as SG
    zh, en, fact1, fact2 = (list(a.plaque()) + ["", "", "", ""])[:4]
    if str(zh).startswith("出口"):
        raise ValueError("A plaque's first line must not start with 出口 "
                         "(verify_exits recognises exit kiosks by it): %r" % zh)
    st = getattr(a, "station", None)
    station = ""
    if st and st[2] <= WALKABLE_M:
        station = SG.fit(["捷運%s站 %d m" % (st[0], int(round(st[2] / 10.0) * 10)),
                          "捷運%s站" % st[0], st[0]])
    en_lines = _wrap(en, SG.SIGN_W, 2) or [SG.fit([en])]
    front = [SG.styled([zh], PLAQUE_INK)] + en_lines
    if len(front) < 3 and fact1:
        front.append(SG.fit([fact1]))
    front.append(station)
    front = (front + ["", "", "", ""])[:4]
    facts = [SG.fit([fact1]) if fact1 else "", SG.fit([fact2]) if fact2 else ""]
    fact_en = [t for t in a.plaque_en() if t]
    if fact_en:
        back = facts + [SG.fit(fact_en)]
    else:
        back = [SG.styled([zh], PLAQUE_INK)] + facts
    return front, back + ["資料 © OpenStreetMap"]


def datapack_entries(sights):
    """Plain data for ride_plan: each attraction's names, nearest station and teleport
    points (only attractions with spots are included). facts holds the first fact in
    Chinese and, where the attraction gives one, in English."""
    out = []
    for a in sights:
        sp = a.spots()
        if not sp:
            continue
        st = getattr(a, "station", None)
        out.append(dict(id=a.id, name_zh=a.name_zh, name_en=a.name_en,
                        station=(st[0], st[1], int(st[2]), st[3]) if st and st[2] <= WALKABLE_M else None,
                        facts=[str(t) for t in list(a.plaque()[2:3]) + list(a.plaque_en()[:1]) if t],
                        spots=[s._asdict() for s in sp]))
    return out


# ---------------------------------------------------------------- Fallback: extrude the OSM massing

class OsmMassing(Attraction):
    """An attraction without its own module: building / building:part extruded by height
    (or levels × 3.5 m), with windows in the outer walls and a flat roof. Location, outline
    and height come from OSM; the appearance is only the massing."""

    wall = "minecraft:light_gray_concrete"
    glass = "minecraft:light_gray_stained_glass_pane"
    roof = "minecraft:smooth_stone"

    def _parts(self):
        mains = [f for f in self.mains() if f.get("outer")]
        near = [f for f in self.features if f.get("outer") and "building:part" in f["tags"]
                and f["dist"] <= self.item["radius"] * 0.6]
        return mains + [f for f in near if f not in mains]

    @staticmethod
    def _height(t):
        for k in ("height",):
            try:
                return float(str(t[k]).split()[0])
            except (KeyError, ValueError):
                pass
        try:
            return float(t["building:levels"]) * 3.5
        except (KeyError, ValueError):
            return 10.0

    def plan(self, site):
        pts = self.outline() or [self.center()]
        xs = [p[0] for p in pts]
        zs = [p[1] for p in pts]
        cx, cz = (min(xs) + max(xs)) / 2, (min(zs) + max(zs)) / 2
        ext = max(max(xs) - min(xs), max(zs) - min(zs)) / 2 + self.margin
        self.fr = Frame(cx, cz, 0.0, ext)
        self.mask = self.fr.polygon(pts) if len(pts) >= 3 else self.fr.box(4, 4)
        self.g0 = site.level(self.fr, self.mask)
        self.height_m = max([self._height(f["tags"]) for f in self._parts()] or [10.0])
        # Viewpoint: south of the outline at 1.5 times the radius, looking at the middle of
        # the massing.
        vx, vz = int(cx), int(cz + ext + 4)
        vy = site.g(vx, vz) + 1
        yaw, pitch = kit.look(vx, vy, vz, cx, self.g0 + self.height_m * 0.4, cz)
        self._spots = [Spot("", vx, vy, vz, yaw, pitch, self.name_zh, self.name_en)]
        self.site = site

    def build(self, w):
        p = Painter(w, self.fr)
        for f in self._parts():
            t = f["tags"]
            for r in f["outer"]:
                if len(r) < 3:
                    continue
                m = self.fr.polygon(r)
                if not m.any():
                    continue
                h = int(round(self._height(t)))
                try:
                    lo = int(round(float(t.get("min_height", 0))))
                except ValueError:
                    lo = 0
                y0, y1 = self.g0 + lo, self.g0 + h
                p.fill(m, y0, y0, self.roof)
                p.walls(m, y0 + 1, y1 - 1, self.wall, window=self.glass, storey=4)
                p.layer(m, y1, self.roof)
