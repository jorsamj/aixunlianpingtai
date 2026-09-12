from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST = ROOT / 'tests/browser/navigation-stability.spec.mjs'
VERSION = ROOT / 'VERSION.txt'

s = TEST.read_text(encoding='utf-8')
marker = "test('model config delete keeps model configuration page consistent'"
if marker in s:
    raise SystemExit('R20e baseline already present')

block = r'''

test('model config delete keeps model configuration page consistent', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.route(/\/api\/v35\/model-configs\/cfg-r20e$/, async route => {
    if (route.request().method() !== 'DELETE') return route.continue();
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({ok: true})});
  });
  await page.route(/\/api\/v35\/model-configs(?:\?.*)?$/, async route => {
    if (route.request().method() !== 'GET') return route.continue();
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({items: []})});
  });

  page.on('dialog', dialog => dialog.accept());
  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await page.evaluate(() => {
    state.page = '模型配置';
    state.modelConfigs = [{
      id: 'cfg-r20e',
      name: 'R20e 模型配置',
      provider_type: 'local',
      model_name: 'r20e-model',
      detect_url: 'http://127.0.0.1:9000/detect',
    }];
    state.promptTemplates = [];
    render();
  });
  await expect(page.locator('#title')).toContainText('模型配置');
  await expect(page.locator('#view')).toContainText('R20e 模型配置');

  await page.getByRole('button', {name: '删除'}).first().click();
  await expect(page.locator('#toast')).toContainText('已删除');
  await expect(page.locator('#view')).not.toContainText('R20e 模型配置');
  expect(pageErrors).toEqual([]);
});

test('prompt template save appears immediately in model configuration', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.route(/\/api\/v35\/prompt-templates$/, async route => {
    const request = route.request();
    if (request.method() !== 'POST') return route.continue();
    const body = request.postDataJSON();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({...body, id: 'tpl-r20e-new', created_at: '2026-09-12T00:00:00Z'}),
    });
  });

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await page.evaluate(() => {
    state.page = '模型配置';
    state.modelConfigs = [];
    state.promptTemplates = [];
    render();
    window.openPromptTemplateModalV35();
  });
  await page.locator('#ptName').fill('R20e 新提示词');
  await page.locator('#ptLabels').fill('fire');
  await page.locator('#ptPrompt').fill('detect fire and return bbox json');
  await page.getByRole('button', {name: '保存模板'}).click();
  await expect(page.locator('#toast')).toContainText('已保存模型标注模板');
  await expect(page.locator('#view')).toContainText('R20e 新提示词');
  expect(pageErrors).toEqual([]);
});

test('prompt template delete disappears immediately in model configuration', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.route(/\/api\/v35\/prompt-templates\/tpl-r20e-old$/, async route => {
    if (route.request().method() !== 'DELETE') return route.continue();
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({ok: true})});
  });

  page.on('dialog', dialog => dialog.accept());
  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await page.evaluate(() => {
    state.page = '模型配置';
    state.modelConfigs = [];
    state.promptTemplates = [{
      id: 'tpl-r20e-old',
      name: 'R20e 旧提示词',
      framework: 'common',
      save_format: 'internal',
      labels: ['fire'],
      prompt: 'old prompt',
    }];
    render();
  });
  await expect(page.locator('#view')).toContainText('R20e 旧提示词');
  const row = page.locator('tr').filter({hasText: 'R20e 旧提示词'});
  await row.getByRole('button', {name: '删除'}).click();
  await expect(page.locator('#toast')).toContainText('已删除');
  await expect(page.locator('#view')).not.toContainText('R20e 旧提示词');
  expect(pageErrors).toEqual([]);
});
'''

TEST.write_text(s + block, encoding='utf-8')
if VERSION.read_text(encoding='utf-8').strip() != '42.24.0':
    raise SystemExit('formal VERSION changed')
print('R20e model-config/prompt behavior baseline added')
