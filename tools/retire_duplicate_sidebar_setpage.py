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


# Retire only the earlier V37 mobile-sidebar setPage wrapper. The later V417
# wrapper remains the live sidebar-close owner in the final setPage chain.
path = 'static/app.js'
text = read(path)
old = (
    "  const baseSetPage=window.setPage;\n"
    "  window.setPage=function(page){toggleMobileSidebarV37(false);baseSetPage(page)};\n"
    "  try{setPage=window.setPage}catch(e){}\n"
)
text = replace_once(text, old, '', 'remove duplicate V37 sidebar setPage wrapper')

if 'const baseSetPage=window.setPage;' in text:
    raise SystemExit('static/app.js: V37 baseSetPage capture remains')
if 'window.setPage=function(page){toggleMobileSidebarV37(false);baseSetPage(page)};' in text:
    raise SystemExit('static/app.js: V37 duplicate sidebar wrapper remains')
if "const baseSetPage417=window.setPage;" not in text:
    raise SystemExit('static/app.js: live V417 setPage base capture was accidentally removed')
if "window.setPage=function(page){window.toggleMobileSidebarV37?.(false);return baseSetPage417?.(page)};" not in text:
    raise SystemExit('static/app.js: live V417 sidebar-close owner was accidentally removed')
write(path, text)

# Cache-bust changed classic app.
path = 'static/index.html'
text = read(path)
text = replace_once(
    text,
    '/static/app.js?v=42.25.50',
    '/static/app.js?v=42.25.51',
    'bump app.js cache',
)
write(path, text)

print('retired duplicate V37 sidebar setPage wrapper; V417 remains final sidebar owner')
