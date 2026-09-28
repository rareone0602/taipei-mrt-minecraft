#!/usr/bin/env python3
"""Stacked stations and pocket tracks: the two tracks of a line split onto two
levels at a station, or a third track appears between stations.

Not every underground Taipei Metro station is "an island platform with both
tracks on one level":

  · Fuzhong (BL06) is a five-level underground station with **stacked side
    platforms**: platform 1 on B3 toward Taipei Nangang Exhibition Center and
    platform 2 on B5 toward Dingpu. The two tracks are stacked at the same
    position, and both platforms are on the left facing Taipei Nangang
    Exhibition Center (doors open on the left on B3 and on the right on B5).
    That is why OSM's two platform polygons (level -3 / -4) sit in exactly the
    same place.
  · Ximen (BL11/G12), Chiang Kai-shek Memorial Hall (R08/G10), Guting
    (G09/O05) and Dongmen (R07/O06) are **cross-platform transfer stations
    with stacked island platforms**: two lines share one two-level station
    box, each level is "one track of its own, one island, one track of the
    other line", and each line's two tracks are stacked on one side of the
    box. The centers of OSM's two platform polygons fall exactly on the
    midline between the two lines, whose centerlines are 17-22.5 m apart at
    the station.

    Dongmen differs from the other three. The other three have "both tracks on
    a level running in the same direction" (one line opens its doors on the
    left, the other on the right); Dongmen has one door side per level (B2
    right, B4 left), which means the two tracks on a level run in opposite
    directions. Wikipedia singles it out as "different from the other stacked
    island stations", explaining that the layout follows the main passenger
    flows. No special case is needed here: which track stays on the upper
    level depends only on upper_toward, and Dongmen's two lines have
    upper_toward pointing to opposite ends of the station box, so the opposite
    directions follow naturally.

Both need the same thing: **the two tracks of a line split onto two levels
near the station**. The method:

  1. SPLIT_M meters outside the station box, one track starts to descend
     LEVEL_H meters at the maximum grade while the other keeps the rail top of
     the alignment. ``upper_toward`` decides which one descends: Taipei Metro
     runs on the right, so trains running toward that station use the track on
     the right of their direction of travel, which stays on the upper level,
     and the opposite track descends.
  2. FLARE_M meters before the station, the two tracks converge from lateral
     offsets of ±3 to a single offset (stacked). In a shared station box
     (Ximen), each line's two tracks converge to ±8 in the box's coordinate
     system. The box follows the midline of the two lines (the frame made by
     ``shift_samples``) and is built once, by the primary line; within the box
     the partner line builds no cross-section and no longer has a station of
     its own.
  3. The station box is a two-level box structure 21 blocks high. The upper
     level is the original island platform station (dy -2..10, with the
     concourse still at rail top +7, so exits, transfer passages and the
     verification tools need no changes), and the lower level is at
     dy -10..-2.

A pocket track (POCKETS) is an extra storage track between the two main
tracks, between two stations: the main tracks first flare out to
±POCKET_OFF, the third track runs between them, and they then close back to
±3. There are no switches (see docs/limitations.md), so the third track ends
before the main tracks close in too near to it.

Which track is on the upper level, which side the platform is on, and where
the pocket tracks are: none of this is in OSM. It is real data, with its
source noted beside each entry.
"""
import numpy as np

from mrt.domain.alignment import (
    BOX_HALF, MAX_GRADE, PLAT_HALF, PLATFORM_LEN, STEP, STN_TRACK_OFF,
    TUN_TRACK_OFF,
)
from mrt.domain.alignment import FLARE_M as STATION_FLARE_M

# How many blocks the lower level's rail top is below the upper level's. The
# upper platform hall occupies dy -1..5 and the concourse floor slab is at 6;
# placing the lower level at -8 gives it its own floor slab (-10), platform
# (-7), four blocks of headroom (-6..-3) and roof (-2, which is the upper
# level's floor slab).
LEVEL_H = 8
RAMP_M  = LEVEL_H / MAX_GRADE      # A descent of 8 m takes 200 m.
FLARE_M = 40                       # Transition length over which the two tracks converge from ±3 to the target offset.
SPLIT_M = RAMP_M + FLARE_M         # Total length of the transition outside the station box.
BOX_BOTTOM_DY = -(LEVEL_H + 2)     # Floor slab of the two-level box structure.

POCKET_OFF     = 6                 # Lateral offset of the main tracks along a pocket track (the third track is at 0).
POCKET_FLARE_M = 60                # Length over which the main tracks flare out and close in
                                   # (the real turnout zone is about 80 m).
POCKET_LEN_M   = 190               # Storage track length: the central refuge tracks of the later
                                   # Taipei Metro network are about 190 m inside.
POCKET_MIN_GAP = 4.5               # The third track ends where the main tracks come nearer than this
                                   # to the centerline (there are no switches).
# Within this radius, the two lines of a shared station box do not count as
# occupying each other (the same value serves the depth bands and the
# clearance between lines). The radius must cover exactly the range where the
# two lines really are one structure: half a station box (PLATFORM_LEN/2) plus
# the level-split transition (SPLIT_M), plus one spatial-hash cell of slack,
# about 350 m.
#
# Too large a value does damage. It was originally 500 m: south of Guting, the
# Songshan-Xindian Line and the Zhonghe-Xinlu Line run in parallel under
# Roosevelt Road for 500 m with centerlines only 7-13 m apart, yet were judged
# to be allies that needed no separate depths, so the two 14 m wide box
# structures overlapped at the same depth for 400 m.
ALLY_M         = 350
# The two lines of a shared station box can form the "track, island, track"
# cross-section only if their centerlines are within this range: too close and
# two tracks plus an island do not fit; too far and it is no longer one box
# structure. Measured: Ximen 17.2 m, Chiang Kai-shek Memorial Hall 22.5 m,
# Guting 17.5 m, Dongmen 17.1 m, all within 14-24 m. Outside the range it is
# better not to build at all: forcing it produces a box structure tens of
# meters wide that spans a whole road, and it does so silently.
SEP_MIN, SEP_MAX = 2 * STN_TRACK_OFF - 2, 2 * BOX_HALF


# ---------- Real data ----------

# (station name, line) -> specification
#   kind          "side"   stacked side platforms (one track per level, platforms on the same side)
#                 "shared" stacked island platforms shared by two lines (each level: one track of
#                          its own, one island, one track of the other line)
#   upper_toward  the station the upper-level trains run toward (an adjacent station on the same line)
#   plat          "left" / "right": which side of the upper-level trains' direction of travel the
#                 platform is on (side only)
#   partner       the other line of a shared station box (shared only; written on the primary entry)
STACKED = {
    # Chinese Wikipedia, "Fuzhong Station (Taiwan)", station structure: five underground levels,
    # stacked side platforms. B3 platform 1: Bannan Line toward Taipei Nangang Exhibition Center,
    # doors open on the left; B5 platform 2: toward Dingpu, doors open on the right.
    ("府中", "BL"): dict(kind="side", upper_toward="板橋", plat="left"),
    # Chinese Wikipedia, "Ximen Station (Taipei)", platform layout: B2 has the Bannan Line toward
    # Taipei Nangang Exhibition Center (doors open on the right) and the Songshan-Xindian Line toward
    # Songshan (doors open on the left); B3 has the Bannan Line toward Dingpu (doors open on the left)
    # and the Songshan-Xindian Line toward Xindian (doors open on the right).
    ("西門", "BL"): dict(kind="shared", partner="G", upper_toward="台北車站"),
    ("西門", "G"):  dict(kind="shared", upper_toward="北門"),
    # Chinese Wikipedia, "Chiang Kai-shek Memorial Hall Station", platform layout: B2 platform 1,
    # Tamsui-Xinyi Line toward Tamsui (doors open on the left), and platform 2, Songshan-Xindian Line
    # toward Songshan (doors open on the right); B3 platform 3, Tamsui-Xinyi Line toward
    # Guangci/Fengtian Temple (doors open on the right), and platform 4, Songshan-Xindian Line toward
    # Xindian (doors open on the left). The upper level is the "toward Tamsui + toward Songshan" pair.
    ("中正紀念堂", "R"): dict(kind="shared", partner="G", upper_toward="台大醫院"),
    ("中正紀念堂", "G"): dict(kind="shared", upper_toward="小南門"),
    # Chinese Wikipedia, "Guting Station", platform layout: B2 platform 1, Songshan-Xindian Line
    # toward Songshan (doors open on the right), and platform 2, Zhonghe-Xinlu Line toward Huilong or
    # Luzhou (doors open on the left); B3 platform 3, Songshan-Xindian Line toward Xindian (doors open
    # on the left), and platform 4, Zhonghe-Xinlu Line toward Nanshijiao (doors open on the right).
    # The upper level is "toward Songshan + toward Huilong/Luzhou".
    ("古亭", "O"): dict(kind="shared", partner="G", upper_toward="東門"),
    ("古亭", "G"): dict(kind="shared", upper_toward="中正紀念堂"),
    # Chinese Wikipedia, "Dongmen Station (Taipei)", platform layout: B2 platform 1, Zhonghe-Xinlu
    # Line toward Huilong or Luzhou, and platform 2, Tamsui-Xinyi Line toward Tamsui; B4 platform 3,
    # Zhonghe-Xinlu Line toward Nanshijiao, and platform 4, Tamsui-Xinyi Line toward
    # Guangci/Fengtian Temple. The upper level is the "toward Huilong/Luzhou + toward Tamsui" pair.
    # This station has one door side per level (B2 right, B4 left), which means the two tracks on a
    # level run in opposite directions; Wikipedia singles it out as "different from the other
    # stacked island stations". The model needs no special case for it: the two lines'
    # upper_toward point to opposite ends of the station box, and the opposite directions follow
    # naturally. (The two platform levels are B2 and B4, with one floor between them; the model
    # only keeps the levels LEVEL_H apart and ignores the real floor numbers.)
    ("東門", "R"): dict(kind="shared", partner="O", upper_toward="中正紀念堂"),
    ("東門", "O"): dict(kind="shared", upper_toward="忠孝新生"),
}

# Pocket tracks: the line, the stations at each end, the OSM way id of the
# storage track (placed along its geometry when data/sidings.json has it), and
# a fallback for when there is no data (the start of the storage track in
# meters from the center of station box a, and its length).
#
# The main source is the Department of Rapid Transit Systems' own book, "MRT
# Engineering Series, enhanced edition, vol. 9: MRT Track Engineering Practice"
# (捷運工程叢書 精進版 9 捷運軌道工程實務), section 8.3.5.2, "Central sidings",
# page 406 (translated): "A pocket track laid between the up and down tracks
# consists of four #10 and two #7 turnouts connected by the standard track
# between them... On the Tamsui Line the central siding is on the elevated
# section between Shipai (R23) and Qilian (R24) stations; in tunnel sections
# there is one on the Tamsui Line between Taipei Main Station (R13) and
# Zhongshan station (R12); on the Xindian Line they are between Taipower
# Building station (G9) and Gongguan station (G7) and between Dapinglin station
# (G4) and Qizhang station (G3); on the Nangang Line between Zhongxiao Fuxing
# station (BL10) and Zhongxiao Dunhua station (BL11); and on the Tucheng Line
# between Far Eastern Hospital station (BL40) and Haishan station (BL40). On
# the Zhonghe Line none was built, because the right-of-way was hard to
# obtain." (The station numbers are the pre-2009 scheme, and the book predates
# the Xinyi and Songshan lines.)
#
# So the Zhonghe-Xinlu Line has none. That is not an omission: the "ten-billion
# slimming" cost cut of the time replaced its refuge tracks with scissors
# crossovers (Chinese Wikipedia, "Zhonghe-Xinlu Line", the refuge track
# controversy). The three on elevated sections (Shipai–Qilian, Wende–Gangqian,
# Xingfu–New Taipei Industrial Park) cannot be built yet: sec_multi only digs
# tunnel cross-sections, and elevated ones need a separate viaduct version; see
# docs/limitations.md.
POCKETS = [
    # The official book's five underground pocket tracks, all of which OSM maps:
    # Zhongxiao Fuxing–Zhongxiao Dunhua. Chinese Wikipedia, "Zhongxiao Dunhua Station": "A pocket
    #   track for train dispatching lies between this station and Zhongxiao Fuxing station." OSM
    #   way 877532286 (211 m), right against the west side of Zhongxiao Dunhua station.
    dict(ref="BL", a="忠孝復興", b="忠孝敦化", osm=877532286, start=None, length=POCKET_LEN_M),
    # Far Eastern Hospital–Haishan: the storage track for turning trains is south of the station
    #   box, and the depot line to Tucheng Depot branches off here too. Five OSM ways are named
    #   "Far Eastern Hospital pocket track"; the central one is 818792051 (197 m). The metro
    #   company's cab-view video shows this box structure and the third track 29-68 seconds after
    #   departing Far Eastern Hospital.
    dict(ref="BL", a="亞東醫院", b="海山", osm=818792051, start=300, length=POCKET_LEN_M),
    # Taipei Main Station–Zhongshan: OSM tags it not as a siding but as service=yard (way
    #   1226066660, 296 m, layer -4, with two turnout legs at each end, 1226066661-4); its shape is
    #   a standard pocket track. Chinese Wikipedia, "Zhongshan Station (Taipei)": "One pocket track
    #   lies south of the Tamsui Line platforms, toward Taipei Main Station."
    dict(ref="R", a="台北車站", b="中山", osm=1226066660, start=None, length=POCKET_LEN_M),
    # Taipower Building–Gongguan. Chinese Wikipedia, "Taipower Building Station": "A pocket track
    #   lies between this station and Gongguan station to the south, one of the two on the Xindian
    #   Line (the other is between Dapinglin and Qizhang stations). From its opening in 1999 until
    #   Dongmen station on the Zhonghe-Xinlu Line opened, it served only as a reserve track." OSM
    #   way 818790283 (200 m).
    dict(ref="G", a="台電大樓", b="公館", osm=818790283, start=None, length=POCKET_LEN_M),
    # Dapinglin–Qizhang: the Xiaobitan branch shuttle turns back on this track. Chinese Wikipedia,
    #   "Qizhang Station": "Xiaobitan branch trains coming from the Xiaobitan branch enter platform 1
    #   (northbound) to let passengers off, then enter the pocket track north of the station." OSM
    #   way 619265949 (206 m).
    dict(ref="G", a="大坪林", b="七張", osm=619265949, start=None, length=POCKET_LEN_M),
    # Two that are not in the book, on the Xinyi Line (2013) and the Songshan Line (2014), both
    # later than the book:
    # Daan–Xinyi Anhe: OSM way 685934617 is named "Daan pocket track" (214 m, right against the
    #   east side of Daan station). Chinese Wikipedia, "Daan Station (Taiwan)", gives its purpose:
    #   "because this station is the terminus of the Tamsui-Xinyi Line's 'Beitou–Daan' short-turn
    #   service", and its platform table also lists "Tamsui-Xinyi Line short-turn alighting
    #   platform (no boarding)".
    dict(ref="R", a="大安", b="信義安和", osm=685934617, start=None, length=POCKET_LEN_M),
    # Songjiang Nanjing–Nanjing Fuxing: **supported only by a rail fan's compilation** (the PTT
    #   MRT board post "Re: [Question] Pocket tracks" of 2023-09-12 lists "Green line, Songjiang
    #   Nanjing ~ Nanjing Fuxing, shield tunnel - pocket - station, standby"). The Songshan Line
    #   opened only in 2014, later than the book above, and the Chinese Wikipedia articles on
    #   Songjiang Nanjing station, Nanjing Fuxing station and the Songshan-Xindian Line do not
    #   mention it. OSM way 871168318 (201 m, layer -2, tunnel) matches in shape and position, and
    #   its length is not on the scale of a crossover, so it is built accordingly, but this is the
    #   only source.
    dict(ref="G", a="松江南京", b="南京復興", osm=871168318, start=None, length=POCKET_LEN_M),
]



# ---------- Direction and layout ----------

def direction_sign(idx, idx_toward):
    """Return whether going from idx toward the station at idx_toward follows
    the sample order (+1) or runs against it (-1)."""
    return 1 if idx_toward > idx else -1


def upper_side(direction):
    """Return the side of the alignment the upper-level track is on (+1 = the
    right-hand side in sample direction, the nx, nz side).

    Right-hand running: trains running toward +u use the +off track, and trains
    running toward -u use the -off track.
    """
    return direction


def plat_side(direction, plat):
    """Return the side of the alignment a side platform is on. plat is left or
    right relative to the upper-level trains' direction of travel."""
    return -direction if plat == "left" else direction


def layout(kind, side):
    """Return the layout of one platform level (lateral offsets in station box
    coordinates):
      tracks  the tracks on this level
      psd     platform screen doors
      yellow  warning strips
      plat    lateral offset range of the platform paving (inclusive)
      stair   lateral offset range of the stairs from the concourse down to the platform
      lstair  lateral offset range of the stairs from the upper platform down to the lower platform
    For kind="side", side is the platform side; for kind="shared", side is the
    partner line's side.
    """
    if kind == "side":
        s = side
        return dict(tracks=[-STN_TRACK_OFF * s], psd=[-PLAT_HALF * s],
                    yellow=[-(PLAT_HALF - 1) * s],
                    plat=(min(-(PLAT_HALF - 1) * s, (BOX_HALF - 2) * s),
                          max(-(PLAT_HALF - 1) * s, (BOX_HALF - 2) * s)),
                    stair=(min(0, 2 * s), max(0, 2 * s)),
                    lstair=(min(6 * s, 8 * s), max(6 * s, 8 * s)))
    return dict(tracks=[-STN_TRACK_OFF * side, STN_TRACK_OFF * side],
                psd=[-PLAT_HALF, PLAT_HALF],
                yellow=[-(PLAT_HALF - 1), PLAT_HALF - 1],
                plat=(-(PLAT_HALF - 1), PLAT_HALF - 1),
                stair=(-3, 3), lstair=(-3, 3))


# ---------- Coordinate systems ----------

def shift_samples(samples, m):
    """Shift the whole sample sequence m meters along the normal (+m = the
    right-hand side). The frame of a shared station box is the primary's
    samples shifted to the midline of the two lines."""
    return [(x - uz * m, z + ux * m, ux, uz, k) for x, z, ux, uz, k in samples]


def station_samples(sg, bi):
    """Return the station box coordinate system of station bi: the frame for a
    shared station box, otherwise the segment's own samples."""
    return sg.get("frames", {}).get(bi, sg["samples"])


def tracks_at(sg, i):
    """Return the tracks at sample i: [(lateral offset, rail top y), ...].

    In a level-split transition (sg["split"]) each of the two tracks has its
    own lateral offset and rail top; elsewhere they are at ±toff with one rail
    top. The third track of a pocket track (sg["extras"]) is included when i
    falls within its range.
    """
    y = int(sg["ys"][i])
    if sg.get("split") is not None and sg["split"][i]:
        out = [(float(sg["off_side"][s][i]), int(sg["y_side"][s][i])) for s in (1, -1)]
    else:
        t = float(sg["toff"][i]) if "toff" in sg else float(TUN_TRACK_OFF)
        out = [(t, y), (-t, y)]
    for ex in sg.get("extras", ()):
        if ex["i0"] <= i <= ex["i1"]:
            out.append((float(ex["off"]), y))
    return out


def strands(sg):
    """Return every track that gets rails: [(i0, i1, off_at(i), y_at(i)), ...].
    One for each of the two main tracks over the whole segment, plus one for a
    pocket track."""
    n = len(sg["samples"])
    split = sg.get("split")
    out = []
    for s in (1, -1):
        def off_at(i, s=s):
            if split is not None and split[i]:
                return float(sg["off_side"][s][i])
            return s * float(sg["toff"][i])

        def y_at(i, s=s):
            if split is not None and split[i]:
                return int(sg["y_side"][s][i])
            return int(sg["ys"][i])
        out.append((0, n - 1, off_at, y_at))
    for ex in sg.get("extras", ()):
        out.append((ex["i0"], ex["i1"], lambda i, o=ex["off"]: float(o),
                    lambda i: int(sg["ys"][i])))
    return out


def lateral_offset(samples, j, x, z):
    """Return the lateral offset of point (x, z) in the coordinate system of
    sample j (+ = the right-hand side)."""
    sx, sz, ux, uz, _ = samples[j]
    return -(x - sx) * uz + (z - sz) * ux


def nearest(samples, x, z, lo=0, hi=None):
    hi = len(samples) - 1 if hi is None else hi
    best, bi = 1e18, lo
    for j in range(lo, hi + 1):
        d = (samples[j][0] - x) ** 2 + (samples[j][1] - z) ** 2
        if d < best:
            best, bi = d, j
    return bi


def frame_track_offsets(samples, lo, hi, frame, flo, fhi, foff):
    """For each partner sample lo..hi, compute the lateral offset, in the
    partner's own coordinate system, of "the line at offset foff in the frame
    coordinate system". The two lines are nearly parallel within the station
    box, so the nearest frame point is enough."""
    pts = [(frame[i][0] - frame[i][3] * foff, frame[i][1] + frame[i][2] * foff)
           for i in range(flo, fhi + 1)]
    out = []
    for j in range(lo, hi + 1):
        sx, sz = samples[j][0], samples[j][1]
        px, pz = min(pts, key=lambda p: (p[0] - sx) ** 2 + (p[1] - sz) ** 2)
        out.append(lateral_offset(samples, j, px, pz))
    return out


# ---------- Splitting the two tracks onto two levels ----------

def split_sides(n, lo, hi, up_side, tgt_in, ys, step=STEP):
    """Split the two tracks onto two levels around station lo..hi.

    tgt_in  the lateral offset the two tracks converge to at each sample within
            the station box (len = hi - lo + 1)
    Returns (off_side, y_side, multi):
      off_side[s]  per-sample lateral offset of track s = ±1 (still ±3 between stations)
      y_side[s]    per-sample rail top; the descending track is at ys - LEVEL_H in the station
      multi        bool array; samples that are True must be built with sec_multi
    """
    ys = np.asarray(ys)
    off_side = {1: np.full(n, float(TUN_TRACK_OFF)), -1: np.full(n, -float(TUN_TRACK_OFF))}
    y_side = {1: ys.astype(float).copy(), -1: ys.astype(float).copy()}
    multi = np.zeros(n, dtype=bool)
    fl = max(1, int(round(FLARE_M / step)))
    rp = max(1, int(round(RAMP_M / step)))
    down = -up_side
    tgt = list(tgt_in)
    for i in range(lo, hi + 1):
        t = tgt[i - lo]
        off_side[1][i] = off_side[-1][i] = t
        y_side[down][i] = ys[i] - LEVEL_H
        multi[i] = True
    for end, sgn, t_end in ((lo, -1, tgt[0]), (hi, 1, tgt[-1])):
        for j in range(1, fl + 1):                           # Converge.
            i = end + sgn * j
            if not (0 <= i < n):
                break
            f = j / fl
            for s in (1, -1):
                off_side[s][i] = t_end + (s * TUN_TRACK_OFF - t_end) * f
            y_side[down][i] = ys[i] - LEVEL_H
            multi[i] = True
        for j in range(1, rp + 1):                           # Descend.
            i = end + sgn * (fl + j)
            if not (0 <= i < n):
                break
            y_side[down][i] = ys[i] - LEVEL_H * (1 - j / rp)
            multi[i] = True
    for s in (1, -1):
        y_side[s] = np.round(y_side[s]).astype(int)
    return off_side, y_side, multi


def split_extent(lo, hi, n, step=STEP):
    """Return the sample index range covered by the level-split transition
    (station box included)."""
    ext = int(round(SPLIT_M / step))
    return max(0, lo - ext), min(n - 1, hi + ext)


def station_range(n, bi, step=STEP):
    half = int(PLATFORM_LEN / 2 / step)
    return max(0, bi - half), min(n - 1, bi + half)


def _ensure_split(sg):
    """The first time a segment is split, add per-sample arrays for the two
    tracks (by default ±3 at one rail top)."""
    n = len(sg["samples"])
    if "split" not in sg:
        sg["off_side"] = {1: np.full(n, float(TUN_TRACK_OFF)),
                          -1: np.full(n, -float(TUN_TRACK_OFF))}
        sg["y_side"] = {1: np.asarray(sg["ys"]).astype(int).copy(),
                        -1: np.asarray(sg["ys"]).astype(int).copy()}
        sg["split"] = np.zeros(n, dtype=bool)
    if "multi" not in sg:
        sg["multi"] = np.zeros(n, dtype=bool)


def _apply_split(sg, lo, hi, up_side, tgt):
    _ensure_split(sg)
    off_side, y_side, multi = split_sides(len(sg["samples"]), lo, hi, up_side, tgt, sg["ys"])
    for s in (1, -1):
        sg["off_side"][s][multi] = off_side[s][multi]
        sg["y_side"][s][multi] = y_side[s][multi]
    sg["split"] |= multi
    sg["multi"] |= multi


def plan_side(sg, bi, direction, plat):
    """Stacked side-platform station (Fuzhong): pin the vertical profile flat
    and split the two tracks onto two levels. direction is the upper-level
    trains' direction of travel (±1 in sample order), and plat is left or right
    of that direction. Returns the layout (also recorded in sg["stacked"][bi],
    which the cli and the exit planner use to recognize stacked stations)."""
    n = len(sg["samples"])
    lo, hi = station_range(n, bi)
    fl = int(round(FLARE_M / STEP))
    sg["ys"] = pin_profile(sg["ys"], max(0, lo - fl), min(n - 1, hi + fl), int(sg["ys"][bi]))
    lay = layout("side", plat_side(direction, plat))
    _apply_split(sg, lo, hi, upper_side(direction), [lay["tracks"][0]] * (hi - lo + 1))
    sg.setdefault("stacked", {})[bi] = lay
    return lay


def plan_shared(sg, bi, direction, psg, pbi, pdirection):
    """Stacked island station shared by two lines (Ximen). sg is the primary
    (the line that builds the station box) and psg the partner. The box
    coordinate system is the primary's samples shifted to the midline of the
    two lines (frame); the primary's two tracks converge to −8·side in the
    frame and the partner's to +8·side (side is the side of the primary that
    the partner is on). The partner's rail top is pinned to match the
    primary's; within the box it builds no cross-section (nobuild) and no
    longer has a station of its own. Returns (layout, midline offset in m,
    side, partner's station box range); if the centerline distance between the
    two lines is not within SEP_MIN..SEP_MAX, returns None and changes
    nothing."""
    n, pn = len(sg["samples"]), len(psg["samples"])
    lo, hi = station_range(n, bi)
    fl = int(round(FLARE_M / STEP))
    y_c = int(sg["ys"][bi])
    px, pz = psg["samples"][pbi][0], psg["samples"][pbi][1]
    doff = lateral_offset(sg["samples"], bi, px, pz)
    if not (SEP_MIN <= abs(doff) <= SEP_MAX):
        return None
    side = 1 if doff >= 0 else -1
    m = int(abs(doff) // 2)
    frame = shift_samples(sg["samples"], side * m)
    sg.setdefault("frames", {})[bi] = frame
    sg["ys"] = pin_profile(sg["ys"], max(0, lo - fl), min(n - 1, hi + fl), y_c)
    lay = layout("shared", side)
    _apply_split(sg, lo, hi, upper_side(direction),
                 [side * (m - STN_TRACK_OFF)] * (hi - lo + 1))
    plo = nearest(psg["samples"], frame[lo][0], frame[lo][1])
    phi = nearest(psg["samples"], frame[hi][0], frame[hi][1])
    if plo > phi:
        plo, phi = phi, plo
    ptgt = frame_track_offsets(psg["samples"], plo, phi, frame, lo, hi, side * STN_TRACK_OFF)
    psg["ys"] = pin_profile(psg["ys"], max(0, plo - fl), min(pn - 1, phi + fl), y_c)
    _apply_split(psg, plo, phi, upper_side(pdirection), ptgt)
    psg.setdefault("nobuild", set()).update(range(plo, phi + 1))
    psg["stn"].pop(pbi, None)
    sg.setdefault("stacked", {})[bi] = lay
    return lay, m, side, (plo, phi)


def plan_pocket(sg, ia, ib, start_m, length_m, rng=None):
    """Open a pocket track between stations ia and ib of sg: widen the main
    track offsets in place and record the third track in sg["extras"]. Call it
    after track_offsets and before hw is computed. Returns (i0, i1) or None."""
    n = len(sg["samples"])
    if "multi" not in sg:
        sg["multi"] = np.zeros(n, dtype=bool)
    res = pocket_zone(sg["toff"], n, ia, ib, start_m, length_m, rng=rng)
    if res is None:
        return None
    i0, i1, multi = res
    sg["multi"] |= multi
    sg.setdefault("extras", []).append(dict(i0=i0, i1=i1, off=0.0))
    return i0, i1


# ---------- Pocket tracks ----------

def pocket_zone(toff, n, ia, ib, start_m, length_m, step=STEP, rng=None,
                off=POCKET_OFF, flare_m=POCKET_FLARE_M, min_gap=POCKET_MIN_GAP):
    """Open a stretch of pocket track between stations ia and ib. Widens the
    main track offsets in place and returns (i0, i1, multi): the sample range
    of the third track and the mask of samples to build with sec_multi.

    rng      (i0, i1): the sample range of the storage track (used when OSM
             maps that track, clipped to the range that fits between the two
             stations); otherwise start_m / length_m are used
    start_m  meters from the center of station box ia to the start of the
             storage track (None = centered between the two stations)
    """
    half = int(PLATFORM_LEN / 2 / step)
    fl = max(1, int(round(flare_m / step)))
    ln = int(round(length_m / step))
    a, b = (ia, ib) if ia < ib else (ib, ia)
    # The pocket track may only use the space outside the flares at the two
    # stations (±3 -> ±8, FLARE_M). At Zhongxiao Dunhua the turnout legs in OSM
    # run all the way to the west end of the station box, while the storage
    # track itself is only 90 m from the box.
    stn_fl = int(round(STATION_FLARE_M / step))
    free_lo, free_hi = a + half + stn_fl, b - half - stn_fl
    if rng is not None:
        i0, i1 = max(free_lo + fl, min(rng)), min(free_hi - fl, max(rng))
    else:
        if start_m is None:
            c = (a + b) // 2
            i0 = c - ln // 2
        else:
            i0 = (ia + int(round(start_m / step))) if ia < ib else (ia - int(round(start_m / step)) - ln)
        i0 = max(free_lo + fl, min(free_hi - fl - ln, i0))
        i1 = i0 + ln
    if i1 - i0 < 2 * fl or i0 < free_lo:
        return None
    multi = np.zeros(n, dtype=bool)
    for i in range(i0, i1 + 1):
        toff[i] = max(toff[i], float(off))
    for j in range(1, fl + 1):
        v = off + (TUN_TRACK_OFF - off) * j / fl
        toff[i0 - j] = max(toff[i0 - j], v)
        toff[i1 + j] = max(toff[i1 + j], v)
    for i in range(i0 - fl, i1 + fl + 1):
        multi[i] = True
    # Extend the third track into the flares at both ends until the main tracks
    # come nearer than min_gap to the centerline.
    lo, hi = i0, i1
    while lo - 1 >= i0 - fl and toff[lo - 1] >= min_gap:
        lo -= 1
    while hi + 1 <= i1 + fl and toff[hi + 1] >= min_gap:
        hi += 1
    return lo, hi, multi


# ---------- Pinning the vertical profile ----------

def pin_profile(ys, lo, hi, y_c, step=STEP, grade=MAX_GRADE):
    """Pin lo..hi flat at y_c, and converge back to the original vertical
    profile at the maximum grade on both sides (clamping both rises and falls).

    The two lines of a shared station box need identical rail tops, and the
    stairs between the two platform levels can only be built accurately if the
    box is level. The original profile is only clamped downward (a lower
    envelope), so after pinning, nearby points may be far too low or too high
    relative to y_c; this walks outward from the pinned stretch and clamps each
    step to within ±grade.
    """
    y = np.asarray(ys, dtype=float).copy()
    n = len(y)
    d = grade * step
    y[lo:hi + 1] = y_c
    for i in range(hi + 1, n):
        y[i] = min(max(y[i], y[i - 1] - d), y[i - 1] + d)
    for i in range(lo - 1, -1, -1):
        y[i] = min(max(y[i], y[i + 1] - d), y[i + 1] + d)
    return np.round(y).astype(int)


def stacked_pins(stations, refs_of, band=0, radius_m=ALLY_M, reserve_m=60.0):
    """Depth-band pins for stacked stations:

      · The station itself is pinned to band (Ximen B2/B3 and Fuzhong B3/B5
        are all shallow), and both lines of a shared station box are pinned to
        the same band, since they are one box structure. The pin radius is the
        same value as ALLY_M: the pinned range is the range where the two lines
        are one structure, and outside it the banding algorithm must be free to
        separate them.
      · The lower level is LEVEL_H below the upper one, so the 21-block box
        structure reaches into the depth of the next band; the station box
        range therefore also reserves the next band, so that no other line can
        pass beneath it.

    stations  [(refs, station name, x, z, ...)] (the format of cli.load_stations)
    refs_of   station name -> the set of line codes registered for that station in STACKED
    Returns pins in the format of tunnel_layers.assign_bands: [(x, z, radius, ref, band)].
    Real pins come first and reservations after, because assign_bands takes the
    first hit for its own line.
    """
    pins, reserve = [], []
    for row in stations:
        name, x, z = row[1], row[2], row[3]
        for ref in sorted(refs_of.get(name, ())):
            pins.append((x, z, radius_m, ref, band))
            reserve.append((x, z, reserve_m, ref, band + 1))
    return pins + reserve
