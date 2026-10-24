import json
import pathlib
import sys

import bpy
import numpy as np


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

import spring_bone
from humanoid_retarget import pipeline
from spring_bone.contact_bake import _mesh_arrays, _skin_weights
from spring_bone.skin_collision import triangle_crossings


spring_bone.register()
arguments = sys.argv[sys.argv.index("--") + 1:]
folder = (ROOT / arguments[0]).resolve()
with bpy.data.libraries.load(str(folder / "corrected-character.blend")) as (available, loaded):
    loaded.objects = [name for name in available.objects if name in {"骨架", "body", "clothing"}]
for obj in loaded.objects:
    bpy.context.collection.objects.link(obj)
arm, cloth, body = (bpy.data.objects[name] for name in ("骨架", "clothing", "body"))
scene = bpy.context.scene
scene.render.fps, scene.render.fps_base = 24, 1.
action = arm.animation_data.action
arm.animation_data.use_nla = False
first, last = int(action["sb_frame_start"]), int(action["sb_frame_end"])
scene.frame_start, scene.frame_end = first, last
names = [item.name for chain in arm.sb_settings.chains for item in chain.bone_names]
mask = _skin_weights(cloth, arm, names).sum(axis=1) > .05
region_names = sorted({bone.name for collider in arm.sb_settings.colliders for bone in (arm.data.bones[collider.bone_name], *arm.data.bones[collider.bone_name].children_recursive)})
region = _skin_weights(body, arm, region_names).sum(axis=1) > .05
cloth_triangles = _mesh_arrays(cloth)[2]
cloth_triangles = cloth_triangles[mask[cloth_triangles].sum(axis=1) >= 2]
body_triangles = _mesh_arrays(body)[2]
body_triangles = body_triangles[region[body_triangles].sum(axis=1) >= 2]
expected = {}
quarter_contacts = []
sample_step = float(action.get("fbx_sample_step", 1.0))
for frame in np.arange(first, last + .125, .25):
    whole = int(frame)
    scene.frame_set(whole, subframe=float(frame - whole))
    points, _, _ = _mesh_arrays(cloth)
    body_points, _, _ = _mesh_arrays(body)
    count = triangle_crossings(points, cloth_triangles, body_points, body_triangles)
    if count:
        quarter_contacts.append({"frame": float(frame), "triangle_pairs": count})
    if abs((frame - first) / sample_step - round((frame - first) / sample_step)) < 1e-6:
        expected[float(frame)] = points
fbx = (ROOT / arguments[1]).resolve() if len(arguments) > 1 else folder / "corrected-character.fbx"
if len(arguments) == 1:
    pipeline.export_armature(arm, str(fbx), export_all_actions=False)
objects, actions = pipeline.import_model(str(fbx))
imported_arm = next(obj for obj in objects if obj.type == "ARMATURE")
imported_cloth = next(obj for obj in objects if obj.type == "MESH" and obj.name.startswith("clothing") and len(obj.data.vertices) == len(cloth.data.vertices))
imported_body = next(obj for obj in objects if obj.type == "MESH" and obj.name.startswith("body") and len(obj.data.vertices) == len(body.data.vertices))
assert imported_arm.animation_data.action is not None
imported_arm.animation_data.use_nla = False
frame_offset = float(imported_arm.animation_data.action.frame_range[0] - action.frame_range[0])
reference_delta = 0.0
if len(arguments) > 1:
    live = np.load(ROOT / "docs/superpowers/evidence/2026-10-24-spring-bone-contact/live-expected.npz")
    for index, frame in enumerate(live["frames"]):
        if float(frame) in expected:
            reference_delta = max(reference_delta, float(np.linalg.norm(expected[float(frame)] - live["cloth"][index], axis=1).max()))
            expected[float(frame)] = live["cloth"][index]
errors = []
contacts = []
for frame, positions in expected.items():
    imported_frame = frame + frame_offset
    whole = int(imported_frame)
    scene.frame_set(whole, subframe=imported_frame - whole)
    actual = _mesh_arrays(imported_cloth)[0]
    body_points = _mesh_arrays(imported_body)[0]
    if actual.shape != positions.shape:
        raise AssertionError(("FBX topology", actual.shape, positions.shape))
    error = float(np.linalg.norm(actual - positions, axis=1).max())
    errors.append(error)
    count = triangle_crossings(actual, cloth_triangles, body_points, body_triangles)
    if count:
        contacts.append({"frame": frame, "triangle_pairs": count})
result = {"blender": bpy.app.version_string, "action": action.name, "fbx_sample_step": float(action.get("fbx_sample_step", 1.0)), "quaternion_sign_repairs": int(action.get("sb_quaternion_sign_repairs", 0)), "import_frame_offset": frame_offset, "checked_frames": len(expected), "reference_fixture_to_live_delta_m": reference_delta, "maximum_skin_error_m": max(errors), "fbx_contacts": contacts, "quarter_frame_contacts_before_export": quarter_contacts, "exported_file": str(fbx)}
result["status"] = "passed" if not contacts and max(errors) < 2e-5 else "failed"
(folder / ("live-fbx-result.json" if len(arguments) > 1 else "fbx-result.json")).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print("CONTACT_FBX_RESULT", json.dumps(result, ensure_ascii=True), flush=True)
assert result["status"] == "passed", result
