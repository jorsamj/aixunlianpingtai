import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const source=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');

function owner(startMarker,endMarker){
  const start=source.indexOf(startMarker);
  const end=source.indexOf(endMarker,start+startMarker.length);
  assert.ok(start>=0&&end>start,`missing owner ${startMarker}`);
  return source.slice(start,end);
}

test('canonical version history cache is single-flight and authoritative refresh bypasses cache',()=>{
  const history=owner('  const conversionHistoryInflight428=new Map();','  window.loadVersionConversionHistory428=deploymentHistory428;');
  assert.match(history,/cacheKey428\('verdeploy',aid,vid,String\(new URLSearchParams\(query\)\)\)/);
  assert.match(history,/conversionHistoryInflight428\.has\(inflightKey\)/);
  assert.match(history,/\/api\/v42\/projects\/\$\{project\}\/algorithms\/\$\{aid\}\/versions\/\$\{vid\}\/deployments\?\$\{params\}/);
  assert.match(history,/conversionHistoryInflight428\.delete\(inflightKey\)/);
  assert.match(history,/if\(!force\)\{const c=readCache428\(k\);if\(c\)return c\}/);
  assert.match(history,/params=new URLSearchParams\(\{\.\.\.query,force:String\(force\)\}\)/);
  assert.match(history,/if\(!signal&&conversionHistoryInflight428\.has\(inflightKey\)\)/);
  assert.match(history,/conversionHistoryInflight428\.get\(inflightKey\)===task/);
  assert.match(history,/signal:deadlineSignal/);
  assert.match(history,/label:'转换记录读取',signal/);
});

test('canonical version polling replaces a terminal transition so newly committed outputs appear',()=>{
  const poll=owner('  function patchVersionConversionLive428(aid,vid,r){','  window.openVersionConvert428=async function(aid,vid)');
  assert.match(poll,/conversionActive428\(previous\)&&!conversionActive428\(next\)\)return false/);
  assert.match(poll,/deploymentHistory428\(aid,vid,true,conversionHistoryQuery428\(view\),view\.controller\?\.signal\)/);
  assert.match(poll,/else replaceVersionConversionBody428\(aid,vid,next\)/);
  assert.match(poll,/if\(epoch!==view\.epoch\|\|project!==pid\(\)\|\|versionConversionRoot428\(aid,vid\)!==root\)return/);
  assert.match(poll,/rows\.some\(job=>conversionActive428\(job\?\.status\)\)/);
  assert.match(source,/class="convert428-outputs">\$\{deployOutput428\(j\)\}/);
  assert.match(source,/o\.exists&&o\.download_url/);
});

test('canonical conversion resources are fetched live with no HTTP cache and without retired page data',()=>{
  const resources=owner('  async function deployResources428(force=false){','  window.loadVersionConversionHistory428=deploymentHistory428;');
  assert.match(resources,/deployResourcesInflight428/);
  assert.match(resources,/api\('\/api\/v39\/deploy\/resources\?detect_missing=false',\{cache:'no-store',signal\}\)/);
  assert.doesNotMatch(resources,/if\(!force\)\{const c=readCache428/);
  assert.doesNotMatch(resources,/source-models|deploy\/artifacts|deploy\/jobs/);
});
