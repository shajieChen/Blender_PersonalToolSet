"""Compare swing continuity prototypes. Does not save a blend or edit the addon."""
from __future__ import annotations

import math
import sys

import bpy
from mathutils import Quaternion, Vector

COPY = r"H:\Blender_Plugin\tmp_forearm_roll"
SOURCE = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"
TARGET = r"c:\Users\chenshajie1\Downloads\body.FBX"
ACTION = "a050_300000"


def wrap(angle):
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def qdeg(a, b):
    a = a.normalized()
    b = b.normalized()
    dot = max(-1.0, min(1.0, a.dot(b)))
    return math.degrees(2.0 * math.acos(min(1.0, abs(dot))))


def swing_twist(delta, axis):
    axis = axis.normalized()
    frame = Vector((0.0, 1.0, 0.0)).rotation_difference(axis)
    local = (frame.inverted() @ delta.normalized() @ frame).normalized()
    swing, twist = local.to_swing_twist("Y")

    def signed(value):
        if hasattr(value, "angle"):
            angle = math.degrees(value.angle)
            return -angle if value.w < 0.0 else angle
        return math.degrees(float(value))

    return signed(swing), signed(twist)


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
    src_roles = {role: pair[0] for role, pair in roles.items()}
    tgt_roles = {role: pair[1] for role, pair in roles.items()}
    source_body = retarget._body_matrix(source, retarget._anatomical_roles(source, src_roles))
    target_body = retarget._body_matrix(target, retarget._anatomical_roles(target, tgt_roles))
    chain_child = {"shoulder_l": "upperarm_l", "upperarm_l": "forearm_l", "forearm_l": "hand_l"}

    def rest_chain(role):
        child = chain_child[role]
        vector = target.data.bones[roles[child][1]].head_local - target.data.bones[roles[role][1]].head_local
        return vector.normalized()

    def rest_orient(role):
        return target.pose.bones[roles[role][1]].bone.matrix_local.to_3x3()

    rests = {role: rest_chain(role) for role in chain_child}
    orients = {role: rest_orient(role) for role in chain_child}
    bone_rest = {role: retarget._rot3(target.data.bones[roles[role][1]].matrix_local) for role in chain_child}
    parent_rest = {
        role: retarget._rot3(target.pose.bones[roles[role][1]].parent.bone.matrix_local)
        for role in ("upperarm_l", "forearm_l")
    }

    def sample(frame):
        scene = bpy.context.scene
        scene.frame_set(math.floor(frame), subframe=frame - math.floor(frame))
        out = {}
        for role in chain_child:
            child = chain_child[role]
            src_chain = (
                source.pose.bones[roles[child][0]].head - source.pose.bones[roles[role][0]].head
            ).normalized()
            desired = (target_body @ (source_body.inverted() @ src_chain)).normalized()
            twist = retarget._source_chain_twist(source, roles[role][0], src_chain)
            out[role] = {"desired": desired, "twist": twist, "src_chain": src_chain}
        return out

    frames = [i for i in range(0, 53)]
    raw = {frame: sample(frame) for frame in frames}
    for mark in (18.4, 19.2):
        raw[mark] = sample(mark)

    def direction_error(orient, role, desired):
        got = (orient.to_matrix() @ (orients[role].inverted() @ rests[role])).normalized()
        dot = max(-1.0, min(1.0, got.dot(desired)))
        return abs(dot - 1.0), math.degrees(math.acos(dot))

    def pose_a(role, item):
        swing = rests[role].rotation_difference(item["desired"])
        orient = (swing.to_matrix() @ orients[role]).to_quaternion()
        if role == "forearm_l":
            orient = (Quaternion(item["desired"], item["twist"]) @ orient).normalized()
        return orient

    def transport(previous, item):
        return (previous["desired"].rotation_difference(item["desired"]) @ previous["orient"]).normalized()

    def pose_c(previous, item):
        carried = transport(previous, item)
        delta = wrap(item["twist"] - previous["twist"])
        return (Quaternion(item["desired"], delta) @ carried).normalized()

    def pose_d(previous_swing, item, role):
        carried = previous_swing["desired"].rotation_difference(item["desired"]) @ previous_swing["swing"]
        base = (carried.to_matrix() @ orients[role]).to_quaternion()
        twist = item["twist"] if role == "forearm_l" else 0.0
        return (Quaternion(item["desired"], twist) @ base).normalized(), carried

    def basis(role, orient, parent_orient):
        return (
            bone_rest[role].inverted()
            @ parent_rest[role]
            @ parent_orient.to_matrix().inverted()
            @ orient.to_matrix()
        ).to_quaternion()

    def run(order, mode):
        state = {}
        chosen = {}
        for frame in order:
            item = raw[frame]
            chosen[frame] = {}
            shoulder = pose_a("shoulder_l", item["shoulder_l"])
            for role, parent in (("upperarm_l", shoulder), ("forearm_l", None)):
                if role not in state or state[role]["frame_gap"]:
                    orient = pose_a(role, item[role])
                    swing = rests[role].rotation_difference(item[role]["desired"])
                    rule = "initA"
                elif mode == "A":
                    orient = pose_a(role, item[role])
                    swing = rests[role].rotation_difference(item[role]["desired"])
                    rule = "A"
                elif mode == "B":
                    orient = transport(state[role], item[role])
                    swing = orient
                    rule = "B"
                elif mode == "C":
                    orient = pose_c(state[role], item[role])
                    swing = orient
                    rule = "C"
                else:
                    orient, swing = pose_d(state[role], item[role], role)
                    rule = "D"
                if role == "forearm_l":
                    parent = chosen[frame]["upperarm_l"]["orient"]
                dot_err, dir_err = direction_error(orient, role, item[role]["desired"])
                chosen[frame][role] = {
                    "orient": orient,
                    "basis": basis(role, orient, parent),
                    "desired": item[role]["desired"].copy(),
                    "twist": item[role]["twist"],
                    "dir": dir_err,
                    "dot": dot_err,
                    "rule": rule,
                    "swing": swing,
                }
            for role in ("upperarm_l", "forearm_l"):
                state[role] = {
                    "frame_gap": False,
                    "desired": item[role]["desired"].copy(),
                    "orient": chosen[frame][role]["orient"].copy(),
                    "twist": item[role]["twist"],
                    "swing": chosen[frame][role]["swing"].copy(),
                }
        return chosen

    def mark_gap(sequence):
        """run() treats a non-following call as init only when frame_gap is set externally."""
        return sequence

    def run_sequential(mode):
        state_gap = True
        # Local wrapper: first frame initializes, later frames continue.
        order = frames
        state = {}
        chosen = {}
        for frame in order:
            item = raw[frame]
            chosen[frame] = {}
            shoulder = pose_a("shoulder_l", item["shoulder_l"])
            for role in ("upperarm_l", "forearm_l"):
                previous = state.get(role)
                if previous is None or mode == "A":
                    orient = pose_a(role, item[role])
                    swing = rests[role].rotation_difference(item[role]["desired"])
                elif mode == "B":
                    orient = transport(previous, item[role])
                    swing = orient
                elif mode == "C":
                    orient = pose_c(previous, item[role])
                    swing = orient
                else:
                    orient, swing = pose_d(previous, item[role], role)
                parent = shoulder if role == "upperarm_l" else chosen[frame]["upperarm_l"]["orient"]
                _dot, dir_err = direction_error(orient, role, item[role]["desired"])
                chosen[frame][role] = {
                    "orient": orient,
                    "basis": basis(role, orient, parent),
                    "desired": item[role]["desired"].copy(),
                    "twist": item[role]["twist"],
                    "dir": dir_err,
                }
                state[role] = {
                    "desired": item[role]["desired"].copy(),
                    "orient": orient.copy(),
                    "twist": item[role]["twist"],
                    "swing": swing.copy(),
                }
            state_gap = False
        return chosen

    def metrics(series, role, a, b):
        left = series[a][role]
        right = series[b][role]
        delta = (right["orient"] @ left["orient"].inverted()).normalized()
        swing, twist = swing_twist(delta, right["desired"])
        src_delta = math.degrees(wrap(right["twist"] - left["twist"]))
        extra = (twist - src_delta + 180.0) % 360.0 - 180.0
        chain = math.degrees(left["desired"].angle(right["desired"]))
        return {
            "chain": chain,
            "total": qdeg(left["orient"], right["orient"]),
            "basis": qdeg(left["basis"], right["basis"]),
            "swing": swing,
            "twist": twist,
            "src": src_delta,
            "extra": extra,
            "dir": right["dir"],
        }

    results = {mode: run_sequential(mode) for mode in ("A", "B", "C", "D")}
    print("PAIR role mode chain total swing twist src extra basis dir")
    for a, b in ((18.0, 19.0), (18.4, 19.2), (19.0, 20.0)):
        # Fractional samples are not in sequential integer runs. Evaluate them as
        # neighbors by a direct two-step from the integer predecessor when needed.
        pass
    focus = ((18, 19), (19, 20), (38, 39), (39, 40))
    for a, b in focus:
        for role in ("upperarm_l", "forearm_l"):
            for mode, series in results.items():
                row = metrics(series, role, a, b)
                print(
                    f"{a}->{b}", role, mode,
                    f"chain {row['chain']:.3f}",
                    f"total {row['total']:.3f}",
                    f"swing {row['swing']:.3f}",
                    f"twist {row['twist']:.3f}",
                    f"src {row['src']:.3f}",
                    f"extra {row['extra']:.3f}",
                    f"basis {row['basis']:.3f}",
                    f"dir {row['dir']:.5f}",
                )

    def direct_pair(a, b, mode):
        series = {}
        item_a = raw[a]
        item_b = raw[b]
        shoulder_a = pose_a("shoulder_l", item_a["shoulder_l"])
        shoulder_b = pose_a("shoulder_l", item_b["shoulder_l"])
        state = {}
        for frame, item, shoulder in ((a, item_a, shoulder_a), (b, item_b, shoulder_b)):
            series[frame] = {}
            for role in ("upperarm_l", "forearm_l"):
                previous = state.get(role)
                if previous is None or mode == "A":
                    orient = pose_a(role, item[role])
                    swing = rests[role].rotation_difference(item[role]["desired"])
                elif mode == "B":
                    orient = transport(previous, item[role])
                    swing = orient
                elif mode == "C":
                    orient = pose_c(previous, item[role])
                    swing = orient
                else:
                    orient, swing = pose_d(previous, item[role], role)
                parent = shoulder if role == "upperarm_l" else series[frame]["upperarm_l"]["orient"]
                _dot, dir_err = direction_error(orient, role, item[role]["desired"])
                series[frame][role] = {
                    "orient": orient, "basis": basis(role, orient, parent),
                    "desired": item[role]["desired"].copy(), "twist": item[role]["twist"], "dir": dir_err,
                }
                state[role] = {
                    "desired": item[role]["desired"].copy(), "orient": orient.copy(),
                    "twist": item[role]["twist"], "swing": swing.copy(),
                }
        return series

    print("KEYS")
    for mode in ("A", "C", "D"):
        series = direct_pair(18.4, 19.2, mode)
        for role in ("upperarm_l", "forearm_l"):
            row = metrics(series, role, 18.4, 19.2)
            print(mode, role, f"chain {row['chain']:.3f}", f"total {row['total']:.3f}", f"twist {row['twist']:.3f}", f"src {row['src']:.3f}", f"extra {row['extra']:.3f}", f"basis {row['basis']:.3f}")

    print("CLIP")
    for mode, series in results.items():
        for role in ("upperarm_l", "forearm_l"):
            worst_extra = 0.0
            worst_total = 0.0
            worst_dir = 0.0
            hot = []
            for frame in range(1, 53):
                row = metrics(series, role, frame - 1, frame)
                worst_extra = max(worst_extra, abs(row["extra"]))
                worst_total = max(worst_total, row["total"])
                worst_dir = max(worst_dir, row["dir"])
                if abs(row["extra"]) > 45.0:
                    hot.append(frame)
            dev_33 = max(qdeg(series[frame][role]["basis"], results["A"][frame][role]["basis"]) for frame in range(33, 53))
            print(mode, role, "maxExtra", round(worst_extra, 3), "maxTotal", round(worst_total, 3), "maxDir", round(worst_dir, 5), "devFromA_33_52", round(dev_33, 3), "hot", hot)

    def replay(order, mode, init_frame):
        state = {}
        out = {}
        for frame in order:
            item = raw[frame]
            out[frame] = {}
            shoulder = pose_a("shoulder_l", item["shoulder_l"])
            for role in ("upperarm_l", "forearm_l"):
                previous = state.get(role)
                if previous is None or mode == "A":
                    orient = pose_a(role, item[role])
                    swing = rests[role].rotation_difference(item[role]["desired"])
                elif mode == "B":
                    orient = transport(previous, item[role])
                    swing = orient
                elif mode == "C":
                    orient = pose_c(previous, item[role])
                    swing = orient
                else:
                    orient, swing = pose_d(previous, item[role], role)
                parent = shoulder if role == "upperarm_l" else out[frame]["upperarm_l"]["orient"]
                out[frame][role] = {"orient": orient, "basis": basis(role, orient, parent)}
                state[role] = {
                    "desired": item[role]["desired"].copy(), "orient": orient.copy(),
                    "twist": item[role]["twist"], "swing": swing.copy(),
                }
            if frame == init_frame and False:
                pass
        return out

    print("ORDER")
    for mode in ("B", "C", "D"):
        forward = results[mode]
        backward = replay(list(range(52, -1, -1)), mode, 52)
        direct = pose_a("forearm_l", raw[19]["forearm_l"])
        jumps = replay([19, 39, 10, 52, 20, 19], mode, 19)
        print(
            mode,
            "rev19", round(qdeg(backward[19]["forearm_l"]["orient"], forward[19]["forearm_l"]["orient"]), 3),
            "direct19", round(qdeg(direct, forward[19]["forearm_l"]["orient"]), 3),
            "jump19", round(qdeg(jumps[19]["forearm_l"]["orient"], forward[19]["forearm_l"]["orient"]), 3),
            "revUpper19", round(qdeg(backward[19]["upperarm_l"]["orient"], forward[19]["upperarm_l"]["orient"]), 3),
        )
    near = []
    for frame in range(1, 53):
        turn = math.degrees(raw[frame - 1]["forearm_l"]["desired"].angle(raw[frame]["forearm_l"]["desired"]))
        turn_u = math.degrees(raw[frame - 1]["upperarm_l"]["desired"].angle(raw[frame]["upperarm_l"]["desired"]))
        if turn > 150.0 or turn_u > 150.0:
            near.append((frame, round(turn_u, 2), round(turn, 2)))
    print("NEAR_REVERSE", near)
    repeat = run_sequential("C")
    print("REPEAT_C", round(max(qdeg(repeat[frame]["forearm_l"]["orient"], results["C"][frame]["forearm_l"]["orient"]) for frame in frames), 6))
    print("DONE")


if __name__ == "__main__":
    main()
