import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');
const start=source.indexOf('window.refreshQuality411=async function(){');
const end=source.indexOf('// ---------- annotation overlays',start);
assert.ok(start>=0&&end>start,'execute the original quality refresh owner');

function harness(){
  const view={innerHTML:''},state={page:'质量中心',qualityCenterTab411:'overview'},requests=[],saved=[];
  let project='p1',generation=0;
  const context={
    state,window:{NavigationStability:{action:()=>{const owner=generation;return {isCurrent:()=>generation===owner}}}},
    document:{getElementById:id=>id==='view'?view:null},
    pid:()=>project,qualityTabs411:()=>'<quality-tabs>',qualityHtml411:data=>`<quality-data>${data.id}</quality-data>`,
    qualityKey411:()=>`quality:${project}`,localStorage:{setItem:(key,value)=>saved.push({key,value})},
    api:url=>new Promise((resolve,reject)=>requests.push({url,resolve,reject})),esc:String,
  };
  vm.runInNewContext(source.slice(start,end),context);
  return {view,state,requests,saved,refresh:context.window.refreshQuality411,
    navigate:page=>{generation++;state.page=page},setProject:value=>{project=value}};
}

test('a retired quality GET error cannot replace a newer page',async()=>{
  const owner=harness();
  const pending=owner.refresh();
  owner.navigate('算法列表');owner.view.innerHTML='<algorithm-list>current</algorithm-list>';
  owner.requests[0].reject(Object.assign(new Error('navigation retired'),{code:'PAGE_NAVIGATION_CANCELLED'}));
  await pending;
  assert.equal(owner.view.innerHTML,'<algorithm-list>current</algorithm-list>');
  assert.deepEqual(owner.saved,[]);
});

test('A→B→A and tab switches cannot commit retired quality data or cache',async()=>{
  const owner=harness();
  const old=owner.refresh();
  owner.navigate('算法列表');owner.navigate('质量中心');
  const latest=owner.refresh();
  owner.requests[1].resolve({id:'current'});
  await latest;
  owner.requests[0].resolve({id:'stale'});
  await old;
  assert.match(owner.view.innerHTML,/current/);
  assert.doesNotMatch(owner.view.innerHTML,/stale/);
  assert.equal(owner.saved.length,1);
  assert.match(owner.saved[0].value,/current/);

  const fromOverview=owner.refresh();
  owner.state.qualityCenterTab411='advanced';owner.view.innerHTML='<advanced>current</advanced>';
  owner.requests[2].reject(new Error('old overview failure'));
  await fromOverview;
  assert.equal(owner.view.innerHTML,'<advanced>current</advanced>');
});

test('a current quality error remains visible, while project changes quarantine old results',async()=>{
  const owner=harness();
  const failed=owner.refresh();
  owner.requests[0].reject(new Error('actual network error'));
  await failed;
  assert.match(owner.view.innerHTML,/actual network error/);

  const old=owner.refresh();
  owner.setProject('p2');owner.view.innerHTML='<project-two>current</project-two>';
  owner.requests[1].resolve({id:'project-one'});
  await old;
  assert.equal(owner.view.innerHTML,'<project-two>current</project-two>');
  assert.deepEqual(owner.saved,[]);
});
