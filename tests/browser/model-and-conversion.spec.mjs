import {test, expect} from '@playwright/test';

// Isolated UI contract fixtures. These are not SDK compilation or hardware evidence.
const uiCatalog={
  revision:1,
  vendors:[{id:'v-atlas',name:'华为 Atlas',template_id:'atlas-atc'},{id:'v-rk',name:'瑞芯微',template_id:'rknn'},{id:'v-s',name:'算能',template_id:'tpu-mlir'}],
  templates:[{id:'atlas-atc',adapter:'ascend'},{id:'rknn',adapter:'rockchip'},{id:'tpu-mlir',adapter:'sophon'}],
  chips:[['Ascend310P3','v-atlas'],['rk3568','v-rk'],['rk3576','v-rk'],['bm1684x','v-s'],['bm1688','v-s']].map(([id,vendor_id])=>({id,vendor_id,name:id.startsWith('bm')||id.startsWith('rk')?id.toUpperCase():id,sdk_code:id,enabled:true}))
};
test.beforeEach(async({page})=>{
  await page.route('**/api/v39/deploy/catalog',route=>route.fulfill({json:uiCatalog}));
  await page.route('**/api/v39/projects/*/deploy/resolve',async route=>{
    const body=route.request().postDataJSON(),p=body.params||{};
    const context=await page.evaluate(()=>({resources:state.conv428Resources||[],defaults:state.conv428ModelDefaults||{}}));
    const resource=context.resources.find(r=>r.id===body.resource_id);
    const chips=uiCatalog.chips.filter(c=>c.vendor_id===p.local_vendor_id),chip=chips.find(c=>c.id===p.local_chip_id);
    const supported=resource?.status==='ready'&&[...(resource.supported_chips||[]),...(resource.detected_soc_versions||[])].includes(chip?.sdk_code);
    const allowed=body.target==='sophon'?['fp16']:body.target==='rockchip'?['fp16','int8']:['fp16','fp32'];
    const precision=p.precision||allowed[0],ready=!!supported&&allowed.includes(precision);
    const height=p.input_height||p.input_size||context.defaults.input_height||context.defaults.input_size||640;
    const width=p.input_width||p.input_size||context.defaults.input_width||context.defaults.input_size||640;
    await route.fulfill({json:{ready,status:ready?'convertible':'not_convertible',errors:ready?[]:['没有已检测通过的芯片合同或尚未选择目标'],
      allowed_precisions:allowed,parameter_sources:{precision:p.precision?'用户自定义':'SDK/芯片约束'},
      params:{...p,chip:chip?.sdk_code,soc_version:body.target==='ascend'?chip?.sdk_code:undefined,precision,
        input_width:width,input_height:height,batch:1,num_core:1,dynamic:false,
        preprocessing:p.preprocessing||{owner:'caller',pixel_format:'rgb',mean:[0,0,0],scale:[1/255,1/255,1/255],letterbox:true}},
      chip_options:chips.map(c=>({...c,status_label:resource?.status==='ready'?'可转换':'转换服务不可用'}))}});
  });
});


async function selectIsolatedTestProject(page, projectId) {
  await page.route('**/api/v53/bootstrap/snapshot**', async route => {
    const url = new URL(route.request().url());
    url.searchParams.set('preferred_project_id', projectId);
    await route.continue({url: url.toString()});
  });
}


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
  const annotation = await request.post(`/api/projects/${project.id}/annotations/${image.id}`, {data: {boxes: [{
    class_id: 0, label: 'fire', x1: 10, y1: 8, x2: 90, y2: 70
  }], expected_version: image.annotation_version, source_content_sha256: image.content_sha256}});
  expect(annotation.ok(), await annotation.text()).toBeTruthy();
  const configured = await request.post('/api/v35/model-configs', {data: {
    name: '浏览器默认视觉模型', provider_type: 'ollama', provider_adapter: 'ollama',
    model_kind: 'vlm', detect_url: 'http://127.0.0.1:11434', model_name: 'qwen2.5vl:3b',
    default_for_annotation: true
  }});
  expect(configured.ok()).toBeTruthy();
  const vendorAlgorithmId = 'vendor-target-algorithm';
  const vendorVersionId = 'vendor-target-version';
  await page.route(`**/api/v42/projects/${project.id}/algorithms/${vendorAlgorithmId}/versions/${vendorVersionId}/deployments`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      algorithm: {id: vendorAlgorithmId, name: '厂商转换参数'},
      version: {id: vendorVersionId, version_name: '20260924080000', model_name: 'best.pt', stored_path: '/models/best.pt'},
      items: []
    })
  }));
  await page.route('**/api/v39/deploy/resources', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({items: [
      {id:'onnx-ready', name:'Ultralytics ONNX', kind:'ultralytics', mode:'local', status:'ready', targets:['onnx'], message:'ONNX ready'},
      {id:'paddle-ready', name:'Paddle Export', kind:'paddle', mode:'local', status:'ready', targets:['paddle_inference'], message:'Paddle ready'},
      {id:'trt-ready', name:'TensorRT 4090', kind:'tensorrt', mode:'local', status:'ready', targets:['tensorrt'], message:'TensorRT ready'},
      {id:'atlas-ready', name:'Atlas CANN', kind:'ascend', mode:'local', status:'ready', targets:['ascend'], detected_soc_versions:['Ascend310P3'], message:'CANN ready'},
      {id:'rknn-ready', name:'RKNN Toolkit', kind:'rockchip', mode:'local', status:'ready', targets:['rockchip'], supported_chips:['rk3568','rk3576'], supported_precisions:['fp16','int8'], message:'RKNN ready'},
      {id:'sophon-ready', name:'TPU-MLIR', kind:'sophon', mode:'local', status:'ready', targets:['sophon'], supported_chips:['bm1684x','bm1688','cv186x'], supported_precisions:['fp16'], message:'Sophon ready'}
    ]})
  }));
  await page.addInitScript(projectId => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({projectId, page: '模型配置'}));
  }, project.id);
  await selectIsolatedTestProject(page, project.id);
  await page.goto('/');
  await expect.poll(() => page.evaluate(() => state.uiReady === true)).toBe(true);

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
  await createAiDialog.locator('#ai429LabelGrid button', {hasText:'fire'}).click();
  await expect(createAiDialog.locator('#ai429Labels')).toHaveValue('fire');
  await createAiDialog.locator('summary').filter({hasText:'高级设置'}).click();
  const reference=createAiDialog.locator('#ai429RefGrid button').first();
  await expect(reference).toBeVisible();
  await reference.click();
  await expect.poll(()=>page.evaluate(()=>state.ai429RefSelected.size)).toBe(1);
  await expect(createAiDialog.locator('#ai429Labels')).toHaveValue('fire');
  await expect(createAiDialog.locator('#ai429ReferenceCount')).toContainText('仅作视觉示例，不改变任务标签');
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
  const candidateDialog = page.getByRole('dialog', {name: 'AI标注审核工作台 · 待确认'});
  await expect(candidateDialog.getByText(/不会自动写入正式标注/)).toBeVisible();
  await expect(candidateDialog.locator('.data412-box')).toBeVisible();
  await expect(candidateDialog.getByRole('button', {name: '全部接受'})).toBeVisible();
  await candidateDialog.getByRole('button', {name: '暂不处理'}).click();

  await page.evaluate(([aid, vid]) => window.openVersionConvert428(aid, vid), [vendorAlgorithmId, vendorVersionId]);
  const versionDialog = page.getByRole('dialog', {name: '版本转换'});
  await expect(versionDialog).toBeVisible();
  await versionDialog.getByRole('button', {name: '选择转换目标'}).click();
  const conversionDialog = page.getByRole('dialog', {name: '新建版本转换'});
  await expect(conversionDialog).toBeVisible();
  await expect(conversionDialog.locator('input[name="conv428Target"]')).toHaveCount(6);

  await conversionDialog.locator('input[name="conv428Target"][value="onnx"]').check();
  await expect(conversionDialog.locator('#conv428Opset')).toBeVisible();
  await expect(conversionDialog.locator('#conv428Resource')).toContainText('Ultralytics ONNX');

  await conversionDialog.locator('input[name="conv428Target"][value="paddle_inference"]').check();
  await expect(conversionDialog.locator('#conv428Resource')).toContainText('Paddle Export');

  await conversionDialog.locator('input[name="conv428Target"][value="ascend"]').check();
  await expect(conversionDialog.locator('#conv428Chip')).toHaveValue('Ascend310P3');

  await conversionDialog.locator('input[name="conv428Target"][value="rockchip"]').check();
  await expect(conversionDialog.locator('#conv428Chip')).toHaveValue('');
  await expect(conversionDialog.locator('[data-convert-submit]')).toBeDisabled();
  await conversionDialog.locator('#conv428Chip').selectOption('rk3568');
  await expect(conversionDialog.locator('.convert428-resource-status')).toContainText('RKNN Toolkit');

  await conversionDialog.locator('input[name="conv428Target"][value="tensorrt"]').check();
  await expect(conversionDialog.locator('#conv428TargetEnvironment')).toBeVisible();
  await expect(conversionDialog.locator('#conv428Precision option[value="bf16"]')).toBeDisabled();

  await conversionDialog.locator('input[name="conv428Target"][value="sophon"]').check();
  await expect(conversionDialog.locator('#conv428Precision option[value="bf16"]')).toBeDisabled();
  await expect(conversionDialog.locator('#conv428Precision option[value="int8"]')).toBeDisabled();
  await expect(conversionDialog.locator('#conv428Chip option')).toHaveText(['请选择目标芯片',/BM1684X.*可转换/,/BM1688.*可转换/]);
  await conversionDialog.locator('#conv428Chip').selectOption('bm1688');
  await expect(conversionDialog.locator('#conv428Chip')).toHaveValue('bm1688');
  await conversionDialog.locator('#conv428Chip').selectOption('bm1684x');
  await expect(conversionDialog.locator('#conv428Width')).toBeVisible();
  await expect(conversionDialog.locator('#conv428Height')).toBeVisible();
  await expect(conversionDialog.locator('#conv428SophonBatch')).toHaveValue('1');
  await expect(conversionDialog.locator('#conv428Preprocess')).toBeVisible();
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
  await selectIsolatedTestProject(page, project.id);
  await page.goto('/');
  await expect.poll(() => page.evaluate(() => state.uiReady === true)).toBe(true);
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
  await expect(historyDialog).toBeVisible();
});

test('module graph is cache-busted and exposes platform helpers', async ({page, request}) => {
  const main = await request.get('/static/main.mjs');
  expect(await main.text()).toMatch(/\.\/modules\/materials\.js\?v=\d+/);

  await page.goto('/');
  await expect.poll(() => page.evaluate(() => state.uiReady === true)).toBe(true);
  await expect.poll(() => page.evaluate(() => typeof window.PlatformCore?.materials?.labelDisplay)).toBe('function');
});


test('deployment resource editor exposes service-node Agent for RKNN', async ({page, request}) => {
  const project = await (await request.post('/api/projects', {data: {
    name: `RKNN-Agent-资源-${Date.now()}`,
    labels: []
  }})).json();
  const algorithmId = 'algorithm-rknn-agent-resource';
  const versionId = 'version-rknn-agent-resource';

  await page.route(`**/api/v42/projects/${project.id}/algorithms/${algorithmId}/versions/${versionId}/deployments`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      algorithm: {id: algorithmId, name: 'RKNN Agent 算法'},
      version: {id: versionId, version_name: '20260924070000', model_name: 'best.pt', stored_path: '/models/best.pt'},
      items: []
    })
  }));
  await page.route('**/api/v39/deploy/resources', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({items: [{
      id: 'rknn-agent-ui',
      name: 'RKNN 服务节点 Agent',
      kind: 'rockchip',
      mode: 'agent',
      status: 'ready',
      targets: ['rockchip'],
      supported_chips: ['rk3568', 'rk3576'],
      supported_precisions: ['fp16', 'int8'],
      agent_nodes: [{node_id: 'rknn-agent-01', display_name: 'RKNN Agent 01'}]
    }]})
  }));

  await selectIsolatedTestProject(page, project.id);
  await page.addInitScript(() => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({page: '算法列表'}));
  });
  await page.goto('/');
  await expect.poll(() => page.evaluate(() => state.uiReady === true)).toBe(true);
  await expect.poll(
    () => page.evaluate(() => typeof state !== 'undefined' && state.uiReady === true && typeof window.openDeployResourceModal === 'function'),
    {timeout: 20_000},
  ).toBe(true);

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

  // The retired deployment-center page is intentionally not restored. Verify the
  // same Agent and RKNN chip contract through the canonical version-conversion owner.
  await page.evaluate(([aid, vid]) => window.openVersionConvert428(aid, vid), [algorithmId, versionId]);
  const historyDialog = page.getByRole('dialog', {name: '版本转换'});
  await expect(historyDialog).toBeVisible();
  await historyDialog.getByRole('button', {name: '选择转换目标'}).click();

  const createDialog = page.getByRole('dialog', {name: '新建版本转换'});
  await expect(createDialog).toBeVisible();
  await createDialog.locator('input[name="conv428Target"][value="rockchip"]').check();
  await expect(createDialog.locator('#conv428Resource')).toHaveValue('rknn-agent-ui');
  await expect(createDialog.locator('#conv428Resource')).toContainText('RKNN 服务节点 Agent');
  await expect(createDialog.locator('#conv428Chip')).toHaveValue('');
  await expect(createDialog.locator('[data-convert-submit]')).toBeDisabled();
  await createDialog.locator('#conv428Chip').selectOption('rk3568');
  expect(await createDialog.locator('#conv428Chip').evaluate(node => node.tagName)).toBe('SELECT');
  await expect(createDialog.locator('#conv428Chip option')).toHaveText(['请选择目标芯片',/RK3568.*可转换/,/RK3576.*可转换/]);
  await expect(createDialog.locator('.convert428-resource-status')).toContainText('RK3568');
  await expect(createDialog.locator('.convert428-resource-status')).toContainText('RK3576');
});

test('RKNN converted_unverified job exposes board verification and upgrades after real task success', async ({page, request}) => {
  const project = await (await request.post('/api/projects', {data: {
    name: `RKNN板端验证-${Date.now()}`,
    labels: []
  }})).json();
  const algorithmId = 'rknn-board-algorithm';
  const versionId = 'rknn-board-version';
  let hardwarePost = null;
  let taskReads = 0;
  let jobVerified = false;
  let releaseHardwareSuccess;
  const hardwareSuccessGate = new Promise(resolve => { releaseHardwareSuccess = resolve; });

  await page.route(`**/api/v42/projects/${project.id}/algorithms/${algorithmId}/versions/${versionId}/deployments`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      algorithm: {id: algorithmId, name: 'RKNN 板端算法'},
      version: {id: versionId, version_name: '20260924090000', model_name: 'best.pt', stored_path: '/models/best.pt'},
      items: [{
        id: 'rk-job-1',
        source_name: 'best.pt',
        target: 'rockchip',
        target_name: '瑞芯微 RKNN',
        status: 'done',
        stage: jobVerified ? 'hardware_verified' : 'converted_unverified',
        progress: 100,
        conversion_status: jobVerified ? 'hardware_verified' : 'converted_unverified',
        validation_status: jobVerified ? 'hardware_verified' : 'converted_unverified',
        hardware_verified: jobVerified,
        runtime_verified: jobVerified,
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
        resource_name: 'RKNN Agent',
        outputs: [{name:'model_rk3568.rknn', size_mb:1, exists:true, download_url:'/fake/model.rknn'}],
        package_url: '/fake/deploy.zip'
      }]
    })
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
    const done = taskReads >= 2;
    if (done) {
      await hardwareSuccessGate;
      jobVerified = true;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'rk-board-task-1',
        task_id: 'rk-board-task-1',
        status: done ? 'SUCCEEDED' : 'RUNNING',
        phase: done ? 'FINALIZING' : 'RKNN_LITE_INFERENCE',
        progress_percent: done ? 100 : 45,
        worker_id: 'agent:rk3568-board-01'
      })
    });
  });

  await selectIsolatedTestProject(page, project.id);
  await page.addInitScript(() => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({
      page: '算法列表'
    }));
  });
  await page.goto('/');
  await expect.poll(() => page.evaluate(() => state.uiReady === true)).toBe(true);
  await expect.poll(async () => page.evaluate(expectedProjectId => ({
    uiReady: state.uiReady === true,
    projectId: String(state.project?.id || ''),
    opener: typeof window.openVersionConvert428,
    expectedProjectId: String(expectedProjectId),
  }), project.id)).toEqual({
    uiReady: true,
    projectId: String(project.id),
    opener: 'function',
    expectedProjectId: String(project.id),
  });
  await page.evaluate(([aid, vid]) => window.openVersionConvert428(aid, vid), [algorithmId, versionId]);

  const historyDialog = page.getByRole('dialog', {name: '版本转换'});
  await expect(historyDialog).toBeVisible();
  const job = historyDialog.locator('.convert428-job', {hasText: '瑞芯微 RKNN'});
  await expect(job.getByText('转换完成 · 待板端验证')).toBeVisible();
  await expect(job.getByText(/RKNN 文件已生成/)).toBeVisible();
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

  const live = dialog.locator('[data-rknn-verify-live]');
  await expect(live).toBeVisible();
  await page.evaluate(() => {
    window.__rknnVerifyStableShell = document.querySelector('[data-rknn-verify-live]');
    window.__rknnVerifyStableBar = document.querySelector('[data-rknn-verify-bar]');
  });
  await expect.poll(() => taskReads).toBeGreaterThan(0);
  await expect(live).toContainText('45%', {timeout: 5_000});
  await expect(live.locator('[data-rknn-verify-bar]')).toHaveAttribute('data-progress', '45.00');
  expect(await page.evaluate(() => ({
    shell: window.__rknnVerifyStableShell === document.querySelector('[data-rknn-verify-live]'),
    bar: window.__rknnVerifyStableBar === document.querySelector('[data-rknn-verify-bar]'),
  }))).toEqual({shell:true, bar:true});
  releaseHardwareSuccess();
  await expect.poll(() => taskReads, {timeout: 5_000}).toBeGreaterThanOrEqual(2);
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
      items: created ? [{id: 'rknn-int8-job', target: 'rockchip', target_name: '瑞芯微 RKNN', status: 'running', stage: 'RKNN 编译中', progress: 37, message: '正在生成 RKNN 产物', params: {chip: 'rk3568', precision: 'int8'}, resource_name: 'RKNN Agent · RK3568', outputs: []}] : []
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

  await selectIsolatedTestProject(page, project.id);
  await page.addInitScript(() => {
    localStorage.clear();
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({page: '工作台'}));
  });
  await page.goto('/');
  await expect.poll(() => page.evaluate(() => state.uiReady === true)).toBe(true);
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
  await expect(dialog.locator('#conv428Chip')).toHaveValue('');
  await expect(dialog.locator('[data-convert-submit]')).toBeDisabled();
  await dialog.locator('#conv428Chip').selectOption('rk3568');
  await expect(dialog.locator('#conv428Precision option[value="fp32"]')).toBeDisabled();
  await expect(dialog.locator('#conv428Precision option[value="int8"]')).toBeEnabled();

  await dialog.locator('#conv428Precision').selectOption('int8');
  await expect(dialog.locator('#conv428Calibration')).toBeVisible();
  await expect(dialog.locator('#conv428CalibrationDataset')).toHaveValue('calibration-dataset');
  await dialog.locator('#conv428CalibrationSplit').selectOption('val');
  await dialog.locator('#conv428CalibrationCount').fill('64');
  await dialog.getByRole('button', {name: '开始转换'}).click();

  await expect.poll(() => submitted).not.toBeNull();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole('dialog', {name: '版本转换'})).toHaveCount(1);
  await expect(historyDialog.locator('[data-conversion-percent]')).toContainText('37%');
  await expect(historyDialog.locator('[data-conversion-message]')).toContainText('正在生成 RKNN 产物');
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


test('Sophon submits explicit rectangular FP16 parameters and keeps BMODEL hardware validation pending', async ({page,request}) => {
  const project=await (await request.post('/api/projects',{data:{name:`Sophon UI-${Date.now()}`,labels:[{code:'smoke'}]}})).json();
  let ready=false,submitted=null,created=false;
  await selectIsolatedTestProject(page,project.id);
  await page.route('**/api/v39/deploy/resources',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({items:[{
    id:'sophon-remote',name:'独立 TPU-MLIR',kind:'sophon',mode:'remote',status:ready?'ready':'missing',
    targets:ready?['sophon']:[],supported_chips:ready?['bm1684x','bm1688']:[],supported_precisions:ready?['fp16']:[],
    version:ready?'v1.30.2-20260831':'',message:ready?'TPU-MLIR自检通过':'TPU_MLIR_NOT_FOUND：model_deploy.py缺失'}]})}));
  await page.route(`**/api/v42/projects/${project.id}/algorithms/sophon-a/versions/v1/deployments`,route=>route.fulfill({
    status:200,contentType:'application/json',body:JSON.stringify({algorithm:{id:'sophon-a',name:'烟火算法'},
      version:{id:'v1',version_name:'v1',model_name:'best.pt',stored_path:'/isolated/best.pt',
        conversion_defaults:{input_size:800,input_width:800,input_height:800,training_precision:'fp32'}},
      items:created?[{id:'sophon-job',target:'sophon',target_name:'算能 Sophon',resource_name:'独立 TPU-MLIR',
        status:'blocked_by_hardware',task_status:'BLOCKED_BY_HARDWARE',validation_status:'converted_unverified',
        task_id:'sophon-job',progress:100,stage:'等待目标硬件验证',message:'BMODEL已生成，尚未实机验证',
        params:{chip:'bm1688',precision:'fp16',input_width:640,input_height:384},
        outputs:[{name:'model_bm1688_fp16.bmodel',available:true,path:'/isolated/model.bmodel',size_bytes:123,download_url:'/isolated/model.bmodel'}]}]:[]})}));
  await page.route(`**/api/v39/projects/${project.id}/deploy/jobs`,async route=>{
    submitted=route.request().postDataJSON();created=true;
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({ok:true,job:{id:'sophon-job',task_status:'QUEUED'}})});
  });
  await page.goto('/');
  await expect.poll(()=>page.evaluate(()=>state.uiReady===true)).toBe(true);
  await page.evaluate(()=>window.openNewConvert428('sophon-a','v1'));
  const dialog=page.getByRole('dialog',{name:'新建版本转换'});
  await dialog.locator('[name="conv428Target"][value="sophon"]').check();
  await expect(dialog.locator('#conv428Warn')).toContainText('没有已检测通过');
  await expect(dialog.locator('[data-convert-submit]')).toBeDisabled();
  await expect(dialog.locator('#conv428ResourceStatus')).toContainText('model_deploy.py缺失');
  ready=true;await dialog.getByRole('button',{name:'刷新资源',exact:true}).click();
  await expect(dialog.locator('#conv428ResourceStatus')).toContainText('v1.30.2-20260831');
  await expect(dialog.locator('#conv428Chip option')).toHaveText(['请选择目标芯片',/BM1684X.*可转换/,/BM1688.*可转换/]);
  await expect(dialog.locator('#conv428Width')).toHaveValue('800');
  await expect(dialog.locator('#conv428Height')).toHaveValue('800');
  await dialog.locator('#conv428Chip').selectOption('bm1688');
  await dialog.locator('#conv428Width').fill('640');await dialog.locator('#conv428Height').fill('384');await dialog.locator('#conv428Height').blur();
  await expect(dialog.locator('[data-convert-submit]')).toBeEnabled();
  await expect(dialog.locator('#conv428Precision')).toHaveValue('fp16');
  await expect(dialog.locator('#conv428Precision option[value="int8"]')).toBeDisabled();
  await expect(dialog.locator('#conv428Calibration')).toBeHidden();
  await dialog.getByRole('button',{name:'开始转换',exact:true}).click();
  await expect.poll(()=>submitted).not.toBeNull();
  expect(submitted).toMatchObject({source_id:'version::sophon-a::v1',target:'sophon',resource_id:'sophon-remote',
    params:{chip:'bm1688',precision:'fp16',input_width:640,input_height:384,batch:1,num_core:1,dynamic:false,
      preprocessing:{owner:'caller',pixel_format:'rgb',mean:[0,0,0],letterbox:true}}});
  expect(submitted.params).not.toHaveProperty('input_size');
  expect(submitted.params.preprocessing.scale).toHaveLength(3);
  const history=page.getByRole('dialog',{name:'版本转换'});
  await expect(history).toContainText('model_bm1688_fp16.bmodel');
  await expect(history).toContainText('尚未实机验证');
});

test('local two-vendor dictionary selects BM1684 FP32 through the existing conversion dialog',async({page,request},testInfo)=>{
  const current=await (await request.get('/api/v39/deploy/catalog')).json();
  const data={vendors:[{id:'local-s',name:'算能',template_id:'tpu-mlir',enabled:true},{id:'local-r',name:'瑞芯微',template_id:'rknn',enabled:true}],
    chips:[{id:'chip-84',vendor_id:'local-s',name:'BM1684',code:'local84',sdk_code:'bm1684',constraint_id:'tpu-mlir-1.30.2',enabled:true},
           {id:'chip-88',vendor_id:'local-s',name:'BM1688',code:'local88',sdk_code:'bm1688',constraint_id:'tpu-mlir-1.30.2',enabled:true}],
    expected_revision:current.revision};
  const saved=await request.put('/api/v39/deploy/catalog',{data});
  expect(saved.ok(),await saved.text()).toBeTruthy();
  await page.unroute('**/api/v39/deploy/catalog');
  const project=await (await request.post('/api/projects',{data:{name:'动态BM1684-'+Date.now(),labels:[{code:'fire'}]}})).json();
  await selectIsolatedTestProject(page,project.id);
  await page.route('**/api/v39/deploy/resources',r=>r.fulfill({json:{items:[{id:'sdk',kind:'sophon',name:'独立SDK',mode:'remote',status:'ready',targets:['sophon'],version:'v1.30.2-20260831',supported_chips:['bm1684','bm1688'],supported_precisions:['fp16','fp32']}]}}));
  await page.route('**/api/v42/projects/*/algorithms/dynamic-a/versions/v1/deployments',r=>r.fulfill({json:{algorithm:{id:'dynamic-a',name:'动态转换'},version:{id:'v1',model_name:'best.pt',stored_path:'/isolated/best.pt',conversion_defaults:{input_size:800,input_width:800,input_height:800,training_precision:'fp32'}},items:[]}}));
  await page.route('**/api/v39/projects/*/deploy/resolve',async route=>{
    const p=route.request().postDataJSON().params,chip=data.chips.find(c=>c.id===p.local_chip_id),precision=chip?.sdk_code==='bm1684'?'fp32':'fp16';
    await route.fulfill({json:{ready:!!chip&&(!p.precision||p.precision===precision),errors:chip?[]:['请选择目标芯片'],allowed_precisions:[precision],
      template:current.templates.find(t=>t.id==='tpu-mlir'),parameter_sources:{precision:'SDK/芯片约束',input_shape:'训练成果继承'},
      chip_options:data.chips.map(c=>({...c,status_label:'可转换'})),
      params:{...p,chip:chip?.sdk_code,precision,batch:1,num_core:1,dynamic:false,input_width:p.input_width||800,input_height:p.input_height||800,
        template_id:'tpu-mlir',template_version:1,preprocessing:{owner:'caller',pixel_format:'rgb',mean:[0,0,0],scale:[1/255,1/255,1/255],letterbox:true}}}});
  });
  let submitted;
  await page.route('**/api/v39/projects/*/deploy/jobs',async route=>{submitted=route.request().postDataJSON();await route.fulfill({json:{ok:true,job:{id:'isolated'}}})});
  await page.goto('/');await expect.poll(()=>page.evaluate(()=>state.uiReady===true)).toBe(true);
  await page.evaluate(()=>window.openConversionCatalog428());
  const editor=page.getByRole('dialog',{name:'厂商与芯片字典'});
  await expect(editor.locator('[data-catalog-vendor]')).toHaveCount(2);
  await expect(editor.locator('[data-catalog-chip]')).toHaveCount(2);
  await editor.getByRole('button',{name:'取消',exact:true}).click();
  await page.evaluate(()=>window.openNewConvert428('dynamic-a','v1'));
  const dialog=page.getByRole('dialog',{name:'新建版本转换'});
  await expect(dialog.locator('[name="conv428Target"]')).toHaveCount(5);
  await dialog.locator('[data-vendor-id="local-s"]').check();
  await expect(dialog.locator('#conv428Chip')).toHaveValue('');
  await expect(dialog.locator('[data-convert-submit]')).toBeDisabled();
  await dialog.locator('#conv428Chip').selectOption('chip-84');
  await expect(dialog.locator('#conv428Precision')).toHaveValue('fp32');
  await expect(dialog.locator('#conv428Precision option[value="fp16"]')).toBeDisabled();
  await expect(dialog.locator('#conv428Warn')).toContainText('SDK/芯片约束');
  await dialog.locator('#conv428Width').fill('640');await dialog.locator('#conv428Height').fill('384');await dialog.locator('#conv428Height').blur();
  await expect(dialog.locator('[data-convert-submit]')).toBeEnabled();
  await expect(dialog.locator('#conv428OnnxFields')).toBeHidden();
  await expect(dialog.locator('#conv428TensorRtFields')).toBeHidden();
  await page.screenshot({path:testInfo.outputPath('dynamic-bm1684-ui.png'),fullPage:false});
  await dialog.getByRole('button',{name:'开始转换',exact:true}).click();
  await expect.poll(()=>submitted).toBeTruthy();
  expect(submitted.params).toMatchObject({local_vendor_id:'local-s',local_chip_id:'chip-84',chip:'bm1684',precision:'fp32',input_width:640,input_height:384,batch:1});
});
