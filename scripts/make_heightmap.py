#!/usr/bin/env python3
"""把 DEM 重新取樣成 Minecraft 座標系的高程網格 -> data/heightmap.npy

高程來源有兩個，優先序不同：

  1. 內政部國土測繪中心 20 m DTM（data/dem/nlsc20/）—— 主要來源。
     這是「數值地形模型」，房屋與樹冠都已濾除，是真正的地面。
     原生就是 TWD97 / TM2 二度分帶（EPSG:3826），跟本專案的座標系同源，
     所以完全不需要重投影，只是平移 + 雙線性內插。
  2. Copernicus GLO-30（data/dem/copernicus/）—— 只用來補雙北以外的空缺
     （機場捷運西段進入桃園）。它是 DSM，建物與樹冠都烘在高程裡，
     所以會先扣掉與 DTM 的系統性偏差，再在交界處做羽化混合，避免出現斷崖。

輸出是以台北車站為原點、20 m 間距的 int16 網格（單位公尺，海平面 = 0）。

用法: ./.venv/bin/python scripts/make_heightmap.py [--step 20]
"""
import os, io, json, glob, zipfile, argparse
os.environ.setdefault("PROJ_NETWORK", "OFF")
import numpy as np, rasterio
from rasterio.merge import merge
from pyproj import Transformer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OE, ON = 302214.8, 2770999.4          # 台北車站 TWD97，與 to_minecraft.py 同源
SEA_Y = 62                            # 海平面對應的 Minecraft y
NLSC_STEP = 20                        # 國土測繪中心格網間距
FEATHER = 20                          # 羽化半徑（格），20 格 = 400 m

TO_LL = Transformer.from_crs("EPSG:3826", "EPSG:4326", always_xy=True)


def bilinear(arr, col, row):
    """對 arr 做雙線性取樣；col/row 為浮點索引"""
    h, w = arr.shape
    c0 = np.clip(np.floor(col).astype(np.int64), 0, w - 2)
    r0 = np.clip(np.floor(row).astype(np.int64), 0, h - 2)
    fc, fr = col - c0, row - r0
    fc = np.clip(fc, 0, 1); fr = np.clip(fr, 0, 1)
    v00 = arr[r0, c0];     v01 = arr[r0, c0 + 1]
    v10 = arr[r0 + 1, c0]; v11 = arr[r0 + 1, c0 + 1]
    return (v00 * (1 - fc) * (1 - fr) + v01 * fc * (1 - fr)
            + v10 * (1 - fc) * fr + v11 * fc * fr)


def box_blur(a, r):
    """用累積和做的方形均值濾波，用來把有效遮罩羽化成混合權重"""
    if r <= 0:
        return a
    out = a
    for axis in (0, 1):
        n = out.shape[axis]
        cs = np.cumsum(np.concatenate(
            [np.zeros((1,) + out.shape[1:]) if axis == 0 else np.zeros((out.shape[0], 1)),
             out], axis=axis), axis=axis)
        idx = np.arange(n)
        lo = np.clip(idx - r, 0, n)
        hi = np.clip(idx + r + 1, 0, n)
        take = (lambda c, i: c[i]) if axis == 0 else (lambda c, i: c[:, i])
        out = (take(cs, hi) - take(cs, lo)) / (hi - lo).reshape(
            (-1, 1) if axis == 0 else (1, -1))
    return out


def _grd_blobs(d):
    """產出 (檔名, bytes)。直接讀 .zip，免得為了一次性的高程計算
    在 repo 裡長期攤開 170 MB 的 ASCII 圖幅。散落的 .grd 也照收。"""
    for zp in sorted(glob.glob(os.path.join(d, "*.zip"))):
        with zipfile.ZipFile(zp) as z:
            for n in sorted(z.namelist()):
                if n.lower().endswith(".grd"):
                    yield os.path.basename(n), z.read(n)
    for f in sorted(glob.glob(os.path.join(d, "**", "*.grd"), recursive=True)):
        yield os.path.basename(f), open(f, "rb").read()


def load_nlsc(d):
    """讀入所有 .grd（ASCII 的 E N Z），散佈到一張共同的 20 m 格網上。

    不假設檔案內的排列順序，直接用座標算索引，所以圖幅缺角或順序不同都不會錯位。
    """
    cols, names = [], set()
    for name, blob in _grd_blobs(d):
        if name in names:            # zip 與散落檔重複時只取一份
            continue
        names.add(name)
        a = np.fromstring(blob.decode("ascii"), sep=" ")
        if a.size % 3:
            raise SystemExit(f"{name} 欄數不是 3 的倍數")
        cols.append(a.reshape(-1, 3))
    if not cols:
        return None, None, None
    print(f"NLSC 20 m DTM：{len(cols)} 幅")
    pts = np.concatenate(cols)
    del cols

    E, N, Z = pts[:, 0], pts[:, 1], pts[:, 2]
    bad = (Z < -50) | (Z > 4000)          # 濾掉無資料哨兵值
    if bad.any():
        print(f"  濾除異常高程 {bad.sum():,} 點")
        E, N, Z = E[~bad], N[~bad], Z[~bad]

    e0, e1 = E.min(), E.max()
    n0, n1 = N.min(), N.max()
    nx = int((e1 - e0) / NLSC_STEP) + 1
    nz = int((n1 - n0) / NLSC_STEP) + 1
    print(f"  範圍 E[{e0:.0f},{e1:.0f}] N[{n0:.0f},{n1:.0f}]"
          f"  = {(e1-e0)/1000:.1f} x {(n1-n0)/1000:.1f} km  格網 {nz}x{nx}")

    grid = np.full((nz, nx), np.nan, dtype=np.float32)
    ci = np.rint((E - e0) / NLSC_STEP).astype(np.int64)
    ri = np.rint((N - n0) / NLSC_STEP).astype(np.int64)
    grid[ri, ci] = Z
    filled = np.isfinite(grid)
    print(f"  {len(Z):,} 點，格網填滿率 {100*filled.mean():.1f}%"
          f"，高程 {np.nanmin(grid):.1f}~{np.nanmax(grid):.1f} m")
    return grid, (e0, n0), filled


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", type=int, default=20, help="網格間距（公尺）")
    ap.add_argument("--margin", type=int, default=600, help="路網外擴（公尺）")
    a = ap.parse_args()

    # 涵蓋範圍取自實際路網
    lines = json.load(open(os.path.join(ROOT, "data", "mc_lines.json")))
    xs, zs = [], []
    for vs in lines.values():
        for v in vs:
            for x, z in v["points"]:
                xs.append(x); zs.append(z)
    x0, x1 = min(xs) - a.margin, max(xs) + a.margin
    z0, z1 = min(zs) - a.margin, max(zs) + a.margin
    print(f"涵蓋 MC X[{x0},{x1}] Z[{z0},{z1}]  = {(x1-x0)/1000:.1f} x {(z1-z0)/1000:.1f} km")

    gx = np.arange(x0, x1 + a.step, a.step)
    gz = np.arange(z0, z1 + a.step, a.step)
    GX, GZ = np.meshgrid(gx, gz)
    E = GX + OE
    N = ON - GZ

    # --- 1. NLSC DTM（主要來源，原生 EPSG:3826，直接平移取樣）---
    nl, org, _ = load_nlsc(os.path.join(ROOT, "data", "dem", "nlsc20"))
    if nl is None:
        raise SystemExit("data/dem/nlsc20/ 下沒有 .grd")
    e0, n0 = org
    col = (E - e0) / NLSC_STEP
    row = (N - n0) / NLSC_STEP
    inside = (col >= 0) & (col <= nl.shape[1] - 1.001) & \
             (row >= 0) & (row <= nl.shape[0] - 1.001)
    ok = np.nan_to_num(nl, nan=0.0)
    msk = np.isfinite(nl).astype(np.float32)
    v = bilinear(ok, np.clip(col, 0, nl.shape[1] - 1.001),
                 np.clip(row, 0, nl.shape[0] - 1.001))
    wt = bilinear(msk, np.clip(col, 0, nl.shape[1] - 1.001),
                  np.clip(row, 0, nl.shape[0] - 1.001))
    good = inside & (wt > 0.99)
    dtm = np.where(good, v / np.where(wt > 0, wt, 1), np.nan)
    print(f"DTM 覆蓋路網範圍 {100*good.mean():.1f}%")

    # --- 2. Copernicus DSM（補空缺）---
    tifs = sorted(glob.glob(os.path.join(ROOT, "data", "dem", "copernicus", "*.tif"))) \
        or sorted(glob.glob(os.path.join(ROOT, "data", "dem", "*.tif")))
    srcs = [rasterio.open(t) for t in tifs]
    mosaic, tf = merge(srcs)
    cop = mosaic[0].astype(np.float32)
    nod = srcs[0].nodata
    if nod is not None:
        cop[cop == nod] = 0.0
    lon, lat = TO_LL.transform(E, N)
    cc, rr = (~tf) * (lon, lat)
    dsm = bilinear(cop, np.asarray(cc), np.asarray(rr))
    print(f"Copernicus DSM 鑲嵌 {cop.shape}（{len(tifs)} 幅）")

    # DSM 系統性偏高（建物 + 樹冠 + 基準差），先扣掉中位數偏差再拿來補
    diff = (dsm - dtm)[good]
    bias = float(np.median(diff))
    print(f"DSM - DTM：中位數 {bias:+.2f} m，"
          f"平均 {np.mean(diff):+.2f} m，"
          f"90 分位 {np.percentile(diff,90):+.2f} m，最大 {diff.max():+.2f} m")

    # --- 3. 羽化混合，交界不出現斷崖 ---
    w = box_blur(good.astype(np.float64), FEATHER)
    w = np.clip(w, 0, 1)
    fill = dsm - bias
    hm_f = np.where(good, np.nan_to_num(dtm) * w + fill * (1 - w), fill)
    n_fill = int((~good).sum())
    print(f"以 DSM 補的格點 {n_fill:,}（{100*n_fill/good.size:.1f}%），"
          f"交界羽化半徑 {FEATHER*a.step} m")

    hm = np.round(hm_f).astype(np.int16)
    np.save(os.path.join(ROOT, "data", "heightmap.npy"), hm)
    meta = dict(x0=int(x0), z0=int(z0), step=int(a.step),
                nx=int(len(gx)), nz=int(len(gz)), sea_y=SEA_Y,
                primary="NLSC 20m DTM (TWD97/TM2, TWVD2001)",
                fallback=[os.path.basename(t) for t in tifs],
                dsm_bias=round(bias, 3), dtm_coverage=round(float(good.mean()), 4))
    json.dump(meta, open(os.path.join(ROOT, "data", "heightmap.json"), "w"),
              indent=1, ensure_ascii=False)

    print(f"\n網格 {hm.shape}  高程 {hm.min()}~{hm.max()} m")
    for q in (1, 25, 50, 75, 95, 99, 99.9):
        print(f"  {q:>5}% 分位: {np.percentile(hm, q):>7.1f} m  -> y={SEA_Y+np.percentile(hm,q):.0f}")
    over = (hm.astype(np.int32) + SEA_Y > 319).sum()
    print(f"超過 y=319 上限的格點: {over} ({100*over/hm.size:.3f}%)")


if __name__ == "__main__":
    main()
