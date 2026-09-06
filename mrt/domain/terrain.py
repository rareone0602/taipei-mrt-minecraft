#!/usr/bin/env python3
"""高程網格取樣器：把 data/heightmap.npy 轉成 Minecraft 的 y 值。"""
import os, json
import numpy as np

from mrt import config

SEA_Y      = 62      # 海平面對應的 y
COMPRESS_H = 180     # 這個高度以上開始壓縮，免得陽明山頂撞到 y=319 上限
COMPRESS_K = 0.5
Y_CAP      = 312


class Terrain:
    def __init__(self, path=None):
        path = path or config.HEIGHTMAP_NPY
        self.hm = np.load(path)
        m = json.load(open(os.path.splitext(path)[0] + ".json", encoding="utf-8"))
        self.x0, self.z0, self.step = m["x0"], m["z0"], m["step"]
        self.nz, self.nx = self.hm.shape

    def elev(self, x, z):
        """雙線性內插的地面高程（公尺，海平面 = 0）"""
        c = (np.asarray(x, dtype=np.float64) - self.x0) / self.step
        r = (np.asarray(z, dtype=np.float64) - self.z0) / self.step
        c = np.clip(c, 0, self.nx - 1.001)
        r = np.clip(r, 0, self.nz - 1.001)
        c0 = c.astype(np.int64); r0 = r.astype(np.int64)
        fc = c - c0; fr = r - r0
        h = self.hm
        v = (h[r0, c0] * (1 - fc) * (1 - fr) + h[r0, c0 + 1] * fc * (1 - fr)
             + h[r0 + 1, c0] * (1 - fc) * fr + h[r0 + 1, c0 + 1] * fc * fr)
        return v

    def y_at(self, x, z):
        """地面的 Minecraft y。超過 COMPRESS_H 的山區做垂直壓縮 —
        1:1 會讓陽明山 (1100 m) 直接超出 y=319 的世界上限。"""
        e = np.asarray(self.elev(x, z), dtype=np.float64)
        hi = e > COMPRESS_H
        e = np.where(hi, COMPRESS_H + (e - COMPRESS_H) * COMPRESS_K, e)
        return np.clip(np.round(SEA_Y + e), -60, Y_CAP).astype(np.int32)
