import test from 'node:test';
import assert from 'node:assert/strict';

import {
  installChangLianDataBrowserRuntime,
  productIdentity,
  providerItems,
  versionIdentity,
  weightIdentity,
  weightRemoteLink,
} from '../../static/modules/changlian-data-browser.js';

test('provider response normalization keeps official products versions and weights', () => {
  assert.deepEqual(providerItems({response: {code: 0, data: [{productId: 1}]}}), [{productId: 1}]);
  assert.deepEqual(providerItems({response: {data: {records: [{algoVersionId: 2}]}}}), [{algoVersionId: 2}]);
  assert.equal(productIdentity({productId: 11}), '11');
  assert.equal(versionIdentity({algoVersionId: 22}), '22');
  assert.equal(weightIdentity({weightId: 33}), '33');
  assert.equal(weightRemoteLink({filePath: 'https://oss.example/model.rknn'}), 'https://oss.example/model.rknn');
  assert.equal(weightRemoteLink({filePath: '/private/path/model.rknn'}), '');
});

test('changlian data browser is manual-only and reads product version weight truth on refresh', async () => {
  const state = {page: '畅联云数据'};
  const urls = [];
  const request = async url => {
    urls.push(url);
    if (url.endsWith('/products?status=1')) return {response: {data: [{productId: 'p1', productName: '抽烟检测', status: 1}]}};
    if (url.endsWith('/products?status=0')) return {response: {data: []}};
    if (url.endsWith('/versions/by-product/p1')) return {response: {data: [{algoVersionId: 'v1', versionName: 'V1'}]}};
    if (url.endsWith('/weights/by-version/v1')) return {response: {data: [{weightId: 'w1', fileName: 'model.rknn', filePath: 'https://oss.example/model.rknn'}]}};
    throw new Error(`unexpected URL: ${url}`);
  };
  const runtime = installChangLianDataBrowserRuntime({getState: () => state, request, document: null});
  assert.deepEqual(urls, []);
  assert.equal(runtime.snapshot().loaded, false);

  const result = await runtime.refresh();
  assert.equal(result.loaded, true);
  assert.deepEqual(urls, [
    '/api/v63/external-algorithm-platform/provider/products?status=1',
    '/api/v63/external-algorithm-platform/provider/products?status=0',
    '/api/v63/external-algorithm-platform/provider/versions/by-product/p1',
    '/api/v63/external-algorithm-platform/provider/weights/by-version/v1',
  ]);
  assert.equal(result.products[0].versions[0].weights[0].weightId, 'w1');
  assert.equal(urls.some(url => /sync|POST|PUT|DELETE/i.test(url)), false);
  runtime.destroy();
});
