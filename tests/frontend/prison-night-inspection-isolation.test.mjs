import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const read=p=>readFileSync(new URL('../../'+p,import.meta.url),'utf8');
const app=read('static/app.js'),main=read('static/main.mjs');
const entry=read('static/modules/prison-night-inspection-entry.mjs');
const html=read('static/isolated/prison-night-inspection-demo.html');
const css=read('static/prison-night-inspection-entry.css');
test('standalone large navigation entry follows the collapsible advanced menu',()=>{
  const nav=app.slice(app.indexOf('renderNav=function(){'),app.indexOf('renderNav=function(){')+2700);
  assert.ok(nav.includes('nav-advanced427'));
  assert.ok(nav.indexOf('nav-night-isolated')>nav.indexOf('nav-advanced427'));
  assert.ok(nav.indexOf('nav-footer')>nav.indexOf('nav-night-isolated'));
  assert.match(nav,/setPage\('监所夜间离床研判'\)/);
  assert.match(main,/registerPageOwner\(\s*'监所夜间离床研判'/);
});
test('the imported demo cannot access or pollute the parent DOM, CSS or storage',()=>{
  assert.match(entry,/sandbox="allow-scripts allow-modals"/);
  assert.doesNotMatch(entry,/allow-same-origin|srcdoc|\.contentWindow|postMessage/);
  assert.match(entry,/static\/isolated\/prison-night-inspection-demo\.html/);
  assert.match(html,/夜间离床风险智能研判系统/);
  assert.match(html,/事件中心/);
  assert.match(html,/工作流配置/);
  assert.match(html,/视频算法任务/);
  assert.match(html,/__nightDemoStorage/);
  assert.doesNotMatch(html,/(^|[^\w])localStorage(?:\.|\[)/);
  assert.match(css,/#nightInspectionIsolated iframe/);
  assert.doesNotMatch(entry,/TrainingSubmit|MaterialBatch|PollRegistry|setInterval|setTimeout/);
});
