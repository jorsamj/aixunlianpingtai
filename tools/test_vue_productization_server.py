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
