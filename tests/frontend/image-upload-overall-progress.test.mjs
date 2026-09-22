import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const runtime = readFileSync(new URL('../../static/modules/material-upload-runtime.js', import.meta.url), 'utf8');

function transferBlock() {
  const start = runtime.indexOf("} else if (event.type === 'transfer') {");
  const end = runtime.indexOf("} else if (event.type === 'chunk-committed') {", start);
  assert.ok(start >= 0 && end > start);
  return runtime.slice(start, end);
}

test('plain-image byte upload reaching 100% stays below terminal progress until server commit', () => {
  const transfer = transferBlock();
  assert.match(transfer, /overallPercent: Math\.min\(99, overallBytes \/ totalBytes \* 100\)/);
  assert.match(runtime, /当前批次已上传，等待服务器入库/);
  assert.match(runtime, /批已上传，等待服务器入库/);
});

test('plain-image terminal 100% is owned by committed server completion', () => {
  const transfer = transferBlock();
  assert.doesNotMatch(transfer, /setProgress\('up411Bar', 100\)/);
  assert.doesNotMatch(transfer, /setText\('up411Pct', '100%'\)/);
  const committed = runtime.slice(runtime.indexOf("event.type === 'chunk-committed'"), runtime.indexOf('      return aggregate;'));
  assert.match(committed, /const percent = committedBytes \/ totalBytes \* 100/);
  assert.match(runtime, /setProgress\('up411Bar', 100\)/);
  assert.match(runtime, /status:'SUCCEEDED',progress:100/);
});
