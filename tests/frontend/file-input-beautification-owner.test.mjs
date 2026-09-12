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

test('post-render cleanup owns page file-input beautification', () => {
  assert.equal(app.includes('window.beautifyFileInputs426=beautifyFileInputs426;'), true);
  assert.equal(
    app.includes("function cleanup(root){\n    if(!root||!root.querySelectorAll)return;\n    window.beautifyFileInputs426?.(root);"),
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
