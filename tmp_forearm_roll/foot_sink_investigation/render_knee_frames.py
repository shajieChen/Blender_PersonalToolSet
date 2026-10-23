"""Bake skin-feedback IK (single action) in a fresh scene, print frame 16-19 leg
diagnostics and render those frames. No save of the blend."""
import json
import math
import os
import sys

import bpy

COPY = r"H:\Blender_Plugin\tmp_forearm_roll"
SOURCE = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"
TARGET = r"c:\Users\chenshajie1\Downloads\body.FBX"
OUT = r"H:\Blender_Plugin\tmp_forearm_roll\foot_sink_investigation\knee_frames"


def v3(value):
    return [round(float(item), 4) for item in value]


def angle_deg(a, b, c):
    first = a - b
    second = c - b
    return round(math.degrees(first.angle(second)), 3) if first.length > 1e-9 and second.length > 1e-9 else None


def main():
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    variant = args[0] if args else "S0"
    out_dir = args[1] if len(args) > 1 else OUT
    if len(args) > 2 and "-" in args[2]:
        lo, hi = args[2].split("-", 1)
        render_frames = tuple(range(int(lo), int(hi) + 1))
    else:
        render_frames = (16, 17, 18, 19)
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

    if variant == "S2":
        ik_module._CONTACT_MIN_KNEE_DEG = 25.0
    elif variant == "S3":
        ik_module._CONTACT_MIN_KNEE_DEG = 15.0
    elif variant == "S4":
        ik_module._CONTACT_MIN_KNEE_DEG = 15.0
        ik_module._CONTACT_KNEE_SMOOTH_DEG = 10.0
    elif variant == "T3":
        ik_module._CONTACT_MIN_KNEE_DEG = 15.0
    print("VARIANT", variant, "min_knee", ik_module._CONTACT_MIN_KNEE_DEG, "smooth", ik_module._CONTACT_KNEE_SMOOTH_DEG)

    goal_calls = {}
    if variant == "T3":
        original_solve = ik_module._solve_chain

        def recording_solve(tgt, space, reference, goal, pole_hint=None):
            distance = original_solve(tgt, space, reference, goal, pole_hint=pole_hint)
            goal_calls.setdefault(
                (bpy.context.scene.frame_current, reference.roles[2]), []
            ).append(goal.position.copy())
            return distance

        ik_module._solve_chain = recording_solve

    source, _ = pipeline.load_source(SOURCE)
    objects, _ = pipeline.import_model(TARGET)
    target = pipeline.pick_armature(objects)
    mesh = next(obj for obj in bpy.data.objects if obj.type == "MESH" and obj.parent == target)
    action = next(item for item in retarget.collect_actions(source) if item.name == "a050_300000")
    retarget._assign_action(source, action)
    retarget.collect_actions = lambda _src: [action]
    pairs = build_pairs(source, target)
    roles = {role: (s, t) for role, s, t in pairs}
    options = retarget.RetargetOptions(
        pairs=pairs, root_motion="KEEP", reference="REST",
        foot_ik=True, hand_ik=False,
        foot_ik_settings=FootIKSettings(floor_enabled=True, floor_alpha=1.0, floor_height_m=0.0),
    )
    retarget.bake_retarget(source, target, options)
    if variant == "T3":
        from mathutils import Vector as _Vector

        raw_series = {}
        for (frame, role), calls in goal_calls.items():
            if role in ("foot_l", "foot_r"):
                raw_series[(frame, role)] = calls[-1] - calls[0] if len(calls) >= 2 else _Vector()
        lowest_series = {
            (entry[0], entry[1]): entry[3] for entry in ik_module.CONTACT_LOG
        }
        ik_module._CORRECTION_PLAN = ik_module.build_height_plan(
            raw_series, lowest_series
        )
        ik_module.CONTACT_LOG.clear()
        retarget.bake_retarget(source, target, options)
    log = {(entry[0], entry[1]): entry for entry in ik_module.CONTACT_LOG}

    def world(name):
        return target.matrix_world @ target.pose.bones[name].head

    os.makedirs(out_dir, exist_ok=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "MATERIAL"
    scene.render.resolution_x = 640
    scene.render.resolution_y = 640
    camera_data = bpy.data.cameras.new("DiagCam")
    camera = bpy.data.objects.new("DiagCam", camera_data)
    scene.collection.objects.link(camera)
    camera.location = (0.55, -1.15, 0.42)
    look = camera.location.copy()
    from mathutils import Vector
    direction = Vector((0.02, 0.0, 0.22)) - Vector(camera.location)
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    camera_data.lens = 42
    scene.camera = camera
    sun_data = bpy.data.lights.new("DiagSun", "SUN")
    sun = bpy.data.objects.new("DiagSun", sun_data)
    scene.collection.objects.link(sun)
    sun.rotation_euler = (math.radians(50), 0.0, math.radians(30))
    for obj in bpy.data.objects:
        if obj not in (mesh, camera, sun):
            obj.hide_render = True

    for frame in render_frames:
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        row = {"frame": frame, "hips": v3(world(roles["hips"][1]))}
        for side in ("l", "r"):
            thigh = world(roles["thigh_" + side][1])
            knee = world(roles["shin_" + side][1])
            ankle = world(roles["foot_" + side][1])
            toe_name = next(c.name for c in target.pose.bones[roles["foot_" + side][1]].children if "toe" in c.name.lower())
            toe = world(toe_name)
            entry = log.get((frame, "foot_" + side))
            row[side] = {
                "thigh": v3(thigh), "knee": v3(knee), "ankle": v3(ankle), "toe": v3(toe),
                "knee_deg": angle_deg(thigh, knee, ankle),
                "corrections": None if entry is None else entry[2],
                "raised_m": None if entry is None else entry[6],
                "final_knee_deg": None if entry is None else entry[7],
            }
        print("DIAG", json.dumps(row))
        scene.render.filepath = os.path.join(out_dir, "frame_%02d.png" % frame)
        bpy.ops.render.render(write_still=True)
    print("DONE")


if __name__ == "__main__":
    main()
