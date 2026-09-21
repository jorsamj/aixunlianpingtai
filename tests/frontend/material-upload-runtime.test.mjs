import fs from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';

import {
  MaterialUploadContractError,
  MaterialUploadInterruptedError,
  partitionMaterialFiles,
  uploadMaterialFilesSequentially,
} from '../../static/modules/material-upload-runtime.js';

const files = count => Array.from({length: count}, (_, index) => ({name: `image-${index}.jpg`, size: 1024}));

test('large upload is partitioned into bounded chunks', () => {
  const chunks = partitionMaterialFiles(files(130), {maxFiles: 64, maxBytes: 1024 * 1024});
  assert.deepEqual(chunks.map(chunk => chunk.length), [64, 64, 2]);
});

test('byte ceiling starts a new chunk without splitting a file', () => {
  const chunks = partitionMaterialFiles([
    {name: 'a', size: 70}, {name: 'b', size: 70}, {name: 'c', size: 10},
  ], {maxFiles: 64, maxBytes: 100});
  assert.deepEqual(chunks.map(chunk => chunk.map(file => file.name)), [['a'], ['b', 'c']]);
});

test('chunks are strictly sequential and progress advances only after server acknowledgement', async () => {
  let active = 0;
  let maxActive = 0;
  const sizes = [];
  const events = [];
  const result = await uploadMaterialFilesSequentially(files(130), {
    maxFiles: 64,
    requestChunk: async (chunk, context) => {
      active += 1;
      maxActive = Math.max(maxActive, active);
      sizes.push(chunk.length);
      context.onTransfer({ratio: 1, loadedBytes: chunk.length, totalBytes: chunk.length});
      await Promise.resolve();
      active -= 1;
      return {
        batch_id: `batch-${sizes.length}`,
        uploaded: chunk.map((file, index) => ({id: `${sizes.length}-${index}`, filename: file.name})),
        failed: [],
      };
    },
    onEvent: event => events.push(event),
  });
  assert.equal(maxActive, 1);
  assert.deepEqual(sizes, [64, 64, 2]);
  assert.equal(result.confirmedFiles, 130);
  assert.equal(result.uploaded.length, 130);
  assert.deepEqual(result.batchIds, ['batch-1', 'batch-2', 'batch-3']);
  assert.deepEqual(events.filter(event => event.type === 'chunk-committed').map(event => event.confirmedFiles), [64, 128, 130]);
});

test('server must account for every file in a chunk', async () => {
  await assert.rejects(
    uploadMaterialFilesSequentially(files(3), {
      requestChunk: async () => ({uploaded: [{id: 'one'}], failed: []}),
    }),
    error => error instanceof MaterialUploadContractError && /1\/3/.test(error.message),
  );
});

test('network interruption exposes only server-confirmed prior chunks and is never auto-retried', async () => {
  let calls = 0;
  await assert.rejects(
    uploadMaterialFilesSequentially(files(70), {
      maxFiles: 64,
      requestChunk: async chunk => {
        calls += 1;
        if (calls === 2) throw new Error('connection reset');
        return {uploaded: chunk.map((file, index) => ({id: `ok-${index}`})), failed: []};
      },
    }),
    error => {
      assert.ok(error instanceof MaterialUploadInterruptedError);
      assert.equal(error.details.confirmedFiles, 64);
      assert.equal(error.details.chunkNumber, 2);
      return true;
    },
  );
  assert.equal(calls, 2, 'ambiguous failed chunk must not be retried automatically');
});

test('browser wiring loads chunk runtime after classic app and keeps legacy decision contract', () => {
  const index = fs.readFileSync('static/index.html', 'utf8');
  const bootstrap = fs.readFileSync('static/material-upload-bootstrap.mjs', 'utf8');
  const runtime = fs.readFileSync('static/modules/material-upload-runtime.js', 'utf8');
  const classic = index.match(/<script src="\/static\/app\.js\?v=([^"]+)"><\/script>/);
  const main = index.match(/<script type="module" src="\/static\/main\.mjs\?v=([^"]+)"><\/script>/);
  const upload = index.match(/<script type="module" src="\/static\/material-upload-bootstrap\.mjs\?v=422530"><\/script>/);
  assert.ok(classic && main && upload, 'classic app, main runtime and upload bootstrap must all be loaded');
  assert.equal(classic[1], main[1], 'classic app and main runtime must use the same cache-bust release');
  assert.ok(index.indexOf(classic[0]) < index.indexOf(main[0]), 'main runtime must load after classic app');
  assert.ok(index.indexOf(main[0]) < index.indexOf(upload[0]), 'upload bootstrap must load after main runtime');
  assert.match(bootstrap, /installMaterialUploadRuntime/);
  assert.match(runtime, /window\.doUploadImages426 = input =>/);
  assert.match(runtime, /window\.uploadData424 = \(\) =>/);
  assert.match(runtime, /openBatch414\(\"ready\"/);
});


test('upload progress is compositor-friendly and high-frequency transfer events are frame-coalesced', () => {
  const runtime = fs.readFileSync('static/modules/material-upload-runtime.js', 'utf8');
  const styles = fs.readFileSync('static/styles.css', 'utf8');
  assert.match(runtime, /requestAnimationFrame/);
  assert.match(runtime, /lastTaskCenterProgressAt >= 150/);
  assert.match(runtime, /style\.transform = `scaleX/);
  assert.match(runtime, /data-progress="0\.00"/);
  assert.doesNotMatch(runtime, /node\.style\.width =/);
  assert.match(styles, /\.up411-bar>i(?:,\.zip411-progress>i>em)?\{width:100%;transform-origin:left center;transition:transform/);
});
