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
  assert.match(history,/cacheKey428\('verdeploy',aid,vid\)/);
  assert.match(history,/conversionHistoryInflight428\.has\(inflightKey\)/);
  assert.match(history,/\/api\/v42\/projects\/\$\{pid\(\)\}\/algorithms\/\$\{aid\}\/versions\/\$\{vid\}\/deployments/);
  assert.match(history,/conversionHistoryInflight428\.delete\(inflightKey\)/);
});

test('canonical version polling replaces a terminal transition so newly committed outputs appear',()=>{
  const poll=owner('  function patchVersionConversionLive428(aid,vid,r){','  window.openVersionConvert428=async function(aid,vid)');
  assert.match(poll,/conversionActive428\(previous\)&&!conversionActive428\(next\)\)return false/);
  assert.match(poll,/deploymentHistory428\(aid,vid,true\)/);
  assert.match(poll,/else replaceVersionConversionBody428\(aid,vid,next\)/);
  assert.match(source,/class="convert428-outputs">\$\{deployOutput428\(j\)\}/);
  assert.match(source,/o\.exists&&o\.download_url/);
});

test('canonical conversion resource reads are cached and single-flight without loading retired page data',()=>{
  const resources=owner('  async function deployResources428(force=false){','  window.loadVersionConversionHistory428=deploymentHistory428;');
  assert.match(resources,/deployResourcesInflight428/);
  assert.match(resources,/api\('\/api\/v39\/deploy\/resources'\)/);
  assert.doesNotMatch(resources,/source-models|deploy\/artifacts|deploy\/jobs/);
});
