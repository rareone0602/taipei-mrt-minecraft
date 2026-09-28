#!/usr/bin/env python3
"""Write a datapack spec (the plain data produced by application/ride_plan.py) as an MC 26.2 datapack.

The 26.2 datapack layout (folder names are always singular since 1.21):
    <save>/datapacks/<name>/pack.mcmeta
    <save>/datapacks/<name>/data/<namespace>/function/<path>.mcfunction
    <save>/datapacks/<name>/data/<namespace>/dialog/<path>.json
    <save>/datapacks/<name>/data/<tag namespace>/tags/function/<tag>.json
    <save>/datapacks/<name>/data/<tag namespace>/tags/dialog/<tag>.json
    <save>/datapacks/<name>/data/minecraft/dimension_type/overworld.json   world height

The pack.mcmeta version number is a detail of this layer (in the same class as
mcworld.DATA_VERSION): the 26.2 version.json has data_major 107, data_minor 1.
Since 1.21.9, pack.mcmeta uses min_format / max_format (an integer or
[major, minor]) instead of pack_format; an integer max_format means 107.*, so
later minor revisions are accepted too. Whether the game actually accepts it is
proven by tools/check_datapack.py, which has the real game load it once, not
by this comment.
"""
import json
import os
import re
import shutil

from mrt import config

PACK_MIN_FORMAT = [107, 1]      # 26.2
PACK_MAX_FORMAT = 107           # 107.*

# The vanilla 26.2 overworld dimension type (data/minecraft/dimension_type/
# overworld.json, exported from the game jar by net.minecraft.data.Main
# --server), with only the height and the clouds changed:
#   - min_y / height / logical_height follow config's vertical world range
#     (Taipei 101 reaches y≈580).
#   - The clouds were at y192.33, only 125 blocks above the basin floor: from
#     the 89th-floor observatory of Taipei 101 (y≈450), looking down would show
#     a sheet of cloud covering the city. They are raised to 600.33, above both
#     the observatory and the roof.
# The dialogs in the same datapack already make the world's registry lifecycle
# experimental (every registry entry from a non-vanilla datapack does; see
# ResourceManagerRegistryLoadTask), so one more dimension type adds no extra
# prompt when the world is opened.
CLOUD_HEIGHT = 600.33
_OVERWORLD_BASE = {
    "ambient_light": 0.0,
    "attributes": {
        "minecraft:audio/ambient_sounds": {"mood": {
            "block_search_extent": 8, "offset": 2.0, "sound": "minecraft:ambient.cave",
            "tick_delay": 6000}},
        "minecraft:audio/background_music": {
            "creative": {"max_delay": 24000, "min_delay": 12000, "sound": "minecraft:music.creative"},
            "default": {"max_delay": 24000, "min_delay": 12000, "sound": "minecraft:music.game"}},
        "minecraft:gameplay/bed_rule": {
            "can_set_spawn": "always", "can_sleep": "when_dark",
            "error_message": {"translate": "block.minecraft.bed.no_sleep"}},
        "minecraft:gameplay/nether_portal_spawns_piglin": True,
        "minecraft:gameplay/respawn_anchor_works": False,
        "minecraft:visual/ambient_light_color": "#0a0a0a",
        "minecraft:visual/cloud_color": "#ccffffff",
        "minecraft:visual/cloud_height": 192.33,
        "minecraft:visual/fog_color": "#c0d8ff",
        "minecraft:visual/sky_color": "#78a7ff",
    },
    "coordinate_scale": 1.0,
    "default_clock": "minecraft:overworld",
    "has_ceiling": False,
    "has_ender_dragon_fight": False,
    "has_skylight": True,
    "height": 384,
    "infiniburn": "#minecraft:infiniburn_overworld",
    "logical_height": 384,
    "min_y": -64,
    "monster_spawn_block_light_limit": 0,
    "monster_spawn_light_level": {"type": "minecraft:uniform", "max_inclusive": 7, "min_inclusive": 0},
    "timelines": "#minecraft:in_overworld",
}


def overworld_dimension_type():
    """Return the overworld dimension type.

    It is a copy of vanilla's, with config's height and the raised clouds.
    """
    d = json.loads(json.dumps(_OVERWORLD_BASE))
    d["min_y"] = config.Y_MIN
    d["height"] = d["logical_height"] = config.WORLD_HEIGHT
    d["attributes"]["minecraft:visual/cloud_height"] = CLOUD_HEIGHT
    return d


_PATH_RE = re.compile(r"^[a-z0-9_.\-/]+$")
_ID_RE = re.compile(r"^[a-z0-9_.\-]+:[a-z0-9_.\-/]+$")


def pack_dir(save, name=None):
    return os.path.join(save, "datapacks", name or config.DATAPACK_NAME)


def _check_path(path):
    if not _PATH_RE.match(path) or path.startswith("/") or path.endswith("/") or "//" in path:
        raise ValueError("A resource path may only use a-z0-9_.-/: %r" % path)


def _dump(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.write("\n")


def write_datapack(save, spec, name=None, ns=None):
    """Write spec into <save>/datapacks/<name>/ and return dict(path, functions, dialogs, tags).

    The whole folder is cleared before writing: when the network changes and a
    ride disappears, its old function file must not stay behind for a sign to
    think it still exists. Only this one folder is cleared; the rest of the
    world save is left alone.
    """
    ns = ns or config.DATAPACK_NS
    root = pack_dir(save, name)
    shutil.rmtree(root, ignore_errors=True)
    os.makedirs(root)
    _dump(os.path.join(root, "pack.mcmeta"), {"pack": {
        "description": spec.get("description", ""),
        "min_format": PACK_MIN_FORMAT,
        "max_format": PACK_MAX_FORMAT,
    }})

    data = os.path.join(root, "data")
    for path, lines in spec["functions"].items():
        _check_path(path)
        bad = [ln for ln in lines if "\n" in ln or "\r" in ln]
        if bad:
            raise ValueError("Function %s has a line break inside a command line: %r" % (path, bad[0][:80]))
        fp = os.path.join(data, ns, "function", path + ".mcfunction")
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        with open(fp, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    for path, obj in spec.get("dialogs", {}).items():
        _check_path(path)
        _dump(os.path.join(data, ns, "dialog", path + ".json"), obj)

    ntag = 0
    for kind, tags in spec.get("tags", {}).items():          # kind: "function" / "dialog"
        for tag, values in tags.items():
            if not _ID_RE.match(tag) or any(not _ID_RE.match(v) for v in values):
                raise ValueError("Tag %s has an invalid id: %r" % (tag, values))
            tns, tpath = tag.split(":", 1)
            _dump(os.path.join(data, tns, "tags", kind, tpath + ".json"),
                  {"replace": False, "values": list(values)})
            ntag += 1

    # World height: chunks are written for config.Y_MIN..Y_MAX, and the game must read the same range.
    _dump(os.path.join(data, "minecraft", "dimension_type", "overworld.json"),
          overworld_dimension_type())

    return dict(path=root, functions=len(spec["functions"]),
                dialogs=len(spec.get("dialogs", {})), tags=ntag)
