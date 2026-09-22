import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const source = (await readFile(new URL('../../static/app.js', import.meta.url), 'utf8')).replace(/\r\n?/g, '\n');

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


test('training device inventory persists across browser reloads and revalidates stale cache in background', () => {
  assert.match(source, /const TRAINING_DEVICE_CACHE_TTL_MS=24\*60\*60\*1000/);
  assert.match(source, /const trainingDeviceCacheKeyV3=\(\)=>`cl_training_devices_v3_\$\{pid\(\)\}`/);
  assert.match(source, /localStorage\.getItem\(trainingDeviceCacheKeyV3\(\)\)/);
  assert.match(source, /localStorage\.setItem\(trainingDeviceCacheKeyV3\(\)/);
  assert.match(source, /localStorage\.removeItem\(trainingDeviceCacheKeyV3\(\)\)/);
  assert.match(source, /state\.trainingDevicesV3\?\.options\?\.length\?state\.trainingDevicesV3:restoreTrainingDeviceCacheV3\(\)/);
  assert.match(source, /if\(!cacheFresh\)api\('\/api\/v62\/training-devices'\)/);
  assert.match(source, /applyDevices\(cachedDevices,\{persist:false\}\)/);
});
