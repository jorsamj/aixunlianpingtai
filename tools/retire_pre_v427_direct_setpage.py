from pathlib import Path

APP = Path('static/app.js')
INDEX = Path('static/index.html')

text = APP.read_text(encoding='utf-8')

persist = """  window.setPage=function(p){
    state.page=p;
    saveUiState();
    render();
  };
"""
plain = "  window.setPage=function(p){state.page=p;render()};\n"
plain_with_alias = "  window.setPage=function(p){state.page=p;render()};try{setPage=window.setPage}catch(e){}\n"
alias_owner = "window.setPage=function(p){state.page=p==='自动标注'?'自动标注及清洗':p;render()};try{setPage=window.setPage}catch(e){}"
readiness_owner = "window.setPage=async function(page){if(!state.uiReady&&window.__v53InitPromise)await window.__v53InitPromise;return setPageReady414(page)}"
sidebar_owner = "window.setPage=function(page){window.toggleMobileSidebarV37?.(false);return baseSetPage417?.(page)}"

if text.count(persist) != 1:
    raise SystemExit(f'v34 persist owner count mismatch: {text.count(persist)}')
if text.count(plain) != 1:
    raise SystemExit(f'v35 plain owner count mismatch: {text.count(plain)}')
if text.count(plain_with_alias) != 1:
    raise SystemExit(f'v42.4 plain owner count mismatch: {text.count(plain_with_alias)}')
if text.count(alias_owner) != 1:
    raise SystemExit(f'v42.7 alias owner count mismatch: {text.count(alias_owner)}')
if text.count(readiness_owner) != 1:
    raise SystemExit(f'v42.14 readiness owner count mismatch: {text.count(readiness_owner)}')
if text.count(sidebar_owner) != 1:
    raise SystemExit(f'v41.7 sidebar owner count mismatch: {text.count(sidebar_owner)}')

positions = [
    text.index(persist),
    text.index(plain),
    text.index(plain_with_alias),
    text.index(alias_owner),
    text.index(readiness_owner),
]
if positions != sorted(positions):
    raise SystemExit(f'unexpected owner order: {positions}')

text = text.replace(persist, '', 1)
text = text.replace(plain, '', 1)
text = text.replace(plain_with_alias, '', 1)

for retired in (persist, plain, plain_with_alias):
    if retired in text:
        raise SystemExit('retired direct setPage owner still present after migration')
for preserved in (alias_owner, readiness_owner, sidebar_owner):
    if text.count(preserved) != 1:
        raise SystemExit('preserved navigation owner changed during migration')

APP.write_text(text, encoding='utf-8')

index = INDEX.read_text(encoding='utf-8')
old_cache = '/static/app.js?v=42.25.52'
new_cache = '/static/app.js?v=42.25.53'
if index.count(old_cache) != 1:
    raise SystemExit(f'app cache token mismatch: expected one {old_cache}')
index = index.replace(old_cache, new_cache, 1)
INDEX.write_text(index, encoding='utf-8')

print('retired v34/v35/v42.4 direct setPage owners; preserved v42.7 alias, readiness and sidebar owners')
