"""Correction-plan cache invalidation matrix (copy only, fresh headless scene).

Each case bakes with correction_smoothing='height' and reports cache keys
before/after, whether the plan was rebuilt, and a hash of the baked action.
No .blend is saved.
"""
import hashlib
import json
import sys

import bpy

COPY = r"H:\Blender_Plugin\tmp_forearm_roll\official_merge_stage"
SOURCE = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"
TARGET = r"c:\Users\chenshajie1\Downloads\body.FBX"


def action_hash(action):
    data = [action.name]
    for layer in action.layers:
        for strip in layer.strips:
            bag = getattr(strip, "channelbag", None)
            if callable(bag):
                try:
                    bag = bag(action.slots[0]) if action.slots else bag()
                except Exception:
                    bag = None
            for curve in getattr(bag, "fcurves", []) if bag is not None else []:
                data.append(curve.data_path + ":" + str(curve.array_index))
                for point in curve.keyframe_points:
                    data.append(repr((round(float(point.co.x), 4), round(float(point.co.y), 5))))
    return hashlib.sha256("\n".join(data).encode()).hexdigest()[:16]


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
    all_actions = list(retarget.collect_actions(source))
    action = next(item for item in all_actions if item.name == "a050_300000")
    other_action = next(item for item in all_actions if item.name != action.name)
    current = {"actions": [action]}
    retarget.collect_actions = lambda _src: list(current["actions"])
    pairs = build_pairs(source, target)

    def make_options(**overrides):
        values = dict(
            pairs=pairs, root_motion="KEEP", reference="REST",
            foot_ik=True, hand_ik=False,
            foot_ik_settings=FootIKSettings(floor_enabled=True, floor_alpha=1.0, floor_height_m=0.0),
            contact_min_knee_deg=15.0, correction_smoothing="height",
        )
        values.update(overrides)
        return retarget.RetargetOptions(**values)

    def bake(label, **overrides):
        before = set(ik_module._PLAN_CACHE)
        retarget._assign_action(source, current["actions"][0])
        report, _ = retarget.bake_retarget(source, target, make_options(**overrides))
        after = set(ik_module._PLAN_CACHE)
        baked = target.animation_data.action
        print("TEST", json.dumps({
            "case": label, "new_keys": len(after - before),
            "cache_size": len(after), "action_hash": action_hash(baked),
            "baked_range": [int(baked.frame_range[0]), int(round(baked.frame_range[1]))],
        }), flush=True)
        return action_hash(baked)

    base_hash = bake("1a_first_bake")
    again_hash = bake("1b_same_inputs_rebake")
    print("CHECK same_inputs_identical", again_hash == base_hash, flush=True)

    # Case 2: frame range is part of the signature (bake-level range change is
    # covered by case 3, whose action has a different range).
    opts = make_options()
    sig_full = retarget._correction_plan_signature(
        source, target, action, (0, 52), pairs, opts, opts.foot_ik_settings, 1.0 / 30.0
    )
    sig_short = retarget._correction_plan_signature(
        source, target, action, (0, 30), pairs, opts, opts.foot_ik_settings, 1.0 / 30.0
    )
    print("CHECK frame_range_in_signature", bool(sig_full) and sig_full != sig_short, flush=True)
    print("OTHER_ACTION_RANGE", list(other_action.frame_range), flush=True)

    # Case 3: different source action.
    current["actions"] = [other_action]
    bake("3_other_source_action", pairs=pairs)
    current["actions"] = [action]

    # Case 4: modified source root displacement (hips location curve +0.1 at one key).
    modified = action.copy()
    modified.name = action.name + "_rootmod"
    touched = 0
    hips_name = next(s for role, s, t in pairs if role == "hips")
    for layer in modified.layers:
        for strip in layer.strips:
            bag = getattr(strip, "channelbag", None)
            if callable(bag):
                try:
                    bag = bag(modified.slots[0]) if modified.slots else bag()
                except Exception:
                    bag = None
            for curve in getattr(bag, "fcurves", []) if bag is not None else []:
                if hips_name in curve.data_path and curve.data_path.endswith("location") and curve.array_index == 2:
                    for point in curve.keyframe_points:
                        if 16.0 <= point.co.x <= 18.0:
                            point.co.y += 0.1
                            touched += 1
    print("ROOTMOD touched_points", touched, flush=True)
    current["actions"] = [modified]
    rootmod_hash = bake("4_modified_root_displacement")
    print("CHECK rootmod_differs", rootmod_hash != base_hash, flush=True)
    current["actions"] = [action]

    # Case 5a: changed mapping (drop one non-leg pair).
    reduced_pairs = [pair for pair in pairs if pair[0] not in ("spine",)]
    bake("5a_mapping_changed", pairs=reduced_pairs)
    # Case 5b: changed target rest pose (move one thigh edit bone head).
    bpy.context.view_layer.objects.active = target
    target.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    thigh_t = next(t for role, s, t in pairs if role == "thigh_l")
    target.data.edit_bones[thigh_t].head.z += 0.02
    bpy.ops.object.mode_set(mode="OBJECT")
    bake("5b_target_rest_changed")

    # Case 6: floor height and knee threshold changes.
    bake("6a_floor_height_changed", foot_ik_settings=FootIKSettings(floor_enabled=True, floor_alpha=1.0, floor_height_m=0.05))
    bake("6b_knee_threshold_changed", contact_min_knee_deg=20.0)
    bake("6c_floor_disabled", foot_ik_settings=FootIKSettings(floor_enabled=False, floor_alpha=1.0, floor_height_m=0.0))

    # Case 7: clear the plan cache, then rebake the original inputs.
    ik_module.clear_correction_plan_cache()
    print("CACHE_CLEARED size", len(ik_module._PLAN_CACHE), flush=True)
    # Rest changed in 5b stays in effect for this process; rebuild must occur.
    cleared_hash = bake("7_after_cache_clear")
    print("CHECK after_clear_rebuilt", len(ik_module._PLAN_CACHE) >= 1, flush=True)

    # Case 8: interruption during the main bake, then a clean rebake.
    original_apply = retarget.apply_contact_ik

    def exploding(*args, **kwargs):
        if bpy.context.scene.frame_current >= 20:
            raise RuntimeError("simulated interruption at frame 20")
        return original_apply(*args, **kwargs)

    retarget.apply_contact_ik = exploding
    interrupted = False
    try:
        retarget._assign_action(source, action)
        retarget.bake_retarget(source, target, make_options())
    except RuntimeError as exc:
        interrupted = True
        print("INTERRUPTED", str(exc), "plan_global_is_none", ik_module._CORRECTION_PLAN is None, flush=True)
    finally:
        retarget.apply_contact_ik = original_apply
    print("CHECK interruption_raised", interrupted, flush=True)
    partial = target.animation_data.action
    partial_keys = 0
    for layer in partial.layers:
        for strip in layer.strips:
            bag = getattr(strip, "channelbag", None)
            if callable(bag):
                try:
                    bag = bag(partial.slots[0]) if partial.slots else bag()
                except Exception:
                    bag = None
            for curve in getattr(bag, "fcurves", []) if bag is not None else []:
                partial_keys += len(curve.keyframe_points)
    print("PARTIAL_ACTION", partial.name, "keyframe_points", partial_keys, flush=True)
    final_hash = bake("8_rebake_after_interruption")
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
