from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected exactly 1 match, found {count}')
    return text.replace(old, new, 1)


bootstrap = 'function setPage(p){state.page=p;render()} window.setPage=setPage;\n'
app_path = Path('static/app.js')
app = app_path.read_text(encoding='utf-8')
if app.count(bootstrap) != 1:
    raise SystemExit(f'bootstrap setPage count mismatch: {app.count(bootstrap)}')
app = app.replace(bootstrap, '', 1)
if 'function setPage(p){state.page=p;render()} window.setPage=setPage;' in app:
    raise SystemExit('bootstrap setPage remains after retirement')
app_path.write_text(app, encoding='utf-8')

index_path = Path('static/index.html')
index = index_path.read_text(encoding='utf-8')
index = replace_once(index, '/static/app.js?v=42.25.56', '/static/app.js?v=42.25.57', 'app cache bump')
index_path.write_text(index, encoding='utf-8')

guard_path = Path('tests/frontend/retired-sidebar-setpage-guard.test.mjs')
guard = guard_path.read_text(encoding='utf-8')
old_test = """test('initial bootstrap setPage binding remains for its separate liveness audit', () => {
  assert.equal(app.includes('function setPage(p){state.page=p;render()} window.setPage=setPage;'), true);
});
"""
new_test = """test('initial bootstrap setPage binding cannot return after named actual navigation owner migration', () => {
  assert.equal(app.includes('function setPage(p){state.page=p;render()} window.setPage=setPage;'), false);
  assert.equal(navigation.includes('performNavigation'), true, 'final navigation must own actual page application');
  assert.equal(
    main.includes(`performNavigation: page => {\n    state.page = page;\n    render();\n  },`),
    true,
    'main runtime must wire exactly one named state.page mutation + render owner',
  );
});
"""
guard = replace_once(guard, old_test, new_test, 'bootstrap retirement guard')
guard_path.write_text(guard, encoding='utf-8')

print('retired initial bootstrap setPage; named performNavigation remains sole actual navigation owner')
