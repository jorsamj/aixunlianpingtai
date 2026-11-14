import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {formatPercentagePointDelta,metricChart,trainingCharts} from '../../static/modules/reports.js';

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

test('percentage point delta distinguishes missing evidence from a real zero',()=>{
  assert.equal(formatPercentagePointDelta(null),'未记录');
  assert.equal(formatPercentagePointDelta(undefined),'未记录');
  assert.equal(formatPercentagePointDelta(''),'未记录');
  assert.equal(formatPercentagePointDelta(Number.NaN),'未记录');
  assert.equal(formatPercentagePointDelta(Number.POSITIVE_INFINITY),'未记录');
  assert.equal(formatPercentagePointDelta(0),'0.0 pp');
  assert.equal(formatPercentagePointDelta(.125),'+12.5 pp');
});

test('quality workspace routes through its canonical page and operates both comparison panes',()=>{
  const source=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');
  assert.doesNotMatch(source,/setPage\('模型检测'\)/);
  assert.match(source,/openScenarioWorkbench429/);
  assert.match(source,/setPage\?\.\('质量中心'\)/);
  assert.match(source,/setQualityCenterTab411\?\.\('detect'\)/);
  assert.match(source,/querySelectorAll\('\.evaluation429-detail \.evaluation429-media'\)/);
  assert.match(source,/eval429PreviewControl\('reset'\)/);
  assert.match(source,/eval429PreviewControl\('fullscreen',/);
  assert.match(source,/modalBody\.scrollTop=0/);
});
