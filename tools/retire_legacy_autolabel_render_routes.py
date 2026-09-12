from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected exactly 1 match, found {count}')
    return text.replace(old, new, 1)


app_path = Path('static/app.js')
app = app_path.read_text(encoding='utf-8')

render422_branch = "    if(state.page==='自动标注'){renderNav();renderTop();renderSummary();renderAutoLabel422();return}\n"
render424_branch = "    if(state.page==='自动标注'){renderAutoLabel424();return}\n"
canonical_owner = "render=function(){renderNav();renderTop();renderSummary();if(state.page==='自动标注及清洗'){renderOps427();return}renderBase427()}"
restore_boundary = "const restoredPage=lastState.page==='自动标注'?'自动标注及清洗':lastState.page;"

app = replace_once(app, render422_branch, '', 'v42.2 legacy auto-label route branch')
app = replace_once(app, render424_branch, '', 'v42.4 legacy auto-label route branch')

for retired, label in (
    (render422_branch, 'v42.2 legacy auto-label route branch'),
    (render424_branch, 'v42.4 legacy auto-label route branch'),
):
    if retired in app:
        raise SystemExit(f'{label} remains')
if canonical_owner not in app:
    raise SystemExit('canonical 自动标注及清洗 renderBase427 owner is missing')
if restore_boundary not in app:
    raise SystemExit('historical auto-label restore canonicalization is missing')
if "state.page='自动标注'" in app or 'state.page="自动标注"' in app:
    raise SystemExit('direct legacy auto-label state.page writer exists')

app_path.write_text(app, encoding='utf-8')

index_path = Path('static/index.html')
index = index_path.read_text(encoding='utf-8')
index = replace_once(index, '/static/app.js?v=42.25.62', '/static/app.js?v=42.25.63', 'app cache bump')
index_path.write_text(index, encoding='utf-8')

test_path = Path('tests/frontend/render-owner-retirement.test.mjs')
test_text = test_path.read_text(encoding='utf-8')
name = 'legacy auto-label render route owners cannot return'
if name in test_text:
    raise SystemExit('legacy auto-label route retirement test already exists')
contract = r'''

test('legacy auto-label render route owners cannot return', () => {
  assert.equal(
    app.includes("if(state.page==='自动标注'){renderNav();renderTop();renderSummary();renderAutoLabel422();return}"),
    false,
  );
  assert.equal(
    app.includes("if(state.page==='自动标注'){renderAutoLabel424();return}"),
    false,
  );
});

test('canonical auto-label cleanup render route remains live', () => {
  assert.equal(
    app.includes("render=function(){renderNav();renderTop();renderSummary();if(state.page==='自动标注及清洗'){renderOps427();return}renderBase427()}"),
    true,
  );
});
'''
test_path.write_text(test_text.rstrip() + contract, encoding='utf-8')

print('retired unreachable legacy 自动标注 render route owners')
