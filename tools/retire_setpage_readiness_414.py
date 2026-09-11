from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected exactly 1 match, found {count}')
    return text.replace(old, new, 1)


app_path = Path('static/app.js')
app = app_path.read_text(encoding='utf-8')
readiness = """  // Navigation may be clicked while the startup snapshot is still loading.
  // Wait for that snapshot so actions never run with an undefined project id.
  const setPageReady414=window.setPage;
  window.setPage=async function(page){if(!state.uiReady&&window.__v53InitPromise)await window.__v53InitPromise;return setPageReady414(page)};
  try{setPage=window.setPage}catch(_){}

"""
if app.count(readiness) != 1:
    raise SystemExit(f'setPageReady414 block count mismatch: {app.count(readiness)}')
if app.count('const baseSetPage417=window.setPage;') != 1:
    raise SystemExit('baseSetPage417 must remain exactly once')
app = app.replace(readiness, '', 1)
if 'setPageReady414' in app:
    raise SystemExit('setPageReady414 token remains after migration')
app_path.write_text(app, encoding='utf-8')

index_path = Path('static/index.html')
index = index_path.read_text(encoding='utf-8')
index = replace_once(index, '/static/app.js?v=42.25.54', '/static/app.js?v=42.25.55', 'app cache bump')
index_path.write_text(index, encoding='utf-8')

guard_path = Path('tests/frontend/retired-pre-v424-setpage-guard.test.mjs')
guard = guard_path.read_text(encoding='utf-8')
old = """test('post-v42.7 readiness and sidebar owners remain after alias-owner cleanup', () => {
  assert.equal(app.includes('const setPageReady414=window.setPage;'), true, 'startup readiness owner must remain');
  assert.equal(app.includes('const baseSetPage417=window.setPage;'), true, 'V417 sidebar owner must remain');
});
"""
new = """test('classic startup readiness owner cannot return after readiness moved to final navigation', () => {
  assert.equal(app.includes('setPageReady414'), false, 'classic startup readiness owner must remain retired');
  assert.equal(navigation.includes('waitForNavigationReady'), true, 'final navigation must own startup readiness');
});

test('V417 sidebar owner remains after readiness cleanup', () => {
  assert.equal(app.includes('const baseSetPage417=window.setPage;'), true, 'V417 sidebar owner must remain');
});
"""
guard = replace_once(guard, old, new, 'advance readiness retirement guard')
guard_path.write_text(guard, encoding='utf-8')

print('retired setPageReady414; preserved baseSetPage417 and advanced permanent test guard')
