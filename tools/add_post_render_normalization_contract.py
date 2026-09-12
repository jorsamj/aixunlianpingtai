from pathlib import Path

SPEC = Path('tests/browser/navigation-stability.spec.mjs')
text = SPEC.read_text(encoding='utf-8')
name = "modal table wrapping and first-field focus survive normalization ownership"
if name in text:
    raise SystemExit('post-render normalization browser contract already exists')

contract = r'''

test('modal table wrapping and first-field focus survive normalization ownership', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});

  await page.evaluate(() => window.modal(
    '后处理生命周期测试',
    '<div class="form"><table id="normalizationProbeTable" class="table"><tbody><tr><td>probe</td></tr></tbody></table><input id="normalizationProbeInput" class="input"><input id="normalizationProbeSecond" class="input"></div>',
    true,
  ));

  await expect(page.locator('#normalizationProbeTable')).toBeVisible();
  await expect(page.locator('#normalizationProbeTable').locator('xpath=..')).toHaveClass(/table-wrap/);
  await expect(page.locator('#normalizationProbeInput')).toBeFocused();

  expect(pageErrors).toEqual([]);
});
'''

SPEC.write_text(text.rstrip() + contract + '\n', encoding='utf-8')
print('added permanent post-render normalization browser contract')
