#!/usr/bin/env python3
"""生成文湖線 (BR) 高架結構到 Minecraft 存檔。

文湖線是全線高架的中運量膠輪系統 (VAL256 / INNOVIA APM 256)，
沒有隧道也沒有地下車站 — 拿來當第一條線的垂直切片最乾淨。

比例 1 方塊 = 1 公尺。斷面 (以中心線為 0，往右為正)：

     -5  -4 -3 -2  -1 0 +1  +2 +3 +4  +5
    [牆] [ 軌 道 一 ] [中央分隔] [ 軌 道 二 ] [牆]

用法: ./.venv/bin/python -m cli.build_br [--out DIR] [--limit N]
"""
import math

GROUND    = 64          # 超平坦地表最上層方塊
DECK_TOP  = 77          # 走行面高度 (地表上 13 m，與實際文湖線相近)
PIER_EVERY = 25         # 橋墩間距 (公尺)
STEP      = 0.5         # 沿線取樣間距，夠密才不會有縫

CONC  = "minecraft:light_gray_concrete"   # 橋體混凝土
DECK  = "minecraft:smooth_stone"          # 走行面
WALL  = "minecraft:gray_concrete"         # 導引牆/欄杆
PIER  = "minecraft:polished_andesite"     # 橋墩
PLAT  = "minecraft:polished_diorite"      # 月台面
ROOF  = "minecraft:light_gray_concrete"
GLASS = "minecraft:light_gray_stained_glass_pane"
PSD   = "minecraft:glass_pane"                 # 月台門
STAIR = "minecraft:smooth_stone"               # 樓梯踏面

PLATFORM_LEN  = 70      # 4 節車廂約 55 m，月台留 70 m
PLATFORM_HALF = PLATFORM_LEN // 2


def resample(pts, step):
    """把折線重新取樣成等距點，回傳 (x, z, dx, dz) — dx,dz 為單位切線"""
    out = []
    acc = 0.0
    for i in range(len(pts) - 1):
        (x0, z0), (x1, z1) = pts[i], pts[i + 1]
        seg = math.hypot(x1 - x0, z1 - z0)
        if seg < 1e-9:
            continue
        ux, uz = (x1 - x0) / seg, (z1 - z0) / seg
        t = -acc
        while t < seg:
            if t >= 0:
                out.append((x0 + ux * t, z0 + uz * t, ux, uz))
            t += step
        acc = (acc + seg) % step
    return out


def build_viaduct(w, samples, station_zones):
    """沿線鋪高架橋面。station_zones 是 (索引下限, 索引上限) 集合，車站段月台另外處理。"""
    placed = 0
    for i, (x, z, ux, uz) in enumerate(samples):
        # 法線 = 切線轉 90 度
        nx, nz = -uz, ux
        dist_m = i * STEP

        for off in range(-5, 6):
            bx = round(x + nx * off)
            bz = round(z + nz * off)
            if off in (-5, 5):                      # 外側導引牆
                w.set(bx, DECK_TOP,     bz, CONC)
                w.set(bx, DECK_TOP + 1, bz, WALL)
                w.set(bx, DECK_TOP + 2, bz, WALL)
            elif off == 0:                          # 中央分隔
                w.set(bx, DECK_TOP,     bz, CONC)
                w.set(bx, DECK_TOP + 1, bz, WALL)
            else:                                   # 走行面
                w.set(bx, DECK_TOP, bz, DECK)
            w.set(bx, DECK_TOP - 1, bz, CONC)       # 橋面版
            placed += 1

        # 橋墩：每 PIER_EVERY 公尺一根 3x3，從地下 4 格頂到橋面版下方
        if abs(dist_m % PIER_EVERY) < STEP / 2:
            cx0, cz0 = round(x), round(z)
            for ddx in (-1, 0, 1):
                for ddz in (-1, 0, 1):
                    for y in range(GROUND - 4, DECK_TOP - 1):
                        w.set(cx0 + ddx, y, cz0 + ddz, PIER)
            # 墩帽：往兩側伸出承接橋面
            for off in range(-4, 5):
                bx = round(x + nx * off); bz = round(z + nz * off)
                w.set(bx, DECK_TOP - 2, bz, CONC)
    return placed


def build_station(w, samples, idx, name):
    """在取樣點 idx 處蓋一座側式月台高架車站（含月台門與出入口樓梯）"""
    n = len(samples)
    half = int(PLATFORM_HALF / STEP)
    lo, hi = max(0, idx - half), min(n - 1, idx + half)

    for i in range(lo, hi + 1):
        x, z, ux, uz = samples[i]
        nx, nz = -uz, ux
        end = i in (lo, hi)
        along_m = (i - lo) * STEP

        # 月台門：文湖線是全高式月台門，開口對齊車門（約每 7 m 一組，寬 2 m）
        door = (along_m % 7.0) < 2.0
        for off in (-5, 5):
            bx = round(x + nx * off); bz = round(z + nz * off)
            for y in range(DECK_TOP + 1, DECK_TOP + 4):
                w.set(bx, y, bz, "minecraft:air" if door else PSD)

        for off in list(range(-10, -5)) + list(range(6, 11)):   # 兩側月台
            bx = round(x + nx * off); bz = round(z + nz * off)
            w.set(bx, DECK_TOP - 1, bz, CONC)
            w.set(bx, DECK_TOP,     bz, PLAT)
            if abs(off) == 10 or end:                            # 外牆
                for y in range(DECK_TOP + 1, DECK_TOP + 5):
                    w.set(bx, y, bz, GLASS if 1 <= (y - DECK_TOP) <= 3 and not end else CONC)
            if abs(off) == 6:                                    # 月台邊緣警示帶
                w.set(bx, DECK_TOP, bz, "minecraft:yellow_concrete")
        for off in range(-10, 11):                               # 屋頂
            bx = round(x + nx * off); bz = round(z + nz * off)
            w.set(bx, DECK_TOP + 5, bz, ROOF)

    build_entrance(w, samples, lo, hi)
    return name


def build_entrance(w, samples, lo, hi):
    """出入口樓梯：從地面爬升到月台層。

    每階升 1 m、進 2 m（前半格半磚、後半格整塊），玩家可直接走上去不必跳。
    取樣間距是 STEP 公尺，所以位移要換算成取樣點數，不能直接用公尺當索引。
    """
    rise = DECK_TOP - GROUND
    per_m = max(1, int(round(1.0 / STEP)))     # 一公尺等於幾個取樣點
    need = rise * 2 * per_m + 2 * per_m        # 樓梯總長（取樣點數）
    start = lo + 4 * per_m
    if start + need > hi:
        start = max(0, lo - need - 4 * per_m)  # 月台段不夠長就往外接

    top_si = start
    for k in range(rise + 1):
        y = GROUND + k
        for j in (0, 1):                       # j=0 前半公尺, j=1 後半公尺
            si = start + (k * 2 + j) * per_m
            if not (0 <= si < len(samples)):
                continue
            top_si = si
            x, z, ux, uz = samples[si]
            nx, nz = -uz, ux
            for off in range(11, 14):           # 樓梯間寬 3 m，貼在月台外側
                bx = round(x + nx * off); bz = round(z + nz * off)
                w.set(bx, y, bz, "minecraft:smooth_stone_slab[type=bottom]" if j == 0 else STAIR)
                for yy in range(y + 1, y + 4):  # 頭頂淨空
                    w.set(bx, yy, bz, "minecraft:air")
                if off == 13:                   # 外側護欄
                    w.set(bx, y + 1, bz, "minecraft:iron_bars")
                    w.set(bx, y + 2, bz, "minecraft:iron_bars")

    # 樓梯頂端接進月台：補平台並在外牆打開一道門
    for si in range(max(0, top_si - per_m), min(len(samples), top_si + per_m + 1)):
        x, z, ux, uz = samples[si]
        nx, nz = -uz, ux
        for off in range(10, 14):
            bx = round(x + nx * off); bz = round(z + nz * off)
            w.set(bx, DECK_TOP, bz, STAIR)
            for yy in range(DECK_TOP + 1, DECK_TOP + 4):
                w.set(bx, yy, bz, "minecraft:air")
