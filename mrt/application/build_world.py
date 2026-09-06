#!/usr/bin/env python3
"""地形與縱斷面的生成服務。

整片地形放不進記憶體，所以按 region (512x512 方塊) 分批：
把取樣點依 region 分桶，逐 region 生地形、蓋結構、寫檔、釋放。

地形只生成在路線走廊內，外緣用距離場漸變回平坦海平面，
免得走廊邊界出現一道垂直懸崖。

串流分批的邏輯與組合根在 cli/build_world.py —— 這裡只留可重用的部分：
縱斷面規劃 (profile)、走廊漸變場 (blend_field)、地形 chunk 組裝 (terrain_chunk)。

terrain_chunk 的第一個參數 ch 是 ports.block_sink.ChunkSink。
"""
import math

import numpy as np

from mrt import config
from mrt.application import build_line as BL
from mrt.domain.alignment import STEP
from mrt.domain.terrain import SEA_Y

OFFSET   = {"bridge": 13, "ground": 1, "tunnel": -20}   # 走行面相對地面

# 每條線各給一個埋深。全部塞在同一層的話，台北車站、忠孝復興這類交會點
# 兩條線的隧道與站體會直接互相打通，變成一個上百公尺寬的大空洞。
#
# 埋深不是隨便挑的：先把各線地下段格化成 60 m 網格算出實際交會關係
#   G-O, O-R, BL-G, G-R, BL-R, G-Y
# 再對這張圖做三著色，讓每一對真的會交叉的路線落在不同層。
# 出入口樓梯每降 1 m 要 2 m 水平距離，最深那條線因此有一段 76 m 的長梯；
# 樓梯走在站體外側 off 13~17，不受月台長度限制。
# 站體現在是「月台層 + 穿堂層」的雙層箱涵，dy -2~10 共 13 格高，
# 所以層距要 15 m 才不會互相咬到（舊的 10 m 只夠單層月台）。
# 隧道深度不再是每條線一個常數 —— 見 tunnel_layers.py。
# 每條線平常走最淺的帶，只有在要穿越別條線的地方才潛下去，
# 所以全網六成五的隧道停在地下 15 m，而不是整條線陪著最深的交會點一起挖。
# 這個常數只在 assign_bands() 沒給結果時當退路。
TUNNEL_FALLBACK = -20
SMOOTH_M = 400        # 縱斷面先平滑掉幾百公尺內的地形雜訊
FLAT_Y   = SEA_Y + 2  # 走廊外的預設地面，與 level.dat 的超平坦一致。
                      # 必須高於海平面，否則漸變區會整圈被判成海灘鋪成沙子。
BLEND_CELL = 8        # 距離場解析度（公尺）

BEDROCK, STONE, DIRT = "minecraft:bedrock", "minecraft:stone", "minecraft:dirt"
GRASS, SAND, WATER, AIR = ("minecraft:grass_block", "minecraft:sand",
                           "minecraft:water", "minecraft:air")


def moving_avg(a, win):
    if win < 2 or len(a) < win:
        return np.asarray(a, dtype=np.float64)
    pad = win // 2
    ext = np.concatenate([np.full(pad, a[0]), a, np.full(pad, a[-1])])
    return np.convolve(ext, np.ones(win) / win, mode="same")[pad:pad + len(a)]


def profile(samples, terr, ref=None, band=None):
    """跟著真實地面的縱斷面，受最大坡度限制。

    band 是 tunnel_layers.assign_bands() 給的逐點深度帶（-1 表示不是地下段）。
    換帶處會被下面的坡度包絡線自動拉成一段 4% 的斜坡，不必另外處理 ——
    15 m 的帶距剛好對應 375 m 的潛降段，跟真實的立體交會差不多長。
    """
    xs = np.array([s[0] for s in samples]); zs = np.array([s[1] for s in samples])
    ground = terr.y_at(xs, zs)
    g = moving_avg(ground.astype(np.float64), int(SMOOTH_M / STEP))
    kinds = [s[4] for s in samples]
    base = np.array([OFFSET.get(k, 1) for k in kinds], dtype=np.float64)
    if band is not None:
        base = np.where(np.asarray(band) >= 0, TL.band_depth(band), base)
    else:
        base = np.where(np.array([k == "tunnel" for k in kinds]),
                        TUNNEL_FALLBACK, base)
    tgt = g + base
    y = tgt.copy()
    d = BL.MAX_GRADE * STEP
    for i in range(1, len(y)):                       # 下包絡線，兩次線性掃描
        if y[i] > y[i - 1] + d: y[i] = y[i - 1] + d
    for i in range(len(y) - 2, -1, -1):
        if y[i] > y[i + 1] + d: y[i] = y[i + 1] + d
    return np.round(y).astype(int), ground


def _runs(mask, min_len):
    """把 True 的區段抓出來，太短的丟掉（前後的空隙一併吸收進來）。"""
    out, i, n = [], 0, len(mask)
    while i < n:
        if not mask[i]:
            i += 1
            continue
        j = i
        gap = 0
        while j < n and gap < min_len // 2:
            gap = 0 if mask[j] else gap + 1
            j += 1
        j -= gap
        if j - i >= min_len:
            out.append((i, j))
        i = j + gap + 1
    return out


def blend_field(pts, rx, rz, inner, outer):
    """region 內每格到路線的距離 -> 地形權重 (1 = 完整地形, 0 = 平坦)。"""
    ox, oz = rx * 512, rz * 512
    n = 512 // BLEND_CELL
    g = (np.arange(n) + 0.5) * BLEND_CELL
    GZ, GX = np.meshgrid(oz + g, ox + g, indexing="ij")
    d2 = np.full((n, n), 1e18)
    for sx, sz in pts:
        np.minimum(d2, (GX - sx) ** 2 + (GZ - sz) ** 2, out=d2)
    d = np.sqrt(d2)
    return np.clip((outer - d) / max(1.0, outer - inner), 0.0, 1.0)


def terrain_chunk(ch, cx, cz, terr, blend, rx, rz):
    """用 numpy 一次組出整個 chunk 的地形。"""
    xs = np.arange(cx * 16, cx * 16 + 16)
    zs = np.arange(cz * 16, cz * 16 + 16)
    ZZ, XX = np.meshgrid(zs, xs, indexing="ij")
    H = terr.y_at(XX, ZZ).astype(np.float64)

    if blend is not None:
        bi = ((XX - rx * 512) // BLEND_CELL).clip(0, blend.shape[1] - 1)
        bj = ((ZZ - rz * 512) // BLEND_CELL).clip(0, blend.shape[0] - 1)
        f = blend[bj.astype(int), bi.astype(int)]
        H = H * f + FLAT_Y * (1 - f)
    H = np.round(H).astype(np.int32)

    names = [AIR, BEDROCK, STONE, DIRT, GRASS, SAND, WATER]
    A, B, S, D, G, SD, W = range(7)
    for sy in range(config.SEC_MIN, config.SEC_MAX + 1):
        yy = np.arange(16).reshape(16, 1, 1) + sy * 16
        H3 = H[None, :, :]
        beach = H3 <= SEA_Y + 1
        code = np.where(yy > H3, A,
               np.where(yy == H3, np.where(beach, SD, G),
               np.where(yy >= H3 - 3, np.where(beach, SD, D), S)))
        code = np.where((yy > H3) & (yy <= SEA_Y), W, code)      # 海平面以下灌水
        code = np.where(yy == -64, B, code)
        if (code != A).any():
            ch.set_section(sy, code, names)
