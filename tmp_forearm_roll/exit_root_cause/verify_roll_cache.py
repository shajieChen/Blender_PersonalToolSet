"""Verify the order-independent forearm roll in the diagnostic copy. Does not save."""
from __future__ import annotations

import math
import sys

import bpy

COPY = r"H:\Blender_Plugin\tmp_forearm_roll"
SOURCE = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"
TARGET = r"c:\Users\chenshajie1\Downloads\body.FBX"
ACTION = "a050_300000"


def qdeg(a, b):
    a = a.normalized()
    b = b.normalized()
    return math.degrees(2.0 * math.acos(min(1.0, abs(max(-1.0, min(1.0, a.dot(b)))))))


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
    mesh = next(obj for obj in objects if obj.type == "MESH")
    action = next(item for item in retarget.collect_actions(source) if item.name == ACTION)
    retarget._assign_action(source, action)
    pairs = build_pairs(source, target)
    roles = {role: (src, tgt) for role, src, tgt in pairs}
    scene = bpy.context.scene
    scene.frame_start = 0
    scene.frame_end = 52
    watched = ("forearm_l", "forearm_r", "upperarm_l", "upperarm_r")
    group = {item.name: item.index for item in mesh.vertex_groups}

    def weight(vertex, name):
        index = group[name]
        for item in vertex.groups:
            if item.group == index:
                return item.weight
        return 0.0

    forearm_name = roles["forearm_l"][1]
    upper_name = roles["upperarm_l"][1]
    blended = [
        vertex.index for vertex in mesh.data.vertices
        if 0.0 < weight(vertex, forearm_name) < 0.999 and weight(vertex, upper_name) > 0.0
    ]

    def capture_elbow():
        depsgraph = bpy.context.evaluated_depsgraph_get()
        evaluated = mesh.evaluated_get(depsgraph)
        temporary = evaluated.to_mesh()
        world = evaluated.matrix_world.copy()
        points = {index: world @ temporary.vertices[index].co for index in blended}
        evaluated.to_mesh_clear()
        arm_eval = target.evaluated_get(depsgraph)
        bone = arm_eval.matrix_world @ arm_eval.pose.bones[forearm_name].matrix
        return points, bone

    def elbow_shift(captured, frame):
        before, bone_before = captured[frame - 1]
        after, bone_after = captured[frame]
        worst = 0.0
        inverse_before = bone_before.inverted()
        inverse_after = bone_after.inverted()
        for index in blended:
            delta = (inverse_before @ before[index]) - (inverse_after @ after[index])
            worst = max(worst, (bone_after.to_3x3() @ delta).length)
        return worst

    def solve(order, cyclic=False, fresh=False):
        options = retarget.RetargetOptions(
            pairs=pairs, forearm_chain_twist=True, foot_ik=False, hand_ik=False,
            reference="REST", root_motion="KEEP", joint_limits=False, soft_repulsion=False,
            forearm_roll_cyclic=cyclic,
        )
        options.forearm_roll_continuity = True
        options._forearm_roll_range = (0, 52)
        options._forearm_roll_cache = None
        poses = {}
        elbows = {}
        dirs = {}
        src_roles = {role: pair[0] for role, pair in roles.items()}
        tgt_roles = {role: pair[1] for role, pair in roles.items()}
        source_body = retarget._body_matrix(source, retarget._anatomical_roles(source, src_roles))
        target_body = retarget._body_matrix(target, retarget._anatomical_roles(target, tgt_roles))
        for frame in order:
            if fresh:
                options._forearm_roll_cache = None
            scene.frame_set(frame)
            retarget._apply_body_orientations(source, target, pairs, options)
            poses[frame] = {
                role: target.pose.bones[roles[role][1]].matrix_basis.to_quaternion().copy()
                for role in watched
            }
            if frame in (38, 39, 40) or (32 <= frame <= 52 and order[0] == 0 and not fresh):
                elbows[frame] = capture_elbow()
            chain = (
                source.pose.bones[roles["hand_l"][0]].head
                - source.pose.bones[roles["forearm_l"][0]].head
            ).normalized()
            desired = (target_body @ (source_body.inverted() @ chain)).normalized()
            got = (
                target.pose.bones[roles["hand_l"][1]].head
                - target.pose.bones[roles["forearm_l"][1]].head
            ).normalized()
            dirs[frame] = math.degrees(got.angle(desired))
        return poses, elbows, dirs

    forward, elbows, dirs = solve(list(range(0, 53)))
    repeat, _, _ = solve(list(range(0, 53)))
    reverse, _, _ = solve(list(range(52, -1, -1)))
    single, _, _ = solve([19, 39, 52], fresh=True)
    random_order, _, _ = solve([19, 39, 10, 52, 20, 19])
    cyclic, cyclic_elbows, _ = solve(list(range(0, 53)), cyclic=True)
    p0_options = retarget.RetargetOptions(
        pairs=pairs, forearm_chain_twist=True, foot_ik=False, hand_ik=False,
        reference="REST", root_motion="KEEP",
    )
    p0_options.forearm_roll_continuity = False
    p0 = {}
    for frame in (0, 19, 38, 39, 52):
        scene.frame_set(frame)
        retarget._apply_body_orientations(source, target, pairs, p0_options)
        p0[frame] = target.pose.bones[roles["forearm_l"][1]].matrix_basis.to_quaternion().copy()

    def step(series, frame):
        return qdeg(series[frame - 1]["forearm_l"], series[frame]["forearm_l"])

    print("STEP_18_19", round(step(forward, 19), 4))
    print("STEP_19_20", round(step(forward, 20), 4))
    print("STEP_38_39", round(step(forward, 39), 4))
    print("STEP_39_40", round(step(forward, 40), 4))
    print("END_VS_START", round(qdeg(forward[0]["forearm_l"], forward[52]["forearm_l"]), 4))
    print("CYCLIC_END_VS_START", round(qdeg(cyclic[0]["forearm_l"], cyclic[52]["forearm_l"]), 4))
    print("MAX_DIR_30_52", round(max(dirs[frame] for frame in range(30, 53)), 6))
    print("REPEAT", round(max(qdeg(forward[frame]["forearm_l"], repeat[frame]["forearm_l"]) for frame in range(53)), 6))
    print("REVERSE39", round(qdeg(reverse[39]["forearm_l"], forward[39]["forearm_l"]), 6))
    print("SINGLE39", round(qdeg(single[39]["forearm_l"], forward[39]["forearm_l"]), 6))
    print("SINGLE19", round(qdeg(single[19]["forearm_l"], forward[19]["forearm_l"]), 6))
    print("RANDOM19", round(qdeg(random_order[19]["forearm_l"], forward[19]["forearm_l"]), 6))
    print("P0_39_DEV", round(qdeg(forward[39]["forearm_l"], p0[39]), 4))
    print("ELBOW39", round(elbow_shift(elbows, 39), 4))
    for role in ("forearm_r", "upperarm_l", "upperarm_r"):
        gap = max(qdeg(forward[frame][role], repeat[frame][role]) for frame in range(53))
        print("REPEAT", role, round(gap, 6))
    print("RIGHT_VS_LEFT_ORDER", round(qdeg(reverse[39]["forearm_r"], forward[39]["forearm_r"]), 6))
    window = max(step(forward, frame) for frame in range(34, 41))
    print("WINDOW_34_40_MAX", round(window, 4))
    cyclic_window = max(qdeg(cyclic[frame - 1]["forearm_l"], cyclic[frame]["forearm_l"]) for frame in range(34, 41))
    print("CYCLIC_WINDOW_34_40_MAX", round(cyclic_window, 4))
    print("CYCLIC_ELBOW39", round(elbow_shift(cyclic_elbows, 39), 4))
    print("DONE")


if __name__ == "__main__":
    main()
