import app as host


def test_browse_ids_and_legacy_batch_report_agree_without_backfill(client,seeded_project,monkeypatch):
    project,image=seeded_project
    repo=host.material_store(project)
    before=repo.current_revision()
    monkeypatch.setattr(host,'v19_read_job',lambda project,job:{'id':job,'status':'done'})
    monkeypatch.setattr(host,'v19_read_import_report',lambda *args:{'imported_image_ids':[image['id']]})
    base=f'/api/v61/projects/{project}/materials'
    browse=client.get(base,params={'source_batch_id':'abc1234567','page':1,'page_size':48})
    assert browse.status_code==200,browse.text
    assert [row['id'] for row in browse.json()['items']]==[image['id']]
    ids=client.get(base+'/ids',params={'source_batch_id':'abc1234567','narrow':'true'})
    assert ids.status_code==200,ids.text
    assert ids.json()['items']==[image['id']]
    assert repo.current_revision()==before
    assert not repo.get(image['id']).get('import_batch_id')
    for endpoint in [base,base+'/ids']:
        result=client.get(endpoint,params={'created_from':'not-a-date'})
        assert result.status_code==400,result.text


def test_new_batch_uses_index_not_legacy_report(client,seeded_project,monkeypatch):
    project,image=seeded_project
    repo=host.material_store(project)
    repo.upsert({**repo.get(image['id']),'import_batch_id':'abc1234567'})
    def fail(*args):raise AssertionError('new indexed batch must not load old JSON IDs')
    monkeypatch.setattr(host,'v19_read_job',fail)
    result=client.get(f'/api/v61/projects/{project}/materials',params={'source_batch_id':'abc1234567'})
    assert result.status_code==200,result.text
    assert result.json()['total']==1

def test_legacy_visible_batch_cannot_silently_freeze_an_empty_filtered_scope(client,seeded_project,monkeypatch):
    project,image=seeded_project
    monkeypatch.setattr(host,'v19_read_job',lambda *args:{'status':'done'})
    monkeypatch.setattr(host,'v19_read_import_report',lambda *args:{'imported_image_ids':[image['id']]})
    assert client.get(f'/api/v61/projects/{project}/materials',params={'source_batch_id':'abc1234567'}).json()['total']==1
    payload={'operation':'DELETE_INDEX','selection_spec':{'scope':'FILTERED','filters':{'source_batch_id':'abc1234567'}}}
    base=f'/api/v62/projects/{project}/material-batches'
    for path in ['/estimate','']:
        result=client.post(base+path,json=payload)
        assert result.status_code==409,result.text
        assert result.json()['code']=='LEGACY_BATCH_SCOPE_REQUIRES_SELECTION'
