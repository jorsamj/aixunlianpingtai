"""Opt-in isolated picker microbenchmark: pytest -s ... (no production services)."""
import json
import sqlite3
import time
import pytest
from platform_core.material_repository import MaterialRepository
from platform_core.annotation_repository import AnnotationRepository
from platform_core.training_material_picker_api import _role_material_page, _cached_role_index, _gt_material_filter_page, _validated_positive_training_label_codes
import platform_core.training_material_picker_api as picker_module

@pytest.mark.parametrize('size',[100,1000,10000,50000])
def test_picker_role_index_microbenchmark(tmp_path,size):
    repo=MaterialRepository(tmp_path / 'project')
    repo.upsert_many([{'id':f'i{i:06d}','filename':f'{i}.jpg','processing_status':'processed',
                      'created_at':'2026-10-28T00:00:00+00:00','storage_source_id':'default_local',
                      'object_key':f'{i}.jpg'} for i in range(size)])
    gt=AnnotationRepository(repo.project_path)
    contract={'effective_label_codes':['person']}
    _cached_role_index.cache_clear()
    started=time.perf_counter()
    first=_role_material_page(repo,gt,contract,limit=60)
    first_ms=(time.perf_counter()-started)*1000
    started=time.perf_counter()
    second=_role_material_page(repo,gt,contract,page=2 if size>60 else 1,limit=60)
    cached_ms=(time.perf_counter()-started)*1000
    started=time.perf_counter()
    bulk=_role_material_page(repo,gt,contract,limit=50000,include_payload=False)
    bulk_ms=(time.perf_counter()-started)*1000
    assert first['total']==second['total']==bulk['total']==size
    assert len(first['items'])==min(60,size)
    assert len(bulk['items'])==size
    assert _cached_role_index.cache_info().misses==1
    assert _cached_role_index.cache_info().hits==2
    assert all(set(row)=={'id','sample_role'} for row in bulk['items'])
    print(json.dumps({'rows':size,'cold_ms':round(first_ms,2),'cached_page_ms':round(cached_ms,2),'bulk_ids_ms':round(bulk_ms,2)}))


def test_twelve_thousand_materials_formal_gt_multi_label_and_deep_page_contract(tmp_path, monkeypatch):
    """Real indexed SQLite, synthetic identities: no production data or model run."""
    repo = MaterialRepository(tmp_path/'p0_scale')
    annotations = AnnotationRepository(repo.project_path)
    total = 12_000
    batch = 400
    for offset in range(0,total,batch):
        materials = []
        ground_truth = []
        for index in range(offset,min(offset+batch,total)):
            image_id=f'img-{index:06d}'
            labels=['smoke','fire'] if index%5==0 else ['smoke'] if index%2==0 else ['person']
            materials.append({'id':image_id, 'filename':f'camera-{index:06d}.jpg',
                'storage_source_id':'remote-a' if index%3 else 'remote-b',
                'processing_status':'processed' if index%7 else 'pending_decision',
                'labels':labels, 'created_at':f'2026-10-28T00:00:{index//1000:02d}.{index:06d}+00:00',
                'object_key':f'{index}.jpg', 'content_sha256':f'{index+1:064x}', 'width':800,'height':800})
            if index%11==0:
                ground_truth.append({'image_id':image_id, 'annotation_state':'confirmed_empty',
                                     'annotation_scope':['smoke','fire'], 'boxes':[]})
            else:
                ground_truth.append({'image_id':image_id, 'annotation_state':'annotated',
                    'annotation_scope':['smoke','fire','person'],
                    'boxes':[{'label':label,'x1':20,'y1':30,'x2':200,'y2':300} for label in labels]})
        repo.upsert_many(materials)
        annotations.upsert_many(ground_truth)

    # Material list uses OR across supplied labels, still applies source/status and deep offset.
    selected = repo.list_page(page=65,limit=50,labels=('smoke','fire'),
                              storage_source_ids=('remote-a',),processing_status='processed')
    # Material index includes only source/status-qualified labels; compare to
    # authoritative indexed SQL, never infer truth from synthetic input alone.
    with sqlite3.connect(repo.path) as db:
        reference_total = db.execute(
            "SELECT COUNT(*) FROM materials m WHERE m.processing_status='processed' "
            "AND m.storage_source_id='remote-a' AND EXISTS "
            "(SELECT 1 FROM material_labels l WHERE l.material_id=m.id "
            "AND l.label_code IN ('smoke','fire'))"
        ).fetchone()[0]
        reference = db.execute(
            "SELECT m.id FROM materials m WHERE m.processing_status='processed' "
            "AND m.storage_source_id='remote-a' AND EXISTS "
            "(SELECT 1 FROM material_labels l WHERE l.material_id=m.id "
            "AND l.label_code IN ('smoke','fire')) "
            "ORDER BY m.created_at,m.id LIMIT 50 OFFSET 3200"
        ).fetchall()
    assert 3000 < selected.total == reference_total < total
    assert [r['id'] for r in selected.items] == [r[0] for r in reference]

    # Formal GT labels must come from AnnotationRepository, excluding unprocessed rows.
    statements = []
    original_connect = picker_module.connect_sqlite
    def tracked_connect(*args, **kwargs):
        db = original_connect(*args, **kwargs)
        if str(args[0]) == str(repo.path):
            db.set_trace_callback(statements.append)
        return db
    monkeypatch.setattr(picker_module,'connect_sqlite',tracked_connect)
    began = time.perf_counter()
    filtered = _gt_material_filter_page(repo,annotations,limit=60,page=80,
                                        labels=('smoke','fire'),include_payload=False)
    gt_cold_ms = (time.perf_counter()-began)*1000
    expected_gt = [i for i in range(total) if i%11 and (i%2==0 or i%5==0)]
    assert filtered['total'] == len(expected_gt)
    assert filtered['items'] == [f'img-{i:06d}' for i in expected_gt[4740:4800]]
    began = time.perf_counter()
    filtered_next = _gt_material_filter_page(repo,annotations,limit=60,page=81,
                                             labels=('smoke','fire'),include_payload=False)
    gt_warm_ms = (time.perf_counter()-began)*1000
    assert filtered_next['total'] == filtered['total']
    assert len([sql for sql in statements if 'SELECT COUNT(*) FROM materials m' in sql]) == 1

    # Positive/confirmed-negative/pending role truth is not inferred from Material labels.
    _cached_role_index.cache_clear()
    began = time.perf_counter()
    roles = _role_material_page(repo,annotations,{'effective_label_codes':['smoke','fire']},
                                limit=60,include_payload=False)
    role_cold_ms = (time.perf_counter()-began)*1000
    expected_processed = total
    assert sum(roles['sample_role_counts'].values()) == expected_processed
    assert roles['sample_role_counts']['positive'] > 0
    assert roles['sample_role_counts']['confirmed_negative'] > 0
    assert all('sample_role' in row and 'id' in row for row in roles['items'])

    began = time.perf_counter()
    evidence_codes = _validated_positive_training_label_codes(
        repo, annotations, [f'img-{i:06d}' for i in range(total)], ['fire', 'smoke', 'person'])
    positive_proof_ms = (time.perf_counter()-began)*1000
    assert evidence_codes == ['fire', 'smoke', 'person']
    began = time.perf_counter()
    assert _validated_positive_training_label_codes(
        repo, annotations, [f'img-{i:06d}' for i in range(total)], ['unproven']) == []
    worst_case_proof_ms = (time.perf_counter()-began)*1000

    with sqlite3.connect(repo.path) as db:
        plan = [row[3] for row in db.execute('EXPLAIN QUERY PLAN '
            'SELECT m.id FROM materials m WHERE m.filename LIKE ? COLLATE NOCASE '
            'ORDER BY m.created_at,m.id LIMIT 60 OFFSET 9000',('%camera%',))]
    assert plan and any('SCAN' in step for step in plan)
    print(json.dumps({'materials':total,'filtered_total':selected.total,
        'formal_gt_total':filtered['total'],'roles':roles['sample_role_counts'],
        'gt_cold_ms':round(gt_cold_ms,2),'gt_warm_ms':round(gt_warm_ms,2),
        'role_cold_ms':round(role_cold_ms,2),'positive_proof_ms':round(positive_proof_ms,2),
        'worst_case_proof_ms':round(worst_case_proof_ms,2),
        'keyword_explain':plan},ensure_ascii=False))
