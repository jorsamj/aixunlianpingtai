import test from 'node:test';
import assert from 'node:assert/strict';

import {PageRequestScope} from '../../static/modules/page-request-scope.js';

function abortError() {
  const error = new Error('aborted');
  error.name = 'AbortError';
  return error;
}

function deferredFetch() {
  const calls = [];
  const fetchImpl = (input, init = {}) => {
    let resolve;
    let reject;
    const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
    const call = {input, init, resolve, reject};
    calls.push(call);
    init.signal?.addEventListener('abort', () => reject(abortError()), {once: true});
    return promise;
  };
  return {calls, fetchImpl};
}

test('same-page API GET receives the page abort signal and completes normally', async () => {
  const fake = deferredFetch();
  const scope = new PageRequestScope({page: '训练任务', fetchImpl: fake.fetchImpl});
  const request = scope.fetch('/api/tasks');

  assert.equal(fake.calls.length, 1);
  assert.ok(fake.calls[0].init.signal instanceof AbortSignal);
  assert.equal(fake.calls[0].init.signal.aborted, false);

  const response = {ok: true};
  fake.calls[0].resolve(response);
  assert.equal(await request, response);
});

test('navigating aborts old page GET and quarantines its continuation', async () => {
  const fake = deferredFetch();
  const scope = new PageRequestScope({page: '训练任务', fetchImpl: fake.fetchImpl});
  const request = scope.fetch('/api/tasks');

  scope.navigate('数据集');
  assert.equal(fake.calls[0].init.signal.aborted, true);

  const outcome = await Promise.race([
    request.then(() => 'settled', () => 'rejected'),
    new Promise(resolve => setTimeout(() => resolve('pending'), 15)),
  ]);
  assert.equal(outcome, 'pending');
  assert.equal(scope.page, '数据集');
  assert.equal(scope.abortedRequests, 1);
});

test('POST mutations are not automatically cancelled by page navigation', async () => {
  const fake = deferredFetch();
  const scope = new PageRequestScope({page: '训练任务', fetchImpl: fake.fetchImpl});
  const request = scope.fetch('/api/tasks', {method: 'POST', body: '{}'});

  assert.equal(fake.calls[0].init.signal, undefined);
  scope.navigate('数据集');

  const response = {ok: true};
  fake.calls[0].resolve(response);
  assert.equal(await request, response);
});

test('non-API requests are left untouched', async () => {
  const fake = deferredFetch();
  const scope = new PageRequestScope({page: '训练任务', fetchImpl: fake.fetchImpl});
  const request = scope.fetch('/static/app.js');

  assert.equal(fake.calls[0].init.signal, undefined);
  const response = {ok: true};
  fake.calls[0].resolve(response);
  assert.equal(await request, response);
});
