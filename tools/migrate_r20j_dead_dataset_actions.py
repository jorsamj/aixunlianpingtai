from pathlib import Path

APP = Path('static/app.js')
INDEX = Path('static/index.html')
TEST = Path('tests/frontend/legacy-dataset-action-shell.test.mjs')

app = APP.read_text(encoding='utf-8')
index = INDEX.read_text(encoding='utf-8')
original_size = len(app.encode('utf-8'))

retired = {
    'window.uploadImages=': 'uploadImages()',
    'window.autoSplit=': 'autoSplit()',
    'window.buildYolo=': 'buildYolo()',
    'window.checkDatasetQuality=': 'checkDatasetQuality()',
    'window.setImageSplit=': 'setImageSplit(',
}

# These owners belong to an old dataset-action generation. Their call forms are globally absent.
for assignment, call_form in retired.items():
    if app.count(assignment) != 1:
        raise SystemExit(f'expected exactly one assignment for {assignment}, got {app.count(assignment)}')
    if app.count(call_form) != 0:
        raise SystemExit(f'{assignment} is not dead: found call form {call_form} {app.count(call_form)} time(s)')

# Keep live import ownership out of this dead-shell batch.
if app.count('window.doImportData=') != 1:
    raise SystemExit('live doImportData owner count changed; do not retire it in R20j')
if app.count('window.importData=') != 3:
    raise SystemExit('importData generation count changed; audit separately from R20j')
if "if(state.page==='数据集'){renderDatasets424();return}" not in app:
    raise SystemExit('final dataset route missing')

lines = app.splitlines(keepends=True)
for assignment in retired:
    matches = [i for i, line in enumerate(lines) if line.startswith(assignment)]
    if len(matches) != 1:
        raise SystemExit(f'line owner for {assignment} expected once, got {len(matches)}')
    del lines[matches[0]]
app = ''.join(lines)

for assignment in retired:
    if assignment in app:
        raise SystemExit(f'retired dataset action still present: {assignment}')
if 'window.doImportData=' not in app:
    raise SystemExit('live doImportData owner was accidentally removed')

old_cache = '/static/app.js?v=42.25.85'
new_cache = '/static/app.js?v=42.25.86'
if index.count(old_cache) != 1:
    raise SystemExit('expected app.js cache 42.25.85 exactly once')
index = index.replace(old_cache, new_cache, 1)

TEST.write_text("""import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync('static/app.js', 'utf8');
const index = fs.readFileSync('static/index.html', 'utf8');

const retired = [
  'window.uploadImages=',
  'window.autoSplit=',
  'window.buildYolo=',
  'window.checkDatasetQuality=',
  'window.setImageSplit=',
];

test('zero-reference legacy dataset action owners stay physically retired', () => {
  for (const token of retired) {
    assert.equal(app.includes(token), false, `retired dataset action owner reintroduced: ${token}`);
  }
});

test('R20j preserves the final dataset route and bounded renderer delegate', () => {
  assert.match(app, /if\(state\.page==='数据集'\)\{renderDatasets424\(\);return\}/);
  assert.match(app, /function renderDatasets\(\)\{return window\.renderDatasets424\?\.\(\)\}/);
});

test('R20j cache moves without changing the formal visible version', () => {
  assert.match(index, /app\.js\?v=42\.25\.86/);
  assert.match(index, /id="versionBadge" class="version-badge">v42\.24\.0</);
});
""", encoding='utf-8')

APP.write_text(app, encoding='utf-8')
INDEX.write_text(index, encoding='utf-8')
print(f'R20j retired zero-reference dataset actions; app.js {original_size} -> {len(app.encode("utf-8"))} bytes')
