import bpy

PATH = r"C:\Users\chenshajie1\Downloads\蓝色小肥鱼Deepseek鲸鱼娘VRM_by_木子恶魔_2ac2129c60df647fbc81d0f128e48b63\蓝色小肥鱼.fbx"
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=PATH)
print("OBJECTS", len(bpy.data.objects))
for obj in bpy.data.objects:
    extra = ""
    if obj.type == "ARMATURE":
        bones = obj.data.bones
        lengths = sorted(bone.length for bone in bones)
        sample = lengths[:3] + lengths[-3:]
        extra = f" bones={len(bones)} len_sample={sample}"
    if obj.type == "MESH":
        groups = len(obj.vertex_groups)
        mods = [m.type for m in obj.modifiers]
        extra = f" groups={groups} mods={mods} verts={len(obj.data.vertices)}"
    print(obj.type, obj.name, "parent", obj.parent.name if obj.parent else None, extra)
arm = next(obj for obj in bpy.data.objects if obj.type == "ARMATURE")
print("ARM_DISPLAY", arm.display_type, "show_in_front", arm.show_in_front, "hide_viewport", arm.hide_viewport, "hide_get", arm.hide_get())
print("BONE_COLLECTIONS", [(c.name, c.is_visible) for c in arm.data.collections])
hidden = [b.name for b in arm.data.bones if b.hide]
print("HIDDEN_BONES", len(hidden), hidden[:8])
print("POSE_POSITION", arm.data.pose_position)
mesh = next(obj for obj in bpy.data.objects if obj.type == "MESH" and obj.name == "body")
print("BODY_LOC", tuple(round(v, 4) for v in mesh.matrix_world.translation))
print("ARM_LOC", tuple(round(v, 4) for v in arm.matrix_world.translation), "scale", tuple(round(v, 4) for v in arm.scale))
print("IMAGES", len(bpy.data.images))
for image in bpy.data.images:
    print(" IMAGE", image.name, image.size[:], "packed", image.packed_file is not None, "path", image.filepath)
print("ARM_DATA_DISPLAY", arm.data.display_type)
for mat in bpy.data.materials:
    images = []
    links = []
    if mat.node_tree:
        images = [n.image.name for n in mat.node_tree.nodes if n.type == "TEX_IMAGE" and n.image]
        for link in mat.node_tree.links:
            links.append(f"{link.from_node.type}:{link.from_socket.name}->{link.to_node.type}:{link.to_socket.name}")
    print("MAT", mat.name, "blend", mat.blend_method if hasattr(mat, "blend_method") else "", images)
    if mat.name in {"body", "head"}:
        print("  LINKS", links)
