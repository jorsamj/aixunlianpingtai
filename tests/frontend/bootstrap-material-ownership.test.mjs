import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const source=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');
const start=source.indexOf(' function apply(s){');
const end=source.indexOf(' window.loadStartupSnapshot413=',start);
assert.ok(start>=0&&end>start,'test executes the real bootstrap apply function');
function applyTo(state,snapshot){
 const apply=new Function('state','window','localStorage','RESTORABLE_PAGES413','rememberCoreView413',
  source.slice(start,end)+';return apply;')(state,{}, {getItem:()=>null,setItem(){}},new Set(),()=>{});
 apply(snapshot);
 return state.images;
}

test('same-project core summary without images preserves the paged material rows',()=>{
 const rows=[{id:'saved-image',annotated:true,box_count:1}];
 assert.equal(applyTo({project:{id:'p'},images:rows},{project:{id:'p'},core_only:true}),rows);
});
test('explicit same-project empty images remains authoritative',()=>{
 const empty=[];
 assert.equal(applyTo({project:{id:'p'},images:[{id:'old'}]},{project:{id:'p'},core_only:true,images:empty}),empty);
});
test('project change without images clears previous project materials',()=>{
 assert.deepEqual(applyTo({project:{id:'old'},images:[{id:'old-image'}]},{project:{id:'new'},core_only:true}),[]);
});
test('initial summary without images starts with an empty material list',()=>{
 assert.deepEqual(applyTo({project:null},{project:{id:'p'},core_only:true}),[]);
});
test('explicit material rows still replace the previous same-project list',()=>{
 const rows=[{id:'new-image'}];
 assert.equal(applyTo({project:{id:'p'},images:[{id:'old-image'}]},{project:{id:'p'},images:rows}),rows);
});
