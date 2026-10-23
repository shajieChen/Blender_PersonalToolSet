"""Bake identical inputs twice in one process; diff the two baked actions."""
import json
import sys

import bpy

COPY = r"H:\Blender_Plugin\tmp_forearm_roll"
SOURCE = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"
TARGET = r"c:\Users\chenshajie1\Downloads\body.FBX"


def curves_of(action):
    out = {}
    for layer in action.layers:
        for strip in layer.strips:
            bag = getattr(strip, "channelbag", None)
            if callable(bag):
                try:
                    bag = bag(action.slots[0]) if action.slots else bag()
                except Exception:
                    bag = None
            for curve in getattr(bag, "fcurves", []) if bag is not None else []:
                out[(curve.data_path, curve.array_index)] = {
                    round(float(p.co.x), 3): float(p.co.y) for p in curve.keyframe_points
                }
    return out


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
    action = next(item for item in retarget.collect_actions(source) if item.name == "a050_300000")
    retarget.collect_actions = lambda _src: [action]
    pairs = build_pairs(source, target)

    def bake_once():
        options = retarget.RetargetOptions(
            pairs=pairs, root_motion="KEEP", reference="REST",
            foot_ik=True, hand_ik=False,
            foot_ik_settings=FootIKSettings(floor_enabled=True, floor_alpha=1.0, floor_height_m=0.0),
            contact_min_knee_deg=15.0, correction_smoothing="height",
        )
        _report, actions = retarget.bake_retarget(source, target, options)
        return actions[0]

    first = bake_once()
    first_curves = curves_of(first)
    second = bake_once()
    second_curves = curves_of(second)
    print("ACTIONS", first.name, second.name, "cache", len(ik_module._PLAN_CACHE), flush=True)
    diffs = []
    for key in sorted(set(first_curves) | set(second_curves)):
        a = first_curves.get(key, {})
        b = second_curves.get(key, {})
        for frame in sorted(set(a) | set(b)):
            va, vb = a.get(frame), b.get(frame)
            if va is None or vb is None or abs(va - vb) > 1e-6:
                diffs.append((key[0], key[1], frame, va, vb, None if va is None or vb is None else abs(va - vb)))
    print("DIFF_COUNT", len(diffs), flush=True)
    print("MAX_DIFF", max((d[5] or 0) for d in diffs) if diffs else 0.0, flush=True)
    for diff in diffs[:15]:
        print("DIFF", json.dumps(diff), flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
