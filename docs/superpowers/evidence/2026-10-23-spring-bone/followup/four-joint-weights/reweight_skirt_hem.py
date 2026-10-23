import hashlib
import json
import math
import struct
from pathlib import Path

import bpy
from mathutils import Matrix


EVIDENCE = Path('H:/Blender_Plugin/docs/superpowers/evidence/2026-10-23-spring-bone/followup/four-joint-weights')
CHAIN_RECORD = EVIDENCE.parent / 'skirt-chain-repair.json'
BLEND_START = 0.35
BLEND_END = 1.0
MAX_TIP_SHARE = 0.8
WEIGHT_EPSILON = 1e-6
TEST_ROTATION = 0.35


def transfer_weight(weight, position):
    ratio = max(0.0, min(1.0, (position - BLEND_START) / (BLEND_END - BLEND_START)))
    return weight * MAX_TIP_SHARE * ratio * ratio * (3.0 - 2.0 * ratio)


def weight_rows(data):
    return [{slot.group: float(slot.weight) for slot in vertex.groups} for vertex in data.vertices]


def mesh_digest(data):
    digest = hashlib.sha256()
    for vertex in data.vertices:
        digest.update(struct.pack('<I3f', vertex.index, *vertex.co))
        for slot in vertex.groups:
            digest.update(struct.pack('<If', slot.group, slot.weight))
    return digest.hexdigest()


def evaluated_positions(obj):
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    data = evaluated.to_mesh()
    try:
        return [evaluated.matrix_world @ vertex.co for vertex in data.vertices]
    finally:
        evaluated.to_mesh_clear()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def apply_weights():
    assert transfer_weight(0.6, BLEND_START) == 0.0
    assert abs(transfer_weight(0.6, BLEND_END) - 0.48) < 1e-12
    assert abs(transfer_weight(0.6, 0.675) - 0.24) < 1e-12
    scene = bpy.context.scene
    armature = scene.sb_target_armature
    assert armature is not None and armature.name == '骨架'
    obj = bpy.data.objects.get('clothing')
    assert obj is not None and obj.type == 'MESH' and obj.mode != 'EDIT'
    assert any(modifier.type == 'ARMATURE' and modifier.object == armature and modifier.use_vertex_groups for modifier in obj.modifiers)
    assert obj.library is None and obj.data.library is None and obj.data.shape_keys is None
    import spring_bone.operators as spring_operators
    assert spring_operators.active_session() is None
    assert not (EVIDENCE / 'weights-before.json').exists(), 'A weight backup already exists; do not apply twice'
    saved = json.loads(CHAIN_RECORD.read_text(encoding='utf-8'))
    expected = {chain['name']: chain['bones'] for chain in saved['before']['chains']}
    chains = {chain.name: chain for chain in armature.sb_settings.chains}
    assert set(expected).issubset(chains)
    for name, bones in expected.items():
        assert [bone.name for bone in chains[name].bone_names] in (bones, bones[:-1])
        assert all(bone in armature.data.bones for bone in bones)
        assert armature.data.bones[bones[-1]].use_deform
    original = obj.data
    original_hash = mesh_digest(original)
    original_fake_user = original.use_fake_user
    original_groups = [group.name for group in obj.vertex_groups]
    original_active_group = obj.vertex_groups.active_index
    original_rows = weight_rows(original)
    previous_chains = {name: [bone.name for bone in chain.bone_names] for name, chain in chains.items()}
    entry_action = armature.animation_data.action
    entry_slot = armature.animation_data.action_slot
    entry_frame = scene.frame_current
    entry_subframe = scene.frame_subframe
    entry_pose_position = armature.data.pose_position
    entry_poses = {pose.name: pose.matrix_basis.copy() for pose in armature.pose.bones}
    group_indices = {group.name: group.index for group in obj.vertex_groups}
    plans = []
    summary = []
    for name, bones in expected.items():
        donor_name, tip_name = bones[-2:]
        donor_index = group_indices[donor_name]
        tip_index = group_indices.get(tip_name)
        assert tip_index is None or all(row.get(tip_index, 0.0) <= WEIGHT_EPSILON for row in original_rows)
        bone = armature.data.bones[donor_name]
        head = armature.matrix_world @ bone.head_local
        tail = armature.matrix_world @ bone.tail_local
        axis = tail - head
        length = axis.length
        assert length > 1e-6
        axis.normalize()
        values = []
        for vertex, row in zip(original.vertices, original_rows):
            weight = row.get(donor_index, 0.0)
            if weight <= WEIGHT_EPSILON:
                continue
            position = ((obj.matrix_world @ vertex.co) - head).dot(axis) / length
            moved = transfer_weight(weight, position)
            if moved > WEIGHT_EPSILON:
                values.append((vertex.index, weight - moved, moved))
        assert values, tip_name
        plans.append((donor_name, tip_name, values))
        summary.append({'chain': name, 'donor': donor_name, 'tip': tip_name, 'vertices': len(values), 'maximum_tip_weight': max(value[2] for value in values)})
    before = {
        'armature': armature.name,
        'object': obj.name,
        'mesh': original.name,
        'mesh_hash': original_hash,
        'fake_user': original_fake_user,
        'groups': original_groups,
        'weights': original_rows,
        'chains': previous_chains,
        'action': entry_action.name,
        'frame': entry_frame,
        'subframe': entry_subframe,
        'plan': summary,
        'red_selected': len(plans),
        'red_unweighted_tips': len(plans),
    }
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    write_json(EVIDENCE / 'weights-before.json', before)
    bpy.data.libraries.write(str(EVIDENCE / 'weights-before.blend'), {obj, armature}, fake_user=True, compress=True)
    replacement = None
    created_groups = []
    try:
        if bpy.ops.ed.undo_push.poll():
            bpy.ops.ed.undo_push(message='裙摆末端权重修改前')
        armature.data.pose_position = 'REST'
        bpy.context.view_layer.update()
        rest_before = evaluated_positions(obj)
        replacement = original.copy()
        replacement.name = original.name + '_SkirtHem'
        original.use_fake_user = True
        obj.data = replacement
        for donor_name, tip_name, values in plans:
            donor = obj.vertex_groups[donor_name]
            tip = obj.vertex_groups.get(tip_name)
            if tip is None:
                tip = obj.vertex_groups.new(name=tip_name)
                created_groups.append(tip_name)
            for vertex_index, remaining, moved in values:
                donor.add([vertex_index], remaining, 'REPLACE')
                tip.add([vertex_index], moved, 'REPLACE')
        for name, bones in expected.items():
            chain = chains[name]
            chain.bone_names.clear()
            for bone in bones:
                chain.bone_names.add().name = bone
        bpy.context.view_layer.update()
        rest_after = evaluated_positions(obj)
        rest_error = max((left - right).length for left, right in zip(rest_before, rest_after))
        assert rest_error < 1e-6, ('REST deformation changed', rest_error)
        after_rows = weight_rows(replacement)
        allowed = {obj.vertex_groups[name].index for donor, tip, _ in plans for name in (donor, tip)}
        modified_vertices = set()
        maximum_sum_error = 0.0
        for vertex_index, (before_row, after_row) in enumerate(zip(original_rows, after_rows)):
            maximum_sum_error = max(maximum_sum_error, abs(sum(before_row.values()) - sum(after_row.values())))
            for index in set(before_row) | set(after_row):
                assert math.isfinite(after_row.get(index, 0.0))
                assert after_row.get(index, 0.0) >= 0.0
                if index not in allowed:
                    assert before_row.get(index, 0.0) == after_row.get(index, 0.0)
            if before_row != after_row:
                modified_vertices.add(vertex_index)
        assert maximum_sum_error < 1e-6
        assert mesh_digest(original) == original_hash
        assert [group.name for group in obj.vertex_groups][:len(original_groups)] == original_groups
        armature.data.pose_position = entry_pose_position
        bpy.context.view_layer.update()
        baseline = evaluated_positions(obj)
        motion = []
        for donor_name, tip_name, values in plans:
            pose = armature.pose.bones[tip_name]
            basis = pose.matrix_basis.copy()
            try:
                pose.matrix_basis = basis @ Matrix.Rotation(TEST_ROTATION, 4, 'X')
                bpy.context.view_layer.update()
                deformed = evaluated_positions(obj)
                deltas = [(left - right).length * scene.unit_settings.scale_length for left, right in zip(baseline, deformed)]
                record = {'bone': tip_name, 'moving_vertices': sum(delta > 1e-6 for delta in deltas), 'maximum_motion_m': max(deltas)}
                assert record['moving_vertices'] > 0 and record['maximum_motion_m'] > 1e-5, record
                motion.append(record)
            finally:
                pose.matrix_basis = basis
                bpy.context.view_layer.update()
        assert armature.animation_data.action == entry_action
        assert armature.animation_data.action_slot == entry_slot
        result = {
            'status': 'GREEN',
            'selected': len(motion),
            'mesh': replacement.name,
            'original_mesh': original.name,
            'original_mesh_unchanged': mesh_digest(original) == original_hash,
            'unique_vertices_modified': len(modified_vertices),
            'maximum_weight_sum_error': maximum_sum_error,
            'rest_mesh_error': rest_error,
            'unchanged_non_skirt_groups': True,
            'chains': {name: [bone.name for bone in chains[name].bone_names] for name in expected},
            'motion': motion,
        }
        write_json(EVIDENCE / 'weights-result.json', result)
        if bpy.ops.ed.undo_push.poll():
            bpy.ops.ed.undo_push(message='四节裙摆末端权重')
        print(json.dumps(result, ensure_ascii=True))
    except Exception:
        obj.data = original
        for name in reversed(created_groups):
            group = obj.vertex_groups.get(name)
            if group is not None:
                obj.vertex_groups.remove(group)
        for name, bones in previous_chains.items():
            chain = chains[name]
            chain.bone_names.clear()
            for bone in bones:
                chain.bone_names.add().name = bone
        original.use_fake_user = original_fake_user
        if replacement is not None and replacement.users == 0:
            bpy.data.meshes.remove(replacement)
        raise
    finally:
        armature.data.pose_position = entry_pose_position
        scene.frame_set(entry_frame, subframe=entry_subframe)
        for name, basis in entry_poses.items():
            armature.pose.bones[name].matrix_basis = basis
        obj.vertex_groups.active_index = original_active_group
        bpy.context.view_layer.update()
        for screen in bpy.data.screens:
            for area in screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()


apply_weights()
