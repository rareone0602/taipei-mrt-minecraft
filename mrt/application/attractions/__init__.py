#!/usr/bin/env python3
"""觀光景點：台北101、中正紀念堂、總統府、城門……蓋在真實位置上。

資料：data/attractions.json（mrt/adapters/osm/fetch_attractions.py 從 OSM 抓的輪廓與標籤）。
每一筆由一個 Attraction 子類別負責蓋（kit.py 的說明）。子類別放在這個套件底下
的各個模組裡，模組用 BUILDS = {景點 id: 類別} 登記 —— 這裡自動掃描，新增一座
景點不必改這個檔案。沒有專屬模組的景點退回 OsmMassing：照 OSM 的 building /
building:part 擠出量體（有 height 就照 height），至少位置與輪廓是對的。

cli 的用法（cli/build_world.py）：
    sights = AT.for_world(stations)                  # 讀資料、建物件、配最近的捷運站
    ...每座的 bbox() 餵地形距離場、分桶...
    AT.plan_all(sights, ground, keep)                # 定案：一樓高度、觀景點
    ...region 迴圈裡對涵蓋到的景點呼叫 AT.build(s, w, keep)...
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

WALKABLE_M = 900           # 說明牌與路線圖寫「最近的捷運站」：這個距離以內才寫
ROUTE_DIALOG = "sights"    # 資料包裡景點清單對話框的路徑（mrt:sights）


def registry():
    """掃描套件底下的模組，收集 BUILDS。"""
    out = {}
    for m in pkgutil.iter_modules(__path__):
        if m.name in ("kit",) or m.name.startswith("_"):
            continue
        mod = importlib.import_module(__name__ + "." + m.name)
        for aid, cls in getattr(mod, "BUILDS", {}).items():
            if aid in out:
                raise ValueError("景點 %s 同時登記在兩個模組：%s、%s" % (aid, out[aid].__module__, cls.__module__))
            out[aid] = cls
    return out


def load_items(path=None):
    p = path or ATTRACTIONS_JSON
    if not os.path.exists(p):
        return []
    return json.load(open(p, encoding="utf-8"))["items"]


def nearest_station(stations, x, z):
    """(中文站名, 站號字串, 距離 m)；stations 是 cli.load_stations() 的列。"""
    best = None
    for refs, name, sx, sz, en, full in stations:
        d = math.hypot(sx - x, sz - z)
        if best is None or d < best[2]:
            best = (name, full, d, en)
    return best


def for_world(stations, items=None, only=None):
    """-> [Attraction]。only 給一組 id 就只蓋那幾座（測試用）。"""
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
        say("  景點 %-22s %-10s 一樓 y%s%s%s" % (
            a.id, a.name_zh, a.g0,
            ("、最高點 y%d" % a.top_y()) if a.top_y() else "",
            ("、%s站 %.0f m" % (st[0], st[2])) if st and st[2] <= WALKABLE_M else ""))


PLAQUE_STYLE = dict(wood="pale_oak", kind="standing", glow=True, color="black")
PLAQUE_INK = "#6B4A00"      # 景點名的字色（深金，在淡色木板上對比約 7:1）


def build(a, w, keep=None):
    """蓋一座景點：寫入先過 Guard（禁區不寫），再交給景點自己的 build()，
    最後在預設觀景點旁邊立說明牌（景點自己立了就設 own_plaque = True）。回傳擋掉幾格。"""
    g = Guard(w, keep if keep is not None else getattr(a, "keep", None))
    a.build(g)
    sp = a.spots()
    if sp and not getattr(a, "own_plaque", False):
        s0 = sp[0]
        # 人站在觀景點面向建築；牌子立在他右手邊 2 格、轉過來面向他
        fx, fz = -math.sin(math.radians(s0.yaw)), math.cos(math.radians(s0.yaw))
        rx, rz = -fz, fx
        px, pz = s0.x + int(round(rx * 2)), s0.z + int(round(rz * 2))
        front, back = plaque_lines(a)
        g.sign(px, s0.y, pz, front, facing=(s0.x - px, s0.z - pz), back=back, **PLAQUE_STYLE)
    return g.dropped


def _wrap(text, width, lines=2):
    """英文名斷成最多 lines 行（每行放得下 width px），斷不下回 None。"""
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
    """說明牌 -> (正面四行, 背面四行)。

    正面：景點名（深金、粗體）、英文名（放不下就斷成兩行）、最近的捷運站；
    背面：景點給的事實（plaque() 的第三、四行）與資料來源。
    第一行不准以「出口」開頭（verify_exits 靠它認出入口亭）。"""
    from mrt.application import signage as SG
    zh, en, fact1, fact2 = (list(a.plaque()) + ["", "", "", ""])[:4]
    if str(zh).startswith("出口"):
        raise ValueError("說明牌第一行不准以「出口」開頭（verify_exits 靠它認出入口亭）：%r" % zh)
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
    back = [SG.styled([zh], PLAQUE_INK), SG.fit([fact1]) if fact1 else "",
            SG.fit([fact2]) if fact2 else "", "資料 © OpenStreetMap"]
    return front, back


def datapack_entries(sights):
    """給 ride_plan 的純資料：每座景點的名字、最近的站、傳送點（有 spots 的才收）。"""
    out = []
    for a in sights:
        sp = a.spots()
        if not sp:
            continue
        st = getattr(a, "station", None)
        out.append(dict(id=a.id, name_zh=a.name_zh, name_en=a.name_en,
                        station=(st[0], st[1], int(st[2]), st[3]) if st else None,
                        facts=[str(t) for t in a.plaque()[2:3] if t],
                        spots=[s._asdict() for s in sp]))
    return out


# ---------------------------------------------------------------- 退路：照 OSM 擠出量體

class OsmMassing(Attraction):
    """沒有專屬模組的景點：building / building:part 照 height（或樓層 × 3.5 m）擠出，
    外牆開窗、平頂。位置、輪廓、高度是 OSM 的；長相只是量體。"""

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
        # 觀景點：輪廓外南側 1.5 倍半徑處，看向量體中段
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
