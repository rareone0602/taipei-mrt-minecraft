#!/usr/bin/env python3
"""從 Anvil 存檔讀回一塊立體範圍的方塊。

寫入那半邊在 mcworld.py。讀回來這半邊本來散在 tools/ 的三支工具裡各寫一份
（verify_rails 掃鐵軌、verify_render 掃地表、slice_world 掃剖面），三份的
palette 解碼與位元解包幾乎一樣。驗證地下街要的是「任意座標查方塊」，
跟那三種掃法都不同，所以把共用的部分放到這裡。

region 檔格式：開頭 4 KB 是 1024 個 (offset, sectors)，接著每個 chunk 是
4 位元組長度 + 1 位元組壓縮方式 + 壓縮過的 NBT。方塊存在 sections[].block_states
的 palette + 位元打包索引裡；1.16 起同一個索引不會跨 long。
"""
import glob
import io
import os
import zlib

import numpy as np
import nbtlib

AIR = "minecraft:air"


def unpack(data, bits, n=4096):
    """位元打包的索引陣列 -> 長度 n 的索引。索引不跨 long（1.16 起的格式）。"""
    per = 64 // bits
    out = np.zeros(n, dtype=np.int64)
    arr = np.asarray(data, dtype=np.int64).view(np.uint64)
    mask = np.uint64((1 << bits) - 1)
    for slot in range(per):
        vals = (arr >> np.uint64(slot * bits)) & mask
        tgt = np.arange(slot, n, per)
        out[tgt] = vals[:len(tgt)]
    return out


def palette_names(bs):
    """block_states -> 帶方塊狀態的名稱清單，順序即 palette 索引。"""
    out = []
    for e in bs["palette"]:
        name = str(e["Name"])
        if "Properties" in e:
            props = ",".join(f"{k}={v}" for k, v in e["Properties"].items())
            name += f"[{props}]"
        out.append(name)
    return out


class Volume:
    """一塊立體範圍的方塊，用 int16 的 palette 索引存。

    1400 x 900 x 32 大約 40 M 格 = 80 MB，查詢是純陣列索引。
    範圍外一律回空氣 —— 呼叫端（walk.flood）自己用 bounds 圈住搜尋範圍，
    這裡不必分辨「外面」與「沒東西」。
    """

    def __init__(self, x0, y0, z0, x1, y1, z1):
        self.x0, self.y0, self.z0 = int(x0), int(y0), int(z0)
        self.x1, self.y1, self.z1 = int(x1), int(y1), int(z1)
        self.nx = self.x1 - self.x0 + 1
        self.ny = self.y1 - self.y0 + 1
        self.nz = self.z1 - self.z0 + 1
        self.data = np.zeros((self.ny, self.nz, self.nx), dtype=np.int16)
        self.names = [AIR]
        self._ids = {AIR: 0}

    def ident(self, name):
        i = self._ids.get(name)
        if i is None:
            i = self._ids[name] = len(self.names)
            self.names.append(name)
        return i

    def get(self, x, y, z):
        if not (self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1
                and self.z0 <= z <= self.z1):
            return AIR
        return self.names[self.data[y - self.y0, z - self.z0, x - self.x0]]

    def count(self, predicate):
        """符合條件的方塊數。predicate 收方塊名稱。"""
        keep = np.array([bool(predicate(n)) for n in self.names])
        return int(keep[self.data].sum())

    def __len__(self):
        return int((self.data != 0).sum())


def _region_dir(save, region_dir=None):
    rdir = region_dir or os.path.join(save, "dimensions", "minecraft",
                                      "overworld", "region")
    if not os.path.isdir(rdir):                 # 26.2 之前的舊佈局
        rdir = os.path.join(save, "region")
    return rdir


def iter_chunks(rdir, x0, z0, x1, z1):
    """走訪與 [x0,x1] x [z0,z1] 有交集的 chunk，產生 (cx, cz, 根 Compound)。"""
    want = []
    for rx in range(x0 >> 9, (x1 >> 9) + 1):
        for rz in range(z0 >> 9, (z1 >> 9) + 1):
            p = os.path.join(rdir, f"r.{rx}.{rz}.mca")
            if os.path.exists(p):
                want.append((rx, rz, p))
    for rx, rz, path in want:
        raw = open(path, "rb").read()
        if len(raw) < 8192:
            continue
        for i in range(1024):
            cx = rx * 32 + (i % 32)
            cz = rz * 32 + (i // 32)
            if (cx * 16 > x1 or cx * 16 + 15 < x0
                    or cz * 16 > z1 or cz * 16 + 15 < z0):
                continue
            off = int.from_bytes(raw[i * 4:i * 4 + 3], "big")
            if off == 0:
                continue
            q = off * 4096
            ln = int.from_bytes(raw[q:q + 4], "big")
            blob = raw[q + 5:q + 4 + ln]
            root = nbtlib.File.parse(io.BytesIO(
                zlib.decompress(blob) if raw[q + 4] == 2 else blob))
            root = root[''] if '' in root else root
            yield cx, cz, root


def read_signs(save, x0, z0, x1, z1, region_dir=None):
    """讀回範圍內所有告示牌：[(x, y, z, [四行文字])]。

    文字在 block_entities 的 front_text.messages 裡（1.21.5 起是原生 NBT
    字串清單，不是 JSON）。驗證出入口用它找出入口亭 —— 牌子是生成器
    立的沒錯，但「牌子旁邊有沒有一座走得通的樓梯」是從方塊讀回來驗的。
    """
    rdir = _region_dir(save, region_dir)
    out = []
    for cx, cz, root in iter_chunks(rdir, x0, z0, x1, z1):
        for be in root.get("block_entities", ()):
            if str(be.get("id", "")) != "minecraft:sign":
                continue
            x, y, z = int(be["x"]), int(be["y"]), int(be["z"])
            if not (x0 <= x <= x1 and z0 <= z <= z1):
                continue
            ft = be.get("front_text", {})
            msgs = [str(m) for m in ft.get("messages", [])]
            out.append((x, y, z, msgs))
    return out


def read_volume(save, x0, y0, z0, x1, y1, z1, region_dir=None, verbose=True):
    """讀回 [x0,x1] x [y0,y1] x [z0,z1]（含端點）的方塊。"""
    rdir = _region_dir(save, region_dir)
    vol = Volume(x0, y0, z0, x1, y1, z1)
    if verbose:
        have = len(glob.glob(os.path.join(rdir, "r.*.mca")))
        nreg = sum(1 for rx in range(x0 >> 9, (x1 >> 9) + 1)
                   for rz in range(z0 >> 9, (z1 >> 9) + 1)
                   if os.path.exists(os.path.join(rdir, f"r.{rx}.{rz}.mca")))
        print(f"  範圍涵蓋 {nreg} 個 region（存檔共 {have} 個）")

    sy0, sy1 = y0 >> 4, y1 >> 4
    nchunk = 0
    for cx, cz, root in iter_chunks(rdir, x0, z0, x1, z1):
        if "sections" not in root:
            continue
        nchunk += 1
        bx, bz = cx * 16, cz * 16
        for sec in root["sections"]:
            sy = int(sec["Y"])
            if sy < sy0 or sy > sy1 or "block_states" not in sec:
                continue
            bs = sec["block_states"]
            pal = palette_names(bs)
            if len(pal) == 1 and pal[0] == AIR:
                continue
            ids = np.array([vol.ident(n) for n in pal], dtype=np.int16)
            if "data" in bs and len(bs["data"]):
                bits = max(4, (len(pal) - 1).bit_length())
                idx = unpack(bs["data"], bits)
            else:
                idx = np.zeros(4096, dtype=np.int64)
            blk = ids[idx].reshape(16, 16, 16)          # [y][z][x]

            # 與目標範圍取交集，只搬重疊的那一塊
            by = sy * 16
            ly0, ly1 = max(y0, by), min(y1, by + 15)
            lz0, lz1 = max(z0, bz), min(z1, bz + 15)
            lx0, lx1 = max(x0, bx), min(x1, bx + 15)
            if ly0 > ly1 or lz0 > lz1 or lx0 > lx1:
                continue
            vol.data[ly0 - y0:ly1 - y0 + 1,
                     lz0 - z0:lz1 - z0 + 1,
                     lx0 - x0:lx1 - x0 + 1] = blk[
                ly0 - by:ly1 - by + 1,
                lz0 - bz:lz1 - bz + 1,
                lx0 - bx:lx1 - bx + 1]
    if verbose:
        print(f"  讀回 {nchunk:,} 個區塊，{len(vol.names)} 種方塊，"
              f"非空氣 {len(vol):,} 格")
    return vol
