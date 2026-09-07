#!/usr/bin/env python3
"""真實出入口與轉乘通道生成器：把 domain/exits.py 算好的計畫變成可以 build() 的物件。

每座車站原本只有一座樣板樓梯。這裡照 `data/entrances.json` 的真實座標與編號，
替每個出入口蓋一座折返式樓梯井（ShaftStair）接到穿堂層，再用一段接駁通道
（Tile）沿站體外側接進穿堂層的非付費區。三樣東西全部沿用地下街的那一套
零件 —— 台北車站的連絡梯就是這麼接的，只是把 g0 從「地下街樓板」換成
「真實地面」。

三種車站三種穿堂（alignment.station_kind）：地下站的穿堂在軌面 +7，井從街上
往下挖；高架站的穿堂在橋下（軌面 -6），井從街上往上爬、通道是空橋；平面站
的穿堂跨在月台上方（軌面 +8）。井是同一座，只是哪一扇門在上面不一樣。

轉乘站的兩座站體之間再接一條轉乘通道（付費區對付費區）：兩層一樣高就
一條通道，不一樣高就在兩座站體之間立一座井，兩層各接一段通道到井的門。

沒有真實出入口資料的車站（機場線桃園段、安坑輕軌、淡海輕軌的平面站）
用一個預設位置的出入口走同一套流程，全網每一座車站都能從街上走到月台。

回傳的物件都有 bbox() 與 build(w)，跟其他地標一樣由 cli/build_world 依 region
分桶。地下的通道標 underground=True（不必為它生成地形），樓梯井與空橋不標
—— 它們露在街上，四周要有真實地形才不會懸空或被埋。

自我測試: ./.venv/bin/python tests/test_exits.py
"""
import collections

from mrt.application import build_concourse as BCC
from mrt.domain import exits as EX
from mrt.domain.alignment import station_kind
from mrt.domain.stacked import station_samples

PIER_EVERY = 6         # 空橋每幾公尺一根柱
APRON = "minecraft:grass_block"   # 出入口門前的前庭地坪：算地形，驗證「門開在街上」認它


def sign_lines(refs, name_zh, name_en):
    """出口牌的四行：編號、站名、英文站名、Exit。"""
    tags = [str(r) for r in refs if str(r)]
    tag = "/".join(tags[:3]) if tags else ""
    return [("出口 " + tag).strip(), name_zh or "", name_en or "",
            ("Exit " + tag).strip()]


def transfer_lines(ref, name_zh, name_en):
    """轉乘井門邊的牌子：往哪條線。"""
    return ["轉乘 Transfer", f"往 {ref} 線", name_zh or "", name_en or ""]


def footprint(objs, used=None):
    """把一批地標的占用格加進 Occupancy（Tile 用實際地板與牆，其餘用 bbox，
    高度一律當成整根柱子）。

    出入口井不能壓到台北車站的地下街 —— 中山地下街一路通到雙連，
    中山站與雙連站的出入口井從地面挖下去，正好穿過它。
    """
    used = EX.Occupancy() if used is None else used
    for o in objs:
        cells = getattr(o, "cells", None)
        if cells is not None and getattr(o, "ring", None) is not None:
            for x, z in set(cells) | set(o.ring):
                used.add(x, z, -64, 319)
            continue
        x0, z0, x1, z1 = o.bbox()
        for x in range(int(x0), int(x1) + 1):
            for z in range(int(z0), int(z1) + 1):
                used.add(x, z, -64, 319)
    return used


def make_well(s, sign):
    """照計畫蓋一座出入口井。街面比穿堂高就從街上往下挖（地下站），
    反過來就從街上往上爬（高架站）—— 出口牌一律立在街上那扇門邊。"""
    street = s["g0"] + 1
    if street > s["y_to"]:
        return BCC.ShaftStair(s["x0"], s["z0"], s["ux"], s["uz"], s["g0"], s["y_to"],
                              bottom_door=True, sign=sign, apron=APRON)
    return BCC.ShaftStair(s["x0"], s["z0"], s["ux"], s["uz"], s["y_to"] - 1, street,
                          bottom_door=True, sign_bottom=sign, apron=APRON)


class GroundGate:
    """平面出入口：通道直接開到街上，門外接一段坡道與前庭。

    高架站的橋下穿堂只比地面高 3～7 m，山坡上的出入口街面可能就在穿堂那個
    高度前後兩公尺內。這時折返梯井蓋不出來：井的兩扇門開在同一面牆上，落差
    不到三格井底的門洞只剩一格，門前的前庭又剛好清掉空橋的樓板（淡江大學的
    預設出入口就是這樣「門口沒有接到街面」）。差 0～2 m 根本不需要井 ——
    通道的盡頭就是門，門外每格升降一格接到街面，再鋪一小塊前庭。

    座標系與 ShaftStair 一樣：(x0, z0) 是門那一格（通道的最後一格，地板由
    通道鋪），u = (ux, uz) 指向街上，坡道與前庭在 a = 1..run、b = -half..half。
    通道的地板要先蓋（通道的刷寬會蓋過 a = 1..2），這裡再把它們改成坡道。
    """

    def __init__(self, x0, z0, ux, uz, street, level, sign=None,
                 step=BCC.STAIR, apron=APRON, run=EX.GATE_RUN, half=EX.PASS_HALF):
        self.x0, self.z0 = int(x0), int(z0)
        self.ux, self.uz = int(round(ux)), int(round(uz))
        self.street, self.level = int(street), int(level)   # 街面與穿堂的站立高度
        self.sign = list(sign) if sign else None
        self.step, self.apron = step, apron
        self.run, self.half = int(run), int(half)

    def _w(self, a, b):
        vx, vz = -self.uz, self.ux
        return self.x0 + self.ux * a + vx * b, self.z0 + self.uz * a + vz * b

    def bbox(self):
        pts = [self._w(a, b) for a in (0, self.run + 1)
               for b in (-self.half - 1, self.half + 1)]
        xs = [p[0] for p in pts]; zs = [p[1] for p in pts]
        return min(xs) - 1, min(zs) - 1, max(xs) + 1, max(zs) + 1

    def floor_at(self, a):
        """門外第 a 格的地坪：從通道樓板每格升降一格接到街面，之後就是街面。"""
        d = self.street - self.level
        sgn = (d > 0) - (d < 0)
        return self.level - 1 + sgn * min(a, abs(d))

    def build(self, w):
        for a in range(1, self.run + 1):
            y = self.floor_at(a)
            blk = self.apron if y == self.street - 1 else self.step
            for b in range(-self.half, self.half + 1):
                x, z = self._w(a, b)
                w.set(x, y, z, blk)
                for yy in range(y + 1, y + 4):
                    w.set(x, yy, z, BCC.AIR)
        # 出口牌立在前庭旁邊、街上那一頭，牌面朝著從街上走過來的人
        if self.sign and hasattr(w, "sign"):
            x, z = self._w(self.run, self.half + 1)
            w.set(x, self.street - 1, z, self.step)
            w.sign(x, self.street, z, self.sign[:4], facing=(self.ux, self.uz))
            w.set(x, self.street + 1, z, BCC.AIR)


def make_gate(s, sign):
    """照計畫蓋一座平面出入口（exits.plan_station 的 gates 項目）。"""
    return GroundGate(s["x0"], s["z0"], s["ux"], s["uz"], s["g0"] + 1, s["y_to"],
                      sign=sign)


def make_tile(cells, no_wall, level, kind, ground_at):
    """一層的通道地板：地下站是隧道，其餘是玻璃空橋（地形比它低就架柱子）。"""
    ring = BCC.outer_ring(cells) - no_wall
    if kind == "tunnel":
        tile = BCC.Tile(cells, ring, level, {}, shopfront=False)
        tile.underground = True
        return tile
    piers = {}
    for x, z in cells:
        if x % PIER_EVERY == 0 and z % PIER_EVERY == 0:
            g = int(ground_at(x, z))
            if g < level - 2:
                piers[(x, z)] = g
    tile = BCC.Tile(cells, ring, level, {}, shopfront=False, bridge=True, pier_to=piers)
    tile.underground = False
    return tile


def station_exits(segs, entrances_by_name, ground_at, skip=(), used=None,
                  verbose=True, no_transfer=(), no_default=()):
    """替所有車站蓋真實出入口，再替轉乘站接轉乘通道。

    segs               cli 規劃好的路段（samples / ys / ground / stn / hw）
    entrances_by_name  {站名: [(ref, x, z)]}
    ground_at          f(x, z) -> 地面 y
    skip               不處理的站名（台北車站一帶由地下街負責）
    used               Occupancy，已被其他地標占用的格子（footprint() 的結果）
    no_transfer        不接轉乘通道的站名（台北車站複合體靠地下街轉乘）
    no_default         沒有出入口也不補預設出入口的站名（複合體由地下街的連絡梯進出）

    回傳 (objects, exits, report)：
      exits   {(路段索引, 取樣索引): 井的數量}，cli 用它關掉樣板樓梯
      report  {站名: dict(built, skipped, transfer)}
    """
    used = EX.Occupancy() if used is None else used
    occ = EX.index_segments(segs)

    # 站體座標系用 stacked.station_samples：共用站體（西門）的是兩線中線的 frame，
    # 出入口與轉乘通道都要接到那座箱涵的側牆，不是接到路線自己的中心線旁邊
    boxes = collections.defaultdict(dict)          # 站名 -> {(li, bi): ...}
    labels = {}
    for li, sg in enumerate(segs):
        for bi, (full, name, en) in sg["stn"].items():
            boxes[name][(li, bi)] = (station_samples(sg, bi), sg["ys"], bi)
            labels[(li, bi)] = (full, name, en)

    objs, exits, report = [], {}, {}
    floors = collections.defaultdict(set)          # (li, bi, level) -> 地板格
    no_wall, kinds = {}, {}
    wells = []                                     # 井要排在地板之後蓋
    n_default = n_tr = n_all = 0

    def interior_of(key):
        sg = segs[key[0]]
        fr = station_samples(sg, key[1])
        lo, hi, _ = EX.station_frame(fr, sg["ys"], key[1])
        return EX.box_cells(fr, lo, hi, EX.BOX_HALF - 2)

    def kind_of(key):
        sg = segs[key[0]]
        return station_kind(int(sg["ys"][key[1]]), int(sg["ground"][key[1]]))

    def plan_exits(name, key, ents, used_):
        """一座站體的出入口。回傳 (計畫, 井)。"""
        li, bi = key
        sg = segs[li]
        plan = EX.plan_station(station_samples(sg, bi), sg["ys"], sg["ground"], bi,
                               ents, ground_at, occ, used_, own_tag=li,
                               ally_tags=sg.get("ally_segs", {}).get(bi, ()))
        out = []
        full, zh, en = labels[key]
        for s in plan["shafts"]:
            well = make_well(s, sign_lines(s["refs"], zh, en))
            well.label = (name, s["refs"])
            well.underground = False
            out.append(well)
        for s in plan["gates"]:
            gate = make_gate(s, sign_lines(s["refs"], zh, en))
            gate.label = (name, s["refs"])
            gate.underground = False
            out.append(gate)
        plan["built"] = plan["shafts"] + plan["gates"]
        return plan, out

    def plan_transfers(name, used_):
        """一座轉乘站的所有站體串成一條鏈，逐對接。回傳 [(ka, kb, 結果, 井)]。"""
        keys = sorted(boxes[name])

        def bx(key):
            li, bi = key
            sg = segs[li]
            return dict(samples=station_samples(sg, bi), ys=sg["ys"], grounds=sg["ground"],
                        idx=bi, tag=li, key=key)
        pairs, rest, cur = [], keys[1:], keys[0]
        while rest:
            nxt = min(rest, key=lambda k: _dist(boxes[name][cur], boxes[name][k]))
            pairs.append((cur, nxt)); rest.remove(nxt); cur = nxt
        out = []
        for ka, kb in pairs:
            A, B = bx(ka), bx(kb)
            res = EX.plan_transfer(A, B, occ, used_)
            well = None
            if res["ok"] and res["well"] is not None:
                x0, z0, dx, dz, top, bottom = res["well"]
                # 上層的門通往哪條線，牌子就寫哪條
                (ta, la, _), (tb, lb, _) = res["legs"]
                up_key, lo_key = (ka, kb) if la >= lb else (kb, ka)
                fa, za, ea = labels[lo_key]
                fb, zb, eb = labels[up_key]
                well = BCC.ShaftStair(x0, z0, dx, dz, top - 1, bottom, bottom_door=True,
                                      sign=transfer_lines(segs[lo_key[0]]["ref"], za, ea),
                                      sign_bottom=transfer_lines(segs[up_key[0]]["ref"], zb, eb))
                well.label = (name, "轉乘")
                well.underground = False
            out.append((ka, kb, res, well))
        return out

    def plan_name(name, assigned, order, used_):
        """一座車站（所有站體）的完整計畫。order "tr" 先接轉乘再接出入口，
        "ex" 反過來。回傳 dict(score, wells, floors, exits, built, skipped, transfer)。"""
        r = dict(score=0, wells=[], floors=collections.defaultdict(set), exits={},
                 built=[], skipped=[], transfer=None, n_default=0, open={})
        do_tr = name not in no_transfer and len(boxes[name]) >= 2

        def exits_pass():
            for key, mine in assigned.items():
                if mine:
                    plan, ws = plan_exits(name, key, mine, used_)
                    r["skipped"] += plan["skipped"]
                    r["built"] += plan["built"]
                    if plan["built"]:
                        r["floors"][(key[0], key[1], plan["ym"])] |= plan["cells"]
                        r["open"].setdefault(key, set()).update(plan["open"])
                        r["wells"] += ws
                        r["exits"][key] = r["exits"].get(key, 0) + len(plan["built"])
                if key in r["exits"] or name in no_default:
                    continue
                # 沒有資料、或全部接不上：用預設位置的出入口，兩側各試一次
                samples, ys, bi = boxes[name][key]
                for e in EX.default_entrances(samples, ys, bi):
                    plan, ws = plan_exits(name, key, [e], used_)
                    if plan["built"]:
                        r["built"] += plan["built"]
                        r["floors"][(key[0], key[1], plan["ym"])] |= plan["cells"]
                        r["open"].setdefault(key, set()).update(plan["open"])
                        r["wells"] += ws
                        r["exits"][key] = len(plan["built"])
                        r["n_default"] += 1
                        break

        def transfer_pass():
            r["transfer"] = plan_transfers(name, used_)
            for ka, kb, res, well in r["transfer"]:
                if not res["ok"]:
                    continue
                for tag, level, cells in res["legs"]:
                    key = ka if tag == ka[0] else kb
                    r["floors"][(key[0], key[1], level)] |= cells
                if well is None:
                    # 同一層直接接：這片地板一頭在 A 站體、另一頭穿進 B 站體，
                    # B 的穿堂裡也不准砌牆，否則洞口內側會被這片地板的外緣封死
                    # （紅樹林 R/V 就是這樣：通道蓋好了，從淡水線那頭走不進去）
                    r["open"].setdefault(ka, set()).update(interior_of(kb))
                    r["open"].setdefault(kb, set()).update(interior_of(ka))
                else:
                    r["wells"].append(well)

        if order == "tr" and do_tr:
            transfer_pass(); exits_pass()
        else:
            exits_pass()
            if do_tr:
                transfer_pass()
        n_ok = sum(1 for t in r["transfer"] if t[2]["ok"]) if r["transfer"] else 0
        # 一條轉乘通道抵四座出入口：少接一座出入口只是繞遠，兩座站體不通是斷的
        r["score"] = len(r["built"]) + 4 * n_ok
        return r

    for name in sorted(boxes):
        if name in skip:
            continue
        ents = entrances_by_name.get(name) or []
        # 先併掉重複的節點，再分派到站體：同編號的兩個節點若分到兩座站體，
        # 後規劃的那條通道一定撞上先蓋的那座井
        merged = [("/".join(g["refs"]), g["x"], g["z"])
                  for g in EX.merge_entrances(ents)]
        assigned = EX.assign_to_boxes(merged, boxes[name])
        # 轉乘站兩種順序都試，留分數高的：先接轉乘通道的話井有地方放，
        # 但可能擋掉一兩座出入口；先接出入口的話轉乘通道可能擠不進去
        best = None
        orders = ("ex", "tr") if (name not in no_transfer and len(boxes[name]) >= 2) else ("ex",)
        for order in orders:
            trial = used.copy()
            r = plan_name(name, assigned, order, trial)
            if best is None or r["score"] > best[0]["score"]:
                best = (r, trial)
        r, trial = best
        used.cells = trial.cells
        for k, cells in r["floors"].items():
            floors[k] |= cells
            no_wall.setdefault(k[:2], interior_of(k[:2]))
            kinds.setdefault(k[:2], kind_of(k[:2]))
        for k, cells in r["open"].items():
            no_wall.setdefault(k, interior_of(k)).update(cells)
        wells += r["wells"]
        exits.update(r["exits"])
        n_default += r["n_default"]
        if r["transfer"]:
            n_all += len(r["transfer"])
            n_tr += sum(1 for t in r["transfer"] if t[2]["ok"])
        report[name] = dict(built=r["built"], skipped=r["skipped"],
                            transfer=[(ka, kb, res) for ka, kb, res, _ in r["transfer"]]
                            if r["transfer"] else None)

    # ---- 地板（每座站體每一層一片），然後才是井與平面出入口：井要在地板之後蓋，
    #      井壁才會把通道刷到的那一排補回去、門才開得出來；坡道要把通道刷過去的
    #      那兩格樓板改成階梯 ----
    for (li, bi, level), cells in sorted(floors.items()):
        objs.append(make_tile(cells, no_wall[(li, bi)], level, kinds[(li, bi)], ground_at))
    objs += wells

    if verbose:
        nb = sum(len(r["built"]) for r in report.values())
        ng = sum(1 for o in wells if isinstance(o, GroundGate))
        ns = sum(len(r["skipped"]) for r in report.values())
        why = collections.Counter(s[3] for r in report.values() for s in r["skipped"])
        print(f"  真實出入口：{len(exits)} 座站體共 {nb} 座"
              + (f"（{nb - ng} 座樓梯井、{ng} 座平面出入口" if ng else "（")
              + (f"；{n_default} 座是沒有資料的車站的預設出入口）" if n_default else "）")
              + (f"，接不上的 {ns} 個（"
                 + "、".join(f"{k} {v}" for k, v in why.most_common()) + "）"
                 if ns else ""))
        bad = [(n, r["transfer"]) for n, r in report.items()
               if r["transfer"] and any(not t[2]["ok"] for t in r["transfer"])]
        print(f"  轉乘通道：{n_tr}/{n_all} 條"
              + (f"，接不上：" + "；".join(
                  f"{n}（{t[2]['reason']}）" for n, ts in bad for t in ts if not t[2]["ok"])
                 if bad else ""))
    return objs, exits, report


def _dist(a, b):
    sa, ya, ia = a
    sb, yb, ib = b
    return ((sa[ia][0] - sb[ib][0]) ** 2 + (sa[ia][1] - sb[ib][1]) ** 2) ** 0.5
