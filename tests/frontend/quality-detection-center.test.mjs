import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const app = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
const main = readFileSync(new URL('../../static/main.mjs', import.meta.url), 'utf8');
const navigation = readFileSync(new URL('../../static/modules/navigation-stability.js', import.meta.url), 'utf8');
const backend = readFileSync(new URL('../../app.py', import.meta.url), 'utf8');

test('collapsed product navigation has only overview, algorithm generation and data center groups', () => {
  const start = app.lastIndexOf('const icon414=');
  const end = app.indexOf('\n\n  window.renderLabelManagement414', start);
  assert.ok(start >= 0 && end > start);
  const nav = app.slice(start, end);
  assert.match(nav, /title:'总览'/);
  assert.match(nav, /title:'算法生成'/);
  assert.match(nav, /title:'数据中心'/);
  assert.doesNotMatch(nav, /title:'测试评测'/);
  assert.doesNotMatch(nav, /title:'部署中心'/);
  assert.match(nav, /if\(state\.v427Advanced\)groups\.push/);
});

test('retired test routes normalize into quality center and are no longer canonical main owners', () => {
  assert.match(navigation, /requested === '测试发布' \|\| requested === '检测台'\) return '质量中心'/);
  assert.doesNotMatch(main, /\['测试发布', 'renderTest'\]/);
  assert.doesNotMatch(main, /\['检测台', 'renderDetectBench'\]/);
  assert.doesNotMatch(main, /PAGE_EXTRAS_OWNERS = new Set\([^\n]+测试发布/);
  assert.doesNotMatch(main, /PAGE_EXTRAS_OWNERS = new Set\([^\n]+检测台/);
});

test('quality center owns a model-detection tab instead of a standalone test section', () => {
  assert.match(app, /window\.setQualityCenterTab411=async function\(tab\)/);
  assert.match(app, /模型检测/);
  assert.match(app, /window\.loadPageExtras413\?\.\('质量中心'\)/);
  assert.match(app, /window\.renderDetectBench\?\.\(\)/);
});

test('quality detection supports original and algorithm-version models on both sides', () => {
  const start = app.lastIndexOf('v64: quality-center model detection workbench');
  assert.ok(start >= 0);
  const source = app.slice(start);
  assert.match(source, /source==='builtin'/);
  assert.match(source, /source==='algorithm_version'/);
  assert.match(source, /modelBrowser64\('A'/);
  assert.match(source, /modelBrowser64\('B'/);
  assert.match(source, /搜索算法、版本或模型/);
  assert.match(source, /原始 \/ 基础模型/);
  assert.match(source, /算法版本/);
});

test('quality detection accepts single, multi and folder image input and runs real inference tasks', () => {
  const start = app.lastIndexOf('v64: quality-center model detection workbench');
  const source = app.slice(start);
  assert.match(source, /id="benchFiles64" type="file" accept="image\/\*" multiple/);
  assert.match(source, /id="benchFolder64" type="file" accept="image\/\*" multiple webkitdirectory directory/);
  assert.match(source, /window\.runBenchBatch64=async function/);
  assert.match(source, /await window\.benchPredictOne\('benchModelA'/);
  assert.match(source, /await window\.benchPredictOne\('benchModelB'/);
  assert.match(app, /\/api\/v61\/projects\/\$\{pid\(\)\}\/deployment-tests/);
  assert.match(app, /ownerPages:\['质量中心'\]/);
});

test('batch detection exposes result details and human correctness review states', () => {
  const start = app.lastIndexOf('v64: quality-center model detection workbench');
  const source = app.slice(start);
  assert.match(source, /本次检测结果/);
  assert.match(source, /openBenchResult64/);
  assert.match(source, /正确/);
  assert.match(source, /漏检/);
  assert.match(source, /误检/);
  assert.match(source, /框不准/);
  assert.match(source, /类别错误/);
});


test('quality detection persists batch identity and restores recent server-side results', () => {
  const start = app.lastIndexOf('v64: quality-center model detection workbench');
  const source = app.slice(start);
  assert.match(app, /form\.append\('detection_batch_id'/);
  assert.match(app, /form\.append\('detection_item_index'/);
  assert.match(app, /form\.append\('detection_side'/);
  assert.match(source, /window\.loadDetectionBatches64=async function/);
  assert.match(source, /\/api\/v64\/projects\/\$\{pid\(\)\}\/detection-batches\?limit=12/);
  assert.match(source, /window\.openDetectionBatch64=async function/);
  assert.match(source, /batchFromDurable64/);
  assert.match(source, /最近检测批次/);
});

test('human detection review is saved through the durable review endpoint', () => {
  const start = app.lastIndexOf('v64: quality-center model detection workbench');
  const source = app.slice(start);
  assert.match(source, /window\.markBenchReview64=async function/);
  assert.match(source, /detection-batches\/\$\{encodeURIComponent\(row\.batchId\)\}\/items\/\$\{Number\(row\.itemIndex\?\?index\)\}\/review/);
  assert.match(source, /已保存：/);
});

test('algorithm-version selector groups versions by their owning algorithm', () => {
  const start = app.lastIndexOf('v64: quality-center model detection workbench');
  const source = app.slice(start);
  assert.match(source, /return `算法 · \$\{algorithm\?\.name/);
  assert.match(source, /state\.algorithms/);
});


test('formal algorithm-version detection can explicitly enter the existing reviewed feedback chain', () => {
  const start = app.lastIndexOf('v64: quality-center model detection workbench');
  const source = app.slice(start);
  assert.match(source, /function canSubmitBenchFeedback64\(value\)/);
  assert.match(source, /model_source\|\|''\)\.toLowerCase\(\)==='algorithm_version'/);
  assert.match(source, /window\.openBenchFeedback64=async function/);
  assert.match(source, /deployment-tests\/\$\{encodeURIComponent\(value\.task_id\)\}\/feedback-evidence/);
  assert.match(source, /state\.lastOnlinePrediction63=prediction/);
  assert.match(source, /window\.openPredictionFeedback63\?\.\(\)/);
  assert.match(source, /提交后先进入待复核，不会自动修改数据集或启动训练/);
});

test('quality detection keeps its mounted shell stable across background model refreshes', () => {
  const start = app.lastIndexOf('v64: quality-center model detection workbench');
  const source = app.slice(start);
  assert.match(source, /data-quality-detection-shell="1"/);
  assert.match(source, /function patchBenchModelBrowser64\(side\)/);
  assert.match(source, /select\.dataset\.modelsSignature!==signature/);
  assert.match(source, /if\(!shell\)\{\s*view\.innerHTML=qualityDetectionShell64\(models,ready\)/);
  assert.match(source, /else\{\s*const notices=document\.getElementById\('benchNotices64'\)/);
  assert.match(source, /if\(mounted\)\{\s*window\.renderBenchFileQueue64\(\)/);

  const renderStart = source.indexOf('window.renderQualityDetectionBench64=function renderQualityDetectionBench64()');
  const renderEnd = source.indexOf('\n  };', renderStart);
  const render = source.slice(renderStart, renderEnd);
  assert.equal((render.match(/view\.innerHTML=/g) || []).length, 1);
  const stableBranch = render.slice(render.indexOf('}else{'), render.indexOf('if(mounted)'));
  assert.doesNotMatch(stableBranch, /view\.innerHTML=/);
  assert.doesNotMatch(stableBranch, /renderBenchFileQueue64/);
});

test('quality center renders the reviewed feedback and external-intake panel', () => {
  assert.match(app, /window\.renderOnlineFeedbackPanel63=function/);
  const start = app.lastIndexOf('v64: quality-center model detection workbench');
  const source = app.slice(start);
  assert.match(source, /window\.renderOnlineFeedbackPanel63\?\.\(view\)/);
  assert.match(app, /openExternalFeedbackIntake63/);
  assert.match(app, /线上抽检 \/ 反馈/);
});

test('backend feedback-evidence promotion is explicit, formal-version-only and success-only', () => {
  assert.match(backend, /@app\.post\("\/api\/v64\/projects\/\{project_id\}\/deployment-tests\/\{task_id\}\/feedback-evidence"\)/);
  assert.match(backend, /只有真实检测成功后才能提交抽检反馈/);
  assert.match(backend, /只有正式算法版本检测可以进入抽检反馈/);
  assert.match(backend, /_online_feedback_version_model_sha256\(version\)/);
  assert.match(backend, /source_channel": "quality_center_detection"/);
  assert.match(backend, /"feedback_eligible": True/);
});
