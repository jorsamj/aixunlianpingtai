import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {trainingReportHtml} from '../../static/modules/reports.js';

const styles=readFileSync(new URL('../../static/styles.css',import.meta.url),'utf8');
const app=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');

test('report skeleton and final content keep the same stable modal layout marker',()=>{
  assert.match(app,/training-report-workspace quality-workspace[^`]+data-training-report-dialog data-training-report-loading/);
  const html=trainingReportHtml({job:{id:'training-1'},report:{identity:{job_id:'training-1'}}});
  assert.match(html,/data-training-report-dialog/);
  assert.match(styles,/\.modal:has\(\[data-training-report-dialog\]\) \.modal-card[^\n]+height:86dvh/);
  assert.match(styles,/\.v424-modal-layer:has\(\[data-training-report-dialog\]\) \.modal-body[^\n]+overflow-y:auto/);
});

test('four report tabs stay on one row, do not shrink and remain horizontally scrollable',()=>{
  const tabStyles=styles.match(/\.training-report-workspace \.quality-tabs\{[^}]+\}/)?.[0]||'';
  assert.match(tabStyles,/flex-wrap:nowrap/);
  assert.match(tabStyles,/overflow-x:auto/);
  const buttonStyles=styles.match(/\.training-report-workspace \.quality-tabs \.btn\{[^}]+\}/)?.[0]||'';
  assert.match(buttonStyles,/flex:0 0 auto/);
  assert.doesNotMatch(styles,/\.training-report-workspace \.quality-tabs \.btn\{flex:1 1 40%/);
});
