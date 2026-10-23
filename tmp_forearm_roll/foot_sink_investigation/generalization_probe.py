"""Probe candidate assets for the contact-stack generalization audit."""
import sys
from pathlib import Path

import bpy

ADDONS = Path(bpy.utils.resource_path("USER")) / "scripts" / "addons"
sys.path.insert(0, str(ADDONS))

CANDIDATES = [
    r"c:\Users\chenshajie1\Downloads\body.FBX",
    r"c:\Users\chenshajie1\Downloads\body(1).FBX",
    r"C:\Users\chenshajie1\Downloads\Walking.fbx",
    r"C:\Users\chenshajie1\Downloads\Breathing Idle.fbx",
    r"C:\Users\chenshajie1\Downloads\exported-model.glb",
]


def leg_info(arm):
    names = [b.name for b in arm.data.bones]
    out = {"bones": len(names), "names_sample": names[:12]}
    for key in ("Thigh", "Calf", "Foot", "Pelvis", "Spine", "Head"):
        hit = next((n for n in names if key.lower() in n.lower()), None)
        out[key] = hit
    # World rest lengths for the first thigh/calf-like chain found.
    for thigh_key in ("L Thigh", "LeftUpLeg", "Left UpLeg", "Thigh_L", "lThigh"):
        pass
    return out


def main():
    from humanoid_retarget import pipeline

    # Source GLB actions.
    bpy.ops.wm.read_factory_settings(use_empty=True)
    source, _ = pipeline.load_source(r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb")
    import humanoid_retarget.retarget as retarget
    acts = retarget.collect_actions(source)
    print("SOURCE_ACTIONS", [(a.name, int(a.frame_range[0]), int(round(a.frame_range[1]))) for a in acts], flush=True)
    print("SOURCE_BONES", len(source.data.bones), flush=True)

    for path in CANDIDATES:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        if not Path(path).is_file():
            print("MISSING", path, flush=True)
            continue
        try:
            objects, _ = pipeline.import_model(path)
        except Exception as exc:  # keep probing others
            print("IMPORT_FAIL", path, type(exc).__name__, exc, flush=True)
            continue
        arms = [o for o in objects if o.type == "ARMATURE"]
        meshes = [o for o in objects if o.type == "MESH"]
        print("CANDIDATE", path, flush=True)
        print(" objects", [(o.name, o.type) for o in objects][:8], flush=True)
        for arm in arms:
            info = leg_info(arm)
            print(" arm", arm.name, "scale", tuple(round(v, 4) for v in arm.scale),
                  "loc", tuple(round(v, 3) for v in arm.location), info, flush=True)
            # Rest world lengths of leg bones whose names contain thigh/calf/foot.
            world = arm.matrix_world
            for bone in arm.data.bones:
                low = bone.name.lower()
                if any(k in low for k in ("thigh", "calf", "upleg", "leg", "shin")) and "fore" not in low:
                    length = (world @ bone.tail_local - world @ bone.head_local).length
                    print("   bone", bone.name, "world_len_m", round(float(length), 4), flush=True)
            acts2 = []
            if arm.animation_data and arm.animation_data.action:
                acts2.append(arm.animation_data.action.name)
            print(" arm_action", acts2, "all_actions", [a.name for a in bpy.data.actions][:6], flush=True)
        for mesh in meshes[:3]:
            groups = [g.name for g in mesh.vertex_groups]
            print(" mesh", mesh.name, "verts", len(mesh.data.vertices),
                  "groups", len(groups), [g for g in groups if "Foot" in g or "Calf" in g][:6], flush=True)


if __name__ == "__main__":
    main()
