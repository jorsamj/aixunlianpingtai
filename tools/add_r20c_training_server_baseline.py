from pathlib import Path

p = Path('tests/browser/navigation-stability.spec.mjs')
s = p.read_text(encoding='utf-8')
marker = "test('training server connection keeps existing form and payload behavior'"
if marker in s:
    raise SystemExit('R20c training-server baseline already present')
addition = r'''

test('training server connection keeps existing form and payload behavior', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await page.evaluate(() => window.setPage('训练资源'));
  await expect(page.locator('#title')).toContainText('训练资源');
  await expect(page.locator('#quickServerUrl')).toBeVisible({timeout: 10_000});

  let submittedBody = null;
  await page.route('**/api/train_servers', async route => {
    if (route.request().method() !== 'POST') return route.continue();
    submittedBody = route.request().postDataJSON();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'server-r20c',
        name: submittedBody?.name || 'R20c训练服务器',
        base_url: submittedBody?.base_url || 'http://127.0.0.1:18020',
        status: 'configured',
      }),
    });
  });

  await page.locator('#quickServerUrl').fill('http://127.0.0.1:18020');
  await page.getByRole('button', {name: '接入服务器'}).click();
  await expect(page.locator('#modal')).not.toHaveClass(/hidden/);
  await expect(page.locator('#surl')).toHaveValue('http://127.0.0.1:18020');
  await page.locator('#sname').fill('R20c训练服务器');
  await page.locator('#modalBody').getByRole('button', {name: '保存'}).click();

  await expect(page.locator('#modal')).toHaveClass(/hidden/);
  await expect(page.locator('#toast')).toContainText('已保存服务器');
  expect(submittedBody).toEqual({
    name: 'R20c训练服务器',
    base_url: 'http://127.0.0.1:18020',
  });
  expect(pageErrors).toEqual([]);
});
'''
p.write_text(s.rstrip() + addition + '\n', encoding='utf-8')
print('R20c training server behavior baseline added')
