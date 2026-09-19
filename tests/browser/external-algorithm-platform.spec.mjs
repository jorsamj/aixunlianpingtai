import {test, expect} from '@playwright/test';

test('changlian platform page tests draft credentials before manual sync', async ({page}) => {
  let testedPayload = null;

  await page.route('**/api/v63/external-algorithm-platform/config', async route => {
    if (route.request().method() !== 'GET') return route.continue();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        config: {
          mode: 'external',
          provider: 'changlian',
          provider_name: '新畅联',
          base_url: 'https://saved.example.test',
          auto_sync_enabled: false,
          auto_sync_interval_seconds: 600,
          auto_publish_enabled: false,
          auth_mode: 'test_sign_bridge',
          credentials: {
            configured: true,
            masked: 'AK-****1234',
            available: true,
            backend: 'encrypted_file',
            writable: true,
          },
          endpoints: {
            test_sign: '/internal/auth/test-sign',
            token: '/internal/auth/token',
            category_tree: '/algorithm-category/tree',
            product_list: '/algorithm-product/listAll',
            analysis_by_product: '/algorithm-product-analysis/listByProduct/{productId}',
            compute_platform_list: '/compute-platform/listAll',
            version_create: '/algorithm-version/add',
            weight_create: '/algorithm-weight/add',
          },
          cache: {
            category_count: 2,
            product_count: 3,
            analysis_count: 4,
            compute_platform_count: 2,
          },
        },
      }),
    });
  });

  await page.route('**/api/v63/external-algorithm-platform/sync-history?limit=20', async route => {
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({ok: true, items: []})});
  });

  await page.route('**/api/v63/external-algorithm-platform/cache', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        cache: {
          provider: 'changlian',
          categories: [{categoryId: 'c1', categoryName: '行为分析'}],
          products: [{productId: 'p1', productName: '抽烟检测', categoryId: 'c1'}],
          analyses_by_product: {p1: [{analysisId: 'a1', analysisName: '视觉智能分析'}]},
          compute_platforms: [{computePlatformId: 'cp1', computePlatformName: 'RK3568'}],
        },
      }),
    });
  });

  await page.route('**/api/v63/external-algorithm-platform/readiness?project_id=*', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        ready: true,
        provider: 'changlian',
        auth_type: 'application_credentials',
        human_login_required: false,
        blocking_keys: [],
        checks: [
          {key: 'human_login', name: '人员登录账号', status: 'not_required', detail: '系统对接不使用人员用户名/密码；内部 API 使用 AccessKey / AccessSecret 应用鉴权。'},
          {key: 'external_mode', name: '外部平台模式', status: 'ready', detail: '已启用新畅联'},
          {key: 'base_url', name: 'API 服务地址', status: 'ready', detail: 'https://saved.example.test'},
          {key: 'credentials', name: '应用凭据', status: 'ready', detail: '已配置 · encrypted_file'},
          {key: 'last_sync', name: '最近主数据同步', status: 'ready', detail: '2026-09-19T12:00:00Z'},
          {key: 'categories', name: '算法品目', status: 'ready', count: 2},
          {key: 'products', name: '算法产品', status: 'ready', count: 3},
          {key: 'analyses', name: '产品分析方式', status: 'ready', count: 4},
          {key: 'compute_platforms', name: '算力环境', status: 'ready', count: 2},
          {key: 'project_algorithms', name: '当前项目畅联云算法', status: 'ready', count: 1, detail: '同步算法 1 个，当前可训练 1 个'},
        ],
      }),
    });
  });

  await page.route('**/api/v63/external-algorithm-platform/test', async route => {
    testedPayload = route.request().postDataJSON();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        provider: 'changlian',
        provider_name: '新畅联',
        base_url: testedPayload.base_url,
        auth_mode: 'test_sign_bridge',
        tested_at: '2026-09-19T12:00:00Z',
        steps: [
          {key: 'auth', name: '应用鉴权', status: 'success'},
          {key: 'categories', name: '算法品目', status: 'success', count: 2},
          {key: 'products', name: '算法产品', status: 'success', count: 3},
          {key: 'compute_platforms', name: '算力环境', status: 'success', count: 2},
          {key: 'analysis', name: '产品分析方式', status: 'success', count: 1},
        ],
      }),
    });
  });

  await page.goto('/');
  await expect.poll(async () => page.evaluate(() => ({
    setPageReady: typeof window.setPage === 'function',
    uiReady: typeof state !== 'undefined' ? !!state.uiReady : false,
  })), {timeout: 20_000}).toEqual({setPageReady: true, uiReady: true});

  await page.evaluate(() => window.setPage('平台对接'));
  await expect(page.getByRole('heading', {name: '平台对接', level: 2})).toBeVisible({timeout: 10_000});

  const readiness = page.locator('[data-changlian-readiness="ready"]');
  await expect(readiness.getByText('基础条件已就绪')).toBeVisible();
  await expect(readiness.getByRole('cell', {name: '人员登录账号'})).toBeVisible();
  await expect(readiness.getByText('无需', {exact: true})).toBeVisible();
  await expect(readiness).toContainText('AccessKey / AccessSecret');
  await expect(readiness.getByRole('cell', {name: '当前项目畅联云算法'})).toBeVisible();

  await page.locator('#externalBaseUrl').fill('https://draft.example.test');
  await page.locator('#externalAccessKey').fill('draft-ak');
  await page.locator('#externalAccessSecret').fill('draft-secret');

  await expect(page.locator('[data-external-automation-settings="1"]')).not.toHaveAttribute('open', '');
  await expect(page.getByRole('button', {name: '↻ 立即同步'})).toBeEnabled();

  await page.getByRole('button', {name: '测试连接'}).click();

  await expect.poll(() => testedPayload).not.toBeNull();
  expect(testedPayload.base_url).toBe('https://draft.example.test');
  expect(testedPayload.access_key).toBe('draft-ak');
  expect(testedPayload.access_secret).toBe('draft-secret');
  expect(testedPayload.mode).toBe('external');

  const connectionResult = page.locator('#externalConnectionResult');
  await expect(connectionResult.getByText('连接成功')).toBeVisible();
  await expect(connectionResult.getByRole('cell', {name: '应用鉴权'})).toBeVisible();
  await expect(connectionResult.getByRole('cell', {name: '算法品目'})).toBeVisible();
  await expect(connectionResult.getByRole('cell', {name: '算法产品'})).toBeVisible();
  await expect(connectionResult.getByRole('cell', {name: '算力环境'})).toBeVisible();
  await expect(connectionResult.getByRole('cell', {name: '产品分析方式'})).toBeVisible();
});
