from pathlib import Path
import re

path = Path('static/app.js')
text = path.read_text(encoding='utf-8')
primitives = ['reload', 'loadAll', 'loadRelated', 'loadCore412']

line_starts = [0]
for m in re.finditer('\n', text):
    line_starts.append(m.end())


def line_no(pos):
    import bisect
    return bisect.bisect_right(line_starts, pos)


def compact(pos, radius=210):
    return ' '.join(text[max(0,pos-radius):min(len(text),pos+radius)].replace('\n',' ').split())

print('=== direct aliases of refresh primitives ===')
aliases = []
for primitive in primitives:
    patterns = [
        re.compile(rf'(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*{re.escape(primitive)}\b'),
        re.compile(rf'window\.([A-Za-z_$][\w$]*)\s*=\s*{re.escape(primitive)}\b'),
    ]
    for pat in patterns:
        for m in pat.finditer(text):
            alias = m.group(1)
            if alias == primitive:
                continue
            aliases.append((m.start(), alias, primitive))
            calls = list(re.finditer(rf'\b{re.escape(alias)}\s*\(', text[m.end():]))
            print(f'L{line_no(m.start())} {alias} <- {primitive}; later alias calls={len(calls)}')
            print('  capture:', compact(m.start()))
            for c in calls:
                absolute = m.end() + c.start()
                print(f'  call L{line_no(absolute)}: {compact(absolute)}')

print()
print('=== second-order aliases ===')
# Follow simple alias chains such as a=loadRelated; b=a; b().
for _, alias, primitive in aliases:
    pat = re.compile(rf'(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*{re.escape(alias)}\b')
    for m in pat.finditer(text):
        alias2 = m.group(1)
        calls = list(re.finditer(rf'\b{re.escape(alias2)}\s*\(', text[m.end():]))
        print(f'L{line_no(m.start())} {alias2} <- {alias} <- {primitive}; later calls={len(calls)}')
        for c in calls:
            absolute = m.end() + c.start()
            print(f'  call L{line_no(absolute)}: {compact(absolute)}')

print()
print('=== selected final owner assignment order ===')
selected = [
    'doUploadZip426','doUploadImages426','confirmStorageImport61',
    'refreshTrainPage428','promoteTrain428','pauseTrain428','resumeTrain428','stopTrain428','deleteTrain428',
    'saveVisionModelM4','saveModelConfig427','confirmClean427','confirmAiLabel427',
]
for name in selected:
    pat = re.compile(rf'window\.{re.escape(name)}\s*=')
    hits = list(pat.finditer(text))
    print(f'{name}: assignments={len(hits)}')
    for i,m in enumerate(hits,1):
        print(f'  {i}. L{line_no(m.start())}: {compact(m.start(), 150)}')

print()
print('=== known runtime modules from main.mjs ===')
main = Path('static/main.mjs').read_text(encoding='utf-8')
for needle in ['installTrainingTaskRuntime','installMaterialPaginationRuntime','installServerMaterialImport61','installMaterialBatchRuntime']:
    print(f'{needle}: {main.count(needle)}')

print()
print('formal_version=' + Path('VERSION.txt').read_text(encoding='utf-8').strip())
