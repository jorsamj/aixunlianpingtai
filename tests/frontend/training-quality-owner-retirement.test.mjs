import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const app=await readFile(new URL('../../static/app.js',import.meta.url),'utf8');
const trainingVisibility=await readFile(new URL('../../static/modules/training-task-visibility-runtime.js',import.meta.url),'utf8');

test('training, quality and legacy auto-label public owners are unique',()=>{
  for(const name of ['openAutoLabelModal','startPrelabelTask','renderQualityCenter424','openTrain424','trainingReport424','renderTrainPicker429','trainQuality429']){
    assert.equal((app.match(new RegExp('window\\.'+name+'\\s*=','g'))||[]).length,1,name);
  }
  assert.equal((app.match(/window\.renderTraining423\s*=/g)||[]).length,0,'app.js must not own training list aliases');
  assert.equal((trainingVisibility.match(/window\.renderTraining423\s*=\s*renderTraining/g)||[]).length,1,'visibility runtime must solely own renderTraining423');
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


test('training report renders canonical random-stage wording without delayed DOM rewrite', () => {
  assert.match(app, /每次随机试验样本/);
  assert.equal(app.includes('固定试验样本'), false);
  assert.equal(app.includes('trainingReportCanonical428'), false);
  assert.match(app, /window\.trainingReport425=window\.trainingReport424=window\.trainingReportCore425/);
});
