import test from 'node:test';
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
    app.includes("function cleanup(root){\n    if(!root||!root.querySelectorAll)return;\n    window.beautifyFileInputs426?.(root);"),
    true,
  );
});

test('modal426 stays retired while modalBody keeps the only normalization observer', () => {
  assert.equal(app.includes('const modal426=modal;'), false);
  assert.equal(app.includes('requestAnimationFrame(()=>beautifyFileInputs426(layer||document))'), false);
  assert.equal(app.includes("const view=document.getElementById('view'),modalBody=document.getElementById('modalBody');"), false);
  assert.equal(app.includes("observer.observe(view,{childList:true,subtree:true})"), false);
  assert.equal(app.includes("const modalBody=document.getElementById('modalBody');"), true);
  assert.equal(app.includes("if(modalBody)modalObserver.observe(modalBody,{childList:true,subtree:true});"), true);
});
