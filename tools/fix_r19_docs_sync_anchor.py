from pathlib import Path

p = Path('tools/sync_r19_docs.py')
s = p.read_text(encoding='utf-8')
old = "t = one(t, 'lifecycle-event-ownership.test.mjs\\nauto-label-poll-runtime.test.mjs', 'lifecycle-event-ownership.test.mjs\\nmodal-content-owner.test.mjs\\nauto-label-poll-runtime.test.mjs', 'audit permanent test')"
new = "t = one(t, 'tests/frontend/lifecycle-event-ownership.test.mjs\\ntests/frontend/auto-label-poll-runtime.test.mjs', 'tests/frontend/lifecycle-event-ownership.test.mjs\\ntests/frontend/modal-content-owner.test.mjs\\ntests/frontend/auto-label-poll-runtime.test.mjs', 'audit permanent test')"
if s.count(old) != 1:
    raise SystemExit(f'R19 audit test anchor source count={s.count(old)}')
p.write_text(s.replace(old, new, 1), encoding='utf-8')
print('R19 audit permanent-test anchor fixed')
