from pathlib import Path

path = Path('tests/browser/navigation-stability.spec.mjs')
text = path.read_text(encoding='utf-8')
anchor = "  await page.goto('/');\n  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});\n  await page.evaluate(() => {\n    state.page = '模型配置';"
replacement = "  await page.goto('/');\n  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});\n  await expect.poll(async () => page.evaluate(() => state.uiReady === true), {timeout: 15_000}).toBe(true);\n  await page.evaluate(() => {\n    state.page = '模型配置';"
if replacement in text:
    raise SystemExit('R20f readiness alignment already applied')
if anchor not in text:
    raise SystemExit('R20f baseline readiness anchor not found')
path.write_text(text.replace(anchor, replacement, 1), encoding='utf-8')
