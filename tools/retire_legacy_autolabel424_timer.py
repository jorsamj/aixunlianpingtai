from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected exactly 1 match, found {count}')
    return text.replace(old, new, 1)


app_path = Path('static/app.js')
app = app_path.read_text(encoding='utf-8')

legacy_timer = "if(state.prelabel424.some(t=>['queued','running'].includes(t.status)))setTimeout(()=>{if(state.page==='自动标注')renderAutoLabel424()},1800)"
app = replace_once(app, legacy_timer, '', 'legacy AutoLabel424 self-refresh timer')

if legacy_timer in app:
    raise SystemExit('legacy AutoLabel424 self-refresh timer remains')
if "state.page==='自动标注'" in app:
    raise SystemExit('legacy auto-label page-state predicate remains in app.js')
if "render=function(){renderNav();renderTop();renderSummary();if(state.page==='自动标注及清洗'){renderOps427();return}renderBase427()}" not in app:
    raise SystemExit('canonical 自动标注及清洗 renderBase427 owner is missing')
if 'window.AutoLabelPollRuntime' not in app and 'AutoLabelPollRuntime' not in app:
    # The runtime may be loaded from main.mjs rather than declared in app.js; do not use this as the primary owner proof.
    pass

app_path.write_text(app, encoding='utf-8')

index_path = Path('static/index.html')
index = index_path.read_text(encoding='utf-8')
index = replace_once(index, '/static/app.js?v=42.25.64', '/static/app.js?v=42.25.65', 'app cache bump')
index_path.write_text(index, encoding='utf-8')

test_path = Path('tests/frontend/render-owner-retirement.test.mjs')
test_text = test_path.read_text(encoding='utf-8')
name = 'legacy AutoLabel424 self-refresh timer cannot return'
if name in test_text:
    raise SystemExit('legacy AutoLabel424 timer retirement test already exists')
contract = r'''

test('legacy AutoLabel424 self-refresh timer cannot return', () => {
  assert.equal(
    app.includes("if(state.prelabel424.some(t=>['queued','running'].includes(t.status)))setTimeout(()=>{if(state.page==='自动标注')renderAutoLabel424()},1800)"),
    false,
  );
  assert.equal(app.includes("state.page==='自动标注'"), false);
});

test('canonical AutoLabel render route remains the only page-state route', () => {
  assert.equal(
    app.includes("render=function(){renderNav();renderTop();renderSummary();if(state.page==='自动标注及清洗'){renderOps427();return}renderBase427()}"),
    true,
  );
});
'''
test_path.write_text(test_text.rstrip() + contract, encoding='utf-8')

print('retired unreachable legacy AutoLabel424 self-refresh timer')
