import sys
from pathlib import Path

import bpy

ROOT = Path(r"H:\Blender_Plugin\tmp_forearm_roll\floor_candidate_root")
sys.path.insert(0, str(ROOT))
for name in list(sys.modules):
    if name == "humanoid_retarget" or name.startswith("humanoid_retarget."):
        del sys.modules[name]

import humanoid_retarget.retarget as retarget
from humanoid_retarget import pipeline
from humanoid_retarget.foot_ik import FootIKSettings
from humanoid_retarget.mapping import build_pairs
from humanoid_retarget.motion_space import build_motion_space

bpy.ops.wm.read_factory_settings(use_empty=True)
source, _ = pipeline.load_source(r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb")
objects, _ = pipeline.import_model(r"c:\Users\chenshajie1\Downloads\body.FBX")
target = pipeline.pick_armature(objects)
pairs = build_pairs(source, target)
tgt_roles = {role: name for role, _s, name in pairs}
src_roles = {role: name for role, name, _t in pairs}
print("target loc", tuple(round(v, 4) for v in target.location), "scale", tuple(target.scale), flush=True)

scene = bpy.context.scene
mpu = scene.unit_settings.scale_length or 1.0
tgt_body = retarget._body_matrix(target, retarget._anatomical_roles(target, tgt_roles))
src_body = retarget._body_matrix(source, retarget._anatomical_roles(source, src_roles))

for floor in (0.0, 0.05, -0.05):
    space = build_motion_space(target, tgt_body, mpu, floor)
    src_space = build_motion_space(source, src_body, mpu, 0.0)
    if floor == 0.0:
        s_lowest = None
        for role in ("foot_l", "foot_r"):
            s_name = src_roles[role]
            s_bone = source.data.bones[s_name]
            for point in retarget._extract_foot_contact_local(source, s_name):
                s_world = source.matrix_world @ (s_bone.matrix_local @ point)
                s_motion = src_space.world_position(s_world)
                s_lowest = s_motion.z if s_lowest is None else min(s_lowest, s_motion.z)
        s_hips = source.data.bones[src_roles["hips"]]
        s_hips_motion = src_space.world_position(source.matrix_world @ s_hips.head_local)
        print("SOURCE sigma_s_world_mm", None if s_lowest is None else round(s_lowest * 1000, 3),
              "hips_mm", round(float(s_hips_motion.z) * 1000, 3),
              "intrinsic_mm", None if s_lowest is None else round((s_hips_motion.z - s_lowest) * 1000, 3), flush=True)
    lowest = None
    detail = {}
    for role in ("foot_l", "foot_r"):
        name = tgt_roles[role]
        bone = target.data.bones[name]
        pts = retarget._extract_foot_contact_local(target, name)
        vals = []
        for point in pts:
            arm_pt = bone.matrix_local @ point
            world = target.matrix_world @ arm_pt
            motion = space.world_position(world)
            vals.append((round(float(world.z) * 1000, 3), round(float(motion.z) * 1000, 3)))
            lowest = motion.z if lowest is None else min(lowest, motion.z)
        detail[role] = vals
    hips = target.data.bones[tgt_roles["hips"]]
    hips_motion = space.world_position(target.matrix_world @ hips.head_local)
    print("floor", floor, "sigma_t_motion_mm", None if lowest is None else round(lowest * 1000, 3),
          "hips_motion_mm", round(float(hips_motion.z) * 1000, 3),
          "intrinsic_mm", None if lowest is None else round((hips_motion.z - lowest) * 1000, 3),
          detail, flush=True)
