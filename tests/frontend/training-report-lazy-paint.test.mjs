import test from 'node:test';
import assert from 'node:assert/strict';
import {trainingReportHtml, trainingCharts} from '../../static/modules/reports.js';

function fixture(){
  const history=Array.from({length:500},(_,i)=>({epoch:i+1,map50:(i+1)/1000,precision:.5,box_loss:1/(i+1)}));
  const report={identity:{project_id:'p',algorithm_id:'a',version_id:'v',job_id:'j'},history,metrics:{map50:.5},
    inspection_marker:'FULL_TECHNICAL_BLOB_SHOULD_BE_LAZY'};
  return {job:{id:'j'},report};
}
test('initial report HTML defers inactive curves and full technical evidence',()=>{
  const source=fixture(),html=trainingReportHtml(source);
  assert.match(html,/data-report-pane="curves" hidden><\/section>/);
  assert.doesNotMatch(html,/data-report-chart="accuracy"/);
  assert.doesNotMatch(html,/<circle tabindex=/);
  assert.match(html,/data-report-technical-details/);
  assert.match(html,/data-report-technical><\/pre>/);
  assert.doesNotMatch(html,/FULL_TECHNICAL_BLOB_SHOULD_BE_LAZY/);
});
test('curves remain available from the unmodified actual history when explicitly requested',()=>{
  const source=fixture(),curves=trainingCharts(source.report.history);
  assert.match(curves,/data-report-chart="accuracy"/);
  assert.match(curves,/data-chart-fallback hidden/);
  assert.match(curves,/<circle tabindex=/);
});
