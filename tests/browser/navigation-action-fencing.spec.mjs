import {test, expect} from '@playwright/test';

test('stale training-server save cannot close or redraw UI owned by the new page', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  let releaseSave;
  const saveGate = new Promise(resolve => { releaseSave = resolve; });
  let saveInterceptedResolve;
  const saveIntercepted = new Promise(resolve => { saveInterceptedResolve = resolve; });
  let postSaveTrainingOptions = 0;
  let saveReleased = false;

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});

  await page.route(/\/api\/train_servers$/, async route => {
    if (route.request().method() !== 'POST') return route.continue();
    saveInterceptedResolve();
    await saveGate;
    saveReleased = true;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({id: 'server-action-fence', name: 'Action Fence GPU', base_url: 'http://127.0.0.1:8020'}),
    });
  });
  page.on('request', request => {
    if (saveReleased && request.method() === 'GET' && /\/api\/training_options(?:\?|$)/.test(request.url())) {
      postSaveTrainingOptions += 1;
    }
  });

  await page.evaluate(() => window.setPage('训练资源'));
  await expect(page.locator('#title')).toContainText('训练资源');
  await page.evaluate(() => window.addServer());
  await expect(page.locator('#modal')).not.toHaveClass(/hidden/);
  await page.locator('#sname').fill('Action Fence GPU');
  await page.locator('#surl').fill('http://127.0.0.1:8020');
  await page.getByRole('button', {name: '保存'}).click();

  await Promise.race([
    saveIntercepted,
    new Promise((_, reject) => setTimeout(() => reject(new Error('saveServer POST was not intercepted')), 8_000)),
  ]);

  await page.evaluate(() => window.setPage('数据集'));
  await expect(page.locator('#title')).toContainText('数据集');
  await page.evaluate(() => window.modal('新页面保护', '<div id="actionFenceSentinel">new-page-modal</div>', true));
  await expect(page.locator('#modal')).not.toHaveClass(/hidden/);
  await expect(page.locator('#modalTitle')).toHaveText('新页面保护');
  await expect(page.locator('#actionFenceSentinel')).toHaveText('new-page-modal');

  releaseSave();
  await page.waitForTimeout(700);

  await expect(page.locator('#title')).toContainText('数据集');
  await expect(page.getByRole('button', {name: /数据集/})).toHaveClass(/active/);
  await expect(page.locator('#modal')).not.toHaveClass(/hidden/);
  await expect(page.locator('#modalTitle')).toHaveText('新页面保护');
  await expect(page.locator('#actionFenceSentinel')).toHaveText('new-page-modal');
  expect(postSaveTrainingOptions).toBe(0);
  expect(pageErrors).toEqual([]);
});
