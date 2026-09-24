import {test, expect} from '@playwright/test';

async function boot(page) {
  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
}

test('terminal source import does not fan out into a broad project reload', async ({page}) => {
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  let interceptedResolve;
  const intercepted = new Promise(resolve => { interceptedResolve = resolve; });
  let terminalReleased = false;
  const forbidden = [];
  let labelGets = 0;
  let materialGets = 0;

  await boot(page);
  await page.evaluate(() => window.setPage('数据集'));
  await expect(page.locator('#title')).toContainText('数据集');
  await expect.poll(async () => page.evaluate(() => ({
    project: Boolean(state.project?.id),
    dataset: Boolean(state.datasetId),
  }))).toEqual({project: true, dataset: true});

  page.on('request', request => {
    if (!terminalReleased || request.method() !== 'GET') return;
    const pathname = new URL(request.url()).pathname;
    if (/\/labels$/.test(pathname)) labelGets += 1;
    if (/\/materials$/.test(pathname)) materialGets += 1;
    if (
      /^\/api\/projects\/[^/]+$/.test(pathname)
      || /^\/api\/projects\/[^/]+\/datasets$/.test(pathname)
      || /^\/api\/projects\/[^/]+\/images$/.test(pathname)
      || /^\/api\/v12\/projects\/[^/]+\/algorithms$/.test(pathname)
      || /^\/api\/v12\/projects\/[^/]+\/publish\/pending$/.test(pathname)
      || /^\/api\/v12\/projects\/[^/]+\/test_models$/.test(pathname)
      || pathname === '/api/v35/model-configs'
      || pathname === '/api/v35/prompt-templates'
    ) forbidden.push(pathname);
  });

  await page.route('**/api/v36/projects/**/datasets/**/source-import/jobs', async route => {
    if (route.request().method() !== 'GET') return route.continue();
    interceptedResolve();
    await gate;
    terminalReleased = true;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({items: [{
        id: 'source-r20l',
        name: 'R20l地址读取',
        source: '/data/import/r20l',
        status: 'done',
        status_text: '导入完成',
        stage: '完成',
        progress: 100,
        imported_images: 12,
        boxes: 8,
        split_counts: {train: 8, val: 2, test: 2},
      }]}),
    });
  });

  await page.evaluate(() => window.importData());
  await Promise.race([
    intercepted,
    new Promise((_, reject) => setTimeout(() => reject(new Error('explicit source-import refresh was not intercepted')), 8_000)),
  ]);
  release();

  await expect(page.locator('#sourceTaskListV36')).toContainText('导入完成');
  await page.waitForTimeout(900);

  expect(forbidden, `terminal source import triggered broad GET fan-out: ${forbidden.join(', ')}`).toEqual([]);
  expect(labelGets, 'terminal source import did not refresh label schema').toBeGreaterThan(0);
  expect(materialGets, 'terminal source import did not refresh the current paged material domain').toBeGreaterThan(0);
});


test('source page revisit reuses the recent snapshot without another list request', async ({page}) => {
  let listGets = 0;
  await page.route('**/api/v42/projects/*/sources', async route => {
    if (route.request().method() !== 'GET') return route.continue();
    listGets += 1;
    await route.fulfill({
      status:200,
      contentType:'application/json',
      body:JSON.stringify({items:[{
        id:'source-cache-1',
        name:'缓存素材源',
        type:'folder',
        source:'/data/cache-source',
        collect_mode:'manual',
        runtime_status:'ready',
        status:'ready',
        enabled:true,
        dataset_id:'default',
        max_items:100,
        interval_seconds:2,
      }]}),
    });
  });

  await boot(page);
  await page.evaluate(() => window.setPage('素材接入'));
  await expect(page.locator('#title')).toContainText('素材接入');
  await expect(page.locator('#source422Rows')).toContainText('缓存素材源',{timeout:10_000});
  await expect.poll(() => listGets).toBeGreaterThan(0);
  const firstVisitGets = listGets;

  await page.evaluate(() => window.setPage('工作台'));
  await expect(page.locator('#title')).toContainText('总览');
  await page.evaluate(() => window.setPage('素材接入'));
  await expect(page.locator('#source422Rows')).toContainText('缓存素材源');
  await page.waitForTimeout(150);
  expect(listGets).toBe(firstVisitGets);
});
