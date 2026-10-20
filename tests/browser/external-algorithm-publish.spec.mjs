import {test, expect} from '@playwright/test';

async function selectIsolatedTestProject(page, projectId) {
  await page.route('**/api/v53/bootstrap/snapshot**', async route => {
    const url = new URL(route.request().url());
    url.searchParams.set('preferred_project_id', projectId);
    await route.continue({url: url.toString()});
  });
}

for(const reason of ['identity','optional']) test(`changlian publish respects core identity and optional metadata: ${reason}`, async ({page, request}) => {
  const project = await (await request.post('/api/projects', {data: {
    name: `畅联云发布预检-${Date.now()}`,
    labels: [{code: 'smoke', display_name: '烟雾'}],
  }})).json();
  const created = await (await request.post(`/api/v12/projects/${project.id}/algorithms`, {data: {
    name: '抽烟检测',
    industry: '测试',
    algorithm_type: 'yolo_ultralytics',
    remark: '',
  }})).json();
  const algorithmId = created.algorithm.id;
  const versionId = 'v-stale-analysis';
  let statusReads = 0;
  let publishWrites = 0;
  let releasePublish;
  const publishGate=new Promise(resolve=>{releasePublish=resolve;});

  await page.route('**/api/v64/external-publish/projects/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/publish')) {
      publishWrites += 1;
      if(reason==='optional')await publishGate;
      return route.fulfill({
        status: reason==='optional'?200:500,
        contentType: 'application/json',
        body: JSON.stringify(reason==='optional'?{ok:true,publication:{status:'PUBLISHED'}}:{detail:'publish must not be called'}),
      });
    }
    statusReads += 1;
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        algorithm: {id: algorithmId, name: '抽烟检测', external_product_id: 'product-1'},
        version: {id: versionId, version_name: '20260919233000', external_publish_status: ''},
        publication: null,
        artifacts: reason==='optional'?[
          {target:'original',file_name:'best.pt',sync_status:publishWrites?'SYNCED':'PENDING',metadata_complete:false,metadata_sync_status:'PENDING',metadata_note:'部分扩展信息未提供：yoloVersion、tags'},
          {target:'rockchip',file_name:'model.rknn',remote_registered:true,sync_status:'SYNCED',compute_platform_id:'rk-child',mapped_chip_code:'RK3576',metadata_sync_status:'PENDING',
            size_bytes:123,sha256:'a'.repeat(64),metadata:{image_width:640,image_height:384,yolo_version:'YOLOv11s',tags:['smoke','fire']}},
        ]:[],
        discovered: [{target: 'rockchip', file_name: 'model.rknn', publish_mapping_status: 'mapped'}],
        mapped_artifact_count: 1,
        blocked_artifact_count: 0,
        ignored_artifact_count: 0,
        transport_ready: true,
        transport_issues: [],
        identity_ready: reason==='optional',
        identity_issues: [{
          code: 'EXTERNAL_VERSION_ANALYSIS_STALE',
          message: '该训练版本绑定的畅联云分析方式已失效',
          detail: 'analysis-old',
          solution: '请立即同步并核对分析方式',
        }],
        publish_ready: reason==='optional',
        conversion_active: false,
      }),
    });
  });

  await selectIsolatedTestProject(page, project.id);
  await page.addInitScript(() => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({page: '算法列表'}));
  });
  await page.goto('/');
  await expect.poll(async () => page.evaluate(() => state.uiReady === true)).toBe(true);
  await expect.poll(async () => page.evaluate(() => typeof window.ExternalAlgorithmPublishRuntime?.publishVersion))
    .toBe('function');

  await page.getByRole('button', {name: /算法列表/}).click();
  await expect(page.locator('#alg412List')).toBeVisible();
  await page.evaluate(({algorithmId, versionId}) => {
    const asset = (state.algorithms || []).find(row => String(row.id) === String(algorithmId));
    if (!asset) throw new Error('algorithm missing from canonical state');
    Object.assign(asset, {
      source_type: 'EXTERNAL',
      provider_type: 'CHANG_LIAN',
      source_name: '新畅联',
      external_product_id: 'product-1',
      external_analysis_id: 'analysis-current',
      external_analysis_ids: ['analysis-current'],
      external_analyses: [{analysis_id: 'analysis-current', analysis_name: '视觉智能分析'}],
      external_active: true,
      versions: [{
        id: versionId,
        version_name: '20260919233000',
        training_status: 'SUCCEEDED',
        artifact_verified: true,
        trainable: true,
        model_name: 'best.pt',
        stored_path: '/models/best.pt',
        external_analysis_id: 'analysis-old',
      }],
      current_version_id: versionId,
    });
    state.alg428Expanded = state.alg428Expanded || {};
    state.alg428Expanded[algorithmId] = true;
    window.renderAlg412?.();
    window.AlgorithmListRuntime?.runDecorators?.();
  }, {algorithmId, versionId});

  const card = page.locator('.alg428-card', {hasText: '抽烟检测'});
  await expect(card).toBeVisible();
  const versionRow = card.locator('.alg428-version-row', {hasText: '20260919233000'});
  await expect(versionRow).toBeVisible();
  const publishButton = versionRow.locator('[data-external-publish-action]');
  await expect(publishButton).toBeVisible();
  await expect(publishButton).toHaveText('发布');

  await publishButton.click();

  if(reason==='optional'){
    await expect.poll(()=>publishWrites).toBe(1);
    const details=versionRow.locator('[data-weight-publication-details]');
    await expect(details).toBeVisible();
    for(const text of ['部分扩展信息未提供：yoloVersion、tags','RK3576','rk-child','640','384','YOLOv11s','123','a'.repeat(64),'smoke, fire','同步成功'])
      await expect(details).toContainText(text);
    await expect(details).not.toContainText('阻断发布');
    releasePublish();
  }

  await expect.poll(() => statusReads).toBe(reason==='identity'?1:2);
  await expect.poll(() => publishWrites).toBe(reason==='identity'?0:1);
  if(reason==='identity'){
    await expect.poll(() => publishWrites).toBe(0);
    await expect(page.getByText(/分析方式已失效/)).toBeVisible();
  }
  else{
    await expect(page.locator('#toast')).toContainText('模型版本和转换产物已同步到新畅联');
  }
});


test('changlian manual publish succeeds through the canonical algorithm version action', async ({page, request}) => {
  const project = await (await request.post('/api/projects', {data: {
    name: `畅联云发布成功-${Date.now()}`,
    labels: [{code: 'smoke', display_name: '烟雾'}],
  }})).json();
  const created = await (await request.post(`/api/v12/projects/${project.id}/algorithms`, {data: {
    name: '抽烟检测发布成功',
    industry: '测试',
    algorithm_type: 'yolo_ultralytics',
    remark: '',
  }})).json();
  const algorithmId = created.algorithm.id;
  const versionId = 'v-publish-ready';
  let statusReads = 0;
  let publishWrites = 0;

  await page.route('**/api/v64/external-publish/projects/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/publish')) {
      publishWrites += 1;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ok: true, published: 1}),
      });
    }
    statusReads += 1;
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        algorithm: {id: algorithmId, name: '抽烟检测发布成功', external_product_id: 'product-ready'},
        version: {id: versionId, version_name: '20260924073000', external_publish_status: ''},
        publication: null,
        artifacts: [{target: 'original', file_name: 'best.pt'}],
        discovered: [{target: 'original', file_name: 'best.pt', publish_mapping_status: 'mapped'}],
        mapped_artifact_count: 1,
        blocked_artifact_count: 0,
        ignored_artifact_count: 0,
        transport_ready: true,
        transport_issues: [],
        identity_ready: true,
        identity_issues: [],
        publish_ready: true,
        conversion_active: false,
      }),
    });
  });

  await selectIsolatedTestProject(page, project.id);
  await page.addInitScript(() => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({page: '算法列表'}));
  });
  await page.goto('/');
  await expect.poll(async () => page.evaluate(() => state.uiReady === true)).toBe(true);
  await expect.poll(async () => page.evaluate(() => typeof window.ExternalAlgorithmPublishRuntime?.publishVersion))
    .toBe('function');

  await page.getByRole('button', {name: /算法列表/}).click();
  await expect(page.locator('#alg412List')).toBeVisible();
  await page.evaluate(({algorithmId, versionId}) => {
    const asset = (state.algorithms || []).find(row => String(row.id) === String(algorithmId));
    if (!asset) throw new Error('algorithm missing from canonical state');
    Object.assign(asset, {
      source_type: 'EXTERNAL',
      provider_type: 'CHANG_LIAN',
      source_name: '新畅联',
      external_product_id: 'product-ready',
      external_analysis_id: 'analysis-ready',
      external_analysis_ids: ['analysis-ready'],
      external_analyses: [{analysis_id: 'analysis-ready', analysis_name: '视觉智能分析'}],
      external_active: true,
      versions: [{
        id: versionId,
        version_name: '20260924073000',
        training_status: 'SUCCEEDED',
        artifact_verified: true,
        trainable: true,
        model_name: 'best.pt',
        stored_path: '/models/best.pt',
        external_analysis_id: 'analysis-ready',
      }],
      current_version_id: versionId,
    });
    state.alg428Expanded = state.alg428Expanded || {};
    state.alg428Expanded[algorithmId] = true;
    window.renderAlg412?.();
  }, {algorithmId, versionId});

  const card = page.locator('.alg428-card', {hasText: '抽烟检测发布成功'});
  const versionRow = card.locator('.alg428-version-row', {hasText: '20260924073000'});
  const publishButton = versionRow.locator('[data-external-publish-action]');
  await expect(publishButton).toBeVisible();
  await expect(publishButton).toHaveText('发布');

  await publishButton.click();

  await expect.poll(() => statusReads).toBe(2);
  await expect.poll(() => publishWrites).toBe(1);
  await expect(page.locator('#toast')).toContainText('模型版本和转换产物已同步到新畅联');
});
