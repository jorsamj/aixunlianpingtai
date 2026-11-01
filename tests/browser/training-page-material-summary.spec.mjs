import {test, expect} from '@playwright/test';

test('training page stays paged and selected labels come from server summary', async ({page}) => {
  const apiRequests = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) apiRequests.push(`${request.method()} ${url.pathname}${url.search}`);
  });

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await expect.poll(async () => page.evaluate(() => window.TrainingMaterialSummaryRuntime?.state?.().networkOwner || false))
    .toBe(true);
  await expect.poll(async () => page.evaluate(() => window.PlatformCore?.materialPaging?.requiresFullMaterialPool?.('训练任务')))
    .toBe(false);

  apiRequests.length = 0;
  await page.evaluate(() => window.setPage('训练任务'));
  await expect.poll(async () => page.evaluate(() => window.__materialPaging61?.mode)).toBe('paged');
  expect(apiRequests.some(value => /\/api\/projects\/[^/]+\/images(?:\?|$)/.test(value))).toBe(false);

  const projectId = await page.evaluate(() => state.project?.id);
  expect(projectId).toBeTruthy();
  const encoded = encodeURIComponent(projectId);
  let summaryCalls = 0;
  await page.route(`**/api/v62/projects/${encoded}/training-materials/selection-summary`, async route => {
    summaryCalls += 1;
    const request = route.request();
    const payload = request.postDataJSON();
    const ids = Array.isArray(payload?.image_ids) ? payload.image_ids : [];
    const positiveCodes = ids.length ? (ids.includes('only-person') ? ['person'] : ['smoke', 'person']) : [];
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        requested_count: ids.length,
        matched_count: ids.length,
        selectable_count: ids.length,
        eligible_count: ids.length,
        pending_annotation_count: 0,
        selectable_total: 10_000,
        eligible_total: 8_000,
        pending_annotation_total: 2_000,
        box_count: ids.length * 2,
        size_bytes: ids.length * 1024,
        label_codes: positiveCodes,
        positive_label_codes: positiveCodes,
        label_counts: ids.length ? {smoke: ids.length, person: ids.length} : {},
        repository_revision: 91,
      }),
    });
  });

  await page.evaluate(() => {
    state.images = [];
    state.labels = [
      {code: 'smoke', display_name: '烟雾'},
      {code: 'person', display_name: '人员'},
      {code: 'fire', display_name: '明火'},
      {code: 'phone', display_name: '电话'},
    ];
    state.algorithms = [{id: 'summary-algorithm', name: '摘要测试算法', versions: []}];
    // Mount the synthetic host inside the app content column, outside the
    // fixed sidebar's hit area, so checkbox tests exercise a real user click.
    document.querySelector('main.main').insertAdjacentHTML('beforeend', `
      <div id="summaryTestHost" class="train429-create">
        <div class="train428-panel">
          <div class="train-v3-summary">
            <div><span>训练素材</span><b>1</b><em id="tr429Labels">—</em></div>
            <div><span>可选素材</span><b id="summaryAvailable">0</b><em>仅含可用于训练的素材</em></div>
          </div>
        </div>
      </div>`);
    window.TrainingDraftRuntime.update({
      algorithmId: 'summary-algorithm',
      materialIds: ['selected-outside-current-page'],
      testMaterialIds: [],
      newLabelCodes: [],
    });
  });

  await expect.poll(() => summaryCalls).toBeGreaterThan(0);
  await expect(page.locator('#summaryAvailable')).toHaveText('10000');
  await expect(page.locator('#tr429Labels')).toContainText('烟雾');
  await expect(page.locator('#tr429Labels')).toContainText('人员');
  await expect(page.locator('#trainingLabelContractPanel')).toContainText('烟雾');
  await expect(page.locator('#trainingLabelContractPanel')).toContainText('人员');
  await expect(page.locator('[data-training-label-code="fire"]')).toHaveCount(0);
  await expect(page.locator('[data-training-label-code="phone"]')).toHaveCount(0);
  // Server truth exposes available material labels, but the product must
  // never select new training classes on the user's behalf.
  await expect.poll(async () => page.evaluate(() => window.TrainingDraftRuntime.current().newLabelCodes.slice().sort()))
    .toEqual([]);
  await page.locator('[data-training-label-code="smoke"]').check();
  await expect.poll(() => page.evaluate(() => window.TrainingDraftRuntime.current().newLabelCodes))
    .toEqual(['smoke']);
  await page.evaluate(() => window.TrainingDraftRuntime.setMaterialIds(['only-person']));
  await expect(page.locator('[data-training-label-code="smoke"]')).toHaveCount(0);
  await expect(page.locator('[data-training-label-code="person"]')).toHaveCount(1);
  await expect.poll(() => page.evaluate(() => window.TrainingDraftRuntime.current().newLabelCodes))
    .toEqual([]);
  await expect.poll(async () => page.evaluate(() => window.TrainingMaterialSummaryRuntime.state().fullPoolHydration))
    .toBe(false);
});

test('training diagnosis filters by each material actual missing review label', async ({page}) => {
  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await expect.poll(async () => page.evaluate(() => Boolean(window.TrainingMaterialSummaryRuntime?.refreshCompatibility)))
    .toBe(true);
  const requests = [];
  await page.route('**/api/v62/projects/*/training-materials/compatibility', async route => {
    const body=route.request().postDataJSON();requests.push(body);
    const rows=[
      {image_id:'has-fire',filename:'fire.jpg',issue_type:'partial_review_scope',
        annotation_scope:['fire'],required_label_codes:['fire','smoke'],missing_label_codes:['smoke']},
      {image_id:'has-smoke',filename:'smoke.jpg',issue_type:'partial_review_scope',
        annotation_scope:['smoke'],required_label_codes:['fire','smoke'],missing_label_codes:['fire']},
    ].filter(item=>!body.missing_label_code||item.missing_label_codes.includes(body.missing_label_code));
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({
      compatible:false,issue_count:2,affected_image_count:2,issue_counts:{partial_review_scope:2},
      effective_label_codes:['fire','smoke'],material_revision:5,annotation_revision:7,
      filtered_affected_image_count:rows.length,filtered_count:rows.length,
      items:rows,page:1,page_size:50,total_pages:1,has_next:false,
    })});
  });
  await page.evaluate(() => {
    state.labels=[{code:'fire',display_name:'明火'},{code:'smoke',display_name:'烟雾'}];
    state.algorithms=[{id:'synthetic-label-review',name:'合成测试算法',versions:[]}];
    window.TrainingDraftRuntime.update({algorithmId:'synthetic-label-review',
      materialIds:['has-fire','has-smoke'],newLabelCodes:['fire','smoke']});
  });
  await page.evaluate(async () => {
    await window.TrainingMaterialSummaryRuntime.refreshCompatibility({force:true});
    window.TrainingMaterialSummaryRuntime.openCompatibilityIssues();
  });
  const labelFilter=page.locator('#trainingCompatibilityMissingLabel');
  await expect(labelFilter).toBeVisible();
  await labelFilter.selectOption('smoke');
  await page.locator('[data-training-compatibility-dialog]').getByRole('button',{name:'筛选',exact:true}).click();
  await expect.poll(() => requests.at(-1)?.missing_label_code).toBe('smoke');
  await expect(page.locator('.training-compatibility-item')).toHaveCount(1);
  await expect(page.locator('.training-compatibility-item')).toContainText('has-fire');
  await expect(page.locator('.training-compatibility-item')).toContainText('缺失：smoke');
  await expect(page.locator('.training-compatibility-item')).not.toContainText('has-smoke');
});
