#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把兩段原始遊戲錄影剪成 README 用的示範素材。

原始錄影是 macOS 的螢幕錄影（1932x1240，畫面裡有視窗外框），沒有進版控 ——
太大了（928 MB）。這支腳本是它們與 repo 裡那幾個檔案之間的唯一連結：
影片剪哪幾段、字幕寫什麼、圖從第幾秒抓，全部寫在這裡，不是手工調出來的。

    ./.venv/bin/python demo/make_demo.py            # 重做 demo/ 下所有素材
    ./.venv/bin/python demo/make_demo.py --only map # 只重畫全網圖

產出：
    hero.gif          README 最上面的動圖（日落時的隧道剖面）
    tour.mp4          56 秒示範影片，含標題卡與字幕
    tour-thumb.jpg    影片封面（README 上點下去會開影片）
    network-map.png   全網示意圖，直接畫投影後的線形資料
    platform / sign / tunnel / concourse / cutaway / sunset .jpg   六張特寫

需要 ffmpeg（這台機器的 ffmpeg 沒編 libfreetype，所以字都用 PIL 畫成
PNG 再疊上去，不是 drawtext）與 pillow、numpy。
"""
import argparse
import csv
import json
import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

DEMO = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(DEMO)
WORK = os.path.join(DEMO, ".work")          # 中間檔，不進版控
RAW1 = os.path.join(DEMO, "raw-1.mov")
RAW2 = os.path.join(DEMO, "raw-2.mov")

TTF = "/System/Library/Fonts/STHeiti Medium.ttc"     # Heiti TC
TTF_L = "/System/Library/Fonts/STHeiti Light.ttc"

CROP = "crop=1704:956:114:133"      # 去掉 macOS 視窗外框，只留遊戲畫面
SCALE = "scale=1280:720:flags=lanczos,setsar=1"
FPS = 30
XFADE = 0.5

EQ_DARK = "eq=brightness=0.05:contrast=1.10:saturation=1.12"   # 地下，偏暗
EQ_SKY = "eq=contrast=1.06:saturation=1.10"                    # 有天空的
EQ_SUNSET = "eq=contrast=1.05:saturation=1.12"

W, H = 1280, 720
LINE_COLORS = [(198, 132, 44), (227, 0, 44), (0, 134, 89),
               (248, 182, 28), (0, 112, 189), (255, 219, 0)]

# 影片鏡頭：(來源, 起點秒, 長度秒, 調色, 字幕鍵)
SHOTS = [
    (RAW2, 176.0, 11.0, EQ_SKY,  "xray"),
    (RAW1,  51.0,  7.5, EQ_SUNSET, "sunset"),
    (RAW2,  40.0, 11.5, EQ_DARK, "tunnel"),
    (RAW2,  25.0,  9.0, EQ_DARK, "platform"),
    (RAW2, 197.0,  7.0, EQ_DARK, "concourse"),
    (RAW2, 212.5,  7.5, EQ_DARK, None),
]

# 字幕：鍵 -> (大字, 小字, 色條顏色)
CAPTIONS = {
    "xray":      (u"隧道剖面", u"把地表切掉：線形一路延伸到天際線", (255, 219, 0)),
    "sunset":    (u"1 方塊 = 1 公尺", u"482 km² 的範圍，不可能手工堆", (227, 0, 44)),
    "tunnel":    (u"地下段", u"雙線隧道，全網鐵軌相通", (198, 132, 44)),
    "platform":  (u"島式月台", u"月台門邊的黃色警示帶、站名告示牌", (0, 134, 89)),
    "concourse": (u"穿堂層與轉乘通道", u"從街上任何一座出入口都走得到月台", (248, 182, 28)),
}

# 特寫：檔名 -> (來源, 秒數, 調色)
STILLS = {
    "platform":  (RAW2, 216.5, EQ_DARK),
    "sign":      (RAW2,  29.5, EQ_DARK),
    "tunnel":    (RAW2,  45.0, EQ_DARK),
    "concourse": (RAW2, 200.0, EQ_DARK),
    "cutaway":   (RAW2, 103.0, EQ_SKY),
    "sunset":    (RAW1,  54.5, EQ_SUNSET),
}

# hero.gif 取的那一段：日落時的隧道剖面，5 秒剛好 2.5 MB
HERO = (RAW1, 52.0, 5.0, EQ_SUNSET)


def run(cmd):
    subprocess.run(cmd, check=True)


def font(size, light=False):
    return ImageFont.truetype(TTF_L if light else TTF, size, index=0)


def need_raw():
    missing = [p for p in (RAW1, RAW2) if not os.path.exists(p)]
    if missing:
        raise SystemExit("缺少原始錄影：%s（沒有進版控，要跟作者要）"
                         % "、".join(os.path.basename(p) for p in missing))


# --------------------------------------------------------------------------
# 圖層：標題卡、字幕、封面
# --------------------------------------------------------------------------

def text(d, xy, s, f, fill, off=3):
    d.text((xy[0] + off, xy[1] + off), s, font=f, fill=(0, 0, 0, 190))
    d.text(xy, s, font=f, fill=fill)


def width_of(d, s, f):
    return d.textbbox((0, 0), s, font=f)[2]


def color_bar(d, y, h):
    seg = W / float(len(LINE_COLORS))
    for i, c in enumerate(LINE_COLORS):
        d.rectangle([i * seg, y, (i + 1) * seg, y + h], fill=c + (255,))


def backdrop(still, dim, blur):
    """拿一張遊戲截圖當底：壓暗、輕微模糊，字才壓得住。"""
    im = Image.open(os.path.join(WORK, still)).convert("RGB")
    im = im.resize((W, H), Image.LANCZOS).filter(ImageFilter.GaussianBlur(blur))
    return ImageEnhance.Brightness(im).enhance(dim).convert("RGBA")


def title_card():
    im = backdrop("still_sunset.png", 0.42, 2.0)
    d = ImageDraw.Draw(im)
    color_bar(d, 0, 10)
    color_bar(d, H - 10, 10)
    f1, f2, f3 = font(104), font(46), font(28, light=True)
    s = u"台北捷運"
    text(d, ((W - width_of(d, s, f1)) // 2, 222), s, f1, (255, 255, 255, 255))
    s = u"Minecraft 1:1 重建"
    text(d, ((W - width_of(d, s, f2)) // 2, 350), s, f2, (150, 205, 255, 255))
    d.line([(W // 2 - 190, 430), (W // 2 + 190, 430)], fill=(90, 100, 115, 255), width=2)
    s = u"1 方塊 = 1 公尺   ·   482 km²   ·   全部程式化生成"
    text(d, ((W - width_of(d, s, f3)) // 2, 456), s, f3, (200, 210, 220, 255))
    return im


def end_card():
    im = backdrop("still_tunnel.png", 0.33, 3.0)
    d = ImageDraw.Draw(im)
    color_bar(d, 0, 10)
    color_bar(d, H - 10, 10)
    f1, f2, f3 = font(40), font(30, light=True), font(26)
    rows = [
        (u"193 座車站", u"地下島式月台、高架與平面側式月台，都有穿堂層與驗票閘門"),
        (u"476 座出入口", u"開在真實位置、掛真實編號；每一座都走得到月台"),
        (u"8.9 km 地下街", u"台北車站一帶，照 OSM 的室內動線蓋"),
    ]
    y = 168
    for head, sub in rows:
        d.rectangle([210, y + 6, 216, y + 44], fill=(0, 112, 189, 255))
        text(d, (240, y), head, f1, (255, 255, 255, 255))
        text(d, (240, y + 52), sub, f2, (170, 180, 192, 255))
        y += 128
    s = "github.com/rareone0602/taipei-mrt-minecraft"
    text(d, ((W - width_of(d, s, f3)) // 2, 588), s, f3, (150, 205, 255, 255))
    return im


def caption_layer(head, sub, accent):
    """左下角字幕：色條 + 大字 + 小字，底下鋪一層由下而上的暗角。"""
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    top = 470
    for y in range(top, H):
        a = int(150 * ((y - top) / float(H - top)) ** 1.5)
        gd.line([(0, y), (W, y)], fill=(0, 0, 0, a))
    im = Image.alpha_composite(im, grad)
    d = ImageDraw.Draw(im)
    x, y = 72, 574
    d.rectangle([x, y + 8, x + 7, y + 46], fill=accent + (255,))
    text(d, (x + 26, y), head, font(42), (255, 255, 255, 255))
    text(d, (x + 26, y + 56), sub, font(26, light=True), (198, 208, 218, 255))
    return im


def thumbnail():
    """影片封面：README 上點下去會開影片，所以要一眼看得出是影片。"""
    im = Image.open(os.path.join(WORK, "still_platform.png")).convert("RGB")
    im = im.resize((W, H), Image.LANCZOS).filter(ImageFilter.GaussianBlur(1.2))
    im = ImageEnhance.Brightness(im).enhance(0.52)
    d = ImageDraw.Draw(im, "RGBA")
    seg = W / float(len(LINE_COLORS))
    for i, c in enumerate(LINE_COLORS):
        d.rectangle([i * seg, 0, (i + 1) * seg, 9], fill=c)
        d.rectangle([i * seg, H - 9, (i + 1) * seg, H], fill=c)
    cx, cy, r = W // 2, 322, 76
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, 235))
    d.polygon([(cx - 24, cy - 38), (cx - 24, cy + 38), (cx + 40, cy)], fill=(18, 20, 26))
    for s, y, f, fill in ((u"台北捷運 · Minecraft 1:1 重建", 452, font(46), (255, 255, 255)),
                          (u"56 秒示範影片：隧道、月台、穿堂、轉乘通道", 520,
                           font(26, light=True), (205, 214, 224))):
        text(d, ((W - width_of(d, s, f)) // 2, y), s, f, fill, off=2)
    im.save(os.path.join(DEMO, "tour-thumb.jpg"), quality=88)
    print("  tour-thumb.jpg")


# --------------------------------------------------------------------------
# 影格
# --------------------------------------------------------------------------

def grab(src, ss, eq, out, width=1280, png=False):
    vf = "%s,%s,scale=%d:-2:flags=lanczos" % (CROP, eq, width)
    cmd = ["ffmpeg", "-v", "error", "-y", "-ss", str(ss), "-i", src,
           "-frames:v", "1", "-vf", vf]
    if not png:
        cmd += ["-q:v", "3"]
    run(cmd + [out])


def build_stills():
    """六張 README 特寫，順便留一份原尺寸 PNG 給標題卡當底。"""
    print("特寫：")
    for name, (src, ss, eq) in STILLS.items():
        grab(src, ss, eq, os.path.join(DEMO, name + ".jpg"))
        print("  %s.jpg" % name)
    for name in ("sunset", "tunnel", "platform"):
        src, ss, eq = STILLS[name]
        grab(src, ss, eq, os.path.join(WORK, "still_%s.png" % name),
             width=1704, png=True)


def build_cards():
    print("圖卡：")
    title_card().save(os.path.join(WORK, "title.png"))
    end_card().save(os.path.join(WORK, "end.png"))
    for key, (head, sub, accent) in CAPTIONS.items():
        caption_layer(head, sub, accent).save(os.path.join(WORK, "cap_%s.png" % key))
    print("  title / end / %d 張字幕" % len(CAPTIONS))
    thumbnail()


# --------------------------------------------------------------------------
# 影片
# --------------------------------------------------------------------------

def render_card(png, dur, out, fade_in=True):
    vf = "%s,fps=%d,format=yuv420p" % (SCALE, FPS)
    if fade_in:
        vf = "fade=in:st=0:d=0.5," + vf
    run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-t", str(dur), "-i", png,
         "-vf", vf, "-c:v", "libx264", "-preset", "slow", "-crf", "18", out])


def render_shot(src, ss, dur, eq, cap, out):
    vf = "%s,%s,%s,fps=%d" % (CROP, eq, SCALE, FPS)
    if cap is None:
        run(["ffmpeg", "-v", "error", "-y", "-ss", str(ss), "-t", str(dur), "-i", src,
             "-vf", vf + ",format=yuv420p", "-an",
             "-c:v", "libx264", "-preset", "slow", "-crf", "18", out])
        return
    png = os.path.join(WORK, "cap_%s.png" % cap)
    fc = ("[0:v]%s[v];"
          "[1:v]format=rgba,fade=in:st=0.5:d=0.5:alpha=1,"
          "fade=out:st=%.2f:d=0.6:alpha=1[c];"
          "[v][c]overlay=0:0:shortest=1,format=yuv420p[o]" % (vf, dur - 1.6))
    run(["ffmpeg", "-v", "error", "-y", "-ss", str(ss), "-t", str(dur), "-i", src,
         "-loop", "1", "-t", str(dur), "-i", png,
         "-filter_complex", fc, "-map", "[o]", "-an",
         "-c:v", "libx264", "-preset", "slow", "-crf", "18", out])


def build_video():
    print("影片：")
    parts = []
    p = os.path.join(WORK, "00_title.mp4")
    render_card(os.path.join(WORK, "title.png"), 2.8, p)
    parts.append((p, 2.8))
    for i, (src, ss, dur, eq, cap) in enumerate(SHOTS):
        p = os.path.join(WORK, "%02d_%s.mp4" % (i + 1, cap or "plain"))
        render_shot(src, ss, dur, eq, cap, p)
        parts.append((p, dur))
        print("  鏡頭 %d：%s +%.1fs" % (i + 1, os.path.basename(src), dur))
    p = os.path.join(WORK, "99_end.mp4")
    render_card(os.path.join(WORK, "end.png"), 3.6, p, fade_in=False)
    parts.append((p, 3.6))

    # 交叉溶接：每接一段，總長就少一個 XFADE
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
    fc.append("%sformat=yuv420p,fade=out:st=%.2f:d=0.8[o]" % (cur, acc - 0.8))
    out = os.path.join(DEMO, "tour.mp4")
    run(["ffmpeg", "-v", "error", "-y"] + inputs +
        ["-filter_complex", ";".join(fc), "-map", "[o]",
         "-c:v", "libx264", "-preset", "slow", "-crf", "25", "-tune", "animation",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", out])
    print("  tour.mp4（%.1f 秒）" % acc)


def build_gif():
    """GIF 沒有影格間壓縮，所以只給 5 秒、560 px、12 fps —— 再多就破 3 MB。"""
    src, ss, dur, eq = HERO
    vf = ("%s,%s,fps=12,scale=560:-1:flags=lanczos,split[a][b];"
          "[a]palettegen=max_colors=200:stats_mode=diff[p];"
          "[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle" % (CROP, eq))
    out = os.path.join(DEMO, "hero.gif")
    run(["ffmpeg", "-v", "error", "-y", "-ss", str(ss), "-t", str(dur), "-i", src,
         "-vf", vf, "-loop", "0", out])
    print("hero.gif（%.1f MB）" % (os.path.getsize(out) / 1e6))


# --------------------------------------------------------------------------
# 全網示意圖
# --------------------------------------------------------------------------

MAP_W, MAP_H, MAP_PAD, MAP_TOP, MAP_BOTTOM = 2000, 1500, 70, 150, 130
MAP_BG = (14, 16, 21)
LEGEND = [
    ("BR", u"文湖線", "#A74C00"), ("R", u"淡水信義線", "#FF0000"),
    ("G", u"松山新店線", "#1e7b54"), ("O", u"中和新蘆線", "#ff8c00"),
    ("BL", u"板南線", "#007ec7"), ("Y", u"環狀線", "#ffd900"),
    ("A", u"機場捷運", "#d4cde7"), ("V", u"淡海輕軌", "#FEBEB5"),
    ("K", u"安坑輕軌", "#c3b091"), ("LB", u"三鶯線", "#6DB7D0"),
]
NAMED = {"orange": "#ff8c00", "red": "#ff0000", "blue": "#0000ff"}


def rgb(c):
    c = str(NAMED.get(str(c).lower(), c)).lstrip("#")
    if len(c) != 6:
        return (200, 200, 200)
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def build_map():
    """直接畫 data/mc_lines.json —— 就是拿去生成世界的那份線形，不是另外畫的。"""
    lines = json.load(open(os.path.join(REPO, "data/mc_lines.json"), encoding="utf-8"))
    with open(os.path.join(REPO, "data/mc_stations.csv"), encoding="utf-8") as fh:
        stations = list(csv.DictReader(fh))

    xs = [p[0] for vs in lines.values() for v in vs for p in v["points"]]
    zs = [p[1] for vs in lines.values() for v in vs for p in v["points"]]
    x0, x1, z0, z1 = min(xs), max(xs), min(zs), max(zs)
    iw, ih = MAP_W - 2 * MAP_PAD, MAP_H - MAP_TOP - MAP_BOTTOM
    s = min(iw / float(x1 - x0), ih / float(z1 - z0))      # 公尺 -> 像素
    ox = MAP_PAD + (iw - (x1 - x0) * s) / 2
    oz = MAP_TOP + (ih - (z1 - z0) * s) / 2

    def pt(x, z):
        return (ox + (x - x0) * s, oz + (z - z0) * s)

    im = Image.new("RGB", (MAP_W, MAP_H), MAP_BG)
    d = ImageDraw.Draw(im)
    # 先鋪一層底色描邊，線交會時才分得開
    for w, colorize in ((9, False), (5, True)):
        for variants in lines.values():
            for v in variants:
                c = rgb(v.get("colour")) if colorize else MAP_BG
                d.line([pt(x, z) for x, z in v["points"]], fill=c, width=w, joint="curve")

    for st in stations:
        px, pz = pt(int(st["mc_x"]), int(st["mc_z"]))
        d.ellipse([px - 3, pz - 3, px + 3, pz + 3], fill=(245, 245, 245), outline=MAP_BG)
    for st in stations:
        if st["ref"].startswith("R10"):          # 台北車站＝投影原點
            px, pz = pt(int(st["mc_x"]), int(st["mc_z"]))
            d.ellipse([px - 7, pz - 7, px + 7, pz + 7], outline=(255, 255, 255), width=3)
            d.text((px + 14, pz - 26), u"台北車站", font=font(20), fill=(255, 255, 255))
            break

    d.text((MAP_PAD, 46), u"台北捷運全網", font=font(52), fill=(255, 255, 255))
    d.text((MAP_PAD + 4, 112),
           u"十條營運路線 + 支線　·　1 方塊 = 1 公尺　·　線形、站點與顏色取自 OpenStreetMap",
           font=font(22, light=True), fill=(150, 160, 175))

    lx, ly, f = MAP_PAD, MAP_H - MAP_BOTTOM + 26, font(20)
    for i, (code, name, col) in enumerate(LEGEND):
        cx, cy = lx + (i % 5) * 372, ly + (i // 5) * 40
        d.rectangle([cx, cy + 6, cx + 30, cy + 12], fill=rgb(col))
        d.text((cx + 44, cy - 2), u"%s　%s" % (code, name), font=f, fill=(215, 222, 230))

    bar = 5000 * s                                # 比例尺就是世界裡的 5000 格
    bx, by = MAP_W - MAP_PAD - bar, 96
    d.line([(bx, by), (bx + bar, by)], fill=(215, 222, 230), width=3)
    for e in (bx, bx + bar):
        d.line([(e, by - 8), (e, by + 8)], fill=(215, 222, 230), width=3)
    d.text((bx + bar / 2 - 26, by + 14), "5 km", font=font(20, light=True),
           fill=(215, 222, 230))

    im.save(os.path.join(DEMO, "network-map.png"))
    print("network-map.png（%.2f px/m）" % s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=("stills", "cards", "video", "gif", "map"),
                    help="只做其中一項（video 需要先有 cards）")
    a = ap.parse_args()
    os.makedirs(WORK, exist_ok=True)
    steps = [a.only] if a.only else ["stills", "cards", "video", "gif", "map"]
    if [s for s in steps if s != "map"]:
        need_raw()
    for name in steps:
        {"stills": build_stills, "cards": build_cards, "video": build_video,
         "gif": build_gif, "map": build_map}[name]()


if __name__ == "__main__":
    sys.exit(main())
