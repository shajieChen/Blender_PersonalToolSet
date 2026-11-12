from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import bpy
import character_locomotion as plugin
from character_control_fixtures import CharacterTestCase

plugin.register()
arguments = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if "verify" in arguments:
    rig = bpy.context.scene.cl_character
    assert rig and len(rig.cl_clips) == 3
    assert rig.cl_settings.walk_speed == 2.25
    assert rig.cl_settings.walk_id == rig.cl_clips[1].clip_id
    assert rig.cl_clips[1].confirmed
    assert len(rig.animation_data.nla_tracks) == 0
    print("PERSISTENCE_REOPEN_PASSED", flush=True)
else:
    fixture = CharacterTestCase()
    fixture.setUp()
    rig = fixture.rig
    rig.cl_settings.walk_speed = 2.25
    identifiers = [clip.clip_id for clip in rig.cl_clips]
    plugin.unregister()
    plugin.register()
    assert [clip.clip_id for clip in rig.cl_clips] == identifiers
    assert rig.cl_settings.walk_speed == 2.25
    path = ROOT / "tests" / "out" / "character_control" / "persistence.blend"
    path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(path))
    print("PERSISTENCE_SAVE_PASSED", flush=True)
