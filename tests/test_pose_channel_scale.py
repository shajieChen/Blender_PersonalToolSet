"""Pose-channel scale gate on the user's body.FBX / 突刺 glb pair."""
from __future__ import annotations

import sys

import bpy

ROOT = r"H:\Blender_Plugin"
SOURCE = r"h:\SErsiko_ExtactedTool\output\c0000_突刺_wp_a_0300.glb"
TARGET = r"c:\Users\chenshajie1\Downloads\body.FBX"


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print("PASS", message)


def main():
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    from humanoid_retarget import pipeline
    from humanoid_retarget.retarget import (
        RetargetError,
        RetargetOptions,
        _pairs_from_options,
        _pose_scales_need_compensation,
        _prepare_pose_channels,
        _preserved_pose_scales,
        _uniform_pose_scale,
        _write_pose_scales,
        correct_chest_pairs,
        correct_deform_pairs,
    )

    check(_uniform_pose_scale((1.0, 1.0, 1.0)) == (1.0, 1.0, 1.0), "unit scale is uniform")
    check(_uniform_pose_scale((0.01, 0.01, 0.01)) == (0.01, 0.01, 0.01), "uniform 0.01 is kept")
    check(_uniform_pose_scale((1.0, 1.00000012, 0.99999994)) is not None, "fbx float noise stays uniform")
    check(_uniform_pose_scale((1.0, 1.2, 1.0)) is None, "non-uniform scale is rejected")
    check(_uniform_pose_scale((-1.0, -1.0, -1.0)) is None, "mirrored scale is rejected")

    source, _ = pipeline.load_source(SOURCE)
    objects, _ = pipeline.import_model(TARGET)
    target = pipeline.pick_armature(objects)
    bpy.context.view_layer.update()
    options = RetargetOptions(joint_limits=True, soft_repulsion=True, foot_ik=True, hand_ik=True)
    pairs = correct_deform_pairs(
        source, target,
        correct_chest_pairs(source, target, _pairs_from_options(source, target, options)),
    )
    _prepare_pose_channels(source, target, pairs, options, bpy.context.scene)
    check(True, "fresh body.FBX passes the pose-channel precheck")

    pelvis = target.pose.bones["Bip01 Pelvis"]
    spine = target.pose.bones["Bip01 Spine"]
    pelvis.scale = (0.01, 0.01, 0.01)
    bpy.context.view_layer.update()
    _prepare_pose_channels(source, target, pairs, options, bpy.context.scene)
    check(True, "uniform pelvis scale 0.01 does not abort pose channels")
    scaled_offset = (spine.head - pelvis.head).length
    preserved = _preserved_pose_scales(target, ["Bip01 Pelvis", "Bip01 Spine"])
    check(
        max(abs(component - 0.01) for component in preserved["Bip01 Pelvis"]) < 1e-6,
        "pelvis uniform scale is preserved",
    )
    check(_pose_scales_need_compensation(preserved), "0.01 scale asks for compensation")
    _write_pose_scales(target, preserved, True)
    bpy.context.view_layer.update()
    unit_offset = (spine.head - pelvis.head).length
    check(unit_offset > scaled_offset * 50.0, "neutralizing pelvis scale restores child spacing")
    _write_pose_scales(target, preserved, False)
    bpy.context.view_layer.update()
    check(
        max(abs(float(v) - 0.01) for v in pelvis.scale) < 1e-6,
        "uniform pelvis scale is restored after the solve",
    )

    pelvis.scale = (1.0, 1.2, 1.0)
    bpy.context.view_layer.update()
    try:
        _prepare_pose_channels(source, target, pairs, options, bpy.context.scene)
    except RetargetError as exc:
        check("Bip01 Pelvis" in str(exc) and "非统一" in str(exc), "non-uniform pelvis names the bone")
    else:
        raise AssertionError("non-uniform pelvis scale was accepted")
    print("POSE_SCALE_OK")


if __name__ == "__main__":
    main()
