import {test, expect} from '@playwright/test';

const PIXEL = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==';
const models = {items: [{
  id: 'vision-model-1', name: '场景视觉模型', model_name: 'vision-v1',
  provider_type: 'local_openai', provider_adapter: 'local_openai',
  default_for_annotation: true, annotation_prompt_template: '检测 {{labels_json}} {{output_schema}}',
}]};
const templates = {items: [{
  id: 'prompt-1', name: '烟火检测模板', version: 4, version_id: 'prompt-v4',
  model_config_id: 'vision-model-1', labels: ['fire'],
  prompt: '只检测 {{labels_json}}，尺寸 {{image_width}}x{{image_height}}。{{output_schema}}',
}]};
const labels = {items: [
  {code: 'fire', display_name_zh: '明火', status: 'active'},
  {code: 'smoke', display_name_zh: '烟雾', status: 'active'},
]};

async function installDelayedCreationApis(page, {materialDelayMs = 1200} = {}) {
  const requests = [];
  page.on('request', request => requests.push(new URL(request.url()).pathname));
  const delayed = async (route, body, delayMs = 1200) => {
    await new Promise(resolve => setTimeout(resolve, delayMs));
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});
  };
  await page.route('**/api/v35/model-configs', route => delayed(route, models));
  await page.route('**/api/v35/prompt-templates', route => delayed(route, templates));
  await page.route('**/api/v12/projects/*/labels', route => delayed(route, labels));
  await page.route('**/api/v61/projects/*/materials**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/materials/ids')) {
      await new Promise(resolve => setTimeout(resolve, 3000));
      return route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({items: [], total: 0})});
    }
    const reference = url.searchParams.get('annotated') === 'true';
    return delayed(route, {
      items: Array.from({length: 6}, (_, index) => ({
        id: `${reference ? 'reference' : 'ai-image'}-${index + 1}`,
        filename: `${reference ? 'reference' : 'scene'}-${index + 1}.jpg`, url: PIXEL,
        width: 640, height: 480, annotated: reference,
        labels: reference ? ['smoke'] : [], size_bytes: 1024,
      })),
      total: 50_000, page: 1, page_size: 12, total_pages: 4167, next_cursor: null,
    }, materialDelayMs);
  });
  return requests;
}

async function ready(page) {
  await page.goto('/');
  await expect.poll(() => page.evaluate(() => ({
    ui: typeof state !== 'undefined' ? !!state.uiReady : false,
    create: typeof window.createAiLabel429 === 'function',
  })), {timeout: 20_000}).toEqual({ui: true, create: true});
}

test('AI create opens immediately while configuration and material pages load lazily', async ({page}, testInfo) => {
  const requests = await installDelayedCreationApis(page, {materialDelayMs: 10_000});
  await ready(page);
  const before = requests.length;
  const elapsed = await page.evaluate(() => {
    const started = performance.now();
    window.createAiLabel429();
    if (!document.querySelector('.ai-create-workbench')) throw new Error('dialog shell missing');
    return performance.now() - started;
  });
  expect(elapsed).toBeLessThan(300);
  await expect(page.getByRole('dialog', {name: '创建AI自动标注任务'})).toBeVisible();
  await expect(page.locator('#ai429Hydration')).toContainText('正在同步');
  expect(requests.slice(before).some(item => item.endsWith('/materials/ids'))).toBe(false);

  await expect(page.locator('#ai429Models')).toContainText('场景视觉模型', {timeout: 5000});
  await expect(page.locator('#ai429LabelGrid')).toContainText('明火');
  await expect(page.locator('#ai429MaterialGrid')).toContainText('scene-1.jpg', {timeout: 15_000});
  await expect(page.locator('#ai429MaterialCount')).toContainText('匹配 50000 张');
  await expect(page.locator('#ai429MaterialGrid button')).toHaveCount(6);
  await page.evaluate(() => { document.querySelector('#modalBody').scrollTop = 0; });
  await page.screenshot({path: testInfo.outputPath('ai-create-1366x768.png'), fullPage: false});
  await page.getByRole('button', {name: /明火/}).click();
  await page.locator('#ai429Template').selectOption('prompt-1');
  await expect(page.locator('#ai429Prompt')).toHaveValue(/只检测/);
  await page.locator('.ai-create-preview').click();
  await expect(page.locator('#ai429PromptPreview')).toContainText('"code": "fire"', {timeout: 5000});

  await page.locator('.ai-create-advanced').click();
  await expect(page.locator('#ai429RefGrid')).toContainText('reference-1.jpg', {timeout: 15_000});
  await page.locator('#ai429RefGrid button').first().click();
  await expect(page.locator('#ai429ReferenceCount')).toContainText('已选 1 张');
  await expect(page.locator('#ai429Labels')).toHaveValue('fire');

  await page.screenshot({path: testInfo.outputPath('ai-create-prompt-1366x768.png'), fullPage: false});
});

test('closing and reopening fences stale AI create hydration and remains usable on mobile', async ({page}, testInfo) => {
  await page.setViewportSize({width: 390, height: 844});
  await installDelayedCreationApis(page);
  await ready(page);
  await page.evaluate(() => window.createAiLabel429());
  const first = await page.locator('.ai-create-workbench').getAttribute('data-ai-create-epoch');
  await page.getByRole('button', {name: '取消'}).click();
  await page.evaluate(() => window.createAiLabel429());
  const second = await page.locator('.ai-create-workbench').getAttribute('data-ai-create-epoch');
  expect(Number(second)).toBeGreaterThan(Number(first));
  await expect(page.locator('#ai429Models')).toContainText('场景视觉模型', {timeout: 5000});
  await expect(page.locator('.ai-create-workbench')).toHaveAttribute('data-ai-create-epoch', second);
  await expect(page.locator('#ai429Submit')).toBeVisible();
  await page.screenshot({path: testInfo.outputPath('ai-create-mobile-390x844.png'), fullPage: false});
});

test('AI create keeps the form on configuration or submit failure and fences duplicate submit', async ({page}) => {
  let modelReads = 0;
  let submitCount = 0;
  await page.route('**/api/v35/model-configs', async route => {
    modelReads += 1;
    if (modelReads === 1) {
      await route.fulfill({status: 503, contentType: 'application/json', body: JSON.stringify({message: '模型配置暂不可用'})});
      return;
    }
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(models)});
  });
  await page.route('**/api/v35/prompt-templates', route => route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(templates)}));
  await page.route('**/api/v12/projects/*/labels', route => route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(labels)}));
  await page.route('**/api/v61/projects/*/materials**', route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({
      items: [{id: 'retry-image', filename: 'retry.jpg', url: PIXEL, width: 640, height: 480, annotated: false}],
      total: 1, page: 1, page_size: 12, total_pages: 1,
    }),
  }));
  await page.route('**/api/v60/projects/*/annotation-tasks', async route => {
    if (route.request().method() !== 'POST') return route.continue();
    submitCount += 1;
    await new Promise(resolve => setTimeout(resolve, 250));
    await route.fulfill({status: 503, contentType: 'application/json', body: JSON.stringify({message: '模型连接失败'})});
  });

  await ready(page);
  await page.evaluate(() => window.createAiLabel429());
  await expect(page.locator('#ai429Hydration')).toContainText('部分配置读取失败');
  await page.locator('#ai429Hydration').getByRole('button', {name: '重试'}).click();
  await expect(page.locator('#ai429Models')).toContainText('场景视觉模型');
  await page.getByRole('button', {name: /明火/}).click();
  await page.locator('#ai429Prompt').fill('保留本次输入 {{labels_json}} {{output_schema}}');
  await page.locator('#ai429Submit').click();
  await page.evaluate(() => window.submitAiLabel429());
  await expect.poll(() => submitCount).toBe(1);
  await expect(page.getByRole('dialog', {name: '创建AI自动标注任务'})).toBeVisible();
  await expect(page.locator('#ai429Prompt')).toHaveValue('保留本次输入 {{labels_json}} {{output_schema}}');
  await expect(page.locator('#ai429Labels')).toHaveValue('fire');
  await expect(page.locator('#ai429Submit')).toBeEnabled();
});
