"""Fresh-import probe: are Bip01 calf/foot pose scales non-unit before any bake?"""
import sys

import bpy

TARGET = r"c:\Users\chenshajie1\Downloads\body.FBX"
SOURCE = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"

bpy.ops.wm.read_factory_settings(use_empty=True)
sys.path.insert(0, r"H:\Blender_Plugin\tmp_forearm_roll\candidate_root")
for name in list(sys.modules):
    if name == "humanoid_retarget" or name.startswith("humanoid_retarget."):
        del sys.modules[name]
from humanoid_retarget import pipeline

objects, _ = pipeline.import_model(TARGET)
target = pipeline.pick_armature(objects)
print("TARGET", target.name, "action", None if target.animation_data is None or target.animation_data.action is None else target.animation_data.action.name)
for name in ("Bip01 Pelvis", "Bip01 L Thigh", "Bip01 L Calf", "Bip01 L Foot", "Bip01 R Thigh", "Bip01 R Calf", "Bip01 R Foot", "Bip01 Spine"):
    pb = target.pose.bones[name]
    print(" POSE", name, "scale", tuple(round(float(v), 4) for x in pb.scale for v in [x]), "loc", tuple(round(float(v), 4) for v in pb.location))
# edit bone (rest) scale concept does not exist; print bone lengths
for a, b in (("Bip01 L Thigh", "Bip01 L Calf"), ("Bip01 L Calf", "Bip01 L Foot")):
    va = target.matrix_world @ target.data.bones[a].head_local
    vb = target.matrix_world @ target.data.bones[b].head_local
    print(" REST world len", a, "->", b, round((vb - va).length, 4))

source, _ = pipeline.load_source(SOURCE)
print("SOURCE", source.name)
for name in ("Pelvis", "L_Thigh", "L_Calf", "L_Foot", "R_Calf", "R_Foot"):
    if name in source.pose.bones:
        pb = source.pose.bones[name]
        print(" SRC POSE", name, "scale", tuple(round(float(v), 4) for v in pb.scale))
print("PROBE_DONE")
