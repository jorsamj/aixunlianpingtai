from pathlib import Path

ROOT = Path('.')
TERMS = [
    'storage-imports',
    'StorageImport',
    'storage_import',
    '/import/jobs',
    'imported_images',
    "result['imported']",
    '"imported"',
]
SKIP = {'.git', 'node_modules', '.venv', 'venv', '__pycache__', 'dist', 'build'}
EXTS = {'.py', '.js', '.mjs'}


def wanted(path: Path) -> bool:
    if path.suffix not in EXTS:
        return False
    return not any(part in SKIP for part in path.parts)

hits = []
for path in ROOT.rglob('*'):
    if not path.is_file() or not wanted(path):
        continue
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except Exception:
        continue
    matching = [i for i,line in enumerate(lines) if any(term in line for term in TERMS)]
    if not matching:
        continue
    # Print merged +/- 8 line windows around matches.
    ranges = []
    for i in matching:
        a,b=max(0,i-8),min(len(lines),i+9)
        if ranges and a <= ranges[-1][1]: ranges[-1]=(ranges[-1][0],max(ranges[-1][1],b))
        else: ranges.append((a,b))
    hits.append((path, lines, ranges))

print('R20g import-contract source matches')
for path, lines, ranges in sorted(hits, key=lambda item: str(item[0])):
    print(f'=== {path} ===')
    for a,b in ranges:
        print(f'--- lines {a+1}-{b} ---')
        for idx in range(a,b):
            print(f'{idx+1:>5}: {lines[idx]}')

print('\n=== frontend scoped refresh surfaces ===')
for path in [Path('static/modules/material-pagination-runtime.js'), Path('static/app.js')]:
    text=path.read_text(encoding='utf-8')
    for needle in ['MaterialPaginationRuntime61', 'reloadMaterialPage61', 'completeZipImportReview412', 'confirmStorageImport61', 'related411']:
        print(f'{path}:{needle} count={text.count(needle)}')

print('formal_version=' + Path('VERSION.txt').read_text(encoding='utf-8').strip())
