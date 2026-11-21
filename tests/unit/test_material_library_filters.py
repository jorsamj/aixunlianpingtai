from contextlib import closing
import pytest
from platform_core.material_repository import MaterialRepository
from platform_core.material_selection import MaterialFilters


def test_library_filters_share_page_count_and_ids_without_rewriting_facts(tmp_path):
    repo=MaterialRepository(tmp_path)
    repo.upsert_many([
        {'id':'raw','filename':'raw.jpg','import_batch_id':'abc1234567','processing_status':'pending_decision','annotation_state':'unannotated','created_at':'2026-11-06T10:00:00+08:00'},
        {'id':'gt','filename':'gt.jpg','import_batch_id':'abc1234567','processing_status':'processed','annotation_state':'annotated','annotated':True,'labels':['fire'],'box_count':1,'created_at':'2026-11-06T11:00:00+08:00'},
        {'id':'review','filename':'review.jpg','import_batch_id':'different','processing_status':'processed','annotation_needs_review':True,'quality_status':'issue','created_at':'2026-11-05T10:00:00+08:00'},
    ])
    revision=repo.current_revision()
    f={'source_batch_id':'abc1234567','created_from':'2026-11-06','created_to':'2026-11-06','quality_status':'pending_decision','annotation_state':'unannotated'}
    assert [r['id'] for r in repo.list_page(**f).items]==['raw']
    assert repo.count_filtered(f)==1
    assert repo.iter_filtered_ids(f,limit=48).items==['raw']
    assert repo.list_page(annotation_state='needs_review').items[0]['id']=='review'
    assert repo.list_page(quality_status='issue').items[0]['id']=='review'
    assert repo.get('raw')['processing_status']=='pending_decision'
    assert not repo.get('raw').get('clean_skipped')
    assert repo.current_revision()==revision
    with closing(repo._connect()) as db:
        plan=' '.join(str(row[3]) for row in db.execute("EXPLAIN QUERY PLAN SELECT id FROM materials m WHERE json_extract(m.payload_json,'$.import_batch_id')=? ORDER BY created_at,id",('abc1234567',)))
        assert 'ix_materials_import_batch' in plan and 'SEARCH' in plan


@pytest.mark.parametrize('values',[{'created_from':'invalid'},{'created_from':'2026-11-07','created_to':'2026-11-06'},{'quality_status':'fabricated'}])
def test_library_rejects_invalid_filters(values):
    with pytest.raises(ValueError):MaterialFilters(**values)


def test_existing_schema6_adds_batch_index_without_data_rewrite(tmp_path):
    repo=MaterialRepository(tmp_path)
    repo.upsert({'id':'keep','filename':'keep.jpg','processing_status':'pending_decision'})
    revision=repo.current_revision()
    with closing(repo._connect()) as db:
        db.execute('DROP INDEX ix_materials_import_batch'); db.commit()
    # Simulate a fresh process opening an old schema6 database. The existing
    # per-process initialization cache intentionally ignores external DDL edits.
    from platform_core.material_repository_batch import _MATERIAL_INIT_READY
    _MATERIAL_INIT_READY.discard(repo.path.resolve())
    restored=MaterialRepository(tmp_path)
    with closing(restored._connect()) as db:
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name='ix_materials_import_batch'").fetchone()
        assert db.execute('PRAGMA user_version').fetchone()[0]==6
    assert restored.get('keep')['processing_status']=='pending_decision'
    assert restored.current_revision()==revision
