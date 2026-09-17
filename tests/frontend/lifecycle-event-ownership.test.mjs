import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
const material = fs.readFileSync(new URL('../../static/modules/material-pagination-runtime.js', import.meta.url), 'utf8');

test('ZIP import review is event-owned and the body-wide observer cannot return', () => {
  assert.equal(app.includes('const oldZip412=window.doUploadZip426;'), false);
  assert.equal(app.includes('obs.observe(document.body,{childList:true,subtree:true});'), false);
  assert.equal(app.split('window.completeZipImportReview412=function(jobId)').length - 1, 1);
  assert.equal(app.split('window.completeZipImportReview412?.(job.id)').length - 1, 1);
  assert.equal(app.includes('t.__reviewBound=true;'), true);
  assert.equal(app.includes('t.__autoReviewOpened=true;'), true);
  assert.equal(app.includes("t.resultHtml=String(t.resultHtml||'')+extra"), true);
});

test('material summary timers are scoped to the live paged dataset page', () => {
  assert.equal(material.includes("if (!pid || !isPagedDataset()) return;"), true);
  assert.equal(material.includes('const expectedPage = state.page;'), true);
  assert.equal(material.includes("if (state.page !== expectedPage || !isPagedDataset()) return;"), true);
  assert.equal(material.includes("if (!pid || transport.mode !== 'paged') return;"), false);
  assert.equal(material.includes('setTimeout(refreshSummary61, 1200);'), true);
});
