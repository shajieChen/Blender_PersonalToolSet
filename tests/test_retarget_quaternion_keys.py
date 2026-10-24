import math
import unittest
from unittest.mock import patch

import bpy
from mathutils import Quaternion

from humanoid_retarget import retarget
from humanoid_retarget.classify import CORE_ROLES
from spring_bone.animation import iter_channelbags


class RetargetQuaternionKeys(unittest.TestCase):
    def test_baked_quaternion_keys_keep_the_same_hemisphere(self):
        objects = []
        actions_before = set(bpy.data.actions)
        scene = bpy.context.scene
        saved = scene.frame_current, scene.frame_subframe, scene.frame_start, scene.frame_end
        try:
            for label in ("QuaternionSource", "QuaternionTarget"):
                arm = bpy.data.objects.new(label, bpy.data.armatures.new(label))
                bpy.context.collection.objects.link(arm)
                objects.append(arm)
                bpy.context.view_layer.objects.active = arm
                arm.select_set(True)
                bpy.ops.object.mode_set(mode="EDIT")
                for index, role in enumerate(CORE_ROLES):
                    bone = arm.data.edit_bones.new(role)
                    height = 0.0 if role.startswith("foot") else 2.0 if role == "head" else 1.0
                    bone.head, bone.tail = (index * .01, 0., height), (index * .01, .1, height)
                bpy.ops.object.mode_set(mode="OBJECT")
            source, target = objects
            for frame in (1, 2):
                source.pose.bones["hips"].keyframe_insert("location", frame=frame)
            pairs = [(role, role, role) for role in CORE_ROLES]

            def write_pose(src, tgt, mapping, options):
                for pose in tgt.pose.bones:
                    pose.rotation_mode = "QUATERNION"
                    pose.rotation_quaternion = (1., 0., 0., 0.)
                angle = math.radians(170. if scene.frame_current == 1 else 190.)
                tgt.pose.bones["hips"].rotation_quaternion = Quaternion((math.cos(angle / 2.), 0., 0., math.sin(angle / 2.)))

            with patch.object(retarget, "_apply_body_orientations", side_effect=write_pose):
                _, baked = retarget.bake_retarget(source, target, retarget.RetargetOptions(pairs=pairs, foot_ik=False))
            action = baked[0]
            path = target.pose.bones["hips"].path_from_id("rotation_quaternion")
            curves = {curve.array_index: curve for bag in iter_channelbags(action, action.slots[0]) for curve in bag.fcurves if curve.data_path == path}
            first = Quaternion(tuple(curves[index].evaluate(1.) for index in range(4)))
            second = Quaternion(tuple(curves[index].evaluate(2.) for index in range(4)))
            self.assertGreater(first.dot(second), 0.)
            scene.frame_set(1, subframe=.5)
            self.assertGreater(target.pose.bones["hips"].rotation_quaternion.magnitude, .99)
        finally:
            for obj in objects:
                data = obj.data
                bpy.data.objects.remove(obj, do_unlink=True)
                if data.users == 0:
                    bpy.data.armatures.remove(data)
            for action in set(bpy.data.actions) - actions_before:
                bpy.data.actions.remove(action, do_unlink=True)
            scene.frame_start, scene.frame_end = saved[2:]
            scene.frame_set(saved[0], subframe=saved[1])
