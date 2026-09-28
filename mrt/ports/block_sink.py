#!/usr/bin/env python3
"""BlockSink: the only "world" interface the generators need to know.

The domain and application layers should not know what Anvil region files, nbtlib
or the 26.2 world-save layout look like; all they need is "put a block at (x, y, z)".
Every function that builds something takes a BlockSink, and the cli layer decides
what is actually passed in.

The implementation is World in infrastructure/mcworld.py; tests just pass a dict
(the self-test in application/landmarks.py runs exactly that way, with no world save).

Every generator used to `from mcworld import World` only so that its main() could open
a world save. The functions that actually build things already took w as their first
argument, so the interface already existed; it had just never been stated.
"""
try:                                    # Protocol is 3.8+; used here only for type annotations
    from typing import Protocol, runtime_checkable
except ImportError:                     # pragma: no cover
    Protocol = object

    def runtime_checkable(c):
        return c


@runtime_checkable
class BlockSink(Protocol):
    """Something that accepts blocks."""

    def set(self, x, y, z, block):
        """Set (x, y, z) to block (such as "minecraft:stone", optionally with block states).

        The implementation discards coordinates outside the range it is currently
        processing. Streaming generation relies on this for clipping, so callers need
        not work out which region a block falls in.
        """


@runtime_checkable
class ChunkSink(Protocol):
    """Batch writes of a whole section (16x16x16).

    A world with full terrain has hundreds of millions of blocks, and calling set()
    once per block never finishes. Terrain generation instead uses numpy to compute
    the encoded array of a whole section at once and hands it over. This is a second
    entry point forced by performance, not another abstraction.
    """

    def set_section(self, sy, codes, names):
        """sy is the section index (y >> 4); codes is a 16x16x16 array of indices,
        and names is the list of block names those indices refer to."""


@runtime_checkable
class SignSink(Protocol):
    """A BlockSink that can place signs.

    A line of text is either a plain string or dict(text=..., color=..., bold=..., italic=...),
    where color is "#rrggbb" or a Minecraft color name. If any line of a sign is a dict,
    or the sign carries a click action, the implementation must write all four lines as
    text components (an NBT list must hold a single type).
    """

    def sign(self, x, y, z, lines, facing=(0, 1), wood="oak", kind="standing",
             glow=False, color="black", command=None, dialog=None, back=None):
        """Place a sign.

        facing   Direction of the sign face (dx, dz): the reader stands on this side of the sign
        kind     "standing" (on a post), "wall" (wall-mounted) or "hanging"
        glow     Glow ink: readable in the dark
        command  Command run with the sign's permissions when the sign is right-clicked (no slash)
        dialog   Dialog id opened when the sign is right-clicked (such as "mrt:network")
        back     Four lines for the back (same format as lines); None leaves it blank
        """


def plain_text(item):
    """Return the plain text of one sign line: the text of a dict, otherwise str()."""
    if isinstance(item, dict):
        return str(item.get("text", ""))
    return str(item)


class DictSink:
    """A BlockSink that collects blocks in a dict, for tests and geometry checks.

    It does no clipping at all: the tests want to see the complete result the generator computed.
    """

    def __init__(self):
        self.blocks = {}
        self.signs = {}                     # (x, y, z) -> four lines of plain text
        self.sign_meta = {}                 # (x, y, z) -> other arguments (facing, click action...)

    def set(self, x, y, z, block):
        self.blocks[(int(x), int(y), int(z))] = block

    def get(self, x, y, z, default="minecraft:air"):
        return self.blocks.get((int(x), int(y), int(z)), default)

    def sign(self, x, y, z, lines, facing=(0, 1), wood="oak", kind="standing",
             glow=False, color="black", command=None, dialog=None, back=None):
        """Place a sign: the block goes in as usual, and the text is recorded separately
        in signs so that tests can check what a sign says.

        World in infrastructure has a method of the same name (that one actually writes
        NBT). Generators call this interface (SignSink) when placing station name signs,
        so the test sink must have it too.
        """
        suffix = {"wall": "wall_sign", "hanging": "hanging_sign"}.get(kind, "sign")
        key = (int(x), int(y), int(z))
        self.set(x, y, z, "minecraft:%s_%s" % (wood, suffix))
        self.signs[key] = [plain_text(t) for t in list(lines)[:4]]
        self.sign_meta[key] = dict(
            facing=tuple(facing), wood=wood, kind=kind, glow=glow, color=color,
            command=command, dialog=dialog, lines=list(lines)[:4],
            back=[plain_text(t) for t in list(back)[:4]] if back else None)

    def __len__(self):
        return len(self.blocks)

    def bbox(self):
        """Return (x0, z0, x1, z1), or None if empty."""
        if not self.blocks:
            return None
        xs = [k[0] for k in self.blocks]
        zs = [k[2] for k in self.blocks]
        return min(xs), min(zs), max(xs), max(zs)
