import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const source = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

test('conversion submit freezes an idempotency key before POST and persists uncertain results', () => {
  assert.match(source, /const request_id=newConversionRequestId428\(\)/);
  assert.match(source, /savePendingConversion428\(project,aid,vid,\{request_id,payload,createdAt:Date\.now\(\)\}\)/);
  assert.match(source, /body:JSON\.stringify\(payload\)/);
  assert.match(source, /label:'转换任务创建',mutation:true/);
  assert.match(source, /if\(uncertain\)conversionUnknown428\.add\(submissionKey\)/);
});

test('uncertain conversion is queried by request identity and retry reuses frozen payload', () => {
  assert.match(source, /if\(conversionUnknown428\.has\(submissionKey\)\|\|pendingConversion428\(project,aid,vid\)\)/);
  assert.match(source, /\/deploy\/jobs\/by-request\/\$\{encodeURIComponent\(pending\.request_id\)\}/);
  assert.match(source, /window\.retryPendingConversion428=async function/);
  assert.match(source, /body:JSON\.stringify\(pending\.payload\)/);
  assert.match(source, /clearPendingConversion428\(project,aid,vid\)/);
});
