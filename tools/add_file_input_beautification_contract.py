from pathlib import Path

SPEC = Path('tests/browser/navigation-stability.spec.mjs')
text = SPEC.read_text(encoding='utf-8')
name = "file input beautification survives page and modal lifecycle ownership"
if name in text:
    raise SystemExit('file input beautification browser contract already exists')

contract = r'''

test('file input beautification survives page and modal lifecycle ownership', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});

  await page.evaluate(() => window.setPage('数据集'));
  await expect(page.locator('#title')).toContainText('数据集');
  await expect(page.locator('#uploadImages')).toHaveClass(/native-file426/);
  await expect(page.locator('#uploadImages + .filepicker426')).toBeVisible();
  await expect(page.locator('#uploadImages + .filepicker426 .filepicker426-btn')).toContainText('选择图片');

  await page.evaluate(() => window.importData());
  await expect(page.locator('#importFile')).toHaveClass(/native-file426/);
  await expect(page.locator('#importFile + .filepicker426')).toBeVisible();
  await expect(page.locator('#importFile + .filepicker426 .filepicker426-btn')).toContainText('选择本地文件');

  expect(pageErrors).toEqual([]);
});
'''

SPEC.write_text(text.rstrip() + contract + '\n', encoding='utf-8')
print('added permanent file-input beautification browser contract')
