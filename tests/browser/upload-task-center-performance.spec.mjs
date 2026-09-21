import {test, expect} from '@playwright/test';

test('upload task center patches progress without rebuilding shell row or progress node', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await expect.poll(() => page.evaluate(() => window.UploadTaskCenterRuntime?.build || null))
    .toBe('upload-task-center-2');

  await page.evaluate(() => {
    window.UploadTaskCenterRuntime.upsert({
      id:'upload-perf-browser',
      kind:'browser-upload',
      title:'浏览器素材上传',
      status:'UPLOADING',
      progress:10,
      stage:'上传中',
      detail:'100 / 1000',
    });
  });

  await page.locator('[data-utc-toggle]').click();
  const row = page.locator('[data-utc-id="upload-perf-browser"]');
  await expect(row).toBeVisible();
  await expect(row).toContainText('10%');

  await page.evaluate(() => {
    window.__uploadCenterShell = document.querySelector('#uploadTaskCenter .utc-shell');
    window.__uploadCenterRow = document.querySelector('[data-utc-id="upload-perf-browser"]');
    window.__uploadCenterProgress = window.__uploadCenterRow?.querySelector('.utc-progress i') || null;

    window.UploadTaskCenterRuntime.upsert({
      id:'upload-perf-browser',
      kind:'browser-upload',
      title:'浏览器素材上传',
      status:'UPLOADING',
      progress:57.5,
      stage:'服务器处理中',
      detail:'575 / 1000',
    });
  });

  await expect(row).toContainText('57.5%');
  await expect(row).toContainText('服务器处理中');
  await expect(row.locator('.utc-progress i')).toHaveAttribute('data-progress', '57.50');

  expect(await page.evaluate(() => ({
    shell: window.__uploadCenterShell === document.querySelector('#uploadTaskCenter .utc-shell'),
    row: window.__uploadCenterRow === document.querySelector('[data-utc-id="upload-perf-browser"]'),
    progress: window.__uploadCenterProgress === document.querySelector('[data-utc-id="upload-perf-browser"] .utc-progress i'),
  }))).toEqual({shell:true,row:true,progress:true});

  await page.evaluate(() => window.UploadTaskCenterRuntime.remove('upload-perf-browser'));
  expect(pageErrors).toEqual([]);
});
