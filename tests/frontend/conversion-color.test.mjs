import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {fileURLToPath} from 'node:url';

const root = fileURLToPath(new URL('../../', import.meta.url));
const page = fs.readFileSync(root + 'static/app.js', 'utf8');

test('version conversion form exposes actual RGB/BGR model input choice', () => {
  assert.match(page, /id="conv428InputColor"/);
  assert.match(page, /value="rgb">RGB/);
  assert.match(page, /value="bgr">BGR/);
  assert.match(page, /source_color_order:'rgb',input_color_order:color/);
  assert.match(page, /input_color_order:document\.getElementById\('conv428InputColor'\)/);
  assert.doesNotMatch(page, /id="conv428Pixel"/);
});

test('conversion record shows persisted input color and adaptation verification', () => {
  assert.match(page, /模型输入颜色/);
  assert.match(page, /颜色适配验证/);
  assert.match(page, /j\.params\?\.input_color_order/);
  assert.match(page, /未记录/);
});
