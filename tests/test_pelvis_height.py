import math
import pathlib
import sys
import unittest

import bpy
from mathutils import Matrix

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from run_retarget_test import build_biped, junk_names
from humanoid_retarget.retarget import RetargetError, RetargetOptions, bake_retarget, capture_reference


class PelvisHeightTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def run_bake(self, leg_scale, torso_scale, object_scale=1.0, offsets=(0.0, 0.0), reference="REST", in_place=False, skin=False, yaw=0.0, floor_height=0.0, foot_mapping=True):
        source_names = junk_names()
        target_names = {role: "Receiver_" + role for role in source_names}
        source = build_biped("Motion", source_names)
        bpy.ops.object.mode_set(mode="OBJECT")
        target = build_biped("Receiver", target_names)
        bpy.ops.object.mode_set(mode="EDIT")
        for role, name in target_names.items():
            bone = target.data.edit_bones[name]
            for point in (bone.head, bone.tail):
                if role.startswith(("thigh", "shin", "foot", "toe")):
                    point.z *= leg_scale
                else:
                    point.z = 0.95 * leg_scale + (point.z - 0.95) * torso_scale
                point /= object_scale
        bpy.ops.object.mode_set(mode="OBJECT")
        target.scale = (object_scale,) * 3
        target.rotation_euler.z = yaw
        source.location.z = offsets[0]
        target.location.z = offsets[1]
        bpy.context.view_layer.update()
        if skin:
            for arm, names, size in ((source, source_names, 1.0), (target, target_names, object_scale)):
                data = bpy.data.meshes.new(arm.name + "Soles")
                data.from_pydata([(0.1 / size, 0, 0), (-0.1 / size, 0, 0), (0, 0, -5.0 / size)], [], [])
                mesh = bpy.data.objects.new(data.name, data)
                bpy.context.collection.objects.link(mesh)
                mesh.parent = arm
                mesh.matrix_parent_inverse = Matrix.Identity(4)
                for index, side in enumerate(("l", "r")):
                    mesh.vertex_groups.new(name=names["foot_" + side]).add([index], 1.0, "REPLACE")
                mesh.vertex_groups.new(name=names["head"]).add([2], 1.0, "REPLACE")
                mesh.modifiers.new("Deform", "ARMATURE").object = arm
        hips = source.pose.bones[source_names["hips"]]
        source.animation_data_create()
        for frame, height in ((1, 0.0), (2, -0.3), (3, 0.2)):
            hips.location = (0.12 * (frame - 1), height, 0.07 * (frame - 1))
            hips.keyframe_insert("location", frame=frame)
        scene = bpy.context.scene
        scene.frame_set(1)
        pairs = [(role, source_names[role], target_names[role]) for role in source_names]
        if not foot_mapping:
            pairs = [pair for pair in pairs if pair[0] not in {"foot_l", "foot_r"}]
        options = RetargetOptions(pairs=pairs, root_motion="IN_PLACE" if in_place else "KEEP")
        options.foot_ik_settings.floor_height_m = floor_height
        if reference in {"CURRENT", "CURRENT_MISSING_MATRIX"}:
            target.pose.bones[target_names["hips"]].location.y = 0.1 / object_scale
            bpy.context.view_layer.update()
            options.reference = "CURRENT"
            options.reference_data = capture_reference(source, target, pairs)
            if reference == "CURRENT_MISSING_MATRIX":
                options.reference_data["source_matrix"].pop(source_names["hips"])
        source_ref = source.matrix_world @ source.pose.bones[source_names["hips"]].head
        target_ref = target.matrix_world @ target.pose.bones[target_names["hips"]].head
        source_floor = offsets[0] + (0.0 if skin else 0.03)
        target_floor = offsets[1] + (0.0 if skin else 0.03 * leg_scale)
        if not foot_mapping:
            source_floor = floor_height
            target_floor = floor_height
        vertical_ratio = (target_ref.z - target_floor) / (source_ref.z - source_floor)
        source_torso = (source.matrix_world @ source.data.bones[source_names["head"]].tail_local).z - (source.matrix_world @ source.data.bones[source_names["hips"]].head_local).z
        target_torso = (target.matrix_world @ target.data.bones[target_names["head"]].tail_local).z - (target.matrix_world @ target.data.bones[target_names["hips"]].head_local).z
        _, actions = bake_retarget(source, target, options)
        self.assertEqual(len(actions), 1)
        for frame in (1, 2, 3):
            scene.frame_set(frame)
            source_delta = source.matrix_world @ source.pose.bones[source_names["hips"]].head - source_ref
            target_delta = target.matrix_world @ target.pose.bones[target_names["hips"]].head - target_ref
            self.assertAlmostEqual(target_delta.z, source_delta.z * vertical_ratio, delta=2e-5)
            for axis in (0, 1):
                expected = 0.0 if in_place else source_delta[axis] * target_torso / source_torso
                self.assertAlmostEqual(target_delta[axis], expected, delta=2e-5)

    def test_short_legs_and_large_torso(self):
        self.run_bake(0.5, 1.4)

    def test_long_legs_and_small_torso(self):
        self.run_bake(1.8, 0.6)

    def test_object_scale_and_distinct_vertical_origins(self):
        self.run_bake(0.6, 1.2, 0.01, (3.0, -4.0))

    def test_current_reference_and_in_place(self):
        self.run_bake(0.6, 1.2, reference="CURRENT", in_place=True)

    def test_bind_mesh_sole_is_used(self):
        self.run_bake(0.5, 1.4, 0.01, (2.0, 5.0), skin=True)

    def test_uniform_proportions_keep_existing_scale(self):
        self.run_bake(1.25, 1.25)

    def test_rotated_object_preserves_world_vertical_and_horizontal_motion(self):
        self.run_bake(0.6, 1.2, 0.01, yaw=math.pi / 2)

    def test_pelvis_below_support_plane_fails_explicitly(self):
        with self.assertRaisesRegex(RetargetError, "参考髋部"):
            self.run_bake(-0.5, 1.0)

    def test_incomplete_current_hip_reference_fails_explicitly(self):
        with self.assertRaisesRegex(RetargetError, "参考.*髋部|髋部.*参考"):
            self.run_bake(0.6, 1.2, reference="CURRENT_MISSING_MATRIX")

    def test_bind_proportions_do_not_depend_on_configured_floor(self):
        self.run_bake(0.5, 1.4, skin=True, floor_height=2.0)

    def test_missing_foot_mapping_uses_explicit_floor(self):
        self.run_bake(0.6, 1.2, floor_height=0.2, foot_mapping=False)
