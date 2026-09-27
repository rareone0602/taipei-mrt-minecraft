#!/usr/bin/env python3
"""車站裡的告示牌與路線色：搭車告示牌、路線色帶、穿堂指引、出口牌的樣式。

下一站是哪一站、牌子立在月台門的哪一格、人站在哪裡，全部由 domain/network.py
算好（plan_berths）—— 資料包的傳送目的地也是同一份。這裡只決定「牌子上寫什麼、
用什麼顏色、立在哪個方塊上」，照著立。

以「一座站體」為單位，cli 在每個 region 蓋完車站之後呼叫 station_signage 一次：
同一座站體跨兩個 region 時兩邊各立一次，範圍外的方塊由 World 自己丟掉。

1. 搭車告示牌（ride_signs）：每個 network.Slot 一面，立在月台門那一排、取代那一格
   玻璃（原本的站名牌也是立在這裡）。寫「往哪裡、下一站、本站、點了搭車」，
   點擊指令是 `function <命名空間>:ride/<本站>_<下一站>`；終點站到站側寫
   「本站終點、請至對面月台」，點了換到對面月台（turn）。
2. 路線色帶（line_bands）：站體裡軌道外側那面牆在月台人眼的高度砌兩排路線色，
   隔著月台門看得到；月台門最上面那一排換成路線色的門楣。疊式站兩層都砌，
   共用站體每一側照那一側的路線。
3. 穿堂指引（concourse_signs）：閘門機箱上立一面雙面牌 —— 正面朝非付費區寫
   「往月台」與這條線往哪些終點，背面朝付費區寫「往出口」；非付費區立一台
   「路線圖／售票機」，點了打開路線圖對話框；側式站穿堂的兩座月台樓梯口各立一面
   「往哪個終點」（兩座月台方向不同，島式站不必）；疊式站上層月台往下層的樓梯口、
   下層月台往上層的樓梯口各一面。
4. 出口牌的樣式（exit_sign_lines、SIGN_STYLE）：第一行（出口編號）上路線色，
   純文字一個字都不改 —— tools/verify_exits.py 靠「第一行以『出口』開頭、第二行是
   站名」認出入口亭。**這裡立的其他牌子第一行都不准以「出口」開頭。**

所有牌子都是淡色木頭（pale_oak）＋發光墨水：北捷的站內標誌是白底，站體裡又暗，
發光的黑字在淡色板子上會描一圈米白色的邊，暗處也讀得出來。路線色太淺的
（環狀線的黃、輕軌的粉彩色）在淡色板子上讀不出來，一律先調暗（ink）。
"""
import colorsys

from mrt.config import DATAPACK_NS
from mrt.domain import network as NW
from mrt.domain import stacked as SK
from mrt.domain.alignment import (
    BOX_HALF, LEVEL_DY, PIER_EVERY, PLAT_HALF, STEP, station_kind,
)
from mrt.ports.block_sink import DictSink
from mrt.application import build_line as BL
from mrt.application.attractions.kit import sight_fn

# ---------- 牌子的樣式 ----------

SIGN_WOOD = "pale_oak"
SIGN_STYLE = dict(wood=SIGN_WOOD, kind="standing", glow=True, color="black")
SIGN_W = 90            # 立牌與壁掛牌一行最寬 90 px，超過的部分遊戲直接不畫
BG_LUM = 0.70          # pale_oak 木板（約 #E3D9D3）的相對亮度
MIN_CONTRAST = 3.0     # 路線色字跟板子至少要有的對比（WCAG 大字的門檻）

# Minecraft 預設字型的字寬（含 1 px 字距）。沒列的 ASCII 一律 6；非 ASCII
# （中文、箭頭、全形符號）走 unifont，全形字 16 px 寬縮一半再加字距約 9。
# 寧可高估：估少了字會被遊戲切掉，估多了只是早一點換成縮寫。
_ASCII_W = {" ": 4, "!": 2, "'": 3, ",": 2, ".": 2, ":": 2, ";": 2, "|": 2,
            "i": 2, "l": 3, "`": 3, "I": 4, "t": 4, "[": 4, "]": 4, '"': 5,
            "(": 5, ")": 5, "{": 5, "}": 5, "*": 5, "f": 5, "k": 5, "<": 5,
            ">": 5, "@": 7, "~": 7}
WIDE_W = 9


def text_width(s, bold=False):
    """一行字在告示牌上的寬度（px）。粗體每個字多 1 px。"""
    w = 0
    for ch in str(s):
        w += _ASCII_W.get(ch, 6) if ord(ch) < 128 else WIDE_W
        if bold:
            w += 1
    return w


def line_width(item):
    """一行告示牌文字（純字串或 dict）的寬度。"""
    if isinstance(item, dict):
        return text_width(item.get("text", ""), bool(item.get("bold")))
    return text_width(item)


def fit(cands, bold=False, width=SIGN_W):
    """候選寫法裡第一個放得下的；都放不下就把最後一個截短、補「…」。"""
    cands = [c for c in cands if c is not None]
    for c in cands:
        if text_width(c, bold) <= width:
            return c
    s = cands[-1] if cands else ""
    while s and text_width(s + "…", bold) > width:
        s = s[:-1]
    return s.rstrip() + "…"


def styled(cands, color=None, width=SIGN_W):
    """路線色／強調的那一行：候選照順序試（前面的資訊多），每個先試粗體、放不下
    再試細體；全部放不下就把最後一個截短。"""
    for c in cands:
        for bold in (True, False):
            if text_width(c, bold) <= width:
                return _item(c, color, bold)
    return _item(fit(cands, False, width), color, False)


def _item(text, color, bold):
    d = dict(text=text)
    if color:
        d["color"] = color
    if bold:
        d["bold"] = True
    return d


# 英文站名太長的時候依序套用的縮寫（先套最不傷辨識度的）。最後才從尾巴一個字
# 一個字拿掉。站名本身是 OSM 的 name:en，這裡只是顯示用的簡寫。
_EN_SHORT = [
    (" Temple Station", " Temple"),
    ("Guangci/Fengtian Temple", "Guangci/Fengtian"),
    ("Taipei Nangang Exhibition Center", "Nangang Exhibition Center"),
    ("Exhibition Center", "Exh. Ctr."),
    ("World Trade Center", "WTC"),
    ("Chiang Kai-Shek", "CKS"),
    ("Sun Yat-Sen", "SYS"),
    ("Tamsui Fisherman's Wharf", "Fisherman's Wharf"),
    ("Fisherman's Wharf", "Wharf"),
    ("Memorial Hospital", "Mem. Hosp."),
    ("Memorial Hall", "Mem. Hall"),
    ("Elementary School", "Elem. Sch."),
    ("Junior High School", "Jr. High"),
    ("Senior High School", "Sr. High"),
    ("High School", "High Sch."),
    ("University of Science and Technology", "Univ. of Sci. & Tech."),
    ("University of Marine Technology", "Univ. of Marine Tech."),
    ("University", "Univ."),
    ("Industrial Park", "Ind. Park"),
    ("Software Park", "Software Pk"),
    ("Sports Park", "Sports Pk"),
    ("District Office", "Dist. Office"),
    ("Main Station", "Main"),
    ("HSR Station", "HSR"),
    ("Old Street", "Old St."),
    ("Building", "Bldg"),
    ("Community", "Comm."),
    ("National ", "Natl. "),
    ("Hospital", "Hosp."),
    ("Technology", "Tech."),
    ("Station", "Sta."),
    ("Temple", "Tpl."),
    ("New Taipei", "NT"),
]
_STOP = {"of", "and", "&", "/", "An"}


def en_forms(name):
    """英文站名由長到短的寫法（第一個是原名）。

    先套 _EN_SHORT 的縮寫；還是太長才從尾巴一個字一個字拿掉，但至少留兩個字
    —— 「Taipei Nangang Exhibition Center」砍到剩「Nangang」就跟南港站撞名了。
    有斜線的（台北101/世貿）最後才只留斜線前面那一半。
    """
    out, s = [name], name
    for a, b in _EN_SHORT:
        if a in s:
            s = s.replace(a, b)
            out.append(s)
    words = s.split(" ")
    while len(words) > 2:
        words = words[:-1]
        while len(words) > 2 and words[-1] in _STOP:
            words = words[:-1]
        out.append(" ".join(words))
    if "/" in name:
        out.append(name.split("/")[0])
    seen, res = set(), []
    for f in out:
        f = f.strip()
        if f and f not in seen:
            seen.add(f); res.append(f)
    return res


def _joined_forms(names):
    """幾個英文站名用 / 串起來，由長到短（同一個縮寫程度一起縮）。

    串起來的不拿掉字：「Tamsui Fisherman's Wharf/Kanding」縮成「Tamsui/Kanding」
    就指到淡水站去了。放不下就只寫第一個再補「/…」。"""
    if len(names) == 1:
        return en_forms(names[0])
    forms = []
    for n in names:
        f, s = [n], n
        for a, b in _EN_SHORT:
            if a in s:
                s = s.replace(a, b)
                f.append(s)
        forms.append(f)
    k = max(len(f) for f in forms)
    out = ["/".join(f[min(lv, len(f) - 1)] for f in forms) for lv in range(k)]
    out += [f + "/…" for f in forms[0]]
    return out


def _is_cut(t):
    """「第一個/…」「第一個等」這種只寫了一部分的寫法。"""
    return "…" in t or t.endswith("等")


def _pref(joined, prefix):
    """候選的順序：加前綴（「To 」「For 」「Next: 」…）的完整寫法、不加前綴的完整寫法、
    加前綴的「第一個/…」、不加前綴的「第一個/…」。"""
    full = [j for j in joined if not _is_cut(j)]
    cut = [j for j in joined if _is_cut(j)]
    return ([prefix + j for j in full] + full + [prefix + j for j in cut] + cut)


def _each(joined, prefixes):
    """每一種寫法依序試各個前綴（最後一個通常是空字串），完整的寫法都試完才輪到
    只寫一部分的 —— 「動物園/南港展覽館」比「往 動物園等」有用。"""
    full = [j for j in joined if not _is_cut(j)]
    cut = [j for j in joined if _is_cut(j)]
    return [p + j for j in full + cut for p in prefixes]


def _dir_cands(joined, prefix, arrow):
    """方向那一行的候選：每種寫法依序試「箭頭＋往／To＋終點」「往／To＋終點」
    「箭頭＋終點」「終點」。"""
    out = []
    for j in joined:
        out += [_with_arrow(prefix + j, arrow), prefix + j, _with_arrow(j, arrow), j]
    return out


def _zh_joined(names):
    """幾個中文站名用 / 串起來；放不下的最後一招是「第一個＋等」。"""
    out = ["/".join(names)]
    if len(names) > 1:
        out.append(names[0] + "等")
    return out


# ---------- 路線色 ----------

def _rgb(hexc):
    h = str(hexc).lstrip("#")
    if len(h) != 6:
        return (128, 128, 128)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _lin(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def rel_lum(rgb):
    r, g, b = rgb
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast(rgb, bg_lum=BG_LUM):
    a, b = rel_lum(rgb), bg_lum
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def ink(hexc):
    """路線色 -> 在淡色木板上讀得出來的字色（"#RRGGBB"）。

    夠深的（板南線藍、松山新店線綠、文湖線棕）原樣；太淺的保留色相、往暗調到
    對比 MIN_CONTRAST 以上。粉彩色（淡海輕軌、機場線 OSM 標的淡紫）先把飽和度
    拉到 0.4～0.6 再調暗，否則暗下來只剩一片灰（或變成跟淡水信義線一樣的正紅）。
    """
    rgb = _rgb(hexc)
    if contrast(rgb) >= MIN_CONTRAST:
        return "#%02X%02X%02X" % rgb
    h, l, s = colorsys.rgb_to_hls(*(c / 255.0 for c in rgb))
    if l > 0.75:
        s = min(max(s, 0.4), 0.6)
    while l > 0.05:
        l -= 0.01
        out = tuple(int(round(c * 255)) for c in colorsys.hls_to_rgb(h, l, s))
        if contrast(out) >= MIN_CONTRAST:
            return "#%02X%02X%02X" % out
    return "#202020"


# 色帶用的方塊：混凝土與陶瓦裡顏色最接近的那一種（貼圖平均色）。
# yellow_concrete 不在候選裡：它是月台邊緣的警示帶，verify_exits、verify_rides
# 都靠「黃色混凝土上面那一格」認月台 —— 牆上多一條黃色混凝土就會被當成月台。
BAND_BLOCKS = {
    "white_concrete": (207, 213, 214), "orange_concrete": (224, 97, 1),
    "magenta_concrete": (169, 48, 159), "light_blue_concrete": (36, 137, 199),
    "lime_concrete": (94, 169, 24), "pink_concrete": (213, 101, 142),
    "gray_concrete": (54, 57, 61), "light_gray_concrete": (125, 125, 115),
    "cyan_concrete": (21, 119, 136), "purple_concrete": (100, 32, 156),
    "blue_concrete": (45, 47, 143), "brown_concrete": (96, 60, 32),
    "green_concrete": (73, 91, 36), "red_concrete": (142, 33, 33),
    "black_concrete": (8, 10, 15),
    "white_terracotta": (210, 178, 161), "orange_terracotta": (162, 84, 38),
    "magenta_terracotta": (150, 88, 109), "light_blue_terracotta": (113, 109, 138),
    "yellow_terracotta": (186, 133, 35), "lime_terracotta": (104, 118, 53),
    "pink_terracotta": (162, 78, 79), "gray_terracotta": (58, 42, 36),
    "light_gray_terracotta": (135, 107, 98), "cyan_terracotta": (87, 91, 91),
    "purple_terracotta": (118, 70, 86), "blue_terracotta": (74, 60, 91),
    "brown_terracotta": (77, 51, 36), "green_terracotta": (76, 83, 42),
    "red_terracotta": (143, 61, 47), "black_terracotta": (37, 23, 16),
    "terracotta": (152, 94, 68),
}

# 最接近的顏色偶爾丟掉了路線的辨識度，這幾條手動指定（理由寫在旁邊）。
# 其餘照色差挑：板南線 light_blue_concrete、松山新店線 green_concrete、文湖線
# orange_terracotta、環狀線 yellow_terracotta（黃色混凝土不在候選裡）、三鶯線
# cyan_concrete、安坑與淡海輕軌 white_terracotta。
BAND_OVERRIDE = {
    "R": "red_concrete",         # OSM #FF0000；CIE76 覺得亮橘比暗紅近，淡水信義線不能是橘色
    "O": "orange_concrete",      # OSM orange；最接近的是黃陶瓦，會跟環狀線同一種
    "A": "purple_concrete",      # OSM 標的是地圖用的淡紫 #D4CDE7，最接近的是白混凝土
}


def _lab(rgb):
    def f(t):
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
    r, g, b = (_lin(c) for c in rgb)
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883
    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def nearest_block(hexc):
    """顏色 -> 混凝土／陶瓦裡最接近的方塊（CIE76 色差）。"""
    L0, a0, b0 = _lab(_rgb(hexc))
    best = min(BAND_BLOCKS.items(), key=lambda kv: sum(
        (p - q) ** 2 for p, q in zip(_lab(kv[1]), (L0, a0, b0))))
    return "minecraft:" + best[0]


def band_block(ref, colours):
    if ref in BAND_OVERRIDE:
        return "minecraft:" + BAND_OVERRIDE[ref]
    return nearest_block(colours.get(ref, "#808080"))


def line_ink(ref, colours):
    return ink(colours.get(ref, "#808080"))


# ---------- 搭車告示牌 ----------

RIDE_HINT_ZH = "▶ 右鍵點擊搭車"
RIDE_HINT_EN = ("▶ Right-click to ride", "▶ Click to ride")
TURN_HINT_ZH = "▶ 右鍵點擊換月台"
TURN_HINT_EN = ("▶ Click to cross", "▶ Cross over")


def ride_command(code_from, code_to):
    return "function %s:%s" % (DATAPACK_NS, NW.ride_fn(code_from, code_to))


def turn_command(code, d):
    return "function %s:%s" % (DATAPACK_NS, NW.turn_fn(code, d))


def travel_arrow(berth):
    """列車離站往看牌子的人的哪一邊開："←" 或 "→"。

    人站在站位上面向月台門，右手邊是 inward·u（見 network.plan_berths 的 face），
    列車往 d·u 開，所以 d·inward > 0 就是往右。島式月台上永遠是從右往左
    （靠右行駛、人在兩股道中間）；側式月台人在軌道外側，反過來是從左往右。
    """
    return "→" if berth.d * berth.inward > 0 else "←"


def _with_arrow(text, arrow):
    return (arrow + " " + text) if arrow == "←" else (text + " " + arrow)


def _en(net, ref, name):
    st = net.get((ref, name))
    return st.en if st is not None and st.en else name


def ride_lines(berth, slot, net, colour, opposite=None):
    """一面搭車告示牌的四行（dict 或字串）與點擊指令：(lines, command)。

    opposite 是同一座站體同一條線另一側的 Berth（終點站的到站側要寫對面往哪裡）。
    """
    st = berth.station
    ref = st.ref
    arrow = travel_arrow(berth)
    col = ink(colour)
    if slot.dest is not None:
        dr = slot.dest
        nxt = net.get((ref, dr.next))
        nxt_code = nxt.code if nxt is not None else dr.next
        terms = list(dr.terminals) or [dr.next]
        if slot.lang == "zh":
            lines = [
                styled(_dir_cands(_zh_joined(terms), "往 ", arrow), col),
                fit(["下一站 " + dr.next, "下一站" + dr.next, "下站 " + dr.next]),
                fit([st.code + " " + st.name, st.name]),
                RIDE_HINT_ZH,
            ]
        else:
            en_terms = [_en(net, ref, t) for t in terms]
            head = styled(_dir_cands(_joined_forms(en_terms), "To ", arrow), col)
            nxt_forms = en_forms(_en(net, ref, dr.next))
            nx = [f for f in nxt_forms if text_width("Next: " + f) <= SIGN_W]
            if nx:
                lines = [head, "Next: " + nx[0],
                         fit([st.code + " " + f for f in en_forms(st.en)] + en_forms(st.en)),
                         fit(list(RIDE_HINT_EN))]
            else:
                # 英文站名常常一行放不下「Next: 」加站名（Zhongxiao Fuxing、Shandao
                # Temple……）。這時「下一站」拆成兩行，本站站名讓位 —— 旁邊那面中文牌
                # 有本站站號，下一站卻只有這一面牌講得出英文
                lines = [head, "Next station", fit(nxt_forms), fit(list(RIDE_HINT_EN))]
        return lines, ride_command(st.code, nxt_code)
    # 終點站的到站側：沒有下一站，點了換到對面月台
    other = [t for dr in (opposite.dests if opposite is not None else ())
             for t in (dr.terminals or [dr.next])]
    other = list(dict.fromkeys(other))
    can_turn = opposite is not None and bool(opposite.slots) and bool(opposite.dests)
    if slot.lang == "zh":
        lines = [styled(["本站終點"], col),
                 "請至對面月台" if can_turn else "本站無列車",
                 fit(_pref(_zh_joined(other), "搭往 ")) if other else "",
                 TURN_HINT_ZH if can_turn else ""]
    else:
        en_other = [_en(net, ref, t) for t in other]
        lines = [styled(["Terminus"], col),
                 fit(_pref(_joined_forms(en_other), "For ")) if other else "",
                 "use other side" if can_turn else "No service",
                 fit(list(TURN_HINT_EN)) if can_turn else ""]
    return lines, (turn_command(st.code, berth.d) if can_turn else None)


# 牌子上面還屬於月台門的格子（相對牌子）：島式與疊式站的月台門是軌面 +2..+5
# （+5 是門楣）、牌子在 +2；側式站是 +1..+4（+4 是門楣）、牌子在 +2，底下那一格
# 另外看（_side_below_is_door）
PSD_ABOVE = {"side": (1,)}
PSD_ABOVE_DEFAULT = (1, 2)


def _side_below_is_door(box, cell):
    """側式站牌子底下那一格（軌面 +1）最後是不是門洞。

    那一格有兩種東西會寫：月台門（±5，+1..+4，門洞是空氣）與月台（6..10，+1 是
    警示帶／月台面）。斜的線形上兩者可能取整到同一格，照 build_line._station_side
    第二趟的順序（每個取樣點先月台門、再月台）重跑一次，看最後是誰。只有門洞要補
    玻璃；是月台面的話牌子本來就踩得住，補了反而把警示帶挖掉一格（六張犁就是這樣）。
    """
    state = None
    for i in range(box.lo, box.hi + 1):
        along = (i - box.lo) * STEP
        door = (along % NW.DOOR_EVERY) < NW.DOOR_OPEN
        for off in (-(PLAT_HALF - 1), PLAT_HALF - 1):
            if box.cell(i, off) == cell:
                state = "door" if door else "glass"
        for off in list(range(-10, -5)) + list(range(6, 11)):
            if box.cell(i, off) == cell:
                state = "plat"
    return state == "door"


def ride_signs(w, berths, net, colours):
    """立這批 Berth 的所有搭車告示牌。回傳立了幾面。

    network 挑站位時只避開「沿線 along % 7 < 2」的門洞，可是斜的或彎的線形上
    相距 1 m 的兩個取樣點會取整到同一格：門洞那個取樣點比較晚蓋，牌子那一格
    （連同上面兩格）就變成門洞 —— 台北車站、中正紀念堂的淡水信義線與板橋的板南線
    都是這樣，牌子立在門洞裡、上面空空的（側式站連牌子底下都是空的）。所以立牌
    的時候順手把那一柱月台門補回玻璃：牌子一定在一片玻璃門板的最下面。
    （牌子上面那幾格只有月台門會寫，補玻璃一定對；側式站牌子底下那一格可能是
    月台的警示帶，要先確定是門洞才補。）
    """
    idx = {(b.line, b.station.name, b.d): b for b in berths}
    n = 0
    for b in berths:
        opp = idx.get((b.line, b.station.name, -b.d))
        above = PSD_ABOVE.get(b.box.kind, PSD_ABOVE_DEFAULT)
        for s in b.slots:
            lines, cmd = ride_lines(b, s, net, colours.get(b.line, "#808080"), opp)
            sx, sy, sz = s.sign
            for dy in above:
                w.set(sx, sy + dy, sz, BL.PSD)
            if b.box.kind == "side" and _side_below_is_door(b.box, (sx, sz)):
                w.set(sx, sy - 1, sz, BL.PSD)
            w.sign(sx, sy, sz, lines, facing=s.face, command=cmd, **SIGN_STYLE)
            n += 1
    return n


# ---------- 路線色帶 ----------

PSD_HEADER_DY = {"island": 5, "stacked_side": 5, "stacked_shared": 5, "side": 4}
WALL_BAND_DY = (3, 4)          # 月台上人眼的高度（站立面 +1～+2）


def _box_levels(box):
    """[(dy0, {離線位 -> 路線})]：每一層的月台門與軌道外側牆各屬哪一條線。

    回傳兩張表：psd（月台門離線位 -> 路線）與 wall（牆的那一側 ±1 -> 路線）。
    """
    lines = box.lines or ["?"]
    a = lines[0]
    b = lines[1] if len(lines) > 1 else a
    if box.kind == "island":
        return [(0, {PLAT_HALF: a, -PLAT_HALF: a}, {1: a, -1: a})]
    if box.kind == "side":
        return [(0, {PLAT_HALF - 1: a, -(PLAT_HALF - 1): a}, {})]
    out = []
    for dy0 in (0, -SK.LEVEL_H):
        if box.kind == "stacked_side":
            s = box.side                          # 月台那一側；軌道在 −s
            out.append((dy0, {box.lay["psd"][0]: a}, {-s: a}))
        else:                                     # 共用島式：primary 的股道在 −side
            sd = box.side
            out.append((dy0, {-sd * PLAT_HALF: a, sd * PLAT_HALF: b}, {-sd: a, sd: b}))
    return out


def line_bands(w, box, colours):
    """月台門的門楣與軌道外側牆的色帶。回傳放了幾格。"""
    samples, ys, lo, hi = box.samples, box.ys, box.lo, box.hi
    hdy = PSD_HEADER_DY.get(box.kind, 5)
    # 斜的線形上，某個取樣點外牆那一格可能是另一個取樣點的站內淨空：
    # 色帶只砌在「任何取樣點都不在站內」的格子上，免得凸進軌道淨空
    inner = set()
    for i in range(lo, hi + 1):
        for o in range(-(BOX_HALF - 2), BOX_HALF - 1):
            inner.add(box.cell(i, o))
    n = 0
    for dy0, psd, wall in _box_levels(box):
        for i in range(lo + 1, hi):
            y = int(ys[i]) + dy0
            for off, ref in psd.items():
                x, z = box.cell(i, off)
                w.set(x, y + hdy, z, band_block(ref, colours))
                n += 1
            for sd, ref in wall.items():
                x, z = box.cell(i, sd * (BOX_HALF - 1))
                if (x, z) in inner:
                    continue
                for dy in WALL_BAND_DY:
                    w.set(x, y + dy, z, band_block(ref, colours))
                    n += 1
    return n


# ---------- 穿堂指引 ----------

GATE_ALONG = 14          # 閘門在 lo + 14 m（build_line._station_island / _side_concourse）
MAP_ALONG = 10           # 路線圖／售票機：非付費區，出入口的洞（lo+5..9、側牆）與閘門之間
GATE_SIGN_OFF = 4        # 閘門列上立牌的機箱：離中線 ±4（中線那一排是橋墩會穿過的地方）


def concourse_kind(box, grounds):
    """穿堂的型態（alignment.station_kind 那一套）：地下與疊式站都是 "tunnel"。"""
    if box.kind != "side":
        return "tunnel"
    mid = (box.lo + box.hi) // 2
    g = int(grounds[mid]) if grounds is not None else 0
    return station_kind(int(box.ys[mid]), g)


def _pier_cells(box, grounds):
    """橋下穿堂裡的橋墩格（build_line._side_concourse 補回去的那些 3x3）。"""
    out = set()
    for i in range(box.lo, box.hi + 1):
        if abs((i * STEP) % PIER_EVERY) >= STEP / 2:
            continue
        y = int(box.ys[i])
        g = int(grounds[i]) if grounds is not None else 0
        if y - 2 <= g:
            continue
        x, z = box.samples[i][:2]
        cx, cz = round(x), round(z)
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                out.add((cx + dx, cz + dz))
    return out


def _terminals(berths, ref):
    """這條線在這座站體所有方向的終點（先 +u 再 −u，去重）。"""
    out = []
    for b in sorted((b for b in berths if b.line == ref), key=lambda b: -b.d):
        for dr in b.dests:
            for t in (dr.terminals or [dr.next]):
                if t not in out:
                    out.append(t)
    return out


def gate_lines(ref, berths, net, colours):
    """閘門上那面牌：(正面朝非付費區, 背面朝付費區)。"""
    zh, en = NW.LINE_NAMES.get(ref, (ref, ref))
    terms = _terminals(berths, ref)
    st = next((b.station for b in berths if b.line == ref), None)
    front = [
        styled(["往月台 Platforms", "往月台"], None),
        styled([zh + " " + ref, zh] if zh != ref else [ref], line_ink(ref, colours)),
        fit(_each(_zh_joined(terms), ["往 ", ""])) if terms else "",
        fit(_en_terms_or_line(ref, [_en(net, ref, t) for t in terms])),
    ]
    codes = []
    for b in berths:
        if b.station.code not in codes:
            codes.append(b.station.code)
    back = [
        styled(["往出口 To Exits", "往出口 Exits", "往出口"], None),
        st.name if st is not None else "",
        fit(en_forms(st.en)) if st is not None else "",
        fit(["/".join(codes)] + codes[:1]),
    ]
    return front, back


def _en_terms_or_line(ref, en_terms):
    """英文那一行：放得下就寫各終點（To Dingpu/Nangang…），放不下改寫英文路線名。
    截短的終點（「Nangang Exh. Ct…」）不如一個完整的路線名。"""
    full = [f for f in _joined_forms(en_terms) if "…" not in f] if en_terms else []
    line_en = NW.LINE_NAMES.get(ref, (ref, ref))[1]
    return (["To " + f for f in full] + full
            + [line_en, line_en.replace(" Line", ""), line_en.split("-")[0],
               " ".join(line_en.split(" ")[1:])])       # Taoyuan Airport MRT -> Airport MRT


def map_lines():
    """路線圖／售票機：點了打開資料包的路線圖對話框（mrt:network）。"""
    return [styled(["路線圖 售票機", "路線圖"], None), "Route Map",
            "& Tickets", fit(["▶ 右鍵開啟 Open", "▶ 右鍵開啟"])]


SIGHT_INK = "#6B4A00"          # 景點牌第一行的字色（深金，跟說明牌同一色）
SIGHTS_PER_STATION = 2         # 穿堂裡最多立幾面景點牌（售票機旁邊另外兩座機台）


# 景點英文名的慣用縮寫（放不下原名時先試這些）
_SIGHT_SHORT = {"Chiang Kai-shek Memorial Hall": ["CKS Memorial Hall"],
                "Sun Yat-sen Memorial Hall": ["SYS Memorial Hall"],
                "National Taiwan Museum": ["Natl. Taiwan Museum", "Taiwan Museum"],
                "Presidential Office Building": ["Presidential Office", "Presidential Ofc.",
                                                 "President's Office"],
                "Shin Kong Life Tower": ["Shin Kong Tower"]}


def sight_en_forms(name):
    """景點英文名由長到短：原名、去掉括號、慣用縮寫、從中間拿掉字（保留頭尾），
    最後才退回站名那一套（從尾巴砍）。「Shin Kong Life Tower」要變「Shin Kong Tower」，
    不是「Shin Kong Life」。"""
    base = name.split(" (")[0].strip()
    out = [name, base]
    short = _SIGHT_SHORT.get(base, [])
    out += short
    if short:
        return out + en_forms(short[-1])     # 有慣用縮寫就不要再從中間拿掉字（National Museum 會誤導）
    words = base.split(" ")
    while len(words) > 2:
        words = words[:-2] + words[-1:]
        out.append(" ".join(words))
    return out + en_forms(base)


def sight_lines(e):
    """穿堂裡的景點牌：點了傳送到景點的觀景點（資料包的 sight/<id>）。
    e 是 attractions.datapack_entries() 的一筆。第一行不以「出口」開頭。"""
    st = e.get("station")
    far = ""
    if st:
        far = fit(["出站約 %d m" % (int(round(st[2] / 10.0)) * 10), "%d m" % st[2]])
    return [styled(["★ " + e["name_zh"], e["name_zh"]], SIGHT_INK),
            fit(sight_en_forms(e["name_en"])), far, fit(["▶ 右鍵前往 Go", "▶ 右鍵前往"])]


def sight_command(e):
    return "function %s:%s" % (DATAPACK_NS, sight_fn(e["id"]))


def _gate_machines(box, kind):
    """閘門第一排（面向非付費區）確定是機箱的格子：{離線位: (x, 機箱 y, z)}。

    斜的線形上相鄰取樣點的格子會重疊，某個離線位算出來那一格最後可能被別的
    取樣點鋪成通道 —— 把 build_line._gates 在一個 DictSink 裡重跑一次，
    只挑真的是機箱、上面是空氣的格子。
    """
    per_m = max(1, int(round(1.0 / STEP)))
    s0 = box.lo + GATE_ALONG * per_m
    if not (box.lo <= s0 <= box.hi):
        return {}, s0
    dy = LEVEL_DY[kind]
    mini = DictSink()
    BL._gates(mini, box.samples, box.ys, s0, per_m, floor_dy=dy - 1)
    y_m = int(box.ys[s0]) + dy                    # 機箱那一格 = 站立面
    out = {}
    for o in range(-(BOX_HALF - 2), BOX_HALF - 1):
        x, z = box.cell(s0, o)
        if mini.get(x, y_m, z) == BL.GATE and mini.get(x, y_m + 1, z) == BL.AIR:
            out[o] = (x, y_m, z)
    return out, s0


class _Guarded:
    """跳過被別的結構占走的格子的 BlockSink（blocked 同 network.plan_berths 的）。

    台北車站地下街往淡水信義線穿堂的連絡梯井從板南線站體中間穿過去，而且是在
    車站之後蓋的：立在那裡的牌子只剩一個沒有方塊的方塊實體。"""

    def __init__(self, w, blocked):
        self.w, self.blocked = w, blocked

    def set(self, x, y, z, block):
        if not self.blocked(x, y, z):
            self.w.set(x, y, z, block)

    def sign(self, x, y, z, *args, **kw):
        if not self.blocked(x, y, z):
            self.w.sign(x, y, z, *args, **kw)


def concourse_signs(w, box, berths, net, colours, grounds=None, blocked=None, sights=()):
    """閘門的雙面牌、路線圖售票機、附近景點、側式站的月台樓梯口。回傳立了幾面。

    sights：這一站走得到的觀光景點（attractions.datapack_entries() 的幾筆，近的在前）。
    售票機旁邊的另外兩個機台位置各立一面，點了傳送到景點前面。"""
    if blocked is not None:
        w = _Guarded(w, blocked)
    per_m = max(1, int(round(1.0 / STEP)))
    kind = concourse_kind(box, grounds)
    lines = [ref for ref in box.lines if any(b.line == ref for b in berths)] or box.lines
    if not lines:
        return 0
    samples, ys, lo, hi = box.samples, box.ys, box.lo, box.hi
    n = 0
    # ---- 閘門：每條線一面雙面牌，立在閘門機箱上（人眼高度）----
    machines, s0 = _gate_machines(box, kind)
    ux, uz = samples[min(max(s0, lo), hi)][2:4]
    if len(lines) == 1:
        spots = [(GATE_SIGN_OFF, lines[0]), (-GATE_SIGN_OFF, lines[0])]
    else:                                  # 共用站體：每條線立在自己那座月台那一側
        sd = box.side if box.kind == "stacked_shared" else 1
        spots = [(-sd * GATE_SIGN_OFF, lines[0]), (sd * GATE_SIGN_OFF, lines[1])]
    for off, ref in spots:
        cell = None
        for o in (off, off + (1 if off > 0 else -1), off - (1 if off > 0 else -1)):
            if o in machines:
                cell = machines[o]
                break
        if cell is None:
            continue
        x, y, z = cell
        front, back = gate_lines(ref, berths, net, colours)
        w.sign(x, y + 1, z, front, facing=(-ux, -uz), back=back, **SIGN_STYLE)
        n += 1
    # ---- 路線圖／售票機：非付費區，一座機台（閘門機箱同款）上立一面牌 ----
    si = lo + MAP_ALONG * per_m
    if lo < si < hi:
        piers = _pier_cells(box, grounds) if kind == "under" else set()
        free = [off for off in (0, GATE_SIGN_OFF, -GATE_SIGN_OFF) if box.cell(si, off) not in piers]
        ys_ = int(ys[si]) + LEVEL_DY[kind]
        mx, mz = samples[si][2:4]
        if free:
            x, z = box.cell(si, free[0])
            w.set(x, ys_, z, BL.GATE)
            w.sign(x, ys_ + 1, z, map_lines(), facing=(-mx, -mz),
                   dialog="%s:%s" % (DATAPACK_NS, NW.MENU_DIALOG), **SIGN_STYLE)
            n += 1
            # 附近景點：售票機旁邊剩下的機台位置
            for off, e in zip(free[1:], list(sights)[:SIGHTS_PER_STATION]):
                x, z = box.cell(si, off)
                w.set(x, ys_, z, BL.GATE)
                w.sign(x, ys_ + 1, z, sight_lines(e), facing=(-mx, -mz),
                       command=sight_command(e), **SIGN_STYLE)
                n += 1
    # ---- 側式站：兩座月台各往一個方向，樓梯口各立一面 ----
    if box.kind == "side":
        n += _side_stair_signs(w, box, berths, net, colours, kind)
    # ---- 疊式站：上層月台往下層、下層月台往上層的樓梯口 ----
    if box.kind.startswith("stacked"):
        n += _level_stair_signs(w, box, berths, net, colours)
    return n


def _side_stair_signs(w, box, berths, net, colours, kind):
    """側式站穿堂的兩座月台樓梯（build_line._side_concourse：hi 端、|off| 8..9）。

    牌子立在樓梯口前 2 m、離線位 ±7（樓梯走 8..9，±7 還在穿堂的走道上，
    也離側牆 ±11 的轉乘通道洞口遠遠的），面向閘門那一頭走過來的人。
    """
    per_m = max(1, int(round(1.0 / STEP)))
    dy = LEVEL_DY[kind]
    run = 2 * abs(dy - 2)
    s0 = box.hi - (run + 1) * per_m
    si = s0 - 2 * per_m
    if not (box.lo + (GATE_ALONG + 3) * per_m < si < box.hi):
        return 0
    ux, uz = box.samples[si][2:4]
    y = int(box.ys[si]) + dy
    n = 0
    for b in berths:
        if b.d not in (1, -1):
            continue
        x, z = box.cell(si, b.d * 7)
        w.sign(x, y, z, platform_lines(b, net, colours, kind), facing=(-ux, -uz), **SIGN_STYLE)
        n += 1
    return n


def platform_lines(berth, net, colours, kind=None):
    """往某一座側式月台的牌：往哪裡、下一站；終點站的到站側寫「下車月台」。"""
    ref = berth.line
    col = line_ink(ref, colours)
    updown = "↑" if kind == "under" else "↓"
    if not berth.dests:
        return [styled([updown + " 下車月台", "下車月台"], col), "Arrival Platform",
                "本站終點", "Terminus"]
    terms = []
    for dr in berth.dests:
        for t in (dr.terminals or [dr.next]):
            if t not in terms:
                terms.append(t)
    nexts = [dr.next for dr in berth.dests]
    return [styled(_each(_zh_joined(terms), [updown + " 往 ", "往 ", ""]), col),
            fit(_pref(_joined_forms([_en(net, ref, t) for t in terms]), "To ")),
            fit(_each(_zh_joined(nexts), ["下一站 ", "下一站", ""])),
            fit(_pref(_joined_forms([_en(net, ref, t) for t in nexts]), "Next: "))]


def _level_stair_signs(w, box, berths, net, colours):
    """疊式站：上層月台在往下層的樓梯洞盡頭立「往下層月台」、下層月台在樓梯腳
    立「往上層月台・出口」，都面向從月台另一頭走過來的人（+u）。

    位置跟樓梯（build_line._level_stair）在 DictSink 裡重跑一次再挑：上層那面要
    落在洞的盡頭之後、腳下還有月台的格子；下層那面在最後一階再往前兩公尺。
    """
    per_m = max(1, int(round(1.0 / STEP)))
    l0, l1 = box.lay["lstair"]
    off = (l0 + l1) // 2
    s_top = box.lo + 4 * per_m
    mini = DictSink()
    steps = BL._level_stair(mini, box.samples, box.ys, s_top, per_m, SK.LEVEL_H, l0, l1)
    if not steps:
        return 0
    n = 0
    lower = [b for b in berths if b.dy0 < 0]
    upper = [b for b in berths if b.dy0 == 0]
    # 上層：從梯頂往 +u 找第一個「月台面還在、那一格沒被樓梯動過」的取樣點，再退 1 m
    top = None
    for si in range(s_top, box.hi - 4 * per_m):
        x, z = box.cell(si, off)
        y = int(box.ys[si])
        touched = any((x, yy, z) in mini.blocks for yy in range(y - SK.LEVEL_H, y + 6))
        if si > steps[0][0] and not touched:
            top = si + per_m
            break
    if top is not None and top < box.hi:
        x, z = box.cell(top, off)
        ux, uz = box.samples[top][2:4]
        w.sign(x, int(box.ys[top]) + 2, z, level_lines(lower, net, colours, down=True),
               facing=(ux, uz), **SIGN_STYLE)
        n += 1
    bot = steps[-1][0] + 2 * per_m
    if bot < box.hi:
        x, z = box.cell(bot, off)
        ux, uz = box.samples[bot][2:4]
        w.sign(x, int(box.ys[bot]) - SK.LEVEL_H + 2, z,
               level_lines(upper, net, colours, down=False), facing=(ux, uz), **SIGN_STYLE)
        n += 1
    return n


def level_lines(berths, net, colours, down):
    """疊式站樓梯口的牌：往哪一層、那一層的列車往哪裡（每條線一行、上路線色）。"""
    head = styled(["↓ 下層月台", "下層月台"] if down else
                  ["↑ 上層月台・出口", "↑ 上層月台", "上層月台"], None)
    sub = "Lower Level" if down else fit(["Upper Level/Exits", "Exits/Upper Level", "Upper Level"])
    rows = []
    for b in sorted(berths, key=lambda b: b.line):
        terms = []
        for dr in b.dests:
            for t in (dr.terminals or [dr.next]):
                if t not in terms:
                    terms.append(t)
        zh = NW.LINE_NAMES.get(b.line, (b.line, b.line))[0]
        if terms:
            # 路線色已經標出是哪條線：放不下時先拿掉路線名，不要先把終點縮成「迴龍等」
            cands = _each(_zh_joined(terms), [zh + " 往 ", "往 ", ""])
        else:
            cands = [zh + " 本站終點", "本站終點"]
        rows.append(styled(cands, line_ink(b.line, colours)))
    if len(rows) == 1:                          # 側式疊式只有一條線：第四行寫英文
        b = berths[0]
        terms = [t for dr in b.dests for t in (dr.terminals or [dr.next])]
        rows.append(fit(_pref(_joined_forms([_en(net, b.line, t) for t in terms]), "To "))
                    if terms else "Terminus")
    return [head, sub] + rows[:2]


# ---------- 出口牌 ----------

def exit_sign_lines(lines, colour):
    """出口牌四行（build_exits.sign_lines）的第一行上路線色。純文字不變：
    verify_exits 靠第一行的「出口」與第二行的站名認出入口亭。"""
    out = list(lines)
    if out and colour:
        out[0] = dict(text=str(out[0]), color=ink(colour), bold=True)
    return out


def transfer_sign_lines(lines, colour):
    """轉乘井門邊的牌：第二行（往 X 線）上 X 線的顏色，純文字不變。"""
    out = list(lines)
    if len(out) > 1 and colour:
        out[1] = dict(text=str(out[1]), color=ink(colour), bold=True)
    return out


# ---------- 一座站體 ----------

def station_signage(w, berths, net, colours, grounds=None, blocked=None, sights=()):
    """一座站體的全部告示牌與色帶（berths 是這座站體的所有 Berth）。

    要在 build_line.build_station 之後呼叫：牌子取代月台門那一格玻璃、色帶取代
    外牆與門楣那一排。回傳 dict(ride, concourse, band) 各放了多少。

    blocked 是 network.plan_berths 用的同一個「這一格被別的結構占走了」：搭車告示牌
    的位置已經避開了，穿堂的牌子也照它避開。sights 是這一站走得到的觀光景點。
    """
    berths = list(berths)
    if not berths:
        return dict(ride=0, concourse=0, band=0)
    box = berths[0].box
    band = line_bands(w, box, colours)
    ride = ride_signs(w, berths, net, colours)
    conc = concourse_signs(w, box, berths, net, colours, grounds, blocked, sights)
    return dict(ride=ride, concourse=conc, band=band)
