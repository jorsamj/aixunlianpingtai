from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected exactly 1 match, found {count}')
    return text.replace(old, new, 1)


app_path = Path('static/app.js')
app = app_path.read_text(encoding='utf-8')
alias_owner = "window.setPage=function(p){state.page=p==='自动标注'?'自动标注及清洗':p;render()};try{setPage=window.setPage}catch(e){}\n"
if app.count(alias_owner) != 1:
    raise SystemExit(f'v42.7 alias owner count mismatch: {app.count(alias_owner)}')
for required in (
    "function setPage(p){state.page=p;render()} window.setPage=setPage;",
    "const setPageReady414=window.setPage;",
    "const baseSetPage417=window.setPage;",
    "render=function(){if(state.page==='自动标注')state.page='自动标注及清洗';",
):
    if app.count(required) != 1:
        raise SystemExit(f'preserved navigation token count mismatch: {required} -> {app.count(required)}')
app = app.replace(alias_owner, '', 1)
if alias_owner in app:
    raise SystemExit('v42.7 alias owner remains after migration')
app_path.write_text(app, encoding='utf-8')

index_path = Path('static/index.html')
index = index_path.read_text(encoding='utf-8')
index = replace_once(index, '/static/app.js?v=42.25.53', '/static/app.js?v=42.25.54', 'app cache bump')
index_path.write_text(index, encoding='utf-8')

guard_path = Path('tests/frontend/retired-pre-v424-setpage-guard.test.mjs')
guard = guard_path.read_text(encoding='utf-8')
guard = replace_once(
    guard,
    "const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');\n",
    "const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');\nconst navigation = fs.readFileSync(new URL('../../static/modules/navigation-stability.js', import.meta.url), 'utf8');\n",
    'guard navigation source binding',
)
old_test = """test('post-v42.7 navigation owners remain after direct-owner cleanup', () => {
  assert.equal(app.includes('const setPageReady414=window.setPage;'), true, 'startup readiness owner must remain');
  assert.equal(app.includes('const baseSetPage417=window.setPage;'), true, 'V417 sidebar owner must remain');
  assert.equal(
    app.includes(\"window.setPage=function(p){state.page=p==='自动标注'?'自动标注及清洗':p;render()};try{setPage=window.setPage}catch(e){}\"),
    true,
    'v42.7 auto-label route owner must remain',
  );
});
"""
new_test = """test('v42.7 direct route owner cannot return after alias normalization moved to final navigation', () => {
  assert.equal(
    app.includes(\"window.setPage=function(p){state.page=p==='自动标注'?'自动标注及清洗':p;render()};try{setPage=window.setPage}catch(e){}\"),
    false,
    'v42.7 direct auto-label route owner must remain retired',
  );
  assert.equal(navigation.includes('export function normalizeNavigationPage(page)'), true, 'semantic page normalizer must remain');
  assert.equal(navigation.includes(\"requested === '自动标注' ? '自动标注及清洗' : requested\"), true, 'legacy auto-label alias must remain canonicalized');
});

test('post-v42.7 readiness and sidebar owners remain after alias-owner cleanup', () => {
  assert.equal(app.includes('const setPageReady414=window.setPage;'), true, 'startup readiness owner must remain');
  assert.equal(app.includes('const baseSetPage417=window.setPage;'), true, 'V417 sidebar owner must remain');
});
"""
guard = replace_once(guard, old_test, new_test, 'advance permanent alias guard')
guard_path.write_text(guard, encoding='utf-8')

print('retired v42.7 direct setPage alias owner and advanced test guard')
