from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected exactly 1 match, found {count}')
    return text.replace(old, new, 1)


app_path = Path('static/app.js')
app = app_path.read_text(encoding='utf-8')
old = """  // Final render override
  const render423Base=render;
  render=function(){
    if(state.page==='算法列表'){renderNav();renderTop();renderSummary();renderAlgorithms423();return}
    if(state.page==='训练任务'){renderNav();renderTop();renderSummary();renderTraining423();window.PollRegistryRuntime?.replaceTrainingJobTimer?.();return}
    render423Base();
  };
"""
app = replace_once(app, old, "  // Algorithm/training routing is owned by the later stable render layers.\n", 'render423Base wrapper')
if 'render423Base' in app:
    raise SystemExit('render423Base token remains after retirement')
for required in ('const renderBase428=render;', 'const oldRender412=render;'):
    if required not in app:
        raise SystemExit(f'outer routing owner missing: {required}')
training_owner = "window.renderTraining425=window.renderTraining424=window.renderTraining423=function()"
if training_owner not in app or 'window.PollRegistryRuntime?.replaceTrainingJobTimer?.()};' not in app:
    raise SystemExit('current training renderer must keep direct PollRegistry ownership')
app_path.write_text(app, encoding='utf-8')

index_path = Path('static/index.html')
index = index_path.read_text(encoding='utf-8')
index = replace_once(index, '/static/app.js?v=42.25.60', '/static/app.js?v=42.25.61', 'app cache bump')
index_path.write_text(index, encoding='utf-8')

test_path = Path('tests/frontend/render-owner-retirement.test.mjs')
test_text = test_path.read_text(encoding='utf-8')
name = 'fully shadowed render423 route wrapper cannot return'
if name in test_text:
    raise SystemExit('render423 retirement test already exists')
contract = r'''

test('fully shadowed render423 route wrapper cannot return', () => {
  assert.equal(app.includes('render423Base'), false);
  assert.equal(
    app.includes("if(state.page==='训练任务'){renderNav();renderTop();renderSummary();renderTraining423();window.PollRegistryRuntime?.replaceTrainingJobTimer?.();return}"),
    false,
  );
});

test('later algorithm/training owners and direct training polling remain', () => {
  assert.equal(app.includes('const renderBase428=render;'), true);
  assert.equal(app.includes('const oldRender412=render;'), true);
  assert.equal(app.includes('window.renderTraining425=window.renderTraining424=window.renderTraining423=function()'), true);
  assert.equal(app.includes('window.PollRegistryRuntime?.replaceTrainingJobTimer?.()};'), true);
});
'''
test_path.write_text(test_text.rstrip() + contract, encoding='utf-8')

print('retired fully shadowed render423Base wrapper')
