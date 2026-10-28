"""Opt-in isolated picker microbenchmark: pytest -s ... (no production services)."""
import json
import time
import pytest
from platform_core.material_repository import MaterialRepository
from platform_core.annotation_repository import AnnotationRepository
from platform_core.training_material_picker_api import _role_material_page, _cached_role_index

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
