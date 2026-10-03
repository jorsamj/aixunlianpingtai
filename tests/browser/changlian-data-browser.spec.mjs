import {test, expect} from '@playwright/test';

test('changlian data page never auto-loads and manual refresh shows remote products versions weights and download links', async ({page}) => {
  let providerReads = 0;
  await page.route('**/api/v63/external-algorithm-platform/provider/products*', async route => {
    providerReads += 1;
    const url = new URL(route.request().url());
    const status = url.searchParams.get('status');
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        response: {code: 0, data: status === '1' ? [{
          productId: 'p-db-1',
          productName: '畅联云抽烟检测',
          productCode: 'SMOKE-001',
          categoryName: '行为分析',
          productType: 3,
          status: 1,
        }] : []},
      }),
    });
  });
  await page.route('**/api/v63/external-algorithm-platform/provider/versions/by-product/p-db-1', async route => {
    providerReads += 1;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ok: true, response: {code: 0, data: [{
        algoVersionId: 'v-db-1',
        versionName: '20260924',
        versionNo: '1.0.0',
        analysisId: 'analysis-1',
        status: 1,
      }]}}),
    });
  });
  await page.route('**/api/v63/external-algorithm-platform/provider/weights/by-version/v-db-1', async route => {
    providerReads += 1;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ok: true, response: {code: 0, data: [{
        weightId: 'w-db-1',
        computePlatformId: 'rk3568',
        chipCode: 'rk3568',
        fileName: 'smoke-v1.rknn',
        filePath: 'https://download.example.test/smoke-v1.rknn',
      }]}}),
    });
  });

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  const advanced = page.getByRole('button', {name: '展开高级功能', exact: true});
  if (await advanced.count()) await advanced.click();
  await page.getByRole('button', {name: /畅联云数据/}).click();

  await expect(page.locator('[data-changlian-data-browser="1"]')).toBeVisible();
  await expect(page.getByText('页面不会自动读取远端数据库。')).toBeVisible();
  await page.waitForTimeout(250);
  expect(providerReads).toBe(0);

  await page.locator('[data-cldb-refresh]').click();
  await expect(page.getByText('畅联云抽烟检测', {exact: true})).toBeVisible();
  await page.getByText('畅联云抽烟检测', {exact: true}).click();
  await expect(page.getByText('20260924', {exact: true})).toBeVisible();
  await expect(page.getByText('smoke-v1.rknn', {exact: true})).toBeVisible();
  await expect(page.getByRole('link', {name: '下载 / 打开'})).toHaveAttribute('href', 'https://download.example.test/smoke-v1.rknn');
  expect(providerReads).toBe(4);
  expect(await page.locator('[data-changlian-data-browser="1"]').count()).toBe(1);
});
