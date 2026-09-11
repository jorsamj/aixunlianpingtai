from pathlib import Path

path = Path('tests/browser/navigation-stability.spec.mjs')
text = path.read_text(encoding='utf-8')
name = "storage configuration route is rendered by the final storage owner"
if name in text:
    raise SystemExit('storage render browser contract already exists')

contract = r'''

test('storage configuration route is rendered by the final storage owner', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});

  await page.evaluate(() => window.setPage('素材存储配置'));
  await expect(page.locator('#title')).toContainText('素材存储配置');
  await expect(page.locator('.storage61-shell')).toBeVisible({timeout: 10_000});
  await expect(page.locator('#storage61Rows')).toBeVisible();

  expect(pageErrors).toEqual([]);
});
'''
path.write_text(text.rstrip() + contract, encoding='utf-8')
print('added storage render browser contract exactly once')
