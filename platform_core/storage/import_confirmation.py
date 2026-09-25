"""Resolve external names explicitly before freezing a durable import decision."""
from __future__ import annotations

import hashlib
import json

def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode('utf-8')).hexdigest()


def external_label_facts(classes):
    """Return source-side facts only; never expose a canonical target decision."""
    allowed = ("class_id", "name", "image_count", "box_count")
    return [
        {key: item.get(key) for key in allowed if key in item}
        for item in classes
        if isinstance(item, dict)
    ]


IMPORT_LABEL_CREATION_BLOCKED_DETAIL = (
    '导入确认不能根据外部标签名隐式创建平台标签；'
    '请先显式创建正式平台标签（可在当前确认弹窗点击“＋ 新建平台标签”），'
    '再将外部类别映射到该标签'
)


def resolve_external_label_mapping(classes, *, label_mapping=None, create_labels=None, labels):
    mapping = dict(label_mapping or {})
    create = sorted(set(create_labels or []))
    if create:
        raise ValueError(IMPORT_LABEL_CREATION_BLOCKED_DETAIL)
    active = {
        str(label['code']): label
        for label in labels
        if label.get('status', 'active') == 'active'
    }
    resolved = {}
    for item in classes:
        external_id, name = str(item['class_id']), item['name']
        by_name, by_id = mapping.get(name), mapping.get(external_id)
        if by_name and by_id and by_name != by_id:
            raise ValueError(f'conflicting mapping for external class {external_id}')
        code = by_name or by_id
        if not code or code not in active:
            raise ValueError(
                f'外部类别 {external_id} 未映射到当前有效标签；'
                '目标标签必须来自当前有效标签库'
            )
        if sum(
            1 for label in labels
            if label.get('code') == code and label.get('status', 'active') == 'active'
        ) > 1:
            raise ValueError(f'ambiguous platform label for external class {external_id}')
        resolved[external_id] = code
    return resolved, []


def confirm_import(store, artifacts, task_id, *, object_keys=None, label_mapping=None,
                   create_labels=None, accept_quality_report=False, labels, create_label=None):
    mapping = dict(label_mapping or {})
    create = sorted(set(create_labels or []))
    if create:
        raise ValueError(IMPORT_LABEL_CREATION_BLOCKED_DETAIL)
    facts = store.selection_facts(object_keys)
    previous = artifacts.read_json(task_id, 'scan/confirmation.json', default=None)

    # Historical confirmations may record create_labels from the retired flow.
    # Replay is allowed only when every frozen target now exists and is active;
    # no retry may create or reactivate a platform label.
    if isinstance(previous, dict) and previous.get('create_labels'):
        previous_mapping = dict(previous.get('label_mapping') or {})
        resolved, _ = resolve_external_label_mapping(
            facts['classes'],
            label_mapping=previous_mapping,
            create_labels=[],
            labels=labels,
        )
        if mapping and mapping != previous_mapping:
            raise ValueError('conflicting import confirmation')
        if resolved != previous_mapping:
            raise ValueError('conflicting import confirmation')
        return previous

    resolved, _ = resolve_external_label_mapping(
        facts['classes'],
        label_mapping=mapping,
        create_labels=[],
        labels=labels,
    )
    request_digest = _digest({'label_mapping': mapping, 'create_labels': [],
                              'accept_quality_report': accept_quality_report,
                              'content_digest': facts['content_digest']})
    if isinstance(previous, dict):
        if not previous.get('request_digest') and not facts['classes'] and not mapping and not accept_quality_report:
            keys = object_keys if object_keys is not None else (r['object_key'] for r in store.iter_status('IMPORTABLE'))
            store.confirm(keys)
            return previous
        if previous.get('request_digest') != request_digest:
            raise ValueError('conflicting import confirmation')
        return previous
    quality = store.quality_summary()
    if quality['issues'] and not accept_quality_report:
        raise ValueError('Please accept the data quality report before importing')
    details = {'request_digest': request_digest, 'content_digest': facts['content_digest'],
               'label_mapping': resolved, 'create_labels': [],
               'external_classes': [
                   {'class_id': str(row.get('class_id')), 'name': str(row.get('name') or '')}
                   for row in facts['classes']
               ],
               'accept_quality_report': bool(accept_quality_report)}
    keys = object_keys if object_keys is not None else (r['object_key'] for r in store.iter_status('IMPORTABLE'))
    selection = store.confirm(keys, details=details)
    confirmation = {**details, 'accepted': True, 'selection_digest': selection.digest,
                    'selected_count': selection.selected_count, 'confirmed_at': selection.confirmed_at}
    artifacts.atomic_write_json(task_id, 'scan/confirmation.json', confirmation)
    return confirmation

def public_quality(value, sanitize):
    """Whitelist bounded quality examples and external class facts."""
    result = {}
    quality = value.get('quality')
    if isinstance(quality, dict):
        result['quality'] = {key: max(0, int(quality.get(key) or 0)) for key in ('images', 'boxes', 'classes')}
        for key in ('annotation_status', 'issues'):
            result['quality'][key] = {sanitize(str(k)): max(0, int(v)) for k, v in list((quality.get(key) or {}).items())[:100] if isinstance(v, (int, float))}
        result['quality']['examples'] = [{key: sanitize(str(row[key])) if key != 'line_number' else max(0, int(row[key]))
            for key in ('object_key', 'line_number', 'code', 'severity') if key in row}
            for row in (quality.get('examples') or [])[:100] if isinstance(row, dict)]
    result['external_classes'] = [{key: sanitize(str(row[key])) if row[key] is not None else None
        for key in ('class_id', 'name') if key in row}
        for row in (value.get('external_classes') or [])[:10000] if isinstance(row, dict)]
    return result
