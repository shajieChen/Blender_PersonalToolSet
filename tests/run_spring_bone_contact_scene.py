import hashlib
import json
import pathlib
import sys
import time

import bpy
import numpy as np


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

import spring_bone
from spring_bone.animation import iter_channelbags
from spring_bone.contact_bake import SkirtContactBakeJob, _garment_arrays, _mesh_arrays
from spring_bone.skin_collision import triangle_crossings


spring_bone.register()
arguments = sys.argv[sys.argv.index("--") + 1:]
source_file = (ROOT / arguments[0]).resolve()
first, last = int(arguments[1]), int(arguments[2])
folder = (ROOT / arguments[3]).resolve()
folder.mkdir(parents=True, exist_ok=True)
with bpy.data.libraries.load(str(source_file)) as (available, loaded):
    loaded.objects = available.objects
    if len(arguments) > 6:
        loaded.actions = [arguments[6]]
for obj in loaded.objects:
    bpy.context.collection.objects.link(obj)
arm = bpy.data.objects["骨架"]
cloth, body = bpy.data.objects["clothing"], bpy.data.objects["body"]
scene = bpy.context.scene
scene.sb_target_armature = arm
scene.frame_start, scene.frame_end = first, last
scene.render.fps, scene.render.fps_base = 24, 1.
arm.sb_settings.contact_garment, arm.sb_settings.contact_body = cloth, body
arm.sb_settings.contact_margin_m = float(arguments[4]) if len(arguments)>4 else .002
arm.sb_settings.contact_frame_step = float(arguments[5]) if len(arguments) > 5 else .5
source = arm.animation_data.action
if len(arguments) > 6:
    source = bpy.data.actions[arguments[6]]
    arm.animation_data.action = source
    arm.animation_data.action_slot = source.slots[0]
arm.animation_data.use_nla = False


def action_digest(action):
    values = [(curve.data_path, curve.array_index, [(tuple(key.co), key.interpolation) for key in curve.keyframe_points]) for bag in iter_channelbags(action, action.slots[0]) for curve in bag.fcurves]
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


before_digest = action_digest(source)
rest = np.array([vertex.co[:] for vertex in cloth.data.vertices])
started = time.perf_counter()
job = SkirtContactBakeJob(arm, first, last)
seen = -1
try:
    while not job.finished:
        job.run_slice()
        if job.frame_index != seen:
            seen = job.frame_index
            print("CONTACT_SCENE_PROGRESS", seen, len(getattr(job, "frames", [])), flush=True)
    assert job.delivered
    assert before_digest == action_digest(source)
    assert np.array_equal(rest, np.array([vertex.co[:] for vertex in cloth.data.vertices]))
    rows = []
    for frame, rotations, locations in job.solutions:
        whole = int(frame)
        scene.frame_set(whole, subframe=frame - whole)
        points, _, triangles = _garment_arrays(job.garments)
        body_points, _, body_triangles = _mesh_arrays(body)
        count = triangle_crossings(points, job.triangles, body_points, job.body_triangles)
        assert count == 0, (frame, count)
        rows.append({"frame": frame, "triangle_pairs": count})
    result = {"status": "passed", "blender": bpy.app.version_string, "input_action": source.name, "output_action": job.result_action.name, "frames": rows, "corrections": job.frame_results, "validation": job.validation_rows, "garments": [obj.name for obj in job.garments], "source_digest_before": before_digest, "source_digest_after": action_digest(source), "rest_vertices_unchanged": True, "chain_lengths": [len(chain.bone_names) for chain in arm.sb_settings.chains], "elapsed_seconds": time.perf_counter() - started}
    bpy.data.libraries.write(str(folder / "corrected-character.blend"), {arm, body, *job.garments}, fake_user=True)
except Exception as exc:
    result = {"status": "failed", "error": str(exc), "frame_results": job.frame_results, "elapsed_seconds": time.perf_counter() - started}
    if getattr(job, "sample", None) is not None and job.candidate is not None:
        sample = job.sample
        np.savez_compressed(folder / "failed-pose.npz", parents=sample.parents, relative=sample.relative_rest, inverse_rest=sample.inverse_rest, rest=sample.rest_points, weights=sample.weights, world=sample.armature_world, parent_fixed=sample.fixed_parents, locations=sample.locations, rotations=np.array([tuple(value) for value in sample.rotations]), scales=sample.scales, points=sample.evaluated_points, body_points=job.body_points, actual_body_points=job.sample_body_points, body_triangles=job.body_triangles, triangles=job.triangles, candidate_rotations=np.array([tuple(value) for value in job.candidate.rotations]), candidate_locations=job.candidate.locations)
    (folder / "scene-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    raise
(folder / "scene-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print("CONTACT_SCENE_RESULT", json.dumps({key: value for key, value in result.items() if key not in {"frames", "corrections", "validation"}}, ensure_ascii=True), flush=True)
