"""在 Blender 中重建台北捷運路網（3D 檢視／線形驗證用）

用法:
  /Applications/Blender.app/Contents/MacOS/Blender --background \
      --python tools/blender_import.py -- [--render out.png]

座標: Blender X = 東, Y = 北, Z = 上。與 Minecraft 的 (x, z) 對應為 y = -z。
單位 1 = 1 公尺 = 1 個 Minecraft 方塊。
"""
import bpy, bmesh, json, csv, sys, os, math

# 這支跑在 Blender 內建的 Python 底下，看不到 .venv 也 import 不到 mrt 套件，
# 所以路徑自己算，不用 mrt.config。
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LINES = os.path.join(ROOT, "data", "mc_lines.json")
STNS  = os.path.join(ROOT, "data", "mc_stations.csv")

# OSM colour 標籤不一定是 hex，補上北捷官方色
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
    # sRGB -> linear，Blender 內部用 linear
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
    m.diffuse_color = (*rgb, 1)              # 視窗實體著色用
    return m

def add_line(ref, variant, mat, radius=8.0):
    """把一條路線的折線做成有厚度的曲線"""
    cu = bpy.data.curves.new(f"{ref}_curve", type="CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = radius
    cu.bevel_resolution = 2
    sp = cu.splines.new("POLY")
    pts = variant["points"]
    sp.points.add(len(pts) - 1)
    for i, (x, z) in enumerate(pts):
        sp.points[i].co = (x, -z, 0.0, 1.0)   # MC z(南+) -> Blender y(北+)
    ob = bpy.data.objects.new(f"line_{ref}", cu)
    ob.data.materials.append(mat)
    bpy.context.collection.objects.link(ob)
    return ob

def add_stations(rows, mat, radius=22.0):
    """所有車站合併成單一 mesh，避免上百個物件"""
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
        raise SystemExit(f"找不到 {LINES}，請先跑 scripts/to_minecraft.py")

    clear_scene()
    lines = json.load(open(LINES))
    all_pts = []

    picked = []
    for ref, variants in sorted(lines.items()):
        v = max(variants, key=lambda v: len(v["points"]))
        if not v["points"]:
            print(f"  線 {ref:<3} 無幾何資料，略過")
            continue
        picked.append((ref, v))
        all_pts += v["points"]

    if not all_pts:
        raise SystemExit("所有路線都沒有點位，請先確認 data/lines/*.json")

    # 線寬與站點半徑必須隨場景跨距縮放：23km 的路網算成 1400px 時
    # 固定 8m 的線寬只有 0.5 像素，會整條看不見。
    _xs = [p[0] for p in all_pts]; _zs = [p[1] for p in all_pts]
    scene_span = max(max(_xs) - min(_xs), max(_zs) - min(_zs))
    line_r = max(8.0, scene_span / 900)
    stn_r  = line_r * 2.6

    for ref, v in picked:
        rgb = hex_rgb(v.get("colour"), hex_rgb(FALLBACK.get(ref, ""), (0.5, 0.5, 0.5)))
        add_line(ref, v, make_mat(f"mat_{ref}", rgb), radius=line_r)
        print(f"  線 {ref:<3} {len(v['points']):>5} 點")

    stn_rows = []
    if os.path.exists(STNS):
        with open(STNS) as f:
            for r in csv.DictReader(f):
                stn_rows.append((int(r["mc_x"]), int(r["mc_z"])))
        add_stations(stn_rows, make_mat("mat_station", (0.9, 0.9, 0.9), emit=2.0), radius=stn_r)

    # 相機：正射投影俯視，框住整個路網
    if all_pts:
        xs = [p[0] for p in all_pts]; zs = [p[1] for p in all_pts]
        cx, cy = (min(xs)+max(xs))/2, -(min(zs)+max(zs))/2
        span = max(max(xs)-min(xs), max(zs)-min(zs)) * 1.08
        cam_d = bpy.data.cameras.new("cam"); cam_d.type = "ORTHO"
        cam_d.ortho_scale = span
        cam_d.clip_start = 1.0
        cam_d.clip_end = 100000.0     # 相機在 z=20000，預設 clip_end=100 會把場景全裁掉
        cam = bpy.data.objects.new("cam", cam_d)
        cam.location = (cx, cy, 20000); cam.rotation_euler = (0, 0, 0)
        bpy.context.collection.objects.link(cam)
        bpy.context.scene.camera = cam
        print(f"\n路網範圍 X[{min(xs)},{max(xs)}] Z[{min(zs)},{max(zs)}]  "
              f"跨距 {max(xs)-min(xs)} x {max(zs)-min(zs)} 方塊")

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
    print(f"\n已存檔 {out_blend}  ({len(lines)} 條線, {len(stn_rows)} 站)")

    if render_to:
        sc.render.filepath = os.path.abspath(render_to)
        bpy.ops.render.render(write_still=True)
        print(f"已算圖 {sc.render.filepath}")

main()
