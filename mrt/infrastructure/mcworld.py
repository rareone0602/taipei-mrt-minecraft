#!/usr/bin/env python3
"""Write blocks into a Minecraft world save (Anvil format, MC 26.2 / DataVersion 4903).

The 26.2 save layout:
    <save>/level.dat
    <save>/data/minecraft/world_gen_settings.dat      <- the world generation settings moved here
    <save>/dimensions/minecraft/overworld/region/r.<rx>.<rz>.mca

Usage:
    w = World("/path/to/save", name="Taipei MRT")
    w.fill(0, 64, 0, 10, 70, 10, "minecraft:stone")
    w.set(5, 71, 5, "minecraft:oak_fence[north=true]")
    w.save()
"""
import os, io, re, zlib, math, struct, time
import numpy as np
import nbtlib
from nbtlib.tag import (Compound, List, String, Int, Byte, Long, LongArray,
                        IntArray, Float)

from mrt.config import Y_MIN, Y_MAX, SEC_MIN, SEC_MAX, N_SEC, DATAPACK_NAME
from mrt.infrastructure import heightmap as HM

DATA_VERSION = 4903          # MC 26.2. This is a detail of the save format, so it stays in this layer.

# Superflat background strata (y_from, y_to, block). A written chunk must fill
# these in itself: it is marked Status=full, so the game will not generate
# terrain for it, and without them the tunnels would hang in the void.
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


# Heightmap flags of each section's background strata ([16], one per layer);
# heightmap computation looks up unwritten cells here.
_BG_FLAGS = {sy: np.array([HM.flags(background_block(sy * 16 + j)) for j in range(16)],
                          dtype=np.uint8)
             for sy in range(SEC_MIN, SEC_MAX + 1)}


_BS_RE = re.compile(r"^([a-z0-9_.:]+)(?:\[(.*)\])?$")

# Sections whose background is entirely air (above y64): when unwritten, their
# contents are identical, so one shared copy is built in advance.
_AIR_SECTIONS = {
    sy: Compound({"Y": Byte(sy),
                  "block_states": Compound({"palette": List[Compound]([Compound({"Name": String("minecraft:air")})])}),
                  "biomes": Compound({"palette": List[String]([String("minecraft:plains")])})})
    for sy in range(SEC_MIN, SEC_MAX + 1)
    if all(background_block(sy * 16 + j) == "minecraft:air" for j in range(16))}


def yaw_of(fx, fz):
    """Map a facing (dx, dz) to a Minecraft yaw in degrees (-180 to 180).

    0 = south (+z), 90 = west, ±180 = north, -90 = east. Both a sign's rotation
    and the spawn point's yaw in level.dat use this conversion."""
    return math.degrees(math.atan2(-fx, fz))


def _u32():
    """Return a signed 32-bit random number for a UUID."""
    return int.from_bytes(os.urandom(4), "big", signed=True)


def parse_block(s):
    """Parse 'minecraft:oak_stairs[facing=north,half=top]' into an nbt Compound."""
    m = _BS_RE.match(s.strip())
    if not m:
        raise ValueError(f"Unrecognised block string: {s!r}")
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


def _component(item, click=None):
    """Convert one line of sign text to a text component compound (26.2's native NBT format).

    Key names follow 26.2's Style encoding: color, bold, italic, click_event
    (snake case; no longer clickEvent since 1.21.5). The field for run_command
    is command, and for show_dialog it is dialog. All of these were checked
    against the class constant pools read from the game jar.
    """
    if isinstance(item, dict):
        c = Compound({"text": String(str(item.get("text", "")))})
        if item.get("color"):
            c["color"] = String(str(item["color"]))
        for k in ("bold", "italic"):
            if item.get(k):
                c[k] = Byte(1)
    else:
        c = Compound({"text": String(str(item))})
    if click is not None:
        c["click_event"] = click
    return c


def _sign_text(lines, color, glow, click):
    """Build front_text / back_text: a list of strings for four plain lines, otherwise all compounds."""
    items = list(lines)[:4]
    items += [""] * (4 - len(items))                     # Must be exactly four lines.
    rich = click is not None or any(isinstance(t, dict) for t in items)
    if rich:
        msgs = List[Compound]([_component(t, click if k == 0 else None)
                               for k, t in enumerate(items)])
    else:
        msgs = List[String]([String(str(t)) for t in items])
    return Compound({"messages": msgs, "color": String(color),
                     "has_glowing_text": Byte(1 if glow else 0)})


def _pack(indices, bits):
    """Bit-pack as in 1.16+: 64//bits entries per long, none spanning longs."""
    per = 64 // bits
    n = math.ceil(len(indices) / per)
    out = np.zeros(n, dtype=np.uint64)
    idx = indices.astype(np.uint64)
    for slot in range(per):
        sl = idx[slot::per]
        if len(sl) == 0:
            continue
        out[:len(sl)] |= sl << np.uint64(slot * bits)
    # NBT longs are signed.
    return out.astype(np.int64)


class Chunk:
    __slots__ = ("cx", "cz", "sections", "pal", "pal_idx", "bes")

    def __init__(self, cx, cz):
        self.cx, self.cz = cx, cz
        self.sections = {}                      # secY -> np.uint16[4096]
        # Index 0 is reserved for "this cell was never written" and is replaced
        # by the background strata on save. Air must not take index 0: digging a
        # tunnel has to be able to write air explicitly.
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
        """Write a whole 16^3 section at once.

        codes is an array of integer codes in (y,z,x) order, and names maps
        each code to a block name. Calling set() cell by cell for terrain is
        two orders of magnitude slower."""
        remap = np.array([self._pid(n) for n in names], dtype=np.uint16)
        self._sec(sy)[:] = remap[np.asarray(codes).reshape(-1)]

    def set(self, x, y, z, block):
        """Set one block; x,z are 0..15 within the chunk and y is the absolute height."""
        if not (Y_MIN <= y <= Y_MAX):
            return
        a = self._sec(y >> 4)
        a[(y & 15) * 256 + z * 16 + x] = self._pid(block)

    def heightmaps(self):
        """Return the four heightmaps (in heightmap.TYPES order), each with 256 entries indexed x + z*16.

        Finding the spawn and respawn points reads the top of the column from
        MOTION_BLOCKING (see the heightmap.py docstring). Palette index 0
        (unwritten) counts as the background strata, and an unwritten section
        is background throughout.
        """
        lut = HM.flags_lut(self.pal[1:])
        lut = np.concatenate([np.zeros(1, dtype=np.uint8), lut])

        def section_flags(sy):
            bg = _BG_FLAGS[sy]
            arr = self.sections.get(sy)
            if arr is None:
                return np.broadcast_to(bg[:, None, None], (16, 16, 16)) if bg.any() else None
            a = arr.reshape(16, 16, 16)
            f = lut[a]
            unset = a == 0
            if unset.any():
                f = np.where(unset, bg[:, None, None], f)
            return f

        return HM.column_heights(section_flags).reshape(4, 256)

    def to_nbt(self):
        secs = List[Compound]()
        for sy in range(SEC_MIN, SEC_MAX + 1):
            arr = self.sections.get(sy)
            if arr is None and sy in _AIR_SECTIONS:
                # Unwritten, with a background that is entirely air: since the
                # world was raised to y639, every chunk has twenty more of these,
                # so they share one prebuilt Compound instead of rebuilding the
                # palette each time.
                secs.append(_AIR_SECTIONS[sy])
                continue
            ybase = sy * 16
            local, lidx = [], {}

            def li(name):
                i = lidx.get(name)
                if i is None:
                    i = len(local); local.append(name); lidx[name] = i
                return i

            # Lay the background strata first.
            codes = np.zeros(4096, dtype=np.uint16)
            for j in range(16):
                codes[j * 256:(j + 1) * 256] = li(background_block(ybase + j))

            # Then overlay the blocks actually written (0 = unwritten, keep the background).
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
            "isLightOn": Byte(0),                 # Let the game recompute lighting.
            "sections": secs,
            "block_entities": List[Compound](list(self.bes.values())),
            "block_ticks": List[Compound]([]),
            "fluid_ticks": List[Compound]([]),
            "PostProcessing": List[List[Compound]]([List[Compound]([]) for _ in range(N_SEC)]),
            # A full chunk saved by the game always carries these four tables;
            # this used to be written empty (see heightmap.py).
            "Heightmaps": Compound({
                t: LongArray(HM.pack(v).tolist())
                for t, v in zip(HM.TYPES, self.heightmaps())}),
            "structures": Compound({"starts": Compound({}), "References": Compound({})}),
        })


class World:
    def __init__(self, path, name="Generated", seed=0, spawn=(0, 80, 0), spawn_facing=None):
        self.path = os.path.abspath(path)
        self.name = name
        self.seed = seed
        self.spawn = spawn
        self.spawn_facing = spawn_facing        # (dx, dz) a new player faces on arrival; None = south.
        self.chunks = {}                        # (cx,cz) -> Chunk
        self._region_filter = None              # When set to (rx,rz), only blocks in that region are kept.

    # ---- Block writes ----
    def set(self, x, y, z, block):
        cx, cz = x >> 4, z >> 4
        if self._region_filter is not None:
            rx, rz = self._region_filter
            if (cx >> 5) != rx or (cz >> 5) != rz:
                return                          # Another region handles this cell itself.
        c = self.chunks.get((cx, cz))
        if c is None:
            c = self.chunks[(cx, cz)] = Chunk(cx, cz)
        c.set(x & 15, y, z & 15, block)


    # ---- Signs ----
    def sign(self, x, y, z, lines, facing=(0, 1), wood="oak", kind="standing",
             glow=False, color="black", command=None, dialog=None, back=None):
        """Place a sign (see ports.block_sink.SignSink for the interface).

        In 26.2 (DataVersion 4903), text components are native NBT rather than
        JSON strings (changed in 1.21.5), and an NBT list must be of a single
        type: the four lines are either all plain strings or all compounds,
        never mixed. A sign with plain text only is still written as strings
        (byte for byte the same as before the change); only a sign with color,
        bold or a click action is written entirely as compounds.

        The click action goes on the first line's click_event. The game runs
        click_event once for every line of the sign, so it may be on one line
        only; otherwise one click would take two rides. Every sign is waxed:
        right-clicking a waxed sign does not open the edit screen, so the click
        action runs instead.
        """
        x, y, z = int(x), int(y), int(z)
        fx, fz = facing
        rot = int(round(yaw_of(fx, fz) / 22.5)) % 16
        if kind == "wall":
            card = "south" if abs(fz) >= abs(fx) and fz > 0 else \
                   "north" if abs(fz) >= abs(fx) else ("east" if fx > 0 else "west")
            self.set(x, y, z, f"minecraft:{wood}_wall_sign[facing={card},waterlogged=false]")
            be_id = "minecraft:sign"
        elif kind == "hanging":
            # A hanging sign under the ceiling: attached=false means two vertical
            # chains, which accept only the four orthogonal directions.
            rot = (int(round(rot / 4.0)) * 4) % 16
            self.set(x, y, z, f"minecraft:{wood}_hanging_sign"
                              f"[attached=false,rotation={rot},waterlogged=false]")
            be_id = "minecraft:hanging_sign"
        else:
            self.set(x, y, z, f"minecraft:{wood}_sign[rotation={rot},waterlogged=false]")
            be_id = "minecraft:sign"
        c = self.chunks.get((x >> 4, z >> 4))
        if c is None:
            return          # Filtered out by region; that region writes it when it is processed.
        click = None
        if command:
            click = Compound({"action": String("run_command"), "command": String(command)})
        elif dialog:
            click = Compound({"action": String("show_dialog"), "dialog": String(dialog)})
        c.bes[(x, y, z)] = Compound({
            "id": String(be_id),
            "x": Int(x), "y": Int(y), "z": Int(z),
            "keepPacked": Byte(0),
            "is_waxed": Byte(1),                         # Waxed, so players cannot edit the text.
            "front_text": _sign_text(lines, color, glow, click),
            "back_text": _sign_text(back or [], color, glow, None),
        })

    def fill(self, x0, y0, z0, x1, y1, z1, block):
        for x in range(min(x0, x1), max(x0, x1) + 1):
            for y in range(min(y0, y1), max(y0, y1) + 1):
                for z in range(min(z0, z1), max(z0, z1) + 1):
                    self.set(x, y, z, block)

    # ---- Saving ----
    def _write_level(self):
        os.makedirs(os.path.join(self.path, "data", "minecraft"), exist_ok=True)
        data = Compound({
            "DataVersion": Int(DATA_VERSION),
            "Version": Compound({"Snapshot": Byte(0), "Series": String("main"),
                                 "Id": Int(DATA_VERSION), "Name": String("26.2")}),
            "LevelName": String(self.name),
            "GameType": Int(1),                  # Creative mode.
            "allowCommands": Byte(1),
            "initialized": Byte(1),
            "WasModded": Byte(0),
            "LastPlayed": Long(int(time.time() * 1000)),
            "Time": Long(0),
            "version": Int(19133),
            "spawn": Compound({"pos": IntArray(list(self.spawn)),
                               "pitch": Float(0.0),
                               "yaw": Float(yaw_of(*self.spawn_facing) if self.spawn_facing else 0.0),
                               "dimension": String("minecraft:overworld")}),
            "difficulty_settings": Compound({"difficulty": String("normal"),
                                             "hardcore": Byte(0), "locked": Byte(0)}),
            "singleplayer_uuid": IntArray([_u32(), _u32(), _u32(), _u32()]),
            # The ride system's datapack (written to datapacks/ by
            # infrastructure/datapack.py) is listed explicitly as enabled. The
            # game also loads new datapacks that are not on the list, but listing
            # it means not relying on that behavior.
            "DataPacks": Compound({"Enabled": List[String]([String("vanilla"),
                                                            String("file/" + DATAPACK_NAME)]),
                                   "Disabled": List[String]([])}),
            "ServerBrands": List[String]([String("vanilla")]),
        })
        nbtlib.File({"Data": data}, gzipped=True).save(
            os.path.join(self.path, "level.dat"))

        # The superflat settings are derived directly from FLAT_LAYERS, so they
        # match the background of the written chunks.
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
        sector = 2                                    # The first two sectors are the header.
        now = int(time.time())
        for c in chunks:
            buf = io.BytesIO()
            nbtlib.File(c.to_nbt()).write(buf)        # Uncompressed raw NBT.
            blob = zlib.compress(buf.getvalue(), 6)
            payload = struct.pack(">IB", len(blob) + 1, 2) + blob
            payload += b"\0" * ((-len(payload)) % 4096)
            cnt = len(payload) // 4096
            if cnt > 255:
                raise ValueError(f"Chunk {c.cx},{c.cz} exceeds the 1 MB limit")
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
        """Write out a single region, then drop its chunks from memory."""
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
                print(f"  r.{rx}.{rz}.mca  {len(chunks)} chunks  {n/1e6:.1f} MB")
        if verbose:
            print(f"Save complete: {self.path}  ({len(self.chunks)} chunks, {len(regions)} region files)")
