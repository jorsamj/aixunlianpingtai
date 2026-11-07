"""Opt-in real SQLite metadata benchmark; synthetic indexes, no production IO."""
import json
import os
import platform
import statistics
import time

import pytest

from platform_core.material_repository import MaterialRepository


@pytest.mark.scale
@pytest.mark.skipif(os.environ.get('RUN_WORKBENCH_SCALE') != '1', reason='explicit isolated scale run')
def test_workbench_metadata_milestones(tmp_path):
    repo = MaterialRepository(tmp_path / 'isolated-project')
    milestones = {1000, 10000, 50000, 100000, 200000}
    report = {'fixture_only': True, 'storage': 'local SQLite, no image bytes',
              'platform': platform.platform(), 'python': platform.python_version(), 'results': []}
    for start in range(0, 200000, 1000):
        repo.upsert_many([{'id': f'm{i:07}', 'filename': f'camera-{i:07}.jpg',
                          'object_key': f'{i}.jpg', 'content_sha256': f'{i+1:064x}',
                          'processing_status': 'processed',
                          'storage_source_id': 'local-a' if i % 2 else 'local-b',
                          'labels': ['fire'] if i % 3 else ['smoke'],
                          'created_at': '2026-11-04T00:00:00+00:00'}
                         for i in range(start, start + 1000)])
        size = start + 1000
        if size not in milestones:
            continue
        for name, kwargs in [('first', {}), ('deep', {'page': max(1, size // 48 - 1)}),
                             ('source_label', {'storage_source_ids': ['local-a'], 'labels': ['fire']}),
                             ('filename', {'query': 'camera-000'})]:
            values = []
            for _ in range(21):
                began = time.perf_counter()
                page = repo.list_page(limit=48, **kwargs)
                values.append((time.perf_counter() - began) * 1000)
                assert len(page.items) <= 48
            report['results'].append({'rows': size, 'query': name, 'samples': len(values),
                                      'first_query_ms': round(values[0], 3),
                                      'p50_ms': round(statistics.median(values), 3),
                                      'p95_ms': round(sorted(values)[19], 3)})
    output = os.environ.get('WORKBENCH_SCALE_REPORT')
    if output:
        from pathlib import Path
        Path(output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
