"""Full-clip bake of the independent copy. Does not touch official files or final_bake.blend."""
from __future__ import annotations

import hashlib
import json
import sys

import bpy

COPY = r"H:\Blender_Plugin\tmp_forearm_roll"
SOURCE = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"
TARGET = r"c:\Users\chenshajie1\Downloads\body.FBX"
ACTION = "a050_300000"
OUT = r"H:\Blender_Plugin\tmp_forearm_roll\acceptance_final\acceptance_bake.blend"
RECORD = r"H:\Blender_Plugin\tmp_forearm_roll\acceptance_final\acceptance_bake_record.json"
OFFICIAL = r"C:\Users\chenshajie1\AppData\Roaming\Blender Foundation\Blender\5.1\scripts\addons\humanoid_retarget\retarget.py"


def digest_bone(action, slot, bone):
    bag = action.layers[0].strips[0].channelbag(slot)
    hasher = hashlib.sha256()
    count = 0
    frames = set()
    for curve in bag.fcurves:
        if f'pose.bones["{bone}"].rotation_quaternion' not in curve.data_path:
            continue
        count += 1
        for key in curve.keyframe_points:
            frames.add(int(round(key.co[0])))
            hasher.update(f"{curve.array_index}:{key.co[0]:.6f},{key.co[1]:.8f};".encode())
    return {"curves": count, "frames": len(frames), "sha256": hasher.hexdigest()}


def main():
    sys.path.insert(0, COPY)
    for name in list(sys.modules):
        if name == "humanoid_retarget" or name.startswith("humanoid_retarget."):
            del sys.modules[name]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    from humanoid_retarget import pipeline
    import humanoid_retarget.retarget as retarget

    print("COPY_FILE", retarget.__file__)
    official = hashlib.sha256(open(OFFICIAL, "rb").read()).hexdigest()
    print("OFFICIAL_SHA", official)
    source, _ = pipeline.load_source(SOURCE)
    objects, _ = pipeline.import_model(TARGET)
    target = pipeline.pick_armature(objects)
    action = next(item for item in retarget.collect_actions(source) if item.name == ACTION)
    retarget.collect_actions = lambda _arm, chosen=action: [chosen]
    options = retarget.RetargetOptions(
        forearm_chain_twist=True,
        foot_ik=False,
        hand_ik=False,
        reference="REST",
        root_motion="KEEP",
        joint_limits=False,
        soft_repulsion=False,
    )
    options.forearm_roll_continuity = True
    report, baked = retarget.bake_retarget(source, target, options)
    print("BAKE_REPORT", report)
    print("BAKED", [item.name for item in baked])
    baked_action = target.animation_data.action
    slot = target.animation_data.action_slot
    bones = (
        "Bip01 L Forearm", "Bip01 R Forearm",
        "Bip01 L UpperArm", "Bip01 R UpperArm",
        "Bip01 L Hand", "Bip01 R Hand",
        "Bip01 Spine", "Bip01 Pelvis",
    )
    digests = {bone: digest_bone(baked_action, slot, bone) for bone in bones}
    for bone, item in digests.items():
        print("DIGEST", bone, item)
    bpy.ops.wm.save_as_mainfile(filepath=OUT)
    record = {
        "file": OUT,
        "copy": retarget.__file__,
        "official_sha256": official,
        "action": baked_action.name,
        "frame_start": bpy.context.scene.frame_start,
        "frame_end": bpy.context.scene.frame_end,
        "forearm_roll_continuity": True,
        "p0_twist_tolerance_deg": None,
        "note": "Sensitive-zone 0.1 degree P0 twist tolerance is not claimed.",
        "digests": digests,
    }
    with open(RECORD, "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2)
    print("SAVED", OUT)
    print("DONE")


if __name__ == "__main__":
    main()
