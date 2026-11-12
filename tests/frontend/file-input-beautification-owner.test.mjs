import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8').replace(/\r\n/g, '\n');

test('render426base page wrapper cannot return', () => {
  assert.equal(app.includes('const render426base=render;'), false);
  assert.equal(
    app.includes("requestAnimationFrame(()=>beautifyFileInputs426(document.getElementById('view')||document))"),
    false,
  );
});

test('post-render cleanup owns file-input beautification', () => {
  assert.equal(app.includes('window.beautifyFileInputs426=beautifyFileInputs426;'), true);
  assert.equal(
    app.includes("function cleanup(root){\n    if(!root||!root.querySelectorAll)return;\n    window.beautifyFileInputs426?.(root);"),
    true,
  );
});

test('modal426 and modal normalization observers stay retired behind ModalContentRuntime', () => {
  assert.equal(app.includes('const modal426=modal;'), false);
  assert.equal(app.includes('requestAnimationFrame(()=>beautifyFileInputs426(layer||document))'), false);
  assert.equal(app.includes('new MutationObserver'), false);
  assert.equal(app.includes('window.ModalContentRuntime=Object.freeze({replace:replaceModalContent});'), true);
  assert.equal(app.includes("if(root.id==='modalBody')window.PostRenderNormalizationRuntime?.apply?.(root);"), true);
  assert.equal(app.includes("window.ModalContentRuntime.replace($('#modalBody'),body);"), true);
});


test('file beautifier excludes business-owned hidden inputs and stays idempotent', async () => {
  const {runInNewContext}=await import('node:vm');
  const body=app.slice(app.indexOf('  function beautifyFileInputs426('),app.indexOf('  window.beautifyFileInputs426='));
  const make=(props={})=>({dataset:{},style:{display:''},hidden:false,classList:{contains:()=>false,add(){}},getAttribute:()=>'',addEventListener(){},insertAdjacentElement(){},...props});
  const plain=make(),hidden=make({hidden:true}),inline=make({style:{display:'none'}}),owned=make({dataset:{file426:'1'}}),platform=make({classList:{contains:c=>c==='hidden-file426',add(){}}});
  const wrappers=[];
  const document={querySelectorAll:()=>[plain,hidden,inline,owned,platform],createElement:()=>({append(){},className:''})};
  plain.insertAdjacentElement=(_,el)=>wrappers.push(el);
  for(const input of [hidden,inline,owned,platform])input.insertAdjacentElement=()=>assert.fail('hidden or business-owned input was decorated');
  const ctx={document};runInNewContext(body+';beautifyFileInputs426();beautifyFileInputs426();',ctx);
  assert.equal(wrappers.length,1);
  assert.equal(plain.dataset.pretty426,'1');
});


test('business-owned scenario mother-model and ZIP resume inputs opt out explicitly',()=>{
  for(const [file,ids] of [
    ['quality-detection-workbench.js',['benchFiles64','benchFolder64']],
    ['resource-discovery.js',['rdMotherModelFile']],
    ['zip-import-runtime.js',['zipResumeFile']],
  ]) {
    const source=fs.readFileSync(new URL('../../static/modules/'+file,import.meta.url),'utf8');
    for(const id of ids)assert.match(source,new RegExp('id="'+id+'" data-file426="1"'));
  }
  assert.match(app,/if\(batchMeta\?\.model_scope!=='scenario'\)patchDeploymentTestProgress\(current,taskId,model\);batchMeta\?\.onProgress\?\.\(current\)/);
});
