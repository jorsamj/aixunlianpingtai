import {test, expect} from '@playwright/test';


function bmp(width = 128, height = 96) {
  const rowBytes = Math.ceil(width * 3 / 4) * 4;
  const buffer = Buffer.alloc(54 + rowBytes * height);
  buffer.write('BM', 0, 'ascii');
  buffer.writeUInt32LE(buffer.length, 2);
  buffer.writeUInt32LE(54, 10);
  buffer.writeUInt32LE(40, 14);
  buffer.writeInt32LE(width, 18);
  buffer.writeInt32LE(height, 22);
  buffer.writeUInt16LE(1, 26);
  buffer.writeUInt16LE(24, 28);
  buffer.writeUInt32LE(rowBytes * height, 34);
  buffer.fill(120, 54);
  return buffer;
}


test('vision providers, candidate review, and vendor target parameters are explicit', async ({page, request}) => {
  const project = await (await request.post('/api/projects', {data: {
    name: `模型转换浏览器-${Date.now()}`,
    labels: [{code: 'fire', display_name: '明火'}]
  }})).json();
  const upload = await request.post(`/api/projects/${project.id}/images`, {multipart: {
    dataset_id: 'default', files: {name: 'candidate.bmp', mimeType: 'image/bmp', buffer: bmp()}
  }});
  const image = (await upload.json()).uploaded[0];
  await request.post(`/api/projects/${project.id}/annotations/${image.id}`, {data: {boxes: [{
    class_id: 0, label: 'fire', x1: 10, y1: 8, x2: 90, y2: 70
  }]}});
  const configured = await request.post('/api/v35/model-configs', {data: {
    name: '浏览器默认视觉模型', provider_type: 'ollama', provider_adapter: 'ollama',
    model_kind: 'vlm', detect_url: 'http://127.0.0.1:11434', model_name: 'qwen2.5vl:3b',
    default_for_annotation: true
  }});
  expect(configured.ok()).toBeTruthy();
  await page.addInitScript(projectId => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({projectId, page: '模型配置'}));
  }, project.id);
  await page.goto('/');

  await page.evaluate(() => window.setPage('模型配置'));
  await page.getByRole('button', {name: /新增模型/}).click();
  const modelDialog = page.getByRole('dialog');
  await expect(modelDialog.locator('#mcProviderAdapter')).toBeVisible();
  await expect(modelDialog.locator('#mcProviderAdapter option')).toHaveText([
    /火山方舟/, /阿里云千问/, /本地 OpenAI/, /Ollama/
  ]);
  await expect(modelDialog.locator('#mcApiKey')).toHaveValue('');
  await expect(modelDialog.locator('#mcAnnPrompt')).toBeVisible();
  await modelDialog.getByRole('button', {name: '取消'}).click();

  await page.evaluate(() => window.setPage('自动标注及清洗'));
  await page.getByRole('button', {name: /创建AI标注任务/}).click();
  const createAiDialog = page.getByRole('dialog', {name: '创建AI自动标注任务'});
  await expect(createAiDialog.getByText('浏览器默认视觉模型', {exact: true})).toBeVisible();
  const keptReferenceNode = await page.evaluate(() => {
    const button = document.querySelector('#ai429RefGrid button');
    button.click();
    return document.querySelector('#ai429RefGrid button') === button;
  });
  expect(keptReferenceNode).toBe(true);
  await expect(createAiDialog.locator('#ai429Labels')).toHaveValue('fire');
  await expect(createAiDialog.locator('#ai417ReferenceLabels')).toContainText('fire · 明火');
  await createAiDialog.getByRole('button', {name: '取消'}).click();

  await page.route(`**/api/v60/projects/${project.id}/annotation-tasks/fake-task/candidates?*`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      total: 1,
      items: [{
        image_id: image.id,
        filename: image.filename,
        url: image.url,
        status: 'success',
        boxes: [{label: 'fire', confidence: 0.95, x1: 10, y1: 8, x2: 90, y2: 70}]
      }]
    })
  }));
  await page.evaluate(() => window.reviewAiLabel427('fake-task'));
  const candidateDialog = page.getByRole('dialog', {name: /AI待确认标注/});
  await expect(candidateDialog.getByText(/不会自动写入正式标注/)).toBeVisible();
  await expect(candidateDialog.locator('.data412-box')).toBeVisible();
  await expect(candidateDialog.getByRole('button', {name: '全部接受'})).toBeVisible();
  await candidateDialog.getByRole('button', {name: '暂不处理'}).click();

  await page.evaluate(() => window.setPage('部署转换'));
  await page.locator('.deploy-target-card', {hasText: '华为 Atlas'}).click();
  await expect(page.locator('#dpSoc')).toBeVisible();
  await page.locator('.deploy-target-card', {hasText: '瑞芯微 RKNN'}).click();
  await expect(page.locator('#dpChip option')).toHaveText(['RK3588', 'RK3576', 'RK3568']);
  await page.locator('.deploy-target-card', {hasText: 'NVIDIA TensorRT'}).click();
  await expect(page.locator('#dpTargetEnvironment')).toBeVisible();
});

test('version conversion shows configured compiler resources and their readiness', async ({page, request}) => {
  const project = await (await request.post('/api/projects', {data: {
    name: `转换资源浏览器-${Date.now()}`,
    labels: [{code: 'fire', display_name: '明火'}]
  }})).json();
  const algorithmId = 'algorithm-resource-test';
  const versionId = 'version-resource-test';
  await page.route(`**/api/v42/projects/${project.id}/algorithms/${algorithmId}/versions/${versionId}/deployments`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      algorithm: {id: algorithmId, name: '转换资源算法'},
      version: {id: versionId, version_name: '20260829120000', model_name: 'best.pt', stored_path: 'C:\\models\\best.pt'},
      items: []
    })
  }));
  await page.route('**/api/v39/deploy/resources', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({items: [
      {id: 'rknn-windows', name: 'Windows RKNN-Toolkit2', kind: 'rockchip', mode: 'local', status: 'missing', targets: [], message: '未检测到 RKNN-Toolkit2；建议配置 Linux/WSL2 或远程转换节点'},
      {id: 'atlas-remote', name: 'Atlas 远程转换节点', kind: 'ascend', mode: 'remote', status: 'unchecked', targets: [], message: '尚未检测远程服务'}
    ]})
  }));
  await page.addInitScript(projectId => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({projectId, page: '工作台'}));
  }, project.id);
  await page.goto('/');
  await page.evaluate(async () => { if (window.__clInit) await window.__clInit(); });
  await expect(page.getByRole('button', {name: /算法列表/})).toBeVisible();
  await page.evaluate(([aid, vid]) => window.openVersionConvert428(aid, vid), [algorithmId, versionId]);
  const historyDialog = page.getByRole('dialog', {name: '版本转换'});
  await expect(historyDialog).toBeVisible();
  await historyDialog.getByRole('button', {name: '选择转换目标'}).click();
  const createDialog = page.getByRole('dialog', {name: '新建版本转换'});
  await expect(createDialog).toBeVisible();
  await createDialog.locator('input[name="conv428Target"][value="rockchip"]').check();
  await expect(createDialog.locator('.convert428-resource-status')).toContainText('Windows RKNN-Toolkit2');
  await expect(createDialog.locator('.convert428-resource-status')).toContainText('未检测到 RKNN-Toolkit2');
  await expect(createDialog.getByRole('button', {name: '配置部署资源'})).toBeVisible();
  await createDialog.getByRole('button', {name: '取消'}).click();
  await historyDialog.locator('button[aria-label="关闭"]').click();
  await page.evaluate(() => window.setPage('部署转换'));
  await expect(page.locator('.deploy-target-card', {hasText: '瑞芯微 RKNN'})).toBeVisible();
  await page.locator('.deploy-target-card', {hasText: '瑞芯微 RKNN'}).click();
  await expect(page.locator('.deploy-resource-readiness')).toContainText('Windows RKNN-Toolkit2');
});

test('module graph is cache-busted and exposes platform helpers', async ({page, request}) => {
  const main = await request.get('/static/main.mjs');
  expect(await main.text()).toMatch(/\.\/modules\/materials\.js\?v=\d+/);

  await page.goto('/');
  await expect.poll(() => page.evaluate(() => typeof window.PlatformCore?.materials?.labelDisplay)).toBe('function');
});


test('deployment resource editor exposes service-node Agent for RKNN', async ({page, request}) => {
  const project = await (await request.post('/api/projects', {data: {
    name: `RKNN-Agent-资源-${Date.now()}`,
    labels: []
  }})).json();
  await page.addInitScript(projectId => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({
      projectId,
      page: '部署资源'
    }));
  }, project.id);
  await page.goto('/');
  await expect.poll(
    () => page.evaluate(() => typeof window.openDeployResourceModal),
    {timeout: 20_000},
  ).toBe('function');

  await page.evaluate(() => window.openDeployResourceModal());
  const dialog = page.getByRole('dialog', {name: '新增部署资源'});
  await expect(dialog).toBeVisible();
  await expect(dialog.locator('#drMode option')).toHaveText([
    '本机',
    '远程转换服务器',
    '服务节点 Agent',
  ]);
  await dialog.locator('#drMode').selectOption('agent');
  await dialog.locator('#drKind').selectOption('rockchip');
  await expect(dialog.locator('#drLocal')).toHaveClass(/hidden/);
  await expect(dialog.locator('#drRemote')).toHaveClass(/hidden/);
  await dialog.getByRole('button', {name: '关闭'}).click();

  await page.evaluate(() => window.setPage('部署转换'));
  await page.locator('.deploy-target-card', {hasText: '瑞芯微 RKNN'}).click();
  await expect(page.locator('#dpChip option')).toHaveText(['RK3588', 'RK3576', 'RK3568']);
});


test('RKNN converted_unverified job exposes board verification and upgrades after real task success', async ({page, request}) => {
  const project = await (await request.post('/api/projects', {data: {
    name: `RKNN板端验证-${Date.now()}`,
    labels: []
  }})).json();
  let hardwarePost = null;
  let taskReads = 0;
  let jobVerified = false;

  await page.route('**/api/v39/deploy/resources', route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({items: []})
  }));
  await page.route(`**/api/v39/projects/${project.id}/deploy/source-models`, route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({items: []})
  }));
  await page.route(`**/api/v39/projects/${project.id}/deploy/artifacts`, route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({items: []})
  }));
  await page.route(`**/api/v39/projects/${project.id}/deploy/jobs`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({items: [{
      id: 'rk-job-1',
      source_name: 'best.pt',
      target: 'rockchip',
      status: 'done',
      stage: jobVerified ? 'hardware_verified' : 'converted_unverified',
      progress: 100,
      conversion_status: jobVerified ? 'hardware_verified' : 'converted_unverified',
      validation_status: jobVerified ? 'hardware_verified' : 'converted_unverified',
      hardware_verified: jobVerified,
      hardware_verification: jobVerified ? {
        task_id: 'rk-board-task-1',
        execution_generation: 1,
        verified_at: '2026-09-19T01:02:03+00:00',
        node_id: 'rk3568-board-01',
        chip: 'rk3568',
        rknn_lite_version: '2.3.2',
        inference_ms: 12.34,
        output_count: 3,
        output_shapes: [[1, 84, 8400]]
      } : null,
      params: {chip: 'rk3568', precision: 'fp16'},
      resource: {name: 'RKNN Agent'}
    }]})
  }));
  await page.route(`**/api/v39/projects/${project.id}/deploy/jobs/rk-job-1/hardware-tests/preflight`, async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        ready: true,
        already_verified: false,
        chip: 'rk3568',
        model: {
          file_name: 'model_rk3568.rknn',
          size_bytes: 1024,
          sha256: 'a'.repeat(64)
        },
        board_nodes: [{
          node_id: 'rk3568-board-01',
          display_name: 'RK3568 验收板',
          build_id: 'board-build',
          chip: 'rk3568',
          rknn_lite_version: '2.3.2'
        }],
        reason: '',
        solution: ''
      })
    });
  });
  await page.route(`**/api/v39/projects/${project.id}/deploy/jobs/rk-job-1/hardware-tests`, async route => {
    hardwarePost = route.request().postDataBuffer();
    await route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'rk-board-task-1',
        task_id: 'rk-board-task-1',
        status: 'QUEUED',
        phase: 'QUEUED',
        progress_percent: 0
      })
    });
  });
  await page.route(`**/api/v39/projects/${project.id}/deploy/jobs/rk-job-1/hardware-tests/report*`, async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        report_version: 1,
        status: 'passed',
        acceptance_scope: 'rknn_runtime_hardware',
        model: {file_name: 'model_rk3568.rknn', size_bytes: 1024, sha256: 'a'.repeat(64)},
        target: {chip: 'rk3568', precision: 'fp16'},
        board: {node_id: 'rk3568-board-01', rknn_lite_version: '2.3.2'},
        verification: {
          task_id: 'rk-board-task-1',
          execution_generation: 1,
          verified_at: '2026-09-19T01:02:03+00:00',
          engine: 'rknn-lite2',
          input: {file_name: 'board-test.bmp', size_bytes: 1234, sha256: 'b'.repeat(64)},
          inference_ms: 12.34,
          output_count: 3,
          output_shapes: [[1, 84, 8400]]
        },
        accuracy_verified: false,
        statement: '本报告仅证明该 RKNN 产物已在匹配 Rockchip 板卡上完成 RKNNLite Runtime 推理验证，不代表算法准确率或业务效果验收。'
      })
    });
  });
  await page.route(`**/api/v62/projects/${project.id}/tasks/rk-board-task-1`, async route => {
    taskReads += 1;
    jobVerified = true;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'rk-board-task-1',
        task_id: 'rk-board-task-1',
        status: 'SUCCEEDED',
        phase: 'FINALIZING',
        progress_percent: 100
      })
    });
  });

  await page.addInitScript(projectId => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({
      projectId,
      page: '部署转换'
    }));
  }, project.id);
  await page.goto('/');
  await expect.poll(() => page.evaluate(() => typeof window.renderDeployCenter)).toBe('function');
  await page.evaluate(async () => {
    if (window.__clInit) await window.__clInit();
    window.setPage('部署转换');
    await window.loadDeployData(true);
    window.renderDeployCenter();
  });

  const job = page.locator('.deploy-job', {hasText: 'best.pt'});
  await expect(job.getByText('RKNN 已转换，尚未完成瑞芯微实机 Runtime 验证')).toBeVisible();
  await job.getByRole('button', {name: '板端验证'}).click();
  const dialog = page.getByRole('dialog', {name: 'RKNN 板端验证'});
  await expect(dialog.getByText(/验收条件已满足/)).toBeVisible();
  await expect(dialog.getByText(/RK3568 验收板 · RKNNLite 2\.3\.2/)).toBeVisible();
  await expect(dialog.getByRole('button', {name: '开始板端验证'})).toBeEnabled();
  await dialog.locator('#rknnVerifyFile').setInputFiles({
    name: 'board-test.bmp',
    mimeType: 'image/bmp',
    buffer: bmp(64, 64)
  });
  await dialog.getByRole('button', {name: '开始板端验证'}).click();

  await expect.poll(() => taskReads).toBeGreaterThan(0);
  expect(hardwarePost).not.toBeNull();
  await expect(page.getByRole('dialog', {name: 'RKNN 板端验证'})).toHaveCount(0);
  await expect(job.getByText(/实机已验证/)).toBeVisible();
  await expect(job.getByText(/推理 12\.34 ms/)).toBeVisible();
  await expect(job.getByRole('button', {name: '板端验证'})).toHaveCount(0);
  await job.getByRole('button', {name: '验收报告'}).click();
  const reportDialog = page.getByRole('dialog', {name: 'RKNN 实机验收报告'});
  await expect(reportDialog.getByText('板端 Runtime 验收通过')).toBeVisible();
  await expect(reportDialog.getByText('rk3568-board-01')).toBeVisible();
  await expect(reportDialog.getByText('2.3.2')).toBeVisible();
  await expect(reportDialog.getByText(/不代表算法准确率/)).toBeVisible();
  await expect(reportDialog.getByRole('link', {name: '下载 JSON 报告'})).toHaveAttribute('href', /hardware-tests\/report\?download=true/);
});


test('RKNN Agent INT8 conversion submits frozen calibration selection from the UI', async ({page, request}) => {
  const project = await (await request.post('/api/projects', {data: {
    name: `RKNN-INT8-${Date.now()}`,
    labels: [{code: 'fire', display_name: '明火'}]
  }})).json();
  const algorithmId = 'algorithm-rknn-int8';
  const versionId = 'version-rknn-int8';
  let submitted = null;
  let created = false;

  await page.route(`**/api/v42/projects/${project.id}/algorithms/${algorithmId}/versions/${versionId}/deployments`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      algorithm: {id: algorithmId, name: 'RKNN INT8 算法'},
      version: {id: versionId, version_name: '20260918193000', model_name: 'best.pt', stored_path: 'models/best.pt'},
      items: created ? [{id: 'rknn-int8-job', target: 'rockchip', status: 'queued', progress: 0, message: '等待远程节点'}] : []
    })
  }));
  await page.route('**/api/v39/deploy/resources', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({items: [{
      id: 'rknn-agent-int8',
      name: 'RKNN Agent · RK3568',
      kind: 'rockchip',
      mode: 'agent',
      status: 'ready',
      targets: ['rockchip'],
      message: '检测到 1 个在线 Agent 可执行 RKNN 转换',
      supported_chips: ['rk3568', 'rk3576'],
      supported_precisions: ['fp16', 'int8'],
      agent_nodes: [{node_id: 'node-rknn', display_name: 'RKNN 转换节点'}]
    }]})
  }));
  await page.route(`**/api/v39/projects/${project.id}/deploy/jobs`, async route => {
    if (route.request().method() !== 'POST') {
      await route.continue();
      return;
    }
    submitted = route.request().postDataJSON();
    created = true;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ok: true, job: {id: 'rknn-int8-job', status: 'queued'}})
    });
  });

  await page.addInitScript(projectId => {
    localStorage.clear();
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({projectId, page: '工作台'}));
  }, project.id);
  await page.goto('/');
  await page.evaluate(async () => { if (window.__clInit) await window.__clInit(); });
  await page.evaluate(() => {
    state.datasets = [{id: 'calibration-dataset', name: 'INT8 校准集'}];
    state.datasetId = 'calibration-dataset';
  });
  await page.evaluate(([aid, vid]) => window.openVersionConvert428(aid, vid), [algorithmId, versionId]);

  const historyDialog = page.getByRole('dialog', {name: '版本转换'});
  await expect(historyDialog).toBeVisible();
  await historyDialog.getByRole('button', {name: '选择转换目标'}).click();

  const dialog = page.getByRole('dialog', {name: '新建版本转换'});
  await dialog.locator('input[name="conv428Target"][value="rockchip"]').check();
  await expect(dialog.locator('#conv428Resource')).toHaveValue('rknn-agent-int8');
  await expect(dialog.locator('#conv428Chip')).toHaveValue('rk3568');
  await expect(dialog.locator('#conv428Precision option[value="fp32"]')).toBeDisabled();
  await expect(dialog.locator('#conv428Precision option[value="int8"]')).toBeEnabled();

  await dialog.locator('#conv428Precision').selectOption('int8');
  await expect(dialog.locator('#conv428Calibration')).toBeVisible();
  await expect(dialog.locator('#conv428CalibrationDataset')).toHaveValue('calibration-dataset');
  await dialog.locator('#conv428CalibrationSplit').selectOption('val');
  await dialog.locator('#conv428CalibrationCount').fill('64');
  await dialog.getByRole('button', {name: '开始转换'}).click();

  await expect.poll(() => submitted).not.toBeNull();
  expect(submitted).toMatchObject({
    source_id: `version::${algorithmId}::${versionId}`,
    target: 'rockchip',
    resource_id: 'rknn-agent-int8',
    params: {
      precision: 'int8',
      input_size: 640,
      chip: 'rk3568'
    },
    dataset_id: 'calibration-dataset',
    calibration_split: 'val',
    calibration_count: 64
  });
});
