from pathlib import Path

SPEC = Path('tests/browser/navigation-stability.spec.mjs')
text = SPEC.read_text(encoding='utf-8')
name = "file input beautification survives page render lifecycle ownership"
if name in text:
    raise SystemExit('file input page-render browser contract already exists')

contract = r'''

test('file input beautification survives page render lifecycle ownership', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});

  await page.evaluate(() => window.setPage('测试发布'));
  await expect(page.locator('#title')).toContainText('测试发布');
  await expect(page.locator('#predFile')).toHaveClass(/native-file426/);
  await expect(page.locator('#predFile + .filepicker426')).toBeVisible();
  await expect(page.locator('#predFile + .filepicker426 .filepicker426-btn')).toContainText('选择图片');

  expect(pageErrors).toEqual([]);
});
'''

SPEC.write_text(text.rstrip() + contract + '\n', encoding='utf-8')
print('added permanent page-render file-input beautification browser contract')
