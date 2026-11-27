import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

// Source contract for the write-lock defect: every smart-audit write went through
// a busy flag that was set but never cleared on failure, and the review refreshed
// the candidates while its own lock was still held (so the refresh was dropped).
const source = fs.readFileSync(new URL('../../frontend/src/app/SmartAudit.vue', import.meta.url), 'utf8');

test('every smart-audit write runs through the releasing wrapper', () => {
  const wrapper = source.slice(source.indexOf('function writeOnce<'));
  const wrapperBody = wrapper.slice(0, wrapper.indexOf('function createAudit('));
  assert.ok(wrapper.indexOf('function writeOnce<') >= 0, 'writeOnce wrapper is missing');
  assert.ok(
    wrapperBody.includes(".finally(()=>{writeBusy.value=''"),
    'writeOnce never releases the lock',
  );
  for (const operation of ['create', 'review', 'cancel', 'retry']) {
    assert.ok(
      source.includes(`writeOnce('${operation}','${operation}'`),
      `${operation} does not use the shared write wrapper`,
    );
    assert.ok(
      !source.includes(`writeBusy.value='${operation}'`),
      `${operation} still sets the lock directly`,
    );
  }
});

test('the review refresh happens after the lock is released', () => {
  assert.ok(
    source.includes('},()=>{void loadFindings()});'),
    'review does not refresh candidates from the post-success hook',
  );
  const reviewBlock = source.slice(source.indexOf('function review('));
  const applyBlock = reviewBlock.slice(0, reviewBlock.indexOf('},()=>{void loadFindings()});'));
  assert.ok(
    !applyBlock.includes('void loadFindings()'),
    'review still refreshes while the write lock is held',
  );
});
