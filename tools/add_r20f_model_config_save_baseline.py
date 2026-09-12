from pathlib import Path

path = Path('tests/browser/navigation-stability.spec.mjs')
text = path.read_text(encoding='utf-8')
marker = "test('model config save appears immediately without broad related refresh', async ({page}) => {"
if marker in text:
    raise SystemExit('R20f baseline already exists')

test = r'''

test('model config save appears immediately without broad related refresh', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.route(/\/api\/v35\/model-configs(?:\?.*)?$/, async route => {
    const request = route.request();
    if (request.method() === 'GET') {
      await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({items: []})});
      return;
    }
    if (request.method() !== 'POST') return route.continue();
    const body = request.postDataJSON();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...body,
        id: 'cfg-r20f-new',
        has_api_key: false,
        api_key_masked: '',
        created_at: '2026-09-12T10:30:00Z',
        updated_at: '2026-09-12T10:30:00Z',
      }),
    });
  });

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await page.evaluate(() => {
    state.page = '模型配置';
    state.modelConfigs = [];
    state.promptTemplates = [];
    render();
    window.openModelConfigModalV35();
  });

  await expect(page.locator('#modal')).not.toHaveClass(/hidden/);
  await page.locator('#mcName').fill('R20f 新模型配置');
  await page.locator('#mcModel').fill('r20f-vision-model');
  await page.locator('#mcUrl').fill('http://127.0.0.1:19020/detect');

  const actionRequests = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) actionRequests.push(`${request.method()} ${url.pathname}${url.search}`);
  });

  await page.locator('#modalBody').getByRole('button', {name: '保存'}).click();
  await expect(page.locator('#modal')).toHaveClass(/hidden/);
  await expect(page.locator('#toast')).toContainText('模型配置已保存');
  await expect(page.locator('#view')).toContainText('R20f 新模型配置');
  await expect.poll(async () => page.evaluate(() => state.modelConfigs.find(x => x.id === 'cfg-r20f-new')?.name || '')).toBe('R20f 新模型配置');

  expect(actionRequests.filter(row => row === 'POST /api/v35/model-configs')).toHaveLength(1);
  expect(actionRequests.filter(row => row.startsWith('GET /api/projects/'))).toEqual([]);
  expect(actionRequests.filter(row => row.startsWith('GET /api/v12/projects/'))).toEqual([]);
  expect(actionRequests.filter(row => row.includes('/bootstrap/snapshot'))).toEqual([]);
  expect(pageErrors).toEqual([]);
});
'''

path.write_text(text.rstrip() + test + '\n', encoding='utf-8')
