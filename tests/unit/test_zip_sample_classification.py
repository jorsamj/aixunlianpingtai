"""v19 scan confirmation freezes upload kind independently from formal GT."""
import copy
import threading

import pytest

from tests.unit.test_negative_pool import setup


def test_new_classless_zip_waits_for_kind_and_freezes_negative_category(tmp_path, monkeypatch):
    import app as api

    repository, pool = setup(tmp_path)
    category = pool.category(name='背光')
    project = {'labels': ['fire', 'retired'], 'label_meta': [{}, {'status': 'disabled'}]}
    job = {'id': 'zip-1', 'dataset_id': 'default', 'status': 'selecting',
           'external_classes': [], 'sample_classification_required': True, 'image_count': 1}
    monkeypatch.setattr(api, 'get_project', lambda _: project)
    monkeypatch.setattr(api, 'material_store', lambda _: repository)
    monkeypatch.setattr(api, 'v19_read_job', lambda *_: copy.deepcopy(job))
    monkeypatch.setattr(api, 'v19_write_job', lambda _, updated, **__: job.update(copy.deepcopy(updated)))
    monkeypatch.setattr(api, 'v19_public_job', lambda _, updated: dict(updated))
    monkeypatch.setattr(api, 'v19_import_jobs_dir', lambda _: tmp_path)
    monkeypatch.setattr(api, 'v19_read_import_report', lambda *_: {'imported_image_ids': []})
    monkeypatch.setattr(threading.Thread, 'start', lambda _: None)

    def start(**body):
        return api._v19_start_import_job_locked('test', 'zip-1', api.V19ImportStartReq(**body))

    with pytest.raises(api.HTTPException) as unclassified:
        start()
    assert unclassified.value.status_code == 422
    with pytest.raises(api.HTTPException) as inactive:
        start(sample_type='positive', intended_label_codes=['retired'])
    assert inactive.value.status_code == 422
    with pytest.raises(api.HTTPException) as absent_category:
        start(sample_type='negative', negative_category_ids=['not-a-category'])
    assert absent_category.value.status_code == 422

    started = start(sample_type='negative', negative_category_ids=[category['id']])
    assert started['upload_sample_type'] == 'negative'
    assert started['upload_negative_category_ids'] == [category['id']]
    assert started['upload_intended_label_codes'] == []
    assert started['status'] == 'running'
    assert pool.query()['total'] == 0, 'scan confirmation must not tag any image before formal import'

    job['status'] = 'failed'
    with pytest.raises(api.HTTPException) as changed:
        start(sample_type='positive', intended_label_codes=['fire'])
    assert changed.value.status_code == 409
