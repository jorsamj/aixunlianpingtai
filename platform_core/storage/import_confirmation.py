"""Resolve external names explicitly before freezing a durable import decision."""
from __future__ import annotations

import hashlib
import json
import re
import uuid


_GENERIC_EXTERNAL_NAMES = {'object', 'target'}
_LABEL_CODE = re.compile(r'^[A-Za-z][A-Za-z0-9_-]{0,63}$')


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode('utf-8')).hexdigest()


def mapping_suggestions(classes, labels):
    active = [label for label in labels if label.get('status', 'active') == 'active']
    result = []
    for item in classes:
        external_name = str(item.get('name') or '').strip()
        lowered = external_name.casefold()
        generic = lowered in _GENERIC_EXTERNAL_NAMES or bool(re.fullmatch(r'class[_ -]?\d+', lowered))
        matches = [] if generic else [label for label in active if lowered in {
            str(label.get('code') or '').casefold(),
            str(label.get('display_name') or '').casefold(),
            *(str(alias).casefold() for alias in (
                label.get('aliases') if isinstance(label.get('aliases'), (list, tuple)) else []
            ) if isinstance(alias, str)),
        }]
        unique = {str(label.get('label_id') or ''): label for label in matches
                  if str(label.get('label_id') or '')}
        suggestion = next(iter(unique.values())) if len(unique) == 1 else None
        result.append({**item,
            'suggested_target_label_id': suggestion.get('label_id') if suggestion else None,
            'target_label_code': suggestion.get('code') if suggestion else None})
    return result


def confirm_import(store, artifacts, task_id, *, object_keys=None, label_mapping=None,
                   create_labels=None, class_actions=None, accept_quality_report=False,
                   labels, create_label):
    mapping = dict(label_mapping or {})
    requested_actions = {str(key): dict(value) for key, value in (class_actions or {}).items()}
    create = sorted(set(create_labels or []))
    if any(not isinstance(code, str) or not code.strip() or code != code.strip() for code in create):
        raise ValueError('create_labels must contain nonempty platform label codes')
    facts = store.selection_facts(object_keys)
    request_digest = _digest({'label_mapping': mapping, 'create_labels': create,
                              'class_actions': requested_actions,
                              'accept_quality_report': accept_quality_report,
                              'content_digest': facts['content_digest']})
    previous = artifacts.read_json(task_id, 'scan/confirmation.json', default=None)
    if isinstance(previous, dict):
        if not previous.get('request_digest') and not facts['classes'] and not mapping and not create and not accept_quality_report:
            keys = object_keys if object_keys is not None else (r['object_key'] for r in store.iter_status('IMPORTABLE'))
            store.confirm(keys)
            return previous
        if previous.get('request_digest') != request_digest:
            raise ValueError('conflicting import confirmation')
        return previous
    quality = store.quality_summary()
    if quality['issues'] and not accept_quality_report:
        raise ValueError('Please accept the data quality report before importing')
    active = {str(label['code']): label for label in labels if label.get('status', 'active') == 'active'}
    active_by_id = {str(label.get('label_id')): label for label in active.values()
                    if label.get('label_id')}
    all_codes = {str(label['code']) for label in labels}
    if any(code in all_codes and code not in active for code in create):
        raise ValueError('cannot recreate an inactive platform label')
    resolved, decisions, create_specs = {}, {}, []
    for item in facts['classes']:
        external_id, name = str(item['class_id']), item['name']
        by_name, by_id = mapping.get(name), mapping.get(external_id)
        if by_name and by_id and by_name != by_id:
            raise ValueError(f'conflicting mapping for external class {external_id}')
        action = requested_actions.get(external_id) or requested_actions.get(str(name))
        legacy_code = by_name or by_id
        if action and legacy_code:
            raise ValueError(f'conflicting confirmation formats for external class {external_id}')
        if not action and legacy_code:
            action = {'action': 'create' if legacy_code in create else 'map', 'code': legacy_code}
        if not action:
            raise ValueError(f'unresolved external class {external_id}: choose map, create, preserve or ignore')
        kind = str(action.get('action') or '')
        if kind == 'ignore':
            decisions[external_id] = {'action': 'ignore', 'target_label_id': None,
                                      'target_label_code': None}
            resolved[external_id] = None
            continue
        if kind == 'map':
            target = active_by_id.get(str(action.get('target_label_id') or ''))
            if target is None and action.get('code'):
                target = active.get(str(action['code']))
            if target is None:
                raise ValueError(f'external class {external_id} must map to an active stable label_id')
            target_id, code = str(target['label_id']), str(target['code'])
        elif kind in {'create', 'preserve'}:
            code = str(action.get('code') or (name if kind == 'preserve' else '')).strip().replace(' ', '_')
            display_name = str(action.get('display_name') or (name if kind == 'preserve' else code)).strip()
            if kind == 'create' and not _LABEL_CODE.fullmatch(code):
                raise ValueError(f'new label code for external class {external_id} must be English letters, digits, _ or -')
            if not code or not display_name:
                raise ValueError(f'new label for external class {external_id} requires code and display_name')
            target_id = 'lbl_' + uuid.uuid5(uuid.NAMESPACE_URL,
                f'material-import:{task_id}:{external_id}:{code}').hex
            existing = active.get(code)
            if existing and str(existing.get('label_id')) != target_id:
                raise ValueError(f'platform label code already exists: {code}')
            create_specs.append({'label_id': target_id, 'code': code,
                                 'display_name': display_name, 'provenance': kind})
        else:
            raise ValueError(f'unsupported action for external class {external_id}')
        resolved[external_id] = target_id
        decisions[external_id] = {'action': kind, 'target_label_id': target_id,
                                  'target_label_code': code}
    created_codes = [spec['code'] for spec in create_specs]
    if len(created_codes) != len(set(created_codes)):
        raise ValueError('multiple external classes cannot create the same platform label code')
    # Frozen in the manifest transaction together with selection. A crash before
    # JSON publication can retry label creation and publish the same decision.
    label_snapshot = {}
    for label in labels:
        snapshot = {key: label.get(key) for key in ('label_id', 'code', 'display_name', 'status')}
        label_snapshot[str(snapshot.get('label_id') or '')] = snapshot
    for spec in create_specs:
        snapshot = {key: spec.get(key) for key in ('label_id', 'code', 'display_name')}
        snapshot['status'] = 'active'
        label_snapshot[str(snapshot['label_id'])] = snapshot
    details = {'request_digest': request_digest, 'content_digest': facts['content_digest'],
               'import_id': store.import_id or task_id, 'label_mapping': resolved,
               'class_actions': decisions, 'create_labels': create_specs,
               'label_snapshot': list(label_snapshot.values()),
               'provenance': {'task_id': task_id, 'source': 'user_confirmation'},
               'accept_quality_report': bool(accept_quality_report)}
    keys = object_keys if object_keys is not None else (r['object_key'] for r in store.iter_status('IMPORTABLE'))
    selection = store.confirm(keys, details=details)
    store.save_label_decisions(decisions)
    for spec in create_specs:
        created = create_label(spec)
        if str(created.get('label_id')) != spec['label_id']:
            raise ValueError('created platform label differs from confirmed stable label_id')
    confirmation = {**details, 'accepted': True, 'selection_digest': selection.digest,
                    'selected_count': selection.selected_count, 'confirmed_at': selection.confirmed_at}
    artifacts.atomic_write_json(task_id, 'scan/confirmation.json', confirmation)
    return confirmation


def public_quality(value, sanitize):
    """Whitelist bounded examples/class suggestions without exposing provider data."""
    result = {}
    quality = value.get('quality')
    if isinstance(quality, dict):
        result['quality'] = {key: max(0, int(quality.get(key) or 0)) for key in ('images', 'boxes', 'classes')}
        for key in ('annotation_status', 'issues'):
            result['quality'][key] = {sanitize(str(k)): max(0, int(v)) for k, v in list((quality.get(key) or {}).items())[:100] if isinstance(v, (int, float))}
        result['quality']['examples'] = [{key: sanitize(str(row[key])) if key != 'line_number' else max(0, int(row[key]))
            for key in ('object_key', 'line_number', 'code', 'severity') if key in row}
            for row in (quality.get('examples') or [])[:100] if isinstance(row, dict)]
    result['external_classes'] = [{key: (
            max(0, int(row[key])) if key in ('image_count', 'box_count') else
            sanitize(str(row[key])) if row[key] is not None else None)
        for key in ('import_id', 'class_id', 'name', 'image_count', 'box_count',
                    'suggested_target_label_id', 'target_label_code') if key in row}
        for row in (value.get('external_classes') or [])[:10000] if isinstance(row, dict)]
    return result
