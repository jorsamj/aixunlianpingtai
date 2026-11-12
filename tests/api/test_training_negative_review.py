import io
from pathlib import Path
import uuid
import pytest
from PIL import Image
import app as platform_app


def test_formal_negative_review_preserves_person_and_cas_evidence(client,monkeypatch):
 project=client.post('/api/projects',json={'name':'negative-'+uuid.uuid4().hex[:8],'labels':[{'code':'vest'},{'code':'person'}]}).json()
 pid=project['id'];buffer=io.BytesIO();Image.new('RGB',(100,80),'blue').save(buffer,format='PNG')
 result=client.post(f'/api/projects/{pid}/images',files=[('files',('person.png',buffer.getvalue(),'image/png'))],data={'dataset_id':'default'}).json()
 image=result['uploaded'][0];iid=image['id'];path=f'/api/projects/{pid}/annotations/{iid}'
 initial=client.get(path).json()['annotation']
 box={'id':'person-1','label':'person','class_id':1,'x1':10,'y1':10,'x2':80,'y2':70}
 saved=client.post(path,json={'boxes':[box],'annotation_state':'annotated','expected_version':initial['version'],'source_content_sha256':image['content_sha256'],'reviewed_label_codes':['person']}).json()['annotation']
 monkeypatch.setattr(platform_app,'list_algorithms_internal',lambda _pid:[{'id':'a','name':'反光衣','versions':[]}])
 generic=client.post(f'/api/v62/projects/{pid}/training-materials/selection-summary',json={'algorithm_asset_id':'a','image_ids':[iid]})
 assert generic.status_code==200,generic.text
 assert generic.json()['label_codes']==['person']
 endpoint=f'/api/v62/projects/{pid}/training-materials/review-negative'
 payload={'algorithm_asset_id':'a','train_labels':['vest'],'model':'yolo11n.pt','confirmed':True,'items':[{'image_id':iid,'expected_version':saved['version'],'source_content_sha256':image['content_sha256']}],'actor_id':'forged'}
 before=platform_app.read_annotation(pid,iid)
 response=client.post(endpoint,json=payload);assert response.status_code==200,response.text
 assert response.json()['succeeded']==[iid] and not response.json()['failures']
 after=platform_app.read_annotation(pid,iid)
 assert after['boxes']==before['boxes'] and after['annotation_scope']==['person','vest']
 evidence=platform_app._v50_annotation_repository(pid).negative_review_evidence(iid,saved['version'],'isolated-test',['vest'],image['content_sha256'])
 assert evidence and evidence['annotation_version']==after['version']
 replay=client.post(endpoint,json=payload).json();assert replay['succeeded']==[iid]
 assert platform_app.read_annotation(pid,iid)['version']==after['version']
 # A later genuine revision invalidates old review evidence, even if scope remains.
 changed=[{**box,'x2':75}]
 fresh=client.post(path,json={'boxes':changed,'annotation_state':'annotated','expected_version':after['version'],'source_content_sha256':image['content_sha256'],'reviewed_label_codes':['person']})
 assert fresh.status_code==200
 stale=client.post(endpoint,json=payload).json();assert not stale['succeeded'] and stale['failures'][0]['status_code']==409
 current=platform_app.read_annotation(pid,iid)
 assert current['annotation_scope']==['person'], 'changed GT must invalidate batch-reviewed vest absence unless explicitly reviewed again'
 payload['items'][0]['expected_version']=current['version']
 assert client.post(endpoint,json=payload).json()['succeeded']==[iid]
 current=platform_app.read_annotation(pid,iid)
 # A genuine isolated source change with identical GT boxes cannot inherit H1 absence.
 import hashlib
 from platform_core.storage.manager import StorageManager
 material=platform_app.material_store(pid).get(iid)
 source=Path(StorageManager(data_dir=platform_app.DATA_DIR,project_id=pid,materials=platform_app.material_store(pid)).materialize(material).path)
 Image.new('RGB',(100,80),'green').save(source)
 new_hash=hashlib.sha256(source.read_bytes()).hexdigest()
 platform_app.material_store(pid).patch({iid:{'content_sha256':new_hash,'size_bytes':source.stat().st_size,'annotation_needs_review':True,'annotation_review_reason':'SOURCE_CONTENT_CHANGED'}})
 refreshed=client.post(path,json={'boxes':current['boxes'],'annotation_state':'annotated','expected_version':current['version'],'source_content_sha256':new_hash,'reviewed_label_codes':['person']})
 assert refreshed.status_code==200,refreshed.text
 current=platform_app.read_annotation(pid,iid)
 assert current['annotation_scope']==['person'], 'same boxes on a new image must not reuse old absence'
 image['content_sha256']=new_hash
 payload['items'][0]['source_content_sha256']=new_hash
 target=client.post(path,json={'boxes':[box,{**box,'id':'vest-1','label':'vest','class_id':0}],'annotation_state':'annotated','expected_version':current['version'],'source_content_sha256':image['content_sha256'],'reviewed_label_codes':['person','vest']}).json()['annotation']
 payload['items'][0]['expected_version']=target['version']
 denied=client.post(endpoint,json=payload).json();assert not denied['succeeded'] and denied['failures'][0]['status_code']==409
 assert platform_app.material_store(pid).get(iid)['content_sha256']==image['content_sha256']


def test_partial_positive_human_scope_review_keeps_original_boxes_and_actor_evidence(client, monkeypatch):
 project=client.post('/api/projects',json={'name':'partial-review-'+uuid.uuid4().hex[:8],
     'labels':[{'code':'person'},{'code':'head'}]}).json()
 pid=project['id'];buffer=io.BytesIO();Image.new('RGB',(100,80),'blue').save(buffer,format='PNG')
 image=client.post(f'/api/projects/{pid}/images',files=[('files',('partial.png',buffer.getvalue(),'image/png'))]).json()['uploaded'][0]
 iid=image['id'];endpoint=f'/api/projects/{pid}/annotations/{iid}'
 previous=client.get(endpoint).json()['annotation']
 box={'id':'person-1','label':'person','class_id':0,'x1':10,'y1':10,'x2':80,'y2':70}
 saved=client.post(endpoint,json={'boxes':[box],'annotation_state':'annotated',
     'expected_version':previous['version'],'source_content_sha256':image['content_sha256'],
     'reviewed_label_codes':['person']}).json()['annotation']
 monkeypatch.setattr(platform_app,'list_algorithms_internal',lambda _pid:[{'id':'a','versions':[]}])
 revisions=client.get(f'/api/v62/projects/{pid}/training-materials/revision').json()
 payload={'algorithm_asset_id':'a','train_labels':['person','head'], 'confirmed':True,
     'expected_material_revision':revisions['repository_revision'],
     'expected_annotation_revision':revisions['annotation_revision'],
     'items':[{'image_id':iid,'expected_version':saved['version'],
         'source_content_sha256':image['content_sha256'],'reviewed_label_codes':['head']}]}
 result=client.post(f'/api/v62/projects/{pid}/training-materials/review-scopes',json=payload)
 assert result.status_code==200,result.text
 assert result.json()['succeeded']==[iid] and not result.json()['failures']
 current=client.get(endpoint).json()['annotation']
 assert current['boxes']==saved['boxes']
 assert current['annotation_scope']==['head','person']
 evidence=platform_app._v50_annotation_repository(pid).negative_review_evidence(
     iid,saved['version'],'isolated-test',['head'],image['content_sha256'])
 assert evidence and evidence['annotation_version']==current['version'] and evidence['reviewed_at']
 refreshed_revisions=client.get(f'/api/v62/projects/{pid}/training-materials/revision').json()
 wrong=client.post(f'/api/v62/projects/{pid}/training-materials/review-scopes',json={**payload,
     'expected_material_revision':refreshed_revisions['repository_revision'],
     'expected_annotation_revision':refreshed_revisions['annotation_revision'],
     'items':[{**payload['items'][0],'expected_version':current['version']}]})
 assert wrong.status_code==200
 assert not wrong.json()['succeeded'] and wrong.json()['failures']


def test_durable_cross_page_review_plan_uses_real_formal_gt_save_and_actor_evidence(client, monkeypatch):
 project=client.post('/api/projects',json={'name':'plan-gt-'+uuid.uuid4().hex[:8],
     'labels':[{'code':'person'},{'code':'head'}]}).json()
 pid=project['id'];selected=[];versions={}
 for index in range(3):
     buffer=io.BytesIO();Image.new('RGB',(100,80),(20+index*50,50,110)).save(buffer,format='PNG')
     uploaded=client.post(f'/api/projects/{pid}/images',files=[('files',(f'plan-{index}.png',buffer.getvalue(),'image/png'))]).json()['uploaded'][0]
     image_id=uploaded['id'];selected.append(image_id)
     before=client.get(f'/api/projects/{pid}/annotations/{image_id}').json()['annotation']
     boxes=[{'id':f'p-{index}','label':'person','class_id':0,'x1':10,'y1':10,'x2':80,'y2':70}]
     if index==0:
         boxes.append({'id':'head-present','label':'head','class_id':1,'x1':20,'y1':15,'x2':40,'y2':40})
     saved=client.post(f'/api/projects/{pid}/annotations/{image_id}',json={
         'boxes':boxes,'annotation_state':'annotated','expected_version':before['version'],
         'source_content_sha256':uploaded['content_sha256'],
         'reviewed_label_codes':['person','head'] if index==0 else ['person']})
     assert saved.status_code==200,saved.text
     versions[image_id]=saved.json()['annotation']['version']
 monkeypatch.setattr(platform_app,'list_algorithms_internal',lambda _pid:[{'id':'a','versions':[]}])
 endpoint=f'/api/v62/projects/{pid}/training-materials'
 body={'algorithm_asset_id':'a','train_labels':['person','head'],'model':'yolo11n.pt',
     'train_image_ids':selected,'split_mode':'random_test_from_training_pool'}
 compatibility=client.post(endpoint+'/compatibility',json=body)
 assert compatibility.status_code==200,compatibility.text
 truth=compatibility.json()
 assert {issue['image_id'] for issue in truth['items'] if issue['issue_type']=='partial_review_scope'}==set(selected[1:])
 payload={**body,'expected_material_revision':truth['material_revision'],
          'expected_annotation_revision':truth['annotation_revision'],
          'selection':{'all_filtered':True}}
 preview=client.post(endpoint+'/review-scope-plans',json=payload)
 assert preview.status_code==200,preview.text
 plan=preview.json();assert plan['pending']==2 and plan['blocked']==0
 executed=client.post(endpoint+'/review-scope-plans/'+plan['task_id']+'/execute',json={'confirmed':True,'max_items':1})
 assert executed.status_code==200,executed.text
 assert executed.json()['pending']==1
 finished=client.post(endpoint+'/review-scope-plans/'+plan['task_id']+'/execute',json={'confirmed':True,'max_items':1})
 assert finished.status_code==200,finished.text
 assert finished.json()['succeeded']==2 and finished.json()['done']
 for image_id in selected[1:]:
     actual=client.get(f'/api/projects/{pid}/annotations/{image_id}').json()['annotation']
     assert len(actual['boxes'])==1 and actual['boxes'][0]['label']=='person'
     assert set(actual['annotation_scope'])=={'person','head'}
     evidence=platform_app._v50_annotation_repository(pid).negative_review_evidence(
         image_id,versions[image_id],'isolated-test',['head'],platform_app.material_store(pid).get(image_id)['content_sha256'])
     assert evidence and evidence['annotation_version']==actual['version']


def test_negative_review_keeps_previously_reviewed_empty_scopes(client,monkeypatch):
 project=client.post('/api/projects',json={'name':'empty-'+uuid.uuid4().hex[:8],'labels':[{'code':'vest'},{'code':'person'}]}).json();pid=project['id']
 buffer=io.BytesIO();Image.new('RGB',(20,20),'red').save(buffer,format='PNG')
 image=client.post(f'/api/projects/{pid}/images',files=[('files',('empty.png',buffer.getvalue(),'image/png'))]).json()['uploaded'][0]
 path=f"/api/projects/{pid}/annotations/{image['id']}"
 before=client.get(path).json()['annotation']
 saved=client.post(path,json={'boxes':[],'annotation_state':'confirmed_empty','expected_version':before['version'],'source_content_sha256':image['content_sha256'],'reviewed_label_codes':['person']}).json()['annotation']
 monkeypatch.setattr(platform_app,'list_algorithms_internal',lambda _pid:[{'id':'a','versions':[]}])
 result=client.post(f'/api/v62/projects/{pid}/training-materials/review-negative',json={'algorithm_asset_id':'a','train_labels':['vest'],'confirmed':True,'items':[{'image_id':image['id'],'expected_version':saved['version'],'source_content_sha256':image['content_sha256']}]}).json()
 assert result['succeeded']==[image['id']]
 assert client.get(path).json()['annotation']['annotation_scope']==['person','vest']



def test_task_negative_confirmation_does_not_write_gt_and_invalidates(client, monkeypatch):
 project=client.post('/api/projects',json={'name':'task-negative-'+uuid.uuid4().hex[:8],'labels':[{'code':'vest'},{'code':'person'}]}).json()
 pid=project['id'];buffer=io.BytesIO();Image.new('RGB',(100,80),'blue').save(buffer,format='PNG')
 image=client.post(f'/api/projects/{pid}/images',files=[('files',('person.png',buffer.getvalue(),'image/png'))]).json()['uploaded'][0]
 iid=image['id'];path=f'/api/projects/{pid}/annotations/{iid}'
 platform_app.material_store(pid).patch({iid:{'processing_status':'processed'}})
 monkeypatch.setattr(platform_app,'list_algorithms_internal',lambda _pid:[{'id':'a','versions':[]}])
 before=client.get(path).json()['annotation']
 formal=client.post(path,json={'boxes':[],'annotation_state':'confirmed_empty',
     'expected_version':before['version'],'source_content_sha256':image['content_sha256'],
     'reviewed_label_codes':['person']})
 assert formal.status_code==200,formal.text
 before=formal.json()['annotation']
 endpoint=f'/api/v62/projects/{pid}/training-materials'
 body={'algorithm_asset_id':'a','train_labels':['vest'],'model':'yolo11n.pt','train_image_ids':[iid]}
 initial_revision=client.get(endpoint+'/revision').json()
 preview=client.post(endpoint+'/negative-preview',json=body)
 assert preview.status_code==200,preview.text
 assert preview.json()['counts']['pending_negative']==1
 role_page=client.post(endpoint+'/role-page',json=dict(body,sample_role='pending_negative'))
 assert role_page.status_code==200,role_page.text
 assert role_page.json()['sample_role_counts']['pending_negative']==1
 assert role_page.json()['items'][0]['id']==iid
 assert client.post(endpoint+'/confirm-negatives',json=dict(body,confirmed=False,proof_digest=preview.json()['proof_digest'])).status_code==422
 assert client.post(endpoint+'/confirm-negatives',json=dict(body,confirmed=True,proof_digest='forged')).status_code==409
 confirmed=client.post(endpoint+'/confirm-negatives',json=dict(body,confirmed=True,proof_digest=preview.json()['proof_digest']))
 assert confirmed.status_code==200,confirmed.text
 assert confirmed.json()['confirmed_count']==1
 revised=client.get(endpoint+'/revision').json()
 assert revised['negative_confirmation_revision']==initial_revision['negative_confirmation_revision']+1
 assert revised['annotation_revision']==initial_revision['annotation_revision']
 role_page=client.post(endpoint+'/role-page',json=dict(body,sample_role='confirmed_negative'))
 assert role_page.status_code==200,role_page.text
 assert role_page.json()['sample_role_counts']['confirmed_negative']==1
 assert role_page.json()['negative_confirmation_revision']==revised['negative_confirmation_revision']
 assert client.get(path).json()['annotation']==before
 fresh=client.post(endpoint+'/negative-preview',json=body).json()
 assert fresh['counts']['confirmed_negative']==1 and fresh['pending_count']==0
 summary=client.post(endpoint+'/selection-summary',json=dict(body,image_ids=[iid]))
 assert summary.status_code==200,summary.text
 assert summary.json()['sample_role_counts']['confirmed_negative']==1
 current=platform_app.material_store(pid).get(iid)
 platform_app.material_store(pid).patch({iid:{'content_sha256':'b'*64}})
 changed=client.post(endpoint+'/negative-preview',json=body).json()
 assert changed['counts']['confirmed_negative']==0
 assert client.get(path).json()['annotation']==before


def test_multiclass_training_preview_confirms_partial_positives_and_unannotated_background_without_gt_edit(client,monkeypatch):
 project=client.post('/api/projects',json={'name':'coverage-'+uuid.uuid4().hex[:8],
     'labels':[{'code':'person'},{'code':'head'}]}).json()
 pid=project['id']
 monkeypatch.setattr(platform_app,'list_algorithms_internal',lambda _pid:[{'id':'a','versions':[]}])
 selected=[]
 for index,channels in enumerate([('person','head'),('person',),('head',),(),()]):
     buffer=io.BytesIO()
     Image.new('RGB',(80,80),(index*35,40,150)).save(buffer,format='PNG')
     upload=client.post(f'/api/projects/{pid}/images',files=[('files',(f'gt-{index}.png',buffer.getvalue(),'image/png'))]).json()['uploaded'][0]
     iid=upload['id'];selected.append(iid)
     platform_app.material_store(pid).patch({iid:{'processing_status':'processed'}})
     # Last image intentionally has no committed GT, including any AI candidate.
     if index==4:continue
     old=client.get(f'/api/projects/{pid}/annotations/{iid}').json()['annotation']
     boxes=[{'id':f'{code}-{index}','label':code,'class_id':0 if code=='person' else 1,
         'x1':8,'y1':8,'x2':42,'y2':50} for code in channels]
     saved=client.post(f'/api/projects/{pid}/annotations/{iid}',json={
         'boxes':boxes,'annotation_state':'annotated' if boxes else 'confirmed_empty',
         'reviewed_label_codes':['person','head'] if boxes else ['person'],
         'expected_version':old['version'],'source_content_sha256':upload['content_sha256']})
     assert saved.status_code==200,saved.text
 endpoint=f'/api/v62/projects/{pid}/training-materials'
 payload={'algorithm_asset_id':'a','train_labels':['person','head'],'model':'yolo11n.pt',
     'train_image_ids':selected,'base_version_id':''}
 response=client.post(endpoint+'/negative-preview',json=payload)
 assert response.status_code==200,response.text
 preview=response.json();coverage=preview['coverage']
 assert coverage['selected_count']==5
 assert coverage['full_coverage_count']==1
 assert coverage['partial_coverage_count']==2
 assert coverage['zero_target_count']==2
 assert coverage['eligible_count']==5
 assert preview['counts']=={'positive':3,'confirmed_negative':0,'pending_negative':2,'pending_review':0}
 assert preview['pending_scope_count']==2
 second_page=client.post(endpoint+'/negative-preview',json={**payload,'preview_offset':1})
 assert second_page.status_code==200,second_page.text
 assert second_page.json()['proof_digest']==preview['proof_digest']
 assert [row['image_id'] for row in second_page.json()['pending_preview']]==[selected[4]]
 assert {item['code']:(item['image_count'],item['box_count']) for item in coverage['classes']}=={
     'person':(2,2),'head':(2,2)}
 assert [item['image_id'] for item in coverage['partial_preview']]==selected[1:3]
 assert [item['label_box_counts'] for item in coverage['partial_preview']]==[{'person':1},{'head':1}]
 assert all('/thumbnail' in item['image_url'] for item in coverage['partial_preview'])
 assert not coverage['problems']
 unannotated_before=client.get(f'/api/projects/{pid}/annotations/{selected[4]}').json()['annotation']
 # Task-local confirmation does not write formal GT even for an unannotated background.
 acknowledged_all=client.post(endpoint+'/confirm-negatives',json={**payload,'confirmed':True,'proof_digest':preview['proof_digest']})
 assert acknowledged_all.status_code==200,acknowledged_all.text
 assert acknowledged_all.json()['confirmed_count']==4
 assert client.get(f'/api/projects/{pid}/annotations/{selected[4]}').json()['annotation']==unannotated_before
 # Formal GT remains untouched, and a subsequent review of a partial positive
 # cannot silently reuse stale evidence after its GT changes.
 allowed=client.post(endpoint+'/negative-preview',json={**payload,'train_image_ids':selected[:3]})
 assert allowed.status_code==200,allowed.text
 assert allowed.json()['coverage']['partial_coverage_count']==2
 assert allowed.json()['pending_count']==0
 acknowledged=client.post(endpoint+'/confirm-negatives',json={**payload,'train_image_ids':selected[:3],
     'confirmed':True,'proof_digest':allowed.json()['proof_digest']})
 assert acknowledged.status_code==200,acknowledged.text
 assert acknowledged.json()['confirmed_count']==0
 target=f'/api/projects/{pid}/annotations/{selected[1]}'
 previous=client.get(target).json()['annotation']
 revised=client.post(target,json={'boxes':[{**previous['boxes'][0],'x2':43}],
     'annotation_state':'annotated','reviewed_label_codes':['person','head'],
     'expected_version':previous['version'],
     'source_content_sha256':platform_app.material_store(pid).get(selected[1])['content_sha256']})
 assert revised.status_code==200,revised.text
 stale=client.post(endpoint+'/confirm-negatives',json={**payload,'train_image_ids':selected[:3],
     'confirmed':True,'proof_digest':allowed.json()['proof_digest']})
 assert stale.status_code==409,'a pre-confirmation GT revision must invalidate the old proof'

@pytest.mark.parametrize("join_mode", ["existing", "upload_intent"])
def test_algorithm_pool_review_to_real_yolo_background(client, tmp_path, join_mode):
 import hashlib
 from platform_core.training_label_tasks import project_training_rows, training_material_role
 from platform_core.training_tasks import materialize_portable_dataset
 pytest.importorskip('ultralytics', reason='real loader proof runs in ultralytics-loader-contract CI job')
 from ultralytics.data.dataset import YOLODataset
 project=client.post('/api/projects',json={'name':'pool-chain-'+uuid.uuid4().hex[:8],'labels':[{'code':'fire'},{'code':'person'}]}).json()
 pid=project['id']
 algorithm=client.post(f'/api/v12/projects/{pid}/algorithms',json={'name':'fire-scope','algorithm_type':'yolo_ultralytics'}).json()['algorithm']
 stream=io.BytesIO();Image.new('RGB',(40,40),'blue').save(stream,format='PNG')
 uploaded=client.post(f'/api/projects/{pid}/images',files=[('files',('background.png',stream.getvalue(),'image/png'))]).json()['uploaded'][0]
 iid=uploaded['id'];pool=f'/api/v61/projects/{pid}/negative-pool'
 if join_mode=='upload_intent':
  category=client.post(pool+'/categories',json={'name':'background'}).json()['id']
  added=client.post(pool+'/upload-intent',json={'sample_type':'negative','algorithm_id':algorithm['id'],'image_ids':[iid],'category_ids':[category]})
 else:
  added=client.post(pool+'/members',json={'algorithm_id':algorithm['id'],'image_ids':[iid]})
 assert added.status_code==200,added.text
 before=platform_app.read_annotation(pid,iid)
 review=client.post(f'/api/v62/projects/{pid}/training-materials/review-negative',json={'algorithm_asset_id':algorithm['id'],'train_labels':['fire'],'confirmed':True,'items':[{'image_id':iid,'expected_version':before['version'],'source_content_sha256':uploaded['content_sha256']}]})
 assert review.status_code==200,review.text
 assert review.json()['succeeded']==[iid]
 listing=client.get(pool,params={'algorithm_id':algorithm['id'],'target_label':'fire'}).json()
 assert listing['items'][0]['negative_pool']['qualification']=='confirmed_for_requested_scope'
 formal=platform_app.read_annotation(pid,iid)
 material=platform_app.material_store(pid).get(iid)
 row={**material,**formal,'id':iid,'annotation_source_content_sha256':formal.get('source_content_sha256','')}
 contract={'effective_label_codes':['fire'],'training_projection_policy':'reviewed_negative_original_v3_preserve_selected'}
 assert training_material_role(row,contract)['role']=='confirmed_negative'
 projected=project_training_rows([row],contract)[0]
 source=tmp_path/'source.png';source.write_bytes(stream.getvalue())
 assert hashlib.sha256(source.read_bytes()).hexdigest()==uploaded['content_sha256']
 snapshot={'schema_version':3,'snapshot_id':'pool-chain','ids':{'train':[iid],'validation':[],'test':[]},'label_schema':[{'code':'fire','class_id':0}], 'images':[{'image_id':iid,'role':'train','content_sha256':uploaded['content_sha256'],'annotation_state':'confirmed_empty','annotation_scope':['fire']}]}
 bundle=materialize_portable_dataset(tmp_path/'task',snapshot,[projected],lambda _:source,safety_reserve_bytes=0)
 import json
 assert json.loads((bundle/'snapshot.json').read_text())['ids']['train']==[iid]
 dataset=YOLODataset(img_path=str(bundle/'dataset/images/train'),data={'names':{0:'fire'},'nc':1},imgsz=64,augment=False,cache=False)
 assert len(dataset.labels)==1 and len(dataset.labels[0]['cls'])==0
 assert dataset.labels[0]['im_file'].endswith(iid+'.png')
 assert platform_app.read_annotation(pid,iid)==formal

def test_pool_zip_session_freezes_algorithm_ownership(client):
 project=client.post('/api/projects',json={'name':'pool-zip-'+uuid.uuid4().hex[:8],'labels':[{'code':'fire'}]}).json()
 pid=project['id'];algorithm=client.post(f'/api/v12/projects/{pid}/algorithms',json={'name':'Fire'}).json()['algorithm']
 endpoint=f'/api/v19/projects/{pid}/datasets/default/import/uploads'
 invalid=client.post(endpoint,json={'file_name':'negative.zip','file_size':100,'fingerprint':'invalid-scope','algorithm_id':'missing'})
 assert invalid.status_code==422
 created=client.post(endpoint,json={'file_name':'negative.zip','file_size':100,'fingerprint':'pool-scope','algorithm_id':algorithm['id']})
 assert created.status_code==200,created.text
 job=platform_app.read_json(platform_app.v19_job_file(pid,created.json()['upload_id']),{})
 assert job['upload_algorithm_id']==algorithm['id']

def test_raw_zip_import_applies_only_frozen_algorithm_pool(client):
 import zipfile,time
 project=client.post('/api/projects',json={'name':'zip-pool-chain-'+uuid.uuid4().hex[:8],'labels':[{'code':'fire'}]}).json();pid=project['id']
 algorithm=client.post(f'/api/v12/projects/{pid}/algorithms',json={'name':'Fire'}).json()['algorithm']
 image=io.BytesIO();Image.new('RGB',(32,32),'green').save(image,format='PNG')
 archive=io.BytesIO()
 with zipfile.ZipFile(archive,'w') as z: z.writestr('raw.png',image.getvalue())
 job=client.post(f'/api/v19/projects/{pid}/datasets/default/import/jobs',files={'file':('raw.zip',archive.getvalue(),'application/zip')}).json()
 pool=f'/api/v61/projects/{pid}/negative-pool';category=client.post(pool+'/categories',json={'name':'background'}).json()['id']
 started=client.post(f'/api/v19/projects/{pid}/import/jobs/{job["id"]}/start',json={'algorithm_id':algorithm['id'],'sample_type':'negative','negative_category_ids':[category]})
 assert started.status_code==200,started.text
 deadline=time.monotonic()+10
 while time.monotonic()<deadline:
  final=client.get(f'/api/v19/projects/{pid}/import/jobs/{job["id"]}').json()
  if final.get('status') in ('done','failed'):break
  time.sleep(.05)
 assert final['status']=='done',final
 assert final['report']['upload_classification_status']=='applied'
 rows=client.get(pool,params={'algorithm_id':algorithm['id']}).json()['items']
 assert len(rows)==1
 assert rows[0]['negative_pool']['qualification']=='pending_confirmation'
 assert platform_app.read_annotation(pid,rows[0]['id'])['annotation_state']=='unannotated'
