import test from 'node:test';
import assert from 'node:assert/strict';

import {createActionRegistry} from '../../static/modules/actions.js';


test('duplicate action registration is rejected', () => {
  const actions = createActionRegistry();
  actions.register('algorithm.create', () => 'first');
  assert.throws(
    () => actions.register('algorithm.create', () => 'second'),
    /动作已注册/
  );
});


test('registered action is invoked with the supplied context', () => {
  const actions = createActionRegistry();
  actions.register('algorithm.create', ({name}) => name);
  assert.equal(actions.invoke('algorithm.create', {name: 'fire'}), 'fire');
});

