import unittest

import bpy
import character_locomotion as plugin
from character_locomotion import animation_library as library


def make_rig(name="Character"):
    rig = bpy.data.objects.new(name, bpy.data.armatures.new(name))
    bpy.context.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    root = rig.data.edit_bones.new("Root")
    root.head = (0, 0, 0)
    root.tail = (0, 0, 1)
    limb = rig.data.edit_bones.new("Limb")
    limb.head = (0, 0, 1)
    limb.tail = (0, 0, 2)
    limb.parent = root
    bpy.ops.object.mode_set(mode="OBJECT")
    return rig


def make_action(rig, name, height):
    rig.animation_data_create().action = None
    bone = rig.pose.bones["Limb"]
    for frame, value in ((1, height), (11, height + 1), (21, height)):
        bone.location.z = value
        bone.keyframe_insert("location", frame=frame)
    action = rig.animation_data.action
    action.name = name
    return action


class CharacterTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        plugin.register()

    @classmethod
    def tearDownClass(cls):
        plugin.unregister()

    def setUp(self):
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete(use_global=False)
        self.rig = make_rig()
        self.scene = bpy.context.scene
        self.scene.unit_settings.scale_length = 1
        self.clips = {}
        for role, height in (("IDLE", 1.0), ("WALK", 5.0), ("RUN", 10.0)):
            action = make_action(self.rig, role, height)
            self.clips[role] = library.add_clip(self.rig, self.scene, action, role, confirmed=True)
        self.scene.cl_character = self.rig
        self.scene.frame_set(1)
        bpy.context.view_layer.update()

    def pose_height(self):
        bpy.context.view_layer.update()
        return self.rig.evaluated_get(bpy.context.evaluated_depsgraph_get()).pose.bones["Limb"].location.z
