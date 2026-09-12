from pathlib import Path

p = Path('tests/browser/algorithm-list-performance.spec.mjs')
s = p.read_text(encoding='utf-8')
old = "  await expect(page.locator('#modalBody')).toContainText('publish-r20b.pt');\n  await expect(page.locator('#algoSel')).toHaveValue('algo-publish-r20b');"
new = "  await expect(page.locator('#modalBody input[disabled]').first()).toHaveValue('publish-r20b.pt');\n  await expect(page.locator('#algoSel')).toHaveValue('algo-publish-r20b');"
if s.count(old) != 1:
    raise SystemExit(f'R20b baseline assertion anchor count={s.count(old)}')
p.write_text(s.replace(old, new, 1), encoding='utf-8')
print('R20b publish baseline assertion corrected to input value semantics')
