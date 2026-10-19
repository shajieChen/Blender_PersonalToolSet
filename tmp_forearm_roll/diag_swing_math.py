"""Read-only check of swing angles and where the extra roll appears."""
from __future__ import annotations

import math
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector

COPY = r"H:\Blender_Plugin\tmp_forearm_roll"
SOURCE = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"
TARGET = r"c:\Users\chenshajie1\Downloads\body.FBX"
ACTION = "a050_300000"


def qdeg(a, b):
    a = a.normalized()
    b = b.normalized()
    dot = max(-1.0, min(1.0, a.dot(b)))
    return math.degrees(2.0 * math.acos(min(1.0, abs(dot)))), dot


def qang(q):
    q = q.normalized()
    return math.degrees(2.0 * math.acos(min(1.0, abs(q.w)))), q.w


def project_twist(quat, axis):
    """Quaternion-vector projection onto axis. Not Blender's to_swing_twist."""
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


def swing_twist_about(delta, axis):
    """Express delta in a frame whose Y is axis, then use Blender swing-twist."""
    axis = axis.normalized()
    frame = Vector((0.0, 1.0, 0.0)).rotation_difference(axis)
    local = (frame.inverted() @ delta.normalized() @ frame).normalized()
    swing, twist = local.to_swing_twist("Y")

    def angle_of(value):
        if hasattr(value, "angle"):
            signed = math.degrees(value.angle)
            if getattr(value, "w", 1.0) < 0.0:
                signed = -signed
            return signed
        return math.degrees(float(value))

    return angle_of(swing), angle_of(twist)


def main():
    sys.path.insert(0, COPY)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    from humanoid_retarget.mapping import build_pairs
    from humanoid_retarget import pipeline
    import humanoid_retarget.retarget as retarget

    source, _ = pipeline.load_source(SOURCE)
    objects, _ = pipeline.import_model(TARGET)
    target = pipeline.pick_armature(objects)
    action = next(item for item in retarget.collect_actions(source) if item.name == ACTION)
    retarget._assign_action(source, action)
    pairs = build_pairs(source, target)
    roles = {role: (source_name, target_name) for role, source_name, target_name in pairs}
    options = retarget.RetargetOptions(
        pairs=pairs, forearm_chain_twist=True, foot_ik=False, hand_ik=False, reference="REST",
    )
    options.forearm_roll_continuity = False
    src_roles = {role: pair[0] for role, pair in roles.items()}
    tgt_roles = {role: pair[1] for role, pair in roles.items()}
    source_body = retarget._body_matrix(source, retarget._anatomical_roles(source, src_roles))
    target_body = retarget._body_matrix(target, retarget._anatomical_roles(target, tgt_roles))
    samples = (18.0, 18.4, 19.0, 19.2, 20.0)
    data = {}
    for frame in samples:
        bpy.context.scene.frame_set(int(frame) if frame == int(frame) else 0)
        # frame_set only accepts ints. Evaluate source curves through the scene by
        # using a fractional subframe when the frame is not integral.
        scene = bpy.context.scene
        scene.frame_set(math.floor(frame))
        scene.frame_set(math.floor(frame), subframe=(frame - math.floor(frame)))
        retarget._apply_body_orientations(source, target, pairs, options)
        bpy.context.view_layer.update()
        data[frame] = {}
        for role, child in (("upperarm_l", "forearm_l"), ("forearm_l", "hand_l")):
            source_name, target_name = roles[role]
            bone = target.pose.bones[target_name]
            rest_chain = (
                target.data.bones[roles[child][1]].head_local
                - target.data.bones[target_name].head_local
            ).normalized()
            src_chain = (
                source.pose.bones[roles[child][0]].head
                - source.pose.bones[source_name].head
            ).normalized()
            desired = (target_body @ (source_body.inverted() @ src_chain)).normalized()
            swing = rest_chain.rotation_difference(desired)
            mapped = (swing @ rest_chain).normalized()
            rest_orient = bone.bone.matrix_local.to_3x3()
            orient = swing.to_matrix() @ rest_orient
            if role == "forearm_l":
                orient = retarget._twist_about_chain(source, source_name, src_chain, desired, orient)
            parent = bone.parent
            rest = retarget._rot3(bone.bone.matrix_local)
            parent_rest = retarget._rot3(parent.bone.matrix_local)
            parent_pose = retarget._rot3(parent.matrix)
            basis = rest.inverted() @ parent_rest @ parent_pose.inverted() @ retarget._rot3(orient.to_4x4())
            data[frame][role] = {
                "rest": rest_chain.copy(),
                "desired": desired.copy(),
                "swing": swing.copy(),
                "mapped_error": math.degrees(mapped.angle(desired)),
                "swing_angle": math.degrees(swing.angle),
                "rest_angle": math.degrees(rest_chain.angle(desired)),
                "orient": retarget._rot3(orient.to_4x4()).to_quaternion(),
                "basis": basis.to_quaternion(),
                "solved_basis": bone.matrix_basis.to_quaternion().copy(),
                "parent_pose": parent_pose.copy(),
                "parent_rest": parent_rest.copy(),
                "rest_bone": rest.copy(),
            }
        scene.frame_set(scene.frame_current)

    def show(role, a, b):
        left = data[a][role]
        right = data[b][role]
        swing_delta = (right["swing"] @ left["swing"].inverted()).normalized()
        orient_delta = (right["orient"] @ left["orient"].inverted()).normalized()
        basis_delta = (right["basis"] @ left["basis"].inverted()).normalized()
        chain = math.degrees(left["desired"].angle(right["desired"]))
        swing_step, swing_dot = qdeg(left["swing"], right["swing"])
        orient_step, _ = qdeg(left["orient"], right["orient"])
        basis_step, basis_dot = qdeg(left["basis"], right["solved_basis"] * 0 + right["basis"])
        basis_step, basis_dot = qdeg(left["basis"], right["basis"])
        solved_step, _ = qdeg(left["solved_basis"], right["solved_basis"])
        proj = math.degrees(project_twist(swing_delta, right["desired"]))
        swing_part, twist_part = swing_twist_about(swing_delta, right["desired"])
        orient_swing, orient_twist = swing_twist_about(orient_delta, right["desired"])
        # Freeze parent at the first sample and only let forearm/upper orient change.
        frozen_parent = (
            right["rest_bone"].inverted()
            @ right["parent_rest"]
            @ left["parent_pose"].inverted()
            @ right["orient"].to_matrix()
        ).to_quaternion()
        frozen_orient = (
            right["rest_bone"].inverted()
            @ right["parent_rest"]
            @ right["parent_pose"].inverted()
            @ left["orient"].to_matrix()
        ).to_quaternion()
        parent_only, _ = qdeg(left["basis"], frozen_orient)
        orient_only, _ = qdeg(left["basis"], frozen_parent)
        print(
            f"{role} {a}->{b}",
            f"mapErr {right['mapped_error']:.6f}",
            f"swingAng {right['swing_angle']:.3f}",
            f"restAng {right['rest_angle']:.3f}",
            f"chain {chain:.3f}",
            f"swingStep {swing_step:.3f} dot {swing_dot:.4f}",
            f"projTwist {proj:.3f}",
            f"frameTwist {twist_part:.3f}",
            f"frameSwing {swing_part:.3f}",
            f"orientStep {orient_step:.3f}",
            f"orientTwist {orient_twist:.3f}",
            f"basisStep {basis_step:.3f} dot {basis_dot:.4f}",
            f"solvedStep {solved_step:.3f}",
            f"parentOnly {parent_only:.3f}",
            f"orientOnly {orient_only:.3f}",
            f"basisMatch {qdeg(right['basis'], right['solved_basis'])[0]:.4f}",
        )

    for role in ("upperarm_l", "forearm_l"):
        for pair in ((18.0, 19.0), (18.4, 19.2), (19.0, 20.0)):
            show(role, *pair)
    # Parallel transport reference: rotate previous orient by the shortest
    # rotation taking previous desired onto the new desired.
    print("TRANSPORT")
    for role in ("upperarm_l", "forearm_l"):
        for a, b in ((18.0, 19.0), (19.0, 20.0)):
            left = data[a][role]
            right = data[b][role]
            carry = left["desired"].rotation_difference(right["desired"])
            transported = (carry @ left["orient"]).normalized()
            gap, _ = qdeg(transported, right["orient"])
            step, _ = qdeg(left["orient"], transported)
            print(role, a, b, "transportStep", round(step, 3), "transportVsIndependent", round(gap, 3))
    print("DONE")


if __name__ == "__main__":
    main()
