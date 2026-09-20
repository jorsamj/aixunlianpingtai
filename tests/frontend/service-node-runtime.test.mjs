import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

import {
  buildAgentCommands,
  capabilityLabel,
  formatBytes,
  nodeStatusMeta,
  renderNodeCard,
  safePercent,
} from '../../static/modules/service-node-runtime.js';

test('service node helpers keep resource values truthful', () => {
  assert.equal(formatBytes(40 * 1024 * 1024 * 1024), '40.0 GB');
  assert.equal(formatBytes(undefined), '-');
  assert.equal(safePercent(117), 100);
  assert.equal(safePercent(-2), 0);
  assert.equal(capabilityLabel('material-import'), '素材导入');
  assert.equal(capabilityLabel('conversion.rknn'), '瑞芯微 RKNN 转换');
  assert.equal(capabilityLabel('deployment-test.rknn'), '瑞芯微板端验证');
  assert.deepEqual(nodeStatusMeta('ONLINE'), {label: 'Agent 在线', className: 'ok'});
  assert.deepEqual(nodeStatusMeta('OFFLINE'), {label: '心跳超时', className: 'err'});
  assert.deepEqual(nodeStatusMeta('NEVER_CONNECTED'), {label: '未收到心跳', className: 'warn'});
});

test('service node card renders observed GPU/runtime/task truth without secrets', () => {
  const html = renderNodeCard({
    node_id: 'gpu-a800-01',
    display_name: 'A800 训练节点',
    status: 'ONLINE',
    enabled: true,
    connection_mode: 'agent',
    hostname: 'ubuntu22',
    os_name: 'Linux',
    architecture: 'x86_64',
    agent_version: 'node-agent-v1',
    build_id: 'build-1',
    heartbeat_age_seconds: 2,
    allowed_capabilities: ['training', 'conversion'],
    reported_capabilities: ['training'],
    effective_capabilities: ['training'],
    resources: {
      cpu: {usage_percent: 25, physical_cores: 8, logical_cores: 16},
      memory: {total_bytes: 32 * 1024 ** 3, used_bytes: 8 * 1024 ** 3, available_bytes: 24 * 1024 ** 3, usage_percent: 25},
      disk: {path: '/data', total_bytes: 500 * 1024 ** 3, used_bytes: 100 * 1024 ** 3, free_bytes: 400 * 1024 ** 3, usage_percent: 20},
      gpu: {gpus: [{id: 'cuda:0', index: 0, name: 'NVIDIA A800-SXM4-40GB', utilization_percent: 17, temperature_c: 45, memory_total_bytes: 40 * 1024 ** 3, memory_used_bytes: 2 * 1024 ** 3, memory_free_bytes: 38 * 1024 ** 3}]},
    },
    runtime: {torch_version: '2.5.0+cu124', cuda_version: '12.4', cuda_available: true},
    process: {pid: 1234, rss_bytes: 512 * 1024 ** 2, threads: 8, open_files: 4, file_descriptors: 32},
    workers: [{worker_id: 'worker-training', roles: ['training'], online: true, pid: 2345}],
    durable_tasks: [{task_id: 'train-1', kind: 'TRAINING', status: 'RUNNING', stage: 'running', progress: 42}],
  });
  assert.match(html, /A800 训练节点/);
  assert.match(html, /NVIDIA A800-SXM4-40GB/);
  assert.match(html, /2\.5\.0\+cu124/);
  assert.match(html, /CUDA/);
  assert.match(html, /train-1/);
  assert.match(html, /42%/);
  assert.match(html, /测试联通/);
  assert.match(html, /data-node-action="test"/);
  assert.doesNotMatch(html, /agent_token|token_hash/i);
});

test('agent launch commands carry the one-time token for both Linux and Windows', () => {
  const commands = buildAgentCommands({
    origin: 'https://control.example.com/',
    nodeId: 'gpu-01',
    token: 'secret-once',
    capabilities: ['training', 'conversion'],
  });
  assert.match(commands.linux, /MC_CONTROL_PLANE_URL='https:\/\/control\.example\.com'/);
  assert.match(commands.linux, /MC_NODE_AGENT_TOKEN='secret-once'/);
  assert.match(commands.windows, /\$env:MC_NODE_ID='gpu-01'/);
  assert.match(commands.windows, /training,conversion/);
  assert.equal(commands.rockchipDoctor, '');
  assert.equal(commands.rockchipInstall, '');
});

test('Rockchip board commands expose strict doctor and token-safe systemd installer command', () => {
  const commands = buildAgentCommands({
    origin: 'https://control.example.com/',
    nodeId: 'rk3568-board-01',
    token: 'secret-once',
    capabilities: ['deployment-test.rknn'],
  });
  assert.match(commands.rockchipDoctor, /node_agent\.py --doctor/);
  assert.match(commands.rockchipDoctor, /deployment-test\.rknn/);
  assert.match(commands.rockchipInstall, /tools\/install_rockchip_agent\.sh/);
  assert.match(commands.rockchipInstall, /--node-id 'rk3568-board-01'/);
  assert.doesNotMatch(commands.rockchipInstall, /secret-once/);
});

test('service node card surfaces observed Rockchip SoC and RKNN runtime truth', () => {
  const html = renderNodeCard({
    node_id: 'rk-board',
    display_name: 'RK3568 板端',
    status: 'ONLINE',
    enabled: true,
    connection_mode: 'agent',
    allowed_capabilities: ['deployment-test.rknn'],
    reported_capabilities: ['deployment-test.rknn'],
    effective_capabilities: ['deployment-test.rknn'],
    runtime: {
      rknn_board: {available: true, chip: 'rk3568', rknn_lite_version: '2.3.2'},
    },
    resources: {},
    process: {},
  });
  assert.match(html, /瑞芯微板端验证/);
  assert.match(html, /RK3568/);
  assert.match(html, /RKNNLite 2\.3\.2/);
});


test('service node connectivity action keeps network reachability separate from Agent heartbeat truth', () => {
  const source = readFileSync(new URL('../../static/modules/service-node-runtime.js', import.meta.url), 'utf8');
  assert.match(source, /\/connectivity-test/);
  assert.match(source, /network_reachable/);
  assert.match(source, /heartbeat_online/);
  assert.match(source, /最近心跳/);
  assert.match(source, /网络可达/);
  assert.match(source, /hadCache/);
  assert.doesNotMatch(source, /fetch\([^\n]*agent_url/);
});
