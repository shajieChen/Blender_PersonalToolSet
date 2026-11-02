import json
import math
import os
from pathlib import Path

import bpy
from mathutils import Matrix, Quaternion, Vector

from . import mounts, weapons

PRESETS = (
    ("AUTO", "自动：优先已记住朝向", "没有记录时保持原始朝向"),
    ("ORIGINAL", "原始朝向", "相对挂点，无额外旋转"),
    ("X_POS", "翻转 +90°（X）", "围绕挂点局部 X 轴"),
    ("X_NEG", "翻转 -90°（X）", "围绕挂点局部 X 轴"),
    ("Y_HALF", "反向 180°（Y）", "围绕挂点局部 Y 轴"),
    ("Z_POS", "转向 +90°（Z）", "围绕挂点局部 Z 轴"),
    ("Z_NEG", "转向 -90°（Z）", "围绕挂点局部 Z 轴"),
)
ROTATIONS = {"ORIGINAL": ((0, 0, 1), 0), "X_POS": ((1, 0, 0), math.pi / 2), "X_NEG": ((1, 0, 0), -math.pi / 2), "Y_HALF": ((0, 1, 0), math.pi), "Z_POS": ((0, 0, 1), math.pi / 2), "Z_NEG": ((0, 0, 1), -math.pi / 2)}


def profile_file():
    return Path(bpy.utils.user_resource("CONFIG")) / "humanoid_mounts_orientations.json"


def read_profiles():
    path = profile_file()
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("朝向预设文件损坏")
    return data


def source_key(root):
    source = root.get("hm_source_file")
    if not isinstance(source, str) or not source:
        raise mounts.HumanoidMountError("请选择从外部库载入的道具")
    return os.path.normcase(str(Path(source).resolve()))


def initial_matrix(obj):
    values = obj.get("hm_library_initial_matrix")
    if values is None or len(values) != 16:
        raise mounts.HumanoidMountError("旧道具没有原始朝向记录，请从库重新载入")
    matrix = Matrix([values[index:index + 4] for index in range(0, 16, 4)])
    mounts.validate_matrix(matrix)
    return matrix


def current_correction(root):
    weapons.validate_grip(root)
    if not root.children:
        raise mounts.HumanoidMountError("道具没有部件")
    reference = mounts.world_matrix(root.parent) if root.parent is not None else mounts.world_matrix(root)
    inverse = reference.inverted()
    corrections = [inverse @ mounts.world_matrix(obj) @ initial_matrix(obj).inverted() for obj in root.children]
    correction = corrections[0]
    mounts.validate_matrix(correction)
    if any(mounts.matrix_distance(correction, other) > mounts.MATRIX_TOLERANCE for other in corrections[1:]):
        raise mounts.HumanoidMountError("部件分别调整过，无法套用统一朝向；请重新载入后整体调整")
    return correction


def preset_rotation(root, preset, part):
    if preset == "AUTO":
        record = read_profiles().get(source_key(root), {})
        if not isinstance(record, dict):
            raise ValueError("朝向预设记录损坏")
        values = record.get(part)
        if values is None:
            return Quaternion()
        if not isinstance(values, list) or len(values) != 4 or any(type(value) not in (int, float) or not math.isfinite(value) for value in values):
            raise ValueError("已保存的朝向无效")
        rotation = Quaternion(values)
        if rotation.magnitude < 1e-8:
            raise ValueError("已保存的朝向无效")
        return rotation.normalized()
    if preset not in ROTATIONS:
        raise ValueError("未知朝向预设")
    axis, angle = ROTATIONS[preset]
    return Quaternion(Vector(axis), angle)


def apply_preset(root, preset, part):
    correction = current_correction(root)
    rotation = preset_rotation(root, preset, part)
    reference = mounts.world_matrix(root.parent) if root.parent is not None else mounts.world_matrix(root)
    desired = reference @ Matrix.LocRotScale(correction.translation, rotation, correction.to_scale())
    poses = [mounts.ParentPose(obj) for obj in root.children]
    try:
        for pose in poses:
            mounts.parent_at_world(pose.obj, root, desired @ initial_matrix(pose.obj))
    except Exception:
        for pose in poses:
            pose.restore()
        raise


def save_orientation(root, part):
    rotation = current_correction(root).to_quaternion().normalized()
    profiles = read_profiles()
    key = source_key(root)
    if key in profiles and not isinstance(profiles[key], dict):
        raise ValueError("朝向预设记录损坏")
    profiles.setdefault(key, {})[part] = list(rotation)
    target = profile_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(profiles, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, target)
