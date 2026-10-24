import test from 'node:test';
import assert from 'node:assert/strict';
import {installAlgorithmListRuntime} from '../../static/modules/algorithm-list-runtime.js';

test('training ordering uses complete authoritative success counts despite paged or duplicated jobs', () => {
  const state={project:{id:'p1'},algorithms:[{id:'a',successful_training_count:3},{id:'b',successful_training_count:1},{id:'old'}],jobs:[{id:'j',algorithm_id:'b',status:'FAILED'},{id:'j',algorithm_id:'b',status:'FAILED'}]};
  globalThis.window={};
  const runtime=installAlgorithmListRuntime({getState:()=>state,projectId:()=>state.project.id});
  runtime.setSort('training');
  assert.deepEqual(runtime.visibleAlgorithms().map(x=>x.id),['a','b','old']);
  state.algorithms[1].successful_training_count=4;
  assert.deepEqual(runtime.visibleAlgorithms().map(x=>x.id),['b','a','old']);
  state.project.id='p2';state.algorithms=[{id:'b',successful_training_count:0},{id:'c',successful_training_count:2}];
  assert.deepEqual(runtime.visibleAlgorithms().map(x=>x.id),['c','b']);
  runtime.destroy();delete globalThis.window;
});

