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

test('deployment cache honors TTL and refreshes authoritative artifacts before reuse',()=>{
  const load=owner('  async function loadDeployData(force=false){','  window.loadDeployData=loadDeployData;');
  assert.match(load,/Date\.now\(\)-Number\(cached\.ts\|\|0\)<ttl/);
  assert.match(load,/await refreshDeployArtifactsV39\(\)/);
});

test('deployment polling refreshes artifacts when a conversion enters a successful terminal state',()=>{
  const poll=owner('  async function pollDeployJobs(){','  window.renderDeployCenter=function(){');
  assert.match(poll,/\['done','blocked_by_hardware'\]\.includes\(current\)/);
  assert.match(poll,/if\(artifactChanged\)await refreshDeployArtifactsV39\(\)/);
});

test('deployment artifact page revalidates server truth without manual refresh',()=>{
  const render=owner('  window.renderDeployArtifacts=function(){','  // Add deployment action to algorithm version management.');
  assert.match(render,/deployArtifactsRefreshedAt/);
  assert.match(render,/refreshDeployArtifactsV39\(\)/);
});
