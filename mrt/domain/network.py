#!/usr/bin/env python3
"""路網：下一站是哪一站、往哪個終點、在月台的哪裡上車 —— 搭乘系統的純規則。

世界蓋得出 253 km 的路網，可是玩家只靠走路逛不完。搭乘系統讓玩家在月台上
右鍵點一面告示牌就「坐到下一站」：資料包把人傳送到下一站同一個行車方向的月台上，
正好站在繼續往前那一面告示牌的前面 —— 連點幾下就是坐好幾站。

三件事都得跟生成器蓋出來的東西一格不差，所以都在這裡算、只算一次：

  · **行車方向**：北捷靠右行駛，往取樣順序 +u 開的列車走 +off 那股道
    （``stacked.upper_side`` 同一條規則）。島式月台上 +側的月台門對著往 +u 的
    列車；疊式站則是「哪一層」由 upper_toward 決定、「哪一側」由路線決定。
  · **月台上的位置**：告示牌立在月台門那一排（取代那一格玻璃，跟原本的站名牌
    同一個位置），人站在往月台內側兩格、面向月台門。
  · **下一站與終點**：沿每一個選用變體的取樣順序排出車站序列，相鄰兩站就是
    一段車程。同一條線的支線在分歧站自然長出第三個方向（大橋頭往蘆洲、
    往迴龍都在同一側月台，各佔一面牌）。

這一層不知道 Minecraft 的指令長怎樣：函式 id 只是一個路徑（"ride/bl12_bl13"），
命名空間在 config、指令字串由 application 組、檔案由 infrastructure 寫。
"""
import math

from mrt.domain import stacked as SK
from mrt.domain.alignment import (
    PLATFORM_LEN, PLAT_HALF, STEP, structure_for_ground,
)

# 路線名稱是事實資料（臺北捷運、新北捷運、桃園捷運的正式路線名）。
# 顏色不寫在這裡：沿用 data/mc_lines.json 裡 OSM 的 colour 標籤（跟 README 的
# 全網圖同一份），由 cli 讀進來傳給 line_colours()。
LINE_NAMES = {
    "BR": ("文湖線", "Wenhu Line"),
    "R":  ("淡水信義線", "Tamsui-Xinyi Line"),
    "G":  ("松山新店線", "Songshan-Xindian Line"),
    "O":  ("中和新蘆線", "Zhonghe-Xinlu Line"),
    "BL": ("板南線", "Bannan Line"),
    "Y":  ("環狀線", "Circular Line"),
    "A":  ("桃園機場捷運", "Taoyuan Airport MRT"),
    "K":  ("安坑輕軌", "Ankeng LRT"),
    "V":  ("淡海輕軌", "Danhai LRT"),
    "LB": ("三鶯線", "Sanying Line"),
}

# OSM 的 colour 偶爾寫 CSS 色名（中和新蘆線是 "orange"）
_CSS = {"orange": "#FFA500", "red": "#FF0000", "green": "#008000", "blue": "#0000FF",
        "yellow": "#FFFF00", "brown": "#A52A2A", "purple": "#800080"}

# 月台上告示牌的位置（離站體 lo 端幾公尺）。第一個是「主位」：從上一站坐過來的人
# 就站在主位那面牌的前面。避開島式月台的兩座樓梯（沿線 24..34、48..58 m，離線位
# −3..3）與側式月台 hi 端的樓梯（最早從 53 m 起）；也不能落在月台門的門洞上
# （沿線每 7 m 開一次、開 2 m：along % 7 < 2 的那幾格是空氣）。地下站的三個位置
# 就是原本站名牌的位置。
SLOTS_UNDER = (40, 20, 60)
SLOTS_SIDE = (37, 16, 51)
DOOR_EVERY, DOOR_OPEN = 7.0, 2.0     # 與 build_line 的月台門同一個節奏
STAND_IN = 2          # 人站在月台門往月台內側幾格
SEQ_AHEAD_M = 40.0    # 判斷「往那一站是站體的哪個方向」時，沿路線往前看幾公尺


# ---------- 小工具 ----------

def line_code(full_ref, ref):
    """"R10;BL12" 在 BL 線上的站號 -> "BL12"（沒有就 None）。"""
    for t in str(full_ref).split(";"):
        t = t.strip()
        if t.startswith(ref) and len(t) > len(ref) and t[len(ref)].isdigit():
            return t
    return None


def fn_code(code):
    """站號 -> 函式路徑用的小寫代號（資料包的資源路徑只准 a-z0-9_.-/）。"""
    return "".join(ch for ch in code.lower() if ch.isalnum() or ch == "_")


# 路線圖對話框（售票機的告示牌、快捷鍵、暫停選單都打開這一個）與各線的站表
MENU_DIALOG = "network"


def line_dialog(ref):
    return "line/%s" % fn_code(ref)


def ride_fn(code_from, code_to):
    return "ride/%s_%s" % (fn_code(code_from), fn_code(code_to))


def go_fn(code):
    return "go/%s" % fn_code(code)


def turn_fn(code, d):
    """終點站：點了換到對面月台（d 是這一側在站體座標系的方向）。"""
    return "turn/%s_%s" % (fn_code(code), "p" if d > 0 else "m")


def yaw_of(fx, fz):
    """面向 (fx, fz) 的 Minecraft 偏航角：0 = 南、90 = 西、180 = 北、-90 = 東。"""
    return round(math.degrees(math.atan2(-fx, fz)), 1)


def code_sort_key(code):
    """站號自然排序：G03 < G03A < G04、O21 < O50。"""
    i = 0
    while i < len(code) and not code[i].isdigit():
        i += 1
    j = i
    while j < len(code) and code[j].isdigit():
        j += 1
    return (code[:i], int(code[i:j]) if j > i else 0, code[j:])


def line_colours(lines_json):
    """{路線: "#rrggbb"}：每條線取最長那個變體的 OSM colour（支線常有自己的顏色，
    例如小碧潭支線、新北投支線，不能讓它們蓋掉幹線的）。"""
    out = {}
    for ref, variants in lines_json.items():
        best = max(variants, key=lambda v: len(v.get("points", ())), default=None)
        c = str((best or {}).get("colour") or "#808080").strip()
        c = _CSS.get(c.lower(), c)
        if not c.startswith("#"):
            c = "#808080"
        out[ref] = c.upper()
    return out


# ---------- 車站序列與方向 ----------

def _seq_of(sg):
    """路段沿取樣順序的車站：[(取樣索引, 站名, 英文名, 站號字串)]。

    用 stn_seq（去重之前的快照）：支線與幹線共用的車站在支線那一段已經被去重
    砍掉，但「支線從七張出發」這件事還是要從支線自己的序列看出來。
    """
    stn = sg.get("stn_seq", sg["stn"])
    return [(bi, v[1], v[2], v[0]) for bi, v in sorted(stn.items())]


class Station:
    """一條線上的一座車站（轉乘站在每條線上各一個）。"""

    def __init__(self, ref, name, en, code):
        self.ref, self.name, self.en, self.code = ref, name, en, code
        self.dirs = {}               # 鄰站名 -> Direction
        self.box = None              # Box：蓋出來的站體（沒蓋就是 None）

    def __repr__(self):
        return "Station(%s %s)" % (self.code, self.name)


class Direction:
    """從某站往某個鄰站：next 是鄰站名，terminals 是這個方向各變體的終點站名。"""

    def __init__(self, nxt):
        self.next = nxt
        self.terminals = []
        self.via = []                # [(路段索引, 本站取樣索引, 鄰站取樣索引)]
        self.d = 0                   # 在站體座標系是 +u (1) 還是 -u (-1)

    def __repr__(self):
        return "Direction(->%s 往%s d=%+d)" % (self.next, "/".join(self.terminals), self.d)


# mc_stations.csv 的英文站名偶有瑕疵，顯示在牌子上之前修一下
_EN_FIX = {"Taipei main station": "Taipei Main Station"}


def display_en(en):
    """顯示用的英文站名：去掉括號註記（廣慈/奉天宮的 "(Under construction)"）。"""
    en = _EN_FIX.get(en, en)
    if "(" in en:
        en = en[:en.index("(")].rstrip()
    return en


def build_network(segs):
    """{(路線, 站名): Station}，含每站往各鄰站的方向與終點站。"""
    # 英文名欄位偶爾是中文（環狀線的大坪林），同名車站在別條線上有英文名就借來用
    en_of = {}
    for sg in segs:
        for _, name, en, _ in _seq_of(sg):
            if any("a" <= ch.lower() <= "z" for ch in en):
                en_of.setdefault(name, en)
    net = {}
    for li, sg in enumerate(segs):
        ref = sg["ref"]
        seq = _seq_of(sg)
        if not seq:
            continue
        first, last = seq[0][1], seq[-1][1]
        for k, (bi, name, en, full) in enumerate(seq):
            code = line_code(full, ref) or full
            st = net.get((ref, name))
            if st is None:
                st = net[(ref, name)] = Station(ref, name, display_en(en_of.get(name, en)), code)
            for kk, term in ((k - 1, first), (k + 1, last)):
                if not (0 <= kk < len(seq)):
                    continue
                nb = seq[kk][1]
                dr = st.dirs.get(nb)
                if dr is None:
                    dr = st.dirs[nb] = Direction(nb)
                if term not in dr.terminals:
                    dr.terminals.append(term)
                dr.via.append((li, bi, seq[kk][0]))
    return net


# ---------- 站體與月台 ----------

class Box:
    """一座蓋出來的站體，與生成器（build_line.build_station）用同一組座標：

    samples  站體座標系的取樣點（共用疊式站是兩線中線的 frame）
    ys       軌面（共用站體用 primary 的，兩線本來就釘成一樣）
    lo, hi   站體範圍的取樣索引
    kind     "island" 地下島式、"side" 高架／平面側式、"stacked_side" 側式疊式、
             "stacked_shared" 兩線共用的島式疊式
    """

    def __init__(self, li, bi, samples, ys, kind, lay=None, side=0):
        n = len(samples)
        half = int(PLATFORM_LEN / 2 / STEP)
        self.li, self.bi = li, bi
        self.samples, self.ys = samples, ys
        self.lo, self.hi = max(0, bi - half), min(n - 1, bi + half)
        self.kind, self.lay, self.side = kind, lay, side
        self.lines = []              # 在這座站體停靠的路線

    @property
    def key(self):
        return (self.li, self.bi)

    def center(self):
        x, z = self.samples[self.bi][:2]
        return x, z

    def cell(self, i, off):
        """取樣點 i、離線位 off 的方塊 (x, z) —— 與 build_line 的取整完全相同。"""
        x, z, ux, uz, _ = self.samples[i]
        nx, nz = -uz, ux
        return round(x + nx * off), round(z + nz * off)

    def normal(self, i):
        x, z, ux, uz, _ = self.samples[i]
        return -uz, ux


def find_boxes(segs):
    """{(路線, 站名): Box}：每條線的每座車站停在哪一座站體。

    一般車站就是 sg["stn"] 裡剩下的那一座；共用疊式站的 partner 在自己的路段上
    已經沒有車站了（stacked.plan_shared 把它拿掉），它停在 primary 蓋的那座站體裡。
    """
    out = {}
    for li, sg in enumerate(segs):
        ref = sg["ref"]
        for bi, (full, name, en) in sg["stn"].items():
            lay = sg.get("stacked", {}).get(bi)
            samples = SK.station_samples(sg, bi)
            if lay is not None:
                tr = lay["tracks"]
                if len(tr) == 1:
                    box = Box(li, bi, samples, sg["ys"], "stacked_side", lay,
                              side=-1 if tr[0] > 0 else 1)
                    box.lines.append(ref)
                    out[(ref, name)] = box
                else:
                    side = 1 if tr[1] > 0 else -1
                    box = Box(li, bi, samples, sg["ys"], "stacked_shared", lay, side=side)
                    box.lines.append(ref)
                    out[(ref, name)] = box
                    spec = SK.STACKED.get((name, ref), {})
                    pref = spec.get("partner")
                    if pref:
                        box.lines.append(pref)
                        out[(pref, name)] = box
                continue
            y, g = int(sg["ys"][bi]), int(sg["ground"][bi])
            kind = "island" if structure_for_ground(y, g) == "tunnel" else "side"
            box = Box(li, bi, samples, sg["ys"], kind)
            box.lines.append(ref)
            out[(ref, name)] = box
    return out


def _box_direction(box, segs, via):
    """某個方向（沿路段 li 從取樣 i_here 往 i_next）在站體座標系是 +u 還是 −u。

    沿路段往前看 SEQ_AHEAD_M 公尺的那個點，投影到站體中心的切線上看正負。
    不直接比兩站的座標：線形在兩站之間可能大轉彎；也不只比切線：支線在分歧站
    的切線可能跟幹線差很多。
    """
    li, i_here, i_next = via
    sm = segs[li]["samples"]
    sgn = 1 if i_next > i_here else -1
    j = i_here + sgn * int(round(SEQ_AHEAD_M / STEP))
    j = max(0, min(len(sm) - 1, j))
    cx, cz, ux, uz, _ = box.samples[box.bi]
    dot = (sm[j][0] - cx) * ux + (sm[j][1] - cz) * uz
    if abs(dot) < 1e-6:
        dot = (sm[j][2] * ux + sm[j][3] * uz) * sgn
    return 1 if dot > 0 else -1


# ---------- 上車位置 ----------

class Slot:
    """月台上的一面搭車告示牌與它前面的站位。

    sign    告示牌的方塊 (x, y, z)（在月台門那一排）
    face    牌面朝向 (dx, dz)：朝著站位
    stand   人的腳所在的方塊 (x, y, z)
    yaw     站在那裡面向月台門的偏航角
    dest    Direction（None = 這一側沒有下一站，是終點站的到站側）
    lang    "zh" / "en"：同一個方向的牌中英文輪流
    """

    def __init__(self, sign, face, stand, yaw, dest, lang):
        self.sign, self.face, self.stand, self.yaw = sign, face, stand, yaw
        self.dest, self.lang = dest, lang

    def __repr__(self):
        return "Slot(%s %s %s)" % (self.sign, self.lang, self.dest)


class Berth:
    """一座站體裡、一條線、一個行車方向的月台邊：幾面牌、各往哪裡。"""

    def __init__(self, station, box, d, dy0, psd, inward):
        self.station, self.box, self.d, self.dy0 = station, box, d, dy0
        self.psd, self.inward = psd, inward      # 月台門離線位；月台在它的哪一側（±1）
        self.dests = []
        self.slots = []

    @property
    def line(self):
        return self.station.ref

    def primary(self, dest_next=None):
        """主位：dest_next 那個方向的第一面牌（沒指定就是整側的第一面）。"""
        for s in self.slots:
            if dest_next is None or (s.dest is not None and s.dest.next == dest_next):
                return s
        return self.slots[0] if self.slots else None

    def __repr__(self):
        return "Berth(%s %s d=%+d dy0=%d psd=%+d)" % (
            self.station.code, self.station.name, self.d, self.dy0, self.psd)


def _geometry(box, d):
    """(dy0, 月台門離線位, 月台在月台門的哪一側) —— 島式／側式站往 d 方向的月台邊。

    島式：軌道 ±8、月台門 ±6、島在中間（月台在月台門的內側）。
    側式：軌道 ±3、月台門 ±5、月台在 6..10（月台在月台門的外側）。
    """
    if box.kind == "island":
        return 0, d * PLAT_HALF, -d
    return 0, d * (PLAT_HALF - 1), d


def _stacked_geometry(box, ref, d, upper_d):
    """疊式站：上層是往 upper_toward 那個方向，另一個方向在下層。"""
    dy0 = 0 if d == upper_d else -SK.LEVEL_H
    if box.kind == "stacked_side":
        psd = box.lay["psd"][0]
        return dy0, psd, -1 if psd > 0 else 1            # 月台在月台門靠站體中線那一側
    # 共用島式：primary 那條線的股道在 −side，partner 在 +side；島在中間
    primary = ref == box.lines[0]
    psd = (-box.side if primary else box.side) * PLAT_HALF
    return dy0, psd, -1 if psd > 0 else 1


def plan_berths(segs, blocked=None):
    """整個路網的上車位置。回傳 (net, berths)：

    net      build_network 的結果，每個 Station 補上 box 與各方向的 d
    berths   [Berth]，每座站體每條線每個方向一個（沒有車站的方向也有：終點站的
             到站側要立一面「本站終點」的牌，點了換到對面月台）
    blocked  (x, y, z) -> bool：這一格被別的結構占走了（組合根拿地標的範圍做）。
             台北車站的臺鐵／高鐵月台層跟板南線站體在同一個深度，西端北側那一段
             月台門被它整個吃掉 —— 牌子立在那裡是懸在大廳半空中，人也站不住
    """
    net = build_network(segs)
    boxes = find_boxes(segs)
    for key, st in net.items():
        st.box = boxes.get(key)
    # 鄰站沒有蓋出站體的方向搭不了（不會發生在 stn_seq 裡的車站上，但別讓
    # 一面牌指向不存在的車程）
    for (ref, name), st in net.items():
        for nb in [nb for nb in st.dirs if net.get((ref, nb)) is None
                   or net[(ref, nb)].box is None]:
            del st.dirs[nb]
    berths = []
    for (ref, name), st in sorted(net.items(), key=lambda kv: code_sort_key(kv[1].code)):
        box = st.box
        if box is None:
            continue
        for dr in st.dirs.values():
            dr.d = _box_direction(box, segs, dr.via[0])
        upper_d = None
        if box.kind.startswith("stacked"):
            spec = SK.STACKED.get((name, ref), {})
            up = st.dirs.get(spec.get("upper_toward"))
            upper_d = up.d if up is not None else 1
        per = max(1, int(round(1.0 / STEP)))
        slots_m = SLOTS_SIDE if box.kind == "side" else SLOTS_UNDER
        for d in (1, -1):
            if upper_d is None:
                dy0, psd, inward = _geometry(box, d)
            else:
                dy0, psd, inward = _stacked_geometry(box, ref, d, upper_d)
            b = Berth(st, box, d, dy0, psd, inward)
            # 分歧站同一側有兩個方向時，幹線（最長的那個變體）拿主位
            b.dests = sorted((dr for dr in st.dirs.values() if dr.d == d),
                             key=lambda dr: (-max(len(segs[li]["samples"]) for li, _, _ in dr.via),
                                             dr.next))
            k = max(1, len(b.dests))
            for j, along in enumerate(slots_m):
                i = box.lo + along * per
                if not (box.lo < i < box.hi):
                    continue
                nx, nz = box.normal(i)
                y = int(box.ys[i]) + dy0 + 2
                sx, sz = box.cell(i, psd)
                tx, tz = box.cell(i, psd + inward * STAND_IN)
                if blocked is not None and (blocked(sx, y, sz) or blocked(tx, y, tz)):
                    continue
                face = (nx * inward, nz * inward)            # 牌面朝站位
                yaw = yaw_of(-face[0], -face[1])             # 人面向月台門
                dest = b.dests[j % k] if b.dests else None
                lang = "zh" if (j // k) % 2 == 0 else "en"
                b.slots.append(Slot((sx, y, sz), face, (tx, y, tz), yaw, dest, lang))
            berths.append(b)
    return net, berths


def berth_index(berths):
    """{(路線, 站名, d): Berth}"""
    return {(b.line, b.station.name, b.d): b for b in berths}


def arrival(net, bidx, ref, frm, to):
    """從 frm 坐到 to：下車的 Slot（站在繼續往前那面牌的前面）。

    到站的列車在 to 的站體裡朝「遠離 frm」的方向開，所以下車的月台邊是
    d = −(to 往 frm 的方向)。那一側若有好幾個方向（分歧站），優先挑跟這段車程
    同一個變體的那一個 —— 從台北橋坐到大橋頭，繼續往前是往民權西路，不是往三重國小。
    """
    st = net.get((ref, to))
    if st is None or st.box is None or frm not in st.dirs:
        return None
    back = st.dirs[frm]
    b = bidx.get((ref, to, -back.d))
    if b is None or not b.slots:
        return None
    same = {li for li, _, _ in back.via}
    for s in b.slots:
        if s.dest is not None and any(li in same for li, _, _ in s.dest.via):
            return s
    return b.primary()


def rides(net, berths):
    """所有車程：[(路線, 起站 Station, 迄站 Station, 下車 Slot, Direction)]。"""
    bidx = berth_index(berths)
    out = []
    for (ref, name), st in sorted(net.items(), key=lambda kv: code_sort_key(kv[1].code)):
        if st.box is None:
            continue
        for nb, dr in sorted(st.dirs.items()):
            to = net.get((ref, nb))
            if to is None or to.box is None:
                continue
            slot = arrival(net, bidx, ref, name, nb)
            if slot is not None:
                out.append((ref, st, to, slot, dr))
    return out


def home_slot(bidx, st):
    """「去某一站」的目的地：有下一站的那一側的主位（終點站就是出發那一側）。"""
    for d in (1, -1):
        b = bidx.get((st.ref, st.name, d))
        if b is not None and b.dests and b.slots:
            return b.primary()
    for d in (1, -1):
        b = bidx.get((st.ref, st.name, d))
        if b is not None and b.slots:
            return b.slots[0]
    return None
