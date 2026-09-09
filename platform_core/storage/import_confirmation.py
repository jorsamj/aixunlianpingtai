"""Resolve external names explicitly before freezing a durable import decision."""
from __future__ import annotations

import hashlib
import json


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode('utf-8')).hexdigest()


def mapping_suggestions(classes, labels):
    active = [label for label in labels if label.get('status', 'active') == 'active']
    result = []
    for item in classes:
        matches = {str(label['code']) for label in active
                   if item['name'] in {label.get('code'), label.get('display_name')}}
        result.append({**item, 'target_label_code': next(iter(matches)) if len(matches) == 1 else None})
    return result


def confirm_import(store, artifacts, task_id, *, object_keys=None, label_mapping=None,
                   create_labels=None, accept_quality_report=False, labels, create_label):
    mapping = dict(label_mapping or {})
    create = sorted(set(create_labels or []))
    if any(not isinstance(code, str) or not code.strip() or code != code.strip() for code in create):
        raise ValueError('create_labels must contain nonempty platform label codes')
    facts = store.selection_facts(object_keys)
    request_digest = _digest({'label_mapping': mapping, 'create_labels': create,
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
    all_codes = {str(label['code']) for label in labels}
    if any(code in all_codes and code not in active for code in create):
        raise ValueError('cannot recreate an inactive platform label')
    resolved = {}
    for item in mapping_suggestions(facts['classes'], labels):
        external_id, name = str(item['class_id']), item['name']
        by_name, by_id = mapping.get(name), mapping.get(external_id)
        if by_name and by_id and by_name != by_id:
            raise ValueError(f'conflicting mapping for external class {external_id}')
        code = by_name or by_id or item['target_label_code']
        if not code or code not in active and code not in create:
            raise ValueError(f'unresolved external class {external_id}: choose an active label or explicitly create one')
        if sum(1 for label in labels if label.get('code') == code and label.get('status', 'active') == 'active') > 1:
            raise ValueError(f'ambiguous platform label for external class {external_id}')
        resolved[external_id] = code
    # Frozen in the manifest transaction together with selection. A crash before
    # JSON publication can retry label creation and publish the same decision.
    details = {'request_digest': request_digest, 'content_digest': facts['content_digest'],
               'label_mapping': resolved, 'create_labels': create,
               'accept_quality_report': bool(accept_quality_report)}
    keys = object_keys if object_keys is not None else (r['object_key'] for r in store.iter_status('IMPORTABLE'))
    selection = store.confirm(keys, details=details)
    for code in create:
        if code not in active:
            created = create_label(code)
            if created != code:
                raise ValueError('created platform label differs from confirmed label code')
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
    result['external_classes'] = [{key: sanitize(str(row[key])) if row[key] is not None else None
        for key in ('class_id', 'name', 'target_label_code') if key in row}
        for row in (value.get('external_classes') or [])[:10000] if isinstance(row, dict)]
    return result
