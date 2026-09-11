from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding='utf-8')


def write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding='utf-8')


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected exactly 1 match, found {count}')
    return text.replace(old, new, 1)


path = 'static/app.js'
text = read(path)

text = replace_once(
    text,
    "  const set423Base=window.setPage;\n  window.setPage=function(p){set423Base(p)};try{setPage=window.setPage}catch(e){}\n",
    '',
    'remove v42.3 pure pass-through setPage wrapper',
)
text = replace_once(
    text,
    "  const setBase424=window.setPage;\n  window.setPage=function(p){state.page=p;render()};try{setPage=window.setPage}catch(e){}\n",
    "  window.setPage=function(p){state.page=p;render()};try{setPage=window.setPage}catch(e){}\n",
    'remove unused v42.4 setPage base capture',
)

for token in ('set423Base', 'setBase424'):
    if token in text:
        raise SystemExit(f'static/app.js: dead setPage compatibility remains: {token}')
if 'window.setPage=function(p){state.page=p;render()};try{setPage=window.setPage}catch(e){}' not in text:
    raise SystemExit('static/app.js: v42.4 direct setPage owner was accidentally removed')
write(path, text)

path = 'static/index.html'
text = read(path)
text = replace_once(
    text,
    '/static/app.js?v=42.25.49',
    '/static/app.js?v=42.25.50',
    'bump app.js cache',
)
write(path, text)

print('retired v42.3 pass-through setPage wrapper and unused v42.4 base capture')
