import {test} from 'node:test';
import assert from 'node:assert/strict';
import {rowMenuPosition} from '../../static/modules/row-action-menu.js';

test('row menu aligns to anchor, flips at bottom and respects both viewport edges', () => {
  const size = {width: 240, height: 106};
  assert.deepEqual(rowMenuPosition({right: 800, top: 200, bottom: 236}, size, {width: 1366, height: 768}), {left: 560, top: 242, above: false});
  assert.deepEqual(rowMenuPosition({right: 1366, top: 720, bottom: 756}, size, {width: 1366, height: 768}), {left: 1118, top: 608, above: true});
  assert.equal(rowMenuPosition({right: 44, top: 200, bottom: 244}, size, {width: 375, height: 812}).left, 8);
  const constrained = rowMenuPosition({right: 240, top: 15, bottom: 59}, {width: 240, height: 84}, {width: 300, height: 100});
  assert.equal(constrained.top, 8);
});
