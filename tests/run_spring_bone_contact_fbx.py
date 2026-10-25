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
from spring_bone.contact_bake import _garment_arrays, _mesh_arrays, _skin_weights, garment_meshes
from spring_bone.skin_collision import triangle_crossings


spring_bone.register()
arguments = sys.argv[sys.argv.index("--") + 1:]
folder = (ROOT / arguments[0]).resolve()
with bpy.data.libraries.load(str(folder / "corrected-character.blend")) as (available, loaded):
    loaded.objects = available.objects
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
garments = garment_meshes(arm, cloth)
region_names = sorted({bone.name for collider in arm.sb_settings.colliders for bone in (arm.data.bones[collider.bone_name], *arm.data.bones[collider.bone_name].children_recursive)})
region = _skin_weights(body, arm, region_names).sum(axis=1) > 1e-8
cloth_triangles = _garment_arrays(garments)[2]
body_triangles = _mesh_arrays(body)[2]
body_triangles = body_triangles[region[body_triangles].any(axis=1)]
expected = {}
quarter_contacts = []
sample_step = float(action.get("fbx_sample_step", 1.0))
validation_step = float(action.get("sb_contact_validation_step", min(.25, sample_step)))
for frame in np.arange(first, last + validation_step * .25, validation_step):
    whole = int(frame)
    scene.frame_set(whole, subframe=float(frame - whole))
    points, _, _ = _garment_arrays(garments)
    body_points, _, _ = _mesh_arrays(body)
    count = triangle_crossings(points, cloth_triangles, body_points, body_triangles)
    if count:
        quarter_contacts.append({"frame": float(frame), "triangle_pairs": count})
    expected[float(frame)] = points
fbx = (ROOT / arguments[1]).resolve() if len(arguments) > 1 else folder / "corrected-character.fbx"
if len(arguments) == 1:
    pipeline.export_armature(arm, str(fbx), export_all_actions=False)
objects, actions = pipeline.import_model(str(fbx))
imported_arm = next(obj for obj in objects if obj.type == "ARMATURE")
imported_garments = []
for garment in garments:
    matches = [obj for obj in objects if obj.type == "MESH" and len(obj.data.vertices) == len(garment.data.vertices) and any(mod.type == "ARMATURE" and mod.object == imported_arm for mod in obj.modifiers)]
    if len(matches) != 1:
        raise AssertionError(("FBX garment identity", garment.name, [obj.name for obj in matches]))
    imported_garments.append(matches[0])
imported_body = next(obj for obj in objects if obj.type == "MESH" and obj.name.startswith("body") and len(obj.data.vertices) == len(body.data.vertices))
assert imported_arm.animation_data.action is not None
imported_arm.animation_data.use_nla = False
frame_offset = float(imported_arm.animation_data.action.frame_range[0] - action.frame_range[0])
reference_delta = 0.0
if len(arguments) > 2:
    live = np.load((ROOT / arguments[2]).resolve())
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
    actual = _garment_arrays(imported_garments)[0]
    body_points = _mesh_arrays(imported_body)[0]
    if actual.shape != positions.shape:
        raise AssertionError(("FBX topology", actual.shape, positions.shape))
    error = float(np.linalg.norm(actual - positions, axis=1).max())
    errors.append(error)
    count = triangle_crossings(actual, cloth_triangles, body_points, body_triangles)
    if count:
        contacts.append({"frame": frame, "triangle_pairs": count})
result = {"blender": bpy.app.version_string, "action": action.name, "fbx_sample_step": float(action.get("fbx_sample_step", 1.0)), "validation_step": validation_step, "garments": [obj.name for obj in garments], "quaternion_sign_repairs": int(action.get("sb_quaternion_sign_repairs", 0)), "import_frame_offset": frame_offset, "checked_frames": len(expected), "reference_fixture_to_live_delta_m": reference_delta, "maximum_skin_error_m": max(errors), "fbx_contacts": contacts, "quarter_frame_contacts_before_export": quarter_contacts, "exported_file": str(fbx)}
result["status"] = "passed" if expected and not contacts and not quarter_contacts and max(errors) < 2e-5 else "failed"
(folder / ("live-fbx-result.json" if len(arguments) > 1 else "fbx-result.json")).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print("CONTACT_FBX_RESULT", json.dumps(result, ensure_ascii=True), flush=True)
assert result["status"] == "passed", result
