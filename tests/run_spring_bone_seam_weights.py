import json
from pathlib import Path

import bpy
import numpy as np

from spring_bone.contact_bake import _mesh_token, _skin_weights


def repair_seam_weights(armature, garment, approved_vertices, backup_path, minimum_weight=.65):
    names = [item.name for chain in armature.sb_settings.chains for item in chain.bone_names]
    spring = _skin_weights(garment, armature, names)
    totals = spring.sum(axis=1)
    deform = {group.index for group in garment.vertex_groups if group.name in armature.data.bones and armature.data.bones[group.name].use_deform}
    spring_groups = {group.index for group in garment.vertex_groups if group.name in names}
    positions = np.array([vertex.co[:] for vertex in garment.data.vertices])
    support = np.flatnonzero(totals >= minimum_weight)
    selected = [int(index) for index in sorted(set(approved_vertices)) if totals[index] < minimum_weight]
    if not len(support) or not 0.0 < minimum_weight <= 1.0:
        raise ValueError("接缝权重范围或参考顶点无效")
    backup = {"object": garment.name, "mesh_before": _mesh_token(garment).hex(), "minimum_weight": minimum_weight, "vertices": []}
    for index in selected:
        vertex = garment.data.vertices[index]
        original = {slot.group: float(slot.weight) for slot in vertex.groups}
        total = sum(weight for group, weight in original.items() if group in deform)
        if total <= 1e-8:
            raise ValueError(f"顶点 {index} 没有有效的原蒙皮")
        nearest = int(support[np.linalg.norm(positions[support] - positions[index], axis=1).argmin()])
        target_name = names[int(spring[nearest].argmax())]
        target_group = garment.vertex_groups.get(target_name)
        if target_group is None:
            raise ValueError("缺少接缝对应的裙骨顶点组")
        values = dict(original)
        for group in deform - spring_groups:
            values[group] = original.get(group, 0.0) * (1.0 - minimum_weight) / max(1.0 - totals[index], 1e-12)
        if totals[index] > 1e-8:
            for group in spring_groups:
                values[group] = original.get(group, 0.0) * minimum_weight / totals[index]
        else:
            values[target_group.index] = minimum_weight * total
        backup["vertices"].append({"index": index, "before": {garment.vertex_groups[group].name: value for group, value in original.items()}, "after": {garment.vertex_groups[group].name: value for group, value in values.items() if value > 0.0}})
    path = Path(backup_path)
    if path.exists():
        raise FileExistsError(path)
    path.write_text(json.dumps(backup, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        for row in backup["vertices"]:
            for name, value in row["after"].items():
                garment.vertex_groups[name].add([row["index"]], value, "REPLACE")
    except Exception:
        restore_seam_weights(garment, backup)
        raise
    garment.data.update()
    return backup


def restore_seam_weights(garment, backup):
    if garment.name != backup["object"]:
        raise ValueError("备份对象不匹配")
    for row in backup["vertices"]:
        for name in set(row["after"]) - set(row["before"]):
            garment.vertex_groups[name].remove([row["index"]])
        for name, value in row["before"].items():
            garment.vertex_groups[name].add([row["index"]], value, "REPLACE")
    garment.data.update()
