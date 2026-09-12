from pathlib import Path

APP = Path('static/app.js')
INDEX = Path('static/index.html')
TEST = Path('tests/frontend/file-input-beautification-owner.test.mjs')

app = APP.read_text(encoding='utf-8')
index = INDEX.read_text(encoding='utf-8')

old = "  const modal426=modal; modal=function(title,body,wide=false){const layer=modal426(title,body,wide);requestAnimationFrame(()=>beautifyFileInputs426(layer||document));return layer};window.modal=modal;"
if app.count(old) != 1:
    raise SystemExit(f'expected exactly one modal426 wrapper, found {app.count(old)}')

required = [
    'window.beautifyFileInputs426=beautifyFileInputs426;',
    'window.beautifyFileInputs426?.(root);',
    "const view=document.getElementById('view'),modalBody=document.getElementById('modalBody');",
    "if(view)observer.observe(view,{childList:true,subtree:true});if(modalBody)observer.observe(modalBody,{childList:true,subtree:true});",
]
for token in required:
    if app.count(token) != 1:
        raise SystemExit(f'required cleanup/modal observer contract changed: {token!r} count={app.count(token)}')

app = app.replace(old, '', 1)

for retired in (
    'const modal426=modal;',
    'requestAnimationFrame(()=>beautifyFileInputs426(layer||document))',
):
    if retired in app:
        raise SystemExit(f'retired modal wrapper fragment remains: {retired}')

old_cache = '/static/app.js?v=42.25.67'
new_cache = '/static/app.js?v=42.25.68'
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

test('post-render cleanup owns file-input beautification', () => {
  assert.equal(app.includes('window.beautifyFileInputs426=beautifyFileInputs426;'), true);
  assert.equal(
    app.includes("function cleanup(root){\\n    if(!root||!root.querySelectorAll)return;\\n    window.beautifyFileInputs426?.(root);"),
    true,
  );
});

test('modal426 wrapper cannot return after modalBody observer takeover', () => {
  assert.equal(app.includes('const modal426=modal;'), false);
  assert.equal(app.includes('requestAnimationFrame(()=>beautifyFileInputs426(layer||document))'), false);
  assert.equal(
    app.includes("const view=document.getElementById('view'),modalBody=document.getElementById('modalBody');"),
    true,
  );
  assert.equal(
    app.includes("if(view)observer.observe(view,{childList:true,subtree:true});if(modalBody)observer.observe(modalBody,{childList:true,subtree:true});"),
    true,
  );
});
""", encoding='utf-8')

APP.write_text(app, encoding='utf-8')
INDEX.write_text(index, encoding='utf-8')
print('retired modal426 wrapper; modalBody cleanup observer is the sole file-input lifecycle owner')
