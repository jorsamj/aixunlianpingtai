import {test, expect} from '@playwright/test';

function node(overrides = {}) {
  return {
    node_id: 'gpu-a800-01',
    display_name: 'A800 训练节点',
    connection_mode: 'agent',
    agent_url: 'http://10.0.0.20:8030',
    enabled: true,
    status: 'ONLINE',
    online: true,
    reachable: true,
    heartbeat_age_seconds: 2,
    heartbeat_ttl_seconds: 45,
    allowed_capabilities: ['training', 'conversion'],
    reported_capabilities: ['training', 'conversion'],
    effective_capabilities: ['training', 'conversion'],
    token_version: 1,
    hostname: 'ubuntu22-a800',
    os_name: 'Linux',
    os_version: 'Ubuntu 22.04',
    architecture: 'x86_64',
    agent_version: 'node-agent-v1',
    build_id: 'build-a800',
    last_heartbeat_at: new Date().toISOString(),
    resources: {
      cpu: {physical_cores: 8, logical_cores: 16, usage_percent: 21},
      memory: {total_bytes: 32 * 1024 ** 3, used_bytes: 8 * 1024 ** 3, available_bytes: 24 * 1024 ** 3, usage_percent: 25},
      disk: {path: '/data', total_bytes: 500 * 1024 ** 3, used_bytes: 100 * 1024 ** 3, free_bytes: 400 * 1024 ** 3, usage_percent: 20},
      gpu: {available: true, gpus: [{id: 'cuda:0', index: 0, name: 'NVIDIA A800-SXM4-40GB', utilization_percent: 17, temperature_c: 45, memory_total_bytes: 40 * 1024 ** 3, memory_used_bytes: 2 * 1024 ** 3, memory_free_bytes: 38 * 1024 ** 3}]},
    },
    runtime: {torch_version: '2.5.0+cu124', cuda_version: '12.4', cuda_available: true, device_count: 1},
    process: {pid: 1234, rss_bytes: 512 * 1024 ** 2, threads: 8, open_files: 4, file_descriptors: 32},
    workers: [{worker_id: 'worker-a800-training', roles: ['training'], online: true, pid: 2345}],
    durable_tasks: [{task_id: 'train-browser-1', kind: 'TRAINING', status: 'RUNNING', stage: 'running', progress: 42}],
    reported_active_tasks: ['train-browser-1'],
    last_error: '',
    ...overrides,
  };
}

test('service node page shows live resources and creates Agent credentials', async ({page}) => {
  const capabilities = ['training', 'material-import', 'cleaning', 'annotation', 'video', 'conversion', 'deployment-test', 'model-upload'];
  let nodes = [node()];
  let createdPayload = null;

  await page.route(/\/api\/v63\/service-nodes$/, async route => {
    const method = route.request().method();
    if (method === 'GET') {
      await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({items: nodes, supported_capabilities: capabilities})});
      return;
    }
    if (method === 'POST') {
      createdPayload = route.request().postDataJSON();
      const created = node({
        node_id: createdPayload.node_id,
        display_name: createdPayload.display_name,
        status: 'NEVER_CONNECTED',
        online: false,
        reachable: false,
        heartbeat_age_seconds: null,
        hostname: '',
        resources: {},
        runtime: {},
        process: {},
        workers: [],
        durable_tasks: [],
        allowed_capabilities: createdPayload.allowed_capabilities,
        reported_capabilities: [],
        effective_capabilities: [],
      });
      nodes = [...nodes, created];
      await route.fulfill({status: 201, contentType: 'application/json', body: JSON.stringify({node: created, agent_token: 'browser-agent-token-once', token_version: 1})});
      return;
    }
    await route.fallback();
  });

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  const nav = page.getByRole('button', {name: /服务节点/});
  await expect(nav).toBeVisible({timeout: 10_000});
  await nav.click();

  await expect(page.locator('#title')).toHaveText('服务节点');
  await expect(page.locator('[data-service-node-page="1"]')).toBeVisible({timeout: 10_000});
  await expect(page.locator('[data-node-card="gpu-a800-01"]')).toContainText('A800 训练节点');
  await expect(page.locator('[data-node-card="gpu-a800-01"]')).toContainText('NVIDIA A800-SXM4-40GB');
  await expect(page.locator('[data-node-card="gpu-a800-01"]')).toContainText('2.5.0+cu124');
  await expect(page.locator('[data-node-card="gpu-a800-01"]')).toContainText('12.4');
  await expect(page.locator('[data-node-card="gpu-a800-01"]')).toContainText('train-browser-1');
  await expect(page.locator('#summary')).toContainText('服务节点');
  await expect(page.locator('#summary')).toContainText('在线');

  await page.getByRole('button', {name: /新增服务节点/}).click();
  await expect(page.locator('[data-node-form="1"]')).toBeVisible();
  await page.locator('#node633Id').fill('worker-material-01');
  await page.locator('#node633Name').fill('素材处理节点');
  await page.locator('.node633-cap-picker input[value="material-import"]').check();
  await page.locator('.node633-cap-picker input[value="cleaning"]').check();
  await page.locator('#node633Save').click();

  await expect(page.locator('[data-node-token="1"]')).toBeVisible({timeout: 10_000});
  await expect(page.locator('#node633TokenValue')).toHaveText('browser-agent-token-once');
  await expect(page.locator('#node633LinuxCommand')).toContainText('MC_NODE_ID=\'worker-material-01\'');
  await expect(page.locator('#node633WindowsCommand')).toContainText("$env:MC_NODE_AGENT_TOKEN='browser-agent-token-once'");
  expect(createdPayload).toMatchObject({
    node_id: 'worker-material-01',
    display_name: '素材处理节点',
    connection_mode: 'agent',
    enabled: true,
  });
  expect(createdPayload.allowed_capabilities).toEqual(['material-import', 'cleaning']);
});
