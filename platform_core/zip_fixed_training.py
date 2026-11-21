"""Confirmed ZIP source evidence for the existing fixed training selection owner."""
from collections import Counter
from contextlib import closing
from pathlib import PurePosixPath
import json
import re

from .storage.zip_folders import digest
from .training_splits import SplitMode, SplitRequest, _component_keys

MODE = SplitMode.FIXED_ZIP_TRAIN_VAL_TEST.value
ROLES = ('train', 'validation', 'test')
_USAGE = {'train': 'train', 'val': 'validation', 'test': 'test', 'unassigned': 'unassigned'}
_SHA = re.compile(r'[0-9a-f]{64}')
_JOB = re.compile(r'[A-Za-z0-9_-]{1,128}')


def job_ids(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 50 or any(not isinstance(i, str) or not _JOB.fullmatch(i) for i in value):
        raise ValueError('请选择 1 至 50 个 ZIP 来源')
    return sorted(set(value))


def source_identity(row):
    source = row.get('zip_folder_source') or {}
    if not isinstance(source, dict):
        raise ValueError('ZIP 来源证据无效')
    job = str(source.get('job_id') or '')
    path = PurePosixPath(str(source.get('source_path') or ''))
    hashes = [source.get(key) for key in ('source_zip_sha256', 'source_scan_digest', 'rule_digest')]
    if (not _JOB.fullmatch(job) or row.get('import_batch_id') != job or row.get('source_task_id') != job
            or not path.name or path.is_absolute() or '..' in path.parts or '\\' in str(path)
            or path.as_posix() != source.get('source_path')
            or str(path.parent) != source.get('folder_key') or source.get('usage_intent') not in _USAGE
            or any(not _SHA.fullmatch(str(value or '')) for value in hashes)
            or row.get('deleted_at') or row.get('deletion_pending') or row.get('source_available') is False
            or not _SHA.fullmatch(str(row.get('content_sha256') or '').lower())):
        raise ValueError(f"素材 {row.get('id')} 缺少可信 ZIP 来源或内容身份")
    return source


def source_proof(rows, split):
    roles = {identity: role for role in ROLES for identity in getattr(split, role + '_image_ids')}
    facts, jobs = [], {}
    for row in rows:
        source = source_identity(row)
        job = source['job_id']
        role = roles.get(row['id'])
        if role != _USAGE[source['usage_intent']] or source.get('classification_status') != 'applied':
            raise ValueError(f"素材 {row['id']} 的 ZIP 用途或归集证据已变化")
        identity = {key: source[key] for key in ('source_zip_sha256', 'source_scan_digest', 'rule_digest')}
        if jobs.setdefault(job, identity) != identity:
            raise ValueError('同一 ZIP 任务的来源摘要不一致')
        facts.append([row['id'], role, row['content_sha256'], source])
    if len(facts) != len(roles):
        raise ValueError('固定 ZIP 素材缺失')
    return {'jobs': jobs, 'source_digest': digest(sorted(facts, key=lambda fact: fact[0]))}


def current_source_proof(materials, split):
    ids = split.image_ids
    rows = [row for offset in range(0, len(ids), 500) for row in materials.get_many(ids[offset:offset + 500])]
    return source_proof(rows, split)


def sources_page(materials, offset, limit):
    with closing(materials._connect()) as db:
        rows = db.execute("""SELECT json_extract(payload_json,'$.import_batch_id') AS job, COUNT(*) AS count
            FROM materials WHERE json_extract(payload_json,'$.import_batch_id') IS NOT NULL
                AND json_extract(payload_json,'$.zip_folder_source.job_id') = json_extract(payload_json,'$.import_batch_id')
            GROUP BY job ORDER BY MIN(created_at) DESC, job LIMIT ? OFFSET ?""", (limit+1,offset)).fetchall()
    return {'items': [{'job_id': row['job'], 'image_count': row['count']} for row in rows[:limit]],
            'next_offset': offset + limit if len(rows) > limit else None}


def preview(materials, payload, contract):
    from .training_label_tasks import training_material_role, task_negative_confirmable, task_partial_scope_confirmable
    from .training_compatibility import _issue_for_row
    from .training_tasks import _selected_project_images
    from .training_selection_reference import MAX_FROZEN_SELECTION_IDS

    requested = job_ids(payload.get('zip_source_job_ids'))
    with closing(materials._connect()) as db:
        found = db.execute("""SELECT id FROM materials WHERE json_extract(payload_json,'$.import_batch_id')
            IN (SELECT value FROM json_each(?)) ORDER BY id LIMIT ?""", (json.dumps(requested), MAX_FROZEN_SELECTION_IDS+1)).fetchall()
    if len(found) > MAX_FROZEN_SELECTION_IDS:
        raise ValueError('固定 ZIP 选择超过服务端引用上限')
    rows = _selected_project_images(materials, materials.project_path, [row['id'] for row in found]) if found else []
    grouped = {role: [] for role in ROLES}
    counts = {role: Counter() for role in ROLES}
    eval_contract = {**contract, 'task_negative_confirmations': []}
    problems = []
    issue_count = 0
    unassigned = 0
    seen = set()
    train_codes = set()
    def blocked(message):
        nonlocal issue_count
        issue_count += 1
        if len(problems) < 10:
            problems.append(str(message))
    for row in rows:
        try:
            source = source_identity(row)
        except ValueError as error:
            blocked(error)
            continue
        seen.add(source['job_id'])
        role = _USAGE[source['usage_intent']]
        if role == 'unassigned':
            unassigned += 1
            continue
        grouped[role].append(row)
        if source.get('classification_status') != 'applied':
            counts[role]['ineligible'] += 1
            blocked(f"{role}: {row['id']} 归集尚未完成")
            continue
        role_contract = contract if role == 'train' else eval_contract
        kind = training_material_role(row, role_contract)['role']
        issue = _issue_for_row(row, role_contract, {})
        if not issue and kind in ('positive','confirmed_negative'):
            counts[role][kind] += 1
            if role == 'train' and kind == 'positive':
                train_codes.update(str(box.get('label') or box.get('code') or '') for box in row.get('boxes', []))
        elif (role == 'train' and (issue or {}).get('issue_type') in {'missing_annotation', 'partial_review_scope'}
              and payload.get('review_all_training_backgrounds') is True
              and (task_negative_confirmable(row, contract) or task_partial_scope_confirmable(row, contract))):
            counts[role]['pending_confirmation'] += 1
            train_codes.update(str(box.get('label') or box.get('code') or '') for box in row.get('boxes', []))
        else:
            counts[role]['ineligible'] += 1
            blocked(f"{role}: {row['id']} 缺少当前目标的正式标注或有效确认")
    if set(requested) != seen:
        blocked('包含不存在、未归集或属于其他项目的 ZIP 来源')
    for role in ROLES:
        if not grouped[role]:
            blocked(f'{role} 集为空')
    missing_codes = set(contract.get('requested_new_label_codes') or ()) - train_codes
    if missing_codes:
        blocked('固定 Train 缺少目标正样本：' + '、'.join(sorted(missing_codes)[:20]))
    if not counts['train']['positive'] and not contract.get('base_version_id'):
        blocked('首次训练的 Train 集必须有正样本')
    proof, split = None, None
    conflict_count = 0
    known = [row for group in grouped.values() for row in group]
    keys = _component_keys(known)
    components = {}
    same_role_hashes = {}
    for role, group in grouped.items():
        for row in group:
            components.setdefault(keys[row['id']], {}).setdefault(role, row['id'])
            identity = (role, row['content_sha256'].lower())
            ids = same_role_hashes.setdefault(identity, [])
            if len(ids) < 2:
                ids.append(row['id'])
    for members in components.values():
        if len(members) > 1:
            conflict_count += 1
            blocked('来源、派生关系或内容跨组冲突：' + '、'.join(f'{role} {identity}' for role, identity in members.items()))
    for (role, _), ids in same_role_hashes.items():
        if len(ids) > 1:
            conflict_count += 1
            blocked(f'{role} 内相同内容：' + '、'.join(ids))
    if not issue_count:
        by_role = {role + '_image_ids': tuple(row['id'] for row in group) for role, group in grouped.items()}
        split = SplitRequest(SplitMode.FIXED_ZIP_TRAIN_VAL_TEST, **by_role, validation_percent=None)
        proof = source_proof(known, split)
    return {'roles': {role: {'total': len(grouped[role]), **dict(counts[role])} for role in ROLES},
            'unassigned': unassigned, 'issue_count': issue_count, 'conflict_count': conflict_count,
            'problems': problems}, split, proof


def reference_scope(payload):
    source_digest = payload.get('zip_selection_digest')
    if not isinstance(source_digest, str) or not _SHA.fullmatch(source_digest):
        raise ValueError('固定 ZIP 选择缺少来源摘要')
    return {'sample_role': MODE, 'job_ids': job_ids(payload.get('zip_source_job_ids')),
            'source_digest': source_digest, 'model': str(payload.get('model') or ''),
            'review_all_training_backgrounds': payload.get('review_all_training_backgrounds') is True}
