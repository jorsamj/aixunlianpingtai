import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const source=readFileSync(new URL('../../static/modules/material-pagination-runtime.js',import.meta.url),'utf8');
const variablesStart=source.indexOf('let statusCountsCache = null;');
const variablesEnd=source.indexOf('let searchTimer = null;',variablesStart);
const functionStart=source.indexOf('async function fetchStatusCounts61(');
const functionEnd=source.indexOf('async function refreshSummary61()',functionStart);
assert.ok(variablesStart>=0&&variablesEnd>variablesStart&&functionStart>=0&&functionEnd>functionStart);

function owner(){
  const responses=[],state={materialSourceFilter61:'all'};
  let project='p1';
  const materialFetch=url=>new Promise(resolve=>responses.push({url,resolve}));
  const code=source.slice(variablesStart,variablesEnd)+'\n'+source.slice(functionStart,functionEnd)
    +'\nreturn {fetch:fetchStatusCounts61,invalidate:invalidateStatusCounts61};';
  const scope=new Function('materialFetch','responseJson','projectId','state',code)(
    materialFetch,value=>value,()=>project,state,
  );
  return {...scope,state,responses,setProject:value=>{project=value}};
}

test('a count response retired by mutation cannot replace a newer status summary',async()=>{
  const ctx=owner();
  const old=ctx.fetch();
  const retired=assert.rejects(old,error=>error.code==='MATERIAL_STATUS_COUNTS_RETIRED');
  ctx.invalidate();
  const newest=ctx.fetch();
  assert.equal(ctx.responses.length,2,'invalidation starts a fresh network read');
  ctx.responses[1].resolve({total:18,annotated:7,unprocessed:11,processed:7});
  assert.equal((await newest).total,18);
  ctx.responses[0].resolve({total:10,annotated:1,unprocessed:9,processed:1});
  await retired;
  assert.deepEqual(await ctx.fetch(),{total:18,annotated:7,unprocessed:11,processed:7});
  assert.equal(ctx.responses.length,2,'only the latest counts are cached');
});

test('source changes fence stale counts and permit fresh per-source totals',async()=>{
  const ctx=owner();
  const old=ctx.fetch();
  const retired=assert.rejects(old,error=>error.code==='MATERIAL_STATUS_COUNTS_RETIRED');
  ctx.state.materialSourceFilter61='source-b';
  const newer=ctx.fetch();
  ctx.responses[1].resolve({total:3});
  assert.equal((await newer).total,3);
  ctx.responses[0].resolve({total:999});
  await retired;
  assert.equal((await ctx.fetch()).total,3);
});
