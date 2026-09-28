#!/usr/bin/env python3
"""Read a box-shaped volume of blocks back from an Anvil world save.

The writing half lives in mcworld.py. The reading half used to be written
three times over in tools/ (verify_rails scans rails, verify_render scans the
ground surface, slice_world scans cross-sections), with nearly identical
palette decoding and bit unpacking. Verifying the underground malls needs
"look up the block at any coordinate", which differs from all three scans, so
the shared parts live here.

Region file format: the first 4 KB is 1024 (offset, sectors) entries; after
that, each chunk is a 4-byte length + a 1-byte compression type + compressed
NBT. Blocks are stored in sections[].block_states as a palette plus
bit-packed indices; since 1.16, no index spans two longs.
"""
import glob
import io
import os
import zlib

import numpy as np
import nbtlib

AIR = "minecraft:air"


def unpack(data, bits, n=4096):
    """Unpack a bit-packed index array into n indices. Indices do not span longs (the format since 1.16)."""
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
    """Map block_states to a list of names with block states, in palette index order."""
    out = []
    for e in bs["palette"]:
        name = str(e["Name"])
        if "Properties" in e:
            props = ",".join(f"{k}={v}" for k, v in e["Properties"].items())
            name += f"[{props}]"
        out.append(name)
    return out


class Volume:
    """A box-shaped volume of blocks, stored as int16 palette indices.

    1400 x 900 x 32 is about 40 M cells = 80 MB, and a lookup is a plain array
    index. Anything outside the volume reads as air: the caller (walk.flood)
    bounds its own search, so this class need not tell "outside" from "empty".
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
        """Return the number of blocks that match; predicate takes a block name."""
        keep = np.array([bool(predicate(n)) for n in self.names])
        return int(keep[self.data].sum())

    def __len__(self):
        return int((self.data != 0).sum())


def _region_dir(save, region_dir=None):
    rdir = region_dir or os.path.join(save, "dimensions", "minecraft",
                                      "overworld", "region")
    if not os.path.isdir(rdir):                 # The old layout from before 26.2.
        rdir = os.path.join(save, "region")
    return rdir


def _parse_chunk(raw, i):
    """Return the root Compound of chunk i in the region file contents raw, or None if the chunk is absent."""
    off = int.from_bytes(raw[i * 4:i * 4 + 3], "big")
    if off == 0:
        return None
    q = off * 4096
    ln = int.from_bytes(raw[q:q + 4], "big")
    blob = raw[q + 5:q + 4 + ln]
    root = nbtlib.File.parse(io.BytesIO(
        zlib.decompress(blob) if raw[q + 4] == 2 else blob))
    return root[''] if '' in root else root


def iter_chunks(rdir, x0, z0, x1, z1):
    """Visit the chunks that intersect [x0,x1] x [z0,z1], yielding (cx, cz, root Compound)."""
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
            root = _parse_chunk(raw, i)
            if root is not None:
                yield cx, cz, root


def chunk_coords(save, region_dir=None):
    """Return the chunks actually written in the save, as [(cx, cz)].

    Reads only the 4 KB index at the start of each region file."""
    rdir = _region_dir(save, region_dir)
    out = []
    for path in sorted(glob.glob(os.path.join(rdir, "r.*.*.mca"))):
        try:
            rx, rz = (int(t) for t in os.path.basename(path)[2:-4].split("."))
        except ValueError:
            continue
        with open(path, "rb") as f:
            head = f.read(4096)
        if len(head) < 4096:
            continue
        for i in range(1024):
            if int.from_bytes(head[i * 4:i * 4 + 3], "big"):
                out.append((rx * 32 + (i % 32), rz * 32 + (i // 32)))
    return out


def read_chunks(save, coords, region_dir=None):
    """Read back the given chunks, yielding (cx, cz, root Compound). Each region file is read once."""
    rdir = _region_dir(save, region_dir)
    by_region = {}
    for cx, cz in coords:
        by_region.setdefault((cx >> 5, cz >> 5), []).append((cx, cz))
    for (rx, rz), cs in sorted(by_region.items()):
        path = os.path.join(rdir, f"r.{rx}.{rz}.mca")
        if not os.path.exists(path):
            continue
        raw = open(path, "rb").read()
        if len(raw) < 8192:
            continue
        for cx, cz in sorted(cs):
            root = _parse_chunk(raw, (cx & 31) + (cz & 31) * 32)
            if root is not None:
                yield cx, cz, root


def section_blocks(sec):
    """Return a section's blocks as (palette names, 4096 indices in (y,z,x) order).

    Returns None if the section has no block_states."""
    if "block_states" not in sec:
        return None
    bs = sec["block_states"]
    pal = palette_names(bs)
    if "data" in bs and len(bs["data"]):
        idx = unpack(bs["data"], max(4, (len(pal) - 1).bit_length()))
    else:
        idx = np.zeros(4096, dtype=np.int64)
    return pal, idx


def component_text(m):
    """Convert a text component to plain text.

    A plain string is returned as is; a compound gives its text followed by extra.
    """
    if isinstance(m, dict):
        s = str(m.get("text", ""))
        for e in m.get("extra", ()):
            s += component_text(e)
        return s
    return str(m)


def _click_of(messages):
    """Return the first click_event among the four lines, or None.

    The result has the form {"action": ..., "command"/"dialog": ...}.
    """
    for m in messages:
        if isinstance(m, dict) and "click_event" in m:
            return {str(k): str(v) for k, v in m["click_event"].items()}
    return None


def read_sign_entities(save, x0, z0, x1, z1, region_dir=None, ids=("minecraft:sign",
                                                                    "minecraft:hanging_sign")):
    """Read back the full contents of every sign in the area: [dict(x, y, z, id, front, back, click, glow)].

    front / back are four lines of plain text, and click is the first click
    action on the front. The ride-sign verifier uses this: where a sign says a
    click will take you must match the function in the datapack and a platform
    at that station that can actually be stood on.
    """
    rdir = _region_dir(save, region_dir)
    out = []
    for cx, cz, root in iter_chunks(rdir, x0, z0, x1, z1):
        for be in root.get("block_entities", ()):
            bid = str(be.get("id", ""))
            if bid not in ids:
                continue
            x, y, z = int(be["x"]), int(be["y"]), int(be["z"])
            if not (x0 <= x <= x1 and z0 <= z <= z1):
                continue
            ft, bt = be.get("front_text", {}), be.get("back_text", {})
            fm = list(ft.get("messages", []))
            out.append(dict(x=x, y=y, z=z, id=bid,
                            front=[component_text(m) for m in fm],
                            back=[component_text(m) for m in bt.get("messages", [])],
                            click=_click_of(fm),
                            glow=bool(int(ft.get("has_glowing_text", 0)))))
    return out


def read_signs(save, x0, z0, x1, z1, region_dir=None):
    """Read back every sign in the area: [(x, y, z, [four lines of text])].

    The text is in the block entity's front_text.messages (native NBT since
    1.21.5, not JSON): a plain-text sign is a list of strings, and a sign with
    color or a click action is a list of compounds; both are flattened to
    plain text here. The exit verifier uses this to find exit kiosks. The
    generator did place the signs, but whether a walkable stair stands next to
    each one is verified from the blocks read back.
    """
    return [(s["x"], s["y"], s["z"], s["front"])
            for s in read_sign_entities(save, x0, z0, x1, z1, region_dir,
                                        ids=("minecraft:sign",))]


def read_volume(save, x0, y0, z0, x1, y1, z1, region_dir=None, verbose=True):
    """Read back the blocks in [x0,x1] x [y0,y1] x [z0,z1], inclusive."""
    rdir = _region_dir(save, region_dir)
    vol = Volume(x0, y0, z0, x1, y1, z1)
    if verbose:
        have = len(glob.glob(os.path.join(rdir, "r.*.mca")))
        nreg = sum(1 for rx in range(x0 >> 9, (x1 >> 9) + 1)
                   for rz in range(z0 >> 9, (z1 >> 9) + 1)
                   if os.path.exists(os.path.join(rdir, f"r.{rx}.{rz}.mca")))
        print(f"  The area covers {nreg} regions ({have} in the save)")

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
            pal, idx = section_blocks(sec)
            if len(pal) == 1 and pal[0] == AIR:
                continue
            ids = np.array([vol.ident(n) for n in pal], dtype=np.int16)
            blk = ids[idx].reshape(16, 16, 16)          # [y][z][x]

            # Intersect with the target volume and copy only the overlap.
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
        print(f"  Read back {nchunk:,} chunks, {len(vol.names)} block types, "
              f"{len(vol):,} non-air cells")
    return vol
