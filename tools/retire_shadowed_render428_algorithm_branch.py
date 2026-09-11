from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected exactly 1 match, found {count}')
    return text.replace(old, new, 1)


app_path = Path('static/app.js')
app = app_path.read_text(encoding='utf-8')
old = """  const renderBase428=render;
  render=function(){if(state.page==='算法列表'){renderNav();renderTop();renderSummary();renderAlgorithms423();return}if(state.page==='训练任务'){renderNav();renderTop();renderSummary();renderTraining423();return}renderBase428()};
"""
new = """  const renderBase428=render;
  render=function(){if(state.page==='训练任务'){renderNav();renderTop();renderSummary();renderTraining423();return}renderBase428()};
"""
app = replace_once(app, old, new, 'shadowed renderBase428 algorithm branch')
if old in app:
    raise SystemExit('shadowed renderBase428 algorithm branch remains')
if app.count(new) != 1:
    raise SystemExit(f'live renderBase428 training owner count mismatch: {app.count(new)}')
outer_algorithm = "render=function(){renderNav();renderTop();renderSummary();if(state.page==='算法列表'){renderAlgorithms423();return}if(state.page==='数据集'){renderDatasets424();return}oldRender412()};"
if outer_algorithm not in app:
    raise SystemExit('oldRender412 algorithm owner is missing')
app_path.write_text(app, encoding='utf-8')

index_path = Path('static/index.html')
index = index_path.read_text(encoding='utf-8')
index = replace_once(index, '/static/app.js?v=42.25.61', '/static/app.js?v=42.25.62', 'app cache bump')
index_path.write_text(index, encoding='utf-8')

test_path = Path('tests/frontend/render-owner-retirement.test.mjs')
test_text = test_path.read_text(encoding='utf-8')
name = 'renderBase428 keeps only its live training route branch'
if name in test_text:
    raise SystemExit('renderBase428 branch test already exists')
contract = r'''

test('renderBase428 keeps only its live training route branch', () => {
  assert.equal(
    app.includes("render=function(){if(state.page==='算法列表'){renderNav();renderTop();renderSummary();renderAlgorithms423();return}if(state.page==='训练任务'){renderNav();renderTop();renderSummary();renderTraining423();return}renderBase428()};"),
    false,
  );
  assert.equal(
    app.includes("render=function(){if(state.page==='训练任务'){renderNav();renderTop();renderSummary();renderTraining423();return}renderBase428()};"),
    true,
  );
});

test('oldRender412 remains the sole outer algorithm-list route owner', () => {
  assert.equal(
    app.includes("render=function(){renderNav();renderTop();renderSummary();if(state.page==='算法列表'){renderAlgorithms423();return}if(state.page==='数据集'){renderDatasets424();return}oldRender412()};"),
    true,
  );
});
'''
test_path.write_text(test_text.rstrip() + contract, encoding='utf-8')

print('retired shadowed algorithm branch from live renderBase428 wrapper')
