import {test, expect} from '@playwright/test';

test('Vue upload pages restore legacy globals and do not reattach a destroyed ZIP runtime', async ({page, request}) => {
  test.setTimeout(120_000);
  const projects = await (await request.get('/api/projects')).json();
  let project = projects[0];
  if (!project) {
    project = await (await request.post('/api/projects', {
      data: {name: '宿主生命周期', labels: [{code: 'fire', display_name: '明火'}]},
    })).json();
  }

  await page.goto(`/app/#/projects/${project.id}/materials/upload`);
  await expect(page.getByRole('heading', {name: '上传图片', level: 2})).toBeVisible({timeout: 45000});
  await expect.poll(() => page.evaluate(() => (
    typeof window.UploadConfirmationRuntime?.open === 'function'
    && typeof window.ImageUppyView?.open === 'function'
  )), {timeout: 20000}).toBe(true);

  await page.goto(`/app/#/projects/${project.id}/materials`);
  await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/materials$`));
  await expect.poll(() => page.evaluate(() => (
    typeof window.UploadConfirmationRuntime === 'undefined'
    && typeof window.ImageUppyView === 'undefined'
    && typeof window.showTaskProgress427 === 'undefined'
    && typeof window.openSmartMaterialAudit === 'undefined'
  ))).toBe(true);

  await page.goto(`/app/#/projects/${project.id}/materials/zip`);
  await expect(page.locator('.uppy-Dashboard')).toBeVisible({timeout: 45000});
  const installed = await page.evaluate(() => {
    window.__lifecycleProbe = window.ZipImportRuntime;
    return {runtime: typeof window.ZipImportRuntime, modal: typeof window.modal,
      marker: window.ZipImportRuntime?.__nativeVueZipRuntime === true,
      upload: typeof window.doUploadZip426};
  });
  expect(installed).toEqual({runtime: 'object', modal: 'function', marker: true, upload: 'function'});

  await page.goto(`/app/#/projects/${project.id}/materials`);
  await expect.poll(() => page.evaluate(() => (
    typeof window.ZipImportRuntime === 'undefined'
    && typeof window.modal === 'undefined'
    && typeof window.doUploadZip426 === 'undefined'
    && typeof window.doImportData === 'undefined'
  ))).toBe(true);

  await page.goto(`/app/#/projects/${project.id}/materials/zip`);
  await expect(page.locator('.uppy-Dashboard')).toBeVisible({timeout: 45000});
  const reentered = await page.evaluate(() => ({
    marker: window.ZipImportRuntime?.__nativeVueZipRuntime === true,
    reusedDestroyed: window.ZipImportRuntime === window.__lifecycleProbe,
  }));
  expect(reentered).toEqual({marker: true, reusedDestroyed: false});
});
