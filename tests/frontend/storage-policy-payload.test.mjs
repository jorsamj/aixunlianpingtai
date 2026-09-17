import test from 'node:test';
import assert from 'node:assert/strict';
import {buildStorageSourcePayload} from '../../static/modules/storage.js';

test('OSS and S3 storage configs persist overwrite protection by default', () => {
  const oss = buildStorageSourcePayload({name:'oss', type:'oss', endpoint:'oss.example.com', bucket:'materials'});
  const s3 = buildStorageSourcePayload({name:'s3', type:'s3', bucket:'materials'});
  assert.equal(oss.config.protect_existing_objects, true);
  assert.equal(s3.config.protect_existing_objects, true);
});

test('legacy overwrite mode must be explicitly requested', () => {
  const payload = buildStorageSourcePayload({name:'s3', type:'s3', bucket:'materials', protect_existing_objects:false});
  assert.equal(payload.config.protect_existing_objects, false);
});
