#!/usr/bin/env python3
"""Read-only integrity audit for a failed V19 ZIP import.

Run against a consistent BACKUP of the project, not live mutable SQLite files:
python tools/audit_v19_partial_import.py --project-root /path/to/project-backup --job-id JOB_ID

Never modifies Material, Annotation, source files or task metadata.
A clean report is evidence for manual review, NOT authorization to train or repair.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path
from urllib.parse import quote


def _select(db_path: Path, sql: str, ids: list[str]) -> dict[str, dict]:
    if not db_path.is_file():
        return {}
    uri = 'file:' + quote(str(db_path.resolve()), safe='/') + '?mode=ro'
    rows = {}
    with sqlite3.connect(uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        for offset in range(0, len(ids), 400):
            chunk = ids[offset:offset + 400]
            if not chunk:
                continue
            placeholders = ','.join('?' for _ in chunk)
            for row in conn.execute(sql.format(placeholders=placeholders), chunk):
                rows[str(row[0])] = dict(row)
    return rows


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def audit(root: Path, job_id: str, *, verify_source_sha256: bool = True) -> dict:
    """Audit identities, projection, provenance, files and report totals.

    No repository owner is mutated; all SQLite connections open in read-only mode.
    Files outside the project root are never opened or hashed.
    """
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', job_id):
        raise ValueError('invalid job id')
    root = root.resolve()
    job_dir = root / 'import_jobs' / job_id
    job = json.loads((job_dir / 'job.json').read_text(encoding='utf-8'))
    report_path = job_dir / 'report.json'
    report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.is_file() else job.get('report') or {}
    if not isinstance(report, dict):
        raise ValueError('invalid import report')
    original_ids = [str(v) for v in report.get('imported_image_ids') or [] if str(v)]
    ids = list(dict.fromkeys(original_ids))
    material_db = root / 'materials.sqlite3'
    annotation_db = root / 'annotations.sqlite3'
    material_rows = _select(material_db,
        'SELECT id, payload_json FROM materials WHERE id IN ({placeholders})', ids)
    gt_rows = _select(annotation_db,
        'SELECT image_id, annotation_state, version, content_digest, boxes_json FROM annotations WHERE image_id IN ({placeholders})', ids)

    issues = Counter()
    examples: dict[str, list[str]] = {}
    hashes = Counter()
    gt_states = Counter()
    verified_files = 0
    verified_hashes = 0
    verified_boxes = 0
    verified_annotated = 0

    def mark(reason: str, image_id: str = '') -> None:
        issues[reason] += 1
        if image_id:
            values = examples.setdefault(reason, [])
            if len(values) < 12:
                values.append(image_id)

    if not material_db.is_file():
        mark('missing_material_database')
    if not annotation_db.is_file():
        mark('missing_annotation_database')
    if not ids:
        mark('no_report_image_ids')
    if len(ids) != len(original_ids):
        mark('duplicate_report_image_id_occurrences')
    if int(report.get('imported_images') or 0) != len(original_ids):
        mark('report_image_count_mismatch')

    for image_id in ids:
        indexed = material_rows.get(image_id)
        if indexed is None:
            mark('missing_material', image_id)
            continue
        try:
            data = json.loads(indexed['payload_json'])
            if not isinstance(data, dict):
                raise ValueError('invalid material payload')
        except (ValueError, TypeError):
            mark('invalid_material_payload', image_id)
            continue

        digest = str(data.get('content_sha256') or '').strip().lower()
        if re.fullmatch(r'[0-9a-f]{64}', digest):
            hashes[digest] += 1
        else:
            mark('missing_or_invalid_material_sha256', image_id)
        source_id = str(data.get('storage_source_id') or 'default_local')
        source_type = str(data.get('storage_type') or '').lower()
        key = str(data.get('object_key') or '')
        if source_type in {'local', 'filesystem', 'file'} and source_id == 'default_local':
            candidate = (root / key).resolve()
            if not key or not candidate.is_relative_to(root):
                mark('invalid_source_path', image_id)
            elif not candidate.is_file():
                mark('missing_local_source', image_id)
            else:
                verified_files += 1
                expected_size = int(data.get('size_bytes') or 0)
                if expected_size <= 0 or candidate.stat().st_size != expected_size:
                    mark('source_size_mismatch', image_id)
                if verify_source_sha256:
                    if not digest or _sha256_file(candidate) != digest:
                        mark('source_sha256_mismatch', image_id)
                    else:
                        verified_hashes += 1
        else:
            # An external/alternate source must be verified using its configured
            # provider, not falsely treated as a file beneath project_root.
            mark('source_requires_provider_verification', image_id)

        truth = gt_rows.get(image_id)
        if truth is None or int(truth.get('version') or 0) < 1:
            mark('missing_formal_annotation', image_id)
            continue
        state = str(truth.get('annotation_state') or '')
        gt_states[state] += 1
        if state not in {'annotated', 'confirmed_empty', 'unannotated'}:
            mark('invalid_ground_truth_state', image_id)
        try:
            boxes = json.loads(truth['boxes_json'])
            if not isinstance(boxes, list):
                raise ValueError('boxes are not a list')
        except (ValueError, TypeError):
            mark('invalid_ground_truth_boxes', image_id)
            continue
        verified_boxes += len(boxes)
        if boxes:
            verified_annotated += 1
        if state == 'annotated' and not boxes:
            mark('annotated_without_boxes', image_id)
        if state in {'confirmed_empty', 'unannotated'} and boxes:
            mark('unexpected_boxes_for_state', image_id)
        if int(data.get('box_count') or 0) != len(boxes):
            mark('annotation_projection_box_count_mismatch', image_id)
        if int(data.get('annotation_version') or 0) != int(truth.get('version') or 0):
            mark('annotation_projection_version_mismatch', image_id)
        if str(data.get('annotation_hash') or '') != str(truth.get('content_digest') or ''):
            mark('annotation_projection_digest_mismatch', image_id)
        if str(data.get('annotation_state') or '') != state:
            mark('annotation_projection_state_mismatch', image_id)
        if state in {'annotated', 'confirmed_empty'}:
            linked_digest = str(data.get('annotation_source_content_sha256') or '').lower()
            if digest and linked_digest != digest:
                mark('annotation_source_identity_mismatch', image_id)
        for box in boxes:
            if not isinstance(box, dict):
                mark('invalid_box_payload', image_id)
                continue
            origin_job = str(box.get('source_task_id') or box.get('import_batch_id') or '')
            if origin_job and origin_job != job_id:
                mark('foreign_annotation_lineage', image_id)
            elif state == 'annotated' and not origin_job:
                mark('missing_annotation_lineage', image_id)

    if verified_boxes != int(report.get('boxes') or 0):
        mark('report_boxes_mismatch')
    if verified_annotated != int(report.get('annotated_images') or 0):
        mark('report_annotated_images_mismatch')

    return {
        'audit_only': True, 'training_approved': False,
        'job_id': job_id, 'job_status': job.get('status'),
        'job_error': job.get('error'),
        'source_sha256_verification_requested': bool(verify_source_sha256),
        'report_imported_images': report.get('imported_images'),
        'report_annotated_images': report.get('annotated_images'),
        'report_boxes': report.get('boxes'),
        'report_image_id_count': len(original_ids),
        'unique_report_image_ids': len(ids),
        'duplicate_report_image_ids': len(original_ids) - len(ids),
        'indexed_material_rows': len(material_rows),
        'persisted_annotation_rows': len(gt_rows),
        'ground_truth_states': dict(gt_states),
        'verified_ground_truth_boxes': verified_boxes,
        'verified_annotated_images': verified_annotated,
        'verified_default_local_source_files': verified_files,
        'verified_source_sha256_matches': verified_hashes,
        'duplicate_content_hash_groups': sum(count > 1 for count in hashes.values()),
        'issues': dict(issues),
        'examples_first_12': examples,
        'note': 'Read-only audit on a consistent backup; no repairs or training approval. '
                'Remote/alternate storage providers require separate verification.',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, required=True)
    parser.add_argument('--job-id', required=True)
    parser.add_argument('--skip-source-hash', action='store_true',
                        help='Only check local file existence and size; never count this as full integrity verification')
    args = parser.parse_args()
    print(json.dumps(audit(args.project_root, args.job_id,
                           verify_source_sha256=not args.skip_source_hash),
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
