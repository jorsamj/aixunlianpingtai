from pathlib import Path

APP = Path('static/app.js')
INDEX = Path('static/index.html')
TEST = Path('tests/frontend/legacy-dataset-group-owner.test.mjs')

app = APP.read_text(encoding='utf-8')
index = INDEX.read_text(encoding='utf-8')
original_size = len(app.encode('utf-8'))

final_route = "if(state.page==='数据集'){renderDatasets424();return}"
if final_route not in app:
    raise SystemExit('final dataset routing contract missing')
if app.count('function renderDatasets(){') != 2:
    raise SystemExit(f'expected exactly two classic renderDatasets generations, got {app.count("function renderDatasets(){")}')

expected_counts = {
    'window.selectDataset=': 2,
    'window.newDataset=': 1,
    'window.saveDataset=': 1,
    'window.editDataset=': 1,
    'window.saveEditDataset=': 1,
    'window.delDataset=': 1,
    'oldSelectDataset': 1,
}
for token, expected in expected_counts.items():
    if app.count(token) != expected:
        raise SystemExit(f'expected {expected} legacy dataset owner token(s) {token}, got {app.count(token)}')

current_dataset = "function currentDataset(){return state.datasets.find(d=>d.id===state.datasetId)||state.datasets[0]}\n"
if app.count(current_dataset) != 1:
    raise SystemExit('currentDataset legacy helper anchor changed')
app = app.replace(current_dataset, '', 1)

first_start = app.find('function renderDatasets(){')
first_end = app.find('\nwindow.selectDataset=', first_start)
if first_start < 0 or first_end < 0:
    raise SystemExit('first classic dataset renderer anchors not found')
first_block = app[first_start:first_end]
for token in ('newDataset()', 'selectDataset(', 'editDataset(', 'delDataset('):
    if token not in first_block:
        raise SystemExit(f'first classic dataset renderer missing expected legacy token {token}')

delegate = 'function renderDatasets(){return window.renderDatasets424?.()}\n'
app = app[:first_start] + delegate + app[first_end:]

crud_start = app.find('window.selectDataset=')
crud_end = app.find('\nwindow.uploadImages=', crud_start)
if crud_start < 0 or crud_end < 0:
    raise SystemExit('legacy dataset CRUD anchors not found')
crud_block = app[crud_start:crud_end]
if 'await reload()' not in crud_block:
    raise SystemExit('legacy dataset CRUD no longer matches broad-reload generation')
for token in ('window.selectDataset=', 'window.newDataset=', 'window.saveDataset=', 'window.editDataset=', 'window.saveEditDataset=', 'window.delDataset='):
    if token not in crud_block:
        raise SystemExit(f'legacy CRUD block missing {token}')
app = app[:crud_start] + app[crud_end + 1:]

persist_wrapper = """  const oldSelectDataset=window.selectDataset;
  window.selectDataset=async function(id){
    state.datasetId=id;
    saveUiState();
    await loadRelated();
    render();
  };
"""
if app.count(persist_wrapper) != 1:
    raise SystemExit('dataset persistence wrapper anchor changed')
app = app.replace(persist_wrapper, '', 1)

second_start = app.find('function renderDatasets(){', first_start + len(delegate))
second_end = app.find('\nfunction renderResources(){', second_start)
if second_start < 0 or second_end < 0:
    raise SystemExit('second classic dataset renderer anchors not found')
second_block = app[second_start:second_end]
for token in ('newDataset()', 'selectDataset(', 'bulkMoveMenu()', 'currentDataset()'):
    if token not in second_block:
        raise SystemExit(f'second classic dataset renderer missing expected token {token}')
app = app[:second_start] + app[second_end + 1:]

if app.count('function renderDatasets(){') != 1:
    raise SystemExit('classic dataset renderer count did not collapse to one delegate')
if delegate.strip() not in app:
    raise SystemExit('bounded dataset delegate missing after migration')
for token in [
    'window.selectDataset=',
    'window.newDataset=',
    'window.saveDataset=',
    'window.editDataset=',
    'window.saveEditDataset=',
    'window.delDataset=',
    'oldSelectDataset',
    'currentDataset()',
]:
    if token in app:
        raise SystemExit(f'retired dataset-group surface still present: {token}')
if final_route not in app:
    raise SystemExit('final dataset direct route was damaged')

old_cache = '/static/app.js?v=42.25.84'
new_cache = '/static/app.js?v=42.25.85'
if index.count(old_cache) != 1:
    raise SystemExit('expected app.js cache 42.25.84 exactly once')
index = index.replace(old_cache, new_cache, 1)

TEST.write_text("""import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync('static/app.js', 'utf8');
const index = fs.readFileSync('static/index.html', 'utf8');

const retired = [
  'window.selectDataset=',
  'window.newDataset=',
  'window.saveDataset=',
  'window.editDataset=',
  'window.saveEditDataset=',
  'window.delDataset=',
  'oldSelectDataset',
  'currentDataset()',
];

test('legacy dataset-group CRUD owners stay physically retired', () => {
  for (const token of retired) {
    assert.equal(app.includes(token), false, `retired dataset-group owner reintroduced: ${token}`);
  }
});

test('historical render maps retain only a bounded dataset delegate', () => {
  assert.equal((app.match(/function renderDatasets\\(\\)\\{/g) || []).length, 1);
  assert.match(app, /function renderDatasets\\(\\)\\{return window\\.renderDatasets424\\?\\.\\(\\)\\}/);
  assert.match(app, /if\\(state\\.page==='数据集'\\)\\{renderDatasets424\\(\\);return\\}/);
});

test('R20i cache moves without changing the formal visible version', () => {
  assert.match(index, /app\\.js\\?v=42\\.25\\.85/);
  assert.match(index, /id="versionBadge" class="version-badge">v42\\.24\\.0</);
});
""", encoding='utf-8')

APP.write_text(app, encoding='utf-8')
INDEX.write_text(index, encoding='utf-8')
print(f'R20i migrated legacy dataset-group generation; app.js {original_size} -> {len(app.encode("utf-8"))} bytes')
