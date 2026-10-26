import json
import math
import statistics
import time
from pathlib import Path

import bpy
import numpy as np

from spring_bone.animation import _rest_token
from spring_bone.contact_bake import _action_token, _mesh_arrays, _mesh_token, _skin_weights
from spring_bone.operators import active_session, start_realtime
from spring_bone.solver import FIXED_DT


def audit_realtime(folder):
    job = active_session().job if active_session() is not None else start_realtime(bpy.context).job
    if not getattr(job, "is_realtime", False):
        raise RuntimeError("当前会话不是实时预览")
    arm = job.armature
    chains = arm.sb_settings.chains
    before = [(chain.gravity_power, tuple(chain.gravity_dir), chain.warmup_seconds) for chain in chains]
    names = job.names
    source_before = _action_token(job.source_action, job.source_action.slots[0])
    rest_before = _rest_token(arm)
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and any(mod.type == "ARMATURE" and mod.object == arm for mod in obj.modifiers)]
    hand_bones = sorted({bone.name for name in ("hand.L", "hand.R") if (root := arm.data.bones.get(name)) is not None for bone in (root, *root.children_recursive) if bone.name not in names})
    hand_masks = {obj.name: _skin_weights(obj, arm, hand_bones).sum(axis=1) > 1e-8 for obj in meshes}
    mesh_before = [_mesh_token(obj) for obj in meshes]
    simulated_meshes = {obj.name for obj in meshes if _skin_weights(obj, arm, names).sum() > 1e-8}
    owned_action = job.input_action
    timer_ticks = job.tick_count
    diagnostics_before = job.diagnostics_enabled
    job.diagnostics_enabled = True

    def directions():
        bpy.context.view_layer.update()
        return {name: (arm.matrix_world.to_3x3() @ (arm.pose.bones[name].tail - arm.pose.bones[name].head)).normalized() for name in names}

    measured = {}
    skin_positions = {}
    try:
        for case, gravity, direction in (("zero", 0., (0., 0., -1.)), ("down", 20., (0., 0., -1.)), ("up", 20., (0., 0., 1.))):
            for chain in chains:
                chain.gravity_power, chain.gravity_dir, chain.warmup_seconds = gravity, direction, 0.
            job.update_paused(FIXED_DT)
            job._reset(job.last_tick)
            for _ in range(60):
                job.update_paused(FIXED_DT)
            measured[case] = directions()
            skin_positions[case] = {obj.name: _mesh_arrays(obj)[0] for obj in meshes}
        rows = [{"bone": name, "down_vs_zero_deg": math.degrees(measured["zero"][name].angle(measured["down"][name])), "down_vs_up_deg": math.degrees(measured["down"][name].angle(measured["up"][name])), "down_z": measured["down"][name].z, "up_z": measured["up"][name].z} for name in names]
    finally:
        for chain, values in zip(chains, before):
            chain.gravity_power, chain.gravity_dir, chain.warmup_seconds = values
        job.update_paused(FIXED_DT)
        job._reset(job.last_tick)
        job._apply()
        bpy.context.view_layer.update()
        job.diagnostics_enabled = diagnostics_before
    durations = []
    for _ in range(60):
        started = time.perf_counter()
        job.update_paused(FIXED_DT)
        durations.append((time.perf_counter() - started) * 1000.)
    result = {"blender": bpy.app.version_string, "source_action": job.source_action.name, "frame": job.scene.frame_current + job.scene.frame_subframe, "segments": len(names), "native_paused_tick_count_before_probe": timer_ticks, "segment_results": rows, "all_segments_responded_to_gravity_direction": all(row["down_vs_up_deg"] > .01 for row in rows), "source_unchanged": source_before == _action_token(job.source_action, job.source_action.slots[0]), "rest_unchanged": rest_before == _rest_token(arm), "mesh_weights_unchanged": mesh_before == [_mesh_token(obj) for obj in meshes], "same_preview_action": job.input_action == owned_action, "parameters_restored": before == [(chain.gravity_power, tuple(chain.gravity_dir), chain.warmup_seconds) for chain in chains], "update_ms": {"median": statistics.median(durations), "p95": sorted(durations)[int(len(durations) * .95) - 1], "maximum": max(durations)}}
    result["skin_motion"] = {name: {"moved_vertices": int((np.linalg.norm(points - skin_positions["up"][name], axis=1) > 1e-6).sum()), "maximum_displacement_m": float(np.linalg.norm(points - skin_positions["up"][name], axis=1).max()) * job.scale_length} for name, points in skin_positions["down"].items() if name in simulated_meshes}
    result["skin_motion_verified"] = bool(result["skin_motion"]) and all(row["moved_vertices"] > 0 for row in result["skin_motion"].values())
    result["protected_hand_skin"] = {name: {"vertices": int(hand_masks[name].sum()), "maximum_displacement_m": float(np.linalg.norm(points[hand_masks[name]] - skin_positions["up"][name][hand_masks[name]], axis=1).max()) * job.scale_length} for name, points in skin_positions["down"].items() if hand_masks[name].any()}
    result["hand_skin_unchanged"] = all(row["maximum_displacement_m"] < 1e-6 for row in result["protected_hand_skin"].values())
    if not result["skin_motion_verified"] or not result["hand_skin_unchanged"]:
        result["status"] = "failed"
    result["status"] = "passed" if all(result[key] for key in ("all_segments_responded_to_gravity_direction", "source_unchanged", "rest_unchanged", "mesh_weights_unchanged", "same_preview_action", "parameters_restored")) else "failed"
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "live-gravity-audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "segment_results"}, ensure_ascii=True))
    assert result["status"] == "passed", result
    return result
