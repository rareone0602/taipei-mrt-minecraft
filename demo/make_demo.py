#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cut the gameplay recording into the demo material for the README.

The recording, demo/raw-4.mov, is a macOS screen recording made on 28
September 2026: full screen, 3024x1898 at 120 fps, 12 minutes 20 seconds and
6 GB, so it is not in version control. This script is the only link between
it and the files in the repo: which segments the video uses, what the
captions say and which second each still is taken from are all written here,
not tuned by hand.

    ./.venv/bin/python demo/make_demo.py               # Rebuild everything under demo/.
    ./.venv/bin/python demo/make_demo.py --only map    # Redraw only the network map.
    ./.venv/bin/python demo/make_demo.py --only video  # Rebuild only the video and its cover.

Outputs:
    hero.gif        The animation at the top of the README (the Circular Line's viaduct).
    tour.mp4        The demo video: route map, a ride, Taipei Main Station, six attractions
                    and the Circular Line, with a title page and an end page.
    tour-thumb.jpg  The video's cover (clicking it in the README opens the video).
    network-map.png Network diagram, drawn directly from the projected alignment data.
    route-map / arrival / sign / platform / exit / main-station / taipei101 /
    taipei101-top / sights-menu / presidential / longshan / viaduct .jpg
                    Twelve stills.

Every word is set in Shantell Sans on paper, after phy's style guide
(https://github.com/rareone0602/phy_friends/blob/main/STYLE.md): no words over
the picture (§7), so each caption is a note on the rule under it; no
gradients, shadows or glows; graphite inks, never black. The font and its
licence are in demo/fonts/, copied from the guide's kit.

Needs ffmpeg (this machine's ffmpeg is built without libfreetype, so all text is
drawn with PIL as PNGs and overlaid, rather than with drawtext), plus pillow and
numpy.
"""
import argparse
import csv
import json
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

DEMO = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(DEMO)
WORK = os.path.join(DEMO, ".work")          # Intermediate files, not in version control.
RAW = os.path.join(DEMO, "raw-4.mov")
FACE = os.path.join(DEMO, "fonts", "ShantellSans-Variable.ttf")

# The recording is full-screen 16:10. Cropping 16:9 from the top cuts off
# exactly the hotbar at the bottom.
CROP = "crop=3024:1701:0:0"
# For ten seconds after a teleport, "Triggered [...]" stays in the chat area
# at the bottom left. This tighter 16:9 crop ends above it and keeps the
# station title, the subtitle and the action bar.
CROP_NOCHAT = "crop=2700:1519:162:0"
FPS = 30
XFADE = 0.5

EQ = "eq=contrast=1.04:saturation=1.08"                         # The game is bright already.
EQ_DARK = "eq=brightness=0.06:contrast=1.08:saturation=1.10"    # Underground.

# ---- Paper and type (STYLE.md §4, §5, §8) ----
# A 1280x720 frame is a slide, which is the notebook page with everything
# x1.5, so the rules are 48 px apart.
SLIDE = 1.5
L = int(32 * SLIDE)                 # Rule spacing.
MARGIN_X = int(88 * SLIDE)          # The margin line.
TEXT_X = MARGIN_X + L // 2          # Words start just right of the margin line.
PAPER = (0xfb, 0xf9, 0xf3)
RULE = (0xcf, 0xdb, 0xe8)
MARGIN = (0xe6, 0xaa, 0xa3)
INK = (0x3d, 0x3c, 0x39)
INK_2 = (0x6d, 0x6a, 0x63)
INK_3 = (0x97, 0x93, 0x8a)
INFORMAL = 100                      # The dial: a hobby project.

# Sizes step by 1.2 from the 18 px print (STYLE.md §5), then x1.5 for a slide.
TITLE = int(64 * SLIDE)
H3 = int(26 * SLIDE)
CAPTION = int(22 * SLIDE)           # Also the intro.
SMALL = int(15 * SLIDE)

W, PICTURE_H = 1280, 720            # The picture is 15 rules tall, top and bottom on rules.
STRIP_H = 2 * L                     # The caption sits on the first rule under the picture.
H = PICTURE_H + STRIP_H             # 816 px: 17 rules.
SCALE = "scale=%d:%d:flags=lanczos,setsar=1" % (W, PICTURE_H)

# Video shots: (start in seconds, length in the recording, speed-up, crop, grade, caption key).
SHOTS = [
    (1.0,    9.0, 1, CROP,        EQ,      "route"),         # Route map -> Tamsui-Xinyi Line -> Taipei Main Station.
    (378.8, 10.0, 1, CROP_NOCHAT, EQ_DARK, "ride"),          # The ride sign, then five stations, one per click.
    (434.5,  7.5, 1, CROP,        EQ,      "main_station"),  # Spectator mode above Taipei Main Station.
    (40.0,   4.0, 1, CROP_NOCHAT, EQ,      "taipei101"),     # The viewpoint in front of Taipei 101.
    (44.0,  52.0, 4, CROP_NOCHAT, EQ,      "spire"),         # Up the side of the tower to the spire.
    (188.5,  7.0, 1, CROP,        EQ,      "presidential"),  # Over the courtyards of the Presidential Office.
    (283.5,  3.0, 1, CROP_NOCHAT, EQ,      "museum"),        # Up into the museum's dome.
    (304.5,  4.0, 1, CROP_NOCHAT, EQ,      "ferris"),        # The Miramar Ferris Wheel.
    (514.0, 10.0, 2, CROP,        EQ,      "sun_yat_sen"),   # Back from the Sun Yat-sen Memorial Hall's roof.
    (655.5, 20.0, 2, CROP_NOCHAT, EQ,      "longshan"),      # From Longshan Temple station to the temple.
    # Zhonghe's arrival is too short to read a caption of its own, so it
    # shares the viaduct's, and the strip holds still across the dissolve.
    (689.0,  2.5, 1, CROP_NOCHAT, EQ,      "viaduct"),       # Arrival on Zhonghe's elevated platform.
    (694.0, 16.0, 2, CROP_NOCHAT, EQ,      "viaduct"),       # Along the Circular Line's viaduct.
]

# Captions are chrome, so lower case; names keep their case (STYLE.md §3).
CAPTIONS = {
    "route":        u"the route map: a line, then a station, and you land on its platform",
    "ride":         u"right-click the sign on the platform to ride to the next station",
    "main_station": u"Taipei Main Station: every kiosk is a real exit, at its real position",
    "taipei101":    u"Taipei 101, 508 m to the tip of its spire",
    "spire":        u"the world is raised to y639 to fit it; vanilla stops at y319",
    "presidential": u"the Presidential Office Building, 1919",
    "museum":       u"under the dome of the National Taiwan Museum, 1915",
    "ferris":       u"the Miramar Ferris Wheel, 100 m, on the roof of its mall",
    "sun_yat_sen":  u"the Sun Yat-sen Memorial Hall, 1972",
    "longshan":     u"Longshan Temple, 223 m from its station, as in Taipei",
    "viaduct":      u"from Zhonghe along the Circular Line's viaduct",
}

TITLE_PAGE = (u"Taipei Metro, 1:1",
              u"rebuilt in Minecraft, one block to the metre",
              u"193 stations · 472 exits · recorded 28 sep 2026 · silent")
END_PAGE = (u"there are no trains.",
            u"you are teleported instead, which at least keeps to the timetable.",
            u"github.com/rareone0602/taipei-mrt-minecraft · map data © OpenStreetMap contributors")
TITLE_S, END_S = 3.2, 3.6

# The cover is a frame of the Taipei 101 shot, with the caption telling what
# the video holds; the length is filled in once the video is cut.
COVER = (42.0, CROP_NOCHAT, EQ,
         u"the demo, %d seconds: the route map, a ride and six attractions")

# Stills: file name -> (second, crop, grade).
STILLS = {
    "route-map":     (391.0, CROP,        EQ),       # Tamsui-Xinyi Line list, Taipei Main Station's tooltip.
    "arrival":       (690.3, CROP_NOCHAT, EQ),       # Zhonghe, Circular Line.
    "sign":          (379.3, CROP_NOCHAT, EQ_DARK),  # A ride sign at Taipei Main Station.
    "platform":      (396.0, CROP_NOCHAT, EQ_DARK),  # The Tamsui-Xinyi Line platform at Taipei Main Station.
    "exit":          (261.0, CROP,        EQ),       # Ximen exit 1.
    "main-station":  (441.0, CROP,        EQ),       # Taipei Main Station and its exit kiosks.
    "taipei101":     (42.0,  CROP_NOCHAT, EQ),       # From the viewpoint.
    "taipei101-top": (90.0,  CROP,        EQ),       # The top sections and the spire.
    "sights-menu":   (272.5, CROP,        EQ),       # National Taiwan Museum's tooltip.
    "presidential":  (193.0, CROP,        EQ),       # The Presidential Office Building from above.
    "longshan":      (674.0, CROP,        EQ),       # Longshan Temple from above.
    "viaduct":       (699.0, CROP_NOCHAT, EQ),       # The Circular Line's viaduct.
}

# The segment for hero.gif: along the Circular Line's viaduct.
HERO = (695.0, 5.0, CROP_NOCHAT, EQ)


def run(cmd):
    subprocess.run(cmd, check=True)


def ensure_raqm():
    """Re-run under Homebrew's library path if Pillow cannot load raqm.

    Pillow's wheel carries raqm but finds fribidi only at run time. Without
    raqm the hand does not bounce and repeated letters do not swap in their
    alternates (STYLE.md §5).
    """
    from PIL import features
    if features.check("raqm"):
        return
    lib = "/opt/homebrew/lib"
    if os.environ.get("DYLD_LIBRARY_PATH") == lib or \
            not os.path.exists(os.path.join(lib, "libfribidi.0.dylib")):
        raise SystemExit("Pillow cannot load raqm, which the text needs for Shantell "
                         "Sans's bounce and alternates; install fribidi (brew install fribidi)")
    env = dict(os.environ, DYLD_LIBRARY_PATH=lib)
    os.execve(sys.executable, [sys.executable] + sys.argv, env)


def need_raw():
    if not os.path.exists(RAW):
        raise SystemExit("Missing the raw recording %s (it is not in version control; "
                         "ask the author for it)" % os.path.relpath(RAW, REPO))


# --------------------------------------------------------------------------
# Paper and pencil
# --------------------------------------------------------------------------

def face(size, hand=False, informal=INFORMAL, weight=300):
    """Shantell Sans at one setting of the dial (STYLE.md §5).

    The hand (titles, captions, notes) is never neater than 50 and bounces in
    the top half of the dial; the print never bounces. Everything is Light
    (300) unless pressed harder.
    """
    f = ImageFont.truetype(FACE, size, layout_engine=ImageFont.Layout.RAQM)
    informality = max(informal, 50) if hand else informal
    bounce = max(0, informality - 50) if hand else 0
    f.set_variation_by_axes([weight, informality, bounce, 0])
    return f


def noise(h, w, seed):
    """Fine fractal noise in 0..1: a pixel octave over a coarser one."""
    rng = np.random.default_rng(seed)
    coarse = rng.random((h // 4 + 1, w // 4 + 1))
    coarse = np.asarray(Image.fromarray((coarse * 255).astype(np.uint8))
                        .resize((w, h), Image.BILINEAR)) / 255.0
    return 0.6 * rng.random((h, w)) + 0.4 * coarse


def paper(w, h, rules=True, margin=True, top=0, tooth=True):
    """A sheet of lined notebook paper, with its tooth multiplied over it.

    top is how far the sheet sits below the top of the frame, so a strip under
    the picture carries on the frame's rules rather than starting its own.
    """
    im = Image.new("RGB", (w, h), PAPER)
    d = ImageDraw.Draw(im)
    if rules:
        for y in range(L - top % L, h, L):
            d.line([(0, y), (w, y)], fill=RULE, width=2)
    if margin:
        d.line([(MARGIN_X, 0), (MARGIN_X, h)], fill=MARGIN, width=2)
    if not tooth:
        return im
    grain = 1.0 - 0.4 * 0.12 * noise(h, w, seed=11)       # The tooth, at 40%.
    return Image.fromarray((np.asarray(im) * grain[..., None]).astype(np.uint8))


def graphite(layer, seed=7):
    """The graphite filter (STYLE.md §6): pencil grain taken out of the ink's alpha."""
    a = np.asarray(layer).astype(float)
    n = 0.5 + 0.12 * np.random.default_rng(seed).standard_normal(a.shape[:2])
    a[..., 3] *= np.clip(2.1 - 2.4 * n, 0.0, 1.0)
    return Image.fromarray(a.astype(np.uint8))


def write(im, rule_y, s, f, ink, tilt=0.0, pencil=False):
    """Write one line with its baseline on the rule at rule_y.

    tilt is anticlockwise, in degrees (STYLE.md §6: the title -1°).
    """
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    if TEXT_X + d.textlength(s, font=f) > im.width - L:
        raise ValueError("%r is too long for one line; shorten it" % s)
    d.text((TEXT_X, rule_y), s, font=f, fill=ink + (255,), anchor="ls")
    if pencil:
        layer = graphite(layer)
    if tilt:
        layer = layer.rotate(tilt, resample=Image.BICUBIC, center=(TEXT_X, rule_y))
    im.paste(layer, (0, 0), layer)


def strip(caption):
    """The paper under the picture, with the caption as a note on its first rule."""
    im = paper(W, STRIP_H, top=PICTURE_H)
    if caption:
        write(im, L, caption, face(CAPTION, hand=True), INK_2)
    return im


def page(lines, big):
    """A full page: a line in the hand, one in the print, and small print."""
    head, intro, small = lines
    im = paper(W, H)
    if big:
        write(im, 8 * L, head, face(TITLE, hand=True), INK, tilt=1.0, pencil=True)
    else:
        write(im, 8 * L, head, face(H3, hand=True), INK)
    write(im, 10 * L, intro, face(CAPTION), INK_2)
    write(im, 11 * L, small, face(SMALL), INK_2)
    return im


# --------------------------------------------------------------------------
# Frames
# --------------------------------------------------------------------------

def grab(ss, crop, eq, out, width=1280, png=False):
    vf = "%s,%s,scale=%d:-2:flags=lanczos" % (crop, eq, width)
    cmd = ["ffmpeg", "-v", "error", "-y", "-ss", str(ss), "-i", RAW,
           "-frames:v", "1", "-vf", vf]
    if not png:
        cmd += ["-q:v", "3"]
    run(cmd + [out])


def build_stills():
    print("Stills:")
    for name, (ss, crop, eq) in STILLS.items():
        grab(ss, crop, eq, os.path.join(DEMO, name + ".jpg"))
        print("  %s.jpg" % name)


# --------------------------------------------------------------------------
# Video
# --------------------------------------------------------------------------

def render_page(png, dur, out):
    run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-t", str(dur), "-i", png,
         "-vf", "fps=%d,format=yuv420p" % FPS,
         "-c:v", "libx264", "-preset", "slow", "-crf", "18", out])


def render_shot(shot, strip_png, out):
    """Render one shot as the picture over its strip of paper."""
    ss, dur, speed, crop, eq, _ = shot
    fc = ("[0:v]%s,%s,%s,setpts=PTS/%g,fps=%d,pad=%d:%d:0:0[v];"
          "[v][1:v]overlay=0:%d,format=yuv420p[o]"
          % (crop, eq, SCALE, speed, FPS, W, H, PICTURE_H))
    run(["ffmpeg", "-v", "error", "-y", "-ss", str(ss), "-t", str(dur), "-i", RAW,
         "-i", strip_png, "-filter_complex", fc, "-map", "[o]", "-an",
         "-c:v", "libx264", "-preset", "slow", "-crf", "18", out])
    return dur / speed


def cut(parts, out):
    """Cross-dissolve the parts into one video; each join shortens it by one XFADE."""
    inputs = []
    for f, _ in parts:
        inputs += ["-i", f]
    fc, cur, acc = [], "[0:v]", parts[0][1]
    for i in range(1, len(parts)):
        off = acc - XFADE
        lab = "[x%d]" % i
        fc.append("%s[%d:v]xfade=transition=fade:duration=%.2f:offset=%.3f%s"
                  % (cur, i, XFADE, off, lab))
        cur, acc = lab, off + parts[i][1]
    # The end fades to paper, not to black.
    fc.append("%sfade=out:st=%.2f:d=0.8:color=0x%02x%02x%02x,format=yuv420p[o]"
              % ((cur, acc - 0.8) + PAPER))
    run(["ffmpeg", "-v", "error", "-y"] + inputs +
        ["-filter_complex", ";".join(fc), "-map", "[o]",
         "-c:v", "libx264", "-preset", "slow", "-crf", "25", "-tune", "animation",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", out])
    return acc


def build_video():
    print("Video:")
    parts = []
    p = os.path.join(WORK, "00_title.mp4")
    page(TITLE_PAGE, big=True).save(os.path.join(WORK, "title.png"))
    render_page(os.path.join(WORK, "title.png"), TITLE_S, p)
    parts.append((p, TITLE_S))
    for i, shot in enumerate(SHOTS):
        key = shot[5]
        png = os.path.join(WORK, "strip_%s.png" % key)
        strip(CAPTIONS[key]).save(png)
        p = os.path.join(WORK, "%02d_%s.mp4" % (i + 1, key))
        parts.append((p, render_shot(shot, png, p)))
        print("  Shot %d: %s, %.1f s" % (i + 1, key, parts[-1][1]))
    p = os.path.join(WORK, "99_end.mp4")
    page(END_PAGE, big=False).save(os.path.join(WORK, "end.png"))
    render_page(os.path.join(WORK, "end.png"), END_S, p)
    parts.append((p, END_S))

    out = os.path.join(DEMO, "tour.mp4")
    length = cut(parts, out)
    print("  tour.mp4 (%.1f s, %.1f MB)" % (length, os.path.getsize(out) / 1e6))
    build_cover(length)


def build_cover(length):
    """Draw the video's cover: a frame of it, as it looks in the video."""
    ss, crop, eq, caption = COVER
    frame = os.path.join(WORK, "cover_frame.png")
    grab(ss, crop, eq, frame, png=True)
    im = Image.new("RGB", (W, H))
    im.paste(Image.open(frame).convert("RGB").resize((W, PICTURE_H), Image.LANCZOS), (0, 0))
    im.paste(strip(caption % round(length)), (0, PICTURE_H))
    im.save(os.path.join(DEMO, "tour-thumb.jpg"), quality=88)
    print("  tour-thumb.jpg")


def build_gif():
    """Render hero.gif.

    GIF has no inter-frame compression, and a flight over grass changes most
    pixels in every frame, so it gets only 5 seconds, 560 px, 10 fps and 128
    colors; any more passes 3 MB.
    """
    ss, dur, crop, eq = HERO
    vf = ("%s,%s,fps=10,scale=560:-1:flags=lanczos,split[a][b];"
          "[a]palettegen=max_colors=128:stats_mode=diff[p];"
          "[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle" % (crop, eq))
    out = os.path.join(DEMO, "hero.gif")
    run(["ffmpeg", "-v", "error", "-y", "-ss", str(ss), "-t", str(dur), "-i", RAW,
         "-vf", vf, "-loop", "0", out])
    print("hero.gif (%.1f MB)" % (os.path.getsize(out) / 1e6))


# --------------------------------------------------------------------------
# Network diagram
# --------------------------------------------------------------------------

# A chart is set at the neat end of the dial and sits on blank paper, with no
# rules behind it, since they would read as gridlines (STYLE.md §8). The lines
# keep the Metro's own colours: they are the data, the only colour on the page.
MAP_W, MAP_H, MAP_PAD, MAP_BOTTOM = 2000, 1440, 70, 150
LEGEND = [
    ("BR", u"Wenhu Line", "#A74C00"), ("R", u"Tamsui-Xinyi Line", "#FF0000"),
    ("G", u"Songshan-Xindian Line", "#1e7b54"), ("O", u"Zhonghe-Xinlu Line", "#ff8c00"),
    ("BL", u"Bannan Line", "#007ec7"), ("Y", u"Circular Line", "#ffd900"),
    ("A", u"Taoyuan Airport MRT", "#d4cde7"), ("V", u"Danhai LRT", "#FEBEB5"),
    ("K", u"Ankeng LRT", "#c3b091"), ("LB", u"Sanying Line", "#6DB7D0"),
]
NAMED = {"orange": "#ff8c00", "red": "#ff0000", "blue": "#0000ff"}


def rgb(c):
    c = str(NAMED.get(str(c).lower(), c)).lstrip("#")
    if len(c) != 6:
        return INK_3
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def build_map():
    """Draw data/mc_lines.json directly.

    It is the same alignment the world is generated from, not a separate drawing.
    """
    lines = json.load(open(os.path.join(REPO, "data/mc_lines.json"), encoding="utf-8"))
    with open(os.path.join(REPO, "data/mc_stations.csv"), encoding="utf-8") as fh:
        stations = list(csv.DictReader(fh))

    xs = [p[0] for vs in lines.values() for v in vs for p in v["points"]]
    zs = [p[1] for vs in lines.values() for v in vs for p in v["points"]]
    x0, x1, z0, z1 = min(xs), max(xs), min(zs), max(zs)
    iw, ih = MAP_W - 2 * MAP_PAD, MAP_H - 2 * MAP_PAD - MAP_BOTTOM
    s = min(iw / float(x1 - x0), ih / float(z1 - z0))      # Meters -> pixels.
    ox = MAP_PAD + (iw - (x1 - x0) * s) / 2
    oz = MAP_PAD + (ih - (z1 - z0) * s) / 2

    def pt(x, z):
        return (ox + (x - x0) * s, oz + (z - z0) * s)

    # Flat paper, as the guide's chart styles have it: a per-pixel tooth
    # would take the PNG from 0.1 MB to 2.6 MB.
    im = paper(MAP_W, MAP_H, rules=False, margin=False, tooth=False)
    d = ImageDraw.Draw(im)
    # Lay a paper-colored outline first, so lines stay distinct where they cross.
    for w, colorize in ((9, False), (5, True)):
        for variants in lines.values():
            for v in variants:
                c = rgb(v.get("colour")) if colorize else PAPER
                d.line([pt(x, z) for x, z in v["points"]], fill=c, width=w, joint="curve")

    for st in stations:
        px, pz = pt(int(st["mc_x"]), int(st["mc_z"]))
        d.ellipse([px - 3.5, pz - 3.5, px + 3.5, pz + 3.5], fill=PAPER, outline=INK_2, width=2)
    label = face(24, informal=0)
    for st in stations:
        if st["ref"].startswith("R10"):          # Taipei Main Station = the projection origin.
            px, pz = pt(int(st["mc_x"]), int(st["mc_z"]))
            d.ellipse([px - 9, pz - 9, px + 9, pz + 9], outline=INK, width=3)
            # The centre is crowded, so the label stands off in the clear
            # space above, joined to the ring by a leader.
            lx, lz = px + 70, pz - 200
            d.line([(px + 5, pz - 8), (lx - 6, lz + 6)], fill=INK_2, width=2)
            d.text((lx, lz), u"Taipei Main Station", font=label, fill=INK, anchor="ls")
            break

    lx, ly = MAP_PAD, MAP_H - MAP_PAD - MAP_BOTTOM + 60
    for i, (code, name, col) in enumerate(LEGEND):
        cx, cy = lx + (i % 5) * 372, ly + (i // 5) * 48
        d.line([(cx, cy - 8), (cx + 30, cy - 8)], fill=rgb(col), width=6)
        d.text((cx + 44, cy), u"%s  %s" % (code, name), font=label, fill=INK, anchor="ls")

    bar = 5000 * s                                # The scale bar is 5000 blocks in the world.
    bx, by = MAP_W - MAP_PAD - bar, MAP_PAD + 20
    d.line([(bx, by), (bx + bar, by)], fill=INK_2, width=3)
    for e in (bx, bx + bar):
        d.line([(e, by - 8), (e, by + 8)], fill=INK_2, width=3)
    d.text((bx + bar / 2, by + 40), "5 km", font=label, fill=INK_2, anchor="ms")

    im.save(os.path.join(DEMO, "network-map.png"))
    print("network-map.png (%.2f px/m)" % s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=("stills", "video", "gif", "map"),
                    help="run only this step")
    a = ap.parse_args()
    ensure_raqm()
    os.makedirs(WORK, exist_ok=True)
    steps = [a.only] if a.only else ["stills", "video", "gif", "map"]
    if any(s != "map" for s in steps):
        need_raw()
    for name in steps:
        {"stills": build_stills, "video": build_video,
         "gif": build_gif, "map": build_map}[name]()


if __name__ == "__main__":
    sys.exit(main())
