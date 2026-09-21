import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const source=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');
const styles=readFileSync(new URL('../../static/styles.css',import.meta.url),'utf8');

test('component scan active progress patches a stable shell and uses central polling',()=>{
  const start=source.lastIndexOf("const COMPONENT_SCAN_POLL_KEY='component-scan-v40'");
  const end=source.indexOf('// ============================================================\n// v41:',start);
  assert.ok(start>=0&&end>start);
  const block=source.slice(start,end);
  assert.match(block,/function patchCompProgress\(\)/);
  assert.match(block,/data-component-progress-bar/);
  assert.match(block,/bar\.style\.transform=/);
  assert.match(block,/scaleX/);
  assert.match(block,/PollRegistryRuntime\?\.startTimeout\?\.\(COMPONENT_SCAN_POLL_KEY,'组件检测',callback,650\)/);
  assert.match(block,/if\(state\.page!=='组件检测'\)return null/);
  assert.match(block,/if\(componentScanActive\(r\)\)patchCompProgress\(\);else renderCompBody\(\)/);
  assert.doesNotMatch(block,/setTimeout\(\(\)=>pollComponentScanV40\(id\),650\)/);
  assert.match(styles,/\.component-progress \.progress-bar i\{width:100%;transform-origin:left center;transition:transform/);
});
