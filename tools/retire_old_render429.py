from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected exactly 1 match, found {count}')
    return text.replace(old, new, 1)


app_path = Path('static/app.js')
app = app_path.read_text(encoding='utf-8')
old = """  // final routing/version
  const oldRender429=render;
  render=function(){if(state.page==='算法列表'){renderNav();renderTop();renderSummary();renderAlgorithms423();return}if(state.page==='数据集'){renderNav();renderTop();renderSummary();renderDatasets424();return}oldRender429()};
"""
app = replace_once(app, old, "  // routing is owned by the later stable render layer.\n", 'oldRender429 wrapper')
if 'oldRender429' in app:
    raise SystemExit('oldRender429 token remains after retirement')
required = "const oldRender412=render;\n  render=function(){renderNav();renderTop();renderSummary();if(state.page==='算法列表'){renderAlgorithms423();return}if(state.page==='数据集'){renderDatasets424();return}oldRender412()};"
if required not in app:
    raise SystemExit('stable oldRender412 routing owner is missing')
app_path.write_text(app, encoding='utf-8')

index_path = Path('static/index.html')
index = index_path.read_text(encoding='utf-8')
index = replace_once(index, '/static/app.js?v=42.25.58', '/static/app.js?v=42.25.59', 'app cache bump')
index_path.write_text(index, encoding='utf-8')

test_path = Path('tests/frontend/render-owner-retirement.test.mjs')
test_path.write_text("""import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

test('fully shadowed v42.9 render wrapper cannot return', () => {
  assert.equal(app.includes('oldRender429'), false);
  assert.equal(
    app.includes("render=function(){if(state.page==='算法列表'){renderNav();renderTop();renderSummary();renderAlgorithms423();return}if(state.page==='数据集'){renderNav();renderTop();renderSummary();renderDatasets424();return}oldRender429()};"),
    false,
  );
});

test('later stable renderer remains the algorithm/data routing owner', () => {
  assert.equal(app.includes('const oldRender412=render;'), true);
  assert.equal(
    app.includes("render=function(){renderNav();renderTop();renderSummary();if(state.page==='算法列表'){renderAlgorithms423();return}if(state.page==='数据集'){renderDatasets424();return}oldRender412()};"),
    true,
  );
});
""", encoding='utf-8')

print('retired fully shadowed oldRender429 wrapper')
