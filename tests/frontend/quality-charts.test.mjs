import test from 'node:test';
import assert from 'node:assert/strict';
import {metricChart,trainingCharts} from '../../static/modules/reports.js';

test('confidence charts use the actual sub-unit x range and never label thresholds as epochs',()=>{
  const html=metricChart([{recall:.2,precision:.8},{recall:.8,precision:.5}],'precision','PR',{xKey:'recall',percent:true});
  assert.match(html,/cx="612"/);
  assert.doesNotMatch(html,/Epoch/);
});

test('training charts preserve zero, omit absent series and do not fill missing values',()=>{
  const html=trainingCharts([{epoch:1,map50:0},{epoch:2,map50:null},{epoch:3,map50:.5}]);
  assert.match(html,/2 个真实记录/);
  assert.match(html,/0.0%/);
  assert.equal((html.match(/class="quality-chart"/g)||[]).length,1);
  assert.match(trainingCharts([]),/不根据最终指标补造/);
});
