import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const source = await readFile(new URL('../../static/app.js', import.meta.url), 'utf8');

test('opening training modal does not wait for GPU device probe', () => {
  const marker = "window.startAlgorithmTraining429=async function(aid){\n    if(!state.uiReady&&window.__v53InitPromise)await window.__v53InitPromise;";
  const start = source.lastIndexOf(marker);
  assert.notEqual(start, -1, 'final training open wrapper must exist');
  const end = source.indexOf('\n  };', start);
  assert.notEqual(end, -1, 'final training open wrapper must have an end');
  const block = source.slice(start, end);
  const modalOpen = block.indexOf('previousStart?.(aid)');
  const deviceProbe = block.indexOf("api('/api/v62/training-devices')");
  assert.notEqual(modalOpen, -1, 'modal open call must remain present');
  assert.notEqual(deviceProbe, -1, 'device probe must remain present');
  assert.ok(modalOpen < deviceProbe, 'modal must open before the potentially slow GPU probe starts');
});
