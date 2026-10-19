"""Print left-forearm basis steps for the copy. No mesh, no save."""
import math
import sys
import bpy

COPY = r"H:\Blender_Plugin\tmp_forearm_roll"
SOURCE = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"
TARGET = r"c:\Users\chenshajie1\Downloads\body.FBX"


def qdeg(a, b):
    a = a.normalized()
    b = b.normalized()
    return math.degrees(2 * math.acos(min(1.0, abs(a.dot(b)))))


def main():
    sys.path.insert(0, COPY)
    for name in list(sys.modules):
        if name == "humanoid_retarget" or name.startswith("humanoid_retarget."):
            del sys.modules[name]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    from humanoid_retarget.mapping import build_pairs
    from humanoid_retarget import pipeline
    import humanoid_retarget.retarget as retarget

    source, _ = pipeline.load_source(SOURCE)
    objects, _ = pipeline.import_model(TARGET)
    target = pipeline.pick_armature(objects)
    action = next(item for item in retarget.collect_actions(source) if item.name == "a050_300000")
    retarget._assign_action(source, action)
    pairs = build_pairs(source, target)
    roles = {role: tgt for role, _src, tgt in pairs}
    options = retarget.RetargetOptions(pairs=pairs, forearm_chain_twist=True, foot_ik=False, hand_ik=False)
    options.forearm_roll_continuity = True
    options._forearm_roll_range = (0, 52)
    options._forearm_roll_cache = None
    prev = None
    for frame in range(0, 53):
        bpy.context.scene.frame_set(frame)
        retarget._apply_body_orientations(source, target, pairs, options)
        quat = target.pose.bones[roles["forearm_l"]].matrix_basis.to_quaternion()
        step = 0.0 if prev is None else qdeg(prev, quat)
        if frame in (1, 19, 20, 33, 34, 35, 36, 37, 38, 39, 40) or step > 25:
            print("STEP", frame, round(step, 3))
        prev = quat.copy()
    print("DONE")


if __name__ == "__main__":
    main()
