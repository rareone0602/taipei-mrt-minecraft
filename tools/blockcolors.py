#!/usr/bin/env python3
"""Block -> color: the average color of the block models and textures in the installed
game jar.

verify_render has a hand-picked palette of forty-odd colors and draws every other
texture magenta. An attraction building uses a hundred or more blocks at once (quartz,
terracotta, copper, stained glass in every color...). A hand-picked table cannot keep up,
and a wrong entry would go unnoticed by whoever reads the image. This module follows
the game's own resolution order: the first variant in blockstates/<block>.json
-> models/block/<model>.json (following parent upward) -> texture image -> average color
of the opaque pixels. The top face (top-down maps) and the side face (elevations) are
computed separately: a log's top shows growth rings and its side shows bark.

The textures belong to Mojang. They are read locally only to compute colors and are
never written into the project. The computed table is cached in the temporary directory.
Biome-tinted textures (grass, leaves, vines, water) are grayscale in the jar, so the
plains colors are applied to them.

Usage (as a library):
    bc = BlockColors()            # Without the game, colors are None and the caller decides.
    bc.rgb("minecraft:oak_stairs[facing=east]", face="side") -> (r, g, b) or None
    bc.alpha("minecraft:glass_pane")                          -> coverage from 0 to 1
"""
import io
import json
import os
import re
import tempfile
import zipfile

MC_DIR = os.path.expanduser("~/Library/Application Support/minecraft")
VERSION = "26.2"

# Biome tint (plains): the textures are grayscale, and the game multiplies them by this
# color at run time.
TINT = {
    "grass_block_top": (145, 189, 89), "short_grass": (145, 189, 89), "tall_grass_top": (145, 189, 89),
    "tall_grass_bottom": (145, 189, 89), "fern": (145, 189, 89), "large_fern_top": (145, 189, 89),
    "grass_block_side_overlay": (145, 189, 89), "vine": (119, 171, 47), "lily_pad": (32, 128, 48),
    "oak_leaves": (119, 171, 47), "jungle_leaves": (119, 171, 47), "acacia_leaves": (119, 171, 47),
    "dark_oak_leaves": (119, 171, 47), "mangrove_leaves": (146, 193, 98), "spruce_leaves": (97, 153, 97),
    "birch_leaves": (128, 167, 85), "water_still": (63, 118, 228), "water_flow": (63, 118, 228),
}
TOP_KEYS = ("top", "end", "up", "all", "texture", "cross", "pane", "side", "particle")
SIDE_KEYS = ("side", "all", "texture", "front", "north", "cross", "pane", "end", "particle")
_BS_RE = re.compile(r"^(?:minecraft:)?([a-z0-9_]+)(?:\[(.*)\])?$")


class BlockColors:
    def __init__(self, mc_dir=MC_DIR, version=VERSION, cache_dir=None):
        self.jar_path = os.path.join(mc_dir, "versions", version, version + ".jar")
        self.cache_path = os.path.join(cache_dir or tempfile.gettempdir(),
                                       "mrt_blockcolors_%s.json" % version)
        self.table = {}
        self._zip = None
        if os.path.exists(self.cache_path):
            try:
                self.table = json.load(open(self.cache_path, encoding="utf-8"))
            except (OSError, ValueError):
                self.table = {}
        self.available = os.path.exists(self.jar_path)
        self._dirty = False

    # ---- Reading the jar ----
    def _z(self):
        if self._zip is None:
            self._zip = zipfile.ZipFile(self.jar_path)
        return self._zip

    def _json(self, path):
        try:
            return json.loads(self._z().read(path))
        except KeyError:
            return None

    def _model_textures(self, model):
        """Model id -> texture variable table, merged along parent with the child first and
        #x references resolved."""
        tex = {}
        seen = 0
        while model and seen < 12:
            seen += 1
            name = model.split(":")[-1]
            m = self._json("assets/minecraft/models/%s.json" % name)
            if m is None:
                break
            for k, v in (m.get("textures") or {}).items():
                if isinstance(v, dict):          # 26.2: {"sprite": ..., "force_translucent": ...}
                    v = v.get("sprite")
                tex.setdefault(k, v)
            model = m.get("parent")
        for _ in range(6):
            for k, v in list(tex.items()):
                if isinstance(v, str) and v.startswith("#"):
                    tex[k] = tex.get(v[1:], v)
        return {k: v for k, v in tex.items() if isinstance(v, str) and not v.startswith("#")}

    def _first_model(self, block):
        bs = self._json("assets/minecraft/blockstates/%s.json" % block)
        if bs is None:
            return None
        if "variants" in bs:
            v = next(iter(bs["variants"].values()))
        elif "multipart" in bs:
            v = bs["multipart"][0]["apply"]
        else:
            return None
        if isinstance(v, list):
            v = v[0]
        return v.get("model")

    def _texture_rgba(self, tex):
        """Texture id -> (r, g, b, coverage). Animated textures (frames stacked vertically)
        use only the first frame."""
        from PIL import Image
        name = tex.split(":")[-1]
        if not name.startswith("block/"):
            name = "block/" + name.split("/")[-1]
        try:
            raw = self._z().read("assets/minecraft/textures/%s.png" % name)
        except KeyError:
            return None
        im = Image.open(io.BytesIO(raw)).convert("RGBA")
        w, h = im.size
        if h > w:
            im = im.crop((0, 0, w, w))
        px = list(im.getdata())
        solid = [p for p in px if p[3] > 24]
        if not solid:
            return (0, 0, 0, 0.0)
        r = sum(p[0] for p in solid) / len(solid)
        g = sum(p[1] for p in solid) / len(solid)
        b = sum(p[2] for p in solid) / len(solid)
        a = sum(p[3] for p in solid) / (255.0 * len(px))
        tint = TINT.get(name.split("/")[-1])
        if tint:
            r, g, b = r * tint[0] / 255, g * tint[1] / 255, b * tint[2] / 255
        return (int(r), int(g), int(b), round(a, 3))

    def _resolve(self, block):
        """Block name -> {"top": [r,g,b,a], "side": [r,g,b,a]}, or None if it cannot be
        resolved."""
        if block in ("air", "cave_air", "void_air"):
            return {"top": [0, 0, 0, 0.0], "side": [0, 0, 0, 0.0]}
        if block in ("water", "bubble_column"):
            c = [63, 118, 228, 0.7]
            return {"top": c, "side": c}
        if block == "lava":
            c = [207, 92, 20, 1.0]
            return {"top": c, "side": c}
        model = self._first_model(block)
        tex = self._model_textures(model) if model else {}
        if not tex:
            # Block entities such as signs, banners and chests have only a particle texture in
            # their model, or no model at all, so fall back to the texture of the same name.
            guess = {"particle": "block/" + block}
            for suf, base in (("_wall_hanging_sign", "_planks"), ("_hanging_sign", "_planks"),
                              ("_wall_sign", "_planks"), ("_sign", "_planks")):
                if block.endswith(suf):
                    guess = {"particle": "block/" + block[:-len(suf)] + base}
            tex = guess
        out = {}
        for face, keys in (("top", TOP_KEYS), ("side", SIDE_KEYS)):
            for k in keys:
                if k in tex:
                    c = self._texture_rgba(tex[k])
                    if c is not None:
                        out[face] = list(c)
                        break
        if not out:
            return None
        out.setdefault("top", out.get("side"))
        out.setdefault("side", out.get("top"))
        return out

    def _entry(self, name):
        m = _BS_RE.match(name.strip())
        block = m.group(1) if m else name.split(":")[-1].split("[")[0]
        e = self.table.get(block)
        if e is None and self.available and block not in self.table:
            e = self._resolve(block)
            self.table[block] = e
            self._dirty = True
        return e

    def rgb(self, name, face="top"):
        e = self._entry(name)
        if not e:
            return None
        return tuple(e[face][:3])

    def alpha(self, name, face="top"):
        e = self._entry(name)
        return float(e[face][3]) if e else 1.0

    def save(self):
        if self._dirty:
            try:
                json.dump(self.table, open(self.cache_path, "w", encoding="utf-8"))
            except OSError:
                pass
            self._dirty = False


if __name__ == "__main__":
    import sys
    bc = BlockColors()
    for n in sys.argv[1:] or ["minecraft:oak_stairs[facing=east]", "minecraft:quartz_pillar",
                              "minecraft:blue_glazed_terracotta", "minecraft:glass_pane",
                              "minecraft:grass_block", "minecraft:oak_leaves", "minecraft:pale_oak_wall_sign"]:
        print(n, bc.rgb(n, "top"), bc.rgb(n, "side"), bc.alpha(n))
    bc.save()
