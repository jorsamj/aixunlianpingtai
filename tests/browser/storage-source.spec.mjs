import {test, expect} from '@playwright/test';

async function openStoragePage(page) {
  await page.goto('/');
  await expect.poll(async () => page.evaluate(() => ({
    setPageReady: typeof window.setPage === 'function',
    uiReady: typeof state !== 'undefined' ? !!state.uiReady : false,
  })), {timeout: 20_000}).toEqual({setPageReady: true, uiReady: true});
  await page.evaluate(() => window.setPage('素材存储配置'));
  await expect(page.getByRole('heading', {name: '素材存储配置', level: 2})).toBeVisible({timeout: 10_000});
}



test('storage configuration creates, health-checks, and removes a real local source', async ({page}) => {
  const name = `浏览器本地源-${Date.now()}`;
  await openStoragePage(page);
  await expect(page.getByText('平台本地存储', {exact: true})).toBeVisible();

  await page.getByRole('button', {name: /新增存储源/}).click();
  await page.locator('#ss61Name').fill(name);
  await page.locator('#ss61Type').selectOption('local');
  await page.getByRole('button', {name: '保存'}).click();

  const row = page.locator('.storage61-row').filter({hasText: name});
  await expect(row).toBeVisible();
  await row.getByRole('button', {name: '测试连接'}).click();
  await expect(row.getByText('AVAILABLE')).toBeVisible();

  page.once('dialog', dialog => dialog.accept());
  await row.getByRole('button', {name: '删除'}).click();
  await expect(page.locator('.storage61-row').filter({hasText: name})).toHaveCount(0);
});


test('object storage import exposes Agent flow and posts remote storage_scan contract', async ({page}) => {
  let submitted = null;

  await page.route('**/api/v61/storage-sources', async route => {
    if (route.request().method() !== 'GET') return route.continue();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: [{
          id: 's3-ui',
          name: '生产素材库',
          type: 's3',
          enabled: true,
          is_default: false,
          health_status: 'AVAILABLE',
          health_message: 'available',
          config: {
            endpoint: 'https://s3.example.test',
            bucket: 'materials',
            prefix: '',
            use_ssl: true,
          },
        }],
      }),
    });
  });

  await page.route('**/api/v61/projects/*/storage-imports/scan', async route => {
    submitted = route.request().postDataJSON();
    await route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({
        task_id: 'remote-storage-scan-ui',
        project_id: 'browser-project',
        kind: 'MATERIAL_IMPORT',
        status: 'AWAITING_CONFIRMATION',
        progress: 48,
        stage: 'REMOTE_MATERIAL_REVIEWING',
        current_item: 'datasets/fire/2026/a.jpg',
        mode: 'storage_scan',
        execution_mode: 'agent',
        storage_source_id: 's3-ui',
        import_format: 'coco',
        prefix: 'datasets/fire/2026',
        recursive: true,
        metrics: {},
        result: {
          scanned_files: 1,
          importable_images: 1,
          duplicates: 0,
          failed: 0,
        },
      }),
    });
  });

  await openStoragePage(page);

  await page.getByRole('button', {name: '从存储导入素材'}).click();
  await expect(page.getByRole('button', {name: '对象存储目录'})).toHaveClass(/on/);
  await expect(page.locator('#si61RemoteSource')).toHaveValue('s3-ui');
  await expect(page.getByText('由远程素材节点执行')).toBeVisible();
  await expect(page.getByText(/中央端保管长期存储凭据/)).toBeVisible();

  await page.locator('#si61RemotePrefix').fill('datasets/fire/2026');
  await expect(page.locator('#si61Format')).toHaveValue('images');
  await expect(page.locator('#si61Format option[value="auto"]')).toBeDisabled();
  await expect(page.locator('#si61Format option[value="coco"]')).toBeEnabled();
  await expect(page.locator('#si61Format option[value="voc"]')).toBeEnabled();
  await page.locator('#si61Format').selectOption('coco');
  await expect(page.locator('#si61DatasetYaml')).toBeDisabled();
  await page.getByRole('button', {name: '开始远程扫描'}).click();

  await expect.poll(() => submitted).not.toBeNull();
  expect(submitted).toEqual({
    mode: 'storage_scan',
    execution_mode: 'agent',
    import_format: 'coco',
    storage_source_id: 's3-ui',
    prefix: 'datasets/fire/2026',
    recursive: true,
  });
  await expect(page.locator('#si61Status')).toContainText('扫描完成，等待确认建立素材索引');
});
