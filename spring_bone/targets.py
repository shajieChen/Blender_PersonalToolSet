def scene_armature(scene, obj):
    return obj.type == "ARMATURE" and scene.objects.get(obj.name) == obj


def target_armature(context):
    scene = context.scene
    target = getattr(scene, "sb_target_armature", None)
    if target is not None:
        return target if scene_armature(scene, target) else None
    obj = context.object
    if obj is None:
        return None
    if obj.type == "ARMATURE":
        target = obj
    elif obj.type == "MESH":
        target = obj.find_armature()
    else:
        return None
    return target if target is not None and scene_armature(scene, target) else None
