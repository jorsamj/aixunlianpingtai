from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected exactly 1 match, found {count}')
    return text.replace(old, new, 1)


app_path = Path('static/app.js')
app = app_path.read_text(encoding='utf-8')
old = """  const previousRender61=render;
  render=function(){if(state.page==='素材存储配置'){renderNav();renderTop();renderSummary();renderStorageSources61();return}previousRender61()};
"""
app = replace_once(app, old, '', 'previousRender61 wrapper')
if 'previousRender61' in app:
    raise SystemExit('previousRender61 token remains after retirement')
final_owner = """  const finalRender=render;
  render=function(){if(state.page==='素材存储配置'){renderNav();renderTop();renderSummary();renderStorageSources61();return}finalRender()};"""
if app.count(final_owner) != 1:
    raise SystemExit(f'final storage render owner count mismatch: {app.count(final_owner)}')
app_path.write_text(app, encoding='utf-8')

index_path = Path('static/index.html')
index = index_path.read_text(encoding='utf-8')
index = replace_once(index, '/static/app.js?v=42.25.59', '/static/app.js?v=42.25.60', 'app cache bump')
index_path.write_text(index, encoding='utf-8')

test_path = Path('tests/frontend/render-owner-retirement.test.mjs')
test_text = test_path.read_text(encoding='utf-8')
name = 'shadowed early storage render wrapper cannot return'
if name in test_text:
    raise SystemExit('storage render owner test already exists')
contract = r'''

test('shadowed early storage render wrapper cannot return', () => {
  assert.equal(app.includes('previousRender61'), false);
  assert.equal(
    app.includes("render=function(){if(state.page==='素材存储配置'){renderNav();renderTop();renderSummary();renderStorageSources61();return}previousRender61()};"),
    false,
  );
});

test('final storage render owner remains the sole storage route wrapper', () => {
  assert.equal(app.includes('const finalRender=render;'), true);
  assert.equal(
    app.includes("render=function(){if(state.page==='素材存储配置'){renderNav();renderTop();renderSummary();renderStorageSources61();return}finalRender()};"),
    true,
  );
});
'''
test_path.write_text(test_text.rstrip() + contract, encoding='utf-8')

print('retired shadowed previousRender61 wrapper; finalRender remains sole storage route owner')
