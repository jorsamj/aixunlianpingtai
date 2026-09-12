from pathlib import Path

app_path = Path('static/app.js')
index_path = Path('static/index.html')
test_path = Path('tests/frontend/model-config-save-refresh-owner.test.mjs')

app = app_path.read_text(encoding='utf-8')
start_marker = "  window.saveModelConfig427=async function(id=''){"
end_marker = "\n\n  // ----- training config: real AI intervention -----"
start = app.find(start_marker)
if start < 0:
    raise SystemExit('final saveModelConfig427 owner not found')
end = app.find(end_marker, start)
if end < 0:
    raise SystemExit('saveModelConfig427 owner boundary not found')
owner = app[start:end]
if owner.count('await loadRelated();') != 1:
    raise SystemExit(f'expected exactly one loadRelated in final saveModelConfig427 owner, got {owner.count("await loadRelated();")}')
if 'const saved=await api(' in owner:
    raise SystemExit('R20f product migration already applied')

owner = owner.replace('try{await api(', 'try{const saved=await api(', 1)
old_tail = ");closeModal();await loadRelated();renderModelConfigPageV35();toast('模型配置已保存')"
new_tail = ");if(saved?.id){const rows=state.modelConfigs||[],i=rows.findIndex(x=>String(x.id)===String(saved.id));state.modelConfigs=i>=0?rows.map((x,n)=>n===i?saved:x):[saved,...rows]}closeModal();renderModelConfigPageV35();toast('模型配置已保存')"
if old_tail not in owner:
    raise SystemExit('final saveModelConfig427 success tail drifted')
owner = owner.replace(old_tail, new_tail, 1)
if 'loadRelated' in owner or 'loadAll' in owner:
    raise SystemExit('broad refresh remains in final saveModelConfig427 owner')
app = app[:start] + owner + app[end:]
app_path.write_text(app, encoding='utf-8')

index = index_path.read_text(encoding='utf-8')
old_cache = '/static/app.js?v=42.25.81'
new_cache = '/static/app.js?v=42.25.82'
if old_cache not in index:
    raise SystemExit('expected app.js cache 42.25.81 not found')
index_path.write_text(index.replace(old_cache, new_cache, 1), encoding='utf-8')

test_path.write_text(r'''import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync('static/app.js', 'utf8');
const startMarker = "  window.saveModelConfig427=async function(id=''){";
const endMarker = '\n\n  // ----- training config: real AI intervention -----';
const start = app.indexOf(startMarker);
const end = app.indexOf(endMarker, start);
assert.ok(start >= 0 && end > start, 'final saveModelConfig427 owner must remain addressable');
const owner = app.slice(start, end);

test('final model config save owner uses authoritative mutation result without broad related refresh', () => {
  assert.equal((app.match(/window\.saveModelConfig427=async function/g) || []).length, 1);
  assert.match(owner, /const saved=await api\(/);
  assert.match(owner, /if\(saved\?\.id\)/);
  assert.match(owner, /state\.modelConfigs=i>=0\?rows\.map\(\(x,n\)=>n===i\?saved:x\):\[saved,\.\.\.rows\]/);
  assert.doesNotMatch(owner, /loadRelated\s*\(/);
  assert.doesNotMatch(owner, /loadAll\s*\(/);
});

test('final model config modal still wires save to saveModelConfig427', () => {
  const finalOpen = app.lastIndexOf('window.openModelConfigModalV35=function');
  assert.ok(finalOpen >= 0);
  const region = app.slice(finalOpen, start);
  assert.match(region, /onclick="saveModelConfig427\('\$\{id\}'\)"/);
});
''', encoding='utf-8')
