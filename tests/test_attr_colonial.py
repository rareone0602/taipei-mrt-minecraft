#!/usr/bin/env python3
"""日治時期的三座洋風建築：總統府、國立臺灣博物館、西門紅樓（application/attractions/）。

在平地（y66）上用 DictSink 蓋出來，不產生存檔，驗「長相」裡最要緊、最容易蓋壞的幾件：
  · 總統府：中央塔頂端離地 60 m、塔在正面（東）那一側、兩個中庭是空的（草地、沒有屋頂）、
    外牆紅磚比白色飾帶多、塔身是亞字形（四角缺一塊）
  · 臺博館：圓頂在、頂端近 30 m、正面朝北的六根門廊柱、大廳 32 根柱、
    從門廊前的台階走得進大廳（地板站得住、頭上兩格是空的）、大廳有燈
  · 紅樓：八角樓在（八個方向都有牆、面積約 412 m²）、中央採光塔最高、十字樓的橫翼在
  · 大家：build() 只能用 plan() 查過的地面（cli 在 plan_all 之後就清掉地形快取）、
    蓋兩次一模一樣（跨 region 會被呼叫好幾次）、禁區一格都不寫、說明牌與告示牌的規矩、
    觀景點面向建築、方塊 id 都是 26.2 認得的（裝了遊戲才驗）、不用黃色混凝土

用法: ./.venv/bin/python tests/test_attr_colonial.py
"""
import math
import os
import re
import sys
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from mrt.application import attractions as AT
from mrt.application import signage as SG
from mrt.application.attractions import kit
from mrt.application.attractions import national_taiwan_museum as NTM
from mrt.application.attractions import presidential_office as PO
from mrt.application.attractions import red_house as RH
from mrt.ports.block_sink import DictSink

G = 66
ok = True


def chk(name, cond):
    global ok
    print(("  ok   " if cond else "  FAIL ") + name)
    ok = ok and cond


class StrictGround:
    """平地；plan() 之後再查就丟例外 —— cli 在 plan_all 之後會清掉地形的快取。"""

    def __init__(self):
        self.locked = False

    def __call__(self, x, z):
        if self.locked:
            raise RuntimeError("build() 裡查了 plan() 沒查過的地面 (%d, %d)" % (x, z))
        return G


def make(aid, keep=None):
    items = [i for i in AT.load_items() if i["id"] == aid]
    a = AT.for_world([], items=items)[0]
    ground = StrictGround()
    a.plan(kit.Site(ground, keep))
    a.keep = keep
    ground.locked = True
    w = DictSink()
    t0 = time.time()
    err = None
    try:
        AT.build(a, w, keep)
    except Exception as e:                      # noqa: BLE001 —— 測試要把錯誤印出來
        err = e
    return a, w, time.time() - t0, err


def base(b):
    return b.split("[")[0]


def solid(b):
    return base(b) not in ("minecraft:air", "minecraft:cave_air")


def local_of(a, x, z):
    return a.fr.local(x, z)


def column_top(w, x, z):
    ys = [k[1] for k, b in w.blocks.items() if k[0] == x and k[2] == z and solid(b)]
    return max(ys) if ys else None


def common(a, w, dt, err):
    chk("%s：build() 沒出錯（%s）" % (a.id, err), err is None)
    chk("%s：一座 %.2f 秒、%d 格（要遠低於一分鐘）" % (a.id, dt, len(w.blocks)), dt < 30)
    names = {base(b) for b in w.blocks.values()}
    chk("%s：沒用黃色混凝土（月台警示帶專用）" % a.id, "minecraft:yellow_concrete" not in names)
    for (x, y, z), lines in w.signs.items():
        if lines and lines[0].startswith("出口"):
            chk("%s：告示牌 (%d,%d,%d) 第一行以「出口」開頭" % (a.id, x, y, z), False)
    sp = a.spots()
    chk("%s：有預設觀景點（key 空字串）" % a.id, bool(sp) and sp[0].key == "")
    if sp:
        s0 = sp[0]
        cx, cz = a.center()
        pts = a.outline()
        cx = sum(p[0] for p in pts) / len(pts)
        cz = sum(p[1] for p in pts) / len(pts)
        want = math.degrees(math.atan2(-(cx + 0.5 - s0.x), cz + 0.5 - s0.z))
        dev = abs((s0.yaw - want + 180) % 360 - 180)
        chk("%s：觀景點面向建築（偏 %.0f°）、腳下是地面 y%d" % (a.id, dev, s0.y), dev <= 45 and s0.y == G + 1)
        under = w.get(s0.x, s0.y, s0.z)
        chk("%s：觀景點那一格沒被建築占掉（%s）" % (a.id, under), not solid(under) or "sign" in under)
    zh, en, f1, f2 = a.plaque()
    chk("%s：說明牌第一行是資料裡的中文名「%s」" % (a.id, zh), zh == a.name_zh)
    chk("%s：兩行事實放得下一行告示牌（%d、%d px）" % (a.id, SG.text_width(f1), SG.text_width(f2)),
        SG.text_width(f1) <= SG.SIGN_W and SG.text_width(f2) <= SG.SIGN_W)
    AT.plaque_lines(a)                          # 第一行以「出口」開頭會丟例外
    chk("%s：說明牌立在觀景點旁邊" % a.id, any(abs(k[0] - sp[0].x) <= 3 and abs(k[2] - sp[0].z) <= 3
                                        for k in w.signs))
    # 蓋兩次要一模一樣（跨 region 會各呼叫一次）
    w2 = DictSink()
    AT.build(a, w2, getattr(a, "keep", None))
    chk("%s：蓋兩次結果相同" % a.id, w2.blocks == w.blocks)
    return names


def jar_names():
    jar = os.path.expanduser("~/Library/Application Support/minecraft/versions/26.2/26.2.jar")
    if not os.path.exists(jar):
        return None
    z = zipfile.ZipFile(jar)
    out = {}
    for n in z.namelist():
        m = re.match(r"assets/minecraft/blockstates/([a-z0-9_]+)\.json$", n)
        if m:
            out["minecraft:" + m.group(1)] = n
    return z, out


JAR = jar_names()


def check_ids(aid, w):
    if JAR is None:
        print("  --   沒有裝 26.2，略過方塊 id 檢查")
        return
    z, table = JAR
    bad = sorted({base(b) for b in w.blocks.values()} - set(table))
    chk("%s：方塊 id 都是 26.2 有的（%s）" % (aid, bad[:5]), not bad)
    # 狀態：每個「屬性=值」都要在 blockstates 裡出現過（樓梯的 facing/half、半磚的 type……）
    wrong = set()
    cache = {}
    for b in set(w.blocks.values()):
        if "[" not in b or base(b) not in table:
            continue
        if base(b) not in cache:
            txt = z.read(table[base(b)]).decode("utf-8")
            cache[base(b)] = txt
        txt = cache[base(b)]
        props = b[b.index("[") + 1:-1].split(",")
        for pv in props:
            k, v = pv.split("=")
            if k == "waterlogged" or k in ("persistent", "distance"):
                continue
            if ("%s=%s" % (k, v)) not in txt and ('"%s": "%s"' % (k, v)) not in txt and \
                    ('"%s":"%s"' % (k, v)) not in txt:
                wrong.add(pv + " @" + base(b))
    chk("%s：方塊狀態的值都合法（%s）" % (aid, sorted(wrong)[:4]), not wrong)


# ---------------------------------------------------------------- 總統府
print("總統府")
a, w, dt, err = make("presidential_office")
names = common(a, w, dt, err)
check_ids(a.id, w)
fr = a.fr
tx, tz = fr.cell(PO.TOWER_U, 0.0)
top = column_top(w, tx, tz)
chk("中央塔頂端離地 %s m（公開資料約 60 m）" % (top - G if top else None), top == G + 60)
peak = max(k[1] for k, b in w.blocks.items() if solid(b))
chk("整座最高點就是塔頂（y%d）" % peak, peak == G + 60)
# 塔在正面（東）：塔的局部 u 比外環中點大；最東的建築是車寄
chk("塔樓在東翼（正面朝東、朝凱達格蘭大道）", PO.TOWER_U > 20 and fr.dir(1, 0)[0] > 0.9)
# 亞字形：塔身 +30 的斷面，四個角缺一塊、面的中點有牆
a_, n_ = PO.TOWER_A, PO.TOWER_N
notch, face = [], []
for x in range(tx - 7, tx + 8):
    for z in range(tz - 7, tz + 8):
        u, v = local_of(a, x, z)
        du, dv = abs(u - PO.TOWER_U), abs(v)
        if a_ - n_ + 0.3 < du <= a_ - 0.2 and a_ - n_ + 0.3 < dv <= a_ - 0.2:
            notch.append(solid(w.get(x, G + 33, z)))
        if a_ - 0.8 < du <= a_ and dv < 0.8:
            face.append(solid(w.get(x, G + 33, z)))
# 8.3 m 見方、缺角 1.2 m，斜 5.7° 的格子上缺口只有一兩格：多數是空的就算
chk("塔身是亞字形：四角缺口 +33 多半是空的（%d/%d 格空）、面中點是牆（%d 格）"
    % (notch.count(False), len(notch), len(face)),
    notch and notch.count(False) * 2 >= len(notch) and face and all(face))
# 中庭：草地、上面沒有東西（樹與矮籬除外，都在 +8 以下）
for i, court in enumerate(a.courts):
    cells = fr.cells(court)
    inner = [c for c in cells if kit.erode(court, 3)[c[1] - fr.z0, c[0] - fr.x0]]
    grass = sum(1 for x, z in inner if w.get(x, G, z) in ("minecraft:grass_block", "minecraft:polished_andesite"))
    roofed = sum(1 for x, z in inner if any(solid(w.get(x, y, z)) for y in range(G + 9, G + 30)))
    chk("中庭 %d：%d 格裡地面是草地或步道 %d 格、+9 以上有東西的 %d 格" % (i + 1, len(inner), grass, roofed),
        len(inner) > 500 and grass == len(inner) and roofed == 0)
chk("兩個中庭（日字形）", len(a.courts) == 2)
cnt = {}
for b in w.blocks.values():
    cnt[base(b)] = cnt.get(base(b), 0) + 1
chk("紅磚比白色飾帶多（磚 %d、飾帶 %d）" % (cnt.get("minecraft:bricks", 0), cnt.get("minecraft:calcite", 0)),
    cnt.get("minecraft:bricks", 0) > 2 * cnt.get("minecraft:calcite", 0))
# 四角角塔比主體高：角塔攢尖頂在 +26 以上
hi = [k for k, b in w.blocks.items() if k[1] >= G + 28 and "copper" in b]
chk("角塔與衛塔的銅頂高過主體屋脊（+28 以上有 %d 格銅）" % len(hi), len(hi) > 40)

# 禁區：擋掉一整塊（外環東北角 10x10、地面到塔頂），裡面一格都不寫
x0, z0 = fr.cell(30.0, -60.0)
keep = lambda x, y, z: x0 - 5 <= x <= x0 + 5 and z0 - 5 <= z <= z0 + 5
a2, w2, _, err2 = make("presidential_office", keep=keep)
chk("禁區裡一格都不寫（出入口、地下街的格子）",
    err2 is None and not any(keep(*k) for k in w2.blocks) and len(w2.blocks) > 0)

# ---------------------------------------------------------------- 臺博館
print("\n國立臺灣博物館")
a, w, dt, err = make("national_taiwan_museum")
names = common(a, w, dt, err)
check_ids(a.id, w)
fr = a.fr
dx, dz = fr.cell(0.0, NTM.DOME_V)
top = column_top(w, dx, dz)
chk("圓頂頂端離地 %s m（近 30 m）" % (top - G if top else None), top == G + 30)
dome = [k for k, b in w.blocks.items() if "copper" in b and k[1] >= G + NTM.H_DOME0 + 2
        and math.hypot(*[a_ - b_ for a_, b_ in zip(local_of(a, k[0], k[2]), (0.0, NTM.DOME_V))]) <= NTM.DOME_R]
chk("圓頂殼在（鼓座上方有 %d 格銅瓦）" % len(dome), len(dome) > 80)
chk("正面朝北（門廊在 -v、Frame 的 v 軸朝南）", NTM.FRONT < NTM.WING_N and fr.dir(0, 1)[1] > 0.99)
# 門廊六根柱：+8 那一層、門廊前緣那一排，數連續的柱身
row = sorted(set(fr.cell(u, NTM.FRONT + 1.0) for u in np.arange(-12.0, 12.01, 0.25)))
runs, prev = 0, False
for x, z in row:
    cur = w.get(x, G + 8, z) == NTM.COLUMN
    if cur and not prev:
        runs += 1
    prev = cur
chk("門廊前排 %d 根多立克柱（六柱式）" % runs, runs == 6)
chk("大廳 %d 根柱（公開資料 32 根）" % a.hall_columns, a.hall_columns == 32)
hall_cols = [k for k, b in w.blocks.items() if k[1] == G + NTM.H_FLOOR + 6 and b == NTM.COLUMN
             and abs(local_of(a, k[0], k[2])[0]) <= NTM.HALL + 0.6
             and abs(local_of(a, k[0], k[2])[1] - NTM.DOME_V) <= NTM.HALL + 0.6]
chk("大廳裡 +8 那一層有 32 格柱身（%d）" % len(hall_cols), len(hall_cols) == 32)


def standable(x, y, z):
    return solid(w.get(x, y - 1, z)) and not solid(w.get(x, y, z)) and not solid(w.get(x, y + 1, z))


# 走得進去：從門廊前的地面，沿中軸往南走到大廳中央，每一步都站得住（台階一次最多上一格）
path = [fr.cell(0.3, v) for v in np.arange(NTM.FRONT - 6.0, NTM.DOME_V + 0.1, 0.5)]
y, walk_ok, where = G + 1, True, None
seen = []
for x, z in path:
    if (x, z) in seen:
        continue
    seen.append((x, z))
    for dy in (0, 1, -1):
        if standable(x, y + dy, z):
            y += dy
            break
    else:
        walk_ok, where = False, (x, y, z, w.get(x, y - 1, z), w.get(x, y, z), w.get(x, y + 1, z))
        break
chk("從館前的地面走上台階、穿過正門走到大廳中央（最後站在 y%d）%s" % (y, "" if walk_ok else where),
    walk_ok and y == G + NTM.H_FLOOR + 1)
lamps = [k for k, b in w.blocks.items() if b == "minecraft:sea_lantern"
         and abs(local_of(a, k[0], k[2])[0]) <= NTM.HALL + 1 and G + 3 <= k[1] <= G + NTM.H_SKY + 1]
chk("大廳有燈（%d 盞海燈）" % len(lamps), len(lamps) >= 12)
sky = [k for k, b in w.blocks.items() if "stained_glass" in b and k[1] == G + NTM.H_SKY]
chk("大廳頂上的彩繪玻璃天窗（%d 格，離一樓地面 %d m）" % (len(sky), NTM.H_SKY - NTM.H_FLOOR - 1), len(sky) > 60)

# ---------------------------------------------------------------- 紅樓
print("\n西門紅樓")
a, w, dt, err = make("red_house")
names = common(a, w, dt, err)
check_ids(a.id, w)
fr = a.fr
octm = a.oct
area = int(octm.sum())
chk("八角樓面積 %d m²（公開資料 412 m²）" % area, abs(area - 412) <= 60)
sectors = [0] * 8
for k, b in w.blocks.items():
    if k[1] != G + 5 or not solid(b):
        continue
    u, v = local_of(a, k[0], k[2])
    r = math.hypot(u, v)
    if RH.A_WALL - 1.5 <= r <= RH.A_WALL / math.cos(math.radians(22.5)) + 0.5:
        sectors[int(((math.degrees(math.atan2(v, u)) + 22.5) % 360) // 45)] += 1
chk("八角樓八個方向都有牆（%s；西面接十字樓）" % sectors, all(s > 0 for s in sectors))
cx, cz = fr.cell(0.0, 0.0)
top = column_top(w, cx, cz)
peak = max(k[1] for k, b in w.blocks.items() if solid(b))
chk("中央採光塔的尖頂是最高點（y%s、離地 %s m）" % (top, top - G if top else None), top == peak == G + RH.H_TOP)
lan = [k for k, b in w.blocks.items() if RH.H_LANTERN[0] <= k[1] - G <= RH.H_LANTERN[1]
       and b == RH.GLASS and math.hypot(*local_of(a, k[0], k[2])) <= RH.A_LANTERN + 0.8]
chk("採光塔四周開窗（%d 格玻璃）" % len(lan), len(lan) >= 4)
xs, zs = fr.cell((RH.CROSS_U[0] + RH.CROSS_U[1]) / 2, RH.CROSS_V[0] + 3.0)
xn, zn = fr.cell((RH.CROSS_U[0] + RH.CROSS_U[1]) / 2, RH.CROSS_V[1] - 3.0)
chk("十字樓的橫翼南北兩端都有屋頂", column_top(w, xs, zs) and column_top(w, xn, zn)
    and column_top(w, xs, zs) >= G + RH.H_HALL_ROOF)
fx, fz = fr.cell(RH.A_WALL + 0.6, 0.0)
chk("正門上方的招牌寫著「西門紅樓」", any(v[0] == "西門紅樓" for v in w.signs.values()))
chk("正門朝向紅樓廣場（觀景點在八角樓正面那一側）", a.spots()[0].x > cx - 1e9 and a.spot_uv()[0] > RH.A_WALL)

print("\n登錄表")
reg = AT.registry()
chk("三座都登記了專屬類別", reg.get("presidential_office") is PO.PresidentialOffice
    and reg.get("national_taiwan_museum") is NTM.NationalTaiwanMuseum and reg.get("red_house") is RH.RedHouse)

print("\n" + ("全部通過" if ok else "有測試失敗"))
sys.exit(0 if ok else 1)
