import {test, expect} from '@playwright/test';

test('delayed request from previous page cannot jump back over the current page', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.getByRole('button', {name: /训练任务/})).toBeVisible({timeout: 15_000});
  await expect(page.getByRole('button', {name: /数据集/})).toBeVisible();

  let release;
  const gate = new Promise(resolve => { release = resolve; });
  let interceptedResolve;
  const intercepted = new Promise(resolve => { interceptedResolve = resolve; });
  let shouldDelay = true;

  await page.route('**/api/**', async route => {
    const request = route.request();
    if (shouldDelay && request.method() === 'GET') {
      shouldDelay = false;
      interceptedResolve(request.url());
      await gate;
      try {
        await route.continue();
      } catch (_) {
        // Expected when PageRequestScope aborts the old page request.
      }
      return;
    }
    await route.continue();
  });

  await page.getByRole('button', {name: /训练任务/}).click();
  const delayedUrl = await Promise.race([
    intercepted,
    new Promise((_, reject) => setTimeout(() => reject(new Error('训练任务页面没有发出可延迟的 GET 请求')), 8_000)),
  ]);
  expect(delayedUrl).toContain('/api/');

  await page.getByRole('button', {name: /数据集/}).click();
  await expect(page.locator('#title')).toContainText('数据集');
  await expect(page.getByRole('button', {name: /数据集/})).toHaveClass(/active/);

  release();
  await page.waitForTimeout(1_500);

  await expect(page.locator('#title')).toContainText('数据集');
  await expect(page.getByRole('button', {name: /数据集/})).toHaveClass(/active/);
  expect(pageErrors).toEqual([]);
});
