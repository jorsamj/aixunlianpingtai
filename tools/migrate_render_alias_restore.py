from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected exactly 1 match, found {count}')
    return text.replace(old, new, 1)


app_path = Path('static/app.js')
app = app_path.read_text(encoding='utf-8')

old_restore = """    const saved=lastState.projectId || '';
    state.project=projects.find(p=>p.id===saved) || projects[0] || null;
    if(lastState.page && RENDER_MAP()[lastState.page]) state.page=lastState.page;
    if(lastState.datasetId) state.datasetId=lastState.datasetId;
"""
new_restore = """    const saved=lastState.projectId || '';
    state.project=projects.find(p=>p.id===saved) || projects[0] || null;
    const restoredPage=lastState.page==='自动标注'?'自动标注及清洗':lastState.page;
    if(restoredPage && (RENDER_MAP()[restoredPage]||restoredPage==='自动标注及清洗')) state.page=restoredPage;
    if(lastState.datasetId) state.datasetId=lastState.datasetId;
"""
app = replace_once(app, old_restore, new_restore, 'historical page restore canonicalization')

old_render = "render=function(){if(state.page==='自动标注')state.page='自动标注及清洗';renderNav();renderTop();renderSummary();if(state.page==='自动标注及清洗'){renderOps427();return}renderBase427()};"
new_render = "render=function(){renderNav();renderTop();renderSummary();if(state.page==='自动标注及清洗'){renderOps427();return}renderBase427()};"
app = replace_once(app, old_render, new_render, 'v42.7 render alias mutation')

if "if(state.page==='自动标注')state.page='自动标注及清洗'" in app:
    raise SystemExit('render-level auto-label alias mutation still remains')
if "const restoredPage=lastState.page==='自动标注'?'自动标注及清洗':lastState.page;" not in app:
    raise SystemExit('historical restore canonicalization missing')
app_path.write_text(app, encoding='utf-8')

index_path = Path('static/index.html')
index = index_path.read_text(encoding='utf-8')
index = replace_once(index, '/static/app.js?v=42.25.57', '/static/app.js?v=42.25.58', 'app cache bump')
index_path.write_text(index, encoding='utf-8')

guard_path = Path('tests/frontend/render-alias-restore.test.mjs')
guard_path.write_text("""import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

test('historical auto-label page alias is canonicalized at restore boundary', () => {
  assert.equal(
    app.includes(\"const restoredPage=lastState.page==='自动标注'?'自动标注及清洗':lastState.page;\"),
    true,
  );
  assert.equal(
    app.includes(\"if(restoredPage && (RENDER_MAP()[restoredPage]||restoredPage==='自动标注及清洗')) state.page=restoredPage;\"),
    true,
  );
});

test('render chain cannot mutate legacy auto-label route state', () => {
  assert.equal(
    app.includes(\"if(state.page==='自动标注')state.page='自动标注及清洗'\"),
    false,
  );
});
""", encoding='utf-8')

print('migrated historical auto-label alias to restore boundary and retired render mutation')
