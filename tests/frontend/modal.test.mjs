import test from 'node:test';
import assert from 'node:assert/strict';

import {createModalStack} from '../../static/modules/modal.js';


test('closing a child modal preserves its parent', () => {
  const stack = createModalStack();
  stack.push({id: 'training'});
  stack.push({id: 'quality'});
  assert.equal(stack.pop().id, 'quality');
  assert.equal(stack.peek().id, 'training');
});

