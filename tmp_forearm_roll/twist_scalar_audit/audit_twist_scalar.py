"""Read-only audit of source twist scalars. Writes CSV only. Does not save a blend."""
from __future__ import annotations

import csv
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Quaternion, Vector

COPY = r"H:\Blender_Plugin\tmp_forearm_roll"
SOURCE = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"
ACTION = "a050_300000"
OUT = Path(r"H:\Blender_Plugin\tmp_forearm_roll\twist_scalar_audit\source_twist_scalar.csv")


def wrap(angle):
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def deg(angle):
    return math.degrees(angle)


def qdist(a, b):
    a = a.normalized()
    b = b.normalized()
    return 2.0 * math.acos(min(1.0, abs(max(-1.0, min(1.0, a.dot(b))))))


def rot3(matrix):
    return matrix.to_3x3().normalized()


def q_of(matrix):
    quat = rot3(matrix).to_quaternion().normalized()
    if quat.w < 0.0:
        quat.negate()
    return quat


def independent_twist(source_matrix, rest_matrix, chain):
    """Same formula as _source_chain_twist, kept local so the call can be diffed."""
    source_delta = rot3(source_matrix) @ rot3(rest_matrix).inverted()
    source_rotation = source_delta.to_quaternion().normalized()
    negated = False
    if source_rotation.w < 0.0:
        source_rotation.negate()
        negated = True
    chain_frame = Vector((0.0, 1.0, 0.0)).rotation_difference(chain.normalized())
    chain_rotation = (chain_frame.inverted() @ source_rotation @ chain_frame).normalized()
    swing, twist = chain_rotation.to_swing_twist("Y")
    raw = float(twist)
    wrapped = wrap(raw)
    rebuilt = (swing @ Quaternion((0.0, 1.0, 0.0), raw)).normalized()
    rebuild_error = qdist(rebuilt, chain_rotation)
    return {
        "quat": source_rotation,
        "negated": negated,
        "swing": swing.normalized(),
        "swing_deg": deg(swing.angle),
        "raw": raw,
        "wrapped": wrapped,
        "rebuild_deg": deg(rebuild_error),
        "rotation_deg": deg(source_rotation.angle),
    }


def twist_about(quat, axis):
    """Project a quaternion onto one axis. Axis may change between frames."""
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
    return angle


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
    action = next(item for item in retarget.collect_actions(source) if item.name == ACTION)
    retarget._assign_action(source, action)
    # build_pairs needs a target. Import the target read-only in this process only.
    target_path = r"c:\Users\chenshajie1\Downloads\body.FBX"
    objects, _ = pipeline.import_model(target_path)
    target = pipeline.pick_armature(objects)
    pairs = build_pairs(source, target)
    roles = {role: source_name for role, source_name, _target_name in pairs}
    chain_child = {
        "upperarm_l": "forearm_l",
        "forearm_l": "hand_l",
        "upperarm_r": "forearm_r",
        "forearm_r": "hand_r",
    }
    twist_bones = [
        bone.name
        for bone in source.data.bones
        if "twist" in bone.name.lower() or "Twist" in bone.name
    ]
    print("TWIST_BONES", twist_bones)
    print("MAP", {role: roles[role] for role in chain_child})

    scene = bpy.context.scene
    samples = []
    frames = [float(i) for i in range(0, 53)] + [18.4, 19.2]
    for frame in frames:
        scene.frame_set(math.floor(frame), subframe=frame - math.floor(frame))
        for role, child_role in chain_child.items():
            bone = source.pose.bones[roles[role]]
            child = source.pose.bones[roles[child_role]]
            chain = (child.head - bone.head).normalized()
            rest_chain = (
                source.data.bones[roles[child_role]].head_local
                - source.data.bones[roles[role]].head_local
            ).normalized()
            parent = bone.parent
            arm_q = q_of(bone.matrix)
            rest_q = q_of(bone.bone.matrix_local)
            parent_q = q_of(parent.matrix) if parent else Quaternion()
            parent_rest = q_of(parent.bone.matrix_local) if parent else Quaternion()
            local_q = (parent_q.inverted() @ arm_q).normalized()
            local_rest = (parent_rest.inverted() @ rest_q).normalized()
            info = independent_twist(bone.matrix, bone.bone.matrix_local, chain)
            algo = retarget._source_chain_twist(source, roles[role], chain)
            bone_y = rot3(bone.matrix) @ Vector((0.0, 1.0, 0.0))
            bone_x = rot3(bone.matrix) @ Vector((1.0, 0.0, 0.0))
            samples.append(
                {
                    "frame": frame,
                    "role": role,
                    "bone": roles[role],
                    "parent": parent.name if parent else "",
                    "quat": info["quat"].copy(),
                    "arm_q": arm_q.copy(),
                    "local_q": local_q.copy(),
                    "local_rest": local_rest.copy(),
                    "parent_q": parent_q.copy(),
                    "chain": chain.copy(),
                    "rest_chain": rest_chain.copy(),
                    "bone_y": bone_y.normalized(),
                    "bone_x": bone_x.normalized(),
                    "swing": info["swing"].copy(),
                    "swing_deg": info["swing_deg"],
                    "rotation_deg": info["rotation_deg"],
                    "raw": info["raw"],
                    "wrapped": info["wrapped"],
                    "algo": algo,
                    "rebuild_deg": info["rebuild_deg"],
                    "negated": info["negated"],
                    "fixed_rest": twist_about(info["quat"], rest_chain),
                    "fixed_y": twist_about(info["quat"], Vector((0.0, 1.0, 0.0))),
                    "moving_proj": twist_about(info["quat"], chain),
                }
            )

    by_key = {(item["frame"], item["role"]): item for item in samples}
    rows = []
    for item in samples:
        prev = by_key.get((round(item["frame"] - 1.0, 5), item["role"]))
        if item["frame"] in (18.4, 19.2):
            prev = by_key.get((18.4 if item["frame"] == 19.2 else 17.6, item["role"]))
        row = {
            "frame": f"{item['frame']:.1f}",
            "role": item["role"],
            "bone": item["bone"],
            "parent": item["parent"],
            "quat_w": f"{item['quat'].w:.8f}",
            "quat_x": f"{item['quat'].x:.8f}",
            "quat_y": f"{item['quat'].y:.8f}",
            "quat_z": f"{item['quat'].z:.8f}",
            "chain_x": f"{item['chain'].x:.8f}",
            "chain_y": f"{item['chain'].y:.8f}",
            "chain_z": f"{item['chain'].z:.8f}",
            "chain_space": "source_armature",
            "twist_axis": "posed_chain_head_to_child_head",
            "algo_twist_deg": f"{deg(item['algo']):.6f}",
            "independent_twist_deg": f"{deg(item['wrapped']):.6f}",
            "algo_minus_independent_deg": f"{deg(wrap(item['algo'] - item['wrapped'])):.6f}",
            "raw_swing_twist_deg": f"{deg(item['raw']):.6f}",
            "swing_deg": f"{item['swing_deg']:.6f}",
            "rest_relative_rotation_deg": f"{item['rotation_deg']:.6f}",
            "rebuild_error_deg": f"{item['rebuild_deg']:.6f}",
            "w_negated": int(item["negated"]),
            "twist_about_rest_chain_deg": f"{deg(item['fixed_rest']):.6f}",
            "twist_about_world_y_deg": f"{deg(item['fixed_y']):.6f}",
            "twist_about_current_chain_proj_deg": f"{deg(item['moving_proj']):.6f}",
        }
        if prev is None:
            for key in (
                "armature_step_deg",
                "local_basis_step_deg",
                "parent_step_deg",
                "chain_step_deg",
                "bone_y_vs_chain_deg",
                "algo_delta_wrapped_deg",
                "algo_delta_unwrapped_deg",
                "scalar_jump_over_180",
                "rel_twist_about_prev_chain_deg",
                "rel_twist_about_curr_chain_deg",
                "rel_twist_about_rest_chain_deg",
                "rel_twist_about_bone_y_deg",
                "transported_roll_deg",
                "fixed_frame18_twist_deg",
                "fixed_frame18_delta_deg",
            ):
                row[key] = ""
        else:
            relative = (item["quat"] @ prev["quat"].inverted()).normalized()
            if relative.w < 0.0:
                relative.negate()
            transport = prev["chain"].rotation_difference(item["chain"])
            transported = (transport @ prev["quat"]).normalized()
            residual = (item["quat"] @ transported.inverted()).normalized()
            fixed18 = by_key[(18.0, item["role"])]["chain"]
            fixed_now = twist_about(item["quat"], fixed18)
            fixed_prev = twist_about(prev["quat"], fixed18)
            algo_delta = wrap(item["algo"] - prev["algo"])
            raw_delta = item["algo"] - prev["algo"]
            row.update(
                {
                    "armature_step_deg": f"{deg(qdist(item['arm_q'], prev['arm_q'])):.6f}",
                    "local_basis_step_deg": f"{deg(qdist(item['local_q'], prev['local_q'])):.6f}",
                    "parent_step_deg": f"{deg(qdist(item['parent_q'], prev['parent_q'])):.6f}",
                    "chain_step_deg": f"{deg(prev['chain'].angle(item['chain'])):.6f}",
                    "bone_y_vs_chain_deg": f"{deg(item['bone_y'].angle(item['chain'])):.6f}",
                    "algo_delta_wrapped_deg": f"{deg(algo_delta):.6f}",
                    "algo_delta_unwrapped_deg": f"{deg(raw_delta):.6f}",
                    "scalar_jump_over_180": int(abs(raw_delta) > math.pi),
                    "rel_twist_about_prev_chain_deg": f"{deg(twist_about(relative, prev['chain'])):.6f}",
                    "rel_twist_about_curr_chain_deg": f"{deg(twist_about(relative, item['chain'])):.6f}",
                    "rel_twist_about_rest_chain_deg": f"{deg(twist_about(relative, item['rest_chain'])):.6f}",
                    "rel_twist_about_bone_y_deg": f"{deg(twist_about(relative, item['bone_y'])):.6f}",
                    "transported_roll_deg": f"{deg(twist_about(residual, item['chain'])):.6f}",
                    "fixed_frame18_twist_deg": f"{deg(fixed_now):.6f}",
                    "fixed_frame18_delta_deg": f"{deg(wrap(fixed_now - fixed_prev)):.6f}",
                }
            )
        rows.append(row)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    focus = [row for row in rows if row["role"] == "forearm_l" and row["frame"] in {"18.0", "19.0", "20.0", "38.0", "39.0"}]
    for row in focus:
        print(
            "FOCUS",
            row["frame"],
            "local",
            row["local_basis_step_deg"],
            "arm",
            row["armature_step_deg"],
            "parent",
            row["parent_step_deg"],
            "algo",
            row["algo_twist_deg"],
            "dd_wrap",
            row["algo_delta_wrapped_deg"],
            "dd_raw",
            row["algo_delta_unwrapped_deg"],
            "rel_prev",
            row["rel_twist_about_prev_chain_deg"],
            "rel_curr",
            row["rel_twist_about_curr_chain_deg"],
            "transport",
            row["transported_roll_deg"],
            "fixed18",
            row["fixed_frame18_delta_deg"],
            "chain",
            row["chain_step_deg"],
            "swing",
            row["swing_deg"],
            "rot",
            row["rest_relative_rotation_deg"],
            "diff",
            row["algo_minus_independent_deg"],
            "y_vs_chain",
            row["bone_y_vs_chain_deg"],
        )
    print("WROTE", OUT)


if __name__ == "__main__":
    main()
