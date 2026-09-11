from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding='utf-8')


def write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding='utf-8')


def require_once(text: str, needle: str, label: str) -> int:
    count = text.count(needle)
    if count != 1:
        raise SystemExit(f'{label}: expected exactly 1 match, found {count}')
    return text.index(needle)


def remove_once(text: str, block: str, label: str) -> str:
    require_once(text, block, label)
    return text.replace(block, '', 1)


path = 'static/app.js'
text = read(path)

v39 = (
    "  const oldSetV39=window.setPage;\n"
    "  window.setPage=function(p){if(['部署转换','部署产物','部署资源','部署插件'].includes(p))state.deployLoaded=false;oldSetV39(p)};\n"
    "  try{setPage=window.setPage}catch(e){}\n"
)
v42 = (
    "  const oldSet42=window.setPage;\n"
    "  window.setPage=function(p){if(['新建算法','素材接入','自动迭代','质量中心'].includes(p))state.v42.loaded=false;oldSet42(p)};try{setPage=window.setPage}catch(e){}\n"
)
v422 = (
    "  const set422Base=window.setPage;\n"
    "  window.setPage=function(p){if(p==='新建算法'||p==='自动迭代')p='算法列表';set422Base(p)};try{setPage=window.setPage}catch(e){}\n"
)
v424_reset = "  window.setPage=function(p){state.page=p;render()};try{setPage=window.setPage}catch(e){}\n"

# Prove the family is bounded and synchronously severed by the later v42.4
# direct assignment before editing anything.
pos_v39 = require_once(text, v39, 'V39 setPage wrapper')
pos_v42 = require_once(text, v42, 'V42 setPage wrapper')
pos_v422 = require_once(text, v422, 'V42.2 setPage wrapper')
pos_reset = require_once(text, v424_reset, 'V42.4 direct setPage reset')
if not (pos_v39 < pos_v42 < pos_v422 < pos_reset):
    raise SystemExit(
        f'unexpected source order: v39={pos_v39}, v42={pos_v42}, v422={pos_v422}, v424_reset={pos_reset}'
    )

for token in ('oldSetV39', 'oldSet42', 'set422Base'):
    if text.count(token) != 2:
        raise SystemExit(f'{token}: expected declaration + own wrapper call only, found {text.count(token)} references')

text = remove_once(text, v39, 'remove dead V39 setPage wrapper')
text = remove_once(text, v42, 'remove dead V42 setPage wrapper')
text = remove_once(text, v422, 'remove dead V42.2 setPage wrapper')

for token in ('oldSetV39', 'oldSet42', 'set422Base'):
    if token in text:
        raise SystemExit(f'static/app.js: retired pre-v42.4 token remains: {token}')

# Explicitly protect later live/retained owners from accidental collateral edits.
for required in (
    v424_reset.strip(),
    "const setPageReady414=window.setPage;",
    "const baseSetPage417=window.setPage;",
    "window.setPage=function(page){window.toggleMobileSidebarV37?.(false);return baseSetPage417?.(page)};",
    "window.setPage=function(p){state.page=p==='自动标注'?'自动标注及清洗':p;render()};",
):
    if required not in text:
        raise SystemExit(f'required later navigation owner missing after migration: {required}')

write(path, text)

path = 'static/index.html'
text = read(path)
old = '/static/app.js?v=42.25.51'
new = '/static/app.js?v=42.25.52'
if text.count(old) != 1:
    raise SystemExit(f'cache bump: expected {old} once, found {text.count(old)}')
write(path, text.replace(old, new, 1))

print('retired pre-v42.4 dead setPage family; later reset/readiness/sidebar owners preserved')
