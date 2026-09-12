from pathlib import Path

APP = Path('static/app.js')
INDEX = Path('static/index.html')

app = APP.read_text(encoding='utf-8')
index = INDEX.read_text(encoding='utf-8')

start_marker = '  window.openNewAlgorithm423=async function(){'
end_marker = '  window.viewAlgorithm423=function(id){'

if app.count(start_marker) != 1:
    raise SystemExit(f'expected one shadowed v423 create owner, got {app.count(start_marker)}')
start = app.index(start_marker)
end = app.find(end_marker, start)
if end < 0:
    raise SystemExit('could not locate v423 CRUD retirement boundary')
block = app[start:end]

required = [
    'window.saveNewAlgorithm423=async function(){',
    'onclick="saveNewAlgorithm423()"',
    'window.editAlgorithm423=function(id)',
    'window.saveEditAlgorithm423=async function(id)',
    'onclick="saveEditAlgorithm423(',
    'await loadRelated()',
]
for token in required:
    if token not in block:
        raise SystemExit(f'expected shadowed v423 token missing: {token}')

later = app[end:]
for token in [
    'window.openNewAlgorithm423=function(){',
    'window.saveNewAlgorithm414=async function()',
    'window.editAlgorithm423=function(id)',
    'window.saveEditAlgorithm414=async id=>',
]:
    if token not in later:
        raise SystemExit(f'final stable algorithm CRUD owner missing after retirement boundary: {token}')

app = app[:start] + app[end:]

for token in [
    'window.openNewAlgorithm423=async function(){',
    'window.saveNewAlgorithm423=async function(){',
    'window.saveEditAlgorithm423=async function(id)',
]:
    if token in app:
        raise SystemExit(f'shadowed v423 owner survived migration: {token}')

if app.count('window.openNewAlgorithm423=') != 1:
    raise SystemExit('openNewAlgorithm423 must have exactly one final owner after migration')
if app.count('window.editAlgorithm423=') != 1:
    raise SystemExit('editAlgorithm423 must have exactly one final owner after migration')

old_cache = '/static/app.js?v=42.25.91'
new_cache = '/static/app.js?v=42.25.92'
if index.count(old_cache) != 1:
    raise SystemExit(f'expected one app cache marker {old_cache}')
index = index.replace(old_cache, new_cache, 1)

APP.write_text(app, encoding='utf-8')
INDEX.write_text(index, encoding='utf-8')
print('R20m shadowed v423 algorithm CRUD generation retired')
