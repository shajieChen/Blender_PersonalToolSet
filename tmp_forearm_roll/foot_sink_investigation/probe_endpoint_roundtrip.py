"""One-clip probe: location/scale round-trip after the endpoint pin, and the frame-5/6 knee flip."""
import sys

import bpy

COPY = r"H:\Blender_Plugin\tmp_forearm_roll"
SOURCE = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"
TARGET = r"c:\Users\chenshajie1\Downloads\body.FBX"


def vec3(value):
    return [round(float(item), 6) for item in value]


def main():
    sys.path.insert(0, COPY)
    for name in list(sys.modules):
        if name == "humanoid_retarget" or name.startswith("humanoid_retarget."):
            del sys.modules[name]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    from humanoid_retarget.mapping import build_pairs
    from humanoid_retarget import pipeline
    import humanoid_retarget.retarget as retarget
    import humanoid_retarget.ik as ik_module
    from humanoid_retarget.foot_ik import FootIKSettings

    source, _ = pipeline.load_source(SOURCE)
    objects, _ = pipeline.import_model(TARGET)
    target = pipeline.pick_armature(objects)
    pairs = build_pairs(source, target)
    roles = {role: (src_name, tgt_name) for role, src_name, tgt_name in pairs}
    actions = {item.name: item for item in retarget.collect_actions(source)}
    holder = {"action": None}
    retarget.collect_actions = lambda _src: [holder["action"]]
    settings = FootIKSettings(floor_enabled=True, floor_alpha=1.0, floor_height_m=0.0)

    real_final = ik_module._apply_calf_roll_final
    real_fold = ik_module._fold_opposes_bind

    def logging_final(tgt, space, reference, goal, lock_endpoints=False):
        role = reference.roles[2]
        frame = bpy.context.scene.frame_current
        mid = tgt.pose.bones[reference.target_names[1]]
        end = tgt.pose.bones[reference.target_names[2]]
        if frame <= 2 and role == "foot_l":
            print("BEFORE", frame, "loc_calf", vec3(mid.location), "loc_foot", vec3(end.location),
                  "scale_calf", vec3(mid.scale), "scale_foot", vec3(end.scale), flush=True)
        real_final(tgt, space, reference, goal, lock_endpoints=lock_endpoints)
        if frame <= 2 and role == "foot_l":
            print("AFTER", frame, "loc_calf", vec3(mid.location), "loc_foot", vec3(end.location),
                  "scale_calf", vec3(mid.scale), "scale_foot", vec3(end.scale), flush=True)

    def logging_fold(tgt, space, upper_name, mid_name, end_name, rest_root, rest_mid, rest_end):
        flipped = real_fold(tgt, space, upper_name, mid_name, end_name, rest_root, rest_mid, rest_end)
        frame = bpy.context.scene.frame_current
        if frame in (5, 6) and end_name == roles["foot_l"][1]:
            world = tgt.matrix_world
            thigh = world @ tgt.pose.bones[upper_name].head
            knee = world @ tgt.pose.bones[mid_name].head
            ankle = world @ tgt.pose.bones[end_name].head
            print("FOLD", frame, "flipped", flipped, "thigh", vec3(thigh), "knee", vec3(knee),
                  "ankle", vec3(ankle), flush=True)
        return flipped

    ik_module._apply_calf_roll_final = logging_final
    ik_module._fold_opposes_bind = logging_fold

    def bake(name, action, foot_ik, hand_ik, roll, mode):
        holder["action"] = action
        retarget._assign_action(source, action)
        ik_module.clear_correction_plan_cache()
        ik_module._CORRECTION_PLAN = None
        ik_module._LAST_PLAN = None
        ik_module._CONTACT_MIN_KNEE_DEG = None
        ik_module.CALF_ROLL_LOG.clear()
        ik_module.ENDPOINT_LOG.clear()
        ik_module.CONTACT_LOG.clear()
        ik_module._CALF_ROLL_FIX_ENABLED = roll
        ik_module._CALF_ROLL_APPLY = mode
        options = retarget.RetargetOptions(
            pairs=pairs, root_motion="KEEP", reference="REST",
            foot_ik=foot_ik, hand_ik=hand_ik,
            foot_ik_settings=settings,
            contact_min_knee_deg=15.0 if foot_ik else 0.0,
            correction_smoothing="height" if foot_ik else "",
        )
        retarget.bake_retarget(source, target, options)
        ik_module._CALF_ROLL_FIX_ENABLED = False
        print("BAKED", name, flush=True)
        shin = roles["shin_l"][1]
        foot = roles["foot_l"][1]
        for frame in (0, 1, 5, 6, 12):
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()
            mid = target.pose.bones[shin]
            end = target.pose.bones[foot]
            world = target.matrix_world
            knee = world @ mid.head
            ankle = world @ end.head
            print("EVAL", name, frame, "len", round((ankle - knee).length, 6),
                  "loc_calf", vec3(mid.location), "loc_foot", vec3(end.location),
                  "scale_calf", vec3(mid.scale), "scale_foot", vec3(end.scale),
                  "knee", vec3(knee), flush=True)

    bake("C_lock", actions["a050_300010"], True, False, True, "bake_lock")
    bake("A_base", actions["a050_300000"], True, False, False, "inline")
    bake("H_both_off", actions["a050_300000"], True, True, False, "inline")
    print("PROBE_DONE", flush=True)


if __name__ == "__main__":
    main()
