import {test, expect} from '@playwright/test';

const viewports = [
  {width: 390, height: 844},
  {width: 1280, height: 800},
  {width: 1920, height: 1080},
];

for (const viewport of viewports) {
  test(`slow first snapshot has one startup owner at ${viewport.width}px`, async ({page}) => {
    await page.setViewportSize(viewport);
    let snapshots = 0;
    await page.route('**/api/v53/bootstrap/snapshot**', async route => {
      snapshots++;
      // Real browser timing, without replacing server snapshot with fake data.
      await new Promise(resolve => setTimeout(resolve, 5000));
      await route.continue();
    });
    await page.goto('/');
    await expect(page.locator('#view [data-boot-card="1"]')).toBeVisible();
    await page.waitForTimeout(3200); // intentionally crosses the old 3s timer
    await expect(page.locator('#view [data-boot-card="1"]')).toHaveCount(1);
    await expect.poll(() => page.evaluate(() => state.uiReady), {timeout: 20000}).toBe(true);
    await expect(page.locator('#view [data-boot-card="1"]')).toHaveCount(0);
    await page.waitForTimeout(7200); // intentionally crosses the old 10s timer
    await expect(page.locator('#view [data-boot-card="1"]')).toHaveCount(0);
    expect(snapshots).toBe(1);
  });
}

test('failed first core snapshot leaves the retry screen in charge of #view', async ({page}) => {
  await page.route('**/api/v53/bootstrap/snapshot**', route => route.fulfill({
    status: 500,
    contentType: 'application/json',
    body: JSON.stringify({detail: '隔离测试：核心接口失败'}),
  }));
  await page.goto('/');
  await expect(page.locator('#view .boot413-card.error')).toContainText('平台数据加载失败');
  await expect(page.locator('#view button')).toContainText(['重新加载', '刷新页面']);
  await expect.poll(() => page.evaluate(() => state.uiReady)).toBe(false);
  await page.waitForTimeout(1100);
  await expect(page.locator('#view [data-algorithm-list-owner]')).toHaveCount(0);
  await expect(page.locator('#view .boot413-card.error')).toBeVisible();
});

test('old page refresh cannot destroy B form after navigation or A→B→A', async ({page}) => {
  await page.goto('/');
  await expect.poll(() => page.evaluate(() => state.uiReady), {timeout: 20000}).toBe(true);
  let release;
  const held = new Promise(resolve => {release = resolve;});
  let started;
  const requested = new Promise(resolve => {started = resolve;});
  await page.route(/\/api\/v53\/bootstrap\/snapshot(?:\?.*)?$/, async route => {
    if (new URL(route.request().url()).searchParams.get('refresh') !== 'true') return route.continue();
    started();
    await held;
    await route.continue();
  });
  // Algorithm/Training have their own focused refresh capture owners; model
  // configuration deliberately exercises the global authoritative button.
  await page.evaluate(() => window.setPage('模型配置'));
  expect(await page.evaluate(() => typeof document.getElementById('refreshBtn')?.onclick)).toBe('function');
  await page.locator('#refreshBtn').click();
  await expect.poll(() => page.locator('#refreshBtn').textContent(), {timeout: 2000}).toContain('刷新中');
  await Promise.race([requested, new Promise((_, reject) => setTimeout(() => reject(new Error('未触发权威刷新请求')), 10000))]);
  await page.evaluate(() => window.setPage('训练任务'));
  await page.evaluate(() => {
    const field = document.createElement('input');
    field.id = 'lifecycle-in-progress-input';
    field.value = '用户未提交的输入';
    document.getElementById('view').appendChild(field);
  });
  release();
  await expect.poll(() => page.evaluate(() => state.page)).toBe('训练任务');
  await expect(page.locator('#lifecycle-in-progress-input')).toHaveValue('用户未提交的输入');
  await page.evaluate(() => window.setPage('模型配置'));
  await expect.poll(() => page.evaluate(() => state.page)).toBe('模型配置');
  await expect(page.locator('#view')).not.toContainText('正在读取核心页面');
});

test('closing a pending task-detail opener cannot resurrect it above a newer modal', async ({page}) => {
  await page.goto('/');
  await expect.poll(() => page.evaluate(() => state.uiReady), {timeout: 20000}).toBe(true);
  const taskId = 'lifecycle-race-only';
  let started;
  const requested = new Promise(resolve => {started = resolve;});
  let release;
  const held = new Promise(resolve => {release = resolve;});
  await page.route(/\/api\/v47\/projects\/[^/]+\/clean-tasks$/, async route => {
    started();
    await held;
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({items: [{id: taskId, status: 'running'}]})});
  });
  await page.evaluate(() => {void window.showCleanTaskProgress429('lifecycle-race-only');});
  await requested;
  await page.evaluate(() => window.modal('新业务窗口 B', '<input id="new-window-input" value="保留草稿">'));
  release();
  await expect(page.locator('.modal:not(.hidden) .modal-title').last()).toHaveText('新业务窗口 B');
  await expect(page.locator('#new-window-input')).toHaveValue('保留草稿');
  await expect(page.locator('[data-clean-progress-task="lifecycle-race-only"]')).toHaveCount(0);
});
