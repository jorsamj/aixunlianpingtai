from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected exactly 1 match, found {count}')
    return text.replace(old, new, 1)


app_path = Path('static/app.js')
app = app_path.read_text(encoding='utf-8')
sidebar_owner = """  const baseSetPage417=window.setPage;
  window.setPage=function(page){window.toggleMobileSidebarV37?.(false);return baseSetPage417?.(page)};try{setPage=window.setPage}catch(_){}
"""
if app.count(sidebar_owner) != 1:
    raise SystemExit(f'baseSetPage417 block count mismatch: {app.count(sidebar_owner)}')
bootstrap = 'function setPage(p){state.page=p;render()} window.setPage=setPage;'
if app.count(bootstrap) != 1:
    raise SystemExit(f'initial bootstrap setPage binding must remain exactly once: {app.count(bootstrap)}')
app = app.replace(sidebar_owner, '', 1)
if 'baseSetPage417' in app:
    raise SystemExit('baseSetPage417 token remains after migration')
if app.count(bootstrap) != 1:
    raise SystemExit('initial bootstrap setPage binding changed unexpectedly')
app_path.write_text(app, encoding='utf-8')

index_path = Path('static/index.html')
index = index_path.read_text(encoding='utf-8')
index = replace_once(index, '/static/app.js?v=42.25.55', '/static/app.js?v=42.25.56', 'app cache bump')
index_path.write_text(index, encoding='utf-8')

guard_path = Path('tests/frontend/retired-sidebar-setpage-guard.test.mjs')
guard = guard_path.read_text(encoding='utf-8')
guard = replace_once(
    guard,
    "const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');\n",
    "const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');\nconst navigation = fs.readFileSync(new URL('../../static/modules/navigation-stability.js', import.meta.url), 'utf8');\nconst main = fs.readFileSync(new URL('../../static/main.mjs', import.meta.url), 'utf8');\n",
    'sidebar guard semantic sources',
)
old_test = """test('V417 remains the sole classic mobile-sidebar close owner in the final setPage chain', () => {
  assert.equal(app.includes('const baseSetPage417=window.setPage;'), true);
  assert.equal(
    app.includes('window.setPage=function(page){window.toggleMobileSidebarV37?.(false);return baseSetPage417?.(page)};'),
    true,
  );
});
"""
new_test = """test('V417 classic mobile-sidebar setPage owner cannot return', () => {
  assert.equal(app.includes('baseSetPage417'), false);
  assert.equal(
    app.includes('window.setPage=function(page){window.toggleMobileSidebarV37?.(false);return baseSetPage417?.(page)};'),
    false,
  );
  assert.equal(navigation.includes('beforeInvokeNavigation'), true, 'final navigation must own pre-invoke UI cleanup');
  assert.equal(
    main.includes('beforeInvokeNavigation: () => window.toggleMobileSidebarV37?.(false),'),
    true,
    'mobile sidebar close semantic wiring must remain in the named runtime',
  );
});

test('initial bootstrap setPage binding remains for its separate liveness audit', () => {
  assert.equal(app.includes('function setPage(p){state.page=p;render()} window.setPage=setPage;'), true);
});
"""
guard = replace_once(guard, old_test, new_test, 'advance V417 sidebar retirement guard')
guard_path.write_text(guard, encoding='utf-8')

print('retired baseSetPage417; preserved initial bootstrap setPage and advanced sidebar guard')
