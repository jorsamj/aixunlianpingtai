from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected exactly 1 match, found {count}')
    return text.replace(old, new, 1)


app_path = Path('static/app.js')
app = app_path.read_text(encoding='utf-8')

old = """  const renderBase424=render;
  render=function(){
    renderNav();renderTop();renderSummary();
    if(state.page==='质量中心'){renderQualityCenter424();return}
    if(state.page==='数据集'){renderDatasets424();return}
    if(state.page==='视频切帧'){renderVideo424();return}
    if(state.page==='训练任务'){renderTraining424();return}
    // v42.3 pages retain their own final implementations
    if(state.page==='算法列表'){renderAlgorithms423();return}
    // call previous render for deploy/test/config pages, but it will redraw nav/top; acceptable
    renderBase424();
  };
"""
new = """  const renderBase424=render;
  render=function(){
    renderNav();renderTop();renderSummary();
    if(state.page==='质量中心'){renderQualityCenter424();return}
    if(state.page==='视频切帧'){renderVideo424();return}
    // algorithm/data/training routes are owned by later stable wrappers.
    renderBase424();
  };
"""

app = replace_once(app, old, new, 'shadowed renderBase424 route branches')
if old in app:
    raise SystemExit('shadowed renderBase424 route branches remain')
if app.count(new) != 1:
    raise SystemExit(f'live renderBase424 quality/video wrapper count mismatch: {app.count(new)}')

algorithm_data_owner = "render=function(){renderNav();renderTop();renderSummary();if(state.page==='算法列表'){renderAlgorithms423();return}if(state.page==='数据集'){renderDatasets424();return}oldRender412()};"
training_owner = "render=function(){if(state.page==='训练任务'){renderNav();renderTop();renderSummary();renderTraining423();return}renderBase428()};"
if algorithm_data_owner not in app:
    raise SystemExit('oldRender412 algorithm/data owner is missing')
if training_owner not in app:
    raise SystemExit('renderBase428 training owner is missing')

app_path.write_text(app, encoding='utf-8')

index_path = Path('static/index.html')
index = index_path.read_text(encoding='utf-8')
index = replace_once(index, '/static/app.js?v=42.25.63', '/static/app.js?v=42.25.64', 'app cache bump')
index_path.write_text(index, encoding='utf-8')

test_path = Path('tests/frontend/render-owner-retirement.test.mjs')
test_text = test_path.read_text(encoding='utf-8')
name = 'renderBase424 keeps only its live quality and video route branches'
if name in test_text:
    raise SystemExit('renderBase424 branch retirement test already exists')
contract = r'''

test('shadowed renderBase424 algorithm/data/training branches cannot return', () => {
  const retired = `  const renderBase424=render;
  render=function(){
    renderNav();renderTop();renderSummary();
    if(state.page==='质量中心'){renderQualityCenter424();return}
    if(state.page==='数据集'){renderDatasets424();return}
    if(state.page==='视频切帧'){renderVideo424();return}
    if(state.page==='训练任务'){renderTraining424();return}
    // v42.3 pages retain their own final implementations
    if(state.page==='算法列表'){renderAlgorithms423();return}
    // call previous render for deploy/test/config pages, but it will redraw nav/top; acceptable
    renderBase424();
  };`;
  assert.equal(app.includes(retired), false);
});

test('renderBase424 keeps only its live quality and video route branches', () => {
  const live = `  const renderBase424=render;
  render=function(){
    renderNav();renderTop();renderSummary();
    if(state.page==='质量中心'){renderQualityCenter424();return}
    if(state.page==='视频切帧'){renderVideo424();return}
    // algorithm/data/training routes are owned by later stable wrappers.
    renderBase424();
  };`;
  assert.equal(app.includes(live), true);
  assert.equal(app.includes("if(state.page==='质量中心'){renderQualityCenter424();return}"), true);
  assert.equal(app.includes("if(state.page==='视频切帧'){renderVideo424();return}"), true);
});

test('later owners remain authoritative for renderBase424 retired routes', () => {
  assert.equal(
    app.includes("render=function(){renderNav();renderTop();renderSummary();if(state.page==='算法列表'){renderAlgorithms423();return}if(state.page==='数据集'){renderDatasets424();return}oldRender412()};"),
    true,
  );
  assert.equal(
    app.includes("render=function(){if(state.page==='训练任务'){renderNav();renderTop();renderSummary();renderTraining423();return}renderBase428()};"),
    true,
  );
});
'''
test_path.write_text(test_text.rstrip() + contract, encoding='utf-8')

print('retired shadowed algorithm/data/training branches from live renderBase424 wrapper')
