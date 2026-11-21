"""Disposable AI-review HTTP fixture: real owners/auth/local bytes, no execution."""
import os,sys,tempfile,io,hashlib
from pathlib import Path
from dataclasses import replace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ['MC_TRAIN_DATA_DIR']=tempfile.mkdtemp(prefix='changlian-ai-review-')
os.environ['MC_LOCAL_USERNAME']='vue-acceptance'
os.environ['MC_LOCAL_PASSWORD']='isolated-test-only'
os.environ['MC_PLATFORM_VERSION']='isolated-ai-review-acceptance'
os.environ['YOLO_CONFIG_DIR']=str(Path(os.environ['MC_TRAIN_DATA_DIR'])/'ultralytics')
import app as api
from PIL import Image,ImageDraw
from platform_core.task_runtime import TaskRecord,TaskKind,TaskStatus
from platform_core.annotation_candidates import CandidateStore
def forbidden(*args,**kwargs):raise RuntimeError('Execution/SDK forbidden in AI review acceptance')
api._builtin_deploy_resources=lambda force=False:api._builtin_deploy_resource_summary()
api._scan_builtin_deploy_resources=forbidden
api._detect_local_deploy_resource=forbidden
api._v53_bootstrap_worker()
assert api._V53_BOOTSTRAP_STATUS['status']=='ready'
project_id=api.read_json(api.PROJECTS_FILE,[])[0]['id']
for code in ['person','vehicle']:api.add_label(project_id,api.AddLabelReq(label=code))
manager=api.storage_manager(project_id)
materials=[]
for index in range(3):
 image=Image.new('RGB',(640,480),(225,235,245));draw=ImageDraw.Draw(image)
 draw.rectangle((100,100,240,220),outline=(50,70,110),width=3);draw.text((20,420),f'ISOLATED AI {index}',fill=(20,30,40))
 data=io.BytesIO();image.save(data,format='JPEG');content=data.getvalue();identity=f'ai-review-material-{index:03}'
 key=f'uploads/{identity}.jpg';manager.upload_object('default_local',key,io.BytesIO(content),content_type='image/jpeg')
 materials.append({'id':identity,'filename':f'isolated-ai-{index:03}.jpg','storage_source_id':'default_local','storage_type':'local',
  'object_key':key,'content_sha256':hashlib.sha256(content).hexdigest(),'size_bytes':len(content),'width':640,'height':480,
  'processing_status':'processed','source_available':True,'created_at':'2026-11-17T01:00:00Z'})
api.material_store(project_id).upsert_many(materials)
task_id='isolated-vue-ai-review'
artifacts=api.shared_task_artifacts();repository=api.shared_task_repository()
artifacts.atomic_write_json(task_id,'request.json',{'name':'隔离AI审核真实入口','image_ids':[row['id'] for row in materials],
 'labels':['person','vehicle'],'model_config_name':'Synthetic saved candidates; no model','model_provider':'isolated'})
repository.create(replace(TaskRecord.new(task_id,project_id,TaskKind.AI_ANNOTATION,'request.json','isolated'),
 status=TaskStatus.AWAITING_CONFIRMATION,progress=100,stage='awaiting_confirmation',result_ref='candidates/manifest.json'))
store=CandidateStore(artifacts,task_id=task_id);store.initialize(labels=['person','vehicle'],total_images=len(materials))
store.append_items([{'image_id':row['id'],'status':'success','boxes':[{'id':f'candidate-{i}','label':'person',
 'x1':100,'y1':100,'x2':240,'y2':220}],'width':640,'height':480,'source_content_sha256':row['content_sha256']} for i,row in enumerate(materials)])
if __name__=='__main__':
 import uvicorn
 print(f'AI_REVIEW_FIXTURE project={project_id} task={task_id} DATA_DIR={api.DATA_DIR}',flush=True)
 uvicorn.run(api.app,host='127.0.0.1',port=int(os.environ.get('MC_VUE_AI_ACCEPTANCE_PORT','8030')),lifespan='off',log_level='warning')
