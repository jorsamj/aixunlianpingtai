import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

test('late Uppy view mount cannot replace a newer Modal view handle',async()=>{
  const source=readFileSync(new URL('../../static/modules/uppy-zip-view.js',import.meta.url),'utf8').replace(/^import .*;\s*$/m,'').replace('export async function','async function');
  const mounts=[],roots=[];
  const mount=()=>new Promise(resolve=>mounts.push(resolve));
  const window={ZipImportRuntime:{getProjectId:()=> 'p'},modal(){const nodes=new Map();roots.push({querySelector:key=>{if(!nodes.has(key))nodes.set(key,{classList:{add(){},remove(){}},replaceChildren(){}});return nodes.get(key)}})}};
  const document={querySelectorAll:()=>roots};
  const open=new Function('mountUppyZipAdapter','window','document',source+';return openUppyZipView;')(mount,window,document);
  const a=open(),b=open();
  const second={uppy:{id:'new'},destroy(){this.destroyed=true}},first={uppy:{id:'old'},destroy(){this.destroyed=true}};
  mounts[1](second);const handle=await b;mounts[0](first);await a;
  assert.equal(window.ZipUppyView,handle);assert.equal(window.ZipUppyView.uppy.id,'new');assert.equal(first.destroyed,true);
});


test('a late entry module cannot reopen a closed chooser or a foreign project',async()=>{
  const source=readFileSync(new URL('../../static/zip-import-bootstrap.mjs',import.meta.url),'utf8').replace(/^import .*;\s*$/m,'').replace("import('./modules/uppy-zip-view.js?v=4226366')",'loadView()');
  for(const change of ['closed','project']){
    let resolve,opened=0;const input={isConnected:true},state={project:{id:'p'}},window={};
    const document={getElementById:()=>input};
    const loadView=()=>new Promise(r=>{resolve=r});
    new Function('installZipImportRuntime','window','state','document','loadView',source)(()=>({}),window,state,document,loadView);
    const pending=window.openUppyZipUpload();
    if(change==='closed')input.isConnected=false;else state.project.id='other';
    resolve({openUppyZipView:()=>{opened++}});await pending;
    assert.equal(opened,0);
  }
});
