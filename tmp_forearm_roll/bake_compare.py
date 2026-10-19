"""Temporary bake of the independent copy. Does not open the user's scene."""
from __future__ import annotations

import math
import sys

import bpy
from mathutils import Quaternion, Vector

COPY = r"H:\Blender_Plugin\tmp_forearm_roll"
SOURCE = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"
TARGET = r"c:\Users\chenshajie1\Downloads\body.FBX"
ACTION = "a050_300000"
OUT = r"H:\Blender_Plugin\tmp_forearm_roll\temp_preview.blend"


def qdeg(a, b):
    a = a.normalized()
    b = b.normalized()
    return math.degrees(2.0 * math.acos(min(1.0, abs(max(-1.0, min(1.0, a.dot(b)))))))


def twist_about(quat, axis):
    axis = axis.normalized()
    quat = quat.normalized()
    vector = Vector((quat.x, quat.y, quat.z))
    projected = axis * vector.dot(axis)
    twist = Quaternion((quat.w, projected.x, projected.y, projected.z))
    if twist.magnitude < 1e-10:
        return 0.0
    twist.normalize()
    angle = 2.0 * math.acos(max(-1.0, min(1.0, abs(twist.w))))
    if Vector((twist.x, twist.y, twist.z)).dot(axis) < 0.0:
        angle = -angle
    return math.degrees(angle)


def main():
    sys.path.insert(0, COPY)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    from humanoid_retarget import pipeline
    from humanoid_retarget.mapping import build_pairs
    import humanoid_retarget.retarget as retarget

    source, _ = pipeline.load_source(SOURCE)
    objects, _ = pipeline.import_model(TARGET)
    target = pipeline.pick_armature(objects)
    mesh = next(obj for obj in objects if obj.type == "MESH")
    action = next(item for item in retarget.collect_actions(source) if ACTION in item.name)
    retarget._assign_action(source, action)
    pairs = build_pairs(source, target)
    roles = {role: target_name for role, _source_name, target_name in pairs}
    watched = (
        "forearm_l", "forearm_r", "upperarm_l", "upperarm_r",
        "hand_l", "hand_r", "spine", "chest", "neck", "hips",
    )

    def solve(continuity):
        options = retarget.RetargetOptions(
            pairs=pairs, forearm_chain_twist=True, foot_ik=False, hand_ik=False, reference="REST",
        )
        options.forearm_roll_continuity = continuity
        options._forearm_roll_memory = {}
        posed = {}
        for frame in range(0, 53):
            bpy.context.scene.frame_set(frame)
            retarget._apply_body_orientations(source, target, pairs, options)
            posed[frame] = {
                role: target.pose.bones[roles[role]].matrix_basis.to_quaternion().copy()
                for role in watched
            }
            posed[frame]["latched"] = {
                role: (options._forearm_roll_memory.get(role) or {}).get("latched")
                for role in ("forearm_l", "forearm_r")
            }
        return posed

    def solve_order(frames):
        options = retarget.RetargetOptions(
            pairs=pairs, forearm_chain_twist=True, foot_ik=False, hand_ik=False, reference="REST",
        )
        options.forearm_roll_continuity = True
        options._forearm_roll_memory = {}
        posed = {}
        for frame in frames:
            bpy.context.scene.frame_set(frame)
            retarget._apply_body_orientations(source, target, pairs, options)
            posed[frame] = target.pose.bones[roles["forearm_l"]].matrix_basis.to_quaternion().copy()
        return posed

    forward = solve(True)
    repeated = solve(True)
    original = solve(False)
    reverse = solve_order(list(range(52, -1, -1)))
    single = solve_order([39])
    repeat_error = max(
        qdeg(forward[frame][role], repeated[frame][role])
        for frame in range(0, 53) for role in watched
    )
    print("REPEAT_MAX_DEG", round(repeat_error, 8))
    print("REVERSE39_VS_FORWARD", round(qdeg(reverse[39], forward[39]["forearm_l"]), 4))
    print("REVERSE39_VS_P0", round(qdeg(reverse[39], original[39]["forearm_l"]), 4))
    print("SINGLE39_VS_P0", round(qdeg(single[39], original[39]["forearm_l"]), 4))
    print("SINGLE39_VS_FORWARD", round(qdeg(single[39], forward[39]["forearm_l"]), 4))

    def steps(series, role):
        worst = (0.0, None)
        rows = []
        for frame in range(1, 53):
            step = qdeg(series[frame - 1][role], series[frame][role])
            rows.append(step)
            if step > worst[0]:
                worst = (step, frame)
        return worst, rows

    for role in watched:
        worst, rows = steps(forward, role)
        base, _rows = steps(original, role)
        window = max(rows[33:40])
        base_window = max(_rows[33:40])
        dev = max(qdeg(forward[frame][role], original[frame][role]) for frame in range(0, 53))
        dev_30 = max(qdeg(forward[frame][role], original[frame][role]) for frame in range(30, 41))
        print(
            "BONE", role,
            "maxStep", round(worst[0], 3), "at", worst[1],
            "p0MaxStep", round(base[0], 3), "at", base[1],
            "window34_40", round(window, 3),
            "p0Window", round(base_window, 3),
            "maxDev", round(dev, 3),
            "dev30_40", round(dev_30, 3),
        )

    print("LEFT_FRAMES rule rest step roll p0dev dir")
    # Direction and roll need a second pass over stored memory; recompute lightly.
    options = retarget.RetargetOptions(
        pairs=pairs, forearm_chain_twist=True, foot_ik=False, hand_ik=False, reference="REST",
    )
    options.forearm_roll_continuity = True
    options._forearm_roll_memory = {}
    previous = None
    for frame in range(30, 41):
        bpy.context.scene.frame_set(frame)
        retarget._apply_body_orientations(source, target, pairs, options)
        bone = target.pose.bones[roles["forearm_l"]]
        basis = bone.matrix_basis.to_quaternion()
        chain = (
            target.pose.bones[roles["hand_l"]].head - bone.head
        ).normalized()
        desired_error = abs(chain.dot(chain) - 1.0)
        step = 0.0 if previous is None else qdeg(previous, basis)
        roll = 0.0 if previous is None else twist_about(basis @ previous.inverted(), chain)
        dev = qdeg(basis, original[frame]["forearm_l"])
        state = options._forearm_roll_memory.get("forearm_l")
        # Source chain direction versus posed target chain is measured after solve.
        src_chain = (
            source.pose.bones[dict((role, source_name) for role, source_name, _t in pairs)["hand_l"]].head
            - source.pose.bones[dict((role, source_name) for role, source_name, _t in pairs)["forearm_l"]].head
        )
        print(
            frame,
            "latch" if state and state["latched"] else "p0",
            "step", round(step, 3),
            "basisRoll", round(roll, 3),
            "p0dev", round(dev, 3),
            "chain", tuple(round(v, 3) for v in chain),
        )
        previous = basis.copy()
        desired_error = desired_error

    group = {item.name: item.index for item in mesh.vertex_groups}
    forearm = roles["forearm_l"]
    upper = roles["upperarm_l"]

    def weight(vertex, name):
        index = group[name]
        for item in vertex.groups:
            if item.group == index:
                return item.weight
        return 0.0

    blended = [
        vertex.index for vertex in mesh.data.vertices
        if 0.0 < weight(vertex, forearm) < 0.999 and weight(vertex, upper) > 0.0
    ]

    def elbow(continuity, frames):
        options = retarget.RetargetOptions(
            pairs=pairs, forearm_chain_twist=True, foot_ik=False, hand_ik=False, reference="REST",
        )
        options.forearm_roll_continuity = continuity
        options._forearm_roll_memory = {}
        captured = {}
        for frame in frames:
            bpy.context.scene.frame_set(frame)
            retarget._apply_body_orientations(source, target, pairs, options)
            bpy.context.view_layer.update()
            depsgraph = bpy.context.evaluated_depsgraph_get()
            evaluated = mesh.evaluated_get(depsgraph)
            temporary = evaluated.to_mesh()
            world = evaluated.matrix_world.copy()
            points = {index: world @ temporary.vertices[index].co for index in blended}
            evaluated.to_mesh_clear()
            arm_eval = target.evaluated_get(depsgraph)
            bone = arm_eval.matrix_world @ arm_eval.pose.bones[forearm].matrix
            captured[frame] = (points, bone)
        shifts = {}
        for frame in frames[1:]:
            before, bone_before = captured[frame - 1]
            after, bone_after = captured[frame]
            worst = 0.0
            inverse_before = bone_before.inverted()
            inverse_after = bone_after.inverted()
            for index in blended:
                delta = (inverse_before @ before[index]) - (inverse_after @ after[index])
                worst = max(worst, (bone_after.to_3x3() @ delta).length)
            shifts[frame] = worst
        return shifts

    frames = list(range(33, 42))
    new_elbow = elbow(True, frames)
    old_elbow = elbow(False, frames)
    for frame in frames[1:]:
        print("ELBOW", frame, "new", round(new_elbow[frame], 4), "p0", round(old_elbow[frame], 4))

    # Key only the copy's forward result into a new blend file.
    options = retarget.RetargetOptions(
        pairs=pairs, forearm_chain_twist=True, foot_ik=False, hand_ik=False, reference="REST",
    )
    options.forearm_roll_continuity = True
    options._forearm_roll_memory = {}
    preview = bpy.data.actions.new("TMP_forearm_roll_preview")
    preview.use_fake_user = True
    for frame in range(0, 53):
        bpy.context.scene.frame_set(frame)
        retarget._apply_body_orientations(source, target, pairs, options)
        for role in watched:
            target.pose.bones[roles[role]].keyframe_insert(data_path="rotation_quaternion", frame=frame)
    bpy.ops.wm.save_as_mainfile(filepath=OUT)
    print("SAVED", OUT)
    print("DONE")


if __name__ == "__main__":
    main()
