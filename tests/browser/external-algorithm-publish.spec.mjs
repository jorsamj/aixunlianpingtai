import {test, expect} from '@playwright/test';

test('changlian manual publish preflight blocks stale version analysis before POST', async ({page, request}) => {
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

  await page.route(`**/api/v12/projects/${project.id}/algorithms`, async route => {
    const response = await route.fetch();
    const body = await response.json();
    const items = (body.items || []).map(asset => String(asset.id) === String(algorithmId) ? {
      ...asset,
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
    } : asset);
    await route.fulfill({response, json: {...body, items}});
  });

  await page.route('**/api/v64/external-publish/projects/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/publish')) {
      publishWrites += 1;
      return route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({detail: 'publish must not be called'}),
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
        artifacts: [],
        discovered: [{target: 'rockchip', file_name: 'model.rknn', publish_mapping_status: 'mapped'}],
        mapped_artifact_count: 1,
        blocked_artifact_count: 0,
        ignored_artifact_count: 0,
        transport_ready: true,
        transport_issues: [],
        identity_ready: false,
        identity_issues: [{
          code: 'EXTERNAL_VERSION_ANALYSIS_STALE',
          message: '该训练版本绑定的畅联云分析方式已失效',
          detail: 'analysis-old',
          solution: '请立即同步并核对分析方式',
        }],
        publish_ready: false,
        conversion_active: false,
      }),
    });
  });

  await page.addInitScript(projectId => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({projectId, page: '算法列表'}));
  }, project.id);
  await page.goto('/');
  await expect.poll(async () => page.evaluate(() => state.uiReady === true)).toBe(true);
  await expect.poll(async () => page.evaluate(() => typeof window.ExternalAlgorithmPublishRuntime?.publishVersion))
    .toBe('function');

  await page.getByRole('button', {name: /算法列表/}).click();
  await expect(page.locator('#alg412List')).toBeVisible();
  await page.evaluate(async () => {
    await window.AlgorithmListRuntime?.refresh?.({render: true});
  });
  await expect.poll(async () => page.evaluate(() => (
    (state.algorithms || []).some(row => row.name === '抽烟检测')
  ))).toBe(true);
  await page.evaluate(() => {
    window.renderAlg412?.();
    window.AlgorithmListRuntime?.runDecorators?.();
  });

  const card = page.locator('.alg428-card', {hasText: '抽烟检测'});
  await expect(card).toBeVisible();
  await card.locator('.alg428-main').click();
  const versionRow = card.locator('.alg428-version-row', {hasText: '20260919233000'});
  await expect(versionRow).toBeVisible();
  const publishButton = versionRow.getByRole('button', {name: '同步到新畅联'});
  await expect(publishButton).toBeVisible();

  await publishButton.click();

  await expect.poll(() => statusReads).toBe(1);
  await expect.poll(() => publishWrites).toBe(0);
  await expect(page.getByText(/分析方式已失效/)).toBeVisible();
});
