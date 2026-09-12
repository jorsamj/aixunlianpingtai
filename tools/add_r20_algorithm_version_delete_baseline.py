from pathlib import Path

p = Path('tests/browser/algorithm-list-performance.spec.mjs')
s = p.read_text(encoding='utf-8')
marker = "test('algorithm version deletion stays functional before scoped refresh migration'"
if marker in s:
    raise SystemExit('R20 baseline already present')
addition = r'''

test('algorithm version deletion stays functional before scoped refresh migration', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await page.evaluate(() => window.setPage('算法列表'));
  await expect(page.locator('#alg412List')).toBeVisible({timeout: 10_000});

  const projectId = await page.evaluate(() => state.project?.id);
  expect(projectId).toBeTruthy();
  const encoded = encodeURIComponent(projectId);
  const requests = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) requests.push(`${request.method()} ${url.pathname}${url.search}`);
  });

  await page.route(`**/api/v12/projects/${encoded}/algorithms/algo-version-delete/versions/version-delete-1`, async route => {
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({ok: true})});
  });
  await page.route(`**/api/v12/projects/${encoded}/algorithms`, async route => {
    if (route.request().method() !== 'GET') return route.continue();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({items: [{
        id: 'algo-version-delete',
        name: '版本删除验收算法',
        remark: 'R20 behavior baseline',
        industry: '测试',
        algorithm_type: 'yolo_ultralytics',
        versions: [],
      }]}),
    });
  });
  await page.route(`**/api/projects/${encoded}/jobs`, async route => {
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify([])});
  });

  await page.evaluate(() => {
    state.algorithms = [{
      id: 'algo-version-delete',
      name: '版本删除验收算法',
      remark: 'R20 behavior baseline',
      industry: '测试',
      algorithm_type: 'yolo_ultralytics',
      versions: [{
        id: 'version-delete-1',
        version_name: '20260912100000',
        model_name: 'best.pt',
        size_mb: 5.2,
        created_at: '2026-09-12T10:00:00Z',
      }],
    }];
    state.jobs = [];
    window.renderAlgorithms423();
    window.viewAlgorithm423('algo-version-delete');
  });

  await expect(page.locator('#modal')).not.toHaveClass(/hidden/);
  await expect(page.locator('#modalBody')).toContainText('20260912100000');
  page.once('dialog', dialog => dialog.accept());
  await page.locator('#modalBody').getByRole('button', {name: '删除版本'}).click();

  await expect(page.locator('#modal')).toHaveClass(/hidden/);
  await expect(page.locator('#alg412List')).toContainText('版本删除验收算法');
  await expect(page.locator('#alg412List')).not.toContainText('20260912100000');
  expect(requests.some(row => row === `DELETE /api/v12/projects/${projectId}/algorithms/algo-version-delete/versions/version-delete-1`)).toBe(true);
  expect(pageErrors).toEqual([]);
});
'''
p.write_text(s.rstrip() + addition + '\n', encoding='utf-8')
print('R20 algorithm version delete behavior baseline added')
