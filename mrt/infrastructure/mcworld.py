#!/usr/bin/env python3
"""把方塊寫進 Minecraft 存檔 (Anvil 格式, MC 26.2 / DataVersion 4903)。

26.2 的存檔佈局:
    <save>/level.dat
    <save>/data/minecraft/world_gen_settings.dat      <- 世界生成設定搬到這裡了
    <save>/dimensions/minecraft/overworld/region/r.<rx>.<rz>.mca

用法:
    w = World("/path/to/save", name="Taipei MRT")
    w.fill(0, 64, 0, 10, 70, 10, "minecraft:stone")
    w.set(5, 71, 5, "minecraft:oak_fence[north=true]")
    w.save()
"""
import os, io, re, zlib, math, struct, shutil, time
import numpy as np
import nbtlib
from nbtlib.tag import (Compound, List, String, Int, Byte, Long, LongArray,
                        IntArray, Float, Double)

from mrt.config import Y_MIN, Y_MAX, SEC_MIN, SEC_MAX, N_SEC

DATA_VERSION = 4903          # MC 26.2 —— 這個是存檔格式的細節，留在這一層

# 超平坦背景地層 (y_from, y_to, block)。寫過的區塊要自己把這些填回去 ——
# 我們標了 Status=full，遊戲就不會再生成地形，不填的話隧道會懸在虛空裡。
FLAT_LAYERS = [(-64, -64, "minecraft:bedrock"),
               (-63,  60, "minecraft:stone"),
               ( 61,  63, "minecraft:dirt"),
               ( 64,  64, "minecraft:grass_block")]
GROUND_TOP = FLAT_LAYERS[-1][1]


def background_block(y):
    for a, b, blk in FLAT_LAYERS:
        if a <= y <= b:
            return blk
    return "minecraft:air"


_BS_RE = re.compile(r"^([a-z0-9_.:]+)(?:\[(.*)\])?$")


def _u32():
    """UUID 用的有號 32-bit 亂數"""
    return int.from_bytes(os.urandom(4), "big", signed=True)


def parse_block(s):
    """'minecraft:oak_stairs[facing=north,half=top]' -> nbt Compound"""
    m = _BS_RE.match(s.strip())
    if not m:
        raise ValueError(f"看不懂的方塊字串: {s!r}")
    name, props = m.group(1), m.group(2)
    if ":" not in name:
        name = "minecraft:" + name
    c = Compound({"Name": String(name)})
    if props:
        p = Compound()
        for kv in props.split(","):
            k, _, v = kv.partition("=")
            p[k.strip()] = String(v.strip())
        c["Properties"] = p
    return c


def _pack(indices, bits):
    """1.16+ 的 bit-packing: 每個 long 塞 64//bits 筆，不跨 long。"""
    per = 64 // bits
    n = math.ceil(len(indices) / per)
    out = np.zeros(n, dtype=np.uint64)
    idx = indices.astype(np.uint64)
    for slot in range(per):
        sl = idx[slot::per]
        if len(sl) == 0:
            continue
        out[:len(sl)] |= sl << np.uint64(slot * bits)
    # NBT 的 long 是有號的
    return out.astype(np.int64)


class Chunk:
    __slots__ = ("cx", "cz", "sections", "pal", "pal_idx", "bes")

    def __init__(self, cx, cz):
        self.cx, self.cz = cx, cz
        self.sections = {}                      # secY -> np.uint16[4096]
        # 0 號保留給「這格沒寫過」，存檔時會換成背景地層。
        # 不能讓 air 佔 0 號 —— 挖隧道時要能明確寫入空氣。
        self.pal = [None]
        self.pal_idx = {}
        self.bes = {}                           # (x,y,z) -> block entity Compound

    def _pid(self, block):
        i = self.pal_idx.get(block)
        if i is None:
            i = len(self.pal)
            self.pal.append(block)
            self.pal_idx[block] = i
        return i

    def _sec(self, sy):
        a = self.sections.get(sy)
        if a is None:
            a = np.zeros(4096, dtype=np.uint16)
            self.sections[sy] = a
        return a

    def set_section(self, sy, codes, names):
        """整個 16^3 section 一次寫入。codes 是 (y,z,x) 順序的整數編碼陣列，
        names 是編碼對應的方塊名。生地形時逐格 set() 會慢兩個數量級。"""
        remap = np.array([self._pid(n) for n in names], dtype=np.uint16)
        self._sec(sy)[:] = remap[np.asarray(codes).reshape(-1)]

    def set(self, x, y, z, block):
        """x,z 為 chunk 內 0..15；y 為絕對高度"""
        if not (Y_MIN <= y <= Y_MAX):
            return
        a = self._sec(y >> 4)
        a[(y & 15) * 256 + z * 16 + x] = self._pid(block)

    def to_nbt(self):
        secs = List[Compound]()
        for sy in range(SEC_MIN, SEC_MAX + 1):
            arr = self.sections.get(sy)
            ybase = sy * 16
            local, lidx = [], {}

            def li(name):
                i = lidx.get(name)
                if i is None:
                    i = len(local); local.append(name); lidx[name] = i
                return i

            # 先鋪背景地層
            codes = np.zeros(4096, dtype=np.uint16)
            for j in range(16):
                codes[j * 256:(j + 1) * 256] = li(background_block(ybase + j))

            # 再蓋上實際寫入的方塊（0 = 沒寫過，保留背景）
            if arr is not None:
                mask = arr != 0
                if mask.any():
                    remap = np.zeros(len(self.pal), dtype=np.uint16)
                    for u in np.unique(arr[mask]):
                        remap[u] = li(self.pal[u])
                    codes[mask] = remap[arr[mask]]

            sec = Compound({"Y": Byte(sy)})
            bs = Compound({"palette": List[Compound]([parse_block(n) for n in local])})
            if len(local) > 1:
                bits = max(4, (len(local) - 1).bit_length())
                bs["data"] = LongArray(_pack(codes, bits).tolist())
            sec["block_states"] = bs
            sec["biomes"] = Compound({"palette": List[String]([String("minecraft:plains")])})
            secs.append(sec)

        return Compound({
            "DataVersion": Int(DATA_VERSION),
            "xPos": Int(self.cx), "yPos": Int(SEC_MIN), "zPos": Int(self.cz),
            "Status": String("minecraft:full"),
            "LastUpdate": Long(0), "InhabitedTime": Long(0),
            "isLightOn": Byte(0),                 # 讓遊戲重算光照
            "sections": secs,
            "block_entities": List[Compound](list(self.bes.values())),
            "block_ticks": List[Compound]([]),
            "fluid_ticks": List[Compound]([]),
            "PostProcessing": List[List[Compound]]([List[Compound]([]) for _ in range(N_SEC)]),
            "Heightmaps": Compound({}),
            "structures": Compound({"starts": Compound({}), "References": Compound({})}),
        })


class World:
    def __init__(self, path, name="Generated", seed=0, spawn=(0, 80, 0)):
        self.path = os.path.abspath(path)
        self.name = name
        self.seed = seed
        self.spawn = spawn
        self.chunks = {}                        # (cx,cz) -> Chunk
        self._region_filter = None              # 設成 (rx,rz) 則只收該 region 的方塊

    # ---- 方塊寫入 ----
    def set(self, x, y, z, block):
        cx, cz = x >> 4, z >> 4
        if self._region_filter is not None:
            rx, rz = self._region_filter
            if (cx >> 5) != rx or (cz >> 5) != rz:
                return                          # 別的 region 會自己處理這格
        c = self.chunks.get((cx, cz))
        if c is None:
            c = self.chunks[(cx, cz)] = Chunk(cx, cz)
        c.set(x & 15, y, z & 15, block)


    # ---- 告示牌 ----
    def sign(self, x, y, z, lines, facing=(0, 1), wood="oak"):
        """立一面告示牌。lines 為最多 4 行文字，facing 是牌面朝向的 (dx, dz)。

        26.2 (DataVersion 4903) 的文字元件是原生 NBT，不再是 JSON 字串
        （1.21.5 起改制）；且 NBT 清單必須同型別，所以四行一律用純字串，
        不能混入 compound。
        """
        fx, fz = facing
        yaw = math.degrees(math.atan2(-fx, fz))          # MC: 0=南, 90=西, 180=北, 270=東
        rot = int(round(yaw / 22.5)) % 16
        msgs = [str(t) for t in list(lines)[:4]]
        msgs += [""] * (4 - len(msgs))                   # 一定要剛好四行
        blank = List[String]([String("") for _ in range(4)])
        self.set(x, y, z, f"minecraft:{wood}_sign[rotation={rot},waterlogged=false]")
        c = self.chunks.get((x >> 4, z >> 4))
        if c is None:
            return          # 被 region 過濾掉了，該 region 處理到時會自己寫
        c.bes[(x, y, z)] = Compound({
            "id": String("minecraft:sign"),
            "x": Int(x), "y": Int(y), "z": Int(z),
            "keepPacked": Byte(0),
            "is_waxed": Byte(1),                         # 上蠟，避免被玩家改字
            "front_text": Compound({
                "messages": List[String]([String(m) for m in msgs]),
                "color": String("black"), "has_glowing_text": Byte(0)}),
            "back_text": Compound({
                "messages": blank,
                "color": String("black"), "has_glowing_text": Byte(0)}),
        })

    def fill(self, x0, y0, z0, x1, y1, z1, block):
        for x in range(min(x0, x1), max(x0, x1) + 1):
            for y in range(min(y0, y1), max(y0, y1) + 1):
                for z in range(min(z0, z1), max(z0, z1) + 1):
                    self.set(x, y, z, block)

    # ---- 存檔 ----
    def _write_level(self):
        os.makedirs(os.path.join(self.path, "data", "minecraft"), exist_ok=True)
        data = Compound({
            "DataVersion": Int(DATA_VERSION),
            "Version": Compound({"Snapshot": Byte(0), "Series": String("main"),
                                 "Id": Int(DATA_VERSION), "Name": String("26.2")}),
            "LevelName": String(self.name),
            "GameType": Int(1),                  # 創造模式
            "allowCommands": Byte(1),
            "initialized": Byte(1),
            "WasModded": Byte(0),
            "LastPlayed": Long(int(time.time() * 1000)),
            "Time": Long(0),
            "version": Int(19133),
            "spawn": Compound({"pos": IntArray(list(self.spawn)),
                               "pitch": Float(0.0), "yaw": Float(0.0),
                               "dimension": String("minecraft:overworld")}),
            "difficulty_settings": Compound({"difficulty": String("normal"),
                                             "hardcore": Byte(0), "locked": Byte(0)}),
            "singleplayer_uuid": IntArray([_u32(), _u32(), _u32(), _u32()]),
            "DataPacks": Compound({"Enabled": List[String]([String("vanilla")]),
                                   "Disabled": List[String]([])}),
            "ServerBrands": List[String]([String("vanilla")]),
        })
        nbtlib.File({"Data": data}, gzipped=True).save(
            os.path.join(self.path, "level.dat"))

        # 超平坦設定直接由 FLAT_LAYERS 導出，確保與寫入區塊的背景一致
        layers = List[Compound]([
            Compound({"height": Int(b - a + 1), "block": String(blk)})
            for a, b, blk in FLAT_LAYERS])
        flat = Compound({
            "biome": String("minecraft:plains"),
            "lakes": Byte(0), "features": Byte(0),
            "layers": layers,
        })
        wgs = Compound({
            "data": Compound({
                "bonus_chest": Byte(0), "seed": Long(self.seed),
                "generate_structures": Byte(0),
                "dimensions": Compound({
                    "minecraft:overworld": Compound({
                        "type": String("minecraft:overworld"),
                        "generator": Compound({"type": String("minecraft:flat"),
                                               "settings": flat})}),
                    "minecraft:the_nether": Compound({
                        "type": String("minecraft:the_nether"),
                        "generator": Compound({
                            "type": String("minecraft:noise"),
                            "settings": String("minecraft:nether"),
                            "biome_source": Compound({"type": String("minecraft:multi_noise"),
                                                      "preset": String("minecraft:nether")})})}),
                    "minecraft:the_end": Compound({
                        "type": String("minecraft:the_end"),
                        "generator": Compound({
                            "type": String("minecraft:noise"),
                            "settings": String("minecraft:end"),
                            "biome_source": Compound({"type": String("minecraft:the_end")})})}),
                }),
            }),
            "DataVersion": Int(DATA_VERSION),
        })
        nbtlib.File(wgs, gzipped=True).save(
            os.path.join(self.path, "data", "minecraft", "world_gen_settings.dat"))

    def _region_dir(self):
        d = os.path.join(self.path, "dimensions", "minecraft", "overworld", "region")
        os.makedirs(d, exist_ok=True)
        return d

    def _write_region(self, rx, rz, chunks, rdir):
        loc = bytearray(4096)
        ts = bytearray(4096)
        body = bytearray()
        sector = 2                                    # 前兩個 sector 是表頭
        now = int(time.time())
        for c in chunks:
            buf = io.BytesIO()
            nbtlib.File(c.to_nbt()).write(buf)        # 未壓縮的原始 NBT
            blob = zlib.compress(buf.getvalue(), 6)
            payload = struct.pack(">IB", len(blob) + 1, 2) + blob
            payload += b"\0" * ((-len(payload)) % 4096)
            cnt = len(payload) // 4096
            if cnt > 255:
                raise ValueError(f"區塊 {c.cx},{c.cz} 超過 1MB 上限")
            i = (c.cx & 31) + (c.cz & 31) * 32
            loc[i*4:i*4+3] = sector.to_bytes(3, "big")
            loc[i*4+3] = cnt
            ts[i*4:i*4+4] = struct.pack(">I", now)
            body += payload
            sector += cnt
        with open(os.path.join(rdir, f"r.{rx}.{rz}.mca"), "wb") as f:
            f.write(loc); f.write(ts); f.write(body)
        return len(body) + 8192

    def save_region(self, rx, rz):
        """只寫出單一 region，寫完就把記憶體裡的區塊丟掉。"""
        n = self._write_region(rx, rz, list(self.chunks.values()), self._region_dir())
        self.chunks.clear()
        return n

    def save(self, verbose=True):
        rdir = self._region_dir()
        self._write_level()
        regions = {}
        for (cx, cz), c in self.chunks.items():
            regions.setdefault((cx >> 5, cz >> 5), []).append(c)
        for (rx, rz), chunks in sorted(regions.items()):
            n = self._write_region(rx, rz, chunks, rdir)
            if verbose:
                print(f"  r.{rx}.{rz}.mca  {len(chunks)} 區塊  {n/1e6:.1f} MB")
        if verbose:
            print(f"存檔完成: {self.path}  ({len(self.chunks)} 區塊, {len(regions)} 區域檔)")
