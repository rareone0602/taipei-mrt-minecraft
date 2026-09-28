#!/usr/bin/env python3
"""Station signs and line colors: ride signs, line color bands, concourse wayfinding, exit sign style.

Which station comes next, which platform screen door cell a sign stands in and
where the player stands are all computed by domain/network.py (plan_berths),
and the datapack's teleport destinations come from the same plan. This module
only decides what a sign says, in which color and on which block, and places it
accordingly.

The unit is one station box. The CLI calls station_signage once per region after
building the stations: when a station box spans two regions, each region places
the signs once, and the World discards blocks outside its range.

1. Ride signs (ride_signs): one per network.Slot, placed in the platform screen
   door row in place of one glass cell (where the station name sign used to
   stand). Each says where the train goes, the next station, this station and
   "click to ride"; the click command is `function <namespace>:ride/<this>_<next>`.
   On the arrival side of a terminus the sign says "this is the terminus, use the
   opposite platform", and clicking it moves the player there (turn).
2. Line color bands (line_bands): two rows of line color on the wall outside the
   track, at eye level on the platform, visible through the platform screen
   doors; the top row of the platform screen doors becomes a line-colored lintel.
   Stacked stations get bands on both levels, and in a shared station box each
   side follows the line on that side.
3. Concourse wayfinding (concourse_signs): a double-sided sign on a fare gate
   cabinet. The front faces the unpaid area and says "to platforms" and the
   line's terminals; the back faces the paid area and says "to exits". The unpaid
   area gets a "route map / ticket machine" that opens the route map dialog when
   clicked. In a side-platform station each of the two platform stairs in the
   concourse gets a sign naming its terminal (the two platforms serve opposite
   directions; island stations don't need this). In a stacked station the stairs
   from the upper platform down and from the lower platform up get one sign each.
4. Exit sign style (exit_sign_lines, SIGN_STYLE): the first line (the exit
   number) takes the line color, and its plain text does not change by a single
   character: tools/verify_exits.py recognizes exit kiosks by a first line
   starting with `出口` and a second line holding the station name. **No other
   sign placed here may have a first line starting with `出口`.**

Every sign is pale wood (pale_oak) with glow ink. Taipei Metro wayfinding is
white, and station boxes are dark; glowing black text on a pale board gets an
off-white outline and stays readable in the dark. Line colors too light to read
on a pale board (the Circular Line yellow, the light rail pastels) are darkened
first (ink).
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

# ---------- Sign style ----------

SIGN_WOOD = "pale_oak"
SIGN_STYLE = dict(wood=SIGN_WOOD, kind="standing", glow=True, color="black")
SIGN_W = 90            # A standing or wall sign line is at most 90 px wide; the game draws nothing beyond that.
BG_LUM = 0.70          # Relative luminance of a pale_oak board (about #E3D9D3).
MIN_CONTRAST = 3.0     # Minimum contrast between line-colored text and the board (the WCAG large-text threshold).

# Character widths in the default Minecraft font (including 1 px of letter
# spacing). Unlisted ASCII is 6. Non-ASCII (Chinese, arrows, full-width symbols)
# comes from unifont: a 16 px full-width glyph scaled to half plus spacing is
# about 9. Overestimate rather than underestimate: an underestimate makes the
# game cut the text off, an overestimate only switches to an abbreviation earlier.
_ASCII_W = {" ": 4, "!": 2, "'": 3, ",": 2, ".": 2, ":": 2, ";": 2, "|": 2,
            "i": 2, "l": 3, "`": 3, "I": 4, "t": 4, "[": 4, "]": 4, '"': 5,
            "(": 5, ")": 5, "{": 5, "}": 5, "*": 5, "f": 5, "k": 5, "<": 5,
            ">": 5, "@": 7, "~": 7}
WIDE_W = 9


def text_width(s, bold=False):
    """Width in pixels of one line of text on a sign. Bold adds 1 px per character."""
    w = 0
    for ch in str(s):
        w += _ASCII_W.get(ch, 6) if ord(ch) < 128 else WIDE_W
        if bold:
            w += 1
    return w


def line_width(item):
    """Width of one sign line (a plain string or a dict)."""
    if isinstance(item, dict):
        return text_width(item.get("text", ""), bool(item.get("bold")))
    return text_width(item)


def fit(cands, bold=False, width=SIGN_W):
    """The first candidate that fits; if none fits, truncate the last one and append an ellipsis."""
    cands = [c for c in cands if c is not None]
    for c in cands:
        if text_width(c, bold) <= width:
            return c
    s = cands[-1] if cands else ""
    while s and text_width(s + "…", bold) > width:
        s = s[:-1]
    return s.rstrip() + "…"


def styled(cands, color=None, width=SIGN_W):
    """A line-colored or emphasized line. The candidates are tried in order
    (earlier ones carry more information), each in bold first and then in
    regular weight; if none fits, the last one is truncated."""
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


# Abbreviations applied in order when an English station name is too long (the
# least damaging to recognition first). Only after these are words dropped from
# the end, one at a time. The station name itself is OSM's name:en; these are
# display abbreviations only.
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


def en_abbrevs(name):
    """The English station name followed by each _EN_SHORT abbreviation stage (no words dropped)."""
    out, s = [name], name
    for a, b in _EN_SHORT:
        if a in s:
            s = s.replace(a, b)
            out.append(s)
    return out


def en_forms(name):
    """English station name forms from longest to shortest (the first is the original name).

    The _EN_SHORT abbreviations are applied first. If the name is still too
    long, words are dropped from the end one at a time, but at least two words
    remain: cutting "Taipei Nangang Exhibition Center" down to "Nangang" would
    collide with Nangang station. For names with a slash (Taipei 101/World Trade
    Center), keeping only the part before the slash is the last resort.
    """
    out = en_abbrevs(name)
    s = out[-1]
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
    """Several English station names joined with a slash, from longest to
    shortest (all abbreviated to the same level together).

    Joined names never drop words: shortening "Tamsui Fisherman's Wharf/Kanding"
    to "Tamsui/Kanding" would point at Tamsui station. If nothing fits, only the
    first name is written, followed by "/…"."""
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
    """A form that shows only part of the list: "first/…" or "first等" (等 means "and others")."""
    return "…" in t or t.endswith("等")


def _pref(joined, prefix):
    """Candidate order: the full form with the prefix ("To ", "For ", "Next: "…),
    the full form without it, the "first/…" form with the prefix, and the
    "first/…" form without it."""
    full = [j for j in joined if not _is_cut(j)]
    cut = [j for j in joined if _is_cut(j)]
    return ([prefix + j for j in full] + full + [prefix + j for j in cut] + cut)


def _each(joined, prefixes):
    """Each form is tried with every prefix in turn (the last is usually an empty
    string), and partial forms get their turn only after every full form has
    been tried: "動物園/南港展覽館" (both terminals) is more useful than
    "往 動物園等" (the first one and others)."""
    full = [j for j in joined if not _is_cut(j)]
    cut = [j for j in joined if _is_cut(j)]
    return [p + j for j in full + cut for p in prefixes]


def _dir_cands(joined, prefix, arrow):
    """Candidates for the direction line: each form is tried as "arrow + 往/To +
    terminal", "往/To + terminal", "arrow + terminal" and "terminal", in turn."""
    out = []
    for j in joined:
        out += [_with_arrow(prefix + j, arrow), prefix + j, _with_arrow(j, arrow), j]
    return out


def _zh_joined(names):
    """Several Chinese station names joined with a slash; the last resort when
    that does not fit is "first + 等" (the first one and others)."""
    out = ["/".join(names)]
    if len(names) > 1:
        out.append(names[0] + "等")
    return out


# ---------- Line colors ----------

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
    """Line color -> a text color readable on a pale wood board ("#RRGGBB").

    Colors dark enough (the Bannan Line blue, the Songshan-Xindian Line green,
    the Wenhu Line brown) are kept as they are; lighter ones keep their hue and
    are darkened until the contrast reaches MIN_CONTRAST. Pastels (the Danhai
    LRT, and the pale purple OSM gives the Airport MRT) first have their
    saturation pulled into 0.4 to 0.6 before darkening; otherwise they darken
    into a flat gray (or into the same pure red as the Tamsui-Xinyi Line).
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


# Blocks for the color bands: whichever concrete or terracotta is closest in
# color (average texture color). yellow_concrete is not a candidate: it is the
# platform-edge warning strip, and verify_exits and verify_rides both recognize
# a platform by "the cell above yellow concrete". An extra strip of yellow
# concrete on a wall would be taken for a platform.
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

# The closest color occasionally loses a line's identity, so these lines are
# assigned by hand (reasons alongside). The rest are chosen by color difference:
# the Bannan Line gets light_blue_concrete, the Songshan-Xindian Line
# green_concrete, the Wenhu Line orange_terracotta, the Circular Line
# yellow_terracotta (yellow concrete is not a candidate), the Sanying Line
# cyan_concrete, and the Ankeng and Danhai LRT white_terracotta.
BAND_OVERRIDE = {
    "R": "red_concrete",         # OSM #FF0000; CIE76 finds bright orange closer than dark red, and the Tamsui-Xinyi Line cannot be orange.
    "O": "orange_concrete",      # OSM orange; the closest is yellow terracotta, the same as the Circular Line.
    "A": "purple_concrete",      # OSM gives the pale map purple #D4CDE7; the closest is white concrete.
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
    """Color -> the closest concrete or terracotta block (CIE76 color difference)."""
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


# ---------- Ride signs ----------

RIDE_HINT_ZH = "▶ 右鍵點擊搭車"
RIDE_HINT_EN = ("▶ Right-click to ride", "▶ Click to ride")
TURN_HINT_ZH = "▶ 右鍵點擊換月台"
TURN_HINT_EN = ("▶ Click to cross", "▶ Cross over")


def ride_command(code_from, code_to):
    return "function %s:%s" % (DATAPACK_NS, NW.ride_fn(code_from, code_to))


def turn_command(code, d):
    return "function %s:%s" % (DATAPACK_NS, NW.turn_fn(code, d))


def travel_arrow(berth):
    """Which way the train leaves, relative to the person reading the sign: "←" or "→".

    A person standing on the berth and facing the platform screen doors has
    inward·u on their right (see face in network.plan_berths), and the train runs
    along d·u, so d·inward > 0 means to the right. On an island platform trains
    always run from right to left (they keep right, and the person stands between
    the two tracks); on a side platform the person stands outside the track, so
    it is the reverse, from left to right.
    """
    return "→" if berth.d * berth.inward > 0 else "←"


def _with_arrow(text, arrow):
    return (arrow + " " + text) if arrow == "←" else (text + " " + arrow)


def _en(net, ref, name):
    st = net.get((ref, name))
    return st.en if st is not None and st.en else name


def _next_en(net, ref, name):
    """The English forms of the next station, and those that fit after "Next: "."""
    forms = en_forms(_en(net, ref, name))
    return forms, [f for f in forms if text_width("Next: " + f) <= SIGN_W]


def _has_en_twin(berth, slot):
    """Whether the berth has an English sign for the same destination as slot.

    Signs alternate Chinese and English per destination, but three signs cannot
    pair up two destinations: at the branch stations (Qizhang, Daqiaotou, Beitou,
    Binhai Shalun) the second destination gets a Chinese sign only."""
    key = slot.dest.next if slot.dest is not None else None
    return any(s.lang == "en" and (s.dest.next if s.dest is not None else None) == key
               for s in berth.slots)


def ride_lines(berth, slot, net, colour, opposite=None):
    """The four lines (dicts or strings) and the click command of one ride sign: (lines, command).

    opposite is the Berth on the other side of the same line in the same station
    box (the arrival side of a terminus says where the opposite side goes). A
    Chinese sign without an English twin on the same berth (_has_en_twin) gives
    up its least needed line to English.
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
            if not _has_en_twin(berth, slot):
                # The next station in English replaces this station's name,
                # which every other sign in the station shows.
                nxt_forms, nx = _next_en(net, ref, dr.next)
                lines[2] = "Next: " + nx[0] if nx else fit(nxt_forms)
        else:
            en_terms = [_en(net, ref, t) for t in terms]
            head = styled(_dir_cands(_joined_forms(en_terms), "To ", arrow), col)
            nxt_forms, nx = _next_en(net, ref, dr.next)
            if nx:
                lines = [head, "Next: " + nx[0],
                         fit([st.code + " " + f for f in en_forms(st.en)] + en_forms(st.en)),
                         fit(list(RIDE_HINT_EN))]
            else:
                # English station names often don't fit on one line after
                # "Next: " (Zhongxiao Fuxing, Shandao Temple...). The next station
                # then takes two lines and this station's name gives way: the
                # Chinese sign beside it shows this station's code, but only this
                # sign gives the next station in English.
                lines = [head, "Next station", fit(nxt_forms), fit(list(RIDE_HINT_EN))]
        return lines, ride_command(st.code, nxt_code)
    # Arrival side of a terminus: there is no next station, and a click moves the
    # player to the opposite platform.
    other = [t for dr in (opposite.dests if opposite is not None else ())
             for t in (dr.terminals or [dr.next])]
    other = list(dict.fromkeys(other))
    can_turn = opposite is not None and bool(opposite.slots) and bool(opposite.dests)
    if slot.lang == "zh" and not _has_en_twin(berth, slot):
        # Without an English twin, the instruction goes in both languages and the
        # destination line gives way.
        lines = [styled(["本站終點 Terminus", "本站終點"], col),
                 "請至對面月台" if can_turn else "本站無列車",
                 "Use other side" if can_turn else "No service",
                 TURN_HINT_ZH if can_turn else ""]
    elif slot.lang == "zh":
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


# The cells above a sign (relative to it) that still belong to the platform
# screen doors: in island and stacked stations the doors span rail top +2..+5
# (+5 is the lintel) and the sign is at +2; in side-platform stations they span
# +1..+4 (+4 is the lintel) and the sign is at +2. The cell below is checked
# separately (_side_below_is_door).
PSD_ABOVE = {"side": (1,)}
PSD_ABOVE_DEFAULT = (1, 2)


def _side_below_is_door(box, cell):
    """Whether the cell below a side-platform sign (rail top +1) ends up as a door opening.

    Two things write that cell: the platform screen doors (±5, +1..+4, where door
    openings are air) and the platform (6..10, where +1 is the warning strip or
    the platform surface). On an oblique alignment both can round to the same
    cell, so this replays the order of the second pass of build_line._station_side
    (at each sample, doors first and then platform) and checks which comes last.
    Only a door opening needs glass; if it is platform surface, the sign already
    has support, and glass would dig a cell out of the warning strip (this
    happened at Liuzhangli).
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
    """Place every ride sign of these Berths. Returns the number placed.

    When network picks berths it only avoids door openings ("along % 7 < 2"
    along the line), but on an oblique or curved alignment two samples 1 m apart
    can round to the same cell. The door-opening sample is built later, so the
    sign's cell (and the two above it) becomes a door opening. The Tamsui-Xinyi
    Line at Taipei Main Station and Chiang Kai-shek Memorial Hall and the Bannan
    Line at Banqiao all did this: the sign stood in a door opening with nothing
    above it (and on side platforms nothing below it either). So placing a sign
    also restores that column of platform screen doors to glass: a sign always
    sits at the bottom of a glass door panel. (Only the platform screen doors
    write the cells above a sign, so glass there is always right; the cell below
    a side-platform sign may be the platform's warning strip, so it gets glass
    only once it is confirmed to be a door opening.)
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


# ---------- Line color bands ----------

PSD_HEADER_DY = {"island": 5, "stacked_side": 5, "stacked_shared": 5, "side": 4}
WALL_BAND_DY = (3, 4)          # Eye level on the platform (standing surface +1 to +2).


def _box_levels(box):
    """[(dy0, psd, wall)]: which line the platform screen doors and the outer
    track wall belong to on each level.

    Two maps per level: psd (platform screen door offset -> line) and wall (the
    wall's side ±1 -> line).
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
            s = box.side                          # The platform side; the track is on −s.
            out.append((dy0, {box.lay["psd"][0]: a}, {-s: a}))
        else:                                     # Shared island: the primary line's track is on −side.
            sd = box.side
            out.append((dy0, {-sd * PLAT_HALF: a, sd * PLAT_HALF: b}, {-sd: a, sd: b}))
    return out


def line_bands(w, box, colours):
    """Line-colored lintels on the platform screen doors and color bands on the
    outer track walls. Returns the number of cells placed."""
    samples, ys, lo, hi = box.samples, box.ys, box.lo, box.hi
    hdy = PSD_HEADER_DY.get(box.kind, 5)
    # On an oblique alignment the outer wall cell of one sample may lie inside the
    # station clearance of another. Bands go only on cells that are inside the
    # station for no sample, so they never stick out into the track clearance.
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


# ---------- Concourse wayfinding ----------

GATE_ALONG = 14          # The fare gates are at lo + 14 m (build_line._station_island / _side_concourse).
MAP_ALONG = 10           # Route map / ticket machine: in the unpaid area, between the exit openings (lo+5..9, side walls) and the fare gates.
GATE_SIGN_OFF = 4        # The gate cabinets that carry a sign: ±4 from the center line (the center row is where piers pass through).


def concourse_kind(box, grounds):
    """The concourse type (as in alignment.station_kind): underground and stacked stations are both "tunnel"."""
    if box.kind != "side":
        return "tunnel"
    mid = (box.lo + box.hi) // 2
    g = int(grounds[mid]) if grounds is not None else 0
    return station_kind(int(box.ys[mid]), g)


def _pier_cells(box, grounds):
    """Pier cells in an under-viaduct concourse (the 3x3 blocks that build_line._side_concourse restores)."""
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
    """Every terminal of this line in this station box, in all directions (+u first, then −u, without duplicates)."""
    out = []
    for b in sorted((b for b in berths if b.line == ref), key=lambda b: -b.d):
        for dr in b.dests:
            for t in (dr.terminals or [dr.next]):
                if t not in out:
                    out.append(t)
    return out


def gate_lines(ref, berths, net, colours):
    """The sign on the fare gates: (front facing the unpaid area, back facing the paid area)."""
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
    """The English line: the terminals if they fit (To Dingpu/Nangang…), otherwise
    the English line name. A truncated terminal ("Nangang Exh. Ct…") is worse
    than a complete line name."""
    full = [f for f in _joined_forms(en_terms) if "…" not in f] if en_terms else []
    line_en = NW.LINE_NAMES.get(ref, (ref, ref))[1]
    return (["To " + f for f in full] + full
            + [line_en, line_en.replace(" Line", ""), line_en.split("-")[0],
               " ".join(line_en.split(" ")[1:])])       # Taoyuan Airport MRT -> Airport MRT


def map_lines():
    """Route map / ticket machine: a click opens the datapack's route map dialog (mrt:network)."""
    return [styled(["路線圖 售票機", "路線圖"], None), "Route Map",
            "& Tickets", fit(["▶ 右鍵開啟 Open", "▶ 右鍵開啟"])]


SIGHT_INK = "#6B4A00"          # Text color of an attraction sign's first line (dark gold, the same as the plaques).
SIGHTS_PER_STATION = 2         # The most attraction signs in one concourse (the two other machine positions beside the ticket machine).


# Conventional English abbreviations of attraction names (tried first when the
# original does not fit).
_SIGHT_SHORT = {"Chiang Kai-shek Memorial Hall": ["CKS Memorial Hall"],
                "Sun Yat-sen Memorial Hall": ["SYS Memorial Hall"],
                "National Taiwan Museum": ["Natl. Taiwan Museum", "Taiwan Museum"],
                "Presidential Office Building": ["Presidential Office", "Presidential Ofc.",
                                                 "President's Office"],
                "Shin Kong Life Tower": ["Shin Kong Tower"],
                "National Taiwan University": ["Natl. Taiwan University", "Natl. Taiwan Univ.",
                                               "NTU"]}


def sight_en_forms(name):
    """English attraction name forms from longest to shortest: the original, the
    name without its parentheses, conventional abbreviations, words removed from
    the middle (keeping the first and last), and finally the station name
    approach (cutting from the end). "Shin Kong Life Tower" should become
    "Shin Kong Tower", not "Shin Kong Life"."""
    base = name.split(" (")[0].strip()
    out = [name, base]
    short = _SIGHT_SHORT.get(base, [])
    out += short
    if short:
        return out + en_forms(short[-1])     # With a conventional abbreviation, remove no middle words ("National Museum" would mislead).
    words = base.split(" ")
    while len(words) > 2:
        words = words[:-2] + words[-1:]
        out.append(" ".join(words))
    return out + en_forms(base)


def sight_lines(e):
    """An attraction sign in the concourse: a click teleports to the attraction's
    viewpoint (the datapack's sight/<id>). e is one entry of
    attractions.datapack_entries(). The first line does not start with `出口`."""
    st = e.get("station")
    far = ""
    if st:
        far = fit(["出站約 %d m away" % (int(round(st[2] / 10.0)) * 10), "%d m" % st[2]])
    return [styled(["★ " + e["name_zh"], e["name_zh"]], SIGHT_INK),
            fit(sight_en_forms(e["name_en"])), far, fit(["▶ 右鍵前往 Go", "▶ 右鍵前往"])]


def sight_command(e):
    return "function %s:%s" % (DATAPACK_NS, sight_fn(e["id"]))


def _gate_machines(box, kind):
    """The cells of the first fare gate row (facing the unpaid area) that are
    certainly cabinets: {offset: (x, cabinet y, z)}.

    On an oblique alignment the cells of adjacent samples overlap, and the cell
    computed for an offset may end up paved as a passage by another sample. This
    replays build_line._gates in a DictSink and keeps only cells that really are
    cabinets with air above them.
    """
    per_m = max(1, int(round(1.0 / STEP)))
    s0 = box.lo + GATE_ALONG * per_m
    if not (box.lo <= s0 <= box.hi):
        return {}, s0
    dy = LEVEL_DY[kind]
    mini = DictSink()
    BL._gates(mini, box.samples, box.ys, s0, per_m, floor_dy=dy - 1)
    y_m = int(box.ys[s0]) + dy                    # The cabinet cell is at the standing surface.
    out = {}
    for o in range(-(BOX_HALF - 2), BOX_HALF - 1):
        x, z = box.cell(s0, o)
        if mini.get(x, y_m, z) == BL.GATE and mini.get(x, y_m + 1, z) == BL.AIR:
            out[o] = (x, y_m, z)
    return out, s0


class _Guarded:
    """A BlockSink that skips cells taken by other structures (blocked is the
    same test as in network.plan_berths).

    At Taipei Main Station the link stair shaft from the underground mall to the
    Tamsui-Xinyi Line concourse passes through the middle of the Bannan Line
    station box, and it is built after the stations: a sign placed there would
    be left as a block entity with no block."""

    def __init__(self, w, blocked):
        self.w, self.blocked = w, blocked

    def set(self, x, y, z, block):
        if not self.blocked(x, y, z):
            self.w.set(x, y, z, block)

    def sign(self, x, y, z, *args, **kw):
        if not self.blocked(x, y, z):
            self.w.sign(x, y, z, *args, **kw)


def concourse_signs(w, box, berths, net, colours, grounds=None, blocked=None, sights=()):
    """The double-sided signs on the fare gates, the route map ticket machine,
    nearby attractions and the platform stair signs of side-platform stations.
    Returns the number placed.

    sights: the attractions within walking distance of this station (a few
    entries of attractions.datapack_entries(), nearest first). One sign stands on
    each of the two other machine positions beside the ticket machine; a click
    teleports to the front of the attraction."""
    if blocked is not None:
        w = _Guarded(w, blocked)
    per_m = max(1, int(round(1.0 / STEP)))
    kind = concourse_kind(box, grounds)
    lines = [ref for ref in box.lines if any(b.line == ref for b in berths)] or box.lines
    if not lines:
        return 0
    samples, ys, lo, hi = box.samples, box.ys, box.lo, box.hi
    n = 0
    # ---- Fare gates: one double-sided sign per line, on a gate cabinet (at eye level) ----
    machines, s0 = _gate_machines(box, kind)
    ux, uz = samples[min(max(s0, lo), hi)][2:4]
    if len(lines) == 1:
        spots = [(GATE_SIGN_OFF, lines[0]), (-GATE_SIGN_OFF, lines[0])]
    else:                                  # Shared station box: each line on its own platform's side.
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
    # ---- Route map / ticket machine: in the unpaid area, a sign on a machine (the same as a gate cabinet) ----
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
            # Nearby attractions: the remaining machine positions beside the ticket machine.
            for off, e in zip(free[1:], list(sights)[:SIGHTS_PER_STATION]):
                x, z = box.cell(si, off)
                w.set(x, ys_, z, BL.GATE)
                w.sign(x, ys_ + 1, z, sight_lines(e), facing=(-mx, -mz),
                       command=sight_command(e), **SIGN_STYLE)
                n += 1
    # ---- Side-platform stations: each platform serves one direction; one sign at each stair ----
    if box.kind == "side":
        n += _side_stair_signs(w, box, berths, net, colours, kind)
    # ---- Stacked stations: the stairs from the upper platform down and from the lower platform up ----
    if box.kind.startswith("stacked"):
        n += _level_stair_signs(w, box, berths, net, colours)
    return n


def _side_stair_signs(w, box, berths, net, colours, kind):
    """The two platform stairs in a side-platform station's concourse
    (build_line._side_concourse: at the hi end, |offset| 8..9).

    The signs stand 2 m before the stairs at offset ±7 (the stairs use 8..9, so
    ±7 is still on the concourse walkway, well clear of the transfer passage
    openings in the side walls at ±11), facing people coming from the fare gates.
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
    """The sign for one side platform: where it goes and the next station; the
    arrival side of a terminus says "arrival platform"."""
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
    """Stacked stations: on the upper platform, a "to the lower platform" sign at
    the end of the stair opening; on the lower platform, a "to the upper platform
    and exits" sign at the foot of the stairs. Both face people coming from the
    far end of the platform (+u).

    The positions come from replaying the stairs (build_line._level_stair) in a
    DictSink: the upper sign must land past the end of the opening, on a cell that
    still has platform under it; the lower one stands two meters past the last
    step.
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
    # Upper level: from the top of the stairs toward +u, find the first sample
    # where the platform surface is intact and the stairs left the cell alone,
    # then add 1 m.
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


def _bilingual_rows(zh_line, zh_terms, en_terms):
    """Row candidates carrying the terminals in both languages, longest first.

    A shared stacked station has two rows and no room for an English fourth
    line, so each row tries Chinese and English terminals side by side. The line
    name goes first, then "往"; terminals are never shortened to "first等"."""
    zh_full = [z for z in _zh_joined(zh_terms) if not _is_cut(z)]
    en_full = [e for e in _joined_forms(en_terms) if not _is_cut(e)]
    return [p + z + " " + e for p in (zh_line + " 往 ", "往 ", "")
            for z in zh_full for e in en_full]


def level_lines(berths, net, colours, down):
    """The sign at a stacked station's stairs: which level, and where that
    level's trains go (one row per line, in the line color)."""
    head = styled(["↓ 下層月台", "下層月台"] if down else
                  ["↑ 上層月台・出口", "↑ 上層月台", "上層月台"], None)
    sub = "Lower Level" if down else fit(["Upper Level/Exits", "Exits/Upper Level",
                                          "Upper Level/Exit", "Upper Level"])
    rows = []
    for b in sorted(berths, key=lambda b: b.line):
        terms = []
        for dr in b.dests:
            for t in (dr.terminals or [dr.next]):
                if t not in terms:
                    terms.append(t)
        zh = NW.LINE_NAMES.get(b.line, (b.line, b.line))[0]
        if terms:
            # The line color already identifies the line: when space runs short,
            # drop the line name first rather than shortening the terminals to
            # "迴龍等" (Huilong and others).
            cands = _each(_zh_joined(terms), [zh + " 往 ", "往 ", ""])
            if len(berths) > 1:
                cands = _bilingual_rows(zh, terms, [_en(net, b.line, t) for t in terms]) + cands
        else:
            cands = [zh + " 本站終點", "本站終點"]
            if len(berths) > 1:
                cands = ["本站終點 Terminus"] + cands
        rows.append(styled(cands, line_ink(b.line, colours)))
    if len(rows) == 1:                          # A side stacked station has one line, so the fourth line is English.
        b = berths[0]
        terms = [t for dr in b.dests for t in (dr.terminals or [dr.next])]
        rows.append(fit(_pref(_joined_forms([_en(net, b.line, t) for t in terms]), "To "))
                    if terms else "Terminus")
    return [head, sub] + rows[:2]


# ---------- Exit signs ----------

def exit_sign_lines(lines, colour):
    """Give the first of an exit sign's four lines (build_exits.sign_lines) the
    line color. The plain text does not change: verify_exits recognizes exit
    kiosks by `出口` on the first line and the station name on the second."""
    out = list(lines)
    if out and colour:
        out[0] = dict(text=str(out[0]), color=ink(colour), bold=True)
    return out


def transfer_sign_lines(lines, colour):
    """The sign beside a transfer shaft door: the second line (往 X 線, "to line
    X") takes line X's color; the plain text does not change."""
    out = list(lines)
    if len(out) > 1 and colour:
        out[1] = dict(text=str(out[1]), color=ink(colour), bold=True)
    return out


# ---------- One station box ----------

def station_signage(w, berths, net, colours, grounds=None, blocked=None, sights=()):
    """All signs and color bands of one station box (berths are all the Berths of this box).

    Call it after build_line.build_station: signs replace one glass cell of the
    platform screen doors, and bands replace the outer wall and the lintel row.
    Returns dict(ride, concourse, band) with the count of each.

    blocked is the same "this cell is taken by another structure" test that
    network.plan_berths uses: ride sign positions already avoid those cells, and
    the concourse signs avoid them too. sights are the attractions within walking
    distance of this station.
    """
    berths = list(berths)
    if not berths:
        return dict(ride=0, concourse=0, band=0)
    box = berths[0].box
    band = line_bands(w, box, colours)
    ride = ride_signs(w, berths, net, colours)
    conc = concourse_signs(w, box, berths, net, colours, grounds, blocked, sights)
    return dict(ride=ride, concourse=conc, band=band)
