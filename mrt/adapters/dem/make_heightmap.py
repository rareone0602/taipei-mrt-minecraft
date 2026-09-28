#!/usr/bin/env python3
"""Resample the DEM into an elevation grid in the Minecraft coordinate system -> data/heightmap.npy.

There are two elevation sources, with different priorities:

  1. The 20 m DTM of the National Land Surveying and Mapping Center, Ministry
     of the Interior (data/dem/nlsc20/): the primary source. It is a digital
     terrain model, with buildings and tree canopy filtered out, so it is the
     true ground surface. It is natively in TWD97 / TM2 two-degree zones
     (EPSG:3826), the same coordinate system as this project, so no
     reprojection is needed at all: only a translation plus bilinear
     interpolation.
  2. Copernicus GLO-30 (data/dem/copernicus/): used only to fill the gaps
     outside Taipei and New Taipei (the western section of the Airport MRT,
     which enters Taoyuan). It is a DSM, with buildings and tree canopy baked
     into the elevations, so its systematic offset from the DTM is subtracted
     first, and the two are feather-blended at the boundary so no cliff
     appears.

The output is an int16 grid with Taipei Main Station as its origin and a 20 m
spacing (in meters, sea level = 0).

Usage: ./.venv/bin/python -m mrt.adapters.dem.make_heightmap [--step 20]
"""
import os, json, glob, zipfile, argparse
os.environ.setdefault("PROJ_NETWORK", "OFF")
import numpy as np, rasterio
from rasterio.merge import merge
from pyproj import Transformer

from mrt import config
OE, ON = 302214.8, 2770999.4          # Taipei Main Station in TWD97; same origin as adapters/projection.py.
SEA_Y = 62                            # Minecraft y of sea level.
NLSC_STEP = 20                        # Grid spacing of the NLSC data.
FEATHER = 20                          # Feather radius in cells; 20 cells = 400 m.

TO_LL = Transformer.from_crs("EPSG:3826", "EPSG:4326", always_xy=True)


def bilinear(arr, col, row):
    """Sample arr bilinearly; col/row are floating-point indices."""
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
    """Apply a box mean filter of radius r, built from cumulative sums.

    Used to feather the valid mask into blend weights."""
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
    """Yield (file name, bytes).

    Reads the .zip files directly, so a one-off elevation computation does not
    leave 170 MB of ASCII map sheets unpacked in the repo. Loose .grd files are
    read as well."""
    for zp in sorted(glob.glob(os.path.join(d, "*.zip"))):
        with zipfile.ZipFile(zp) as z:
            for n in sorted(z.namelist()):
                if n.lower().endswith(".grd"):
                    yield os.path.basename(n), z.read(n)
    for f in sorted(glob.glob(os.path.join(d, "**", "*.grd"), recursive=True)):
        yield os.path.basename(f), open(f, "rb").read()


def load_nlsc(d):
    """Read every .grd (ASCII E N Z) and scatter it onto one shared 20 m grid.

    No order is assumed within a file: indices are computed from the
    coordinates, so a map sheet with a missing corner or a different order is
    not misplaced.
    """
    cols, names = [], set()
    for name, blob in _grd_blobs(d):
        if name in names:            # Take one copy when a zip and a loose file duplicate each other.
            continue
        names.add(name)
        a = np.fromstring(blob.decode("ascii"), sep=" ")
        if a.size % 3:
            raise SystemExit(f"{name}: the number of values is not a multiple of 3")
        cols.append(a.reshape(-1, 3))
    if not cols:
        return None, None, None
    print(f"NLSC 20 m DTM: {len(cols)} sheets")
    pts = np.concatenate(cols)
    del cols

    E, N, Z = pts[:, 0], pts[:, 1], pts[:, 2]
    bad = (Z < -50) | (Z > 4000)          # Filter out no-data sentinel values.
    if bad.any():
        print(f"  Filtered out {bad.sum():,} points with abnormal elevations")
        E, N, Z = E[~bad], N[~bad], Z[~bad]

    e0, e1 = E.min(), E.max()
    n0, n1 = N.min(), N.max()
    nx = int((e1 - e0) / NLSC_STEP) + 1
    nz = int((n1 - n0) / NLSC_STEP) + 1
    print(f"  Extent E[{e0:.0f},{e1:.0f}] N[{n0:.0f},{n1:.0f}]"
          f"  = {(e1-e0)/1000:.1f} x {(n1-n0)/1000:.1f} km  grid {nz}x{nx}")

    grid = np.full((nz, nx), np.nan, dtype=np.float32)
    ci = np.rint((E - e0) / NLSC_STEP).astype(np.int64)
    ri = np.rint((N - n0) / NLSC_STEP).astype(np.int64)
    grid[ri, ci] = Z
    filled = np.isfinite(grid)
    print(f"  {len(Z):,} points, grid {100*filled.mean():.1f}% filled"
          f", elevation {np.nanmin(grid):.1f}~{np.nanmax(grid):.1f} m")
    return grid, (e0, n0), filled


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", type=int, default=20, help="grid spacing in metres")
    ap.add_argument("--margin", type=int, default=600, help="margin around the network in metres")
    a = ap.parse_args()

    # The coverage is taken from the actual network.
    lines = json.load(open(config.MC_LINES_JSON, encoding="utf-8"))
    xs, zs = [], []
    for vs in lines.values():
        for v in vs:
            for x, z in v["points"]:
                xs.append(x); zs.append(z)
    x0, x1 = min(xs) - a.margin, max(xs) + a.margin
    z0, z1 = min(zs) - a.margin, max(zs) + a.margin
    print(f"Coverage MC X[{x0},{x1}] Z[{z0},{z1}]  = {(x1-x0)/1000:.1f} x {(z1-z0)/1000:.1f} km")

    gx = np.arange(x0, x1 + a.step, a.step)
    gz = np.arange(z0, z1 + a.step, a.step)
    GX, GZ = np.meshgrid(gx, gz)
    E = GX + OE
    N = ON - GZ

    # --- 1. NLSC DTM (primary source, native EPSG:3826, sampled after a plain translation) ---
    nl, org, _ = load_nlsc(config.DEM_NLSC)
    if nl is None:
        raise SystemExit(f"No .grd files under {config.DEM_NLSC}")
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
    print(f"DTM covers {100*good.mean():.1f}% of the network extent")

    # --- 2. Copernicus DSM (fills the gaps) ---
    tifs = sorted(glob.glob(os.path.join(config.DEM_COPERNICUS, "*.tif"))) \
        or sorted(glob.glob(os.path.join(config.DATA, "dem", "*.tif")))
    srcs = [rasterio.open(t) for t in tifs]
    mosaic, tf = merge(srcs)
    cop = mosaic[0].astype(np.float32)
    nod = srcs[0].nodata
    if nod is not None:
        cop[cop == nod] = 0.0
    lon, lat = TO_LL.transform(E, N)
    cc, rr = (~tf) * (lon, lat)
    dsm = bilinear(cop, np.asarray(cc), np.asarray(rr))
    print(f"Copernicus DSM mosaic {cop.shape} ({len(tifs)} tiles)")

    # The DSM reads systematically high (buildings + tree canopy + datum
    # difference), so subtract the median offset before using it as fill.
    diff = (dsm - dtm)[good]
    bias = float(np.median(diff))
    print(f"DSM - DTM: median {bias:+.2f} m, "
          f"mean {np.mean(diff):+.2f} m, "
          f"90th percentile {np.percentile(diff,90):+.2f} m, max {diff.max():+.2f} m")

    # --- 3. Feathered blend, so no cliff appears at the boundary ---
    w = box_blur(good.astype(np.float64), FEATHER)
    w = np.clip(w, 0, 1)
    fill = dsm - bias
    hm_f = np.where(good, np.nan_to_num(dtm) * w + fill * (1 - w), fill)
    n_fill = int((~good).sum())
    print(f"Cells filled from the DSM: {n_fill:,} ({100*n_fill/good.size:.1f}%), "
          f"boundary feather radius {FEATHER*a.step} m")

    hm = np.round(hm_f).astype(np.int16)
    np.save(config.HEIGHTMAP_NPY, hm)
    meta = dict(x0=int(x0), z0=int(z0), step=int(a.step),
                nx=int(len(gx)), nz=int(len(gz)), sea_y=SEA_Y,
                primary="NLSC 20m DTM (TWD97/TM2, TWVD2001)",
                fallback=[os.path.basename(t) for t in tifs],
                dsm_bias=round(bias, 3), dtm_coverage=round(float(good.mean()), 4))
    json.dump(meta, open(config.HEIGHTMAP_JSON, "w", encoding="utf-8"),
              indent=1, ensure_ascii=False)

    print(f"\nGrid {hm.shape}  elevation {hm.min()}~{hm.max()} m")
    for q in (1, 25, 50, 75, 95, 99, 99.9):
        print(f"  {q:>5}% quantile: {np.percentile(hm, q):>7.1f} m  -> y={SEA_Y+np.percentile(hm,q):.0f}")
    over = (hm.astype(np.int32) + SEA_Y > 319).sum()
    print(f"Cells above the y=319 limit: {over} ({100*over/hm.size:.3f}%)")


if __name__ == "__main__":
    main()
