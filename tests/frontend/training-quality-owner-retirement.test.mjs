import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const app=await readFile(new URL('../../static/app.js',import.meta.url),'utf8');

test('training, quality and legacy auto-label public owners are unique',()=>{
  for(const name of ['openAutoLabelModal','startPrelabelTask','renderQualityCenter424','openTrain424','renderTraining423','trainingReport424','renderTrainPicker429','trainQuality429']){
    assert.equal((app.match(new RegExp('window\\.'+name+'\\s*=','g'))||[]).length,1,name);
  }
});

test('quality center keeps cached non-blocking owner',()=>{
  const start=app.indexOf('window.renderQualityCenter424=async function()');
  const end=app.indexOf('window.refreshQuality411=async function()',start);
  const block=app.slice(start,end);
  assert.match(block,/localStorage\.getItem\(qualityKey411\(\)\)/);
  assert.match(block,/质量指标尚未计算/);
  assert.doesNotMatch(block,/await api\(/);
});

test('training picker and quality use latest explicit training-draft paths',()=>{
  assert.match(app,/window\.renderTrainPicker429=function\(\)/);
  assert.match(app,/pool415\(\)/);
  assert.match(app,/window\.trainQuality429=async function\(\)/);
  assert.match(app,/训练素材 · 数据质量/);
});
