import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

import {
  buildStorageSourcePayload,
  defaultStorageSource,
  enabledStorageSources,
  sourceMatches,
  storageSourceLabel,
} from '../../static/modules/storage.js';

test('storage source helpers keep physical source separate from material identity', () => {
  const sources = [
    {id: 'default_local', name: '平台本地存储', type: 'local', enabled: true},
    {id: 'minio', name: '内网 MinIO', type: 's3', enabled: true, is_default: true},
    {id: 'off', name: '停用', enabled: false},
  ];
  assert.deepEqual(enabledStorageSources(sources).map(item => item.id), ['default_local', 'minio']);
  assert.equal(defaultStorageSource(sources).id, 'minio');
  assert.equal(storageSourceLabel(sources[1]), '内网 MinIO');
  assert.equal(sourceMatches({id: 'image-1', storage_source_id: 'minio'}, 'minio'), true);
  assert.equal(sourceMatches({id: 'image-1'}, 'default_local'), true);
});

test('storage configuration separates secrets from ordinary config', () => {
  const payload = buildStorageSourcePayload({
    name: 'MinIO', type: 's3', endpoint: 'http://minio:9000', region: 'us-east-1',
    bucket: 'materials', prefix: 'vision', access_key_id: 'user', secret_access_key: 'secret', use_ssl: false,
  });
  assert.deepEqual(payload.config, {
    endpoint: 'http://minio:9000', region: 'us-east-1', bucket: 'materials', prefix: 'vision', use_ssl: false,
  });
  assert.deepEqual(payload.credentials, {access_key_id: 'user', secret_access_key: 'secret'});
  assert.equal(JSON.stringify(payload.config).includes('secret'), false);
});

test('editing a configured source with blank credential fields preserves the stored secret', () => {
  const payload = buildStorageSourcePayload({
    name: 'MinIO', type: 's3', endpoint: 'http://minio:9000', region: 'us-east-1',
    bucket: 'materials', prefix: 'changed-prefix', access_key_id: '', secret_access_key: '', use_ssl: false,
  });
  assert.equal(Object.hasOwn(payload, 'credentials'), false);
  assert.equal(payload.config.prefix, 'changed-prefix');
});

test('object storage credentials must be replaced as a complete pair', () => {
  assert.throws(
    () => buildStorageSourcePayload({name: 'OSS', type: 'oss', endpoint: 'oss.example.com', bucket: 'materials', access_key_id: 'only-id'}),
    /必须同时填写/,
  );
  assert.throws(
    () => buildStorageSourcePayload({name: 'S3', type: 's3', bucket: 'materials', secret_access_key: 'only-secret'}),
    /必须同时填写/,
  );
});

test('storage UI is appended only to expanded resource configuration', () => {
  const source = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  const block = source.slice(source.indexOf('v42.22 multi-source material storage UI'));
  assert.match(block, /state\.v427Advanced/);
  assert.match(block, /素材存储配置/);
  assert.match(block, /storage_source_id/);
  assert.match(block, /storage-imports\/scan/);
  assert.match(block, /浏览器上传/);
  assert.match(block, /服务器本地目录/);
  assert.match(block, /服务器 ZIP/);
  assert.match(block, /source=>source\.type===['"]local['"]/);
  assert.doesNotMatch(block, /train_dataset_ids|test_dataset_ids/);
});
