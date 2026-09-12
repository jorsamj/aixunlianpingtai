from pathlib import Path

p=Path('tests/browser/navigation-stability.spec.mjs')
s=p.read_text(encoding='utf-8')
marker="test('base modal post-open content refresh stays functional',"
if marker in s:
    raise SystemExit('R19 baseline already present')
addition=r'''

test('base modal post-open content refresh stays functional', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));
  let listCalls = 0;

  await page.route(/\/api\/v19\/projects\/[^/]+\/import\/jobs$/, async route => {
    if (route.request().method() !== 'GET') return route.continue();
    listCalls += 1;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({items: listCalls === 1 ? [] : [{
        id: 'modal-refresh-job',
        file_name: 'modal-refresh.zip',
        status: 'done',
        stage: '导入完成',
        message: '完成',
        image_count: 2,
        report: {imported_images: 2, annotated_images: 1, boxes: 3, warnings: []},
      }]}),
    });
  });

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await page.evaluate(async () => { await window.openImportDock(); });

  await expect(page.locator('#modal')).not.toHaveClass(/hidden/);
  await expect(page.locator('#modalTitle')).toHaveText('后台导入任务');
  await expect(page.locator('#modalBody')).toContainText('暂无导入任务');

  await page.locator('#modalBody').getByRole('button', {name: '刷新'}).click();
  await expect(page.locator('#modalBody')).toContainText('modal-refresh.zip');
  await expect(page.locator('#modalBody')).toContainText('导入完成');
  expect(listCalls).toBeGreaterThanOrEqual(2);
  expect(pageErrors).toEqual([]);
});
'''
p.write_text(s.rstrip()+addition+'\n',encoding='utf-8')
print('R19 modal refresh baseline added')
