import {test, expect} from '@playwright/test';

async function boot(page) {
  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
}

async function protectNewPageModal(page, pageName = '数据集') {
  await page.evaluate(name => window.setPage(name), pageName);
  await expect(page.locator('#title')).toContainText(pageName);
  await page.evaluate(() => {
    const modal = document.getElementById('modal');
    document.getElementById('modalTitle').textContent = 'R2新页面保护';
    window.ModalContentRuntime?.replace?.(document.getElementById('modalBody'), '<div id="actionFenceR2Sentinel">new-page-r2</div>');
    modal.classList.remove('hidden');
  });
  await expect(page.locator('#modal')).not.toHaveClass(/hidden/);
  await expect(page.locator('#actionFenceR2Sentinel')).toHaveText('new-page-r2');
}

test('stale final M4 model save cannot close or redraw the page selected afterwards', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  let interceptedResolve;
  const intercepted = new Promise(resolve => { interceptedResolve = resolve; });

  await boot(page);
  await page.route(/\/api\/v35\/model-configs$/, async route => {
    if (route.request().method() !== 'POST') return route.continue();
    interceptedResolve();
    await gate;
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({
      id: 'model-r2', name: 'R2视觉模型', provider_type: 'local_openai', provider_adapter: 'local_openai',
      model_kind: 'vlm', model_name: 'r2-vlm', base_url: 'http://127.0.0.1:8000/v1', detect_url: 'http://127.0.0.1:8000/v1',
    })});
  });

  await page.evaluate(() => window.setPage('模型配置'));
  await expect(page.locator('#title')).toContainText('模型配置');
  await page.evaluate(() => window.openModelConfigModalV35());
  await page.locator('#mcName').fill('R2视觉模型');
  await page.locator('#mcModel').fill('r2-vlm');
  await page.locator('#mcUrl').fill('http://127.0.0.1:8000/v1');
  await page.getByRole('button', {name: '保存配置'}).click();

  await Promise.race([intercepted, new Promise((_, reject) => setTimeout(() => reject(new Error('M4 model save was not intercepted')), 8_000))]);
  await protectNewPageModal(page, '数据集');
  release();
  await page.waitForTimeout(700);

  await expect(page.locator('#title')).toContainText('数据集');
  await expect(page.locator('#modal'), 'stale M4 save closed the newer page modal').not.toHaveClass(/hidden/);
  await expect(page.locator('#modalTitle'), 'stale M4 save rewrote the newer page modal title').toHaveText('R2新页面保护');
  await expect(page.locator('#actionFenceR2Sentinel'), 'stale M4 save destroyed the newer page modal body').toHaveText('new-page-r2');
  expect(pageErrors).toEqual([]);
});

test('stale model connection test cannot open its result modal over a newer page modal', async ({page}) => {
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  let interceptedResolve;
  const intercepted = new Promise(resolve => { interceptedResolve = resolve; });

  await boot(page);
  await page.route(/\/api\/v35\/model-configs\/cfg-r2\/test-annotation$/, async route => {
    if (route.request().method() !== 'POST') return route.continue();
    interceptedResolve();
    await gate;
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({
      reachable: true, provider: 'local_openai', model: 'r2-vlm', latency_ms: 12, parsed_boxes: [], raw_preview: '{}',
    })});
  });

  await page.evaluate(() => window.setPage('模型配置'));
  await page.evaluate(() => { void window.testModelConfigV35('cfg-r2'); });
  await Promise.race([intercepted, new Promise((_, reject) => setTimeout(() => reject(new Error('model test POST was not intercepted')), 8_000))]);
  await protectNewPageModal(page, '数据集');
  release();
  await page.waitForTimeout(500);

  await expect(page.locator('#modalTitle'), 'stale model test replaced the newer page modal').toHaveText('R2新页面保护');
  await expect(page.locator('#actionFenceR2Sentinel'), 'stale model test destroyed the newer page modal body').toHaveText('new-page-r2');
});

test('stale clean confirmation cannot close newer UI or start broad project refresh', async ({page}) => {
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  let interceptedResolve;
  const intercepted = new Promise(resolve => { interceptedResolve = resolve; });
  let confirmReleased = false;
  let broadGetsAfterRelease = 0;

  await boot(page);
  await page.route(/\/api\/v47\/projects\/[^/]+\/clean-tasks\/clean-r2\/result$/, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({result: {items: [{image_id: 'image-r2', filename: 'image-r2.jpg', suggest_delete: true, issues: [{name: '重复图', detail: '测试'}]}]}}),
  }));
  await page.route(/\/api\/v47\/projects\/[^/]+\/clean-tasks\/clean-r2\/confirm$/, async route => {
    if (route.request().method() !== 'POST') return route.continue();
    interceptedResolve();
    await gate;
    confirmReleased = true;
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({ok: true, deleted: 1, deleted_ids: ['image-r2'], deleted_images: [], processed_ids: []})});
  });
  page.on('request', request => {
    if (!confirmReleased || request.method() !== 'GET') return;
    const url = request.url();
    if (/\/api\/projects\/[^/?]+(?:$|\/datasets(?:\?|$)|\/images(?:\?|$))/.test(url)) broadGetsAfterRelease += 1;
  });

  await page.evaluate(() => window.setPage('数据集'));
  await page.evaluate(() => window.reviewClean427('clean-r2'));
  await expect(page.getByRole('button', {name: '确认应用清洗'})).toBeVisible();
  await page.getByRole('button', {name: '确认应用清洗'}).click();
  await Promise.race([intercepted, new Promise((_, reject) => setTimeout(() => reject(new Error('clean confirm POST was not intercepted')), 8_000))]);

  await protectNewPageModal(page, '模型配置');
  release();
  await page.waitForTimeout(900);

  await expect(page.locator('#title')).toContainText('模型配置');
  await expect(page.locator('#modal'), 'stale clean confirm closed the newer page modal').not.toHaveClass(/hidden/);
  await expect(page.locator('#modalTitle'), 'stale clean confirm replaced the newer page modal').toHaveText('R2新页面保护');
  await expect(page.locator('#actionFenceR2Sentinel'), 'stale clean confirm destroyed the newer page modal body').toHaveText('new-page-r2');
  expect(broadGetsAfterRelease, 'stale clean confirm started broad GET fan-out').toBe(0);
});

test('stale AI confirmation cannot patch or close UI owned by a newer page', async ({page}) => {
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  let interceptedResolve;
  const intercepted = new Promise(resolve => { interceptedResolve = resolve; });

  await boot(page);
  await page.route(/\/api\/v47\/projects\/[^/]+\/ai-label-tasks\/ai-r2\/result$/, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({result: {labels: ['smoke'], items: [{image_id: 'image-ai-r2', filename: 'image-ai-r2.jpg', status: 'ok', boxes: [{label: 'smoke', x1: 1, y1: 1, x2: 10, y2: 10, confidence: 0.9}]}]}}),
  }));
  await page.route(/\/api\/v47\/projects\/[^/]+\/ai-label-tasks\/ai-r2\/confirm$/, async route => {
    if (route.request().method() !== 'POST') return route.continue();
    interceptedResolve();
    await gate;
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({
      applied_images: 1, boxes_added: 1, applied_image_ids: ['image-ai-r2'],
    })});
  });

  await page.evaluate(() => window.setPage('数据集'));
  await page.evaluate(() => window.reviewAiLabel427('ai-r2'));
  await expect(page.getByRole('button', {name: '确认写入标注'})).toBeVisible();
  await page.getByRole('button', {name: '确认写入标注'}).click();
  await Promise.race([intercepted, new Promise((_, reject) => setTimeout(() => reject(new Error('AI confirm POST was not intercepted')), 8_000))]);

  await protectNewPageModal(page, '模型配置');
  release();
  await page.waitForTimeout(700);

  await expect(page.locator('#title')).toContainText('模型配置');
  await expect(page.locator('#modal'), 'stale AI confirm closed the newer page modal').not.toHaveClass(/hidden/);
  await expect(page.locator('#modalTitle'), 'stale AI confirm replaced the newer page modal').toHaveText('R2新页面保护');
  await expect(page.locator('#actionFenceR2Sentinel'), 'stale AI confirm destroyed the newer page modal body').toHaveText('new-page-r2');
});
