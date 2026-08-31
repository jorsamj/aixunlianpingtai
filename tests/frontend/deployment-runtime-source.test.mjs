import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const source=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');

test('final deployment test uses persistent runtime worker API and exposes timing dimensions',()=>{
  const marker=source.lastIndexOf('Persistent deployment tests');
  assert.ok(marker>0);
  const finalLayer=source.slice(marker);
  assert.match(finalLayer,/api\/v61\/projects/);
  assert.doesNotMatch(finalLayer,/api\/v12\/projects/);
  assert.match(finalLayer,/preprocess_ms/);
  assert.match(finalLayer,/inference_ms/);
  assert.match(finalLayer,/postprocess_ms/);
});
