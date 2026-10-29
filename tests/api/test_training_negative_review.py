import io
from pathlib import Path
import uuid
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


def test_multiclass_training_preview_keeps_partial_positives_and_rejects_uncommitted_gt(client,monkeypatch):
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
 assert coverage['zero_target_count']==1
 assert coverage['eligible_count']==4
 assert preview['counts']=={'positive':3,'confirmed_negative':0,'pending_negative':1,'pending_review':1}
 assert {item['code']:(item['image_count'],item['box_count']) for item in coverage['classes']}=={
     'person':(2,2),'head':(2,2)}
 assert coverage['problems'][0]['image_id']==selected[4]
 # A task-level acknowledgment cannot launder the uncommitted image into a background sample.
 denied=client.post(endpoint+'/confirm-negatives',json={**payload,'confirmed':True,'proof_digest':preview['proof_digest']})
 assert denied.status_code==422
 # Partial positive coverage alone is enough to trigger an informational review;
 # formally reviewed class absence never removes the other positive GT boxes.
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
