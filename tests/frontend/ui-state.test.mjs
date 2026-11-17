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
  assert.equal('projectId' in saved, false);
  assert.equal(saved.datasetId, '');
  assert.equal(saved.imageFilter, 'all');
  assert.equal(saved.ts, 7);
});

import {readVueNavigation} from '../../static/modules/ui-state.js';
test('Vue navigation persists only matching project and identity, never model data or secrets',()=>{
 const storage=memoryStorage();persistUiState({page:'训练报告只读浏览',project:{id:'p'}},{storage,vueNavigation:{project_id:'p',selection:{algorithmId:'a',versionId:'v',secret:'DO_NOT_STORE'},report:{jobId:'j',returnPage:'workbench',algorithmId:'a',versionId:'v',metrics:{map50:1},token:'DO_NOT_STORE'},payload:'DO_NOT_STORE'}});
 const saved=readVueNavigation('p',{storage});assert.deepEqual(saved,{project_id:'p',selection:{algorithmId:'a',versionId:'v'},report:{jobId:'j',returnPage:'workbench',algorithmId:'a',versionId:'v'}});assert.equal(storage.value(UI_STATE_STORAGE_KEY).includes('DO_NOT_STORE'),false);assert.equal(readVueNavigation('q',{storage}),null);
 persistUiState({page:'总览',project:{id:'q'}},{storage,vueNavigation:{project_id:'p',selection:{algorithmId:'a',versionId:'v'}}});assert.equal(readVueNavigation('p',{storage}),null);
});
