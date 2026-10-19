"""Headless policy search. Does not read or write the user's open scene."""
from __future__ import annotations

import math
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector

COPY = r"H:\Blender_Plugin\tmp_forearm_roll"
SOURCE = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"
TARGET = r"c:\Users\chenshajie1\Downloads\body.FBX"
ACTION = "a050_300000"


def wrap(angle):
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def qdeg(a, b):
    a = a.normalized()
    b = b.normalized()
    return math.degrees(2.0 * math.acos(min(1.0, abs(max(-1.0, min(1.0, a.dot(b)))))))


def qang(q):
    return math.degrees(2.0 * math.acos(min(1.0, abs(max(-1.0, min(1.0, q.normalized().w))))))


def project(vector, axis):
    axis = axis.normalized()
    return (vector - axis * vector.dot(axis)).normalized()


def signed(a, b, axis):
    a = project(a, axis)
    b = project(b, axis)
    return math.atan2(a.cross(b).dot(axis.normalized()), a.dot(b))


def marker(matrix, axis):
    columns = [matrix.col[index].xyz for index in range(3)]
    return max(columns, key=lambda column: abs(math.sin(column.angle(axis)))).normalized()


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
    options = retarget.RetargetOptions(
        pairs=pairs, forearm_chain_twist=True, foot_ik=False, hand_ik=False, reference="REST"
    )
    roles = {role: (source_name, target_name) for role, source_name, target_name in pairs}
    group = {item.name: item.index for item in mesh.vertex_groups}

    def weight(vertex, name):
        index = group.get(name)
        if index is None:
            return 0.0
        for item in vertex.groups:
            if item.group == index:
                return item.weight
        return 0.0

    forearm_name = roles["forearm_l"][1]
    upper_name = roles["upperarm_l"][1]
    blended = [
        vertex.index
        for vertex in mesh.data.vertices
        if 0.0 < weight(vertex, forearm_name) < 0.999 and weight(vertex, upper_name) > 0.0
    ]
    print("MESH", mesh.name, "VERTS", len(mesh.data.vertices), "BLENDED", len(blended))

    def arm_const(side):
        source_name, target_name = roles[f"forearm_{side}"]
        _hand_source, hand_target = roles[f"hand_{side}"]
        rest_m = target.data.bones[target_name].matrix_local.to_3x3()
        rest_chain = (
            target.data.bones[hand_target].head_local - target.data.bones[target_name].head_local
        ).normalized()
        return {
            "source": source_name,
            "target": target_name,
            "hand": hand_target,
            "upper": roles[f"upperarm_{side}"][1],
            "rest_m": rest_m,
            "rest_chain": rest_chain,
            "mark": marker(rest_m, rest_chain),
            "rest": retarget._rot3(target.data.bones[target_name].matrix_local),
            "parent_rest": retarget._rot3(target.pose.bones[target_name].parent.bone.matrix_local),
        }

    arms = {"L": arm_const("l"), "R": arm_const("r")}
    src_roles = {role: pair[0] for role, pair in roles.items()}
    tgt_roles = {role: pair[1] for role, pair in roles.items()}
    source_body = retarget._body_matrix(source, retarget._anatomical_roles(source, src_roles))
    target_body = retarget._body_matrix(target, retarget._anatomical_roles(target, tgt_roles))

    def sample(side):
        const = arms[side]
        chain = (
            source.pose.bones[roles[f"hand_{side.lower()}"][0]].head
            - source.pose.bones[const["source"]].head
        ).normalized()
        desired = (target_body @ (source_body.inverted() @ chain)).normalized()
        source_rest = retarget._rot3(source.data.bones[const["source"]].matrix_local)
        source_delta = retarget._rot3(source.pose.bones[const["source"]].matrix) @ source_rest.inverted()
        source_rotation = source_delta.to_quaternion().normalized()
        if source_rotation.w < 0.0:
            source_rotation.negate()
        chain_frame = Vector((0.0, 1.0, 0.0)).rotation_difference(chain)
        scalar = wrap((chain_frame.inverted() @ source_rotation @ chain_frame).to_swing_twist("Y")[1])
        swing = const["rest_chain"].rotation_difference(desired)
        orient = (Quaternion(desired, scalar).to_matrix() @ swing.to_matrix() @ const["rest_m"]).to_quaternion()
        parent = retarget._rot3(target.pose.bones[const["target"]].parent.matrix)
        basis = (
            const["rest"].inverted() @ const["parent_rest"] @ parent.inverted() @ retarget._rot3(orient.to_matrix().to_4x4())
        ).to_quaternion()
        posed_chain = (
            target.pose.bones[const["hand"]].head - target.pose.bones[const["target"]].head
        ).normalized()
        return {
            "desired": desired.copy(),
            "twist": scalar,
            "orient": orient,
            "basis": basis,
            "rest_deg": math.degrees(const["rest_chain"].angle(desired)),
            "posed_chain": posed_chain,
            "upper": target.pose.bones[const["upper"]].matrix_basis.to_quaternion().copy(),
            "spine": target.pose.bones[roles["spine"][1]].matrix_basis.to_quaternion().copy(),
        }

    def solve_basis(side, orient):
        const = arms[side]
        parent = retarget._rot3(target.pose.bones[const["target"]].parent.matrix)
        return (
            const["rest"].inverted()
            @ const["parent_rest"]
            @ parent.inverted()
            @ retarget._rot3(orient.to_matrix().to_4x4())
        ).to_quaternion()

    def direction_error(side, orient, desired):
        const = arms[side]
        got = (
            retarget._rot3(orient.to_matrix().to_4x4())
            @ (const["rest_m"].inverted() @ const["rest_chain"])
        ).normalized()
        dot = max(-1.0, min(1.0, got.dot(desired)))
        return abs(dot - 1.0), math.degrees(math.acos(dot))

    def transport(prev, current_desired, current_twist):
        carried = prev["desired"].rotation_difference(current_desired).to_matrix() @ prev["orient"].to_matrix()
        delta = wrap(current_twist - prev["twist"])
        return (Quaternion(current_desired, delta).to_matrix() @ carried).to_quaternion()

    def elbow_shift(before_pts, bone_before, after_pts, bone_after):
        if not blended:
            return 0.0
        inverse_before = bone_before.inverted()
        inverse_after = bone_after.inverted()
        worst = 0.0
        for index in blended:
            delta = (inverse_before @ before_pts[index]) - (inverse_after @ after_pts[index])
            worst = max(worst, (bone_after.to_3x3() @ delta).length)
        return worst

    def capture_elbow():
        depsgraph = bpy.context.evaluated_depsgraph_get()
        evaluated = mesh.evaluated_get(depsgraph)
        temporary = evaluated.to_mesh()
        world = evaluated.matrix_world.copy()
        points = {index: (world @ temporary.vertices[index].co) for index in blended}
        evaluated.to_mesh_clear()
        arm_eval = target.evaluated_get(depsgraph)
        bone = arm_eval.pose.bones[forearm_name]
        return points, arm_eval.matrix_world @ bone.matrix

    frames = list(range(0, 53))
    p0 = {}
    sample_cache = {}
    for frame in frames:
        bpy.context.scene.frame_set(frame)
        retarget._apply_body_orientations(source, target, pairs, options)
        sample_cache = {}
        p0[frame] = {}
        for side in ("L", "R"):
            item = sample(side)
            sample_cache[side] = item
            p0[frame][side] = item
        p0[frame]["elbow"] = capture_elbow()

    def run(enter_deg, exit_deg, return_deg):
        state = {}
        chosen = {}
        for frame in frames:
            chosen[frame] = {}
            for side in ("L", "R"):
                current = p0[frame][side]
                if side not in state:
                    orient = current["orient"].copy()
                    latched = current["rest_deg"] >= enter_deg
                    rule = "init_p0"
                else:
                    prev = state[side]
                    continuous = transport(prev, current["desired"], current["twist"])
                    delta = (continuous @ current["orient"].inverted()).normalized()
                    rolled = abs(twist_about(delta, current["desired"]))
                    if prev["latched"]:
                        if current["rest_deg"] < exit_deg and rolled <= return_deg:
                            orient = current["orient"].copy()
                            latched = False
                            rule = "return_p0"
                        else:
                            orient = continuous
                            latched = True
                            rule = "hold"
                    elif current["rest_deg"] >= enter_deg:
                        orient = continuous
                        latched = True
                        rule = "enter"
                    else:
                        orient = current["orient"].copy()
                        latched = False
                        rule = "p0"
                state[side] = {
                    "desired": current["desired"].copy(),
                    "twist": current["twist"],
                    "orient": orient.copy(),
                    "latched": latched,
                }
                chosen[frame][side] = {"orient": orient, "rule": rule, "latched": latched}
        return chosen

    def report(tag, chosen):
        print("POLICY", tag)
        prev = {}
        prev_orient = {}
        prev_pts = None
        max_step = {"L": 0.0, "R": 0.0}
        max_p0 = {"L": 0.0, "R": 0.0}
        max_dir = 0.0
        max_elbow = 0.0
        p0_elbow_max = 0.0
        for frame in frames:
            # Reconstruct elbow by applying the chosen forearm over the stored P0 pose.
            bpy.context.scene.frame_set(frame)
            retarget._apply_body_orientations(source, target, pairs, options)
            for side in ("L", "R"):
                orient = chosen[frame][side]["orient"]
                target.pose.bones[arms[side]["target"]].rotation_quaternion = solve_basis(side, orient)
            bpy.context.view_layer.update()
            elbow = capture_elbow()
            line = [tag, f"f{frame}"]
            for side in ("L", "R"):
                orient = chosen[frame][side]["orient"]
                basis = solve_basis(side, orient)
                dot_err, dir_err = direction_error(side, orient, p0[frame][side]["desired"])
                dev = qdeg(orient, p0[frame][side]["orient"])
                step = 0.0 if side not in prev else qdeg(prev[side], basis)
                chain_step = 0.0
                if side in prev:
                    delta = (orient @ prev_orient[side].inverted()).normalized()
                    chain_step = twist_about(delta, p0[frame][side]["desired"])
                prev[side] = basis
                prev_orient[side] = orient
                max_step[side] = max(max_step[side], abs(step))
                max_p0[side] = max(max_p0[side], dev)
                max_dir = max(max_dir, dot_err)
                if 30 <= frame <= 45 or chosen[frame][side]["rule"] != "p0":
                    line.append(
                        f"{side}:{chosen[frame][side]['rule'][:4]} rest {p0[frame][side]['rest_deg']:.1f} "
                        f"dir {dir_err:.4f} p0 {dev:.2f} step {step:.2f} roll {chain_step:.2f}"
                    )
            if prev_pts is not None:
                shift = elbow_shift(prev_pts[0], prev_pts[1], elbow[0], elbow[1])
                p0_shift = elbow_shift(prev_p0[0], prev_p0[1], p0[frame]["elbow"][0], p0[frame]["elbow"][1])
                max_elbow = max(max_elbow, shift)
                p0_elbow_max = max(p0_elbow_max, p0_shift)
                if 33 <= frame <= 41:
                    line.append(f"elbow {shift:.4f} p0elbow {p0_shift:.4f}")
            prev_pts = elbow
            prev_p0 = p0[frame]["elbow"]
            if len(line) > 2:
                print(" ".join(line))
        upper_delta = 0.0
        spine_delta = 0.0
        for frame in frames:
            # Upper arm and spine were never overwritten; sampled from P0.
            upper_delta = 0.0
            spine_delta = 0.0
        print(
            "SUM", tag,
            "maxStepL", round(max_step["L"], 3),
            "maxStepR", round(max_step["R"], 3),
            "maxP0L", round(max_p0["L"], 3),
            "maxP0R", round(max_p0["R"], 3),
            "maxDot", f"{max_dir:.3e}",
            "maxElbow", round(max_elbow, 4),
            "p0Elbow", round(p0_elbow_max, 4),
        )

    for enter, exit_deg, back in ((165.0, 150.0, 8.0), (160.0, 140.0, 8.0), (168.0, 160.0, 12.0)):
        report(f"enter{enter}_exit{exit_deg}_back{back}", run(enter, exit_deg, back))
    print("DONE")


if __name__ == "__main__":
    main()
