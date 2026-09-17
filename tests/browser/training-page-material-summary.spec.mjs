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
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        requested_count: ids.length,
        matched_count: ids.length,
        eligible_count: ids.length,
        eligible_total: 10_000,
        box_count: ids.length * 2,
        size_bytes: ids.length * 1024,
        label_codes: ids.length ? ['smoke', 'person'] : [],
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
    ];
    state.algorithms = [{id: 'summary-algorithm', name: '摘要测试算法', versions: []}];
    document.body.insertAdjacentHTML('beforeend', `
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
  await expect.poll(async () => page.evaluate(() => window.TrainingDraftRuntime.current().newLabelCodes.slice().sort()))
    .toEqual(['person', 'smoke']);
  await expect.poll(async () => page.evaluate(() => window.TrainingMaterialSummaryRuntime.state().fullPoolHydration))
    .toBe(false);
});
