"""Read-only check of the acceptance bake. Does not save."""
import math
import bpy

BLEND = r"H:\Blender_Plugin\tmp_forearm_roll\acceptance_final\acceptance_bake.blend"


def qdeg(a, b):
    a = a.normalized()
    b = b.normalized()
    return math.degrees(2 * math.acos(min(1.0, abs(max(-1.0, min(1.0, a.dot(b)))))))


def main():
    bpy.ops.wm.open_mainfile(filepath=BLEND)
    target = bpy.data.objects["Bip01"]
    source = next(obj for obj in bpy.data.objects if obj.type == "ARMATURE" and obj.name != "Bip01")
    scene = bpy.context.scene
    print("RANGE", scene.frame_start, scene.frame_end, "ACTION", target.animation_data.action.name)

    def basis(arm, bone):
        return arm.pose.bones[bone].matrix_basis.to_quaternion().copy()

    scene.frame_set(0)
    src0 = basis(source, "L_Forearm")
    tgt0 = basis(target, "Bip01 L Forearm")
    scene.frame_set(52)
    src52 = basis(source, "L_Forearm")
    tgt52 = basis(target, "Bip01 L Forearm")
    print("SRC_0_VS_52", round(qdeg(src0, src52), 4))
    print("TGT_0_VS_52", round(qdeg(tgt0, tgt52), 4))
    print("NOT_SAVED")


if __name__ == "__main__":
    main()
