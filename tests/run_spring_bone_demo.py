import math
import os
import sys
import time

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bpy
from mathutils import Quaternion, Vector

import spring_bone
from spring_bone.animation import SpringBoneBakeJob, specs_from_settings
from spring_bone.solver import CapsuleCollider, SphereCollider, signed_collider_distance

EVIDENCE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "docs",
    "superpowers",
    "evidence",
    "2026-10-23-spring-bone",
)


def _bone(arm, name, head, tail, parent):
    bone = arm.edit_bones.new(name)
    bone.head = head
    bone.tail = tail
    if parent:
        bone.parent = arm.edit_bones[parent]
    return bone


def _key_quat(pose, frame, axis, angle):
    pose.rotation_mode = "QUATERNION"
    pose.rotation_quaternion = Quaternion(Vector(axis), angle)
    pose.keyframe_insert("rotation_quaternion", frame=frame)


def _key_loc(pose, frame, location):
    pose.location = location
    pose.keyframe_insert("location", frame=frame)


def build_scene():
    spring_bone.register()
    scene = bpy.context.scene
    cube = bpy.data.objects.get("Cube")
    if cube is not None:
        bpy.data.objects.remove(cube, do_unlink=True)
    scene.render.fps = 30
    scene.render.fps_base = 1.0
    scene.frame_start = 1
    scene.frame_end = 301
    scene.unit_settings.scale_length = 1.0
    arm_data = bpy.data.armatures.new("SkirtArm")
    arm = bpy.data.objects.new("SkirtArm", arm_data)
    scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    _bone(arm_data, "Pelvis", (0.0, 0.0, 0.9), (0.0, 0.0, 1.1), "")
    _bone(arm_data, "Thigh.L", (0.09, 0.0, 0.9), (0.09, 0.04, 0.5), "Pelvis")
    _bone(arm_data, "Shin.L", (0.09, 0.04, 0.5), (0.09, 0.06, 0.12), "Thigh.L")
    _bone(arm_data, "Thigh.R", (-0.09, 0.0, 0.9), (-0.09, 0.04, 0.5), "Pelvis")
    _bone(arm_data, "Shin.R", (-0.09, 0.04, 0.5), (-0.09, 0.06, 0.12), "Thigh.R")
    names = []
    for index in range(8):
        angle = index * math.tau / 8.0
        direction = Vector((math.cos(angle), math.sin(angle), 0.0))
        heights = (0.9, 0.72, 0.54, 0.36)
        radii = (0.15, 0.2, 0.26, 0.32)
        parent = "Pelvis"
        for segment in range(3):
            name = f"Skirt_{index}_{segment}"
            head = direction * radii[segment] + Vector((0.0, 0.0, heights[segment]))
            tail = direction * radii[segment + 1] + Vector((0.0, 0.0, heights[segment + 1]))
            _bone(arm_data, name, head, tail, parent)
            names.append(name)
            parent = name
    bpy.ops.object.mode_set(mode="POSE")
    settings = arm.sb_settings
    for index in range(8):
        chain = settings.chains.add()
        chain.name = f"裙{index}"
        chain.stiffness = 8.0
        chain.drag_force = 0.5
        chain.gravity_power = 1.5
        chain.gravity_dir = (0.0, 0.0, -1.0)
        chain.hit_radius_m = 0.01
        chain.weight = 1.0
        chain.cone_enabled = True
        chain.cone_angle_deg = 70.0
        chain.inertia_space = "WORLD"
        chain.warmup_seconds = 0.5
        for segment in range(3):
            item = chain.bone_names.add()
            item.name = f"Skirt_{index}_{segment}"
    for bone_name, shape, radius, head, tail in (
        ("Pelvis", "SPHERE", 0.11, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
        ("Thigh.L", "CAPSULE", 0.07, (0.0, 0.04, 0.0), (0.0, 0.36, 0.0)),
        ("Shin.L", "CAPSULE", 0.055, (0.0, 0.03, 0.0), (0.0, 0.32, 0.0)),
        ("Thigh.R", "CAPSULE", 0.07, (0.0, 0.04, 0.0), (0.0, 0.36, 0.0)),
        ("Shin.R", "CAPSULE", 0.055, (0.0, 0.03, 0.0), (0.0, 0.32, 0.0)),
    ):
        collider = settings.colliders.add()
        collider.name = bone_name
        collider.shape = shape
        collider.bone_name = bone_name
        collider.radius_m = radius
        collider.head_offset_m = head
        collider.tail_offset_m = tail
    _animate(arm)
    _mesh(arm, names)
    _limb_mesh(arm)
    return arm


def _animate(arm):
    pelvis = arm.pose.bones["Pelvis"]
    left = arm.pose.bones["Thigh.L"]
    right = arm.pose.bones["Thigh.R"]
    shin_l = arm.pose.bones["Shin.L"]
    shin_r = arm.pose.bones["Shin.R"]
    samples = (
        (1, (0.0, 0.0, 0.0), 0.0, 0.35, -0.35, 0.25, 0.25),
        (20, (0.0, 0.03, -0.16), 0.0, -0.45, 0.45, 0.55, 0.1),
        (40, (0.0, 0.0, -0.32), 0.0, 0.45, -0.45, 0.1, 0.55),
        (60, (0.0, 0.03, -0.48), 0.0, -0.35, 0.35, 0.45, 0.15),
        (75, (0.0, 0.0, -0.6), 0.0, 0.2, -0.2, 0.2, 0.2),
        (110, (0.0, 0.0, -0.6), math.radians(90.0), 0.15, -0.15, 0.1, 0.1),
        (150, (0.0, 0.0, -0.6), math.radians(180.0), 0.0, 0.0, 0.1, 0.1),
        (190, (0.0, -0.26, -0.6), math.radians(180.0), 1.15, 1.15, 1.35, 1.35),
        (225, (0.0, 0.0, -0.6), math.radians(180.0), 0.15, 0.15, 0.15, 0.15),
        (250, (0.0, 0.0, -0.6), math.radians(180.0), 1.5, 0.05, 0.3, 0.1),
        (270, (0.0, 0.02, -0.72), math.radians(180.0), 0.25, 0.15, 0.15, 0.15),
        (301, (0.0, 0.0, -0.85), math.radians(180.0), 0.2, -0.2, 0.2, 0.2),
    )
    for frame, location, yaw, thigh_l, thigh_r, shin_left, shin_right in samples:
        pelvis.location = location
        pelvis.rotation_mode = "QUATERNION"
        pelvis.rotation_quaternion = Quaternion(Vector((0.0, 0.0, 1.0)), yaw)
        pelvis.keyframe_insert("location", frame=frame)
        pelvis.keyframe_insert("rotation_quaternion", frame=frame)
        _key_quat(left, frame, (1.0, 0.0, 0.0), thigh_l)
        _key_quat(right, frame, (1.0, 0.0, 0.0), thigh_r)
        _key_quat(shin_l, frame, (1.0, 0.0, 0.0), shin_left)
        _key_quat(shin_r, frame, (1.0, 0.0, 0.0), shin_right)


def _mesh(arm, bone_names):
    vertices = []
    faces = []
    weights = []
    for index in range(8):
        angle = index * math.tau / 8.0
        radial = Vector((math.cos(angle), math.sin(angle), 0.0))
        side = Vector((-math.sin(angle), math.cos(angle), 0.0)) * 0.035
        column = []
        for row, (radius, height) in enumerate(((0.15, 0.9), (0.2, 0.72), (0.26, 0.54), (0.32, 0.36))):
            center = radial * radius + Vector((0.0, 0.0, height))
            column.append(len(vertices))
            vertices.append(center - side)
            column.append(len(vertices))
            vertices.append(center + side)
            bone = "Pelvis" if row == 0 else f"Skirt_{index}_{row - 1}"
            weights.append(bone)
            weights.append(bone)
        for row in range(3):
            a = column[row * 2]
            b = column[row * 2 + 1]
            c = column[row * 2 + 2]
            d = column[row * 2 + 3]
            faces.append((a, b, d, c))
    mesh = bpy.data.meshes.new("SkirtMesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new("SkirtMesh", mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.parent = arm
    modifier = obj.modifiers.new("Armature", "ARMATURE")
    modifier.object = arm
    groups = {}
    for name in ["Pelvis", *bone_names]:
        groups[name] = obj.vertex_groups.new(name=name)
    for vertex, bone in enumerate(weights):
        groups[bone].add([vertex], 1.0, "REPLACE")
    material = bpy.data.materials.new("Skirt")
    material.use_nodes = True
    principled = next(node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
    principled.inputs[0].default_value = (0.72, 0.22, 0.32, 1.0)
    mesh.materials.append(material)
    obj.color = (0.72, 0.22, 0.32, 1.0)


def _limb_mesh(arm):
    vertices = []
    faces = []
    weights = []
    limbs = (
        ("Thigh.L", (0.09, 0.0, 0.9), (0.09, 0.04, 0.5)),
        ("Shin.L", (0.09, 0.04, 0.5), (0.09, 0.06, 0.12)),
        ("Thigh.R", (-0.09, 0.0, 0.9), (-0.09, 0.04, 0.5)),
        ("Shin.R", (-0.09, 0.04, 0.5), (-0.09, 0.06, 0.12)),
    )
    for name, head, tail in limbs:
        start = Vector(head)
        end = Vector(tail)
        side = Vector((0.02, 0.0, 0.0))
        base = len(vertices)
        vertices.extend((start - side, start + side, end + side, end - side))
        faces.append((base, base + 1, base + 2, base + 3))
        weights.extend((name, name, name, name))
    mesh = bpy.data.meshes.new("LegMesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new("LegMesh", mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.parent = arm
    modifier = obj.modifiers.new("Armature", "ARMATURE")
    modifier.object = arm
    groups = {}
    for name, _head, _tail in limbs:
        groups[name] = obj.vertex_groups.new(name=name)
    for vertex, bone in enumerate(weights):
        groups[bone].add([vertex], 1.0, "REPLACE")
    obj.color = (0.32, 0.28, 0.24, 1.0)


def _percentile(values, fraction):
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def _measure(arm, chains, colliders):
    scene = bpy.context.scene
    scale = scene.unit_settings.scale_length
    sections = (("walk", 1, 75), ("turn", 76, 150), ("squat", 151, 225), ("raise", 226, 301))
    rows = []
    for label, start, end in sections:
        deepest = 0.0
        longest = 0.0
        for frame in range(start, end + 1, 15):
            scene.frame_set(frame)
            for chain in chains:
                for name in chain.bone_names:
                    pose = arm.pose.bones[name]
                    tail = (arm.matrix_world @ pose.tail) * scale
                    head = (arm.matrix_world @ pose.head) * scale
                    longest = max(longest, abs((tail - head).length - pose.bone.length * scale))
                    for spec in colliders:
                        bind = arm.matrix_world @ arm.pose.bones[spec.bone_name].matrix
                        center = (bind @ (Vector(spec.head_offset_m) / scale)) * scale
                        if spec.shape == "SPHERE":
                            signed = signed_collider_distance(
                                tail,
                                SphereCollider(center, spec.radius_m),
                                chain.parameters.hit_radius_m,
                            )
                        else:
                            end_point = (bind @ (Vector(spec.tail_offset_m) / scale)) * scale
                            signed = signed_collider_distance(
                                tail,
                                CapsuleCollider(center, end_point, spec.radius_m),
                                chain.parameters.hit_radius_m,
                            )
                        deepest = max(deepest, max(0.0, -signed))
        rows.append((label, deepest, longest))
    return rows


def main():
    started = time.perf_counter()
    arm = build_scene()
    print("SPRING_BONE_FILE", spring_bone.__file__)
    print("SPRING_BONE_BLENDER", bpy.app.version_string, getattr(bpy.app, "build_hash", ""))
    chains, colliders = specs_from_settings(arm.sb_settings)
    scene = bpy.context.scene
    job = SpringBoneBakeJob(arm, chains, colliders, scene.frame_start, scene.frame_end, True)
    job.run_budgeted()
    elapsed = time.perf_counter() - started
    sections = _measure(arm, chains, colliders)
    p95 = _percentile(job.slice_seconds, 0.95)
    print("SPRING_BONE_DEMO_SECONDS", round(elapsed, 3))
    print("SPRING_BONE_DEMO_STAGES", {key: round(value, 3) for key, value in job.stage_seconds.items()})
    print("SPRING_BONE_DEMO_LONGEST_UNIT", round(job.longest_unit, 4))
    print("SPRING_BONE_DEMO_P95_SLICE", round(p95, 4))
    print("SPRING_BONE_DEMO_SLICES", len(job.slice_seconds))
    print("SPRING_BONE_DEMO_PENETRATION", job.max_penetration_m)
    for label, depth, length_error in sections:
        print("SPRING_BONE_DEMO_SECTION", label, round(depth, 6), round(length_error, 6))
    if elapsed > 10.0 or p95 > 0.05:
        print("SPRING_BONE_DEMO_CONCERN", round(elapsed, 3), round(p95, 4), round(job.longest_unit, 4))
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 960
    scene.render.resolution_y = 720
    scene.display.shading.color_type = "OBJECT"
    scene.display.shading.light = "STUDIO"
    scene.camera = bpy.data.objects.get("Camera")
    if scene.camera is not None:
        scene.camera.data.lens = 48.0
        scene.camera.data.clip_start = 0.05
        scene.camera.data.clip_end = 50.0
    target = bpy.data.objects.new("SkirtLook", None)
    scene.collection.objects.link(target)
    if scene.camera is not None:
        constraint = scene.camera.constraints.new("TRACK_TO")
        constraint.target = target
        constraint.track_axis = "TRACK_NEGATIVE_Z"
        constraint.up_axis = "UP_Y"
    for label, frame in (("walk", 40), ("turn", 110), ("squat", 190), ("raise", 250)):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        pelvis = arm.matrix_world @ arm.pose.bones["Pelvis"].head
        thigh = arm.matrix_world @ arm.pose.bones["Thigh.L"].tail
        hem = arm.matrix_world @ arm.pose.bones["Skirt_0_2"].tail
        points = []
        for bone in arm.pose.bones:
            points.append(arm.matrix_world @ bone.head)
            points.append(arm.matrix_world @ bone.tail)
        low = Vector((min(point.x for point in points), min(point.y for point in points), min(point.z for point in points)))
        high = Vector((max(point.x for point in points), max(point.y for point in points), max(point.z for point in points)))
        center = (low + high) * 0.5
        span = max((high - low).length, 0.4)
        target.location = center
        if scene.camera is not None:
            scene.camera.location = center + Vector((span * 0.85, -span * 1.05, span * 0.28))
        print(
            "SPRING_BONE_DEMO_FRAME",
            label,
            frame,
            tuple(round(value, 4) for value in pelvis),
            tuple(round(value, 4) for value in thigh),
            tuple(round(value, 4) for value in hem),
        )
        scene.render.filepath = os.path.join(EVIDENCE, f"skirt_{label}.png")
        bpy.ops.render.render(write_still=True)
    if job.entry_action is not None:
        job.entry_action.use_fake_user = True
    print("SPRING_BONE_DEMO_ACTIONS", " ".join(action.name for action in bpy.data.actions))
    blend = os.path.join(EVIDENCE, "skirt_demo.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend)
    print("SPRING_BONE_DEMO_OK")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception as exc:
        print("SPRING_BONE_DEMO_FAIL", type(exc).__name__, exc)
        code = 1
    sys.exit(code)
