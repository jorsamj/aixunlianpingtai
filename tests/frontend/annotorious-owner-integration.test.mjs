import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const app=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');
const main=readFileSync(new URL('../../static/main.mjs',import.meta.url),'utf8');
test('formal manual entry delegates to one official kernel and retires old editable DOM and listeners',()=>{
  assert.match(main,/createAnnotoriousEditor/);
  assert.match(app,/function ensureAnnotationEditor420/);
  assert.match(app,/state\.annotationEditor\?\.destroy/);
  assert.doesNotMatch(app,/className='box box424'|className='drawBox'|bound411|bound424/);
  assert.doesNotMatch(app,/window\.addEventListener\('mouse(?:move|up)'/);
  assert.match(app,/if\(e\.defaultPrevented\)return/);
});
test('manual tooling keeps one business history, protected lifecycle and explicit visibility controls',()=>{
  assert.match(app,/data-ann-mode="select"/);
  assert.match(app,/data-ann-mode="draw"/);
  assert.match(app,/data-ann-mode="pan"/);
  assert.match(app,/data-ann-visibility/);
  assert.match(app,/data-ann-filter/);
  assert.match(app,/clearTimeout\(state\.annAutoSaveTimer\)/);
  assert.match(app,/state\.annotationEditorGeneration/);
});
