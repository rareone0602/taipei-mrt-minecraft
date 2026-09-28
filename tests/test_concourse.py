#!/usr/bin/env python3
"""Unit tests for the underground malls: build a small one in a DictSink and walk it.

No world save is needed. The point is not whether blocks were placed but whether the
result can be walked. This test and tools/verify_concourse.py share the same rules in
domain/walk.py; they differ only in where the blocks come from: an in-memory dict here,
a read-back Anvil world save there. So any problem this test catches is the same problem
in the real world.

Usage: ./.venv/bin/python tests/test_concourse.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mrt.application import build_concourse as BC
from mrt.domain import concourse as CC
from mrt.domain import walk
from mrt.ports.block_sink import DictSink

ok = True
G = 68              # Flat ground
Y = G - 6           # Underground mall standing surface


def chk(name, cond):
    global ok
    print(("  ok   " if cond else "  FAIL ") + name)
    ok = ok and cond


def ways_T():
    """A T junction: an east-west trunk plus a branch heading south. The ways connect only
    because they share node ids."""
    return [
        {"nodes": [1, 2, 3], "points": [[-60, 0], [0, 0], [60, 0]]},
        {"nodes": [2, 4], "points": [[0, 0], [0, 60]]},
    ]


print("Parsing level tags")
chk("-1 -> (-1, -1)", CC.parse_level("-1") == (-1.0, -1.0))
chk("-2--1 is a range, not a subtraction", CC.parse_level("-2--1") == (-2.0, -1.0))
chk("the -0 in -2--0 becomes 0", CC.parse_level("-2--0") == (-2.0, 0.0))
chk("a semicolon list need not be sorted", CC.parse_level("0;-0.5;-1") == (-1.0, 0.0))
chk("a colon is read as a mistyped semicolon", CC.parse_level("-1:0;1") == (-1.0, 1.0))
chk("5A takes the leading number", CC.parse_level("5A") == (5.0, 5.0))
chk("an empty string returns None", CC.parse_level("") is None)
chk("underground is collected", CC.underground({"level": "-1"}))
chk("ground level is not collected", not CC.underground({"level": "0"}))
chk("a department store escalator reaching the ground floor or above is not collected",
    not CC.underground({"level": "-1-4"}))
chk("no level but tagged as a tunnel also counts", CC.underground({"tunnel": "yes"}))

print("Node merging and connectivity")
pos, adj, edges = CC.build_graph(ways_T(), tol=3.0)
chk(f"a T junction has 4 nodes (got {len(pos)})", len(pos) == 4)
chk("the junction node has degree 3", max(len(v) for v in adj.values()) == 3)
chk("only one connected component", len(CC.components(pos, adj)) == 1)

# Unjoined endpoints: 2 m apart should merge, 40 m apart should not
near = ways_T() + [{"nodes": [9, 10], "points": [[62, 0], [90, 0]]}]
pos2, adj2, _ = CC.build_graph(near, tol=3.0)
chk("dangling endpoints 2 m apart are merged", len(CC.components(pos2, adj2)) == 1)
far = ways_T() + [{"nodes": [9, 10], "points": [[100, 0], [130, 0]]}]
pos3, adj3, edges3 = CC.build_graph(far, tol=3.0)
chk("endpoints 40 m apart are not merged", len(CC.components(pos3, adj3)) == 2)
added = CC.bridge_gaps(pos3, adj3, edges3, max_gap=45.0)
chk(f"connected after closing gaps ({len(added)} added)", len(CC.components(pos3, adj3)) == 1)

print("Choosing the main component")
# Directly above Taipei Main Station there is an isolated two-node corridor, which choosing the
# nearest would pick
# The isolated short corridor must be far enough from the main network (within the 3 m merge
# tolerance it would be absorbed)
stray = [{"nodes": [77, 78], "points": [[6, 6], [14, 14]]}] + ways_T()
p4, a4, _ = CC.build_graph(stray, tol=3.0)
grp = CC.main_component(p4, a4, near=(0, 0))
chk(f"picks the largest nearby cluster, not the nearest ({len(grp)} nodes)", len(grp) == 4)

print("Direction of exit stairs")
d = CC.outward(pos, adj, 3, 60, 0)          # The exit is the east end node itself
chk(f"an end-node exit climbs east, away from the corridor {d}", d == (1, 0))
d = CC.outward(pos, adj, 1, -60, 0)
chk(f"the west end node climbs west {d}", d == (-1, 0))

print("Building a small underground mall and walking it")
ents = [("E", 60, 0), ("W", -60, 0), ("S", 0, 60)]
objs, rep = BC.plan(ways_T(), ents, lambda x, z: G, Y, near=(0, 0))
w = DictSink()
for o in objs:
    o.build(w)
chk(f"wrote {len(w.blocks):,} blocks", len(w.blocks) > 5000)
chk(f"all three exits connect ({len(rep['connected'])})", len(rep["connected"]) == 3)
chk(f"no unconnected exits ({rep['orphan']})", not rep["orphan"])
chk(f"built {len(rep['exits'])} exit stairs", len(rep["exits"]) == 3)

get = w.get
bnd = (-90, Y - 10, -30, 90, G + 10, 90)
feet = {}
for ref, x, z in ents:
    feet[ref] = walk.nearest_standable(get, x, Y, z, radius=6, dy=4)
chk("all three exits have somewhere to stand underground", all(feet.values()))

# The key point: every exit must reach every other without going above ground
ug = (-90, Y - 10, -30, 90, G - 2, 90)
comps = walk.components(get, list(feet.values()), bounds=ug)
chk(f"connected as one cluster without going above ground (components: {len(comps)})",
    len(comps) == 1)
dist, _ = walk.flood(get, [feet["E"]], bounds=ug)
chk(f"east end to west end in {dist.get(feet['W'])} steps (120 m in a straight line)",
    dist.get(feet["W"], 0) >= 120)

# Every exit must lead up to the ground
for ref, x, z in ents:
    d2, _ = walk.flood(get, [feet[ref]], bounds=bnd)
    chk(f"{ref} leads up to the ground", any(p[1] >= G for p in d2))

print("The checker catches a broken underground mall")
# Otherwise passing everything above means nothing: wall off the junction, and there must be
# 2 connected components
w2 = DictSink()
for o in objs:
    o.build(w2)
# Wall off the whole cross-section of the east wing (floor and headroom included); the east
# exit should be isolated
for x in (10, 11, 12):
    for z in range(-9, 10):
        for y in range(Y - 1, Y + BC.HEAD + 2):
            w2.set(x, y, z, "minecraft:deepslate_bricks")
comps2 = walk.components(w2.get, list(feet.values()), bounds=ug)
chk(f"splits into {len(comps2)} clusters once the junction is walled off", len(comps2) == 2)

print("Degenerate input")
o0, r0 = BC.plan([], [], lambda x, z: G, Y)
chk("no corridors does not crash and produces no objects", o0 == [] and r0["cells"] == 0)
o1, r1 = BC.plan(ways_T(), [("X", 900, 900)], lambda x, z: G, Y, near=(0, 0))
chk(f"an exit too far away is listed as unconnected ({r1['orphan']})", len(r1["orphan"]) == 1)
o2, r2 = BC.plan(ways_T(), [], lambda x, z: Y, Y, near=(0, 0))
chk("when the ground is lower than the underground mall, the whole run is dropped rather than "
    "built as an open trench", r2["cells"] == 0)

print("\nAll passed" if ok else "\nSome tests failed")
raise SystemExit(0 if ok else 1)
