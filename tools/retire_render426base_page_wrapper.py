from pathlib import Path

APP = Path('static/app.js')
INDEX = Path('static/index.html')
TEST = Path('tests/frontend/file-input-beautification-owner.test.mjs')

app = APP.read_text(encoding='utf-8')
index = INDEX.read_text(encoding='utf-8')

old_wrapper = "  const render426base=render;render=function(){render426base();requestAnimationFrame(()=>beautifyFileInputs426(document.getElementById('view')||document))};"
if app.count(old_wrapper) != 1:
    raise SystemExit(f'expected exactly one render426base page wrapper, found {app.count(old_wrapper)}')

cleanup_anchor = "  function cleanup(root){\n    if(!root||!root.querySelectorAll)return;\n"
if app.count(cleanup_anchor) != 1:
    raise SystemExit(f'expected exactly one cleanup owner anchor, found {app.count(cleanup_anchor)}')

if app.count('const modal426=modal;') != 1:
    raise SystemExit('modal426 ownership changed; this batch must not retire modal lifecycle semantics')
if app.count('window.beautifyFileInputs426=beautifyFileInputs426;') != 1:
    raise SystemExit('beautifyFileInputs426 owner export changed unexpectedly')

app = app.replace(old_wrapper, '', 1)
app = app.replace(
    cleanup_anchor,
    cleanup_anchor + "    window.beautifyFileInputs426?.(root);\n",
    1,
)

if 'render426base' in app:
    raise SystemExit('render426base remains after migration')
if 'requestAnimationFrame(()=>beautifyFileInputs426(document.getElementById(\'view\')||document))' in app:
    raise SystemExit('old page-render beautification callback remains after migration')
if 'const modal426=modal;' not in app:
    raise SystemExit('modal426 was removed accidentally')
if 'window.beautifyFileInputs426?.(root);' not in app:
    raise SystemExit('cleanup owner does not invoke file-input beautification')

old_cache = '/static/app.js?v=42.25.66'
new_cache = '/static/app.js?v=42.25.67'
if index.count(old_cache) != 1:
    raise SystemExit(f'expected one {old_cache} cache token, found {index.count(old_cache)}')
index = index.replace(old_cache, new_cache, 1)

TEST.write_text("""import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

test('render426base page wrapper cannot return', () => {
  assert.equal(app.includes('const render426base=render;'), false);
  assert.equal(
    app.includes("requestAnimationFrame(()=>beautifyFileInputs426(document.getElementById('view')||document))"),
    false,
  );
});

test('post-render cleanup owns page file-input beautification', () => {
  assert.equal(app.includes('window.beautifyFileInputs426=beautifyFileInputs426;'), true);
  assert.equal(
    app.includes("function cleanup(root){\\n    if(!root||!root.querySelectorAll)return;\\n    window.beautifyFileInputs426?.(root);"),
    true,
  );
});

test('modal426 remains live until modal lifecycle is separately audited', () => {
  assert.equal(app.includes('const modal426=modal;'), true);
  assert.equal(
    app.includes('requestAnimationFrame(()=>beautifyFileInputs426(layer||document))'),
    true,
  );
});
""", encoding='utf-8')

APP.write_text(app, encoding='utf-8')
INDEX.write_text(index, encoding='utf-8')
print('retired render426base page wrapper; cleanup now owns page file-input beautification')
