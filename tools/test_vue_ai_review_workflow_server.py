"""8031 disposable real-owner workflow fixture; no model or executor startup."""
import io,hashlib
from dataclasses import replace
import test_vue_ai_review_server as fixture
from PIL import Image,ImageDraw
from platform_core.annotation_candidates import CandidateStore
from platform_core.task_runtime import TaskRecord,TaskKind,TaskStatus
from platform_core.negative_pool import NegativePool

api=fixture.api
project_id=fixture.project_id
artifacts=api.shared_task_artifacts()
def seed(task_id,count,mode='clean'):
    rows=[]
    for index in range(count):
        identity=f'{task_id}-{index:03}'
        image=Image.new('RGB',(320,240),(230,230,230));draw=ImageDraw.Draw(image)
        draw.rectangle((50,50,150,150),outline=(40,40,40),width=3);draw.text((10,210),identity,fill=(20,20,20))
        data=io.BytesIO();image.save(data,format='JPEG');content=data.getvalue();key=f'uploads/{identity}.jpg'
        fixture.manager.upload_object('default_local',key,io.BytesIO(content),content_type='image/jpeg')
        rows.append(dict(id=identity,filename=identity+'.jpg',object_key=key,storage_source_id='default_local',storage_type='local',
            content_sha256=hashlib.sha256(content).hexdigest(),size_bytes=len(content),width=320,height=240,processing_status='processed',source_available=True))
    api.material_store(project_id).upsert_many(rows)
    artifacts.atomic_write_json(task_id,'request.json',dict(name=task_id,image_ids=[r['id'] for r in rows],labels=['person','vehicle'],model_provider='isolated'))
    api.shared_task_repository().create(replace(TaskRecord.new(task_id,project_id,TaskKind.AI_ANNOTATION,'request.json','isolated'),status=TaskStatus.AWAITING_CONFIRMATION,progress=100,stage='awaiting_confirmation',result_ref='candidates/manifest.json'))
    store=CandidateStore(artifacts,task_id=task_id);store.initialize(labels=['person','vehicle'],total_images=count)
    items=[]
    for i,row in enumerate(rows):
        boxes=[dict(id=f'{i}-p',label='person',x1=50,y1=50,x2=150,y2=150)]
        item=dict(image_id=row['id'],filename=row['filename'],status='success',width=320,height=240,source_content_sha256=row['content_sha256'])
        if mode=='transfer' and i==1:boxes=[];item['status']='empty'
        if mode=='ambiguity':
            if i<2:
                boxes.append(dict(id=f'{i}-v',label='vehicle',x1=52,y1=52,x2=152,y2=152))
                if i==1:boxes.append(dict(id=f'{i}-p2',label='person',x1=53,y1=53,x2=153,y2=153))
                item['manual_review_required']=True
            elif i==2:boxes=[];item['status']='empty'
            else:boxes=[];item.update(status='failed',error='ISOLATED saved provider failure; no call made',error_code='ISOLATED_FAILURE')
        items.append({**item,'boxes':boxes})
    store.append_items(items)
seed('isolated-vue-batch',31)
seed('isolated-vue-lost',1)
seed('isolated-vue-transfer',2,'transfer')
seed('isolated-vue-ambiguity',4,'ambiguity')
NegativePool(api.material_store(project_id)).category(name='隔离流程分类')
if __name__=='__main__':
    import uvicorn
    print(f'AI_WORKFLOW_FIXTURE project={project_id} DATA_DIR={api.DATA_DIR}',flush=True)
    uvicorn.run(api.app,host='127.0.0.1',port=8031,lifespan='off',log_level='warning')
