from pathlib import Path
p=Path('tools/sync_r18_docs.py')
s=p.read_text(encoding='utf-8')
old="t = one(t, 'v35/v36/V37 80/100/120ms startup render/version timers\\n```', 'v35/v36/V37 80/100/120ms startup render/version timers\\nbounded 100ms renderTop/cleanup startup timer\\n```', 'map retired')"
new="t = one(t, '#view post-render MutationObserver\\n```', '#view post-render MutationObserver\\nbounded 100ms renderTop/cleanup startup timer\\n```', 'map retired')"
if s.count(old)!=1: raise SystemExit(f'R18 map anchor source count={s.count(old)}')
p.write_text(s.replace(old,new,1),encoding='utf-8')
print('R18 sync anchor fixed')
