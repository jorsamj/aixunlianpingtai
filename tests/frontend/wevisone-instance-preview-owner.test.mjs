import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
const styles = readFileSync(new URL('../../static/styles.css', import.meta.url), 'utf8');

test('WeVisOne and generic OpenAI remain optional peers in the original model editor', () => {
  assert.match(source, /local_openai:'通用 · OpenAI 兼容'/);
  assert.match(source, /wevisone_vl:'WeVisOne · 专用视觉'/);
  assert.match(source, /advanced\.classList\.remove\('hidden'\)/);
  assert.match(source, /coordinate_space:read\('mcCoordinateSpace'\)/);
  assert.match(source, /window\.verifyModelCoordinatesM4=async function/);
});

test('one existing preview panel displays each instance without a second dialog or GT POST', () => {
  const start = source.indexOf('window.verifyModelCoordinatesM4=async function');
  const end = source.indexOf('window.openModelConfigM4=function', start);
  assert.ok(start >= 0 && end > start);
  const owner = source.slice(start, end);
  assert.match(owner, /Array\.isArray\(r\.instances\)/);
  assert.match(owner, /instances\.map\(\(instance,index\)=>/);
  assert.match(owner, /instance\.images/);
  assert.match(owner, /仅供人工核实，不写入正式 GT/);
  assert.doesNotMatch(owner, /modal\(/);
  assert.doesNotMatch(owner, /\/decisions|\/annotations\/.*POST/);
  assert.match(styles, /\.model-m4-instance\{/);
  assert.match(styles, /\.model-m4-image-stage img\{display:block;width:auto;height:auto;max-width:100%;/);
});
