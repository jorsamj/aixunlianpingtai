import test from 'node:test';
import assert from 'node:assert/strict';

import {UI_STATE_STORAGE_KEY, persistUiState} from '../../static/modules/ui-state.js';

function memoryStorage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem(key) { return values.has(key) ? values.get(key) : null; },
    setItem(key, value) { values.set(key, String(value)); },
    value(key) { return values.get(key); },
  };
}

test('persistUiState writes current navigation state while preserving unrelated keys', () => {
  const storage = memoryStorage({
    [UI_STATE_STORAGE_KEY]: JSON.stringify({page: '算法列表', projectId: 'old', custom: 'keep'}),
  });
  const state = {
    page: '数据集',
    project: {id: 'project-1'},
    datasetId: 'dataset-1',
    imageFilter: 'annotated',
  };

  const saved = persistUiState(state, {storage, now: () => 12345});
  assert.deepEqual(saved, {
    page: '数据集',
    projectId: 'project-1',
    custom: 'keep',
    datasetId: 'dataset-1',
    imageFilter: 'annotated',
    ts: 12345,
  });
  assert.deepEqual(JSON.parse(storage.value(UI_STATE_STORAGE_KEY)), saved);
});

test('persistUiState recovers from malformed historical storage', () => {
  const storage = memoryStorage({[UI_STATE_STORAGE_KEY]: '{broken'});
  const saved = persistUiState({page: '训练任务'}, {storage, now: () => 7});
  assert.equal(saved.page, '训练任务');
  assert.equal(saved.projectId, '');
  assert.equal(saved.datasetId, '');
  assert.equal(saved.imageFilter, 'all');
  assert.equal(saved.ts, 7);
});
