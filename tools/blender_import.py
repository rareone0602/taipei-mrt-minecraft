"""Rebuild the Taipei Metro network in Blender, for 3D viewing and alignment checks.

Usage:
  /Applications/Blender.app/Contents/MacOS/Blender --background \
      --python tools/blender_import.py -- [--render out.png]

Coordinates: Blender X = east, Y = north, Z = up. Minecraft (x, z) maps to y = -z.
One unit = 1 meter = one Minecraft block.
"""
import bpy, bmesh, json, csv, sys, os

# This script runs under Blender's bundled Python, which cannot see .venv or import the
# mrt package, so it computes its own paths instead of using mrt.config.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LINES = os.path.join(ROOT, "data", "mc_lines.json")
STNS  = os.path.join(ROOT, "data", "mc_stations.csv")

# The OSM colour tag is not always hex, so fall back to Taipei Metro's official colors.
FALLBACK = {"R": "#E3002C", "G": "#008659", "O": "#F8B61C", "BL": "#0070BD",
            "BR": "#C48C31", "Y": "#FFDB00", "A": "#8246AF", "V": "#F5A9BC",
            "K": "#C3B091", "LB": "#6DB7D0"}

def hex_rgb(h, fallback=(0.5, 0.5, 0.5)):
    if not h or not h.startswith("#") or len(h) not in (4, 7):
        return fallback
    if len(h) == 4:
        h = "#" + "".join(c * 2 for c in h[1:])
    try:
        r, g, b = (int(h[i:i+2], 16) / 255 for i in (1, 3, 5))
    except ValueError:
        return fallback
    # sRGB -> linear; Blender works in linear internally.
    lin = lambda c: c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return (lin(r), lin(g), lin(b))

def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for coll in (bpy.data.meshes, bpy.data.curves, bpy.data.materials):
        for blk in list(coll):
            if blk.users == 0:
                coll.remove(blk)

def make_mat(name, rgb, emit=1.5):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = m.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*rgb, 1)
    if "Emission Color" in bsdf.inputs:      # Blender 4.x+
        bsdf.inputs["Emission Color"].default_value = (*rgb, 1)
        bsdf.inputs["Emission Strength"].default_value = emit
    m.diffuse_color = (*rgb, 1)              # For solid shading in the viewport.
    return m

def add_line(ref, variant, mat, radius=8.0):
    """Turn a line's polyline into a curve with thickness."""
    cu = bpy.data.curves.new(f"{ref}_curve", type="CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = radius
    cu.bevel_resolution = 2
    sp = cu.splines.new("POLY")
    pts = variant["points"]
    sp.points.add(len(pts) - 1)
    for i, (x, z) in enumerate(pts):
        sp.points[i].co = (x, -z, 0.0, 1.0)   # MC z (south +) -> Blender y (north +)
    ob = bpy.data.objects.new(f"line_{ref}", cu)
    ob.data.materials.append(mat)
    bpy.context.collection.objects.link(ob)
    return ob

def add_stations(rows, mat, radius=22.0):
    """Merge all stations into a single mesh to avoid hundreds of objects."""
    bm = bmesh.new()
    for x, z in rows:
        m = bmesh.new()
        bmesh.ops.create_uvsphere(m, u_segments=10, v_segments=6, radius=radius)
        bmesh.ops.translate(m, verts=m.verts, vec=(x, -z, 0.0))
        me = bpy.data.meshes.new("tmp"); m.to_mesh(me); m.free()
        bm.from_mesh(me); bpy.data.meshes.remove(me)
    me = bpy.data.meshes.new("stations_mesh"); bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new("stations", me)
    ob.data.materials.append(mat)
    bpy.context.collection.objects.link(ob)
    return ob

def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    render_to = argv[argv.index("--render") + 1] if "--render" in argv else None

    if not os.path.exists(LINES):
        raise SystemExit(f"{LINES} not found. Run scripts/to_minecraft.py first.")

    clear_scene()
    lines = json.load(open(LINES, encoding="utf-8"))
    all_pts = []

    picked = []
    for ref, variants in sorted(lines.items()):
        v = max(variants, key=lambda v: len(v["points"]))
        if not v["points"]:
            print(f"  Line {ref:<3} has no geometry; skipped")
            continue
        picked.append((ref, v))
        all_pts += v["points"]

    if not all_pts:
        raise SystemExit("No line has any points. Check data/lines/*.json first.")

    # Line width and station radius must scale with the scene's span: when a 23 km network
    # is rendered at 1400 px, a fixed 8 m line width is only 0.5 pixels and the whole line
    # disappears.
    _xs = [p[0] for p in all_pts]; _zs = [p[1] for p in all_pts]
    scene_span = max(max(_xs) - min(_xs), max(_zs) - min(_zs))
    line_r = max(8.0, scene_span / 900)
    stn_r  = line_r * 2.6

    for ref, v in picked:
        rgb = hex_rgb(v.get("colour"), hex_rgb(FALLBACK.get(ref, ""), (0.5, 0.5, 0.5)))
        add_line(ref, v, make_mat(f"mat_{ref}", rgb), radius=line_r)
        print(f"  Line {ref:<3} {len(v['points']):>5} points")

    stn_rows = []
    if os.path.exists(STNS):
        with open(STNS, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                stn_rows.append((int(r["mc_x"]), int(r["mc_z"])))
        add_stations(stn_rows, make_mat("mat_station", (0.9, 0.9, 0.9), emit=2.0), radius=stn_r)

    # Camera: an orthographic top-down view framing the whole network.
    if all_pts:
        xs = [p[0] for p in all_pts]; zs = [p[1] for p in all_pts]
        cx, cy = (min(xs)+max(xs))/2, -(min(zs)+max(zs))/2
        span = max(max(xs)-min(xs), max(zs)-min(zs)) * 1.08
        cam_d = bpy.data.cameras.new("cam"); cam_d.type = "ORTHO"
        cam_d.ortho_scale = span
        cam_d.clip_start = 1.0
        cam_d.clip_end = 100000.0     # The camera is at z=20000, and the default
                                      # clip_end=100 would clip the whole scene.
        cam = bpy.data.objects.new("cam", cam_d)
        cam.location = (cx, cy, 20000); cam.rotation_euler = (0, 0, 0)
        bpy.context.collection.objects.link(cam)
        bpy.context.scene.camera = cam
        print(f"\nNetwork extent X[{min(xs)},{max(xs)}] Z[{min(zs)},{max(zs)}]  "
              f"span {max(xs)-min(xs)} x {max(zs)-min(zs)} blocks")

    sc = bpy.context.scene
    sc.render.engine = "BLENDER_WORKBENCH"
    sc.render.resolution_x = sc.render.resolution_y = 1400
    sc.render.film_transparent = False
    sc.world = sc.world or bpy.data.worlds.new("World")
    sc.world.color = (0.02, 0.02, 0.03)
    sh = sc.display.shading
    sh.light = "FLAT"; sh.color_type = "MATERIAL"; sh.background_type = "WORLD"

    out_blend = os.path.join(ROOT, "data", "taipei_mrt.blend")
    bpy.ops.wm.save_as_mainfile(filepath=out_blend)
    print(f"\nSaved {out_blend}  ({len(lines)} lines, {len(stn_rows)} stations)")

    if render_to:
        sc.render.filepath = os.path.abspath(render_to)
        bpy.ops.render.render(write_still=True)
        print(f"Rendered {sc.render.filepath}")

main()
