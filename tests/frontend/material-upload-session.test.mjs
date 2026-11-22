import assert from 'node:assert/strict';
import test from 'node:test';
import {
  MAX_INDEX_ROWS, isUploadSessionProtected, listUploadIndex, listUploadSessions,
  uploadIndexStorageKey, uploadSessionStorageKey, writeUploadSession,
} from '../../static/modules/material-upload-session.js';

const actor = '["test","alice"]';
const project = 'project-1';

function memoryStorage() {
  const values = new Map();
  return {
    values,
    getItem: key => values.has(key) ? values.get(key) : null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: key => values.delete(key),
  };
}
function session(requestId, overrides = {}) {
  return {
    projectId: project, owner: actor, totalFiles: 1, requestIds: [requestId], batchIds: [requestId],
    status: 'SUCCEEDED', failed: 0, requestSeed: requestId, deferred: false,
    pendingDecision: 0, confirmationState: '', createdAt: '2026-11-22T00:00:00.000Z',
    updatedAt: '2026-11-22T00:00:00.000Z', ...overrides,
  };
}
function seedIndex(storage, rows) {
  storage.setItem(uploadIndexStorageKey(actor, project), JSON.stringify(rows));
}

test('index write failure fails closed and rolls the current pointer back', () => {
  const storage = memoryStorage();
  const first = writeUploadSession({actorKey: actor, projectId: project, storage,
    patch: {totalFiles: 1, requestIds: ['first-0001'], status: 'SUCCEEDED'}});
  assert.equal(first.ok, true);
  const indexKey = uploadIndexStorageKey(actor, project);
  const originalSet = storage.setItem;
  storage.setItem = (key, value) => {
    if (key === indexKey) throw new Error('quota');
    return originalSet(key, value);
  };
  const second = writeUploadSession({actorKey: actor, projectId: project, storage,
    patch: {totalFiles: 1, requestIds: ['second-0001'], status: 'UPLOADING'}});
  assert.equal(second.ok, false);
  const current = JSON.parse(storage.getItem(uploadSessionStorageKey(actor, project)));
  assert.deepEqual(current.requestIds, ['first-0001']);
  assert.equal(current.status, 'SUCCEEDED');
});

test('an accepted request keeps its current pointer when the index write fails', () => {
  const storage = memoryStorage();
  const indexKey = uploadIndexStorageKey(actor, project);
  const originalSet = storage.setItem;
  storage.setItem = (key, value) => {
    if (key === indexKey) throw new Error('quota');
    return originalSet(key, value);
  };
  const result = writeUploadSession({actorKey: actor, projectId: project, storage,
    patch: {totalFiles: 1, requestIds: ['accepted-0001'], status: 'UPLOADING'},
    protectCurrent: true});
  assert.equal(result.ok, false);
  const current = JSON.parse(storage.getItem(uploadSessionStorageKey(actor, project)));
  assert.deepEqual(current.requestIds, ['accepted-0001']);
  assert.equal(current.status, 'UPLOADING');
});

test('a full index of protected pointers refuses a new ordinary session', () => {
  const storage = memoryStorage();
  const rows = Array.from({length: MAX_INDEX_ROWS}, (_, index) =>
    session(`protected-${index}`, {status: 'UNKNOWN', pendingDecision: 1, confirmationState: 'PENDING'}));
  seedIndex(storage, rows);
  const result = writeUploadSession({actorKey: actor, projectId: project, storage,
    patch: {totalFiles: 1, requestIds: ['new-0001'], status: 'SUCCEEDED'}});
  assert.equal(result.ok, false);
  const after = listUploadIndex({actorKey: actor, projectId: project, storage});
  assert.equal(after.length, MAX_INDEX_ROWS);
  assert.equal(after.every(row => isUploadSessionProtected(row)), true);
  assert.equal(after.some(row => row.requestIds[0] === 'new-0001'), false);
});

test('ordinary history is evicted before pending-decision sessions', () => {
  const storage = memoryStorage();
  const rows = [
    ...Array.from({length: MAX_INDEX_ROWS - 1}, (_, index) =>
      session(`pending-${index}`, {pendingDecision: 1, confirmationState: 'PENDING'})),
    session('ordinary-old', {updatedAt: '2026-11-22T00:00:00.000Z'}),
  ];
  seedIndex(storage, rows);
  const result = writeUploadSession({actorKey: actor, projectId: project, storage,
    patch: {totalFiles: 1, requestIds: ['ordinary-new'], status: 'SUCCEEDED'}});
  assert.equal(result.ok, true);
  const after = listUploadIndex({actorKey: actor, projectId: project, storage});
  assert.equal(after.length, MAX_INDEX_ROWS);
  assert.equal(after.some(row => row.requestIds[0] === 'ordinary-new'), true);
  assert.equal(after.some(row => row.requestIds[0] === 'ordinary-old'), false);
  assert.equal(after.filter(row => isUploadSessionProtected(row)).length, MAX_INDEX_ROWS - 1);
});

test('two request identities remain in the index even when the current pointer moves', () => {
  const storage = memoryStorage();
  assert.equal(writeUploadSession({actorKey: actor, projectId: project, storage,
    patch: {totalFiles: 1, requestIds: ['tab-a-0001'], status: 'UPLOADING'}}).ok, true);
  assert.equal(writeUploadSession({actorKey: actor, projectId: project, storage,
    patch: {totalFiles: 1, requestIds: ['tab-b-0001'], status: 'UPLOADING'}}).ok, true);
  const sessions = listUploadSessions({actorKey: actor, projectId: project, storage});
  assert.equal(sessions.length, 2);
  assert.deepEqual(new Set(sessions.flatMap(row => row.requestIds)), new Set(['tab-a-0001', 'tab-b-0001']));
  assert.equal(sessions.every(row => row.owner === actor), true);
});

test('owner-less legacy sessions are never assigned to the current account', () => {
  const storage = memoryStorage();
  storage.setItem(`material-upload-session:${project}`,
    JSON.stringify({projectId: project, totalFiles: 1, requestIds: ['legacy-0001'],
      status: 'UNKNOWN', failed: 0, batchIds: []}));
  assert.deepEqual(listUploadSessions({actorKey: actor, projectId: project, storage}), []);
});
