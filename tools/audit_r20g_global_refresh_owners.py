from pathlib import Path
import re

path = Path('static/app.js')
text = path.read_text(encoding='utf-8')
primitives = ['reload', 'loadAll', 'loadRelated', 'loadCore412']

line_starts = [0]
for m in re.finditer('\n', text):
    line_starts.append(m.end())


def line_no(pos: int) -> int:
    import bisect
    return bisect.bisect_right(line_starts, pos)


def context(pos: int, radius: int = 190) -> str:
    s = text[max(0, pos-radius):min(len(text), pos+radius)]
    return ' '.join(s.replace('\n', ' ').split())

owner_patterns = [
    re.compile(r'window\.([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?function\b'),
    re.compile(r'function\s+([A-Za-z_$][\w$]*)\s*\('),
    re.compile(r'(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:function\b|\([^;\n]*?\)\s*=>|[A-Za-z_$][\w$]*\s*=>)'),
]

owners = []
for pat in owner_patterns:
    for m in pat.finditer(text):
        owners.append((m.start(), m.group(1), m.group(0)))
owners.sort()


def nearest_owner(pos: int):
    candidates = [x for x in owners if x[0] < pos]
    if not candidates:
        return ('<top-level>', -1, '')
    start, name, raw = candidates[-1]
    # Keep owner inference bounded. If declaration is very far away, call it top-level/unknown.
    if pos - start > 14000:
        return ('<unknown>', start, raw)
    return (name, start, raw)

print('R20g authoritative full-file audit')
print(f'file={path} chars={len(text)} lines={len(line_starts)}')
print()

# Primitive definitions / assignment points.
print('=== primitive definitions / assignments ===')
for name in primitives:
    pats = [
        re.compile(rf'function\s+{re.escape(name)}\s*\('),
        re.compile(rf'window\.{re.escape(name)}\s*='),
        re.compile(rf'(?:const|let|var)\s+{re.escape(name)}\s*='),
    ]
    hits = []
    for pat in pats:
        hits.extend(m.start() for m in pat.finditer(text))
    hits = sorted(set(hits))
    print(f'{name}: definition/assignment hits={len(hits)}')
    for p in hits:
        print(f'  L{line_no(p)} @{p}: {context(p)}')
print()

# All call-shaped occurrences, including definitions explicitly classified.
print('=== call-shaped occurrences ===')
records = []
for name in primitives:
    pat = re.compile(rf'\b{re.escape(name)}\s*\(')
    for m in pat.finditer(text):
        p = m.start()
        before = text[max(0, p-40):p]
        is_definition = bool(re.search(rf'function\s+{re.escape(name)}\s*$', before))
        owner, owner_pos, raw = nearest_owner(p)
        later_window_assignments = 0
        if owner not in ('<top-level>', '<unknown>'):
            later_window_assignments = len(list(re.finditer(rf'window\.{re.escape(owner)}\s*=', text[p+1:])))
        records.append((p, name, owner, is_definition, later_window_assignments))

records.sort()
for p, name, owner, is_def, later in records:
    kind = 'definition' if is_def else 'call'
    print(f'L{line_no(p):>5} @{p:<8} {name:<12} {kind:<10} owner={owner:<34} later-window-owner-assignments={later}')
    print('  ' + context(p))
print()

# Summaries by primitive and inferred owner.
print('=== summary by primitive ===')
for name in primitives:
    rows = [r for r in records if r[1] == name and not r[3]]
    print(f'{name}: calls={len(rows)}')
    counts = {}
    for _, _, owner, _, _ in rows:
        counts[owner] = counts.get(owner, 0) + 1
    for owner, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f'  {owner}: {count}')
print()

# Capture / restore aliases: window.__alias = window.public and reverse restore.
print('=== capture / restore aliases ===')
captures = []
cap_pat = re.compile(r'window\.(__[A-Za-z0-9_$]+)\s*=\s*window\.([A-Za-z0-9_$]+)')
for m in cap_pat.finditer(text):
    alias, public = m.group(1), m.group(2)
    restores = list(re.finditer(rf'window\.{re.escape(public)}\s*=\s*window\.{re.escape(alias)}\b', text[m.end():]))
    captures.append((m.start(), alias, public, len(restores)))
for p, alias, public, restores in captures:
    relevant = public in {r[2] for r in records}
    marker = 'REFRESH-OWNER-RELATED' if relevant else ''
    print(f'L{line_no(p)} {alias} <- {public}; later restores={restores} {marker}'.rstrip())
print()

# Window actions whose declaration text contains a target primitive before the next window function assignment on that line/block.
print('=== candidate mutation/action owners containing refresh calls ===')
window_assigns = list(re.finditer(r'window\.([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?function\b', text))
for i, m in enumerate(window_assigns):
    start = m.start()
    end = window_assigns[i+1].start() if i + 1 < len(window_assigns) else len(text)
    # Bound enormous historical regions so one owner cannot absorb unrelated later code.
    end = min(end, start + 18000)
    region = text[start:end]
    used = [name for name in primitives if re.search(rf'\b{re.escape(name)}\s*\(', region)]
    if used:
        name = m.group(1)
        later_same = len(list(re.finditer(rf'window\.{re.escape(name)}\s*=', text[end:])))
        alias_caps = len(list(re.finditer(rf'window\.(__[A-Za-z0-9_$]+)\s*=\s*window\.{re.escape(name)}\b', text)))
        alias_restores = len(list(re.finditer(rf'window\.{re.escape(name)}\s*=\s*window\.__[A-Za-z0-9_$]+\b', text)))
        print(f'L{line_no(start):>5} owner={name:<34} primitives={",".join(used):<32} later_same_assign={later_same} captures={alias_caps} restores={alias_restores}')

# Hard facts used by the next migration selection.
print()
print('=== hard counts ===')
for name in primitives:
    calls = [r for r in records if r[1] == name and not r[3]]
    print(f'{name}_calls={len(calls)}')
print(f'classic_window_setPage_assignments={len(re.findall(r"window\.setPage\s*=", text))}')
print(f'active_new_MutationObserver={len(re.findall(r"new\s+MutationObserver\s*\(", text))}')
