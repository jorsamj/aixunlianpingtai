from pathlib import Path

SPEC = Path('tests/browser/navigation-stability.spec.mjs')
text = SPEC.read_text(encoding='utf-8')
name = "modal file input beautification survives modal lifecycle ownership"
if name in text:
    raise SystemExit('modal file-input browser contract already exists')

contract = r'''

test('modal file input beautification survives modal lifecycle ownership', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});

  await page.evaluate(() => window.modal(
    '文件选择器生命周期测试',
    '<div class="form"><div class="field"><label>选择文件</label><input id="modalProbeFile" type="file" class="file" accept=".zip"></div></div>',
    true,
  ));

  await expect(page.locator('#modal')).not.toHaveClass(/hidden/);
  await expect(page.locator('#modalProbeFile')).toHaveClass(/native-file426/);
  await expect(page.locator('#modalProbeFile + .filepicker426')).toBeVisible();
  await expect(page.locator('#modalProbeFile + .filepicker426 .filepicker426-btn')).toContainText('选择本地文件');
  await expect(page.locator('#modalProbeFile + .filepicker426 .filepicker426-name')).toContainText('未选择');

  expect(pageErrors).toEqual([]);
});
'''

SPEC.write_text(text.rstrip() + contract + '\n', encoding='utf-8')
print('added permanent modal file-input beautification browser contract')
