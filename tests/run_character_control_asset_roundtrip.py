from pathlib import Path
import sys
import json

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import bpy
import run_retarget_test as retarget_fixture
from humanoid_retarget.pipeline import export_armature, load_source, retarget_existing
from humanoid_retarget.retarget import RetargetOptions
import character_locomotion as plugin
from character_locomotion import animation_library as library
from character_locomotion.animation_playback import CharacterPlayback

OUT = ROOT / "tests" / "out" / "character_control"
OUT.mkdir(parents=True, exist_ok=True)
plugin.register()
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
names = retarget_fixture.junk_names()
source = retarget_fixture.build_biped("ExportSource", names)
retarget_fixture.animate(source, names)
bpy.context.scene.frame_end = 10
export_armature(source, str(OUT / "source-motion.fbx"))
imported, summary = load_source(str(OUT / "source-motion.fbx"))
target_names = {role: "Target_" + name for role, name in names.items()}
target = retarget_fixture.build_biped("PreparedCharacter", target_names)
options = RetargetOptions(pairs=[(role, names[role], target_names[role]) for role in names], root_motion="IN_PLACE")
report, actions = retarget_existing(imported, target, options)
assert actions
clip = library.add_clip(target, bpy.context.scene, actions[0], "WALK", confirmed=True)
clip.source_action = imported.animation_data.action
clip.source_slot = library.slot_identifier(clip.source_action)
curves, slot = library.action_curves(clip.action, clip.slot_id)
roots = {bone.path_from_id() for bone in target.pose.bones if bone.parent is None}
root_report = [{"path": curve.data_path, "index": curve.array_index, "constant": library.constant_curve(curve, clip.start, clip.end), "modifiers": [item.type for item in curve.modifiers], "values": [curve.evaluate(frame) for frame in (clip.start, (clip.start + clip.end) / 2, clip.end)]} for curve in curves if curve.data_path.rpartition(".")[0] in roots]
(OUT / "prepared-root-audit.json").write_text(json.dumps(root_report, indent=2), encoding="utf-8")
library.validate_clip(clip, target, bpy.context.scene)
path = OUT / "prepared-library.blend"
library.save_library(target, bpy.context.scene, str(path), overwrite=True)
receiver = bpy.data.objects.new("LibraryReceiver", target.data.copy())
bpy.context.collection.objects.link(receiver)
bpy.context.view_layer.update()
library.load_library(receiver, bpy.context.scene, str(path))
assert len(receiver.cl_clips) == 1
loaded = receiver.cl_clips[0]
library.validate_clip(loaded, receiver, bpy.context.scene)
player = CharacterPlayback(receiver, bpy.context.scene, bpy.context.view_layer, {"PREVIEW": loaded}, 0)
try:
    player.update("PREVIEW", 0)
    bpy.context.view_layer.update()
    before = receiver.evaluated_get(bpy.context.evaluated_depsgraph_get()).pose.bones[target_names["upperarm_l"]].matrix.copy()
    player.update("PREVIEW", 5 / loaded.fps)
    bpy.context.view_layer.update()
    after = receiver.evaluated_get(bpy.context.evaluated_depsgraph_get()).pose.bones[target_names["upperarm_l"]].matrix
    assert max(abs(before[row][column] - after[row][column]) for row in range(4) for column in range(4)) > 0.01
finally:
    player.close()
print("FBX_IN_PLACE_LIBRARY_PLAYBACK_PASSED", flush=True)
