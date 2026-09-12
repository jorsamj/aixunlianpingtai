from pathlib import Path

p = Path('tools/sync_r19_docs.py')
s = p.read_text(encoding='utf-8')

repls = [
    (
        "t = one(t, 'lifecycle-event-ownership.test.mjs\\nauto-label-poll-runtime.test.mjs', 'lifecycle-event-ownership.test.mjs\\nmodal-content-owner.test.mjs\\nauto-label-poll-runtime.test.mjs', 'audit permanent test')",
        "t = one(t, 'tests/frontend/lifecycle-event-ownership.test.mjs\\ntests/frontend/auto-label-poll-runtime.test.mjs', 'tests/frontend/lifecycle-event-ownership.test.mjs\\ntests/frontend/modal-content-owner.test.mjs\\ntests/frontend/auto-label-poll-runtime.test.mjs', 'audit permanent test')",
        'audit',
    ),
    (
        "t = one(t, 'lifecycle-event-ownership.test.mjs\\nnavigation-stability.test.mjs', 'lifecycle-event-ownership.test.mjs\\nmodal-content-owner.test.mjs\\nnavigation-stability.test.mjs', 'map permanent test')",
        "t = one(t, 'tests/frontend/lifecycle-event-ownership.test.mjs\\ntests/frontend/navigation-stability.test.mjs', 'tests/frontend/lifecycle-event-ownership.test.mjs\\ntests/frontend/modal-content-owner.test.mjs\\ntests/frontend/navigation-stability.test.mjs', 'map permanent test')",
        'map',
    ),
]

for old, new, label in repls:
    if s.count(old) != 1:
        raise SystemExit(f'R19 {label} test anchor source count={s.count(old)}')
    s = s.replace(old, new, 1)

p.write_text(s, encoding='utf-8')
print('R19 audit/map permanent-test anchors fixed')
