"""Isolated real-entry acceptance server. Never points at an existing DATA_DIR.

Uses real auth, catalog operations/receipts, references, service-node repository
and HTTP routes. Startup schedulers/recovery and SDK probes are deliberately off.
All node/device evidence below is synthetic and is not hardware verification.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['MC_TRAIN_DATA_DIR'] = tempfile.mkdtemp(prefix='changlian-vue-p1bd-')
os.environ['MC_LOCAL_USERNAME'] = 'vue-acceptance'
os.environ['MC_LOCAL_PASSWORD'] = 'isolated-test-only'
os.environ['MC_PLATFORM_VERSION'] = 'isolated-vue-acceptance'
os.environ['YOLO_CONFIG_DIR'] = str(Path(os.environ['MC_TRAIN_DATA_DIR']) / 'ultralytics')

import app as api
from platform_core.service_nodes import ServiceNodeRepository

def forbidden(*_args, **_kwargs):
    raise RuntimeError('Hardware/SDK probing forbidden in Vue acceptance')

# Existing legacy GETs may otherwise launch implicit SDK probes.
api._builtin_deploy_resources = lambda force=False: api._builtin_deploy_resource_summary()
api._scan_builtin_deploy_resources = forbidden
api._detect_local_deploy_resource = forbidden
api._v53_bootstrap_worker()
assert api._V53_BOOTSTRAP_STATUS['status'] == 'ready'

# Saved synthetic version/job records only: never create or execute a training or
# conversion task. Exercise the original SQL and history owners through HTTP.
from platform_core.algorithms import save_algorithms
project_id=api.read_json(api.PROJECTS_FILE,[])[0]['id']
save_algorithms(api.algorithms_file(project_id),[{
    'id':'acceptance-algorithm','name':'隔离验收模型（合成数据）',
    'algorithm_type':'yolo_ultralytics','industry':'验收','source_type':'LOCAL',
    'current_version_id':'acceptance-v0','created_at':'2026-11-01',
    'versions':[{'id':f'acceptance-v{i}','version_name':f'合成版本 {i}',
        'framework':'ultralytics','training_status':'SUCCEEDED',
        'created_at':'2026-11-15','stored_path':'/isolated/private/best.pt',
        'job_id':'acceptance-train-00' if i==0 else '',
        'sha256':'synthetic-source-sha','metrics':{'map50':None},
        'val_metrics':{'map50':0},'evaluation':{'metrics':{'map50':.72},'samples':['FROZEN_GT_SENTINEL']},
        'label_codes':['smoke'],'training_lineage':{'parameters':{'actual':{'epochs':50,'imgsz':640}}}}
        for i in range(22)]}])
for i in range(25):
    directory=api.deploy_root(project_id)/'jobs'/f'acceptance-conversion-{i:02}'
    directory.mkdir(parents=True,exist_ok=True)
    api.write_json(directory/'job.json',{'id':f'acceptance-conversion-{i:02}',
        'source_id':'version::acceptance-algorithm::acceptance-v0',
        'source_trace':{'algorithm_id':'acceptance-algorithm','version_id':'acceptance-v0','sha256':'synthetic-source-sha'},
        'status':'failed' if i%2 else 'done','target':'onnx',
        'created_at':f'2026-11-15T12:{i:02}:00Z','finished_at':f'2026-11-15T12:{i:02}:30Z',
        'params':{'precision':'fp16','chip':'fixture-chip','csc':{'preset':'none'}},
        'outputs':[{'name':'model.onnx','path':str(directory/'missing.onnx')}],
        'error':'合成诊断：依赖缺失 token=PRIVATE_SENTINEL /isolated/private/file' if i%2 else ''})

from dataclasses import replace
from platform_core.task_runtime import TaskRecord,TaskKind,TaskStatus
for i in range(25):
    task_id=f'acceptance-train-{i:02}'
    task=TaskRecord.new(task_id,project_id,TaskKind.TRAINING,'payload.json','training:auto')
    api.shared_task_repository().create(replace(task,status=TaskStatus.SUCCEEDED if i%2==0 else TaskStatus.FAILED,
        progress=100,stage='finished',worker_id='synthetic-worker',finished_at='2026-11-17T00:00:00Z'))
    api.shared_task_artifacts().atomic_write_json(task_id,'payload.json',{'asset_algorithm_id':'acceptance-algorithm',
        'asset_algorithm_name':'隔离验收模型（合成数据）','epochs':50,'batch':4,'imgsz':640,
        'dataset_selected_ids':['FROZEN_GT_SENTINEL'],'token':'PRIVATE_SENTINEL'})
    api.shared_task_artifacts().atomic_write_json(task_id,'result.json',{
        'training_report':{'metrics':{'precision':0,'recall':None,'map50':None,'map50_95':.5},
            'history':[{'epoch':j,'map50':j/100,'box_loss':1-j/50,'val_box_loss':.8} for j in range(1,15)]},
        'evaluation':{'status':'succeeded','metrics':{'map50':.72},'error_samples':['FROZEN_GT_SENTINEL']},
        'execution':{'node_id':'synthetic-node','worker_id':'synthetic-worker','started_at':'2026-11-16T23:00:00Z'},
        'metric_credibility':{'status':'unavailable','message':'合成数据，仅验展示，不代表现场质量'}})
    directory=api.project_dir(project_id)/'jobs'/task_id;directory.mkdir(parents=True,exist_ok=True)
    api.write_json(directory/'job.json',{'id':task_id,'status':'done' if i%2==0 else 'failed','framework':'ultralytics',
        'asset_algorithm_id':'acceptance-algorithm','epochs':50,'batch':4,'imgsz':640,'metrics':{'map50':.99}})

registry = ServiceNodeRepository(api.shared_task_repository())
_, token = registry.create({'node_id': 'acceptance-arm64', 'display_name': 'ARM64 测试快照节点', 'connection_mode': 'agent', 'allowed_capabilities': ['training', 'conversion']})
registry.heartbeat('acceptance-arm64', token, {
    'hostname': 'isolated-fixture', 'os_name': 'Linux', 'architecture': 'aarch64',
    'agent_version': 'acceptance-fixture', 'reported_capabilities': ['conversion'],
    'resources': {'cpu': {'usage_percent': 18, 'physical_cores': 8, 'logical_cores': 16},
                  'memory': {'usage_percent': 25, 'used_bytes': 4294967296, 'total_bytes': 17179869184, 'available_bytes': 12884901888},
                  'gpu': {'gpus': []}},
    'last_error': '合成心跳，仅验证展示合同，不代表真实硬件。',
})
registry.create({'node_id': 'acceptance-never', 'display_name': '未连接测试节点', 'connection_mode': 'local', 'allowed_capabilities': []})

if __name__ == '__main__':
    import uvicorn
    print('Isolated Vue acceptance server; synthetic heartbeat; SDK disabled.', flush=True)
    uvicorn.run(api.app, host='127.0.0.1', port=int(os.environ.get('MC_VUE_ACCEPTANCE_PORT', '8028')), lifespan='off', log_level='warning')
