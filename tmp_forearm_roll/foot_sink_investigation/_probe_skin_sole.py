import bpy, sys
from pathlib import Path
ROOT = Path(r"H:\Blender_Plugin\tmp_forearm_roll\floor_candidate_root")
sys.path.insert(0, str(ROOT))
for name in list(sys.modules):
    if name == "humanoid_retarget" or name.startswith("humanoid_retarget."):
        del sys.modules[name]
from humanoid_retarget import retarget, pipeline

def load():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    src, _ = pipeline.load_source(r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb")
    objects, _ = pipeline.import_model(r"c:\Users\chenshajie1\Downloads\body.FBX")
    tgt = pipeline.pick_armature(objects)
    return src, tgt

def skin_sole_world(arm):
    roles = retarget.classify_armature(arm)
    foot_names = {roles.get("foot_l"), roles.get("foot_r")} - {None}
    meshes = [c for c in arm.children_recursive if c.type == 'MESH']
    lowest = None
    count = 0
    for mesh in meshes:
        groups = {g.name: g.index for g in mesh.vertex_groups}
        idx = {groups[n] for n in foot_names if n in groups}
        if not idx:
            continue
        mw = mesh.matrix_world
        for v in mesh.data.vertices:
            w = max((g.weight for g in v.groups if g.group in idx), default=0.0)
            if w < 0.5:
                continue
            count += 1
            z = float((mw @ v.co).z)
            lowest = z if lowest is None else min(lowest, z)
    return lowest, count, roles

src, tgt = load()
for label, arm in (("SOURCE", src), ("TARGET", tgt)):
    low, n, roles = skin_sole_world(arm)
    hips = arm.data.bones[roles["hips"]]
    hips_w = float((arm.matrix_world @ hips.head_local).z)
    print(label, "skin_sole_world_mm", None if low is None else round(low*1000, 3),
          "footverts", n, "hips_world_mm", round(hips_w*1000, 3),
          "intrinsic_skin_mm", None if low is None else round((hips_w-low)*1000, 3), flush=True)
print("PROBE_DONE", flush=True)
