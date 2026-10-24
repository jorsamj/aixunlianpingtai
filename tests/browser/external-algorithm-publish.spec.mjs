import {test, expect} from '@playwright/test';

async function selectIsolatedTestProject(page, projectId) {
  await page.route('**/api/v53/bootstrap/snapshot**', async route => {
    const url = new URL(route.request().url());
    url.searchParams.set('preferred_project_id', projectId);
    await route.continue({url: url.toString()});
  });
}

for(const reason of ['identity','optional','review']) test(`changlian publish respects core identity and optional metadata: ${reason}`, async ({page, request}) => {
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
  let selections = [];
  let releasePublish;
  const publishGate=new Promise(resolve=>{releasePublish=resolve;});

  await page.route('**/api/v64/external-publish/projects/**', async route => {
    const url = new URL(route.request().url());
    if(url.pathname.endsWith('/selection')){
      selections.push(route.request().postDataJSON());
      return route.fulfill({status:410,json:{ok:false,code:'EXTERNAL_WEIGHT_AUTOMATIC_SELECTION'}});
    }
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
        project_id:project.id,
        algorithm: {id: algorithmId, name: '抽烟检测', external_product_id: 'product-1'},
        version: {id: versionId, version_name: '20260919233000', external_publish_status: ''},
        publication: reason==='review'?{status:'PARTIAL'}:null,
        weight_delivery_status:reason==='review'?'PARTIAL':undefined,
        artifacts: reason==='review'?[
          {artifact_id:'old-artifact',target:'sophon',file_name:'same.bmodel',external_weight_id:'old-weight',sync_status:'SYNCED',storage_status:'UPLOADED',compute_platform_id:'parent',chip_code:'BM1684X',sha256:'a'.repeat(64)},
          {artifact_id:'new-artifact',target:'sophon',file_name:'same.bmodel',sync_status:'UNKNOWN',storage_status:'UPLOADED',chip_code:'BM1684X',sha256:'b'.repeat(64),review_required:true,requested_artifact_id:selections.length?'new-artifact':'',recovery_plan:{old_weight_id:'old-weight',target_compute_platform_id:'child',reason:'同一芯片存在多个Weight ID',suggested_operation:'READ_ONLY_RECOVERY'}}
        ]:reason==='optional'?[
          {target:'original',file_name:'best.pt',sync_status:publishWrites?'SYNCED':'PENDING',metadata_complete:false,metadata_sync_status:'PENDING',metadata_note:'部分扩展信息未提供：yoloVersion、tags'},
          {target:'rockchip',file_name:'model.rknn',remote_registered:true,external_weight_id:'current-rk-weight',delivery_role:'AUTOMATIC_CURRENT',remote_identity_status:'READ_BACK',sync_status:'SYNCED',compute_platform_id:'rk-child',mapped_chip_code:'RK3576',metadata_sync_status:'PENDING',
            frozen_tags:['smoke','fire'],local_tags:['smoke','fire'],prepared_tags:['smoke','fire'],confirmed_tags:null,remote_tags_status:'NOT_RETURNED',size_bytes:123,sha256:'a'.repeat(64),metadata:{image_width:640,image_height:384,yolo_version:'YOLOv11s',tags:['smoke','fire']}},
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

  if(reason==='review'){
    const details=versionRow.locator('[data-weight-publication-details]');
    await expect(details).toContainText('Version PARTIAL / Weight PARTIAL');
    for(const text of ['old-weight','UNKNOWN','UPLOADED','child','同一芯片存在多个Weight ID','远端身份未读回验证','管理员'])await expect(details).toContainText(text);
    await expect(details.locator('[data-weight-select]')).toHaveCount(0);
    expect(selections).toHaveLength(0);expect(publishWrites).toBe(0);expect(statusReads).toBe(1);
    return;
  }

  if(reason==='optional'){
    await expect.poll(()=>publishWrites).toBe(1);
    const details=versionRow.locator('[data-weight-publication-details]');
    await expect(details).toBeVisible();
    for(const text of ['部分扩展信息未提供：yoloVersion、tags','RK3576','rk-child','640','384','YOLOv11s','123','a'.repeat(64),'smoke, fire','同步成功','自动当前交付','远端读回已确认','current-rk-weight'])
      await expect(details).toContainText(text);
    for(const text of ['冻结类别','本地类别','准备提交','已确认提交','远端未返回 tags','标签补齐待处理'])await expect(details).toContainText(text);
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


test('stable vendor mapping uses formal tab, preserves drafts and locks returning panels during one save', async ({page}) => {
  let writes=0, releaseSave, startedSave, failSave=false, rollbackSave=false;
  const started=new Promise(resolve=>startedSave=resolve);
  let config={mapping_history:[{revision:2,target_mappings:{original:{compute_platform_id:'generic',enabled:true}}}],mapping_revision:3,target_mappings:{original:{compute_platform_id:'generic',enabled:true},rockchip:{compute_platform_id:'legacy',chip_mappings:{RK3568:'legacy-child'},enabled:true}}};
  const catalog={revision:7,vendors:[{id:'local-s',name:'算能业务厂商',template_id:'tpu-mlir',adapter:'sophon',enabled:true},{id:'local-r',name:'瑞芯微业务厂商',template_id:'rknn',adapter:'rockchip',enabled:true}],chips:[{id:'chip84',vendor_id:'local-s',name:'BM1684X',sdk_code:'bm1684x',enabled:true},{id:'chip68',vendor_id:'local-r',name:'RK3568',sdk_code:'rk3568',enabled:true}]};
  const platforms=[{computePlatformId:'generic',computePlatformName:'通用原始模型',parentId:'0'},{computePlatformId:'s-parent',computePlatformName:'算能',parentId:'0'},{computePlatformId:'s-child',computePlatformName:'BM1684X',parentId:'s-parent'},{computePlatformId:'r-parent',computePlatformName:'瑞芯微',parentId:'0'},{computePlatformId:'r-child',computePlatformName:'RK3568',parentId:'r-parent'}];
  await page.route('**/api/v64/external-publish/config',async route=>{
    if(route.request().method()==='PUT'){
      writes++;const body=route.request().postDataJSON();
      if(failSave)return route.fulfill({status:409,json:{detail:'映射版本已变化，请核对草稿'}});
      if(rollbackSave){expect(body.replace_target_mappings).toBe(true);expect(body.target_mappings).not.toHaveProperty('vendor:local-s');expect(body.target_mappings).not.toHaveProperty('vendor:local-r');config={...config,target_mappings:body.target_mappings,mapping_revision:5};return route.fulfill({json:{ok:true,config}})}
      expect(body.expected_revision).toBe(3);expect(body.expected_catalog_revision).toBe(7);
      expect(body.target_mappings['vendor:local-s'].chip_mappings).toEqual({chip84:'s-child'});
      expect(body.target_mappings).not.toHaveProperty('vendor:local-r');
      expect(body.target_mappings.rockchip.chip_mappings).toEqual({RK3568:'legacy-child'});
      startedSave();await new Promise(resolve=>releaseSave=resolve);
      config={...config,target_mappings:body.target_mappings,mapping_revision:4};
    }
    await route.fulfill({json:{ok:true,config,local_catalog:catalog,compute_platforms:platforms,mapping_diagnostics:{vendors:{},legacy_proposals:[]}}});
  });
  await page.goto('/');
  await expect.poll(()=>page.evaluate(()=>typeof window.setPage==='function'&&state.uiReady===true)).toBe(true);
  const enter=async()=>{
    await page.evaluate(()=>window.setPage('平台对接'));
    await page.locator('[data-external-platform-tab="vendor"]').click();
    await expect(page.locator('[data-external-publish-panel="1"]')).toBeVisible();
  };
  await enter();
  let vendor=page.locator('[data-local-vendor="local-s"]');await vendor.locator('summary').click();
  await vendor.locator('[data-publish-platform]').selectOption('s-parent');
  await vendor.locator('[data-publish-chip-child]').selectOption('s-child');
  await page.evaluate(()=>window.setPage('工作台'));await enter();
  vendor=page.locator('[data-local-vendor="local-s"]');await vendor.locator('summary').click();
  await expect(vendor.locator('[data-publish-chip-child]')).toHaveValue('s-child');
  await page.locator('#externalPublishSave').click();await started;
  await page.evaluate(()=>window.setPage('工作台'));await enter();
  await expect(page.locator('#externalPublishSave')).toBeDisabled();
  releaseSave();await expect(page.locator('#externalPublishSave')).toBeEnabled();
  expect(writes).toBe(1);
  await page.reload();await expect.poll(()=>page.evaluate(()=>typeof window.setPage==='function'&&state.uiReady===true)).toBe(true);await enter();
  vendor=page.locator('[data-local-vendor="local-s"]');await vendor.locator('summary').click();
  await expect(vendor.locator('[data-publish-chip-child]')).toHaveValue('s-child');
  await expect(page.locator('[data-local-vendor]')).toHaveCount(2);
  await page.screenshot({path:'C:/Users/jorsam/.codex/visualizations/2026/10/20/01a156ca-1ca0-7b70-8497-bd255da4345e/stable-vendor-mapping-20261021.png',fullPage:true});
  failSave=true;
  await vendor.locator('[data-publish-chip-child]').selectOption('');
  await page.locator('#externalPublishSave').click();
  await expect(page.locator('#externalPublishSave')).toBeEnabled();
  await expect(page.locator('[data-mapping-dirty]')).toContainText('未保存');
  await expect(page.locator('[data-local-vendor="local-s"] [data-publish-chip-child]')).toHaveValue('');
  expect(config.target_mappings['vendor:local-s'].chip_mappings).toEqual({chip84:'s-child'});
  failSave=false;rollbackSave=true;
  await page.locator('.external-vendor-advanced > summary').click();
  await page.locator('[data-mapping-restore]').click();
  await page.locator('#externalPublishSave').click();
  await expect(page.locator('#externalPublishSave')).toBeEnabled();
  await expect.poll(()=>config.mapping_revision).toBe(5);
  expect(writes).toBe(3);

});
