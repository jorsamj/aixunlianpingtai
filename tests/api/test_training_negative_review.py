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
